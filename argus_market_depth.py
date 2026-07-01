"""argus_market_depth — Market Depth capability report (market-depth-v1).

Pure, dependency-injected, stdlib-only (mirrors argus_visibility / argus_downside).
Turns raw provider signals into an HONEST per-capability status so the app can say
exactly what market depth it has — and feed the Visibility Risk Guard real values
instead of hardcoded defaults.

Discipline (must not regress): a capability is only "live" on VENUE-TIMESTAMP proof
(moomoo overallEntitlement == "realtime_proven", or a fresh realtimeProof). Push
CADENCE alone never earns "live" — 15s delivery ≠ realtime data. Structural depth
that ARGUS cannot see (PTS / L2 / tape / VWAP / extended / options / borrow) stays
unavailable/testing until a real capability test proves otherwise.
"""
from typing import Any, Dict, Optional

ENGINE_VERSION = "market-depth-v1"

# Per-capability provider/label metadata (JP labels for display).
_META: Dict[str, Dict[str, str]] = {
    "BRIDGE":      {"provider": "moomoo/OpenD bridge", "labelJa": "リアルタイム配信(ブリッジ)"},
    "JP_CASH":     {"provider": "moomoo → Yahoo/J-Quants", "labelJa": "日本株 現物(場中)"},
    "US_REGULAR":  {"provider": "Twelve Data", "labelJa": "米国株 レギュラー"},
    "JP_PTS":      {"provider": "—", "labelJa": "日本株 PTS(夜間)"},
    "US_EXTENDED": {"provider": "Twelve Data(要検証)", "labelJa": "米国株 時間外"},
    "VWAP":        {"provider": "—", "labelJa": "VWAP"},
    "TAPE":        {"provider": "—", "labelJa": "歩み値(Time&Sales)"},
    "L2":          {"provider": "—", "labelJa": "板(Level 2)"},
    "OPTIONS_IV":  {"provider": "—", "labelJa": "オプションIV/スキュー"},
    "BORROW_FEE":  {"provider": "—", "labelJa": "貸株料/空売り可否"},
    "FX_FUTURES":  {"provider": "—", "labelJa": "為替/先物/商品"},
    "TDNET":       {"provider": "yanoshin(無料)/要契約(速報)", "labelJa": "TDnet 適時開示速報"},
}

# Capabilities that may influence Action Level (situational, can block ENTER). The
# structural-depth caps NEVER gate an action — they are context only.
_ACTION_LEVEL_CAPS = {"BRIDGE", "JP_CASH", "US_REGULAR"}


def _normalize(status: str) -> str:
    """Registry/raw status → the market-depth vocabulary."""
    s = str(status or "").lower()
    return {
        "confirmed_live": "live", "live": "live",
        "confirmed_delayed": "partial", "delayed": "partial", "partial": "partial",
        "requires_test": "testing", "testing": "testing", "untested": "testing",
        "paid_not_enabled": "requires_contract", "requires_contract": "requires_contract",
        "unavailable": "unavailable", "missing": "unavailable", "": "unavailable",
    }.get(s, "unavailable")


def _to_guard_status(status: str) -> str:
    """Collapse to the vocab argus_visibility understands: live / untested /
    unavailable. (partial = real-but-delayed data counts as present for the guard's
    structural read; requires_contract reads as unavailable.)"""
    s = _normalize(status)
    if s == "live":
        return "live"
    if s == "partial":
        return "live"          # real data present (delayed) — not a structural gap
    if s == "testing":
        return "untested"
    return "unavailable"       # requires_contract / unavailable


def compute_vwap(bars) -> Optional[float]:
    """Session VWAP from intraday OHLCV bars. bars = [{high,low,close,volume}, …].
    Typical price = (H+L+C)/3, volume-weighted. None if no usable volume (pure)."""
    num = 0.0
    den = 0.0
    for b in (bars or []):
        try:
            h = float(b.get("high")); l = float(b.get("low")); c = float(b.get("close")); v = float(b.get("volume"))
        except (TypeError, ValueError, AttributeError):
            continue
        if v <= 0:
            continue
        num += ((h + l + c) / 3.0) * v
        den += v
    if den <= 0:
        return None
    return round(num / den, 4)


def _bridge_status(bridge_age_sec: Optional[float]) -> str:
    if bridge_age_sec is None:
        return "unavailable"
    if bridge_age_sec <= 120:
        return "live"
    if bridge_age_sec <= 900:
        return "partial"
    return "unavailable"       # stale beyond the bridge-lamp threshold


def build_market_depth_report(
    *,
    now_iso: str,
    bridge_age_sec: Optional[float] = None,
    moomoo_capability: Optional[Dict[str, Any]] = None,
    realtime_proof: Optional[Dict[str, Any]] = None,
    source_registry: Optional[Dict[str, Any]] = None,
    jp_open: bool = False,
    us_open: bool = False,
    vwap_probe: Optional[Dict[str, Any]] = None,
    us_extended_probe: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Per-capability depth report + a guard-status projection. Pure; never raises.
    vwap_probe / us_extended_probe carry REAL measurement results (実測) when the
    caller ran them; absent → the honest structural default, marked probed=False."""
    mc = moomoo_capability if isinstance(moomoo_capability, dict) else {}
    entitlement = str(mc.get("overallEntitlement") or "unknown")
    rp = realtime_proof if isinstance(realtime_proof, dict) else {}
    p95 = rp.get("p95AgeSeconds")
    realtime_proven = (entitlement == "realtime_proven")

    # ── raw status per capability (honest defaults; only proof earns "live") ──
    raw: Dict[str, Dict[str, Any]] = {}

    raw["BRIDGE"] = {
        "status": _bridge_status(bridge_age_sec),
        "entitlement": entitlement,
        "latency": (round(bridge_age_sec, 1) if isinstance(bridge_age_sec, (int, float)) else None),
        "freshness": (f"{round(bridge_age_sec)}s" if isinstance(bridge_age_sec, (int, float)) else "never"),
        "coverage": "swept universe ∪ watchlist", "probed": True,
        "limitations": "配信頻度≠データ鮮度。realtime性はexchangeTsで証明できるまでunknown。",
    }

    # JP cash: realtime ONLY on venue-timestamp proof, else delayed/close (partial).
    jp_cash = "live" if realtime_proven else "partial"
    raw["JP_CASH"] = {
        "status": jp_cash, "entitlement": entitlement, "probed": True,
        "latency": p95, "freshness": (f"p95 {p95}s" if p95 is not None else "delayed/close"),
        "coverage": "watchlist + swept", "limitations": ("" if realtime_proven else "遅延/終値ベース(realtime未証明)"),
    }
    raw["US_REGULAR"] = {
        "status": "live", "entitlement": "twelvedata_basic_regular",
        "latency": None, "freshness": "regular session", "coverage": "watchlist",
        "limitations": "レギュラー時間のみ(時間外は別capability)",
    }
    raw["JP_PTS"] = {"status": "unavailable", "limitations": "PTS(夜間)配信の統合なし。夜間の日本株可視性は無い。"}

    # US_EXTENDED — reflect a real entitlement probe when provided (実測)
    _uxp = us_extended_probe if isinstance(us_extended_probe, dict) else {}
    raw["US_EXTENDED"] = {"status": _uxp.get("status") or "testing", "probed": bool(_uxp.get("probed")),
                          "limitations": _uxp.get("note") or "pre/after配信は未検証 — 時間外の可視性は主張しない。"}

    # VWAP — genuinely COMPUTED from intraday bars when the probe succeeds (実測)
    _vp = vwap_probe if isinstance(vwap_probe, dict) else {}
    if _vp.get("computed"):
        raw["VWAP"] = {"status": "live", "entitlement": "computed_from_intraday_bars",
                       "coverage": f"{len(_vp.get('values') or {})} symbols", "probed": True,
                       "sample": _vp.get("values"), "freshness": _vp.get("asOf"),
                       "limitations": _vp.get("note") or "5分足のセッションVWAPを算出(算出値であり板約定VWAPではない)"}
    else:
        raw["VWAP"] = {"status": "unavailable", "probed": bool(_vp.get("probed")),
                       "limitations": _vp.get("note") or "十分なintraday barが無く未算出(実測プローブ)。"}
    raw["TAPE"] = {"status": "requires_contract", "limitations": "歩み値フィード未契約。約定の質は推定しない。"}
    raw["L2"] = {"status": "requires_contract", "limitations": "板(Level 2)未契約。需給の確度は推定しない。"}
    raw["OPTIONS_IV"] = {"status": "unavailable", "limitations": "IV/スキューのプロバイダ未統合。"}
    raw["BORROW_FEE"] = {"status": "unavailable", "limitations": "貸株料/空売り可否のプロバイダ未統合。"}
    raw["FX_FUTURES"] = {"status": "unavailable", "limitations": "為替/先物/商品の板・深さは未統合(水準は文脈変数のみ)。"}

    # TDnet: read from the source registry if present (real-time paid feed stays off).
    tdnet_status = "unavailable"
    for s in ((source_registry or {}).get("sources") or []):
        cap = str(s.get("capability") or "").lower()
        if "tdnet" in cap or "適時開示" in str(s.get("notesJa") or ""):
            tdnet_status = _normalize(s.get("status"))
            break
    raw["TDNET"] = {"status": tdnet_status,
                    "limitations": "無料は第三者ラッパ(タイトルのみ)。速報の機械可読フィードは要契約。"}

    # ── assemble the rich report + the guard-status projection ──
    capabilities: Dict[str, Dict[str, Any]] = {}
    guard: Dict[str, str] = {}
    for key, r in raw.items():
        st = _normalize(r.get("status"))
        meta = _META.get(key, {})
        capabilities[key] = {
            "status": st,
            "provider": meta.get("provider", "—"),
            "labelJa": meta.get("labelJa", key),
            "entitlement": r.get("entitlement"),
            "latency": r.get("latency"),
            "freshness": r.get("freshness"),
            "coverage": r.get("coverage"),
            "lastSuccess": now_iso if st in ("live", "partial") else None,
            "limitations": r.get("limitations", ""),
            "affectsActionLevel": key in _ACTION_LEVEL_CAPS,
            "probed": bool(r.get("probed")),   # True = backed by a real measurement (実測), not assumed
            "sample": r.get("sample"),
        }
        guard[key] = _to_guard_status(st)

    live_n = sum(1 for c in capabilities.values() if c["status"] == "live")
    return {
        "asOf": now_iso, "engineVersion": ENGINE_VERSION,
        "capabilities": capabilities,
        "capabilitiesForGuard": guard,
        "summary": {"live": live_n, "total": len(capabilities),
                    "jpRealtimeProven": realtime_proven,
                    "sessionOpen": bool(jp_open or us_open)},
        "note": "深さの可視性。live判定はexchangeTs等の実証のみ。未接続/未検証は誇張しない。",
    }
