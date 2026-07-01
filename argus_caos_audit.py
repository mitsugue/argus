"""ARGUS Pro — C.A.O.S. association audit trail (Phase 7).

Pure, stdlib-only. CAOS links a symbol to an event/headline by association. This
module records WHY each association was made so the owner can inspect it — and it
hard-codes the discipline that association is NOT cause:

  * Every entry carries a nonCausalityCaveatJa.
  * A single-source theme association can only be a candidate/background, never a
    confirmed cause (enforced by build_entry, not left to the caller).
  * An event that post-dates the price move can never be an immediate trigger.
  * Only METADATA is retained (matched terms, source family/tier, why) — never the
    full text of a link-only / licensed source.

build_entry is a pure normaliser; record()/snapshot()/clear() manage a capped
in-memory ring buffer (metadata only, resets on restart — no durable PII).
"""
from typing import Any, Dict, List, Optional

SCHEMA_VERSION = "caos-link-v1"
_MAX = 300
_TRAIL: List[Dict[str, Any]] = []

_LINK_TYPES = {
    "direct_mention", "entity_profile", "theme", "supply_chain",
    "competitor", "macro_sensitive", "owner_alias",
}
_NON_CAUSAL_CAVEAT = "これは連想・候補であり、原因確定ではありません。"


def _trigger_role(*, link_type: str, corroboration_level: str, event_after_move: bool) -> str:
    """Discipline: how strong may this association's trigger role be?"""
    if event_after_move:
        return "background_theme"                      # post-move → never a trigger
    if link_type in ("theme", "macro_sensitive", "supply_chain", "competitor"):
        # broad-association types need corroboration to rise above background.
        if corroboration_level in ("official", "market_confirmed", "corroborated", "multi_source"):
            return "probable_catalyst"
        return "candidate_catalyst" if corroboration_level == "single_source" else "background_theme"
    if link_type == "direct_mention":
        if corroboration_level in ("official",):
            return "probable_catalyst"
        if corroboration_level in ("corroborated", "multi_source", "market_confirmed"):
            return "probable_catalyst"
        return "candidate_catalyst"
    # entity_profile / owner_alias
    return "candidate_catalyst" if corroboration_level not in ("none", "") else "background_theme"


def build_entry(*, symbol: str, event_id: Optional[str], link_type: str,
                matched_terms: Optional[List[str]] = None,
                source_family: Optional[str] = None, source_tier: Optional[str] = None,
                corroboration_level: str = "single_source", confidence: float = 0.3,
                why_ja: str = "", event_after_move: bool = False,
                now_iso: Optional[str] = None) -> Dict[str, Any]:
    """Pure: normalise one CAOS association into an audit entry. NEVER accepts or
    stores article full text — only metadata. triggerRole is derived, not trusted."""
    lt = link_type if link_type in _LINK_TYPES else "theme"
    role = _trigger_role(link_type=lt, corroboration_level=corroboration_level,
                         event_after_move=event_after_move)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "asOf": now_iso,
        "symbol": str(symbol or "").upper(),
        "eventId": event_id,
        "linkType": lt,
        "matchedTerms": list(matched_terms or [])[:12],
        "sourceFamily": source_family,
        "sourceTier": source_tier,
        "corroborationLevel": corroboration_level,
        "triggerRole": role,
        "confidence": round(max(0.0, min(1.0, float(confidence or 0.0))), 3),
        "whyJa": (why_ja or "")[:280],          # short rationale only, never full text
        "nonCausalityCaveatJa": _NON_CAUSAL_CAVEAT,
    }


def record(entry: Dict[str, Any]) -> Dict[str, Any]:
    """Append a normalised entry to the capped ring buffer."""
    _TRAIL.append(entry)
    if len(_TRAIL) > _MAX:
        del _TRAIL[:-_MAX]
    return entry


def record_association(**kw) -> Dict[str, Any]:
    """Convenience: build_entry(**kw) then record()."""
    return record(build_entry(**kw))


def snapshot(symbol: Optional[str] = None, limit: int = 100) -> Dict[str, Any]:
    rows = _TRAIL
    if symbol:
        s = str(symbol).upper()
        rows = [r for r in rows if r.get("symbol") == s]
    rows = list(reversed(rows))[:max(1, int(limit))]
    return {"schemaVersion": SCHEMA_VERSION, "count": len(rows), "items": rows}


def clear() -> None:
    _TRAIL.clear()
