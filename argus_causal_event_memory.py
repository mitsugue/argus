"""ARGUS v13.5.4 — causal event memory (deterministic evidence authority).

This module is deliberately storage- and UI-light.  It defines the immutable
records, point-in-time checks, causal assessment policy, episode independence,
regime-aware analog retrieval, maturity model, and the fsynced append-only
ledger used by ``scanner.py``.

Authority boundaries:

* News Intelligence authenticates and normalizes mail.
* Market Data Truth remains point-in-time market authority.
* Prediction Ledger remains issued-decision/outcome authority.
* SDA remains the only final decision authority.
* Event Memory emits evidence only.  Its calibration mode is always SHADOW in
  this generation and no function in this module changes a live policy weight.

The ledger never stores raw mail/article bodies or private portfolio values.
"""
from __future__ import annotations

import copy
import datetime as dt
import fcntl
import hashlib
import json
import math
import os
import re
import threading
import time
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


SCHEMA_VERSION = "argus-causal-event-memory-v1"
EVENT_SCHEMA_VERSION = "argus-causal-event-v1"
ASSESSMENT_SCHEMA_VERSION = "argus-causal-assessment-v1"
OUTCOME_SCHEMA_VERSION = "argus-causal-outcome-window-v1"
REVIEW_SCHEMA_VERSION = "argus-causal-review-v1"
LINK_SCHEMA_VERSION = "argus-causal-event-link-v1"
EVENT_POLICY_VERSION = "causal-event-policy-v1"
CAUSAL_POLICY_VERSION = "causal-assessment-policy-v1"
ANALOG_POLICY_VERSION = "structured-regime-analog-v1"
CALIBRATION_GENERATION = "event-calibration-shadow-v1"
CALIBRATION_MODE = "SHADOW"

ORIGINS = ("FORWARD_LIVE", "HISTORICAL_REPLAY", "BACKFILL", "SHADOW")
EVENT_STATUSES = (
    "OPEN", "WATCHING", "PARTIALLY_CONFIRMED", "CONFIRMED", "WEAKENED",
    "INVALIDATED", "RESOLVED", "UNSCORABLE", "DATA_GATED",
)
EVIDENCE_RELATIONS = ("SUPPORTING", "CONTRADICTING", "NEUTRAL", "UNKNOWN")
ATTRIBUTION_MODES = ("SINGLE_CAUSAL", "MULTI_CAUSAL", "ATTRIBUTION_UNCERTAIN")
OUTCOME_HORIZONS = ("1H", "SESSION_CLOSE", "1D", "5D", "20D", "60D")
OUTCOME_STATUSES = ("OBSERVED", "UNSCORABLE", "DATA_GATED")
REVIEW_TYPES = ("MISSED_MATERIAL_EVENT", "FALSE_ALERT_REVIEW")

MAX_RECORD_BYTES = 96 * 1024
MAX_LEDGER_BYTES = 256 * 1024 * 1024
MAX_LEDGER_RECORDS = 100_000
MAX_ANALOG_CANDIDATES = 2_000
MAX_ANALOG_RESULTS = 12
MAX_SOURCE_REFS = 12
MAX_FACTS = 12
MAX_ENTITIES = 16
MAX_RELATED_EVENTS = 16
FLAG_RECOVERY_MIN_AGE_SECONDS = 24 * 60 * 60
EPISODE_LINK_MAX_AGE_DAYS = 120
MIN_ANALOG_SAMPLE = 3

_UTC = dt.timezone.utc
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:\-/]{0,159}$")
_LOW_VALUE_RE = re.compile(
    r"(?:welcome new user|subscription (?:change )?confirmation|"
    r"one[ -]?time password|otp|登録(?:方法|完了)|メール配信サービス|"
    r"配信登録|購読確認|パスワード|password reset)", re.I)
_PRIVATE_KEYS = {
    "quantity", "costbasis", "averageprice", "avgprice", "pnl", "profitloss",
    "purchaseprice", "holdingquantity", "ownerportfolio", "holdings",
}
_TERMINAL = {"CONFIRMED", "INVALIDATED", "RESOLVED", "UNSCORABLE"}
_APPEND_LOCK = threading.Lock()
_ANALOG_CACHE_LOCK = threading.Lock()
_ANALOG_CACHE: Dict[Tuple[Any, ...], Dict[str, Any]] = {}
_ANALOG_CACHE_STATS = {"hits": 0, "misses": 0, "lastComputeMs": None}
_ANALOG_CACHE_MAX = 256


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, allow_nan=False,
                      sort_keys=True, separators=(",", ":")).encode("utf-8")


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _parse_time(value: Any, field: str) -> dt.datetime:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field}_missing")
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field}_invalid") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field}_timezone_missing")
    return parsed.astimezone(_UTC)


def _iso(value: Any, field: str) -> str:
    parsed = _parse_time(value, field)
    return parsed.isoformat().replace("+00:00", "Z")


def _optional_iso(value: Any, field: str) -> Optional[str]:
    return None if value in (None, "") else _iso(value, field)


def _text(value: Any, maximum: int = 200) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:maximum]


def _string_list(values: Any, maximum: int, item_maximum: int = 120) -> List[str]:
    if not isinstance(values, (list, tuple, set)):
        return []
    out: List[str] = []
    for value in values:
        text = _text(value, item_maximum)
        if text and text not in out:
            out.append(text)
        if len(out) >= maximum:
            break
    return out


def _slug(value: Any) -> str:
    text = re.sub(r"[^A-Za-z0-9]+", "_", str(value or "").upper()).strip("_")
    return text[:80] or "UNKNOWN"


def _jaccard(left: Iterable[str], right: Iterable[str]) -> float:
    a, b = set(left), set(right)
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _contains_private_key(value: Any) -> bool:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if re.sub(r"[^a-z]", "", str(key).lower()) in _PRIVATE_KEYS:
                return True
            if _contains_private_key(item):
                return True
    elif isinstance(value, (list, tuple)):
        return any(_contains_private_key(item) for item in value)
    return False


def _finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) \
        and math.isfinite(float(value))


def event_memory_eligible(news_event: Mapping[str, Any]) -> Tuple[bool, str]:
    """Keep operational setup noise and INFO mail out of longitudinal memory."""
    if not isinstance(news_event, Mapping):
        return False, "malformed_event"
    if news_event.get("sdaAuthority") is not False or \
            news_event.get("authority") not in ("NEWS_RISK_EVIDENCE", None):
        return False, "untrusted_authority_shape"
    if news_event.get("severity") == "INFO":
        return False, "info_not_material"
    if news_event.get("dataInput") is True:
        return False, "routine_data_input"
    headline = _text(news_event.get("headlineJa"), 300)
    if _LOW_VALUE_RE.search(headline):
        return False, "administrative_mail"
    if news_event.get("eventType") in ("LOW_RELEVANCE", "OTHER_MARKET_RELEVANT") \
            and not (news_event.get("facts") or []):
        return False, "unstructured_low_value"
    if not news_event.get("eventId") or not news_event.get("sourceFingerprint"):
        return False, "missing_provenance"
    return True, "eligible"


_EVENT_FAMILY = {
    "IRAN": "MIDDLE_EAST_SUPPLY", "HORMUZ": "MIDDLE_EAST_SUPPLY",
    "WAR_ESCALATION": "MIDDLE_EAST_SUPPLY", "CEASEFIRE": "MIDDLE_EAST_SUPPLY",
    "SANCTIONS": "MIDDLE_EAST_SUPPLY", "OIL": "ENERGY_INFLATION",
    "COMMODITIES": "ENERGY_INFLATION", "INFLATION": "INFLATION_RATES",
    "RATES": "LONG_END_RATES", "US_FISCAL": "LONG_END_RATES",
    "FED": "MONETARY_POLICY", "CENTRAL_BANK": "MONETARY_POLICY",
    "BOJ": "JAPAN_MONETARY_POLICY", "JAPAN_POLICY": "JAPAN_MONETARY_POLICY",
    "SEMICONDUCTORS": "AI_SEMICONDUCTORS", "AI_DATACENTER": "AI_SEMICONDUCTORS",
}


def event_family(event_type: Any) -> str:
    event_type = _slug(event_type)
    return _EVENT_FAMILY.get(event_type, event_type)


def _japan_transmission_paths(family: str) -> List[str]:
    if family in ("MIDDLE_EAST_SUPPLY", "ENERGY_INFLATION"):
        return ["oil_import_costs", "jpy_inflation", "transport_chemicals_utilities_consumers"]
    if family in ("LONG_END_RATES", "INFLATION_RATES", "MONETARY_POLICY"):
        return ["us_yields", "usd_jpy", "valuation", "growth_exporters_banks"]
    if family == "AI_SEMICONDUCTORS":
        return ["ai_capex", "semiconductor_optical_cable", "power_infrastructure"]
    if family == "JAPAN_MONETARY_POLICY":
        return ["boj_policy", "jgb_yields", "usd_jpy", "banks_exporters_growth"]
    return ["global_risk", "japan_equities"]


def _hypothesis(event_id: str, key: str, chain: Sequence[str],
                directions: Mapping[str, str], markets: Sequence[str],
                horizons: Sequence[str], invalidations: Sequence[str],
                requirements: Sequence[str], confidence: str = "MEDIUM") -> Dict[str, Any]:
    body = {
        "causeEventId": event_id,
        "pathKey": key,
        "intermediateVariables": list(chain),
        "expectedDirections": dict(directions),
        "expectedAffectedMarkets": list(markets),
        "expectedTimeHorizons": list(horizons),
        "initialConfidence": confidence,
        "missingEvidence": list(requirements),
        "invalidationCriteria": list(invalidations),
        "confirmationRequirements": list(requirements),
        "initialStatus": "WATCHING",
        "initialEvidenceRefs": [],
    }
    body["hypothesisId"] = "ceh-" + _hash(body)[:24]
    return body


def causal_hypothesis_templates(event_id: str, event_type: str) -> List[Dict[str, Any]]:
    """Versioned deterministic templates; LLM prose never rewrites these."""
    family = event_family(event_type)
    if family == "MIDDLE_EAST_SUPPLY":
        return [
            _hypothesis(
                event_id, "supply_inflation_duration",
                ("event_escalation", "oil_price", "inflation_expectations",
                 "long_end_yields", "long_duration_growth"),
                {"event_escalation": "UP", "oil_price": "UP",
                 "inflation_expectations": "UP", "long_end_yields": "UP",
                 "long_duration_growth": "DOWN"},
                ("WTI", "US30Y", "QQQ", "JP_LONG_DURATION_GROWTH"),
                ("1D", "5D", "20D", "60D"),
                ("DEESCALATION_CONFIRMED", "OIL_SUPPLY_UNAFFECTED"),
                ("oil_price", "long_end_yields", "long_duration_growth")),
            _hypothesis(
                event_id, "direct_risk_aversion",
                ("event_escalation", "risk_aversion", "equity_risk"),
                {"event_escalation": "UP", "risk_aversion": "UP",
                 "equity_risk": "DOWN"},
                ("VIX", "GLOBAL_EQUITIES", "JP_EQUITIES"),
                ("1H", "SESSION_CLOSE", "1D", "5D"),
                ("DEESCALATION_CONFIRMED", "RISK_AVERSION_ABSENT"),
                ("risk_aversion", "equity_risk"), "LOW"),
        ]
    if family in ("LONG_END_RATES", "INFLATION_RATES", "ENERGY_INFLATION"):
        prefix = (("inflation_expectations", "long_end_yields")
                  if family != "LONG_END_RATES" else ("long_end_yields",))
        requirements = ("long_end_yields", "long_duration_growth")
        return [_hypothesis(
            event_id, "rates_duration_japan", prefix + (
                "usd_jpy", "long_duration_growth", "japan_style_rotation"),
            {"inflation_expectations": "UP", "long_end_yields": "UP",
             "usd_jpy": "UP", "long_duration_growth": "DOWN",
             "japan_style_rotation": "VALUE"},
            ("US30Y", "USDJPY", "QQQ", "JP_GROWTH", "JP_BANKS"),
            ("1D", "5D", "20D"),
            ("YIELD_REVERSAL_CONFIRMED", "GROWTH_RESILIENCE_CONFIRMED"),
            requirements)]
    if family in ("MONETARY_POLICY", "JAPAN_MONETARY_POLICY"):
        return [_hypothesis(
            event_id, "policy_rates_fx_japan",
            ("policy_stance", "long_end_yields", "usd_jpy", "japan_style_rotation"),
            {"policy_stance": "HAWKISH", "long_end_yields": "UP",
             "usd_jpy": "DOWN", "japan_style_rotation": "VALUE"},
            ("US30Y", "USDJPY", "JP_BANKS", "JP_EXPORTERS", "JP_GROWTH"),
            ("SESSION_CLOSE", "1D", "5D", "20D"),
            ("POLICY_REVERSAL_CONFIRMED", "MARKET_PRICING_UNCHANGED"),
            ("long_end_yields", "usd_jpy"))]
    if family == "AI_SEMICONDUCTORS":
        return [_hypothesis(
            event_id, "ai_capex_japan_supply_chain",
            ("ai_capex", "semiconductor_demand", "japan_supply_chain"),
            {"ai_capex": "UP", "semiconductor_demand": "UP",
             "japan_supply_chain": "UP"},
            ("SOX", "QQQ", "JP_SEMICONDUCTORS", "JP_POWER_INFRA"),
            ("1D", "5D", "20D", "60D"),
            ("CAPEX_CUT_CONFIRMED", "DEMAND_GUIDANCE_DOWN"),
            ("semiconductor_demand", "japan_supply_chain"))]
    return [_hypothesis(
        event_id, "generic_risk_transmission", ("event_materiality", "market_response"),
        {"event_materiality": "UP", "market_response": "RISK_OFF"},
        ("GLOBAL_EQUITIES", "JP_EQUITIES"), ("1D", "5D"),
        ("EVENT_REVERSED", "NO_MARKET_TRANSMISSION"),
        ("event_materiality", "market_response"), "LOW")]


def _regime_context(value: Any) -> Dict[str, str]:
    allowed = ("ratesRegime", "equityVolatility", "monetaryPolicyRegime",
               "growthValueRegime", "liquidityState", "oilCommodityState",
               "usdJpyRegime", "japanSessionContext")
    source = value if isinstance(value, Mapping) else {}
    return {key: _slug(source.get(key) or "UNKNOWN") for key in allowed}


def _market_context(values: Any, cutoff: dt.datetime) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for raw in values if isinstance(values, (list, tuple)) else []:
        if not isinstance(raw, Mapping):
            continue
        known_at = _iso(raw.get("knownAt"), "market_context_known_at")
        if _parse_time(known_at, "market_context_known_at") > cutoff:
            raise ValueError("future_market_context_rejected")
        value = raw.get("value")
        change = raw.get("change")
        if value is not None and not _finite_number(value):
            raise ValueError("invalid_market_context_value")
        if change is not None and not _finite_number(change):
            raise ValueError("invalid_market_context_change")
        out.append({
            "key": _slug(raw.get("key")), "value": value, "change": change,
            "unit": _text(raw.get("unit"), 16), "asOf": _text(raw.get("asOf"), 40) or None,
            "knownAt": known_at, "sourceRef": _text(raw.get("sourceRef"), 160) or None,
            "state": _slug(raw.get("state") or "UNKNOWN"),
        })
        if len(out) >= 24:
            break
    return out


def choose_episode(existing_events: Sequence[Mapping[str, Any]], *, event_id: str,
                   event_type: str, themes: Sequence[str], entities: Sequence[str],
                   countries: Sequence[str], known_at: str,
                   origin: str = "FORWARD_LIVE") -> Dict[str, Any]:
    """Structured open-episode linkage.  Headlines/outcomes are never inputs."""
    if origin not in ORIGINS:
        raise ValueError("invalid_episode_origin")
    cutoff = _parse_time(known_at, "known_at")
    family = event_family(event_type)
    best: Optional[Tuple[float, Mapping[str, Any]]] = None
    for event in list(existing_events)[-MAX_ANALOG_CANDIDATES:]:
        if event.get("eventId") == event_id or event.get("currentStatus") in _TERMINAL \
                or event.get("origin") != origin:
            continue
        try:
            age = (cutoff - _parse_time(event.get("lastKnownAt") or event.get("firstSeenAt"),
                                         "candidate_known_at")).total_seconds()
        except ValueError:
            continue
        if age < 0 or age > EPISODE_LINK_MAX_AGE_DAYS * 86400:
            continue
        same_family = event_family(event.get("eventType")) == family
        if not same_family:
            continue
        score = 0.55
        score += 0.20 * _jaccard(map(_slug, themes), map(_slug, event.get("themes") or []))
        score += 0.15 * max(
            _jaccard(map(_slug, entities), map(_slug, event.get("entities") or [])),
            _jaccard(map(_slug, countries), map(_slug, event.get("countries") or [])))
        current_paths = {h["pathKey"] for h in causal_hypothesis_templates(event_id, event_type)}
        prior_paths = {h.get("pathKey") for h in event.get("causalHypotheses") or []}
        score += 0.10 * _jaccard(current_paths, prior_paths)
        if best is None or score > best[0]:
            best = (score, event)
    if best and best[0] >= 0.65:
        return {"episodeId": best[1]["episodeId"], "linked": True,
                "similarity": round(best[0], 4),
                "relatedEventId": best[1]["eventId"]}
    seed = {"eventId": event_id, "family": family, "knownAt": known_at}
    return {"episodeId": "cep-" + _hash(seed)[:24], "linked": False,
            "similarity": None, "relatedEventId": None}


def build_event_revision(*, news_event: Mapping[str, Any], known_at: str,
                         origin: str, code_identity: str,
                         episode: Mapping[str, Any],
                         market_context: Optional[Sequence[Mapping[str, Any]]] = None,
                         regime_context: Optional[Mapping[str, Any]] = None,
                         market_truth_snapshot_ref: Optional[str] = None,
                         prior_event: Optional[Mapping[str, Any]] = None,
                         related_event_refs: Optional[Sequence[str]] = None,
                         countries: Optional[Sequence[str]] = None,
                         sectors: Optional[Sequence[str]] = None,
                         instruments: Optional[Sequence[str]] = None) -> Dict[str, Any]:
    eligible, reason = event_memory_eligible(news_event)
    if not eligible:
        raise ValueError(f"event_not_eligible:{reason}")
    if origin not in ORIGINS:
        raise ValueError("invalid_event_origin")
    cutoff_iso = _iso(known_at, "known_at")
    cutoff = _parse_time(cutoff_iso, "known_at")
    received = _optional_iso(news_event.get("sourceReceivedAt"), "received_at")
    published = _optional_iso(news_event.get("sourcePublishedAt"), "published_at")
    normalized = _iso(news_event.get("processedAt") or cutoff_iso, "normalized_at")
    for value, field in ((received, "received_at"), (published, "published_at"),
                         (normalized, "normalized_at")):
        if value and _parse_time(value, field) > cutoff:
            raise ValueError(f"future_{field}_rejected")
    event_id = _text(news_event.get("eventId"), 160)
    if not _SAFE_ID.match(event_id):
        raise ValueError("invalid_event_id")
    episode_id = _text(episode.get("episodeId"), 160)
    if not _SAFE_ID.match(episode_id):
        raise ValueError("invalid_episode_id")
    prior_revision = None
    if prior_event:
        revisions = prior_event.get("revisions") or []
        prior_revision = revisions[-1] if revisions else None
        initial_revision = revisions[0] if revisions else None
        if not initial_revision or episode_id != prior_event.get("episodeId"):
            raise ValueError("event_episode_mutation_rejected")
        if origin != initial_revision.get("origin"):
            raise ValueError("event_origin_mutation_rejected")
        if _parse_time(cutoff_iso, "known_at") < _parse_time(
                prior_revision.get("knownAt"), "prior_known_at"):
            raise ValueError("event_revision_backdating_rejected")
    event_version = int((prior_revision or {}).get("eventVersion") or 0) + 1
    initial_severity = ((prior_revision or {}).get("initialSeverity")
                        or news_event.get("severity"))
    initial_materiality = ((prior_revision or {}).get("initialMateriality")
                           or {"severity": news_event.get("severity"),
                               "reasons": _string_list(news_event.get("severityReasons"), 12)})
    hypotheses = copy.deepcopy((prior_revision or {}).get("causalHypotheses") or
                               causal_hypothesis_templates(
                                   event_id, _slug(news_event.get("eventType"))))
    first_seen = ((prior_revision or {}).get("firstSeenAt") or cutoff_iso)
    source_ref = {
        "sourceEventId": event_id,
        "sourceFamily": _slug(news_event.get("sourceFamily") or news_event.get("source")),
        "sourceTier": _slug(news_event.get("sourceTier") or "UNKNOWN"),
        "sourceFingerprint": _text(news_event.get("sourceFingerprint"), 128),
        "sourceUrl": _text(news_event.get("sourceUrl"), 500) or None,
        "receivedAt": received, "publishedAt": published, "knownAt": cutoff_iso,
    }
    contexts = _market_context(market_context or [], cutoff)
    context_ref = "cmc-" + _hash(contexts)[:24] if contexts else None
    refs = _string_list(related_event_refs, MAX_RELATED_EVENTS, 160)
    if episode.get("relatedEventId"):
        refs = _string_list(refs + [episode["relatedEventId"]], MAX_RELATED_EVENTS, 160)
    source_family = _slug(news_event.get("sourceFamily") or news_event.get("source"))
    scheduled = source_family in ("BLS", "FEDERAL_RESERVE_BOARD", "BANK_OF_JAPAN")
    surprise = None
    raw_surprise = news_event.get("surpriseInformation")
    if scheduled and isinstance(raw_surprise, Mapping) \
            and _finite_number(raw_surprise.get("actual")) \
            and _finite_number(raw_surprise.get("consensus")):
        surprise_known = _iso(raw_surprise.get("knownAt") or cutoff_iso,
                              "surprise_known_at")
        if _parse_time(surprise_known, "surprise_known_at") > cutoff:
            raise ValueError("future_surprise_information_rejected")
        surprise = {
            "actual": float(raw_surprise["actual"]),
            "consensus": float(raw_surprise["consensus"]),
            "unit": _text(raw_surprise.get("unit"), 20),
            "knownAt": surprise_known,
            "sourceRef": _text(raw_surprise.get("sourceRef"), 200) or None,
        }
    family = event_family(news_event.get("eventType"))
    body = {
        "schemaVersion": EVENT_SCHEMA_VERSION,
        "recordType": "event_revision",
        "eventId": event_id, "eventVersion": event_version,
        "episodeId": episode_id,
        "firstSeenAt": first_seen, "knownAt": cutoff_iso,
        "eventDecisionCutoff": cutoff_iso,
        "sourcePublishedAt": published, "receivedAt": received,
        "normalizedAt": normalized, "sourceRefs": [source_ref],
        "sourceTier": source_ref["sourceTier"],
        "headline": _text(news_event.get("headlineJa"), 240),
        "headlineHash": _hash(_text(news_event.get("headlineJa"), 240)),
        "eventType": _slug(news_event.get("eventType")),
        "eventFamily": family,
        "entities": _string_list(news_event.get("entities"), MAX_ENTITIES),
        "countries": _string_list(countries, 12),
        "themes": _string_list(news_event.get("themeTags"), 16),
        "sectors": _string_list(sectors or news_event.get("themeTags"), 16),
        "instruments": _string_list(instruments, 16),
        "factualClaims": _string_list(news_event.get("facts"), MAX_FACTS, 240),
        "initialSeverity": initial_severity,
        "initialMateriality": initial_materiality,
        "currentSeverity": news_event.get("severity"),
        "marketContextRef": context_ref,
        "marketTruthSnapshotRef": _text(market_truth_snapshot_ref, 160) or None,
        "marketContext": contexts,
        "regimeContext": _regime_context(regime_context),
        "causalHypotheses": hypotheses,
        "expectedTransmissionPaths": [h["pathKey"] for h in hypotheses],
        "japanTransmissionPaths": _japan_transmission_paths(family),
        "invalidationConditions": sorted({value for h in hypotheses
                                           for value in h["invalidationCriteria"]}),
        "relatedEventRefs": refs,
        "status": ((prior_event or {}).get("currentStatus")
                   or ("WATCHING" if initial_severity == "WATCH" else "OPEN")),
        "origin": origin,
        "backfill": origin == "BACKFILL",
        "scheduledEvent": scheduled,
        "eventInformationType": (
            "SURPRISE_INFORMATION" if surprise else
            "EXPECTED_EVENT" if scheduled else "UNSCHEDULED_EVENT"),
        "surpriseInformation": surprise,
        "policyVersion": EVENT_POLICY_VERSION,
        "causalPolicyVersion": CAUSAL_POLICY_VERSION,
        "analogPolicyVersion": ANALOG_POLICY_VERSION,
        "calibrationGeneration": CALIBRATION_GENERATION,
        "calibrationMode": CALIBRATION_MODE,
        "schemaGeneration": 1,
        "codeIdentity": _text(code_identity, 64),
        "authority": "EVENT_MEMORY_EVIDENCE",
        "sdaAuthority": False,
        "immutableCreatedAt": cutoff_iso,
    }
    validate_event_revision(body)
    return body


def validate_event_revision(body: Any) -> bool:
    if not isinstance(body, Mapping) or body.get("schemaVersion") != EVENT_SCHEMA_VERSION \
            or body.get("recordType") != "event_revision":
        raise ValueError("invalid_event_revision_schema")
    if _contains_private_key(body) or body.get("sdaAuthority") is not False \
            or body.get("authority") != "EVENT_MEMORY_EVIDENCE":
        raise ValueError("event_authority_or_privacy_violation")
    if body.get("origin") not in ORIGINS or body.get("status") not in EVENT_STATUSES \
            or body.get("calibrationMode") != "SHADOW":
        raise ValueError("invalid_event_policy_state")
    cutoff = _parse_time(body.get("eventDecisionCutoff"), "event_cutoff")
    if body.get("knownAt") != body.get("eventDecisionCutoff"):
        raise ValueError("event_cutoff_binding_mismatch")
    for field in ("firstSeenAt", "knownAt", "receivedAt", "sourcePublishedAt",
                  "normalizedAt", "immutableCreatedAt"):
        value = body.get(field)
        if value and _parse_time(value, field) > cutoff and field not in ():
            raise ValueError(f"future_{field}_rejected")
    for context in body.get("marketContext") or []:
        if _parse_time(context.get("knownAt"), "market_known_at") > cutoff:
            raise ValueError("future_market_context_rejected")
    if not body.get("causalHypotheses"):
        raise ValueError("event_hypothesis_missing")
    return True


def market_observations(readings: Sequence[Mapping[str, Any]], *, known_at: str,
                        source_prefix: str = "market") -> List[Dict[str, Any]]:
    """Convert bounded live readings into direction observations, not causality."""
    known = _iso(known_at, "known_at")
    variable_map = {
        "OIL": "oil_price", "WTI": "oil_price",
        "US30Y": "long_end_yields", "DGS30": "long_end_yields",
        "US10Y": "long_end_yields", "VIX": "risk_aversion",
        "USDJPY": "usd_jpy", "QQQ": "long_duration_growth",
        "GROWTH": "long_duration_growth", "EQUITY": "equity_risk",
    }
    out: List[Dict[str, Any]] = []
    for raw in readings or []:
        key = _slug(raw.get("key"))
        variable = variable_map.get(key)
        if not variable:
            continue
        change, value = raw.get("change"), raw.get("value")
        direction = "UNKNOWN"
        if _finite_number(change):
            threshold = 3.0 if key in ("US30Y", "DGS30", "US10Y") else 1.0
            if float(change) >= threshold:
                direction = "UP"
            elif float(change) <= -threshold:
                direction = "DOWN"
        if direction == "UNKNOWN" and variable == "long_end_yields" \
                and _finite_number(value) and float(value) >= 5.0 \
                and _slug(raw.get("state")) in ("HIGH", "CRITICAL"):
            direction = "UP"
        out.append({
            "variable": variable, "observedDirection": direction,
            "knownAt": known,
            "sourceRef": f"{source_prefix}:{key}:{_text(raw.get('asOf'), 40) or known}",
            "noteCode": "MARKET_OBSERVATION",
        })
    return out[:24]


def evidence_for_hypothesis(hypothesis: Mapping[str, Any],
                            observations: Sequence[Mapping[str, Any]],
                            *, event_support_ref: Optional[str] = None,
                            event_supporting: bool = False) -> List[Dict[str, Any]]:
    expected = hypothesis.get("expectedDirections") or {}
    out: List[Dict[str, Any]] = []
    if event_support_ref:
        out.append({
            "variable": "event_escalation",
            "relation": "SUPPORTING" if event_supporting else "NEUTRAL",
            "observedDirection": "UP" if event_supporting else "UNKNOWN",
            "expectedDirection": expected.get("event_escalation") or "UP",
            "knownAt": observations[0].get("knownAt") if observations else None,
            "sourceRef": event_support_ref,
            "noteCode": "RELATED_EVENT_ESCALATION" if event_supporting else "RELATED_EVENT",
        })
    for raw in observations:
        variable = _text(raw.get("variable"), 80)
        observed = _slug(raw.get("observedDirection"))
        anticipated = _slug(expected.get(variable) or "UNKNOWN")
        if observed == "UNKNOWN" or anticipated == "UNKNOWN":
            relation = "UNKNOWN"
        elif observed == anticipated:
            relation = "SUPPORTING"
        elif anticipated == "VALUE":
            relation = "UNKNOWN"
        else:
            relation = "CONTRADICTING"
        out.append({
            "variable": variable, "relation": relation,
            "observedDirection": observed, "expectedDirection": anticipated,
            "knownAt": raw.get("knownAt"),
            "sourceRef": _text(raw.get("sourceRef"), 200),
            "noteCode": _slug(raw.get("noteCode") or "MARKET_OBSERVATION"),
        })
    return out[:32]


def _hypothesis_state(event: Mapping[str, Any], hypothesis_id: str) -> str:
    for row in reversed(event.get("assessments") or []):
        if row.get("hypothesisId") == hypothesis_id:
            return row.get("status") or "WATCHING"
    for row in (event.get("causalHypotheses") or []):
        if row.get("hypothesisId") == hypothesis_id:
            return row.get("initialStatus") or "WATCHING"
    return "WATCHING"


def _aggregate_event_status(states: Sequence[str]) -> str:
    if any(state == "CONFIRMED" for state in states):
        return "CONFIRMED"
    if any(state == "PARTIALLY_CONFIRMED" for state in states):
        return "PARTIALLY_CONFIRMED"
    if states and all(state == "INVALIDATED" for state in states):
        return "INVALIDATED"
    if states and all(state in ("WEAKENED", "INVALIDATED") for state in states):
        return "WEAKENED"
    if states and all(state == "DATA_GATED" for state in states):
        return "DATA_GATED"
    if states and all(state == "UNSCORABLE" for state in states):
        return "UNSCORABLE"
    return "WATCHING"


def build_assessment(*, event: Mapping[str, Any], hypothesis_id: str,
                     evaluated_at: str, evidence: Sequence[Mapping[str, Any]],
                     attribution_mode: str = "SINGLE_CAUSAL",
                     competing_event_refs: Optional[Sequence[str]] = None,
                     code_identity: str = "") -> Dict[str, Any]:
    if attribution_mode not in ATTRIBUTION_MODES:
        raise ValueError("invalid_attribution_mode")
    evaluated = _iso(evaluated_at, "evaluated_at")
    chronology_floor = event.get("lastKnownAt") or event.get("firstSeenAt")
    for prior in event.get("assessments") or []:
        if prior.get("evaluatedAt") and _parse_time(
                prior["evaluatedAt"], "prior_assessment_at") > _parse_time(
                    chronology_floor, "chronology_floor"):
            chronology_floor = prior["evaluatedAt"]
    if _parse_time(evaluated, "evaluated_at") < _parse_time(
            chronology_floor, "chronology_floor"):
        raise ValueError("assessment_before_event")
    hypothesis = next((row for row in event.get("causalHypotheses") or []
                       if row.get("hypothesisId") == hypothesis_id), None)
    if not hypothesis:
        raise ValueError("unknown_hypothesis")
    normalized: List[Dict[str, Any]] = []
    for raw in evidence or []:
        if not isinstance(raw, Mapping):
            raise ValueError("invalid_causal_evidence")
        relation = _slug(raw.get("relation"))
        if relation not in EVIDENCE_RELATIONS:
            raise ValueError("invalid_evidence_relation")
        known = _iso(raw.get("knownAt") or evaluated, "evidence_known_at")
        if _parse_time(known, "evidence_known_at") > _parse_time(evaluated, "evaluated_at"):
            raise ValueError("future_causal_evidence_rejected")
        normalized.append({
            "variable": _text(raw.get("variable"), 80), "relation": relation,
            "observedDirection": _slug(raw.get("observedDirection") or "UNKNOWN"),
            "expectedDirection": _slug(raw.get("expectedDirection") or "UNKNOWN"),
            "knownAt": known, "sourceRef": _text(raw.get("sourceRef"), 200),
            "noteCode": _slug(raw.get("noteCode") or "UNSPECIFIED"),
        })
    previous = _hypothesis_state(event, hypothesis_id)
    supporting = {row["variable"] for row in normalized
                  if row["relation"] == "SUPPORTING"}
    contradicting = {row["variable"] for row in normalized
                      if row["relation"] == "CONTRADICTING"}
    codes = {row["noteCode"] for row in normalized}
    invalidation_codes = set(hypothesis.get("invalidationCriteria") or [])
    requirements = set(hypothesis.get("confirmationRequirements") or [])
    covered = requirements & supporting
    if not normalized:
        status = "DATA_GATED"
    elif codes & invalidation_codes:
        status = "INVALIDATED"
    elif len(contradicting) >= max(1, len(supporting) + 1):
        status = "WEAKENED"
    elif requirements and covered == requirements:
        status = "CONFIRMED"
    elif supporting:
        status = "PARTIALLY_CONFIRMED"
    else:
        status = "WATCHING"
    if attribution_mode == "ATTRIBUTION_UNCERTAIN" and status == "CONFIRMED":
        status = "PARTIALLY_CONFIRMED"
    state_by_hypothesis = {
        row["hypothesisId"]: _hypothesis_state(event, row["hypothesisId"])
        for row in event.get("causalHypotheses") or []}
    state_by_hypothesis[hypothesis_id] = status
    event_status = _aggregate_event_status(list(state_by_hypothesis.values()))
    age = (_parse_time(evaluated, "evaluated_at") -
           _parse_time(event.get("firstSeenAt"), "first_seen_at")).total_seconds()
    # One downstream move is not a recovered thesis.  A partial recovery needs
    # at least two originally declared confirmation requirements; a fully
    # covered chain may recover normally.  This blocks, for example, an old CPI
    # flag from being "recovered" merely because yields later rose for a fiscal
    # cause.
    recovery_evidence_sufficient = (status == "CONFIRMED" or len(covered) >= 2)
    flag_recovery = (age >= FLAG_RECOVERY_MIN_AGE_SECONDS
                     and previous in ("OPEN", "WATCHING", "WEAKENED", "DATA_GATED")
                     and status in ("PARTIALLY_CONFIRMED", "CONFIRMED")
                     and recovery_evidence_sufficient)
    body = {
        "schemaVersion": ASSESSMENT_SCHEMA_VERSION,
        "recordType": "hypothesis_assessment",
        "eventId": event.get("eventId"), "episodeId": event.get("episodeId"),
        "hypothesisId": hypothesis_id, "previousStatus": previous,
        "status": status, "eventStatus": event_status,
        "evaluatedAt": evaluated, "eventDecisionCutoff": event.get("eventDecisionCutoff"),
        "evidence": normalized,
        "supportingVariables": sorted(supporting),
        "contradictingVariables": sorted(contradicting),
        "confirmationRequirements": sorted(requirements),
        "requirementsCovered": sorted(covered),
        "missingEvidence": sorted(requirements - covered),
        "attributionMode": attribution_mode,
        "competingEventRefs": _string_list(competing_event_refs, 12, 160),
        "causalLanguage": "CONSISTENT_WITH",
        "flagRecovery": flag_recovery,
        "origin": event.get("origin"),
        "calibrationMode": CALIBRATION_MODE,
        "policyVersion": CAUSAL_POLICY_VERSION,
        "codeIdentity": _text(code_identity, 64),
        "authority": "EVENT_MEMORY_EVIDENCE", "sdaAuthority": False,
        "immutableCreatedAt": evaluated,
    }
    validate_assessment(body)
    return body


def validate_assessment(body: Any) -> bool:
    if not isinstance(body, Mapping) or body.get("schemaVersion") != ASSESSMENT_SCHEMA_VERSION \
            or body.get("recordType") != "hypothesis_assessment":
        raise ValueError("invalid_assessment_schema")
    if body.get("status") not in EVENT_STATUSES or \
            body.get("eventStatus") not in EVENT_STATUSES or \
            body.get("attributionMode") not in ATTRIBUTION_MODES:
        raise ValueError("invalid_assessment_state")
    if body.get("causalLanguage") != "CONSISTENT_WITH" or \
            body.get("sdaAuthority") is not False or _contains_private_key(body):
        raise ValueError("causal_language_or_privacy_violation")
    evaluated = _parse_time(body.get("evaluatedAt"), "evaluated_at")
    for row in body.get("evidence") or []:
        if row.get("relation") not in EVIDENCE_RELATIONS or \
                _parse_time(row.get("knownAt"), "evidence_known_at") > evaluated:
            raise ValueError("invalid_or_future_assessment_evidence")
    return True


def build_outcome_window(*, event: Mapping[str, Any], hypothesis_id: str,
                         horizon: str, target_at: str, observed_at: str,
                         known_at: str, metrics: Optional[Sequence[Mapping[str, Any]]],
                         truth_refs: Optional[Sequence[str]],
                         missing_reasons: Optional[Sequence[str]] = None,
                         code_identity: str = "") -> Dict[str, Any]:
    if horizon not in OUTCOME_HORIZONS:
        raise ValueError("invalid_outcome_horizon")
    known_hypotheses = {
        str(row.get("hypothesisId")) for row in event.get("causalHypotheses") or []
        if isinstance(row, Mapping)
    }
    if str(hypothesis_id) not in known_hypotheses:
        raise ValueError("outcome_hypothesis_missing")
    target = _iso(target_at, "target_at")
    observed = _iso(observed_at, "observed_at")
    known = _iso(known_at, "known_at")
    if _parse_time(target, "target_at") < _parse_time(
            event.get("firstSeenAt"), "first_seen_at") or \
            _parse_time(observed, "observed_at") < _parse_time(target, "target_at") or \
            _parse_time(observed, "observed_at") > _parse_time(known, "known_at"):
        raise ValueError("invalid_outcome_time_contract")
    normalized: List[Dict[str, Any]] = []
    for raw in metrics or []:
        if not isinstance(raw, Mapping) or not _finite_number(raw.get("value")):
            raise ValueError("invalid_outcome_metric")
        normalized.append({
            "metric": _slug(raw.get("metric")), "instrument": _slug(raw.get("instrument")),
            "value": float(raw["value"]), "unit": _text(raw.get("unit"), 20),
        })
    missing = _string_list(missing_reasons, 16, 160)
    refs = _string_list(truth_refs, 24, 200)
    if normalized and refs:
        status = "OBSERVED"
    elif missing:
        status = "UNSCORABLE"
        normalized = []
    else:
        status = "DATA_GATED"
        normalized = []
    body = {
        "schemaVersion": OUTCOME_SCHEMA_VERSION,
        "recordType": "outcome_window",
        "eventId": event.get("eventId"), "episodeId": event.get("episodeId"),
        "hypothesisId": hypothesis_id, "horizon": horizon,
        "anchorAt": event.get("firstSeenAt"), "targetAt": target,
        "observedAt": observed, "knownAt": known, "status": status,
        "metrics": normalized, "truthRefs": refs if status == "OBSERVED" else [],
        "missingReasons": missing,
        "origin": event.get("origin"),
        "forwardLiveCalibrationEvidence": (
            event.get("origin") == "FORWARD_LIVE" and status == "OBSERVED"),
        "policyInfluence": False, "calibrationMode": CALIBRATION_MODE,
        "policyVersion": CAUSAL_POLICY_VERSION,
        "codeIdentity": _text(code_identity, 64),
        "authority": "EVENT_MEMORY_EVIDENCE", "sdaAuthority": False,
        "immutableCreatedAt": known,
    }
    validate_outcome_window(body)
    return body


def validate_outcome_window(body: Any) -> bool:
    if not isinstance(body, Mapping) or body.get("schemaVersion") != OUTCOME_SCHEMA_VERSION \
            or body.get("status") not in OUTCOME_STATUSES \
            or body.get("horizon") not in OUTCOME_HORIZONS:
        raise ValueError("invalid_outcome_schema")
    if body.get("policyInfluence") is not False or body.get("sdaAuthority") is not False \
            or _contains_private_key(body):
        raise ValueError("outcome_authority_or_privacy_violation")
    if body.get("status") != "OBSERVED" and (body.get("metrics") or body.get("truthRefs")):
        raise ValueError("unscorable_outcome_has_metrics")
    if _parse_time(body.get("observedAt"), "observed_at") > _parse_time(
            body.get("knownAt"), "known_at"):
        raise ValueError("future_outcome_rejected")
    return True


def build_review(*, event: Mapping[str, Any], review_type: str,
                 finding_at: str, reason_codes: Sequence[str],
                 policy_change_warranted: bool,
                 regression_fixture_ref: Optional[str] = None,
                 evidence_refs: Optional[Sequence[str]] = None,
                 code_identity: str = "") -> Dict[str, Any]:
    if review_type not in REVIEW_TYPES:
        raise ValueError("invalid_review_type")
    finding = _iso(finding_at, "finding_at")
    if _parse_time(finding, "finding_at") < _parse_time(
            event.get("lastKnownAt") or event.get("firstSeenAt"), "event_known_at"):
        raise ValueError("review_backdating_rejected")
    body = {
        "schemaVersion": REVIEW_SCHEMA_VERSION, "recordType": "event_review",
        "reviewType": review_type, "eventId": event.get("eventId"),
        "episodeId": event.get("episodeId"), "findingAt": finding,
        "originalClassification": event.get("initialSeverity"),
        "originalEventDecisionCutoff": event.get("eventDecisionCutoff"),
        "reasonCodes": _string_list(reason_codes, 12, 120),
        "policyChangeWarranted": bool(policy_change_warranted),
        "regressionFixtureRef": _text(regression_fixture_ref, 200) or None,
        "evidenceRefs": _string_list(evidence_refs, 16, 200),
        "historyMutated": False, "policyInfluence": False,
        "calibrationMode": CALIBRATION_MODE,
        "policyVersion": CAUSAL_POLICY_VERSION,
        "codeIdentity": _text(code_identity, 64),
        "authority": "EVENT_MEMORY_EVIDENCE", "sdaAuthority": False,
        "immutableCreatedAt": finding,
    }
    if _contains_private_key(body) or not body["reasonCodes"]:
        raise ValueError("invalid_or_private_review")
    return body


def build_event_link(*, event_id: str, related_event_id: str, episode_id: str,
                     link_type: str, known_at: str, evidence_refs: Sequence[str],
                     code_identity: str = "") -> Dict[str, Any]:
    if event_id == related_event_id or link_type not in (
            "EPISODE_CONTINUATION", "SOURCE_CONFIRMATION", "REVISION_CHRONOLOGY"):
        raise ValueError("invalid_event_link")
    known = _iso(known_at, "known_at")
    body = {
        "schemaVersion": LINK_SCHEMA_VERSION, "recordType": "event_link",
        "eventId": event_id, "relatedEventId": related_event_id,
        "episodeId": episode_id, "linkType": link_type, "knownAt": known,
        "evidenceRefs": _string_list(evidence_refs, 12, 200),
        "policyVersion": EVENT_POLICY_VERSION,
        "codeIdentity": _text(code_identity, 64),
        "authority": "EVENT_MEMORY_EVIDENCE", "sdaAuthority": False,
        "immutableCreatedAt": known,
    }
    if _contains_private_key(body):
        raise ValueError("private_event_link")
    return body


def _validate_record_body(body: Mapping[str, Any]) -> bool:
    kind = body.get("recordType")
    if kind == "event_revision":
        return validate_event_revision(body)
    if kind == "hypothesis_assessment":
        return validate_assessment(body)
    if kind == "outcome_window":
        return validate_outcome_window(body)
    if kind == "event_review":
        if body.get("schemaVersion") != REVIEW_SCHEMA_VERSION:
            raise ValueError("invalid_review_schema")
        return True
    if kind == "event_link":
        if body.get("schemaVersion") != LINK_SCHEMA_VERSION:
            raise ValueError("invalid_link_schema")
        return True
    raise ValueError("unsupported_event_memory_record")


def _sealed_material(record: Mapping[str, Any]) -> Dict[str, Any]:
    return {key: value for key, value in record.items() if key != "recordHash"}


def verify_ledger_record(record: Any, *, expected_sequence: Optional[int] = None,
                         expected_previous_hash: Optional[str] = None) -> bool:
    if not isinstance(record, Mapping) or record.get("ledgerSchemaVersion") != SCHEMA_VERSION:
        return False
    try:
        if expected_sequence is not None and record.get("sequence") != expected_sequence:
            return False
        if expected_previous_hash is not None and \
                record.get("previousRecordHash") != expected_previous_hash:
            return False
        if record.get("recordHash") != _hash(_sealed_material(record)):
            return False
        body = record.get("payload")
        if not isinstance(body, Mapping) or record.get("recordId") != \
                "cemr-" + _hash(body)[:32]:
            return False
        _validate_record_body(body)
        return True
    except (TypeError, ValueError):
        return False


def _last_line(path: str) -> Optional[bytes]:
    try:
        with open(path, "rb") as handle:
            handle.seek(0, os.SEEK_END)
            position = handle.tell()
            pending = b""
            while position > 0 and len(pending) <= MAX_RECORD_BYTES * 2:
                size = min(64 * 1024, position)
                position -= size
                handle.seek(position)
                pending = handle.read(size) + pending
                lines = pending.rstrip(b"\n").split(b"\n")
                if len(lines) > 1 or position == 0:
                    return lines[-1] if lines and lines[-1] else None
    except FileNotFoundError:
        return None
    return None


def append_record(path: str, payload: Mapping[str, Any]) -> Dict[str, Any]:
    """Append one fsynced hash-chained record under a stable flock."""
    _validate_record_body(payload)
    encoded_payload = _canonical(payload)
    if len(encoded_payload) > MAX_RECORD_BYTES:
        raise ValueError("event_memory_record_too_large")
    final = os.path.abspath(path)
    os.makedirs(os.path.dirname(final), exist_ok=True)
    lock_path = final + ".lock"
    with _APPEND_LOCK:
        lock_fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
        with os.fdopen(lock_fd, "a+b") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            raw_last = _last_line(final)
            last = None
            if raw_last:
                try:
                    last = json.loads(raw_last.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise RuntimeError("event_memory_corrupt_tail") from exc
                if not verify_ledger_record(last):
                    raise RuntimeError("event_memory_invalid_tail")
            record_id = "cemr-" + _hash(payload)[:32]
            if last and last.get("recordId") == record_id:
                return {**last, "duplicateAppendSuppressed": True}
            record = {
                "ledgerSchemaVersion": SCHEMA_VERSION,
                "sequence": int((last or {}).get("sequence") or 0) + 1,
                "previousRecordHash": (last or {}).get("recordHash"),
                "recordId": record_id,
                "payload": copy.deepcopy(dict(payload)),
            }
            record["recordHash"] = _hash(_sealed_material(record))
            encoded = _canonical(record) + b"\n"
            if len(encoded) > MAX_RECORD_BYTES:
                raise ValueError("event_memory_record_too_large")
            if int((last or {}).get("sequence") or 0) >= MAX_LEDGER_RECORDS:
                raise RuntimeError("event_memory_record_bound_reached")
            current_bytes = os.path.getsize(final) if os.path.exists(final) else 0
            if current_bytes + len(encoded) > MAX_LEDGER_BYTES:
                raise RuntimeError("event_memory_byte_bound_reached")
            with open(final, "ab", buffering=0) as handle:
                handle.write(encoded)
                os.fsync(handle.fileno())
            directory_fd = os.open(os.path.dirname(final), os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
            return record


def read_ledger(path: str) -> Dict[str, Any]:
    records: List[Dict[str, Any]] = []
    previous_hash = None
    corrupt_line = None
    try:
        if os.path.getsize(path) > MAX_LEDGER_BYTES:
            return {"status": "DATA_GATED", "reason": "ledger_byte_bound_exceeded",
                    "records": [], "corruptLine": None}
        with open(path, "rb") as handle:
            for line_number, raw in enumerate(handle, 1):
                if len(records) >= MAX_LEDGER_RECORDS:
                    return {"status": "DATA_GATED", "reason": "ledger_record_bound_exceeded",
                            "records": records, "corruptLine": None}
                try:
                    row = json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    corrupt_line = line_number
                    break
                if row.get("previousRecordHash") != previous_hash or \
                        not verify_ledger_record(
                            row, expected_sequence=line_number):
                    corrupt_line = line_number
                    break
                records.append(row)
                previous_hash = row["recordHash"]
    except FileNotFoundError:
        return {"status": "EMPTY", "reason": None, "records": [], "corruptLine": None}
    return {"status": "CORRUPT" if corrupt_line else "VERIFIED",
            "reason": "hash_chain_invalid" if corrupt_line else None,
            "records": records, "corruptLine": corrupt_line}


def empty_state() -> Dict[str, Any]:
    return {"schemaVersion": SCHEMA_VERSION, "events": {}, "episodes": {},
            "links": [], "recordIds": set(), "lastSequence": 0,
            "lastRecordHash": None, "ledgerStatus": "EMPTY"}


def fold_records(records: Sequence[Mapping[str, Any]], *, ledger_status: str = "VERIFIED") -> Dict[str, Any]:
    state = empty_state()
    state["ledgerStatus"] = ledger_status
    for record in records:
        apply_record(state, record)
    return state


def apply_record(state: Dict[str, Any], record: Mapping[str, Any]) -> bool:
    if not verify_ledger_record(record):
        raise ValueError("invalid_event_memory_record")
    if record["recordId"] in state["recordIds"]:
        return False
    payload = copy.deepcopy(record["payload"])
    kind = payload["recordType"]
    if kind == "event_revision":
        event = state["events"].setdefault(payload["eventId"], {
            "eventId": payload["eventId"], "episodeId": payload["episodeId"],
            "revisions": [], "assessments": [], "outcomes": [], "reviews": [],
            "links": [], "currentStatus": payload["status"],
        })
        if event["revisions"] and payload["eventVersion"] != \
                event["revisions"][-1]["eventVersion"] + 1:
            raise ValueError("event_revision_sequence_invalid")
        if event["revisions"] and payload["knownAt"] < \
                event["revisions"][-1]["knownAt"]:
            raise ValueError("event_revision_chronology_invalid")
        if event["revisions"] and (
                payload["firstSeenAt"] != event["revisions"][0]["firstSeenAt"] or
                payload["initialSeverity"] != event["revisions"][0]["initialSeverity"] or
                payload["causalHypotheses"] != event["revisions"][0]["causalHypotheses"] or
                payload["episodeId"] != event["episodeId"] or
                payload["origin"] != event["revisions"][0]["origin"]):
            raise ValueError("event_history_mutation_rejected")
        event["revisions"].append(payload)
        event["currentStatus"] = payload["status"]
        episode = state["episodes"].setdefault(payload["episodeId"], {
            "episodeId": payload["episodeId"], "eventIds": [],
            "origin": payload["origin"], "firstSeenAt": payload["firstSeenAt"],
        })
        if episode["origin"] != payload["origin"]:
            raise ValueError("episode_origin_mismatch")
        if payload["eventId"] not in episode["eventIds"]:
            episode["eventIds"].append(payload["eventId"])
    elif kind == "hypothesis_assessment":
        event = state["events"].get(payload["eventId"])
        if not event:
            raise ValueError("assessment_event_missing")
        event["assessments"].append(payload)
        event["currentStatus"] = payload["eventStatus"]
    elif kind == "outcome_window":
        event = state["events"].get(payload["eventId"])
        if not event:
            raise ValueError("outcome_event_missing")
        event["outcomes"].append(payload)
    elif kind == "event_review":
        event = state["events"].get(payload["eventId"])
        if not event:
            raise ValueError("review_event_missing")
        event["reviews"].append(payload)
    elif kind == "event_link":
        state["links"].append(payload)
        for event_id in (payload["eventId"], payload["relatedEventId"]):
            if event_id in state["events"]:
                state["events"][event_id]["links"].append(payload)
    state["recordIds"].add(record["recordId"])
    state["lastSequence"] = record["sequence"]
    state["lastRecordHash"] = record["recordHash"]
    return True


def event_view(event: Mapping[str, Any]) -> Dict[str, Any]:
    revisions = event.get("revisions") or []
    if not revisions:
        raise ValueError("event_revision_missing")
    first, latest = revisions[0], revisions[-1]
    source_refs: List[Dict[str, Any]] = []
    for revision in revisions:
        for source in revision.get("sourceRefs") or []:
            if source.get("sourceFingerprint") not in {
                    row.get("sourceFingerprint") for row in source_refs}:
                source_refs.append(source)
    hypothesis_states = {
        row["hypothesisId"]: _hypothesis_state(event, row["hypothesisId"])
        for row in first.get("causalHypotheses") or []}
    recoveries = [row for row in event.get("assessments") or [] if row.get("flagRecovery")]
    return {
        "eventId": event["eventId"], "episodeId": event["episodeId"],
        "eventVersion": latest["eventVersion"], "firstSeenAt": first["firstSeenAt"],
        "lastKnownAt": latest["knownAt"], "eventDecisionCutoff": first["eventDecisionCutoff"],
        "eventType": first["eventType"], "eventFamily": first["eventFamily"],
        "headline": latest["headline"], "entities": first["entities"],
        "countries": first["countries"], "themes": first["themes"],
        "sectors": first["sectors"], "instruments": first["instruments"],
        "initialSeverity": first["initialSeverity"],
        "currentSeverity": latest["currentSeverity"],
        "currentStatus": event["currentStatus"],
        "origin": first["origin"], "sourceRefs": source_refs[:MAX_SOURCE_REFS],
        "marketContextRef": first["marketContextRef"],
        "marketTruthSnapshotRef": first["marketTruthSnapshotRef"],
        "regimeContext": first["regimeContext"],
        "causalHypotheses": first["causalHypotheses"],
        "hypothesisStates": hypothesis_states,
        "relatedEventRefs": latest["relatedEventRefs"],
        "assessmentCount": len(event.get("assessments") or []),
        "outcomeWindowCount": len(event.get("outcomes") or []),
        "reviews": copy.deepcopy(event.get("reviews") or []),
        "flagRecovery": bool(recoveries),
        "latestFlagRecovery": copy.deepcopy(recoveries[-1]) if recoveries else None,
        "calibrationMode": CALIBRATION_MODE,
        "authority": "EVENT_MEMORY_EVIDENCE", "sdaAuthority": False,
    }


def event_view_at(event: Mapping[str, Any], *, as_of: str) -> Dict[str, Any]:
    """Reconstruct an event using only records knowable at ``as_of``."""
    cutoff = _parse_time(as_of, "as_of")
    revisions = [copy.deepcopy(row) for row in event.get("revisions") or []
                 if _parse_time(row["knownAt"], "revision_known_at") <= cutoff]
    if not revisions:
        raise ValueError("event_not_known_at_cutoff")
    assessments = [copy.deepcopy(row) for row in event.get("assessments") or []
                   if _parse_time(row["evaluatedAt"], "assessment_known_at") <= cutoff]
    outcomes = [copy.deepcopy(row) for row in event.get("outcomes") or []
                if _parse_time(row["knownAt"], "outcome_known_at") <= cutoff]
    reviews = [copy.deepcopy(row) for row in event.get("reviews") or []
               if _parse_time(row["findingAt"], "review_known_at") <= cutoff]
    links = [copy.deepcopy(row) for row in event.get("links") or []
             if _parse_time(row["knownAt"], "link_known_at") <= cutoff]
    status = assessments[-1]["eventStatus"] if assessments else revisions[-1]["status"]
    reconstructed = {
        "eventId": event["eventId"], "episodeId": event["episodeId"],
        "revisions": revisions, "assessments": assessments,
        "outcomes": outcomes, "reviews": reviews, "links": links,
        "currentStatus": status,
    }
    return event_view(reconstructed)


def all_event_views(state: Mapping[str, Any]) -> List[Dict[str, Any]]:
    views = [event_view(value) for value in (state.get("events") or {}).values()
             if value.get("revisions")]
    return sorted(views, key=lambda row: (row["firstSeenAt"], row["eventId"]))


def _regime_similarity(left: Mapping[str, Any], right: Mapping[str, Any]) -> float:
    keys = ("ratesRegime", "equityVolatility", "monetaryPolicyRegime",
            "growthValueRegime", "liquidityState", "oilCommodityState",
            "usdJpyRegime")
    usable = [(left.get(key), right.get(key)) for key in keys
              if left.get(key) not in (None, "UNKNOWN")
              and right.get(key) not in (None, "UNKNOWN")]
    return (sum(1 for a, b in usable if a == b) / len(usable)) if usable else 0.0


def _analog_cache_key(state: Mapping[str, Any], current: Mapping[str, Any],
                      *, as_of: str, limit: int) -> Tuple[Any, ...]:
    return (current["eventId"], current["eventVersion"], ANALOG_POLICY_VERSION,
            state.get("lastRecordHash"), _iso(as_of, "as_of"),
            max(1, min(limit, MAX_ANALOG_RESULTS)))


def _outcome_statistics_by_origin(rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    # One value per independent episode/metric/horizon. Revisions within an
    # episode replace neither episode count nor sample confidence.
    buckets: Dict[Tuple[str, str, str, str], Dict[str, float]] = {}
    for row in rows:
        origin, episode_id = row["origin"], row["episodeId"]
        for window in row.get("outcomeWindows") or []:
            if window.get("status") != "OBSERVED":
                continue
            for metric in window.get("metrics") or []:
                key = (origin, window["horizon"], metric["instrument"], metric["metric"])
                buckets.setdefault(key, {})[episode_id] = float(metric["value"])
    result: Dict[str, List[Dict[str, Any]]] = {origin: [] for origin in ORIGINS}
    for (origin, horizon, instrument, metric), by_episode in sorted(buckets.items()):
        values = sorted(by_episode.values())
        midpoint = len(values) // 2
        median = (values[midpoint] if len(values) % 2 else
                  (values[midpoint - 1] + values[midpoint]) / 2)
        result[origin].append({
            "horizon": horizon, "instrument": instrument, "metric": metric,
            "independentEpisodeCount": len(values), "median": round(median, 6),
            "negativeCount": sum(value < 0 for value in values),
            "positiveCount": sum(value > 0 for value in values),
            "zeroCount": sum(value == 0 for value in values),
        })
    return result


def analog_cache_metrics() -> Dict[str, Any]:
    with _ANALOG_CACHE_LOCK:
        return {**_ANALOG_CACHE_STATS, "entryCount": len(_ANALOG_CACHE),
                "maximumEntries": _ANALOG_CACHE_MAX,
                "keyDimensions": ["eventVersion", "analogPolicyVersion",
                                  "ledgerOutcomeGeneration", "pointInTimeCutoff"]}


def retrieve_analogs(state: Mapping[str, Any], *, event_id: str, as_of: str,
                     limit: int = MAX_ANALOG_RESULTS) -> Dict[str, Any]:
    cutoff = _parse_time(as_of, "as_of")
    current_raw = (state.get("events") or {}).get(event_id)
    if not current_raw:
        raise ValueError("current_event_missing")
    current = event_view_at(current_raw, as_of=as_of)
    cache_key = _analog_cache_key(state, current, as_of=as_of, limit=limit)
    with _ANALOG_CACHE_LOCK:
        cached = _ANALOG_CACHE.get(cache_key)
        if cached is not None:
            _ANALOG_CACHE_STATS["hits"] += 1
            return copy.deepcopy(cached)
        _ANALOG_CACHE_STATS["misses"] += 1
    started = time.perf_counter()
    current_paths = {row["pathKey"] for row in current["causalHypotheses"]}
    by_episode: Dict[str, Dict[str, Any]] = {}
    for candidate_raw in list((state.get("events") or {}).values())[-MAX_ANALOG_CANDIDATES:]:
        try:
            candidate = event_view_at(candidate_raw, as_of=as_of)
        except ValueError:
            continue
        if candidate["eventId"] == event_id or \
                _parse_time(candidate["firstSeenAt"], "candidate_first_seen") >= cutoff:
            continue
        family_match = candidate["eventFamily"] == current["eventFamily"]
        candidate_paths = {row["pathKey"] for row in candidate["causalHypotheses"]}
        path_similarity = _jaccard(current_paths, candidate_paths)
        entity_similarity = max(
            _jaccard(map(_slug, current["entities"]), map(_slug, candidate["entities"])),
            _jaccard(map(_slug, current["countries"]), map(_slug, candidate["countries"])))
        theme_similarity = _jaccard(map(_slug, current["themes"]),
                                    map(_slug, candidate["themes"]))
        regime_similarity = _regime_similarity(current["regimeContext"],
                                                candidate["regimeContext"])
        severity_similarity = 1.0 if candidate["initialSeverity"] == \
            current["initialSeverity"] else 0.0
        score = (0.30 * float(family_match) + 0.25 * path_similarity
                 + 0.10 * entity_similarity + 0.10 * theme_similarity
                 + 0.20 * regime_similarity + 0.05 * severity_similarity)
        # A text-identical but regime-mismatched event receives no hidden boost.
        if not family_match or path_similarity == 0:
            continue
        outcomes = [row for row in candidate_raw.get("outcomes") or []
                    if _parse_time(row["knownAt"], "outcome_known_at") <= cutoff]
        row = {
            "candidateEventId": candidate["eventId"],
            "episodeId": candidate["episodeId"],
            "similarity": round(score, 4),
            "regimeSimilarity": round(regime_similarity, 4),
            "eventFamilyMatch": family_match,
            "causalPathSimilarity": round(path_similarity, 4),
            "entitySimilarity": round(entity_similarity, 4),
            "themeSimilarity": round(theme_similarity, 4),
            "initialSeverity": candidate["initialSeverity"],
            "origin": candidate["origin"],
            "currentStatus": candidate["currentStatus"],
            "outcomeWindows": copy.deepcopy(outcomes),
        }
        prior = by_episode.get(candidate["episodeId"])
        if prior is None or row["similarity"] > prior["similarity"]:
            by_episode[candidate["episodeId"]] = row
    rows = sorted(by_episode.values(), key=lambda row: (
        -row["similarity"], row["candidateEventId"]))[:max(1, min(limit, MAX_ANALOG_RESULTS))]
    origin_counts = {origin: sum(1 for row in rows if row["origin"] == origin)
                     for origin in ORIGINS}
    scored = [row for row in rows if row["outcomeWindows"]]
    result = {
        "schemaVersion": "argus-causal-analog-result-v1",
        "eventId": event_id, "asOf": _iso(as_of, "as_of"),
        "cohortDefinition": "same_event_family+causal_path; one_sample_per_episode",
        "sampleSize": len(rows), "independentEpisodeCount": len(rows),
        "scoredEpisodeCount": len(scored), "missingOutcomeCount": len(rows) - len(scored),
        "originCounts": origin_counts,
        "insufficientEvidence": len(rows) < MIN_ANALOG_SAMPLE,
        "confidence": ("INSUFFICIENT" if len(rows) < MIN_ANALOG_SAMPLE
                       else "LOW" if len(rows) < 8 else "MEDIUM"),
        "analogs": rows, "policyVersion": ANALOG_POLICY_VERSION,
        "outcomeStatisticsByOrigin": _outcome_statistics_by_origin(rows),
        "selectionUsesOutcomes": False, "calibratedProbability": None,
        "authority": "EVENT_MEMORY_EVIDENCE", "sdaAuthority": False,
    }
    with _ANALOG_CACHE_LOCK:
        if len(_ANALOG_CACHE) >= _ANALOG_CACHE_MAX:
            _ANALOG_CACHE.pop(next(iter(_ANALOG_CACHE)))
        _ANALOG_CACHE[cache_key] = copy.deepcopy(result)
        _ANALOG_CACHE_STATS["lastComputeMs"] = round(
            (time.perf_counter() - started) * 1000, 3)
    return result


def event_intelligence_metrics(state: Mapping[str, Any]) -> Dict[str, Any]:
    views = all_event_views(state)
    raw_events = list((state.get("events") or {}).values())
    reviews = [review for event in raw_events for review in event.get("reviews") or []]
    assessments = [row for event in raw_events for row in event.get("assessments") or []]
    origins = {origin: sum(row["origin"] == origin for row in views) for origin in ORIGINS}
    return {
        "schemaVersion": "argus-event-intelligence-metrics-v1",
        "materialEventsSurfaced": len(views),
        "independentEpisodes": len({row["episodeId"] for row in views}),
        "highCriticalInitialEvents": sum(
            row["initialSeverity"] in ("HIGH", "CRITICAL") for row in views),
        "openEvents": sum(row["currentStatus"] not in _TERMINAL for row in views),
        "confirmedAssessments": sum(row["status"] == "CONFIRMED" for row in assessments),
        "invalidatedAssessments": sum(row["status"] == "INVALIDATED" for row in assessments),
        "flagRecoveries": sum(bool(row.get("flagRecovery")) for row in assessments),
        "missedMaterialEventReviews": sum(
            row.get("reviewType") == "MISSED_MATERIAL_EVENT" for row in reviews),
        "falseAlertReviews": sum(
            row.get("reviewType") == "FALSE_ALERT_REVIEW" for row in reviews),
        "outcomeWindows": sum(len(event.get("outcomes") or []) for event in raw_events),
        "originCounts": origins,
        "falseCausalAttributionRate": None,
        "predictionLedgerOutcomeEffect": "NOT_YET_MEASURED",
        "calibrationMode": CALIBRATION_MODE,
        "policyInfluence": False,
    }


def maturity(state: Mapping[str, Any], *, as_of: str) -> Dict[str, Any]:
    views = all_event_views(state)
    forward = [row for row in views if row["origin"] == "FORWARD_LIVE"]
    episode_ids = {row["episodeId"] for row in forward}
    resolved_ids = {row["episodeId"] for row in forward
                    if row["currentStatus"] in _TERMINAL}
    open_ids = episode_ids - resolved_ids
    days = sorted({row["firstSeenAt"][:10] for row in forward})
    span_days = 0
    if len(days) >= 2:
        span_days = (_parse_time(days[-1] + "T00:00:00Z", "last_day") -
                     _parse_time(days[0] + "T00:00:00Z", "first_day")).days + 1
    trading_span_days = 0
    if days:
        cursor = _parse_time(days[0] + "T00:00:00Z", "first_day").date()
        last = _parse_time(days[-1] + "T00:00:00Z", "last_day").date()
        while cursor <= last:
            if cursor.weekday() < 5:
                trading_span_days += 1
            cursor += dt.timedelta(days=1)
    qualified = (len(episode_ids) >= 30 and len(resolved_ids) >= 20
                 and trading_span_days >= 60)
    calibration_eligible = (len(episode_ids) >= 100 and len(resolved_ids) >= 60
                            and trading_span_days >= 120)
    return {
        "schemaVersion": "argus-event-learning-maturity-v1",
        "eventMemory": "ACTIVE",
        "forwardLiveIndependentEpisodes": len(episode_ids),
        "resolvedIndependentEpisodes": len(resolved_ids),
        "openIndependentEpisodes": len(open_ids),
        "forwardLiveCalendarSpanDays": span_days,
        "forwardLiveTradingDaySpan": trading_span_days,
        "calibration": CALIBRATION_MODE,
        "maturity": "QUALIFIED" if qualified else "INSUFFICIENT",
        "graduationEligibility": (
            "CALIBRATION_ELIGIBLE" if calibration_eligible else
            "QUALIFIED" if qualified else "SHADOW"),
        "ownerApprovalRequired": True,
        "automaticCalibrationEnabled": False,
        "walkForwardRequired": True, "holdoutRequired": True,
        "minimumIndependentEpisodes": 100,
        "minimumResolvedEpisodes": 60,
        "minimumTradingDaySpan": 120,
        "ledgerStatus": state.get("ledgerStatus") or "UNKNOWN",
        "asOf": _iso(as_of, "as_of"),
    }


def learning_observations(state: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """One stable lesson input per independent episode; email volume cannot inflate n."""
    views = all_event_views(state)
    by_episode: Dict[str, Dict[str, Any]] = {}
    for row in views:
        prior = by_episode.get(row["episodeId"])
        if prior is None or row["lastKnownAt"] > prior["lastKnownAt"]:
            by_episode[row["episodeId"]] = row
    out: List[Dict[str, Any]] = []
    for row in by_episode.values():
        status = row["currentStatus"]
        if status == "CONFIRMED":
            outcome, pending = "hit", False
        elif status == "PARTIALLY_CONFIRMED":
            outcome, pending = "partial", False
        elif status == "INVALIDATED":
            outcome, pending = "miss", False
        else:
            outcome, pending = None, True
        out.append({
            "cohortType": "eventType", "cohortKey": row["eventFamily"],
            "outcome": outcome, "pending": pending,
            "episodeId": row["episodeId"], "origin": row["origin"],
        })
    return sorted(out, key=lambda row: (row["cohortKey"], row["episodeId"]))


def active_evidence_refs(state: Mapping[str, Any], *, limit: int = 8) -> List[str]:
    """Prediction-ledger linkage only; refs do not change forecast/action weights."""
    active = [row for row in all_event_views(state)
              if row["origin"] == "FORWARD_LIVE"
              and row["currentStatus"] not in _TERMINAL]
    active.sort(key=lambda row: (row["lastKnownAt"], row["eventId"]), reverse=True)
    refs: List[str] = []
    for row in active:
        refs.append(f"causal-event:{row['eventId']}")
        for hypothesis in row["causalHypotheses"][:1]:
            refs.append(f"causal-hypothesis:{hypothesis['hypothesisId']}")
        if len(refs) >= limit:
            break
    return refs[:limit]


def compact_public_view(state: Mapping[str, Any], *, as_of: str,
                        event_limit: int = 20) -> Dict[str, Any]:
    views = all_event_views(state)
    views.sort(key=lambda row: (row["lastKnownAt"], row["eventId"]), reverse=True)
    compact = []
    for row in views[:max(1, min(event_limit, 50))]:
        compact.append({key: row[key] for key in (
            "eventId", "episodeId", "firstSeenAt", "lastKnownAt", "eventType",
            "eventFamily", "headline", "initialSeverity", "currentSeverity",
            "currentStatus", "origin", "hypothesisStates", "assessmentCount",
            "outcomeWindowCount", "flagRecovery", "calibrationMode",
            "authority", "sdaAuthority")})
    return {
        "schemaVersion": "argus-causal-event-memory-view-v1",
        "generatedAt": _iso(as_of, "as_of"),
        "eventCount": len(views), "events": compact,
        "openEvents": sum(1 for row in views if row["currentStatus"] not in _TERMINAL),
        "flagRecoveryCount": sum(1 for row in views if row["flagRecovery"]),
        "eventIntelligenceMetrics": event_intelligence_metrics(state),
        "maturity": maturity(state, as_of=as_of),
        "calibrationMode": CALIBRATION_MODE,
        "automaticCalibrationEnabled": False,
        "authority": "EVENT_MEMORY_EVIDENCE", "sdaAuthority": False,
    }
