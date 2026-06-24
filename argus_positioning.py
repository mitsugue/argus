"""ARGUS — §14 Institutional Positioning aggregator (pure, deterministic, honest).

SLOW positioning data (FINRA short interest, JPX/EDINET/SEC disclosed holdings,
JSF lending) moves on a multi-day-to-quarterly delay and is about BALANCES; FAST
market flow (moomoo流, 短期の値動き/出来高, 相対弱さ) is intraday and is about
TRANSACTIONS. This module fuses the two into ONE uncalibrated read of what the
positioning shift *might* be — never a calibrated probability, never a named
trader, never a trade instruction.

Hard epistemic + safety rules (mirrors argus_attribution / argus_research_mesh):
  * short-sale VOLUME is NEVER short INTEREST (出来高≠残高). 強調して明示する。
  * No institution is named as the trader unless an OFFICIAL disclosure identity
    is supplied (`name_trader`). intradayのフローから個人/機関は特定できない。
  * The 7 positioning probabilities always SUM TO 1.0; `unknown` stays a real,
    material outcome whenever the evidence is thin. Bad/missing input → unknown=1.0.
  * calibrationStatus is always 'uncalibrated' — we never claim a calibrated number.
  * No trade instruction, ever. Decision-support only.
Stdlib-only; may import argus_research_mesh (rights/institution registry) but does
NOT reach into scanner.py or any runtime. All functions are PURE (inputs only).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import argus_research_mesh as M

SCHEMA = "positioning-v1"
CALIB = "uncalibrated"  # 校正されていない発見的推定。確率を校正済みと称さない。

# The 7 mutually-exclusive positioning outcomes we spread probability mass over.
POSITIONING_OUTCOMES = (
    "newLongAccumulation",   # 新規の買い建て・集積
    "longLiquidation",       # 既存ロングの手仕舞い
    "newShortBuildup",       # 新規の空売り積み増し
    "shortCovering",         # 買い戻し(空売りの解消)
    "distribution",          # 分配(上値での売り抜け・売り渡し)
    "retailNoise",           # 個人主体のノイズ的売買
    "unknown",               # 不明(証拠が薄いときは必ず残す)
)

# ── §14 source descriptors ──────────────────────────────────────────────────
# SLOW = balance/disclosure data (delayed, about 建玉/保有 = positionOrVolume:'position').
# FAST = intraday flow data (about 出来高/フロー = positionOrVolume mostly 'volume').
# Each template carries the honest semantics so the caller can never mistake a
# delayed balance for live flow, or short-sale VOLUME for short INTEREST.
SLOW_SOURCES: Dict[str, Dict[str, Any]] = {
    "finra_short_interest": {
        "labelJa": "FINRA 空売り残高(SI)", "publicationDelay": "月2回・数日遅延",
        "coverage": "US上場・集計", "threshold": "報告対象全銘柄",
        "identityAvailable": False, "positionOrVolume": "position", "freshness": "delayed",
        "noteJa": "建玉(残高)。リアルタイムでも投資家特定でもない。"},
    "jpx_disclosed_short": {
        "labelJa": "JPX 空売り残高報告", "publicationDelay": "閾値超のみ・遅延",
        "coverage": "JP上場・閾値超のみ", "threshold": "残高割合0.5%超",
        "identityAvailable": True, "positionOrVolume": "position", "freshness": "delayed",
        "noteJa": "報告閾値を超えた建玉のみ・遅延。intradayのフローではない。"},
    "edinet_large_holding": {
        "labelJa": "EDINET 大量保有報告", "publicationDelay": "提出後・遅延",
        "coverage": "JP上場・5%超等", "threshold": "保有割合5%超",
        "identityAvailable": True, "positionOrVolume": "position", "freshness": "delayed",
        "noteJa": "大量保有/変更報告。提出義務者は識別できるが、intradayの売買ではない。"},
    "sec_form4_13d_13g_13f": {
        "labelJa": "SEC Form4/13D/13G/13F", "publicationDelay": "提出遅延・四半期等",
        "coverage": "US上場・閾値/インサイダー", "threshold": "5%超/役員等/四半期保有",
        "identityAvailable": True, "positionOrVolume": "position", "freshness": "delayed",
        "noteJa": "遅延開示。提出者は識別できるが、intradayのフロー追跡ではない。"},
    "jsf_lending": {
        "labelJa": "日証金 貸借残高", "publicationDelay": "日次・翌営業日",
        "coverage": "JP貸借銘柄", "threshold": "貸借取引対象",
        "identityAvailable": False, "positionOrVolume": "position", "freshness": "delayed",
        "noteJa": "信用需給の目安(残高)。個人特定は不可。"},
}

FAST_SOURCES: Dict[str, Dict[str, Any]] = {
    "finra_daily_short_volume": {
        "labelJa": "FINRA 日次空売り出来高", "publicationDelay": "翌日・集計値",
        "coverage": "US上場・日次集計", "threshold": "報告対象全約定",
        "identityAvailable": False, "positionOrVolume": "volume", "freshness": "daily",
        "noteJa": "★出来高であり空売り残高(SI)ではない。建玉や投資家特定は不可。"},
    "moomoo_flow": {
        "labelJa": "moomoo 高速フロー", "publicationDelay": "ほぼリアルタイム/15分遅延",
        "coverage": "対象銘柄・intraday", "threshold": "なし(連続)",
        "identityAvailable": False, "positionOrVolume": "volume", "freshness": "intraday",
        "noteJa": "intradayの資金流向の目安。投資家の特定はできない。"},
    "price_volume_intraday": {
        "labelJa": "短期の値動き/出来高", "publicationDelay": "intraday",
        "coverage": "対象銘柄・intraday", "threshold": "なし(連続)",
        "identityAvailable": False, "positionOrVolume": "volume", "freshness": "intraday",
        "noteJa": "値動き・出来高比・相対弱さ。フロー方向の推定のみ。"},
}

# Default descriptor template — every field present and HONEST when unknown.
_DEFAULT_DESCRIPTOR = {
    "asOf": None, "publicationDelay": "unknown", "coverage": "unknown",
    "threshold": "unknown", "identityAvailable": False,
    "positionOrVolume": "volume", "freshness": "unknown",
}


def describe_source(source_id: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Normalize a positioning source into a descriptor with the §14 fields.

    Pulls the honest defaults from SLOW_SOURCES / FAST_SOURCES, then overlays any
    concrete values supplied in `payload` (e.g. an actual asOf timestamp). Unknown
    sources fall back to a fully-honest default (no false freshness/identity). The
    accessClass from the research-mesh rights registry is attached for downstream
    enforcement.
    """
    payload = payload or {}
    template = SLOW_SOURCES.get(source_id) or FAST_SOURCES.get(source_id) or {}
    tier = ("slow" if source_id in SLOW_SOURCES
            else "fast" if source_id in FAST_SOURCES else "unknown")

    desc: Dict[str, Any] = dict(_DEFAULT_DESCRIPTOR)
    desc.update(template)               # honest source semantics
    # Overlay only the recognized descriptor fields from the payload (caller data).
    for k in ("asOf", "publicationDelay", "coverage", "threshold",
              "identityAvailable", "positionOrVolume", "freshness"):
        if k in payload and payload[k] is not None:
            desc[k] = payload[k]

    rights = M.source_rights(payload.get("rightsSourceId", source_id))
    desc.update({
        "sourceId": source_id, "tier": tier,
        "labelJa": template.get("labelJa", source_id),
        "noteJa": template.get("noteJa", "出所の意味論は未確認。"),
        "accessClass": rights["accessClass"],
        # short-sale VOLUME ≠ short INTEREST 警告を出来高系では常に添える。
        "volumeVsInterestNote": (short_volume_guard(template.get("labelJa", source_id))
                                 if desc["positionOrVolume"] == "volume" else None),
    })
    return desc


def short_volume_guard(label: str = "") -> str:
    """Return the standing clarification that short-sale VOLUME is NOT outstanding
    short INTEREST. Both words appear verbatim so any caller/UI/test can rely on it.
    出来高(volume)は約定の量、残高(interest)は建玉。別物。"""
    prefix = f"{label}: " if label else ""
    return (prefix + "short-sale VOLUME (出来高) は outstanding short INTEREST (空売り残高) "
            "ではない。出来高は当日の約定量、残高(short interest)は積み上がった建玉であり、"
            "両者を同一視してはならない。")


def name_trader(disclosure: Optional[Dict[str, Any]]) -> Optional[str]:
    """Return an institution name ONLY when an OFFICIAL disclosure carries an
    identity; otherwise None. NEVER guesses a trader from flow/volume.

    Requires disclosure.get('official') is True AND a usable name. If an
    institutionId resolves in the research-mesh watchlist we return its canonical
    name; otherwise we echo the disclosed name verbatim. No identity, no name.
    """
    if not isinstance(disclosure, dict):
        return None
    if disclosure.get("official") is not True:
        return None  # 公式開示でなければ決して名指ししない
    iid = disclosure.get("institutionId")
    if iid and iid in M.INSTITUTIONS:
        return M.INSTITUTIONS[iid]["canonicalName"]
    name = (disclosure.get("name") or disclosure.get("institutionName") or "").strip()
    return name or None


# ── §14 aggregation: SLOW positioning vs FAST flow → one uncalibrated read ────
def _num(v: Any) -> Optional[float]:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def aggregate_positioning(signals: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Fuse SLOW positioning + FAST flow signals into an uncalibrated probability
    spread over the 7 outcomes. The probabilities ALWAYS sum to 1.0.

    Deterministic heuristic (intentionally conservative — `unknown` stays material):
      * heavy short-sale VOLUME + price down → tilt newShortBuildup / distribution,
        but the volume guard keeps `unknown` high (出来高≠残高 だから建玉断定不可),
      * short-covering bounce (price up on prior-heavy short + outflow) → shortCovering,
      * outflow + price down → longLiquidation / distribution,
      * inflow + price up → newLongAccumulation,
      * quiet tape → retailNoise.
    On bad/missing input the whole mass goes to `unknown` (=1.0). NEVER names a
    trader; identifiedTrader is None unless an OFFICIAL disclosure is supplied.
    """
    # Bad / missing input → honest all-unknown.
    if not isinstance(signals, dict) or not signals:
        return _unknown_result("入力が空または不正のため、ポジショニングは不明(unknown=1.0)。")

    chg = _num(signals.get("changePct"))
    vol_ratio = _num(signals.get("volRatio"))
    short_vol_ratio = _num(signals.get("shortVolumeRatio"))   # 出来高に占める空売り出来高の比
    flow = _num(signals.get("flowRatio"))
    prior_flow = _num(signals.get("priorFlowRatio"))
    prior_short_interest_high = bool(signals.get("priorShortInterestHigh"))
    rel_weak = bool(signals.get("relativeWeakness"))

    # Count how much FAST evidence we actually have (drives the unknown floor).
    have = sum(1 for v in (chg, vol_ratio, short_vol_ratio, flow) if v is not None)
    if have == 0:
        return _unknown_result("数値シグナルが無く、ポジショニングは不明(unknown=1.0)。")

    down = chg is not None and chg < 0
    up = chg is not None and chg > 0
    heavy = vol_ratio is not None and vol_ratio >= 1.3
    heavy_short_vol = short_vol_ratio is not None and short_vol_ratio >= 0.45
    outflow = flow is not None and flow < 0
    inflow = flow is not None and flow > 0
    flow_reversed_down = (flow is not None and prior_flow is not None
                          and prior_flow > 0 and flow < 0)

    raw = {k: 0.0 for k in POSITIONING_OUTCOMES}

    # heavy short-sale VOLUME + price down → tilt newShortBuildup / distribution,
    # but VOLUME≠INTEREST so we never let this collapse unknown.
    if down and heavy_short_vol:
        raw["newShortBuildup"] += 1.0
        raw["distribution"] += 0.5
    if down and heavy and outflow:
        raw["distribution"] += 1.2
    if down and outflow:
        raw["longLiquidation"] += 1.0
    if down and flow_reversed_down:
        raw["longLiquidation"] += 0.5
    if down and rel_weak and not outflow:
        raw["newShortBuildup"] += 0.6

    # short-covering bounce: price UP, prior heavy short / outflow on the bid → covering.
    if up and (prior_short_interest_high or (heavy_short_vol and outflow)):
        raw["shortCovering"] += 1.2
    if up and inflow:
        raw["newLongAccumulation"] += 1.1
    if up and outflow:                        # 上昇＋資金流出 = 買い戻し色
        raw["shortCovering"] += 0.6

    # quiet tape → retail noise.
    if not heavy and (chg is None or abs(chg) < 1.0):
        raw["retailNoise"] += 0.5

    # ── unknown floor ── keep `unknown` MATERIAL when evidence is weak. Heavy
    # short-VOLUME never resolves to a confident short-INTEREST build, so the
    # volume-only path keeps a meaningful unknown share.
    unknown = 0.6 if have >= 3 else 1.6 if have == 1 else 1.0
    if heavy_short_vol and not prior_short_interest_high:
        # 出来高は建玉ではない。残高の裏取りが無い限り不明を厚めに残す。
        unknown += 0.6
    raw["unknown"] += unknown

    # Normalize to sum exactly 1.0 (push rounding drift onto the top bucket).
    total = sum(raw.values()) or 1.0
    probs = {k: round(v / total, 4) for k, v in raw.items()}
    drift = round(1.0 - sum(probs.values()), 4)
    top = max(probs, key=probs.get)
    probs[top] = round(probs[top] + drift, 4)

    # Identity: only from an OFFICIAL disclosure, never from flow.
    identified = name_trader(signals.get("disclosure"))

    notes: List[str] = [
        "SLOW(建玉・遅延)とFAST(intradayフロー)を統合した校正前の推定。",
        short_volume_guard("空売り出来高"),
        "投資家の特定はできない。intradayフローや出来高から機関名は導けない。",
    ]
    if probs["unknown"] >= 0.3:
        notes.append("証拠が薄く、不明(unknown)が依然として大きい。")

    return {
        "schemaVersion": SCHEMA,
        "probabilities": probs,
        "calibrationStatus": CALIB,            # 常に 'uncalibrated'
        "notesJa": notes,
        "identifiedTrader": identified,        # None unless official disclosure
        "evidenceCount": have,
        "topOutcome": max(probs, key=probs.get),
        "dataLimitations": [
            "ポジショニングは遅延・建玉/出来高の別あり・個人特定不可(SLOW/FAST_SOURCESの意味論を参照)。",
            "short-sale VOLUME は short INTEREST ではない。",
        ],
    }


def _unknown_result(reason_ja: str) -> Dict[str, Any]:
    """All-unknown spread (sums to 1.0) for bad/missing/empty input."""
    probs = {k: 0.0 for k in POSITIONING_OUTCOMES}
    probs["unknown"] = 1.0
    return {
        "schemaVersion": SCHEMA,
        "probabilities": probs,
        "calibrationStatus": CALIB,
        "notesJa": [reason_ja, short_volume_guard("空売り出来高"),
                    "投資家の特定はできない。"],
        "identifiedTrader": None,
        "evidenceCount": 0,
        "topOutcome": "unknown",
        "dataLimitations": [
            "ポジショニングは遅延・建玉/出来高の別あり・個人特定不可。",
            "short-sale VOLUME は short INTEREST ではない。",
        ],
    }
