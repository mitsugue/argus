"""ARGUS — Important Events priority + novice explanations (pure, v10.138).

Turns the Event Radar's schedule rows into owner-facing "why this matters" cards:
a beginner-readable explanation, an owner-relevance-aware priority, the action
that is blocked until release, and what to re-check afterward. Deterministic
templates only — NO forecasts, NO consensus, NO direction prediction, NO trading.
Event IMPACT = how strongly markets may move, NOT whether the result is good/bad.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

# Beginner-readable, direction-neutral explanations per event kind (en/ja).
NOVICE: Dict[str, Dict[str, str]] = {
    "pce": {
        "en": "A major US inflation release watched closely by the Federal Reserve. A result above or below market expectations can quickly move interest rates, USDJPY, growth stocks and semiconductor stocks.",
        "ja": "FRBが重視する米国のインフレ指標です。市場予想との差によって、米金利・ドル円・グロース株・半導体株が大きく動く可能性があります。",
    },
    "cpi": {
        "en": "US consumer inflation. A hotter or cooler reading shifts rate-cut expectations, which can move US rates, USDJPY and high-valuation growth stocks.",
        "ja": "米国の消費者物価(インフレ)です。強い/弱い結果で利下げ期待が変わり、米金利・ドル円・高PERのグロース株が動きやすくなります。",
    },
    "ppi": {
        "en": "US wholesale (producer) inflation — a leading indicator for CPI. It can nudge rate expectations and US yields ahead of the consumer numbers.",
        "ja": "米国の卸売物価(PPI)。CPIの先行指標で、金利期待と米金利を発表前に動かすことがあります。",
    },
    "fomc": {
        "en": "The Federal Reserve's interest-rate decision, economic projections and the Chair's press conference. One of the highest-impact events for global rates, USDJPY and equities.",
        "ja": "FRBの政策金利の決定・経済見通し・議長会見です。世界の金利・ドル円・株式に最も影響しやすいイベントの一つです。",
    },
    "boj": {
        "en": "The Bank of Japan's policy meeting. It moves Japanese rates and the yen, which in turn affect banks, exporters and Japanese growth stocks.",
        "ja": "日銀の金融政策決定会合です。日本の金利と円相場を動かし、銀行株・輸出株・日本のグロース株に波及します。",
    },
    "nfp": {
        "en": "The US monthly jobs report. Strong or weak employment changes rate-cut expectations and can move US yields, USDJPY and equities.",
        "ja": "米国の雇用統計です。雇用の強弱で利下げ期待が変わり、米金利・ドル円・株式が動く可能性があります。",
    },
    "jolts": {
        "en": "US job openings — a gauge of labor-market tightness and wage pressure. It can affect rate expectations, USDJPY and growth stocks.",
        "ja": "米国の求人件数(JOLTS)。労働需給と賃金圧力を示し、金利期待・ドル円・グロース株に影響することがあります。",
    },
    "gdp": {
        "en": "US economic growth. A strong or weak reading shifts the balance between recession worries and overheating, moving yields and equity indices.",
        "ja": "米国のGDP(成長率)です。強い/弱い結果で景気後退懸念と過熱懸念のバランスが変わり、金利・株価指数が動きます。",
    },
    "auction": {
        "en": "A US Treasury bond auction. Weak demand can push long-term yields up, which pressures rate-sensitive and high-valuation stocks (e.g. NASDAQ names).",
        "ja": "米国債の入札です。需要が弱いと長期金利が上昇し、金利に敏感な株・高PER株(NASDAQ系など)に圧力がかかります。",
    },
    "earnings": {
        "en": "A company or sector earnings release. The risk is company/sector-specific: a surprise versus expectations can move that name and its peers.",
        "ja": "企業・セクターの決算発表です。リスクは個別・セクター固有で、予想との差がその銘柄や同業に波及します。",
    },
}
_FALLBACK_NOVICE = {
    "en": "A scheduled macro event. Markets may move around the release depending on how the result compares with expectations.",
    "ja": "予定されたマクロイベントです。結果と予想の差し引きで、発表前後に市場が動く可能性があります。",
}

IMPACT_RANK = {"critical": 4, "high": 3, "medium": 2, "low": 1}
_RANK_IMPACT = {v: k for k, v in IMPACT_RANK.items()}

# Action blocked until release, by DISPLAY impact (en/ja). Direction-neutral.
ACTION_UNTIL = {
    "critical": {"en": "NEW ENTRY BLOCKED · ADD BLOCKED", "ja": "新規購入 禁止 · 買い増し 禁止"},
    "high":     {"en": "NEW ENTRY BLOCKED · ADD BLOCKED", "ja": "新規購入 禁止 · 買い増し 禁止"},
    "medium":   {"en": "Hold new lump-sum entries; size down", "ja": "新規の一括投入は見送り・サイズは控えめに"},
    "low":      {"en": "No restriction; stay aware", "ja": "制限なし・頭の片隅に"},
}


def _proximity_score(days: Optional[int]) -> float:
    if days is None:
        return 0.3
    if days <= 0:
        return 1.0
    if days == 1:
        return 0.9
    if days <= 3:
        return 0.65
    if days <= 7:
        return 0.45
    return 0.25


def lifecycle_state(days: Optional[int]) -> str:
    """UPCOMING → IMMINENT (today) → RELEASED (already passed). Result/reaction
    states are set elsewhere once verified data exists (none fabricated here)."""
    if days is None:
        return "UPCOMING"
    if days < 0:
        return "RELEASED"
    if days == 0:
        return "IMMINENT"
    return "UPCOMING"


def _owner_relevance(linked: List[str], owner_symbols: set, held_symbols: set,
                     ctx: Dict[str, Any]) -> (str, List[str]):
    reasons: List[str] = []
    linked_up = {str(a).upper() for a in (linked or [])}
    owner_hit = linked_up & {s.upper() for s in owner_symbols}
    held_hit = linked_up & {s.upper() for s in held_symbols}
    # Proxy themes: growth/semis exposure when the owner holds QQQ/SMH-like or the
    # linked set includes them (kept simple + explicit; no hidden formula).
    theme_proxy = bool(linked_up & {"QQQ", "SMH", "NVDA", "SOXX"})
    rel = "normal"
    if held_hit:
        rel = "critical"
        reasons.append("held_asset_linked")
    elif owner_hit:
        rel = "high"
        reasons.append("watchlist_asset_linked")
    elif theme_proxy:
        rel = "medium"
        reasons.append("growth_semiconductor_exposure")
    return rel, reasons


def _promote(base_impact: str, owner_rel: str, days: Optional[int]) -> str:
    """Owner relevance + proximity can raise DISPLAY impact one notch (never lower)."""
    rank = IMPACT_RANK.get(base_impact, 1)
    near = days is not None and days <= 1
    if owner_rel == "critical" and near:
        rank += 1
    elif owner_rel in ("high",) and near and rank < 4:
        rank += 1
    return _RANK_IMPACT[min(4, rank)]


def prioritize_event(event: Dict[str, Any], owner_symbols: set, held_symbols: set,
                     ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    ctx = ctx or {}
    base_impact = (event.get("impact") or "low").lower()
    days = event.get("daysUntil")
    owner_rel, reasons = _owner_relevance(event.get("linkedAssets") or [],
                                          owner_symbols, held_symbols, ctx)
    display_impact = _promote(base_impact, owner_rel, days)

    # Direction-neutral priority score (0-100): impact + proximity + relevance +
    # macro stress. Shown to the user only as short reasons, never the raw formula.
    score = 0.0
    score += IMPACT_RANK.get(base_impact, 1) * 14           # up to 56
    score += _proximity_score(days) * 24                    # up to 24
    score += {"critical": 16, "high": 11, "medium": 6, "normal": 0}[owner_rel]
    regime = str(ctx.get("regime") or "").upper()
    if regime in ("EVENT_WAIT", "RISK_OFF"):
        score += 4
        reasons.append("event_wait_regime" if regime == "EVENT_WAIT" else "risk_off_regime")
    if ctx.get("vixElevated"):
        score += 2
        reasons.append("elevated_volatility")
    if base_impact in ("critical", "high"):
        reasons.insert(0, f"{base_impact}_impact_event")
    if days is not None and days <= 1:
        reasons.append("within_24_hours")

    return {
        "baseImpact": base_impact,
        "displayImpact": display_impact,
        "ownerRelevance": owner_rel,
        "proximity": event.get("escalation") or "normal",
        "priorityScore": int(round(min(100.0, score))),
        "priorityReasons": reasons[:4],
        "lifecycle": lifecycle_state(days),
    }


def build_important_events(events: List[Dict[str, Any]], owner_symbols=None,
                           held_symbols=None, ctx=None, limit: int = 8) -> List[Dict[str, Any]]:
    """Enrich + filter + sort events for the Today command area.

    Default visibility: CRITICAL/HIGH always; MEDIUM only when owner-relevant; LOW
    stays in the full calendar. Sorted by displayImpact, then priorityScore, then
    time. No forecast/consensus/actual is invented — those fields stay 'unavailable'
    until a verified source provides them.
    """
    owner_symbols = set(owner_symbols or [])
    held_symbols = set(held_symbols or [])
    ctx = ctx or {}
    out = []
    for e in events or []:
        kind = (e.get("kind") or "").lower()
        pr = prioritize_event(e, owner_symbols, held_symbols, ctx)
        di = pr["displayImpact"]
        # Visibility rule.
        if di in ("critical", "high"):
            pass
        elif di == "medium" and pr["ownerRelevance"] != "normal":
            pass
        else:
            continue
        novice = NOVICE.get(kind, _FALLBACK_NOVICE)
        au = ACTION_UNTIL.get(di, ACTION_UNTIL["low"])
        out.append({
            "eventId": e.get("id"),
            "eventCode": kind.upper() or "EVENT",
            "title": e.get("title"),
            "date": e.get("eventDate"),
            "jstTime": e.get("localTimeJst"),     # may be None for date-only events
            "eventTimeUtc": e.get("eventTimeUtc"),
            "countdown": e.get("escalation") or "normal",
            "daysUntil": e.get("daysUntil"),
            "baseImpact": pr["baseImpact"],
            "displayImpact": di,
            "ownerRelevance": pr["ownerRelevance"],
            "priorityScore": pr["priorityScore"],
            "priorityReasons": pr["priorityReasons"],
            "lifecycle": pr["lifecycle"],
            "noviceEn": novice["en"],
            "noviceJa": novice["ja"],
            "rationaleJa": e.get("rationaleJa"),
            "linkedAssets": e.get("linkedAssets") or [],
            "actionUntilEn": au["en"],
            "actionUntilJa": au["ja"],
            "source": e.get("source"),
            "sourceStatus": e.get("status") or "unknown",
            # Honest data state — never fabricated.
            "forecast": "UNAVAILABLE",
            "previous": "UNAVAILABLE",
            "actual": None,
            "releasedAt": None,
        })
    rank = IMPACT_RANK
    out.sort(key=lambda x: (-rank.get(x["displayImpact"], 0), -x["priorityScore"],
                            x["daysUntil"] if x["daysUntil"] is not None else 999))
    return out[:limit]
