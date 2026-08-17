"""ARGUS Pro — EventCard v2 (the canonical research object).

Pure, stdlib-only. This module does NOT fetch, mutate inputs, or call an LLM. It
FOLDS the three existing event schemas (EventEnvelope / dossier-v2 / IntelligenceItem)
plus the Visibility Guard into ONE flat, auditable card and enforces the epistemic
discipline that keeps ARGUS honest:

  * A single-source association can NEVER be a confirmed_cause.
  * With fewer than two independent source families and no official source, the
    strongest a trigger can be is candidate_catalyst.
  * A theme-only link cannot move a posture unless corroborated (official / a second
    independent family / market confirmation).
  * confidenceFinal = min(confidenceRaw, visibility.confidenceCap).
  * An event that happened AFTER the price move is never an immediate trigger.
  * Every card states what is MISSING. "unknown" is acceptable; fake certainty is not.

The scanner wires real inputs; every rule here is unit-tested in isolation.
"""
from typing import Any, Dict, List, Optional

SCHEMA_VERSION = "event-card-v2"

# EventEnvelope.eventType (argus_events) → EventCard eventType vocabulary.
_EVENT_TYPE_MAP = {
    "PRICE_MOVE": "price_move", "PRICE_SPIKE": "price_move", "PRICE_CRASH": "price_move",
    "LIMIT_UP": "price_move", "LIMIT_DOWN": "price_move", "GAP": "price_move",
    "VOLUME_ANOMALY": "flow", "FLOW_ANOMALY": "flow", "FLOW_REVERSAL": "flow",
    "MACRO": "macro", "MACRO_EVENT": "macro", "RATE_DECISION": "macro",
    "EARNINGS": "earnings", "TDNET": "tdnet", "FILING": "official_filing",
    "EDINET": "official_filing", "ANALYST_ACTION": "analyst_action",
    "INSTITUTIONAL_VIEW": "institutional_view", "THEME": "theme",
    "CAOS_CANDIDATE": "caos_candidate", "RISK_EVENT": "risk_event",
}

_CORROBORATION_ORDER = [
    "none", "single_source", "multi_source", "official",
    "market_confirmed", "official_and_market_confirmed",
]
_CORR_BUMP = {
    "none": 0.0, "single_source": 0.05, "multi_source": 0.2,
    "official": 0.3, "market_confirmed": 0.25, "official_and_market_confirmed": 0.4,
}
_TRIGGER_ROLES = [
    "confirmed_cause", "probable_catalyst", "candidate_catalyst",
    "vulnerability_context", "background_theme", "unknown",
]


def map_event_type(envelope_type: Optional[str]) -> str:
    return _EVENT_TYPE_MAP.get(str(envelope_type or "").upper(), "unknown")


def corroboration_level(*, independent_family_count: int, has_official: bool,
                        market_confirmed: bool) -> str:
    """Fold independent-source-family count + official + market confirmation into the
    6-level vocabulary. Two syndicated copies of ONE wire are ONE family, so the caller
    must pass the INDEPENDENT family count (not the article count)."""
    off, mkt = bool(has_official), bool(market_confirmed)
    if off and mkt:
        return "official_and_market_confirmed"
    if mkt:
        return "market_confirmed"
    if off:
        return "official"
    if independent_family_count >= 2:
        return "multi_source"
    if independent_family_count >= 1:
        return "single_source"
    return "none"


def resolve_trigger_role(*, corroboration: str, theme_only: bool, event_after_move: bool,
                         has_official: bool, independent_family_count: int) -> str:
    """The discipline gate. Association is never silently promoted to cause."""
    # An event that post-dates the price move cannot be the immediate trigger.
    if event_after_move:
        return "background_theme" if theme_only else "vulnerability_context"
    # A theme-only association needs corroboration before it can be a catalyst.
    if theme_only and corroboration in ("none", "single_source"):
        return "background_theme"
    # Fewer than two independent families AND no official source → candidate at most.
    if independent_family_count < 2 and not has_official:
        return "candidate_catalyst"
    # confirmed_cause requires BOTH an official source AND market confirmation.
    if corroboration == "official_and_market_confirmed":
        return "confirmed_cause"
    if corroboration in ("official", "market_confirmed", "multi_source"):
        return "probable_catalyst"
    return "candidate_catalyst"


def _confidence_raw(*, reliability: float, trigger_score: float, corroboration: str) -> float:
    base = 0.40 * float(reliability or 0.0) + 0.20 * float(trigger_score or 0.0)
    raw = base + _CORR_BUMP.get(corroboration, 0.0)
    return round(max(0.05, min(0.85, raw)), 3)


def confidence_final(confidence_raw: float, confidence_cap: Optional[float],
                     missing_depth_penalty: float = 0.0) -> float:
    """min(raw, cap) then a small penalty for missing REQUIRED market depth. Never rises."""
    v = float(confidence_raw)
    if confidence_cap is not None:
        v = min(v, float(confidence_cap))
    v = max(0.0, v - max(0.0, missing_depth_penalty))
    return round(v, 3)


def build_card(envelope: Dict[str, Any], *,
               source_ids: Optional[List[str]] = None,
               independent_family_count: Optional[int] = None,
               has_official: Optional[bool] = None,
               theme_only: bool = False,
               event_after_move: bool = False,
               market_confirmed: bool = False,
               source_tiers: Optional[List[str]] = None,
               rights_classes: Optional[List[str]] = None,
               institutional_views: Optional[List[Dict[str, Any]]] = None,
               missing_depth: Optional[List[str]] = None,
               guard: Optional[Dict[str, Any]] = None,
               now_iso: Optional[str] = None) -> Dict[str, Any]:
    """Fold ONE EventEnvelope (+ its corroboration context + guard) into an EventCard v2.
    Pure: inputs are not mutated. `source_ids` (independent families are counted by the
    caller via research_mesh) OR an explicit `independent_family_count`/`has_official`."""
    env = envelope or {}
    guard = guard or {}
    src = list(source_ids or ([env.get("source")] if env.get("source") else []))
    fams = {s for s in src if s}
    fam_count = independent_family_count if independent_family_count is not None else len(fams)
    official = bool(has_official) if has_official is not None else any(
        str(s).lower().startswith(("official", "edinet", "tdnet", "sec", "boj", "fed")) for s in src)

    corr = corroboration_level(independent_family_count=fam_count,
                               has_official=official, market_confirmed=market_confirmed)
    trigger_role = resolve_trigger_role(corroboration=corr, theme_only=theme_only,
                                        event_after_move=event_after_move,
                                        has_official=official,
                                        independent_family_count=fam_count)

    raw = _confidence_raw(reliability=env.get("reliabilityScore", 0.5),
                          trigger_score=env.get("triggerScore", 0.0), corroboration=corr)
    cap = guard.get("confidenceCap")
    missing = list(missing_depth or [])
    depth_penalty = 0.05 if missing else 0.0
    final = confidence_final(raw, cap, depth_penalty)

    # what's missing — every card must say this, honestly.
    missing_conf: List[str] = []
    if not official:
        missing_conf.append("official_confirmation")
    if not market_confirmed:
        missing_conf.append("market_confirmation")
    missing_conf.extend(f"market_depth:{m}" for m in missing)

    # decision impact — theme-only / uncorroborated cannot move the Today call.
    blocked_actions = list(guard.get("blockedActions") or [])
    can_affect = trigger_role in ("confirmed_cause", "probable_catalyst") and not (
        theme_only and corr in ("none", "single_source"))
    posture_delta = "unknown" if trigger_role == "unknown" else (
        "downgrade" if (cap is not None or blocked_actions) else "neutral")
    downgrade_reason = ""
    if blocked_actions:
        downgrade_reason = "可視性ガードが新規エントリーを一時停止中。"
    elif cap is not None:
        downgrade_reason = f"可視性/校正により確信度を上限{cap}にキャップ。"

    return {
        "schemaVersion": SCHEMA_VERSION,
        "cardId": env.get("eventId"),
        "eventId": env.get("eventId"),
        "asOf": now_iso or env.get("detectedAt"),
        "eventType": map_event_type(env.get("eventType")),
        "rawEventType": env.get("eventType"),
        "headline": env.get("headline") or env.get("reasonJa") or (env.get("eventType") or "event"),
        "summaryJa": env.get("reasonJa") or "",
        "directAssets": [env["symbol"]] if env.get("symbol") else [],
        "associatedAssets": list(env.get("linkedAssets") or []),
        "themes": list(env.get("themes") or []),
        "sourceFamilies": sorted(fams),
        "sourceTiers": list(source_tiers or []),
        "rightsClasses": list(rights_classes or []),
        "corroborationLevel": corr,
        "triggerRole": trigger_role,
        "institutionalViews": list(institutional_views or []),
        "officialConfirmations": [s for s in src if official and str(s).lower().startswith(
            ("official", "edinet", "tdnet", "sec", "boj", "fed"))],
        "marketConfirmations": (["price_move_confirmed"] if market_confirmed else []),
        "missingConfirmations": missing_conf,
        "caosLinks": [],                       # populated by the CAOS audit trail (Phase 7)
        "marketDepthProof": [],                # populated from /market-depth/proof
        "visibility": {
            "visibilityLevel": guard.get("visibilityLevel"),
            "confidenceCap": cap,
            "reasonCodes": list(guard.get("reasonCodes") or []),
            "coverageLineJa": guard.get("coverageLineJa") or "",
        },
        "confidenceRaw": raw,
        "confidenceFinal": final,
        "decisionImpact": {
            "allowedActions": [],
            "blockedActions": blocked_actions,
            "postureDelta": posture_delta,
            "downgradeReasonJa": downgrade_reason,
            "canAffectTodayCall": bool(can_affect),
        },
        "nextCheck": env.get("nextOpenAt"),
        "recordRefs": {
            "ledgerRef": None, "calibrationRef": None, "decisionValueRef": None,
            "evidenceIds": list(env.get("evidenceIds") or []),
        },
        "lifecycleState": env.get("lifecycleState"),
        "recommendedPosture": env.get("recommendedPosture"),
    }


def build_cards(envelopes: List[Dict[str, Any]], *,
                guard: Optional[Dict[str, Any]] = None,
                context_by_event: Optional[Dict[str, Dict[str, Any]]] = None,
                now_iso: Optional[str] = None,
                limit: int = 60) -> List[Dict[str, Any]]:
    """Fold a list of EventEnvelopes into EventCards. `context_by_event` optionally
    supplies per-event corroboration context (source_ids / theme_only / market_confirmed
    / missing_depth / source_tiers) keyed by eventId."""
    ctx = context_by_event or {}
    out: List[Dict[str, Any]] = []
    for env in (envelopes or [])[:limit]:
        c = (ctx.get(env.get("eventId")) or {}) if isinstance(env, dict) else {}
        out.append(build_card(env, guard=guard, now_iso=now_iso, **c))
    return out
