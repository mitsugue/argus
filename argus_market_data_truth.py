"""Canonical, provider-neutral market-data truth contracts.

This module is deliberately pure and credential-free.  Provider adapters turn
their payloads into immutable observations; selection applies the repository's
explicit source policy; point-in-time queries admit only facts known by the
requested cutoff; and decision snapshots bind the exact selected and dissenting
evidence without retaining raw provider payloads.

Registering an adapter never grants it authority.  A provider becomes selectable
only through an explicit entry in ``REPOSITORY_PROVIDER_PRIORITY``.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import argus_market_clock


SCHEMA_VERSION = "argus-market-data-truth-v1"
OBSERVATION_SCHEMA_VERSION = "argus-market-observation-v1"
SELECTION_SCHEMA_VERSION = "argus-market-selection-v1"
SNAPSHOT_SCHEMA_VERSION = "argus-decision-market-snapshot-v1"
ADAPTER_OUTCOME_SCHEMA_VERSION = "argus-market-adapter-outcome-v1"
PROVENANCE_SCHEMA_VERSION = "argus-market-provenance-v1"

AUTHORITY_POLICY_ID = "repo-market-provider-priority-v1"
QUALITY_POLICY_ID = "market-truth-quality-v1"
DISAGREEMENT_POLICY_ID = "market-truth-disagreement-v1"
PIT_POLICY_ID = "known-at-revision-cutoff-v1"

FRESH = "FRESH"
DELAYED = "DELAYED"
STALE = "STALE"
UNAVAILABLE = "UNAVAILABLE"
FRESHNESS_VALUES = frozenset({FRESH, DELAYED, STALE, UNAVAILABLE})

COMPLETE = "COMPLETE"
PARTIAL = "PARTIAL"
MISSING = "MISSING"
COMPLETENESS_VALUES = frozenset({COMPLETE, PARTIAL, MISSING})

MARKETS = frozenset({"JP", "US", "FX", "CRYPTO"})
FACT_TYPES = frozenset({"QUOTE", "OHLCV_BAR", "RATE", "INDEX_PROXY", "NAV"})
ASSET_TYPES = frozenset({
    "EQUITY", "ETF", "ETF_PROXY", "CRYPTO", "FX_PAIR", "RATE", "FUND",
})

MAX_VALUE_FIELDS = 16
MAX_MISSING_FIELDS = 16
MAX_PROVENANCE_FIELDS = 16
MAX_PROVENANCE_BYTES = 4096
MAX_OBSERVATION_BYTES = 16 * 1024
MAX_INPUT_OBSERVATIONS = 8192
MAX_ADAPTER_OBSERVATIONS = 64
MAX_ADAPTER_ERRORS = 64
MAX_CANDIDATES = 8
MAX_ALTERNATES = 4
MAX_SNAPSHOT_REQUESTS = 64
MAX_DERIVED_EVIDENCE = 32
MAX_EVIDENCE_INPUTS = 32
MAX_SNAPSHOT_BYTES = 256 * 1024

_DECISION_SNAPSHOT_SEAL = object()


class _BuilderIssuedDecisionSnapshot(dict):
    """Runtime capability produced only by the canonical snapshot builder."""

    __slots__ = ("_authority_seal", "_body_digest")

# Canonical records are closed schemas.  The two deliberately extensible
# members are ``values`` (closed per fact type below) and ``provenance`` (a
# bounded scalar/list-only extension map).  A digest authenticates bytes; it
# never turns an unknown member into a trusted contract field.
_OBSERVATION_FIELDS = frozenset({
    "schemaVersion", "logicalKey", "instrument", "factType", "values",
    "observedAt", "receivedAt", "knownAt", "periodStart", "periodEnd",
    "freshness", "freshUntil", "completeness", "missingFields", "session",
    "source", "provenance", "revision", "authorityPolicyId",
    "qualityPolicyId", "pitPolicyId", "observationId",
})
_INSTRUMENT_FIELDS = frozenset({
    "instrumentId", "symbol", "market", "assetType", "currency",
})
_SOURCE_FIELDS = frozenset({"provider", "providerKey", "adapter", "sourceRef"})
_SESSION_FIELDS = frozenset({
    "market", "session", "marketDate", "isTradingDay", "calendarVersion",
    "officialCalendar", "providerStatus", "providerConflict", "providerRole",
})
_FACT_VALUE_FIELDS = {
    "QUOTE": frozenset({
        "price", "previousClose", "changeAbs", "changePct", "volume",
    }),
    "OHLCV_BAR": frozenset({
        "open", "high", "low", "close", "volume", "adjustedClose",
    }),
    "RATE": frozenset({"rate", "previousRate", "change", "changeBp"}),
    "INDEX_PROXY": frozenset({
        "price", "previousClose", "changeAbs", "changePct", "volume",
    }),
    "NAV": frozenset({"nav", "previousNav", "changeAbs", "changePct"}),
}
# A COMPLETE fact must contain its semantic core, not merely some allowed
# member.  Optional comparison/change fields do not define completeness.
_FACT_REQUIRED_VALUE_FIELDS = {
    "QUOTE": frozenset({"price"}),
    "OHLCV_BAR": frozenset({"open", "high", "low", "close", "volume"}),
    "RATE": frozenset({"rate"}),
    "INDEX_PROXY": frozenset({"price"}),
    "NAV": frozenset({"nav"}),
}
_SNAPSHOT_FIELDS = frozenset({
    "schemaVersion", "authorityPolicyId", "qualityPolicyId", "pitPolicyId",
    "decisionAt", "generatedAt", "buildIdentity", "datasetDigest",
    "selections", "derivedEvidence", "qualitySummary", "bounds", "digest",
    "snapshotId",
})
_SNAPSHOT_REQUEST_FIELDS = frozenset({
    "instrumentId", "market", "factType", "currency", "required",
})
_QUALITY_SUMMARY_FIELDS = frozenset({
    "completeness", "requiredCount", "selectedRequiredCount",
    "missingRequiredCount", "freshnessCounts", "disagreementCount",
})
_SNAPSHOT_BOUNDS_FIELDS = frozenset({
    "selectionCount", "derivedEvidenceCount", "candidateObservationCount",
    "maxSelections", "maxAlternatesPerSelection",
})
_DERIVED_EVIDENCE_FIELDS = frozenset({
    "evidenceId", "kind", "knownAt", "methodVersion",
    "inputObservationIds", "summary",
})
_ADAPTER_OUTCOME_FIELDS = frozenset({"observations", "errors"})
_ADAPTER_ERROR_FIELDS = frozenset({"code", "instrumentId", "retryable"})
_PROVENANCE_FIELDS = frozenset({"schemaVersion", "attributes"})
_PIT_PROOF_FIELDS = frozenset({
    "policyId", "status", "cutoff", "inputCount", "includedCount",
    "visibleRevisionCount", "supersededRevisionCount",
    "excludedFutureCount", "excludedUnknownKnowledgeTimeCount",
    "excludedMalformedCount", "knowledgeTimeFields", "maxKnownAt",
    "maxObservedAt", "futureRowsAdmitted", "revisionSelection",
    "admittedDatasetDigest", "proofDigest",
})
_PIT_KNOWLEDGE_TIME_FIELDS = frozenset({"knownAt", "availableFrom"})

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:\-/]{0,127}$")
_SAFE_FIELD = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
_BUILD_SHA = re.compile(r"^[0-9a-f]{40}$")
_DATASET_SHA = re.compile(r"^[0-9a-f]{64}$")


# This is the current codebase's actual authority order.  It intentionally does
# not contain a generic "JP provider" slot and does not grant authority merely
# because a new adapter is registered.
REPOSITORY_PROVIDER_PRIORITY: Dict[Tuple[str, str], Tuple[str, ...]] = {
    ("JP", "QUOTE"): ("moomoo", "jquants"),
    ("JP", "OHLCV_BAR"): ("jquants",),
    ("JP", "INDEX_PROXY"): ("moomoo", "jquants"),
    ("JP", "NAV"): ("toushin_library",),
    ("US", "QUOTE"): ("moomoo", "twelvedata", "finnhub"),
    ("US", "OHLCV_BAR"): ("twelvedata", "finnhub"),
    ("US", "INDEX_PROXY"): ("moomoo", "twelvedata", "finnhub"),
    ("FX", "QUOTE"): ("yahoo", "fred"),
    ("FX", "RATE"): ("yahoo", "fred"),
    ("CRYPTO", "QUOTE"): ("coingecko", "coinbase"),
}

_PROVIDER_ALIASES = {
    "moomoo-rt": "moomoo",
    "moomoo-bridge": "moomoo",
    "moomoo/opend": "moomoo",
    "opend": "moomoo",
    "j-quants": "jquants",
    "jquants-v2": "jquants",
    "twelve-data": "twelvedata",
    "twelve data": "twelvedata",
    "yahoo-rt": "yahoo",
    "yahoo-delayed": "yahoo",
    "fred-daily": "fred",
    "投信総合ライブラリー": "toushin_library",
    "toushin-lib": "toushin_library",
}

_FRESHNESS_ALIASES = {
    "fresh": FRESH, "live": FRESH, "realtime": FRESH, "real_time": FRESH,
    "delayed": DELAYED, "eod": DELAYED, "t-1": DELAYED, "15m": DELAYED,
    "20m": DELAYED, "stale": STALE, "expired": STALE,
    "unavailable": UNAVAILABLE, "missing": UNAVAILABLE, "mock": UNAVAILABLE,
    "offline": UNAVAILABLE, "error": UNAVAILABLE,
}


def _canonical(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    )


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _safe_text(value: Any, field: str, *, maximum: int = 128) -> str:
    # Canonical contract members are typed, not coercion surfaces.  In
    # particular, ``123`` must never become the valid identifier ``"123"`` and
    # a provider object must never gain meaning through ``__str__``.
    if not isinstance(value, str):
        raise ValueError(f"invalid_{field}")
    text = value.strip()
    if not text or len(text) > maximum:
        raise ValueError(f"invalid_{field}")
    return text


def _safe_id(value: Any, field: str) -> str:
    text = _safe_text(value, field)
    if not _SAFE_ID.fullmatch(text):
        raise ValueError(f"invalid_{field}")
    return text


def _upper_text(value: Any, field: str) -> str:
    """Canonical uppercase text without accepting non-string coercions."""
    return _safe_text(value, field).upper()


def _currency(value: Any, *, required: bool) -> Optional[str]:
    """Return a canonical currency or fail on every non-string non-null type."""
    if value is None:
        if required:
            raise ValueError("currency_required")
        return None
    normalized = _upper_text(value, "currency")
    if not re.fullmatch(r"[A-Z][A-Z0-9_]{1,15}", normalized):
        raise ValueError("invalid_currency")
    return normalized


def _build_identity(value: Any) -> str:
    """Accept only the deployed commit's canonical lowercase SHA string."""
    if type(value) is not str or not _BUILD_SHA.fullmatch(value):
        raise ValueError("invalid_build_identity")
    return value


def _selection_max_alternates(value: Any) -> int:
    """Validate the selector bound without granting authority by coercion."""
    if type(value) is not int or not 0 <= value <= MAX_ALTERNATES:
        raise ValueError("invalid_max_alternates")
    return value


def _selection_relative_tolerance(value: Any) -> Any:
    """Validate the finite numeric disagreement threshold without coercion."""
    if type(value) not in (int, float) or \
            (type(value) is float and not math.isfinite(value)) or \
            not 0 <= value <= 1:
        raise ValueError("invalid_relative_tolerance")
    return value


def _parse_time(value: Any, field: str, *, optional: bool = False) -> Optional[datetime]:
    if value is None and optional:
        return None
    if not isinstance(value, str):
        raise ValueError(f"invalid_{field}")
    text = value.strip()
    if not text and optional:
        return None
    if not text or len(text) == 10:
        raise ValueError(f"invalid_{field}")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid_{field}") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"timezone_required_{field}")
    return parsed.astimezone(timezone.utc)


def _iso(value: Any, field: str, *, optional: bool = False) -> Optional[str]:
    parsed = _parse_time(value, field, optional=optional)
    if parsed is None:
        return None
    return parsed.isoformat().replace("+00:00", "Z")


def _json_scalar(value: Any, field: str) -> Any:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError(f"boolean_{field}")
    if isinstance(value, (int, float)):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError(f"non_finite_{field}")
        return value
    if isinstance(value, str) and len(value) <= 256:
        return value
    raise ValueError(f"invalid_{field}")


def _has_exact_fields(value: Any, expected: frozenset) -> bool:
    return isinstance(value, Mapping) and set(value.keys()) == set(expected)


def _has_closed_fields(value: Any, allowed: frozenset, *, required: frozenset) -> bool:
    return isinstance(value, Mapping) and required <= set(value.keys()) <= allowed


def _values(value: Mapping[str, Any], *, fact_type: Optional[str] = None) -> Dict[str, Any]:
    if not isinstance(value, Mapping) or len(value) > MAX_VALUE_FIELDS:
        raise ValueError("invalid_values")
    if fact_type is not None and not isinstance(fact_type, str):
        raise ValueError("invalid_fact_type")
    allowed = _FACT_VALUE_FIELDS.get(fact_type.upper()) \
        if fact_type is not None else None
    out: Dict[str, Any] = {}
    for raw_key, raw_value in value.items():
        if not isinstance(raw_key, str):
            raise ValueError("invalid_value_field")
        key = raw_key
        if not _SAFE_FIELD.fullmatch(key):
            raise ValueError("invalid_value_field")
        if allowed is not None and key not in allowed:
            raise ValueError("unknown_value_field")
        if raw_value is None:
            out[key] = None
        elif isinstance(raw_value, bool) or not isinstance(
                raw_value, (int, float)):
            raise ValueError(f"invalid_value_{key}")
        elif not math.isfinite(float(raw_value)):
            raise ValueError(f"non_finite_value_{key}")
        else:
            out[key] = raw_value
    _validate_market_values(out)
    return out


def _validate_market_values(values: Mapping[str, Any]) -> None:
    for key in ("price", "open", "high", "low", "close", "previousClose", "nav"):
        value = values.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value <= 0:
            raise ValueError(f"non_positive_{key}")
    volume = values.get("volume")
    if isinstance(volume, (int, float)) and not isinstance(volume, bool) and volume < 0:
        raise ValueError("negative_volume")
    o, h, low, c = (values.get(key) for key in ("open", "high", "low", "close"))
    numeric = all(isinstance(item, (int, float)) and not isinstance(item, bool)
                  for item in (o, h, low, c))
    if numeric and (float(h) < max(float(o), float(c))
                    or float(low) > min(float(o), float(c))
                    or float(h) < float(low)):
        raise ValueError("inconsistent_ohlc")


def _validate_completeness_shape(
    fact_type: str, values: Mapping[str, Any], missing_fields: Sequence[str],
    completeness: str,
) -> None:
    """Fail closed on semantically false COMPLETE/PARTIAL/MISSING shapes."""
    required = _FACT_REQUIRED_VALUE_FIELDS[fact_type]
    missing = set(missing_fields)
    nonnull = {key for key, value in values.items() if value is not None}
    null_fields = {key for key, value in values.items() if value is None}
    if completeness == COMPLETE:
        if missing or null_fields or not required <= nonnull:
            raise ValueError("complete_observation_missing_required_values")
        return
    if completeness == PARTIAL:
        if not missing or not nonnull:
            raise ValueError("partial_observation_requires_values_and_missing_fields")
        if null_fields - missing or any(
                field in nonnull for field in missing):
            raise ValueError("partial_observation_missing_fields_mismatch")
        if not (required - nonnull) <= missing:
            raise ValueError("partial_observation_undeclared_required_missing")
        return
    if completeness == MISSING:
        if values or not required <= missing:
            raise ValueError("missing_observation_requires_declared_core_absence")
        return
    raise ValueError("invalid_completeness")


def _bounded_provenance(value: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping) or len(value) > MAX_PROVENANCE_FIELDS:
        raise ValueError("invalid_provenance")
    out: Dict[str, Any] = {}
    for raw_key, raw_value in value.items():
        if not isinstance(raw_key, str):
            raise ValueError("invalid_provenance_field")
        key = raw_key
        if not _SAFE_FIELD.fullmatch(key):
            raise ValueError("invalid_provenance_field")
        if isinstance(raw_value, list):
            if len(raw_value) > 16:
                raise ValueError("provenance_list_too_large")
            out[key] = [_json_scalar(item, f"provenance_{key}") for item in raw_value]
        else:
            out[key] = _json_scalar(raw_value, f"provenance_{key}")
    if len(_canonical(out).encode("utf-8")) > MAX_PROVENANCE_BYTES:
        raise ValueError("provenance_too_large")
    return out


def _typed_provenance(value: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """The sole extensible observation member, explicitly typed and bounded."""
    if isinstance(value, Mapping) and value.get("schemaVersion") == \
            PROVENANCE_SCHEMA_VERSION:
        if not _has_exact_fields(value, _PROVENANCE_FIELDS):
            raise ValueError("provenance_schema_not_closed")
        attributes = _bounded_provenance(value.get("attributes"))
    else:
        attributes = _bounded_provenance(value)
    return {
        "schemaVersion": PROVENANCE_SCHEMA_VERSION,
        "attributes": attributes,
    }


def provider_key(provider: Any) -> str:
    text = _safe_text(provider, "provider", maximum=80).lower().strip()
    text = _PROVIDER_ALIASES.get(text, text)
    normalized = re.sub(r"[^a-z0-9_]+", "_", text).strip("_")
    if not normalized or len(normalized) > 64:
        raise ValueError("invalid_provider")
    return normalized


def repository_provider_priority(market: str, fact_type: str) -> Tuple[str, ...]:
    key = (_upper_text(market, "market"),
           _upper_text(fact_type, "fact_type"))
    if key not in REPOSITORY_PROVIDER_PRIORITY:
        raise ValueError("unsupported_authority_scope")
    return REPOSITORY_PROVIDER_PRIORITY[key]


def repository_authority_policy() -> Dict[str, Any]:
    return {
        "policyId": AUTHORITY_POLICY_ID,
        "scopes": {
            f"{market}:{fact_type}": list(providers)
            for (market, fact_type), providers in sorted(
                REPOSITORY_PROVIDER_PRIORITY.items())
        },
        "registrationGrantsAuthority": False,
    }


def normalize_freshness(value: Any, *, completeness: str) -> str:
    raw = _safe_text(value, "freshness")
    normalized = raw.upper() if raw.upper() in FRESHNESS_VALUES else \
        _FRESHNESS_ALIASES.get(raw.lower())
    if normalized not in FRESHNESS_VALUES:
        raise ValueError("invalid_freshness")
    if completeness == MISSING:
        return UNAVAILABLE
    if normalized == UNAVAILABLE:
        raise ValueError("unavailable_requires_missing")
    return str(normalized)


def _clock_market(market: str) -> str:
    return {
        "JP": argus_market_clock.JP_EQUITY,
        "US": argus_market_clock.US_EQUITY,
        "FX": argus_market_clock.FX,
        "CRYPTO": argus_market_clock.CRYPTO,
    }[market]


def canonical_session(market: str, at: Any, *, provider_status: Optional[str] = None
                      ) -> Dict[str, Any]:
    normalized_market = _upper_text(market, "market")
    if normalized_market not in MARKETS:
        raise ValueError("invalid_market")
    if provider_status is not None:
        provider_status = _safe_text(
            provider_status, "provider_status", maximum=80)
    instant = _parse_time(at, "session_at")
    assert instant is not None
    result = argus_market_clock.market_session(
        _clock_market(normalized_market), instant,
        provider_status=provider_status,
    )
    return {
        "market": normalized_market,
        "session": result.get("session"),
        "marketDate": result.get("marketDate"),
        "isTradingDay": result.get("isTradingDay"),
        "calendarVersion": result.get("calendarVersion"),
        "officialCalendar": result.get("officialCalendar"),
        "providerStatus": result.get("providerStatus"),
        "providerConflict": bool(result.get("providerConflict")),
        "providerRole": "auxiliary_only",
    }


def _logical_key(instrument_id: str, fact_type: str, period_end: Optional[str]) -> str:
    material = {
        "instrumentId": instrument_id,
        "factType": fact_type,
        "periodEnd": period_end,
    }
    return "mdk-" + _sha(material)[:32]


def build_observation(
    *,
    instrument_id: str,
    symbol: str,
    market: str,
    asset_type: str,
    fact_type: str,
    values: Mapping[str, Any],
    provider: str,
    adapter: str,
    source_ref: str,
    observed_at: Optional[str],
    received_at: str,
    known_at: str,
    freshness: str,
    completeness: str,
    fresh_until: Optional[str] = None,
    currency: Optional[str] = None,
    missing_fields: Sequence[str] = (),
    period_start: Optional[str] = None,
    period_end: Optional[str] = None,
    revision: int = 0,
    provider_session: Optional[str] = None,
    provenance: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Build and validate one immutable canonical observation.

    ``known_at`` is the first instant this revision was allowed to influence a
    decision.  It is never inferred from ``period_end``.  Missing observations
    have no ``observed_at`` or values and remain explicitly unavailable.
    """
    instrument_id = _safe_id(instrument_id, "instrument_id")
    symbol = _safe_id(_upper_text(symbol, "symbol"), "symbol")
    market = _upper_text(market, "market")
    asset_type = _upper_text(asset_type, "asset_type")
    fact_type = _upper_text(fact_type, "fact_type")
    if market not in MARKETS:
        raise ValueError("invalid_market")
    if asset_type not in ASSET_TYPES:
        raise ValueError("invalid_asset_type")
    if fact_type not in FACT_TYPES:
        raise ValueError("invalid_fact_type")
    completeness = _upper_text(completeness, "completeness")
    if completeness not in COMPLETENESS_VALUES:
        raise ValueError("invalid_completeness")
    normalized_values = _values(values, fact_type=fact_type)
    missing = []
    for raw in missing_fields:
        if not isinstance(raw, str):
            raise ValueError("invalid_missing_field")
        field = raw
        if not _SAFE_FIELD.fullmatch(field) or field in missing or \
                field not in _FACT_VALUE_FIELDS[fact_type]:
            raise ValueError("invalid_missing_field")
        missing.append(field)
    if len(missing) > MAX_MISSING_FIELDS:
        raise ValueError("too_many_missing_fields")
    _validate_completeness_shape(
        fact_type, normalized_values, missing, completeness)

    received = _iso(received_at, "received_at")
    known = _iso(known_at, "known_at")
    observed = _iso(observed_at, "observed_at", optional=True)
    if completeness == MISSING and observed is not None:
        raise ValueError("missing_observation_has_observed_at")
    if completeness != MISSING and observed is None:
        raise ValueError("observed_at_required")
    received_dt = _parse_time(received, "received_at")
    known_dt = _parse_time(known, "known_at")
    observed_dt = _parse_time(observed, "observed_at", optional=True)
    assert received_dt is not None and known_dt is not None
    if known_dt < received_dt:
        raise ValueError("known_before_received")
    if observed_dt is not None and observed_dt > received_dt:
        # A future source timestamp is invalid evidence, never age-zero/live.
        raise ValueError("source_timestamp_future")

    normalized_freshness = normalize_freshness(
        freshness, completeness=completeness)
    until = _iso(fresh_until, "fresh_until", optional=True)
    until_dt = _parse_time(until, "fresh_until", optional=True)
    if normalized_freshness in {FRESH, DELAYED} and until_dt is None:
        raise ValueError("fresh_until_required")
    if until_dt is not None and normalized_freshness in {FRESH, DELAYED} \
            and until_dt < known_dt:
        raise ValueError("fresh_until_before_known")

    p_start = _iso(period_start, "period_start", optional=True)
    p_end = _iso(period_end, "period_end", optional=True) or observed
    start_dt = _parse_time(p_start, "period_start", optional=True)
    end_dt = _parse_time(p_end, "period_end", optional=True)
    if start_dt is not None and end_dt is not None and start_dt > end_dt:
        raise ValueError("period_inversion")
    if end_dt is not None and observed_dt is not None and end_dt > observed_dt:
        raise ValueError("period_end_after_observation")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
        raise ValueError("invalid_revision")

    currency_value = _currency(
        currency,
        required=fact_type in {"QUOTE", "OHLCV_BAR", "INDEX_PROXY", "NAV"})

    provider_display = _safe_text(provider, "provider", maximum=80)
    provider_normalized = provider_key(provider_display)
    adapter_id = _safe_id(adapter, "adapter")
    source_reference = _safe_text(source_ref, "source_ref", maximum=256)
    clock_at = observed or received
    session = canonical_session(
        market, clock_at, provider_status=provider_session)
    logical_key = _logical_key(instrument_id, fact_type, p_end)
    body: Dict[str, Any] = {
        "schemaVersion": OBSERVATION_SCHEMA_VERSION,
        "logicalKey": logical_key,
        "instrument": {
            "instrumentId": instrument_id,
            "symbol": symbol,
            "market": market,
            "assetType": asset_type,
            "currency": currency_value,
        },
        "factType": fact_type,
        "values": normalized_values,
        "observedAt": observed,
        "receivedAt": received,
        "knownAt": known,
        "periodStart": p_start,
        "periodEnd": p_end,
        "freshness": normalized_freshness,
        "freshUntil": until,
        "completeness": completeness,
        "missingFields": sorted(missing),
        "session": session,
        "source": {
            "provider": provider_display,
            "providerKey": provider_normalized,
            "adapter": adapter_id,
            "sourceRef": source_reference,
        },
        "provenance": _typed_provenance(provenance),
        "revision": revision,
        "authorityPolicyId": AUTHORITY_POLICY_ID,
        "qualityPolicyId": QUALITY_POLICY_ID,
        "pitPolicyId": PIT_POLICY_ID,
    }
    body["observationId"] = "mdo-" + _sha(body)[:32]
    if len(_canonical(body).encode("utf-8")) > MAX_OBSERVATION_BYTES:
        raise ValueError("observation_too_large")
    return body


def validate_observation(value: Any) -> Tuple[bool, str]:
    if not isinstance(value, dict):
        return False, "malformed_observation"
    try:
        if not _has_exact_fields(value, _OBSERVATION_FIELDS):
            return False, "observation_schema_not_closed"
        if value.get("schemaVersion") != OBSERVATION_SCHEMA_VERSION:
            return False, "wrong_schema"
        material = copy.deepcopy(value)
        supplied = material.pop("observationId", None)
        expected = "mdo-" + _sha(material)[:32]
        if supplied != expected:
            return False, "observation_digest_mismatch"
        if len(_canonical(value).encode("utf-8")) > MAX_OBSERVATION_BYTES:
            return False, "observation_too_large"
        instrument = value.get("instrument")
        source = value.get("source")
        if not _has_exact_fields(instrument, _INSTRUMENT_FIELDS) or not \
                _has_exact_fields(source, _SOURCE_FIELDS):
            return False, "invalid_observation_shape"
        instrument_id = _safe_id(
            instrument.get("instrumentId"), "instrument_id")
        symbol = _safe_id(instrument.get("symbol"), "symbol")
        market = _safe_text(instrument.get("market"), "market")
        asset_type = _safe_text(
            instrument.get("assetType"), "asset_type")
        fact_type = _safe_text(value.get("factType"), "fact_type")
        if instrument_id != instrument.get("instrumentId") or \
                symbol != instrument.get("symbol") or symbol != symbol.upper() or \
                market != instrument.get("market") or \
                asset_type != instrument.get("assetType") or \
                fact_type != value.get("factType"):
            return False, "invalid_instrument_types"
        if market not in MARKETS or asset_type not in ASSET_TYPES or fact_type not in FACT_TYPES:
            return False, "invalid_observation_scope"
        currency = instrument.get("currency")
        required_currency = fact_type in {
            "QUOTE", "OHLCV_BAR", "INDEX_PROXY", "NAV"}
        if _currency(currency, required=required_currency) != currency:
            return False, "invalid_currency"
        completeness = _safe_text(
            value.get("completeness"), "completeness")
        freshness = _safe_text(value.get("freshness"), "freshness")
        if completeness != value.get("completeness") or \
                freshness != value.get("freshness"):
            return False, "invalid_quality_types"
        if completeness not in COMPLETENESS_VALUES or freshness not in FRESHNESS_VALUES:
            return False, "invalid_quality"
        normalized_values = _values(value.get("values"), fact_type=fact_type)
        missing = value.get("missingFields")
        if not isinstance(missing, list) or len(missing) > MAX_MISSING_FIELDS \
                or len(missing) != len(set(missing)):
            return False, "invalid_missing_fields"
        if any(not isinstance(field, str) or
               not _SAFE_FIELD.fullmatch(field) or
               field not in _FACT_VALUE_FIELDS[fact_type]
               for field in missing):
            return False, "invalid_missing_fields"
        _validate_completeness_shape(
            fact_type, normalized_values, missing, completeness)
        if completeness == MISSING and (
                value.get("observedAt") is not None or freshness != UNAVAILABLE):
            return False, "invalid_missing_observation"

        received = _parse_time(value.get("receivedAt"), "received_at")
        known = _parse_time(value.get("knownAt"), "known_at")
        observed = _parse_time(value.get("observedAt"), "observed_at", optional=True)
        if (_iso(value.get("receivedAt"), "received_at") !=
                value.get("receivedAt") or
                _iso(value.get("knownAt"), "known_at") !=
                value.get("knownAt") or
                _iso(value.get("observedAt"), "observed_at", optional=True) !=
                value.get("observedAt")):
            return False, "noncanonical_observation_time"
        assert received is not None and known is not None
        if known < received or (observed is not None and observed > received):
            return False, "invalid_observation_time_order"
        if completeness != MISSING and observed is None:
            return False, "observed_at_required"
        fresh_until = _parse_time(value.get("freshUntil"), "fresh_until", optional=True)
        if _iso(value.get("freshUntil"), "fresh_until", optional=True) != \
                value.get("freshUntil"):
            return False, "noncanonical_observation_time"
        if freshness in {FRESH, DELAYED} and (
                fresh_until is None or fresh_until < known):
            return False, "invalid_fresh_until"
        period_start = _parse_time(value.get("periodStart"), "period_start", optional=True)
        period_end = _parse_time(value.get("periodEnd"), "period_end", optional=True)
        if (_iso(value.get("periodStart"), "period_start", optional=True) !=
                value.get("periodStart") or
                _iso(value.get("periodEnd"), "period_end", optional=True) !=
                value.get("periodEnd")):
            return False, "noncanonical_observation_time"
        if period_start is not None and period_end is not None and period_start > period_end:
            return False, "invalid_period"
        if period_end is not None and observed is not None and period_end > observed:
            return False, "invalid_period"
        revision = value.get("revision")
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
            return False, "invalid_revision"
        provider = _safe_text(
            source.get("provider"), "provider", maximum=80)
        provider_normalized = _safe_id(
            source.get("providerKey"), "provider_key")
        adapter = _safe_id(source.get("adapter"), "adapter")
        source_ref = _safe_text(
            source.get("sourceRef"), "source_ref", maximum=256)
        if provider != source.get("provider") or \
                provider_key(provider) != provider_normalized or \
                provider_normalized != source.get("providerKey"):
            return False, "invalid_provider_key"
        if adapter != source.get("adapter") or \
                source_ref != source.get("sourceRef"):
            return False, "invalid_source_types"
        if _typed_provenance(value.get("provenance")) != value.get("provenance"):
            return False, "invalid_provenance"
        if value.get("logicalKey") != _logical_key(
                instrument_id, fact_type, value.get("periodEnd")):
            return False, "logical_key_mismatch"
        if (value.get("authorityPolicyId") != AUTHORITY_POLICY_ID
                or value.get("qualityPolicyId") != QUALITY_POLICY_ID
                or value.get("pitPolicyId") != PIT_POLICY_ID):
            return False, "policy_identity_mismatch"
        session = value.get("session")
        if not _has_exact_fields(session, _SESSION_FIELDS) or \
                session.get("providerRole") != "auxiliary_only" \
                or session.get("market") != market:
            return False, "invalid_session_authority"
        required_session_strings = (
            "market", "session", "marketDate", "calendarVersion",
            "officialCalendar", "providerRole",
        )
        if any(not isinstance(session.get(field), str)
               for field in required_session_strings) or \
                not isinstance(session.get("isTradingDay"), bool) or \
                not isinstance(session.get("providerConflict"), bool) or \
                (session.get("providerStatus") is not None and not isinstance(
                    session.get("providerStatus"), str)):
            return False, "invalid_session_types"
        expected_session = canonical_session(
            market, value.get("observedAt") or value.get("receivedAt"),
            provider_status=session.get("providerStatus"))
        if session != expected_session:
            return False, "session_clock_mismatch"
        return True, "ok"
    except (TypeError, ValueError, OverflowError):
        return False, "invalid_observation"


def _observation_instant(observation: Mapping[str, Any], field: str) -> datetime:
    parsed = _parse_time(observation.get(field), field)
    assert parsed is not None
    return parsed


def freshness_at(observation: Mapping[str, Any], as_of: str) -> str:
    cutoff = _parse_time(as_of, "as_of")
    assert cutoff is not None
    base = str(observation.get("freshness") or "")
    if base in {UNAVAILABLE, STALE}:
        return base
    until = _parse_time(observation.get("freshUntil"), "fresh_until", optional=True)
    if until is None:
        return STALE
    return base if cutoff <= until else STALE


def _validated_observations(values: Iterable[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    rows = list(values or [])
    if len(rows) > MAX_INPUT_OBSERVATIONS:
        raise ValueError("too_many_observations")
    out: List[Dict[str, Any]] = []
    for row in rows:
        ok, reason = validate_observation(row)
        if not ok:
            raise ValueError(reason)
        out.append(copy.deepcopy(dict(row)))
    return out


def observations_as_of(values: Iterable[Mapping[str, Any]], as_of: str
                       ) -> List[Dict[str, Any]]:
    """Return effective provider revisions known at ``as_of``.

    Conflicting payloads claiming the same provider/logical-key/revision are
    rejected rather than resolved by input order.
    """
    cutoff = _parse_time(as_of, "as_of")
    assert cutoff is not None
    visible: List[Dict[str, Any]] = []
    seen_ids = set()
    conflicts: Dict[Tuple[str, str, int], str] = {}
    for row in _validated_observations(values):
        if row["observationId"] in seen_ids:
            continue
        seen_ids.add(row["observationId"])
        if _observation_instant(row, "knownAt") > cutoff:
            continue
        observed = _parse_time(row.get("observedAt"), "observed_at", optional=True)
        if observed is not None and observed > cutoff:
            continue
        provider = str((row.get("source") or {}).get("providerKey") or "")
        conflict_key = (str(row.get("logicalKey")), provider,
                        int(row.get("revision") or 0))
        prior = conflicts.get(conflict_key)
        if prior is not None and prior != row["observationId"]:
            raise ValueError("conflicting_revision")
        conflicts[conflict_key] = row["observationId"]
        visible.append(row)

    latest: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for row in sorted(visible, key=lambda item: (
            str(item.get("logicalKey")),
            str((item.get("source") or {}).get("providerKey")),
            int(item.get("revision") or 0),
            str(item.get("knownAt")),
            str(item.get("observationId")))):
        key = (str(row.get("logicalKey")),
               str((row.get("source") or {}).get("providerKey")))
        latest[key] = row
    return sorted(latest.values(), key=lambda item: (
        str((item.get("instrument") or {}).get("instrumentId")),
        str(item.get("factType")), str(item.get("periodEnd") or ""),
        str((item.get("source") or {}).get("providerKey")),
    ))


def _quality_entry(observation: Mapping[str, Any], as_of: str, *, rank: Optional[int],
                   eligible: bool, reason: Optional[str]) -> Dict[str, Any]:
    return {
        "observation": copy.deepcopy(dict(observation)),
        "qualityAtAsOf": {
            "freshness": freshness_at(observation, as_of),
            "completeness": observation.get("completeness"),
        },
        "authorityRank": rank,
        "selectionEligible": bool(eligible),
        "rejectionReason": reason,
    }


def _numeric_delta(left: Any, right: Any, relative_tolerance: float) -> Dict[str, Any]:
    if isinstance(left, (int, float)) and not isinstance(left, bool) \
            and isinstance(right, (int, float)) and not isinstance(right, bool):
        absolute = float(right) - float(left)
        scale = max(abs(float(left)), abs(float(right)), 1e-12)
        relative = absolute / scale
        return {
            "selectedValue": left, "alternateValue": right,
            "absoluteDelta": round(absolute, 12),
            "relativeDeltaPct": round(relative * 100.0, 9),
            "material": abs(relative) > relative_tolerance,
        }
    return {
        "selectedValue": left, "alternateValue": right,
        "absoluteDelta": None, "relativeDeltaPct": None,
        "material": left != right,
    }


def _disagreement(selected: Optional[Dict[str, Any]], alternatives: Sequence[Dict[str, Any]],
                  *, relative_tolerance: float) -> Dict[str, Any]:
    if selected is None:
        return {"policyId": DISAGREEMENT_POLICY_ID, "status": "NOT_COMPARABLE",
                "comparisons": [], "material": False}
    primary = selected["observation"]
    primary_values = primary.get("values") or {}
    comparisons = []
    any_comparable = False
    any_difference = False
    any_material = False
    for candidate in alternatives:
        alternate = candidate["observation"]
        currency_left = (primary.get("instrument") or {}).get("currency")
        currency_right = (alternate.get("instrument") or {}).get("currency")
        provider = (alternate.get("source") or {}).get("providerKey")
        if currency_left != currency_right:
            comparisons.append({
                "alternateObservationId": alternate.get("observationId"),
                "alternateProvider": provider,
                "status": "CURRENCY_MISMATCH",
                "selectedCurrency": currency_left,
                "alternateCurrency": currency_right,
                "fields": [],
            })
            any_difference = any_material = True
            continue
        fields = []
        for key in sorted(set(primary_values) & set(alternate.get("values") or {})):
            left, right = primary_values.get(key), (alternate.get("values") or {}).get(key)
            if left is None or right is None:
                continue
            any_comparable = True
            if left != right:
                delta = _numeric_delta(left, right, relative_tolerance)
                fields.append({"field": key, **delta})
                any_difference = True
                any_material = any_material or bool(delta["material"])
        observed_delta = abs((
            _observation_instant(primary, "observedAt") -
            _observation_instant(alternate, "observedAt")
        ).total_seconds()) if primary.get("observedAt") and alternate.get("observedAt") else None
        comparisons.append({
            "alternateObservationId": alternate.get("observationId"),
            "alternateProvider": provider,
            "status": "VALUE_MISMATCH" if fields else "MATCH",
            "observedAtDeltaSec": observed_delta,
            "fields": fields,
        })
    status = ("PRESENT" if any_difference else "NONE" if any_comparable or not alternatives
              else "NOT_COMPARABLE")
    return {
        "policyId": DISAGREEMENT_POLICY_ID,
        "relativeTolerance": relative_tolerance,
        "status": status,
        "comparisons": comparisons,
        "material": any_material,
    }


def _select_from_candidates(
    candidates: Sequence[Dict[str, Any]], *, market: str, fact_type: str,
    as_of: str, expected_currency: Optional[str], max_alternates: int,
    relative_tolerance: float,
) -> Dict[str, Any]:
    priorities = repository_provider_priority(market, fact_type)
    rank_by_provider = {provider: rank for rank, provider in enumerate(priorities)}
    newest_by_provider: Dict[str, Dict[str, Any]] = {}
    for row in candidates:
        provider = str((row.get("source") or {}).get("providerKey") or "")
        prior = newest_by_provider.get(provider)
        row_observed = (_observation_instant(row, "observedAt").timestamp()
                        if row.get("observedAt") is not None else float("-inf"))
        row_key = (row_observed, _observation_instant(row, "knownAt").timestamp(),
                   int(row.get("revision") or 0), str(row.get("observationId") or ""))
        prior_key = (((_observation_instant(prior, "observedAt").timestamp()
                       if prior.get("observedAt") is not None else float("-inf")),
                      _observation_instant(prior, "knownAt").timestamp(),
                      int(prior.get("revision") or 0), str(prior.get("observationId") or ""))
                     if prior else None)
        if prior_key is None or row_key > prior_key:
            newest_by_provider[provider] = row

    assessed = []
    # Omitted/None means no currency constraint.  Every present value must be a
    # real canonical string; falsy JSON values must never widen the selection.
    expected = _currency(expected_currency, required=False)
    for provider, row in newest_by_provider.items():
        rank = rank_by_provider.get(provider)
        effective_freshness = freshness_at(row, as_of)
        currency = (row.get("instrument") or {}).get("currency")
        reason = None
        if rank is None:
            reason = "provider_not_authoritative"
        elif expected and currency != expected:
            reason = "currency_mismatch"
        elif row.get("completeness") == MISSING or effective_freshness == UNAVAILABLE:
            reason = "observation_unavailable"
        eligible = reason is None
        quality_bucket = 0 if effective_freshness in {FRESH, DELAYED} else \
            1 if effective_freshness == STALE else 2
        assessed.append((quality_bucket, rank if rank is not None else 999,
                         0 if row.get("completeness") == COMPLETE else 1,
                         -_observation_instant(row, "knownAt").timestamp(),
                         row, eligible, reason, rank))
    assessed.sort(key=lambda item: item[:4])
    selected_tuple = next((item for item in assessed if item[5]), None)
    selected = (_quality_entry(selected_tuple[4], as_of, rank=selected_tuple[7],
                               eligible=True, reason=None)
                if selected_tuple else None)
    alternate_rows = [item for item in assessed
                      if selected_tuple is None or item[4]["observationId"] !=
                      selected_tuple[4]["observationId"]]
    alternates = [_quality_entry(item[4], as_of, rank=item[7], eligible=item[5], reason=item[6])
                  for item in alternate_rows[:max_alternates]]
    all_entries = ([selected] if selected else []) + alternates
    return {
        "schemaVersion": SELECTION_SCHEMA_VERSION,
        "policyId": AUTHORITY_POLICY_ID,
        "qualityPolicyId": QUALITY_POLICY_ID,
        "pitPolicyId": PIT_POLICY_ID,
        "market": market,
        "factType": fact_type,
        "asOf": _iso(as_of, "as_of"),
        "expectedCurrency": expected,
        "selectedObservationId": (
            selected["observation"]["observationId"] if selected else None),
        "selected": selected,
        "alternates": alternates,
        "candidates": all_entries[:MAX_CANDIDATES],
        "candidateCount": len(assessed),
        "candidatesTruncated": len(assessed) > len(all_entries[:MAX_CANDIDATES]),
        "freshness": (selected["qualityAtAsOf"]["freshness"] if selected else UNAVAILABLE),
        "completeness": (selected["qualityAtAsOf"]["completeness"] if selected else MISSING),
        "missingReason": None if selected else "no_authoritative_observation",
        # Rejected/unknown alternates remain visible as dissenting evidence but
        # can never become the selected fact.
        "disagreement": _disagreement(
            selected, alternates, relative_tolerance=relative_tolerance),
    }


def select_truth(
    values: Iterable[Mapping[str, Any]], *, instrument_id: str, market: str,
    fact_type: str, as_of: str, expected_currency: Optional[str] = None,
    max_alternates: int = MAX_ALTERNATES, relative_tolerance: float = 0.001,
) -> Dict[str, Any]:
    max_alternates = _selection_max_alternates(max_alternates)
    relative_tolerance = _selection_relative_tolerance(relative_tolerance)
    instrument_id = _safe_id(instrument_id, "instrument_id")
    market = _upper_text(market, "market")
    fact_type = _upper_text(fact_type, "fact_type")
    expected_currency = _currency(expected_currency, required=False)
    visible = observations_as_of(values, as_of)
    candidates = [row for row in visible
                  if (row.get("instrument") or {}).get("instrumentId") == instrument_id
                  and (row.get("instrument") or {}).get("market") == market
                  and row.get("factType") == fact_type]
    result = _select_from_candidates(
        candidates, market=market, fact_type=fact_type, as_of=as_of,
        expected_currency=expected_currency, max_alternates=max_alternates,
        relative_tolerance=relative_tolerance)
    result["instrumentId"] = instrument_id
    return result


def select_history_as_of(
    values: Iterable[Mapping[str, Any]], *, instrument_id: str, market: str,
    fact_type: str, as_of: str, expected_currency: Optional[str] = None,
    max_alternates: int = MAX_ALTERNATES,
    relative_tolerance: float = 0.001,
) -> List[Dict[str, Any]]:
    """Select one canonical provider revision for every period known by cutoff."""
    max_alternates = _selection_max_alternates(max_alternates)
    relative_tolerance = _selection_relative_tolerance(relative_tolerance)
    instrument_id = _safe_id(instrument_id, "instrument_id")
    market = _upper_text(market, "market")
    fact_type = _upper_text(fact_type, "fact_type")
    expected_currency = _currency(expected_currency, required=False)
    visible = observations_as_of(values, as_of)
    matching = [row for row in visible
                if (row.get("instrument") or {}).get("instrumentId") == instrument_id
                and (row.get("instrument") or {}).get("market") == market
                and row.get("factType") == fact_type]
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for row in matching:
        groups.setdefault(str(row.get("logicalKey")), []).append(row)
    out = [_select_from_candidates(
        rows, market=market, fact_type=fact_type, as_of=as_of,
        expected_currency=expected_currency, max_alternates=max_alternates,
        relative_tolerance=relative_tolerance) for _, rows in sorted(
            groups.items(), key=lambda item: (
            str((item[1][0] if item[1] else {}).get("periodEnd") or ""), item[0]))]
    for row in out:
        row["instrumentId"] = instrument_id
    return out


def point_in_time_rows(rows: Iterable[Mapping[str, Any]], as_of: str) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Strict legacy-row cutoff used while provider caches migrate to observations.

    A row must expose ``knownAt`` or explicit ``availableFrom``; date-only fallback
    is not silently treated as proof.  Unsafe/malformed/future rows are excluded
    and counted in the returned mechanical proof.
    """
    cutoff = _parse_time(as_of, "as_of")
    assert cutoff is not None
    source = list(rows or [])
    if len(source) > MAX_INPUT_OBSERVATIONS:
        raise ValueError("too_many_rows")
    visible: List[Tuple[str, int, datetime, Dict[str, Any]]] = []
    excluded_future = excluded_unknown = excluded_malformed = 0
    known_fields = {"knownAt": 0, "availableFrom": 0}
    max_known: Optional[datetime] = None
    max_observed: Optional[datetime] = None
    for raw in source:
        if not isinstance(raw, Mapping):
            excluded_malformed += 1
            continue
        row = copy.deepcopy(dict(raw))
        revision = row.get("revision", 0)
        known_field = "knownAt" if row.get("knownAt") else \
            "availableFrom" if row.get("availableFrom") else None
        fact_raw = row.get("observedAt") or row.get("periodEnd") or row.get("date")
        try:
            if known_field is None:
                excluded_unknown += 1
                continue
            if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
                raise ValueError("invalid_row_revision")
            # Corrections cannot inherit the original publication date.  A
            # revision needs its own exact first-known instant.
            if revision > 0 and known_field != "knownAt":
                excluded_unknown += 1
                continue
            known_raw = row.get(known_field)
            # Existing daily caches expose an explicit YYYY-MM-DD availableFrom.
            # Interpret it conservatively as end-of-day UTC, never start-of-day.
            if isinstance(known_raw, str) and len(known_raw) == 10:
                known_raw = known_raw + "T23:59:59.999999Z"
            if isinstance(fact_raw, str) and len(fact_raw) == 10:
                fact_raw = fact_raw + "T23:59:59.999999Z"
            known = _parse_time(known_raw, "row_known_at")
            observed = _parse_time(fact_raw, "row_observed_at")
            assert known is not None and observed is not None
        except (TypeError, ValueError):
            excluded_malformed += 1
            continue
        if known > cutoff or observed > cutoff:
            excluded_future += 1
            continue
        row["knownAt"] = known.isoformat().replace("+00:00", "Z")
        row["revision"] = revision
        period_key = str(row.get("date") or row.get("periodEnd")
                         or row.get("observedAt") or "")[:10]
        if len(period_key) != 10:
            excluded_malformed += 1
            continue
        known_fields[known_field] += 1
        max_known = known if max_known is None or known > max_known else max_known
        max_observed = observed if max_observed is None or observed > max_observed else max_observed
        visible.append((period_key, revision, known, row))

    # Daily replay accepts one revision per period.  Highest visible revision
    # wins; conflicting payloads claiming the same revision fail closed instead
    # of inheriting iterable/input order.
    by_period: Dict[str, Tuple[str, int, datetime, Dict[str, Any]]] = {}
    superseded = 0
    for entry in sorted(visible, key=lambda item: (item[0], item[1], item[2], _sha(item[3]))):
        period_key, revision, known, row = entry
        prior = by_period.get(period_key)
        if prior is not None and prior[1] == revision and _sha(prior[3]) != _sha(row):
            raise ValueError("conflicting_row_revision")
        if prior is not None:
            superseded += 1
        by_period[period_key] = entry
    included = [entry[3] for _, entry in sorted(by_period.items())]
    proof = {
        "policyId": PIT_POLICY_ID,
        "status": "PASS",
        "cutoff": cutoff.isoformat().replace("+00:00", "Z"),
        "inputCount": len(source),
        "includedCount": len(included),
        "visibleRevisionCount": len(visible),
        "supersededRevisionCount": superseded,
        "excludedFutureCount": excluded_future,
        "excludedUnknownKnowledgeTimeCount": excluded_unknown,
        "excludedMalformedCount": excluded_malformed,
        "knowledgeTimeFields": known_fields,
        "maxKnownAt": (max_known.isoformat().replace("+00:00", "Z") if max_known else None),
        "maxObservedAt": (max_observed.isoformat().replace("+00:00", "Z") if max_observed else None),
        "futureRowsAdmitted": False,
        "revisionSelection": "highest_visible_revision_per_period",
        "admittedDatasetDigest": _sha(included),
    }
    proof["proofDigest"] = _sha(proof)
    return included, proof


def verify_point_in_time_proof(value: Any) -> Tuple[bool, str]:
    if not isinstance(value, dict):
        return False, "malformed_pit_proof"
    try:
        if not _has_exact_fields(value, _PIT_PROOF_FIELDS):
            return False, "pit_proof_schema_not_closed"
        material = copy.deepcopy(value)
        supplied = material.pop("proofDigest", None)
        if type(supplied) is not str or not _DATASET_SHA.fullmatch(supplied):
            return False, "pit_proof_digest_mismatch"
        if supplied != _sha(material):
            return False, "pit_proof_digest_mismatch"
        if value.get("policyId") != PIT_POLICY_ID or value.get("status") != "PASS":
            return False, "pit_policy_not_proven"
        if value.get("futureRowsAdmitted") is not False:
            return False, "future_rows_admitted"
        raw_cutoff = value.get("cutoff")
        canonical_cutoff = _iso(raw_cutoff, "cutoff")
        if canonical_cutoff != raw_cutoff:
            return False, "noncanonical_pit_time"
        cutoff = _parse_time(canonical_cutoff, "cutoff")
        assert cutoff is not None
        for field in ("maxKnownAt", "maxObservedAt"):
            raw_instant = value.get(field)
            canonical_instant = _iso(
                raw_instant, field, optional=True)
            if canonical_instant != raw_instant:
                return False, "noncanonical_pit_time"
            instant = _parse_time(
                canonical_instant, field, optional=True)
            if instant is not None and instant > cutoff:
                return False, "future_row_in_proof"
        if value.get("revisionSelection") != "highest_visible_revision_per_period":
            return False, "revision_selection_unproven"
        count_fields = (
            "inputCount", "includedCount", "visibleRevisionCount",
            "supersededRevisionCount", "excludedFutureCount",
            "excludedUnknownKnowledgeTimeCount", "excludedMalformedCount",
        )
        counts = {field: value.get(field) for field in count_fields}
        if any(type(item) is not int or item < 0
               for item in counts.values()):
            return False, "invalid_pit_counts"
        if counts["inputCount"] > MAX_INPUT_OBSERVATIONS:
            return False, "invalid_pit_counts"
        if counts["visibleRevisionCount"] != (
                counts["includedCount"] + counts["supersededRevisionCount"]):
            return False, "invalid_revision_counts"
        if ((counts["visibleRevisionCount"] > 0
             and counts["includedCount"] == 0)
                or (counts["visibleRevisionCount"] == 0
                    and counts["includedCount"] != 0)):
            return False, "invalid_revision_counts"
        if counts["inputCount"] != (
                counts["visibleRevisionCount"] + counts["excludedFutureCount"]
                + counts["excludedUnknownKnowledgeTimeCount"]
                + counts["excludedMalformedCount"]):
            return False, "invalid_filter_counts"

        knowledge_counts = value.get("knowledgeTimeFields")
        if type(knowledge_counts) is not dict or not _has_exact_fields(
                knowledge_counts, _PIT_KNOWLEDGE_TIME_FIELDS) or any(
                    type(item) is not int or item < 0
                    for item in knowledge_counts.values()):
            return False, "invalid_knowledge_time_counts"
        if sum(knowledge_counts.values()) != counts["visibleRevisionCount"]:
            return False, "invalid_knowledge_time_counts"

        maxima = (value.get("maxKnownAt"), value.get("maxObservedAt"))
        if counts["visibleRevisionCount"] > 0:
            if any(item is None for item in maxima):
                return False, "missing_visible_time_maxima"
        elif any(item is not None for item in maxima):
            return False, "unexpected_visible_time_maxima"

        dataset_digest = value.get("admittedDatasetDigest")
        if type(dataset_digest) is not str or not _DATASET_SHA.fullmatch(
                dataset_digest):
            return False, "dataset_digest_missing"
        return True, "ok"
    except (TypeError, ValueError, OverflowError):
        return False, "invalid_pit_proof"


def _derived_evidence(
    values: Sequence[Mapping[str, Any]], *, cutoff: datetime, visible_ids: set,
) -> List[Dict[str, Any]]:
    if len(values) > MAX_DERIVED_EVIDENCE:
        raise ValueError("too_many_derived_evidence_rows")
    out = []
    for raw in values:
        if type(raw) is not dict or not _has_exact_fields(
                raw, _DERIVED_EVIDENCE_FIELDS):
            raise ValueError("invalid_derived_evidence")
        evidence_id = _safe_id(raw.get("evidenceId"), "evidence_id")
        kind = _safe_id(raw.get("kind"), "evidence_kind")
        method = _safe_id(raw.get("methodVersion"), "evidence_method")
        known = _iso(raw.get("knownAt"), "evidence_known_at")
        known_dt = _parse_time(known, "evidence_known_at")
        assert known_dt is not None
        if known_dt > cutoff:
            raise ValueError("future_derived_evidence")
        raw_inputs = raw.get("inputObservationIds")
        if type(raw_inputs) is not list or any(
                type(item) is not str or
                re.fullmatch(r"mdo-[0-9a-f]{32}", item) is None
                for item in raw_inputs):
            raise ValueError("invalid_evidence_inputs")
        inputs = list(raw_inputs)
        if not inputs or len(inputs) > MAX_EVIDENCE_INPUTS or \
                len(inputs) != len(set(inputs)):
            raise ValueError("invalid_evidence_inputs")
        if any(item not in visible_ids for item in inputs):
            raise ValueError("evidence_input_not_visible")
        summary_value = raw.get("summary")
        if type(summary_value) is not dict:
            raise ValueError("invalid_derived_evidence_summary")
        summary = _bounded_provenance(summary_value)
        out.append({
            "evidenceId": evidence_id, "kind": kind, "knownAt": known,
            "methodVersion": method, "inputObservationIds": sorted(inputs),
            "summary": summary,
        })
    return sorted(out, key=lambda item: (item["knownAt"], item["evidenceId"]))


def build_decision_snapshot(
    values: Iterable[Mapping[str, Any]], *, requests: Sequence[Mapping[str, Any]],
    decision_at: str, generated_at: str, build_identity: str,
    derived_evidence: Sequence[Mapping[str, Any]] = (),
) -> Dict[str, Any]:
    cutoff = _parse_time(decision_at, "decision_at")
    generated = _parse_time(generated_at, "generated_at")
    assert cutoff is not None and generated is not None
    if cutoff > generated:
        raise ValueError("future_decision_at")
    build_identity = _build_identity(build_identity)
    if not requests or len(requests) > MAX_SNAPSHOT_REQUESTS:
        raise ValueError("invalid_snapshot_requests")
    observations = _validated_observations(values)
    visible = observations_as_of(observations, decision_at)
    visible_ids = {row["observationId"] for row in visible}
    selections = []
    request_keys = set()
    required_count = 0
    for raw in requests:
        if not _has_closed_fields(
                raw, _SNAPSHOT_REQUEST_FIELDS,
                required=frozenset({"instrumentId", "market", "factType"})):
            raise ValueError("invalid_snapshot_request")
        instrument_id = _safe_id(raw.get("instrumentId"), "instrument_id")
        market = _upper_text(raw.get("market"), "market")
        fact_type = _upper_text(raw.get("factType"), "fact_type")
        if market not in MARKETS or fact_type not in FACT_TYPES:
            raise ValueError("invalid_snapshot_request_scope")
        currency = (_currency(raw.get("currency"), required=False)
                    if "currency" in raw else None)
        if "required" in raw and not isinstance(raw.get("required"), bool):
            raise ValueError("invalid_snapshot_request_required")
        required = raw.get("required", True)
        key = (instrument_id, market, fact_type, currency)
        if key in request_keys:
            raise ValueError("duplicate_snapshot_request")
        request_keys.add(key)
        required_count += int(required)
        selected = select_truth(
            observations, instrument_id=instrument_id, market=market,
            fact_type=fact_type, as_of=decision_at,
            expected_currency=currency)
        if selected.get("candidatesTruncated"):
            raise ValueError("snapshot_candidates_truncated")
        selections.append({"required": required, **selected})
    selections.sort(key=lambda row: (
        row["market"], row["instrumentId"], row["factType"],
        str(row.get("expectedCurrency") or "")))
    required = [row for row in selections if row["required"]]
    selected_required = [row for row in required if row["selected"] is not None]
    if required and len(selected_required) == len(required) and all(
            row["completeness"] == COMPLETE for row in selected_required):
        aggregate_completeness = COMPLETE
    elif not selected_required:
        aggregate_completeness = MISSING
    else:
        aggregate_completeness = PARTIAL
    freshness_counts = {value: 0 for value in sorted(FRESHNESS_VALUES)}
    for row in selections:
        freshness_counts[row["freshness"]] += 1
    selected_and_candidates = sorted({
        entry["observation"]["observationId"]
        for selection in selections
        for entry in selection.get("candidates") or []
    })
    evidence = _derived_evidence(
        list(derived_evidence), cutoff=cutoff,
        visible_ids=set(selected_and_candidates))
    material: Dict[str, Any] = {
        "schemaVersion": SNAPSHOT_SCHEMA_VERSION,
        "authorityPolicyId": AUTHORITY_POLICY_ID,
        "qualityPolicyId": QUALITY_POLICY_ID,
        "pitPolicyId": PIT_POLICY_ID,
        "decisionAt": cutoff.isoformat().replace("+00:00", "Z"),
        "generatedAt": generated.isoformat().replace("+00:00", "Z"),
        "buildIdentity": build_identity,
        "datasetDigest": _sha(selected_and_candidates),
        "selections": selections,
        "derivedEvidence": evidence,
        "qualitySummary": {
            "completeness": aggregate_completeness,
            "requiredCount": required_count,
            "selectedRequiredCount": len(selected_required),
            "missingRequiredCount": required_count - len(selected_required),
            "freshnessCounts": freshness_counts,
            "disagreementCount": sum(
                1 for row in selections
                if (row.get("disagreement") or {}).get("status") == "PRESENT"),
        },
        "bounds": {
            "selectionCount": len(selections),
            "derivedEvidenceCount": len(evidence),
            "candidateObservationCount": len(selected_and_candidates),
            "maxSelections": MAX_SNAPSHOT_REQUESTS,
            "maxAlternatesPerSelection": MAX_ALTERNATES,
        },
    }
    material["digest"] = _sha(material)
    material["snapshotId"] = "mds-" + material["digest"][:32]
    if len(_canonical(material).encode("utf-8")) > MAX_SNAPSHOT_BYTES:
        raise ValueError("snapshot_too_large")
    snapshot = _BuilderIssuedDecisionSnapshot(material)
    snapshot._authority_seal = _DECISION_SNAPSHOT_SEAL
    snapshot._body_digest = _sha(snapshot)
    return snapshot


def is_builder_issued_decision_snapshot(value: Any) -> bool:
    """Return whether ``value`` is an unmodified canonical-builder result."""
    return bool(
        isinstance(value, _BuilderIssuedDecisionSnapshot)
        and getattr(value, "_authority_seal", None) is _DECISION_SNAPSHOT_SEAL
        and getattr(value, "_body_digest", None) == _sha(value)
        and verify_decision_snapshot(value) == (True, "ok")
    )


def verify_decision_snapshot(value: Any) -> Tuple[bool, str]:
    if not isinstance(value, dict):
        return False, "malformed_snapshot"
    try:
        if not _has_exact_fields(value, _SNAPSHOT_FIELDS):
            return False, "snapshot_schema_not_closed"
        if value.get("schemaVersion") != SNAPSHOT_SCHEMA_VERSION:
            return False, "wrong_schema"
        if len(_canonical(value).encode("utf-8")) > MAX_SNAPSHOT_BYTES:
            return False, "snapshot_too_large"
        material = copy.deepcopy(value)
        supplied_id = material.pop("snapshotId", None)
        supplied_digest = material.pop("digest", None)
        expected_digest = _sha(material)
        if supplied_digest != expected_digest:
            return False, "snapshot_digest_mismatch"
        if supplied_id != "mds-" + expected_digest[:32]:
            return False, "snapshot_id_mismatch"
        raw_decision_at = value.get("decisionAt")
        raw_generated_at = value.get("generatedAt")
        canonical_decision_at = _iso(raw_decision_at, "decision_at")
        canonical_generated_at = _iso(raw_generated_at, "generated_at")
        decision = _parse_time(canonical_decision_at, "decision_at")
        generated = _parse_time(canonical_generated_at, "generated_at")
        if decision is None or generated is None or decision > generated:
            return False, "invalid_snapshot_time"
        if canonical_decision_at != raw_decision_at or \
                canonical_generated_at != raw_generated_at:
            return False, "noncanonical_snapshot_time"
        _build_identity(value.get("buildIdentity"))
        selections = value.get("selections")
        if not isinstance(selections, list) or not selections or \
                len(selections) > MAX_SNAPSHOT_REQUESTS:
            return False, "snapshot_unbounded"
        if value.get("authorityPolicyId") != AUTHORITY_POLICY_ID or \
                value.get("qualityPolicyId") != QUALITY_POLICY_ID or \
                value.get("pitPolicyId") != PIT_POLICY_ID:
            return False, "snapshot_policy_mismatch"

        selected_and_candidates = set()
        request_keys = set()
        required_count = selected_required_count = 0
        freshness_counts = {item: 0 for item in sorted(FRESHNESS_VALUES)}
        disagreement_count = 0
        normalized_selections = []
        for selection in selections:
            if not isinstance(selection, dict) or \
                    selection.get("schemaVersion") != SELECTION_SCHEMA_VERSION:
                return False, "invalid_snapshot_selection"
            if selection.get("asOf") != value.get("decisionAt") or \
                    selection.get("candidatesTruncated") is not False:
                return False, "unverifiable_snapshot_selection"
            instrument_id = _safe_id(
                selection.get("instrumentId"), "instrument_id")
            market = _safe_text(selection.get("market"), "market")
            fact_type = _safe_text(selection.get("factType"), "fact_type")
            if market not in MARKETS or fact_type not in FACT_TYPES or \
                    market != market.upper() or fact_type != fact_type.upper():
                return False, "invalid_snapshot_selection_scope"
            raw_expected_currency = selection.get("expectedCurrency")
            expected_currency = _currency(
                raw_expected_currency, required=False)
            if expected_currency != raw_expected_currency:
                return False, "invalid_snapshot_selection_currency"
            if not isinstance(selection.get("required"), bool):
                return False, "invalid_snapshot_selection_required"
            request_key = (instrument_id, market, fact_type,
                           expected_currency)
            if request_key in request_keys:
                return False, "duplicate_snapshot_selection"
            request_keys.add(request_key)
            candidates = selection.get("candidates")
            if not isinstance(candidates, list) or len(candidates) > MAX_CANDIDATES:
                return False, "invalid_snapshot_candidates"
            observations = []
            for entry in candidates:
                if not isinstance(entry, dict) or not isinstance(
                        entry.get("observation"), dict):
                    return False, "invalid_snapshot_candidate"
                observation = entry["observation"]
                valid, _ = validate_observation(observation)
                if not valid or \
                        (observation.get("instrument") or {}).get(
                            "instrumentId") != instrument_id or \
                        (observation.get("instrument") or {}).get(
                            "market") != market or \
                        observation.get("factType") != fact_type:
                    return False, "invalid_snapshot_candidate_observation"
                observations.append(observation)
                selected_and_candidates.add(observation["observationId"])
            recomputed = select_truth(
                observations, instrument_id=instrument_id, market=market,
                fact_type=fact_type, as_of=value["decisionAt"],
                expected_currency=expected_currency,
                max_alternates=MAX_ALTERNATES,
                relative_tolerance=(selection.get("disagreement") or {}).get(
                    "relativeTolerance", 0.001))
            normalized = {"required": selection.get("required"),
                          **recomputed}
            # Canonical JSON comparison is type-sensitive (`false` != `0`,
            # `true` != `1`) unlike Python mapping equality.
            if _canonical(normalized) != _canonical(selection):
                return False, "snapshot_selection_mismatch"
            normalized_selections.append(normalized)
            required = normalized["required"]
            required_count += int(required)
            selected_required_count += int(
                required and normalized.get("selected") is not None)
            freshness = normalized.get("freshness")
            if freshness not in freshness_counts:
                return False, "invalid_snapshot_freshness"
            freshness_counts[freshness] += 1
            disagreement_count += int(
                (normalized.get("disagreement") or {}).get("status") ==
                "PRESENT")

        expected_order = sorted(normalized_selections, key=lambda row: (
            row["market"], row["instrumentId"], row["factType"],
            str(row.get("expectedCurrency") or "")))
        if normalized_selections != expected_order:
            return False, "snapshot_selection_order_mismatch"
        selected_required = [row for row in normalized_selections
                             if row["required"] and row.get("selected")]
        if required_count and len(selected_required) == required_count and all(
                row["completeness"] == COMPLETE
                for row in selected_required):
            aggregate_completeness = COMPLETE
        elif not selected_required:
            aggregate_completeness = MISSING
        else:
            aggregate_completeness = PARTIAL
        expected_quality = {
            "completeness": aggregate_completeness,
            "requiredCount": required_count,
            "selectedRequiredCount": selected_required_count,
            "missingRequiredCount": required_count - selected_required_count,
            "freshnessCounts": freshness_counts,
            "disagreementCount": disagreement_count,
        }
        if not _has_exact_fields(value.get("qualitySummary"),
                                 _QUALITY_SUMMARY_FIELDS):
            return False, "snapshot_quality_schema_not_closed"
        if _canonical(value.get("qualitySummary")) != _canonical(
                expected_quality):
            return False, "snapshot_quality_summary_mismatch"
        if value.get("datasetDigest") != _sha(
                sorted(selected_and_candidates)):
            return False, "snapshot_dataset_digest_mismatch"
        evidence = value.get("derivedEvidence")
        if not isinstance(evidence, list) or _derived_evidence(
                evidence, cutoff=decision,
                visible_ids=selected_and_candidates) != evidence:
            return False, "invalid_snapshot_derived_evidence"
        expected_bounds = {
            "selectionCount": len(normalized_selections),
            "derivedEvidenceCount": len(evidence),
            "candidateObservationCount": len(selected_and_candidates),
            "maxSelections": MAX_SNAPSHOT_REQUESTS,
            "maxAlternatesPerSelection": MAX_ALTERNATES,
        }
        if not _has_exact_fields(value.get("bounds"), _SNAPSHOT_BOUNDS_FIELDS) or \
                _canonical(value.get("bounds")) != _canonical(expected_bounds):
            return False, "snapshot_bounds_mismatch"
        return True, "ok"
    except (TypeError, ValueError, OverflowError):
        return False, "invalid_snapshot"


@dataclass(frozen=True)
class AdapterSpec:
    adapter_id: str
    provider: str
    markets: Tuple[str, ...]
    fact_types: Tuple[str, ...]
    schema_version: str


AdapterNormalizer = Callable[[Any, Mapping[str, Any]], Mapping[str, Any]]


class ProviderAdapterRegistry:
    """Credential-free adapter seam; registration never changes authority."""

    def __init__(self) -> None:
        self._items: Dict[str, Tuple[AdapterSpec, AdapterNormalizer]] = {}

    def register(self, spec: AdapterSpec, normalizer: AdapterNormalizer) -> None:
        adapter_id = _safe_id(spec.adapter_id, "adapter_id")
        if adapter_id in self._items:
            raise ValueError("duplicate_adapter")
        if not callable(normalizer):
            raise ValueError("adapter_normalizer_required")
        if not isinstance(spec.markets, tuple) or not isinstance(
                spec.fact_types, tuple):
            raise ValueError("invalid_adapter_scopes")
        markets = tuple(_upper_text(item, "adapter_market")
                        for item in spec.markets)
        fact_types = tuple(_upper_text(item, "adapter_fact_type")
                           for item in spec.fact_types)
        if not markets or any(item not in MARKETS for item in markets):
            raise ValueError("invalid_adapter_markets")
        if not fact_types or any(item not in FACT_TYPES for item in fact_types):
            raise ValueError("invalid_adapter_fact_types")
        normalized = AdapterSpec(
            adapter_id=adapter_id,
            provider=provider_key(spec.provider),
            markets=markets,
            fact_types=fact_types,
            schema_version=_safe_id(spec.schema_version, "adapter_schema_version"),
        )
        self._items[adapter_id] = (normalized, normalizer)

    def describe(self) -> List[Dict[str, Any]]:
        out = []
        for adapter_id, (spec, _) in sorted(self._items.items()):
            scopes = []
            for market in spec.markets:
                for fact_type in spec.fact_types:
                    providers = REPOSITORY_PROVIDER_PRIORITY.get((market, fact_type), ())
                    scopes.append({
                        "market": market, "factType": fact_type,
                        "authority": spec.provider in providers,
                        "authorityRank": (providers.index(spec.provider)
                                          if spec.provider in providers else None),
                    })
            out.append({
                "adapterId": adapter_id, "provider": spec.provider,
                "schemaVersion": spec.schema_version, "scopes": scopes,
                "registrationGrantsAuthority": False,
            })
        return out

    def adapt(self, adapter_id: str, payload: Any, context: Mapping[str, Any]) -> Dict[str, Any]:
        key = _safe_id(adapter_id, "adapter_id")
        item = self._items.get(key)
        if item is None:
            raise ValueError("adapter_not_registered")
        spec, normalizer = item
        outcome = normalizer(payload, copy.deepcopy(dict(context or {})))
        if not _has_exact_fields(outcome, _ADAPTER_OUTCOME_FIELDS):
            raise ValueError("invalid_adapter_outcome")
        observations = outcome.get("observations")
        errors = outcome.get("errors")
        if not isinstance(observations, list) or not isinstance(errors, list):
            raise ValueError("invalid_adapter_outcome_types")
        if len(observations) > MAX_ADAPTER_OBSERVATIONS or len(errors) > MAX_ADAPTER_ERRORS:
            raise ValueError("adapter_outcome_unbounded")
        normalized_observations = _validated_observations(observations)
        for observation in normalized_observations:
            source = observation.get("source") or {}
            instrument = observation.get("instrument") or {}
            if source.get("adapter") != spec.adapter_id or source.get("providerKey") != spec.provider:
                raise ValueError("adapter_observation_source_mismatch")
            if instrument.get("market") not in spec.markets or observation.get("factType") not in spec.fact_types:
                raise ValueError("adapter_observation_scope_mismatch")
        normalized_errors = []
        for raw in errors:
            if not _has_closed_fields(
                    raw, _ADAPTER_ERROR_FIELDS,
                    required=frozenset({"code", "retryable"})):
                raise ValueError("invalid_adapter_error")
            if not isinstance(raw.get("retryable"), bool):
                raise ValueError("invalid_adapter_retryable")
            raw_instrument_id = raw.get("instrumentId")
            if raw_instrument_id is not None and not isinstance(
                    raw_instrument_id, str):
                raise ValueError("invalid_adapter_error_instrument_id")
            normalized_errors.append({
                "code": _safe_id(raw.get("code"), "adapter_error_code"),
                "instrumentId": (_safe_id(
                    raw_instrument_id, "instrument_id")
                    if raw_instrument_id is not None else None),
                "retryable": raw.get("retryable"),
            })
        return {
            "schemaVersion": ADAPTER_OUTCOME_SCHEMA_VERSION,
            "adapterId": spec.adapter_id,
            "provider": spec.provider,
            "observations": normalized_observations,
            "errors": normalized_errors,
            "authorityPolicyId": AUTHORITY_POLICY_ID,
        }
