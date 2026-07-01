"""argus_visibility — Visibility Risk Guard (visibility-guard-v1).

Pure, dependency-injected, stdlib-only (mirrors argus_downside / argus_attribution).
It aggregates every data-visibility signal ARGUS already exposes into one honest
verdict so the app can (a) surface what it CANNOT see, (b) cap confidence and block
ENTER/ADD when the tape it needs isn't visible, and (c) never let "no alert" read as
"safe".

Design principle — STRUCTURAL vs SITUATIONAL (this is the whole point):

  STRUCTURAL gaps are permanent today (PTS / L2 / tape / VWAP / US-extended /
  FX-futures / paid TDnet are simply not connected). They are ALWAYS true, so if they
  turned the banner red or blocked ENTER every day, the warning would be permanent —
  which desensitises the owner and is itself a broken state. So structural gaps only
  populate `limitations` + a muted `coverageLineJa`; they never drop visibilityLevel,
  never block actions, never cap confidence.

  SITUATIONAL degradation is transient and actionable (the moomoo bridge went stale
  DURING a session, the regime read is a held-over stale copy, the AI budget stopped,
  realtime is unproven). THESE drop visibilityLevel, may block ENTER, cap confidence,
  and raise a prominent warning.

Nothing here performs I/O, trades, or claims certainty. Decision-support only.
"""

from typing import Any, Dict, List, Optional

ENGINE_VERSION = "visibility-guard-v1"

# Calibration stages considered "proven enough" to NOT cap confidence. Anything
# below regime_level (burn_in / early_signal / provisional) is still unproven and
# caps the hero confidence — ARGUS must not look more certain than its record permits.
_MATURE_CAL_STAGES = {"regime_level", "mature", "reliable", "validation"}

# Market-depth capabilities ARGUS would like to see. Values are the honest current
# status; a later Market-Depth capability test (Phase D) overrides these with proof.
# "live" = proven; anything else is a structural gap surfaced as a limitation.
DEFAULT_CAPABILITIES: Dict[str, str] = {
    "JP_CASH": "live",          # regular-session JP cash prices (moomoo / Yahoo close)
    "US_REGULAR": "live",       # regular-session US equities (Twelve Data)
    "JP_PTS": "unavailable",    # JP proprietary/after-hours (PTS) — not connected
    "US_EXTENDED": "untested",  # US pre/after-market — untested, do not claim
    "L2": "unavailable",        # order book / depth
    "TAPE": "unavailable",      # time-and-sales
    "VWAP": "unavailable",      # volume-weighted average price
    "FX_FUTURES": "unavailable",# FX / futures / commodities depth
    "TDNET": "unavailable",     # paid TDnet real-time disclosure feed
    "OPTIONS_IV": "unavailable",# options IV / skew
    "BORROW_FEE": "unavailable",# borrow fee / short availability
}

# Structural (depth) capabilities checked in the always-on context loop.
_STRUCTURAL_CAPS = ("JP_PTS", "US_EXTENDED", "L2", "TAPE", "VWAP", "FX_FUTURES", "TDNET",
                    "OPTIONS_IV", "BORROW_FEE")

# Human labels (JP) for the structural coverage line — short, calm.
_CAP_LABEL_JA: Dict[str, str] = {
    "JP_PTS": "PTS(夜間)", "US_EXTENDED": "米時間外", "L2": "板",
    "TAPE": "歩み値", "VWAP": "VWAP", "FX_FUTURES": "為替/先物", "TDNET": "TDnet速報",
    "OPTIONS_IV": "オプションIV", "BORROW_FEE": "貸株料",
}
# Capabilities we surface in the muted "監視の穴" line when not live (the ones the
# owner most plausibly assumes are covered). Ordered for a readable line.
_COVERAGE_LINE_CAPS = ["JP_PTS", "L2", "TAPE", "VWAP", "US_EXTENDED"]

# confidenceCap implied by a situational reason code (min wins). Aligns with the
# app's existing 0.60 partial-data cap so behaviour stays consistent.
_CAP_BY_CODE: Dict[str, float] = {
    "CALIBRATION_BURN_IN": 0.60,
    "REGIME_HELD_STALE": 0.60,
    "BRIDGE_STALE": 0.55,
    "BRIDGE_NEVER": 0.55,
    "REALTIME_UNPROVEN": 0.55,
    "AI_BUDGET_STOPPED": 0.60,
}

_WARN_JA: Dict[str, str] = {
    "BRIDGE_STALE": "リアルタイム配信(moomooブリッジ)が場中に停滞しています。ザラ場の値動き・入りの精度は信用しないでください。",
    "BRIDGE_NEVER": "リアルタイム配信(moomooブリッジ)が未接続です。価格は遅延/終値ベースです。",
    "REALTIME_UNPROVEN": "リアルタイム性が未証明です(配信頻度≠鮮度)。板・歩み値の裏取りはできません。",
    "REGIME_HELD_STALE": "地合い判定は前回のフル評価を保持表示中です。最新の確定ではありません。",
    "AI_BUDGET_STOPPED": "AI判定が予算上限で停止中です。現在はルール暫定の判断です。",
}


def _cap_status(caps: Optional[Dict[str, str]], key: str) -> str:
    src = caps if isinstance(caps, dict) else DEFAULT_CAPABILITIES
    return str(src.get(key, DEFAULT_CAPABILITIES.get(key, "unavailable")))


def build_visibility_guard(
    *,
    now_iso: str,
    system_health: Optional[Dict[str, Any]] = None,
    capabilities: Optional[Dict[str, str]] = None,
    bridge_age_sec: Optional[float] = None,
    jp_open: bool = False,
    us_open: bool = False,
    moomoo_overall_entitlement: Optional[str] = None,
    regime_held_over_min: Optional[float] = None,
    calibration_stage: Optional[str] = None,
    decision_value_phase: Optional[str] = None,
) -> Dict[str, Any]:
    """Aggregate visibility signals → the guard verdict. Pure; never raises on
    partial inputs (missing signal = treated as unknown, not as coverage)."""
    reason_codes: List[str] = []
    warnings: List[Dict[str, str]] = []
    limitations: List[str] = []

    # ── STRUCTURAL market-depth gaps (always-on context; never alarming) ──
    missing_depth: List[str] = []
    for key in _STRUCTURAL_CAPS:
        st = _cap_status(capabilities, key)
        if st == "live":
            continue
        code = f"{key}_UNAVAILABLE" if st in ("unavailable", "requires_contract", "missing") else f"{key}_UNTESTED"
        reason_codes.append(code)
        label = _CAP_LABEL_JA.get(key, key)
        if key == "US_EXTENDED" and st == "untested":
            limitations.append(f"{label}: 未検証(TESTING) — 時間外の可視性は主張しません")
        else:
            limitations.append(f"{label}: 未接続 — この情報は見えていません")
        if key in _COVERAGE_LINE_CAPS:
            missing_depth.append(label)

    coverage_line_ja = ""
    if missing_depth:
        coverage_line_ja = (
            "監視の穴: " + "・".join(missing_depth)
            + "は未接続です。ARGUSが検知していないことは安全を意味しません。"
        )

    # ── SITUATIONAL degradation (transient; drops level / caps / blocks / warns) ──
    lamps = {}
    overall_health = None
    if isinstance(system_health, dict):
        overall_health = system_health.get("overall")
        for lp in (system_health.get("lamps") or []):
            if isinstance(lp, dict) and lp.get("id"):
                lamps[str(lp["id"])] = str(lp.get("status") or "")

    session_open = bool(jp_open or us_open)

    # moomoo bridge freshness (mirrors the existing bridge lamp threshold: 900s).
    if bridge_age_sec is None:
        # No bridge ever seen. Only situational if a session is open (else we're just
        # on delayed/close data off-hours, which is normal — not a degradation).
        if session_open:
            reason_codes.append("BRIDGE_NEVER")
            warnings.append({"code": "BRIDGE_NEVER", "messageJa": _WARN_JA["BRIDGE_NEVER"]})
    elif session_open and bridge_age_sec > 900:
        reason_codes.append("BRIDGE_STALE")
        warnings.append({"code": "BRIDGE_STALE", "messageJa": _WARN_JA["BRIDGE_STALE"]})

    if str(moomoo_overall_entitlement or "").lower() == "unknown" and session_open:
        reason_codes.append("REALTIME_UNPROVEN")
        warnings.append({"code": "REALTIME_UNPROVEN", "messageJa": _WARN_JA["REALTIME_UNPROVEN"]})

    if regime_held_over_min not in (None, 0, False):
        reason_codes.append("REGIME_HELD_STALE")
        warnings.append({"code": "REGIME_HELD_STALE", "messageJa": _WARN_JA["REGIME_HELD_STALE"]})

    # Health lamps: prices/bridge stopped is a hard degradation; ai_budget stopped
    # means the read is rule-only.
    prices_stopped = any(
        lamps.get(k) == "stopped" for k in ("prices_jp", "prices_us", "prices", "bridge")
    )
    if lamps.get("ai_budget") == "stopped":
        reason_codes.append("AI_BUDGET_STOPPED")
        warnings.append({"code": "AI_BUDGET_STOPPED", "messageJa": _WARN_JA["AI_BUDGET_STOPPED"]})

    # Calibration not-yet-proven caps confidence (accuracy is only "proven" at the
    # mature regime_level stage, 120+ scored days). burn_in / early_signal /
    # provisional all still cap. Context, not a banner (it is persistent).
    if str(calibration_stage or "").lower() not in _MATURE_CAL_STAGES:
        reason_codes.append("CALIBRATION_BURN_IN")
        limitations.append(f"自己採点は較正中(stage={calibration_stage or 'unknown'}) — 精度は証明済みではありません")
    dv = str(decision_value_phase or "").lower()
    if dv and ("shadow" in dv or "phase1" in dv or "engine" in dv or "no_shadow" in dv):
        reason_codes.append("DV_SHADOW_ONLY")
        limitations.append("Decision Valueはシャドー記録段階 — 優位性(edge)は未証明です")

    # ── visibilityLevel (SITUATIONAL only) ──
    if prices_stopped or "BRIDGE_STALE" in reason_codes or "BRIDGE_NEVER" in reason_codes:
        visibility_level = "minimal"
    elif any(c in reason_codes for c in ("REGIME_HELD_STALE", "AI_BUDGET_STOPPED", "REALTIME_UNPROVEN")):
        visibility_level = "reduced"
    else:
        visibility_level = "full"

    # ── blockedActions (SITUATIONAL only) — intraday entry precision untrustworthy ──
    blocked: List[str] = []
    if "BRIDGE_STALE" in reason_codes or "BRIDGE_NEVER" in reason_codes or prices_stopped:
        blocked = ["ENTER"]

    # ── confidenceCap = min over caps implied by present codes ──
    caps = [_CAP_BY_CODE[c] for c in reason_codes if c in _CAP_BY_CODE]
    confidence_cap = min(caps) if caps else None
    if confidence_cap is not None:
        confidence_cap = max(0.0, min(1.0, round(confidence_cap, 2)))

    return {
        "asOf": now_iso,
        "engineVersion": ENGINE_VERSION,
        "visibilityLevel": visibility_level,
        "blockedActions": blocked,
        "warnings": warnings,
        "limitations": limitations,
        "structuralGapCount": len(missing_depth),
        "coverageLineJa": coverage_line_ja,
        "confidenceCap": confidence_cap,
        "reasonCodes": reason_codes,
        "healthOverall": overall_health,
    }
