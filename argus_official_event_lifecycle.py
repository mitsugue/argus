"""ARGUS V11.3 — Official Event Lifecycle (pure).

Official disclosures are not one-off headlines: each becomes a lifecycle-tracked
research event — disclosure → EventCard → Evidence Pack → judgment → market reaction
→ follow-ups (1d/3d/5d) → scoring → learning memory.

Pure + deterministic + serializable. No fetching, no LLM. Discipline baked in:
  * a title alone confirms a FACT (fact_only), never a price cause;
  * MATERIAL categories may become an official_catalyst CANDIDATE (probable_catalyst);
  * confirmed_cause requires BOTH timing consistency AND market confirmation;
  * a disclosure that post-dates the move can never be the immediate trigger;
  * missing market data keeps market_reaction_pending — never fabricated.
"""
import hashlib
from typing import Any, Dict, List, Optional

SCHEMA_VERSION = "official-event-lifecycle-v1"

MATERIAL_CATEGORIES = {
    "guidance_down", "guidance_up", "dividend_cut", "dividend_up", "buyback",
    "dilution", "impairment", "special_loss", "restatement", "delisting",
    "audit_issue", "insolvency",
}

STAGES = ["discovered", "classified", "eventcard_created", "judged",
          "market_reaction_pending", "market_reaction_observed",
          "followup_1d", "followup_3d", "followup_5d", "scored"]

_WINDOWS = ("same_day", "next_session", "day3", "day5")
# deterministic market-confirmation thresholds (abs %):
_CONFIRM_MOVE_PCT = 2.0
_CONFIRM_REL_PCT = 1.5


def official_event_id(provider: str, symbol: str, disclosed_at: str, title: str) -> str:
    h = hashlib.sha256(f"{provider}|{symbol}|{disclosed_at}|{title}".encode("utf-8")).hexdigest()[:12]
    return f"oe-{str(symbol or '').upper()}-{h}"


def from_disclosure(item: Dict[str, Any], *, source: str = "tdnet",
                    provider: str = "jquants-tdnet", market: str = "JP",
                    first_seen_at: str = "", event_card_id: Optional[str] = None,
                    evidence_pack_id: Optional[str] = None) -> Dict[str, Any]:
    """Normalize ONE classified disclosure (get_tdnet_recent item shape) into a
    lifecycle record. Deterministic given inputs."""
    sym = str(item.get("code") or item.get("symbol") or "").upper()
    title = item.get("title") or ""
    disclosed = item.get("time") or item.get("disclosedAt") or ""
    material = bool(item.get("material")) or (item.get("category") in MATERIAL_CATEGORIES)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "officialEventId": official_event_id(provider, sym, disclosed, title),
        "source": source,
        "provider": provider,
        "official": bool(item.get("official", provider != "yanoshin-tdnet")),
        "symbol": sym,
        "market": market,
        "companyName": item.get("name") or item.get("company"),
        "title": title[:160],
        "category": item.get("category") or "other",
        "categoryJa": item.get("categoryJa") or "適時開示",
        "material": material,
        "sentiment": item.get("sentiment") or "unknown",
        "disclosedAt": disclosed,
        "firstSeenAt": first_seen_at,
        "eventCardId": event_card_id,
        "evidencePackId": evidence_pack_id,
        "lifecycleStage": "classified",
        "marketReaction": {"sameDay": {}, "nextSession": {}, "day3": {}, "day5": {}},
        "causeStatus": ("probable_catalyst" if material else "fact_only"),
        "missingConfirmations": ["market_reaction:same_day", "market_reaction:next_session"],
        "decisionRefs": [],
        "scoringRefs": [],
    }


def build_market_reaction(*, window: str, observed_at: str,
                          price_move_pct: Optional[float] = None,
                          volume_ratio: Optional[float] = None,
                          relative_to_index_pct: Optional[float] = None,
                          peer_basket_move_pct: Optional[float] = None) -> Dict[str, Any]:
    """One reaction snapshot. marketConfirmed is DERIVED (deterministic thresholds),
    and every missing input is stated in limitationsJa — never fabricated."""
    if window not in _WINDOWS:
        window = "same_day"
    lims: List[str] = []
    if price_move_pct is None:
        lims.append("価格データ未取得")
    if volume_ratio is None:
        lims.append("出来高比未取得")
    if relative_to_index_pct is None:
        lims.append("指数相対未取得")
    if peer_basket_move_pct is None:
        lims.append("同業比較未取得")
    confirmed = bool(
        (price_move_pct is not None and abs(price_move_pct) >= _CONFIRM_MOVE_PCT) or
        (relative_to_index_pct is not None and abs(relative_to_index_pct) >= _CONFIRM_REL_PCT))
    return {"window": window, "observedAt": observed_at,
            "priceMovePct": price_move_pct, "volumeRatio": volume_ratio,
            "relativeToIndexPct": relative_to_index_pct,
            "peerBasketMovePct": peer_basket_move_pct,
            "marketConfirmed": confirmed, "limitationsJa": lims}


_WINDOW_KEY = {"same_day": "sameDay", "next_session": "nextSession",
               "day3": "day3", "day5": "day5"}


def apply_market_reaction(record: Dict[str, Any], reaction: Dict[str, Any],
                          *, move_started_at: Optional[str] = None) -> Dict[str, Any]:
    """Attach a reaction snapshot and advance the lifecycle + causeStatus. Returns a
    NEW record (never mutates). Discipline:
      * disclosure AFTER the move → can never be confirmed_cause (timing violation);
      * material + timing-ok + marketConfirmed → confirmed_cause;
      * all observed windows unconfirmed (same_day + next_session) → not_cause;
      * anything unobserved stays pending/probable — unknown is acceptable."""
    r = {**record, "marketReaction": {**record.get("marketReaction", {})}}
    key = _WINDOW_KEY.get(reaction.get("window"), "sameDay")
    r["marketReaction"][key] = reaction
    # missing-confirmation bookkeeping
    missing = set(r.get("missingConfirmations") or [])
    missing.discard(f"market_reaction:{reaction.get('window')}")
    # timing gate
    disclosed = str(r.get("disclosedAt") or "")
    after_move = bool(move_started_at and disclosed and disclosed > str(move_started_at))
    if after_move:
        missing.add("timing:disclosure_after_move")
    r["missingConfirmations"] = sorted(missing)
    # stage
    observed = [w for w, k in _WINDOW_KEY.items() if r["marketReaction"].get(k)]
    if "day5" in observed:
        r["lifecycleStage"] = "followup_5d"
    elif "day3" in observed:
        r["lifecycleStage"] = "followup_3d"
    elif "next_session" in observed:
        r["lifecycleStage"] = "followup_1d"
    else:
        r["lifecycleStage"] = "market_reaction_observed"
    # cause status (conservative)
    if r.get("material") and not after_move and any(
            (r["marketReaction"].get(k) or {}).get("marketConfirmed") for k in ("sameDay", "nextSession")):
        r["causeStatus"] = "confirmed_cause"
    elif after_move:
        r["causeStatus"] = "fact_only" if not r.get("material") else "probable_catalyst"
    elif (r["marketReaction"].get("sameDay") and r["marketReaction"].get("nextSession")
          and not any((r["marketReaction"].get(k) or {}).get("marketConfirmed")
                      for k in ("sameDay", "nextSession"))):
        r["causeStatus"] = "not_cause"
    return r


def evidence_ref(record: Dict[str, Any]) -> Dict[str, Any]:
    """Compact projection for the Evidence Pack (officialEventRefs entry)."""
    mr = record.get("marketReaction") or {}
    observed = [w for w, k in _WINDOW_KEY.items() if mr.get(k)]
    due = [w for w in ("next_session", "day3", "day5") if w not in observed]
    return {"officialEventId": record.get("officialEventId"),
            "title": (record.get("title") or "")[:80],
            "categoryJa": record.get("categoryJa"),
            "material": bool(record.get("material")),
            "lifecycleStage": record.get("lifecycleStage"),
            "causeStatus": record.get("causeStatus"),
            "marketConfirmed": any((mr.get(k) or {}).get("marketConfirmed") for k in mr),
            "followupDue": due}
