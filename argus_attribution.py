"""ARGUS — Cause Attribution Integrity (pure, deterministic).

WHY (v10.116): a Gemini analysis of the Micron/AI-semis selloff over-claimed —
it said Micron *earnings* triggered the June-23 drop (earnings were AFTER the
June-24 close), named institutions "mathematically decided to sell", and treated
FINRA daily short-VOLUME as short-INTEREST / whale identity. All false.

This module enforces causal integrity. It distinguishes immediate trigger vs
background vulnerability vs amplifier vs propagation vs unknown, with TIMESTAMP
rules (evidence published after the move can't be the trigger; a not-yet-released
earnings can't be an earnings-result cause; a stale report isn't an immediate
trigger), keeps `unknown` a valid non-zero outcome, refuses to name an institution
without an official filing, and exposes the real semantics/delays of positioning
data sources. A narrative-integrity gate rejects over-claims.

Decision-support only. Nothing here trades, sizes, or routes orders. Reuses the
existing dossier (argus_research) and flow inference; this adds the integrity layer.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

# ── Vocabulary ──────────────────────────────────────────────────────────────
CAUSE_LABELS = [
    "EARNINGS_RESULT_SHOCK", "PRE_EARNINGS_DE_RISKING", "CROWDED_TRADE_UNWIND",
    "VALUATION_REPRICING", "RATE_SHOCK", "AI_CAPEX_ROI_CONCERN",
    "SECTOR_WIDE_DELEVERAGING", "LONG_LIQUIDATION", "NEW_SHORT_BUILDUP",
    "SHORT_COVERING", "DISTRIBUTION", "COMPANY_SPECIFIC_CATALYST", "UNKNOWN",
]
CAUSAL_ROLES = ["trigger", "vulnerability", "amplifier", "confirmation",
                "propagation", "contradiction", "background_only"]
CONTAGION_SCOPES = ["company_specific", "subsector_wide", "sector_wide",
                    "cross_market", "global_growth_unwind", "unconfirmed"]


def _to_epoch(iso: Optional[str]) -> Optional[float]:
    if not iso:
        return None
    s = str(iso).strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except (ValueError, TypeError):
        return None


# ── 2. Causal role classification (TIMESTAMP integrity) ─────────────────────
def causal_role(ev: Dict[str, Any], move_started_at: Optional[str]) -> Dict[str, Any]:
    """Classify one evidence item's causal role relative to when the move began.

    Hard rules:
      * a FUTURE event (e.g. earnings not yet released) is never a trigger,
      * evidence PUBLISHED AFTER the move began is never the original trigger
        (at most an amplifier/confirmation),
      * STALE evidence (published well before the move) is background_only unless
        same-day recirculation is evidenced.
    """
    move = _to_epoch(move_started_at)
    pub = _to_epoch(ev.get("publishedAt"))
    reliab = float(ev.get("sourceReliability") or 0.0)
    recirculated = bool(ev.get("sameDayRecirculation"))

    if ev.get("isFutureEvent"):
        return _role("background_only", 0.0, "未発生のイベントは過去の引き金になり得ない（リスク要因）。")
    if pub is None or move is None:
        return _role("background_only", _align(pub, move), "時刻情報が不足し引き金と断定できない。")
    if pub > move + 600:                      # published >10min after the move began
        return _role("amplifier" if reliab >= 0.4 else "background_only", _align(pub, move),
                     "動意の後に出た情報。元の引き金ではない（増幅/追認の可能性）。")
    staleness = (move - pub) / 86400.0        # days before the move
    if staleness > 1.5:
        if recirculated:
            return _role("amplifier", 0.5,
                         "古い情報だが当日の再流通が確認できる。引き金ではなく増幅要因。")
        return _role("background_only", _align(pub, move),
                     "古い情報。当日の再流通が確認できない限り即時の引き金ではない（背景脆弱性）。")
    align = _align(pub, move)
    if align >= 0.6 and reliab >= 0.5:
        return _role("trigger", align, "動意と時間整合し、信頼度も十分。引き金候補。")
    return _role("amplifier" if align >= 0.4 else "background_only", align,
                 "時間整合または信頼度が中程度。引き金とは断定しない。")


def _align(pub: Optional[float], move: Optional[float]) -> float:
    """1.0 when published right at the move; decays over ~24h; 0 if after/unknown."""
    if pub is None or move is None or pub > move:
        return 0.0
    return round(max(0.0, 1.0 - (move - pub) / 86400.0), 3)


def _role(role: str, align: float, ja: str) -> Dict[str, Any]:
    return {"role": role, "timeAlignmentScore": round(align, 3), "reasonJa": ja}


# ── 3. Pre-event de-risking detector ────────────────────────────────────────
def pre_event_derisking(ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Upcoming earnings/event + a stretched prior move + weak peers → the drop
    is likely PRE-event de-risking, NOT a result shock. badResultConfirmed stays
    False until an actual result exists."""
    days = ctx.get("daysToEarnings")
    result_out = bool(ctx.get("earningsResultReleased"))
    rally = float(ctx.get("priorRunupPct") or 0.0)     # e.g. 20d run-up before the drop
    peers_down = bool(ctx.get("peersDown"))
    accel_down = bool(ctx.get("shortWindowDownAccel"))
    flow_reversal = bool(ctx.get("flowReversal"))

    p = 0.0
    if isinstance(days, (int, float)) and 0 < days <= 5 and not result_out:
        p += 0.45
    if rally >= 15:
        p += 0.2
    if peers_down:
        p += 0.15
    if accel_down:
        p += 0.1
    if flow_reversal:
        p += 0.1
    p = min(p, 0.95)

    action = "HOLD_CAUTION"
    if p >= 0.5:
        action = "DO_NOT_ADD"          # don't add into an unconfirmed pre-event unwind
    if p >= 0.5 and ctx.get("isHeld"):
        action = "REVIEW_REQUIRED"
    return {
        "preEventDeRiskingProbability": round(p, 2),
        "badResultConfirmed": False if not result_out else bool(ctx.get("badResult")),
        "eventRisk": "elevated" if (isinstance(days, (int, float)) and 0 < days <= 5) else "normal",
        "followThroughRisk": "high" if (accel_down and peers_down) else "medium" if accel_down else "low",
        "actionOverride": action,
        "nextEvidenceRequired": "実際の決算結果（未発表のうちは結果ショックと断定しない）／引け方向／ピア継続",
    }


# ── 4. Cross-market contagion graph (versioned) ─────────────────────────────
CONTAGION_GRAPH_VERSION = "contagion-v1"
CONTAGION_GRAPH: Dict[str, List[Dict[str, str]]] = {
    "MU": [{"to": "memory_semis", "type": "sector"}, {"to": "SMH", "type": "etf"}],
    "285A": [{"to": "memory_semis", "type": "sector"}, {"to": "MU", "type": "competitor"},
             {"to": "japan_tech", "type": "theme"}],          # キオクシア
    "5801": [{"to": "ai_datacenter_infra", "type": "theme"}, {"to": "SMH", "type": "macro"}],  # 古河電工
    "5803": [{"to": "ai_datacenter_infra", "type": "theme"}],  # フジクラ
    "NVDA": [{"to": "ai_compute", "type": "theme"}, {"to": "SMH", "type": "etf"}],
    "SMH": [{"to": "us_semis", "type": "index"}],
    "9984": [{"to": "global_tech_sentiment", "type": "macro"}],  # SBG
}


def classify_contagion(symbol: str, peer_returns: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """From timestamped peer breadth + relative returns, classify how broad the
    move is. Graph membership alone never asserts causality — peers must actually
    be moving together."""
    peers = [p for p in (peer_returns or []) if isinstance(p.get("changePct"), (int, float))]
    if not peers:
        return {"scope": "unconfirmed", "graphVersion": CONTAGION_GRAPH_VERSION,
                "peersDown": 0, "peersTotal": 0,
                "noteJa": "ピアの値動きが取得できず、波及範囲は未確認。"}
    down = [p for p in peers if p["changePct"] <= -1.0]
    frac = len(down) / len(peers)
    themes = {p.get("theme") for p in down if p.get("theme")}
    cross_market = any(p.get("market") and p.get("market") != peers[0].get("market") for p in down)
    if frac < 0.34:
        scope = "company_specific"
    elif cross_market and frac >= 0.6:
        scope = "cross_market"
    elif len(themes) >= 2 and frac >= 0.6:
        scope = "global_growth_unwind"
    elif frac >= 0.6:
        scope = "sector_wide"
    else:
        scope = "subsector_wide"
    return {"scope": scope, "graphVersion": CONTAGION_GRAPH_VERSION,
            "peersDown": len(down), "peersTotal": len(peers), "downFraction": round(frac, 2),
            "noteJa": "グラフ所属だけでは因果を断定しない。実際に同時に下げているかで範囲を判定。"}


# ── 5. Institutional positioning context (honest source semantics) ──────────
# The actual, non-negotiable semantics of each positioning source. These prevent
# the short-VOLUME=short-INTEREST and "intraday whale identity" errors.
POSITIONING_SOURCES: Dict[str, Dict[str, Any]] = {
    "finra_short_interest": {
        "labelJa": "FINRA 空売り残高(SI)", "publicationDelayJa": "月2回・数日遅延",
        "identityAvailable": False, "isPositionData": True, "isTransactionVolume": False,
        "noteJa": "建玉(残高)。リアルタイムでも個人特定でもない。"},
    "finra_daily_short_volume": {
        "labelJa": "FINRA 日次空売り出来高", "publicationDelayJa": "翌日・集計値",
        "identityAvailable": False, "isPositionData": False, "isTransactionVolume": True,
        "noteJa": "★出来高であり空売り残高ではない。建玉や投資家特定は不可。"},
    "jpx_disclosed_short": {
        "labelJa": "JPX 空売り残高報告", "publicationDelayJa": "閾値超のみ・遅延",
        "identityAvailable": True, "isPositionData": True, "isTransactionVolume": False,
        "noteJa": "報告閾値超の建玉のみ・遅延。intradayのフローではない。"},
    "jsf_lending": {
        "labelJa": "日証金 貸借", "publicationDelayJa": "日次・翌営業日",
        "identityAvailable": False, "isPositionData": True, "isTransactionVolume": False,
        "noteJa": "需給の目安。個人特定不可。"},
    "edinet_large_holding": {
        "labelJa": "EDINET 大量保有報告", "publicationDelayJa": "提出後・遅延",
        "identityAvailable": True, "isPositionData": True, "isTransactionVolume": False,
        "noteJa": "5%超等の保有報告。intradayの売買ではない。"},
    "sec_form4_13d_13g_13f": {
        "labelJa": "SEC Form4/13D/13G/13F", "publicationDelayJa": "提出遅延・四半期等",
        "identityAvailable": True, "isPositionData": True, "isTransactionVolume": False,
        "noteJa": "遅延開示。intradayのフロー追跡ではない。"},
}


def positioning_probabilities(fast: Dict[str, Any]) -> Dict[str, Any]:
    """Probabilities over what the FAST evidence (moomoo flow, short-window
    price/volume, relative strength) implies. Sums to 1; `unknown` stays non-zero
    when evidence is thin. NEVER attaches an institution name."""
    flow = fast.get("flowRatio")
    prior_flow = fast.get("priorFlowRatio")
    chg = fast.get("changePct")
    vol_ratio = fast.get("volRatio")
    rel_weak = bool(fast.get("relativeWeakness"))
    have = sum(1 for v in (flow, chg, vol_ratio) if isinstance(v, (int, float)))

    raw = {k: 0.0 for k in ("newLongAccumulation", "longLiquidation", "newShortBuildup",
                            "shortCovering", "distribution", "retailNoise", "unknown")}
    down = isinstance(chg, (int, float)) and chg < 0
    up = isinstance(chg, (int, float)) and chg > 0
    heavy = isinstance(vol_ratio, (int, float)) and vol_ratio >= 1.3
    outflow = isinstance(flow, (int, float)) and flow < 0
    inflow = isinstance(flow, (int, float)) and flow > 0
    flow_reversed_down = (isinstance(flow, (int, float)) and isinstance(prior_flow, (int, float))
                          and prior_flow > 0 and flow < 0)

    if down and outflow and heavy:
        raw["distribution"] += 1.4
    if down and outflow:
        raw["longLiquidation"] += 1.0
    if down and flow_reversed_down:
        raw["longLiquidation"] += 0.6
    if down and not outflow and rel_weak:
        raw["newShortBuildup"] += 0.8
    if up and inflow:
        raw["newLongAccumulation"] += 1.2
    if up and outflow:
        raw["shortCovering"] += 0.9
    if not heavy and abs(chg or 0) < 1.0:
        raw["retailNoise"] += 0.6
    # unknown floor — higher when we have little fast evidence
    raw["unknown"] += 1.5 if have < 2 else 0.5

    total = sum(raw.values()) or 1.0
    probs = {k: round(v / total, 3) for k, v in raw.items()}
    drift = round(1.0 - sum(probs.values()), 3)
    top = max(probs, key=probs.get)
    probs[top] = round(probs[top] + drift, 3)
    return {"probabilities": probs,
            "identityClaim": None,     # never name an institution from flow
            "noteJa": "高速フローからの推定。投資家の特定はできない（建玉/出来高/個人名は別物）。"}


# ── 7. Narrative integrity gate ─────────────────────────────────────────────
_BAD_PATTERNS = [
    ("完全に原因", "単一原因の断定（monocausal）。"),
    ("クジラが数学的", "『クジラが数学的に判断』は根拠なき擬人化。"),
    ("機関投資家が完全に売り", "機関の全面転換を断定している。"),
    ("100%", "確実性の過大主張。"),
    ("確実に", "確実性の過大主張。"),
]
_INSTITUTION_NAMES = ["goldman", "morgan stanley", "jpmorgan", "j.p. morgan", "jpモルガン",
                      "ゴールドマン", "モルガン・スタンレー", "野村", "blackrock", "citadel"]


def narrative_violations(text: str, *, evidence: Optional[List[Dict[str, Any]]] = None,
                         has_official_identity: bool = False) -> List[Dict[str, str]]:
    """Return integrity violations in a narrative. Empty list = passes the gate."""
    t = (text or "")
    tl = t.lower()
    out: List[Dict[str, str]] = []
    for kw, why in _BAD_PATTERNS:
        if kw.lower() in tl:
            out.append({"type": "overclaim", "match": kw, "reasonJa": why})
    # named institution without official identity evidence
    if not has_official_identity:
        for nm in _INSTITUTION_NAMES:
            if nm in tl:
                out.append({"type": "named_entity_without_evidence", "match": nm,
                            "reasonJa": "公式開示の裏付けなく機関名を原因として名指ししている。"})
                break
    # short volume vs short interest confusion
    if ("空売り出来高" in t or "short volume" in tl) and ("残高" in t or "short interest" in tl):
        out.append({"type": "short_volume_vs_interest", "match": "空売り出来高/残高",
                    "reasonJa": "空売り『出来高』と『残高』を混同している。"})
    # future earnings used as a past cause
    if ("決算" in t or "earnings" in tl) and ("引き金" in t or "triggered" in tl or "が原因" in t):
        for e in (evidence or []):
            if e.get("kind") == "earnings" and e.get("isFutureEvent"):
                out.append({"type": "future_event_as_cause", "match": "earnings",
                            "reasonJa": "未発表の決算を過去の原因として扱っている。"})
                break
    return out


# ── 6. Report intelligence (preserve BOTH bullish and bearish) ──────────────
_BULL_KW = ["強い", "好調", "増益", "上方修正", "恩恵", "堅調", "最高益", "需要拡大",
            "strong", "beat", "upgrade", "raise", "robust", "tailwind", "record"]
_BEAR_KW = ["懸念", "下方修正", "悪化", "減益", "頭打ち", "巻き戻し", "割高", "catch-down",
            "roi", "pressure", "downgrade", "cut", "weak", "headwind", "overvalued", "derat"]
_COND_KW = ["もし", "可能性", "リスク", "条件", "次第", "if ", "could", "may ", "risk of",
            "potential", "unless", "depending"]


def analyze_report(text: str, *, source: str = "", title: str = "",
                   published_at: Optional[str] = None,
                   move_started_at: Optional[str] = None) -> Dict[str, Any]:
    """Extract a report's bullish AND bearish claims + conditional risks WITHOUT
    collapsing a balanced report to one bearish keyword score. Classifies it as
    background vs immediate-trigger using the timestamp rule."""
    sents = [s.strip() for s in
             (text or "").replace("。", "。\n").replace(". ", ".\n").splitlines() if s.strip()]
    bull, bear, cond = [], [], []
    for s in sents:
        sl = s.lower()
        if any(k in s or k in sl for k in _BULL_KW):
            bull.append(s[:140])
        if any(k in s or k in sl for k in _BEAR_KW):
            bear.append(s[:140])
        if any(k in s or k in sl for k in _COND_KW):
            cond.append(s[:140])
    # background vs trigger via timestamp (a report rarely is an immediate trigger)
    role = causal_role({"publishedAt": published_at, "sourceReliability": 0.6, "kind": "report"},
                       move_started_at)["role"] if move_started_at else "background_only"
    balanced = bool(bull) and bool(bear)
    return {
        "source": source, "title": title, "publishedAt": published_at,
        "bullishClaims": bull[:5], "bearishClaims": bear[:5], "conditionalRisks": cond[:5],
        "balanced": balanced,
        "backgroundVsTrigger": "background" if role in ("background_only", "vulnerability") else role,
        "noteJa": ("両論(強気・弱気)を保持。単一キーワードで弱気と断定しない。"
                   if balanced else "一方向の主張が中心(両論の有無を確認)。"),
        "dominantKeywordScoreRejected": True,
    }


# ── 1. Cause attribution stack (orchestrator) ───────────────────────────────
def attribute_cause(ctx: Dict[str, Any], evidence: Sequence[Dict[str, Any]],
                    *, now_iso: Optional[str] = None) -> Dict[str, Any]:
    """Build the full cause stack for a material move. Enforces every integrity
    rule. `unknown` is always a valid non-zero outcome when evidence is weak."""
    move_start = ctx.get("moveStartedAt")
    roles = []
    for ev in evidence or []:
        r = causal_role(ev, move_start)
        roles.append({**r, "evidenceId": ev.get("id"), "kind": ev.get("kind"),
                      "supports": ev.get("supports") or []})

    triggers = [r for r in roles if r["role"] == "trigger"]
    vulns = [r for r in roles if r["role"] in ("background_only", "vulnerability")]
    amps = [r for r in roles if r["role"] == "amplifier"]
    props = [r for r in roles if r["role"] == "propagation"]

    pre = pre_event_derisking(ctx)
    contagion = ctx.get("contagion") or {}

    # Score cause probabilities (always include a non-zero unknown).
    raw = {c: 0.0 for c in CAUSE_LABELS}
    # pre-earnings de-risking dominates when an event is upcoming + unconfirmed
    if pre["preEventDeRiskingProbability"] >= 0.4:
        raw["PRE_EARNINGS_DE_RISKING"] += 2.5 * pre["preEventDeRiskingProbability"]
    # earnings-result shock ONLY if a result actually exists
    if ctx.get("earningsResultReleased") and ctx.get("badResult"):
        raw["EARNINGS_RESULT_SHOCK"] += 2.0
    # crowded-trade / sector unwind from contagion breadth
    scope = contagion.get("scope")
    if scope in ("sector_wide", "subsector_wide"):
        raw["SECTOR_WIDE_DELEVERAGING"] += 1.2
        raw["CROWDED_TRADE_UNWIND"] += 0.8
    if scope in ("cross_market", "global_growth_unwind"):
        raw["CROWDED_TRADE_UNWIND"] += 1.4
    if ctx.get("aiCapexConcern"):
        raw["AI_CAPEX_ROI_CONCERN"] += 0.8
    if ctx.get("rateShock"):
        raw["RATE_SHOCK"] += 1.0
    # flow-implied
    pos = ctx.get("positioning") or {}
    pp = (pos.get("probabilities") or {})
    raw["DISTRIBUTION"] += 1.2 * pp.get("distribution", 0)
    raw["LONG_LIQUIDATION"] += 1.2 * pp.get("longLiquidation", 0)
    raw["NEW_SHORT_BUILDUP"] += 1.0 * pp.get("newShortBuildup", 0)
    raw["SHORT_COVERING"] += 1.0 * pp.get("shortCovering", 0)
    # confirmed company-specific catalyst only if a timestamp-valid trigger exists
    if triggers and any("COMPANY_SPECIFIC_CATALYST" in (r.get("supports") or []) for r in triggers):
        raw["COMPANY_SPECIFIC_CATALYST"] += 1.6

    known = sum(raw.values())
    # UNKNOWN floor: high when no valid trigger / thin evidence.
    unknown = 1.2
    # No valid trigger raises unknown — UNLESS pre-event de-risking already
    # explains the trigger-less drop (de-risking has no single news trigger).
    if not triggers and pre["preEventDeRiskingProbability"] < 0.4:
        unknown += 0.8
    if known < 1.0:
        unknown += 1.0
    raw["UNKNOWN"] = unknown

    total = sum(raw.values()) or 1.0
    probs = {c: round(v / total, 3) for c, v in raw.items() if v > 0}
    drift = round(1.0 - sum(probs.values()), 3)
    if probs:
        top = max(probs, key=probs.get)
        probs[top] = round(probs[top] + drift, 3)
    ranked = sorted(probs.items(), key=lambda kv: kv[1], reverse=True)

    immediate = None
    if triggers:
        best = max(triggers, key=lambda r: r["timeAlignmentScore"])
        # the immediate trigger label is the top NON-unknown cause it supports
        lbl = next((c for c in (best.get("supports") or []) if c in CAUSE_LABELS and c != "UNKNOWN"), None)
        if lbl:
            immediate = {"cause": lbl, "confidence": round(best["timeAlignmentScore"], 2),
                         "evidenceIds": [best["evidenceId"]]}

    overall_conf = round(min(0.9, (max(probs.values()) if probs else 0.0) * (0.5 + 0.5 * (1 if triggers else 0))), 2)

    return {
        "schemaVersion": "cause-attribution-v1",
        "immediateTrigger": immediate,                 # None when no timestamp-valid trigger
        "vulnerabilities": [r["evidenceId"] for r in vulns],
        "amplifiers": [r["evidenceId"] for r in amps],
        "propagationPaths": [r["evidenceId"] for r in props] or contagion.get("paths") or [],
        "alternativeExplanations": [{"cause": c, "probability": p} for c, p in ranked[1:4]],
        "causeProbabilities": dict(ranked),
        "unknownShare": probs.get("UNKNOWN", 0.0),
        "overallConfidence": overall_conf,
        "preEvent": pre,
        "contagion": contagion,
        "positioning": pos,
        "roles": roles,
        "evidenceIds": [ev.get("id") for ev in (evidence or [])],
        "dataLimitations": ctx.get("dataLimitations") or [
            "ポジショニングデータは遅延・建玉/出来高の別あり・個人特定不可（出所別の意味論を参照）。",
            "intradayのフローはmoomoo等の高速指標のみ。投資家の特定はできない。",
        ],
        "noteJa": "即時引き金/背景脆弱性/増幅/波及/不明を区別。証拠の時刻整合と出所の意味論を厳格化。"
                  "未発表イベントは結果ショックにしない。機関名は公式開示がない限り名指ししない。",
    }
