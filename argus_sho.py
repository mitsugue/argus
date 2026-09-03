"""Canonical SHO-JP evidence engine for ARGUS Round 2.

This module is intentionally pure and bounded.  It performs no network, file,
environment, clock, AI, storage, order, or broker operation.  Every public
calculation receives an explicit information cutoff.  Missing evidence stays
missing, licensed evidence stays license-blocked, and unvalidated research
never acquires production status merely by being calculable.

The owner-supplied Canonical SHO RFC is bound by its exact SHA-256.  SHO
propositions are evidence generators, never independent action authorities.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import statistics
from datetime import datetime, time, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import argus_market_signals  # v13.5.38: owner-facing SIG-01..07 projection (pure)


CANONICAL_SHO_RFC_SHA256 = (
    "69a631ebc549b3bede6356cabf338e38d9418fc3683821198ef9a3c1eb440d51"
)
SHO_REGISTRY_SCHEMA = "argus-sho-proposition-registry-v1"
SHO_REGISTRY_VERSION = "sho-jp-canonical-2026.08-round2-v1"
SHO_EVIDENCE_SCHEMA = "argus-sho-evidence-v1"
REVERSAL_SCHEMA = "argus-sho-reversal-v1"
TARGET_LADDER_SCHEMA = "argus-sho-target-ladder-v1"
DIRECT_INDEX_SCHEMA = "argus-sho-direct-index-v1"
STOCK_LENS_SCHEMA = "argus-stock-sho-lens-v1"
COVERAGE_SCHEMA = "argus-round2-sho-coverage-v1"
CONSUMER_PROJECTION_SCHEMA = "argus-sho-today-sda-projection-v1"

_REVERSAL_ARTIFACT_SEAL = object()


class _BuilderIssuedReversalArtifact(dict):
    """Runtime capability produced only by the canonical reversal builder."""

    __slots__ = ("_authority_seal", "_body_digest")

LINEAGES = (
    "SHO_ORIGINAL",
    "ARGUS_CANDIDATE",
    "TURTLE_REFERENCE",
    "SEVEN_SIGN_CANDIDATE",
)
VALIDATION_STATUSES = ("UNVALIDATED", "VALIDATED", "CONDITIONAL", "REJECTED")
DATA_STATUSES = (
    "AVAILABLE",
    "PARTIAL",
    "MISSING",
    "STALE",
    "UNVALIDATED",
    "LICENSE_BLOCKED",
    "DATA_GATED",
    "UNKNOWN",
)
PROVENANCE_CLASSES = ("OBSERVED", "DERIVED", "INFERRED")
SHO_STATES = (
    "FRAGILE",
    "DOWNSIDE_TRIGGERED",
    "SELL_OFF_ACTIVE",
    "REVERSAL_EARLY",
    "TECHNICAL_REBOUND",
    "RECOVERY_TEST",
    "CONFIRMED_ADVANCE",
    "FALSE_RALLY",
    "MIXED",
)
SUPPLY_STATES = (
    "CROWDED_LONG",
    "FORCED_LIQUIDATION",
    "SUPPLY_CLEANUP",
    "REPAIRING",
    "LIGHT_SUPPLY",
    "REACCUMULATION",
)
HORIZONS = (1, 5, 10, 20, 40)

SHO_D01_THRESHOLD_JPY = 800_000_000_000
D01_SENSITIVITY_THRESHOLDS_JPY = (
    700_000_000_000,
    750_000_000_000,
    800_000_000_000,
    850_000_000_000,
    900_000_000_000,
)
ARGUS_MACD_BASELINE = (12, 26, 9)

CREDIT_CSV_PATH = "ops/imports/jpx_two_market_credit_20020802_20260710.csv"
CREDIT_CSV_SHA256 = (
    "50c57ae35762d90f5123f4fc40614c85954c7dee417ff249fc688b9130ee37cb"
)
CREDIT_COVERAGE_START = "2002-08-02"
CREDIT_COVERAGE_END = "2026-07-10"
CREDIT_POINTS_PER_SERIES = 1217

DIRECT_INDEX_TO_PROXY = {
    "NIKKEI_225_INDEX": "1321",
    "TOPIX_INDEX": "1306",
}
ANALYSIS_INSTRUMENTS = tuple(DIRECT_INDEX_TO_PROXY)

TARGET_CLUSTER_POLICY_ID = "sho-target-cluster-atr-half-v1"
TARGET_CLUSTER_POLICY = {
    "policyId": TARGET_CLUSTER_POLICY_ID,
    "version": "1",
    "distanceRule": "absolute level distance <= 0.5 * latest ATR14",
    "singleLevelPadRule": "max(0.05% of level, 0.05 * ATR14)",
    "direction": "upside levels strictly above current analysis price",
    "probabilityRule": "null until a matching validated artifact is supplied",
}
TARGET_CLUSTER_POLICY_SHA256 = ""  # assigned after canonical helpers below


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


TARGET_CLUSTER_POLICY_SHA256 = _sha256(TARGET_CLUSTER_POLICY)

SUPPLY_STATE_POLICY = {
    "policyId": "argus-stock-supply-state-candidate-v1",
    "version": "1",
    "lineage": "ARGUS_CANDIDATE",
    "validationStatus": "UNVALIDATED",
    "rules": [
        "FORCED_LIQUIDATION: return_5d_pct <= -5 and volume_ratio_20 >= 1.5 and margin_long_1w_change < 0",
        "SUPPLY_CLEANUP: margin_long_1w_change < 0 and return_5d_pct >= -2",
        "CROWDED_LONG: margin_ratio >= 3 or margin_long_1w_change_pct >= 10",
        "REACCUMULATION: return_5d_pct > 0 and relative_strength_20d > 0 and volume_ratio_20 >= 1.2",
        "LIGHT_SUPPLY: margin_ratio < 1",
        "REPAIRING: return_5d_pct > 0 or relative_strength_20d > 0",
    ],
    "inferredEvidenceMayClassify": False,
}
SUPPLY_STATE_POLICY_SHA256 = _sha256(SUPPLY_STATE_POLICY)


def _finite(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _instant(value: Any) -> Optional[datetime]:
    """Parse an exact ISO instant; date-only evidence becomes end-of-day UTC.

    Treating a date-only publication as end-of-day is conservative: it cannot
    enter a decision made earlier on that same date.
    """
    if not isinstance(value, str) or not value:
        return None
    text = value.strip()
    try:
        if len(text) == 10:
            parsed = datetime.combine(
                datetime.strptime(text, "%Y-%m-%d").date(),
                time(23, 59, 59, 999999),
                tzinfo=timezone.utc,
            )
        else:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                return None
            parsed = parsed.astimezone(timezone.utc)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed


def _cutoff(value: str) -> datetime:
    parsed = _instant(value)
    if parsed is None:
        raise ValueError("cutoff_must_be_exact_iso_time")
    return parsed


def _knowledge_time(row: Mapping[str, Any]) -> Optional[datetime]:
    times: List[datetime] = []
    for key in ("publishedAt", "availableFrom", "knownAt"):
        raw = row.get(key)
        if raw is None:
            continue
        parsed = _instant(raw)
        if parsed is None:
            return None
        times.append(parsed)
    return max(times) if times else None


def _registry_parameter(operator: str, value: Any, unit: str) -> Dict[str, Any]:
    return {"operator": operator, "value": value, "unit": unit}


def _proposition(
    *,
    proposition_id: str,
    claim: str,
    family: str,
    lineage: str,
    importance: str,
    parameter: Any,
    original_parameter: Any,
    factors: Sequence[str],
    notes: Sequence[str],
) -> Dict[str, Any]:
    policy_id = f"sho-jp-{proposition_id.lower()}-v1"
    policy_material = {
        "id": proposition_id,
        "claim": claim,
        "lineage": lineage,
        "parameter": parameter,
        "factors": list(factors),
        "canonicalRfcSha256": CANONICAL_SHO_RFC_SHA256,
    }
    return {
        "id": proposition_id,
        "family": family,
        "claim": claim,
        "sourceReference": f"owner-canonical-sho-rfc:{CANONICAL_SHO_RFC_SHA256}",
        "sourceTimestamp": None,
        "type": "DOWNSIDE_EVIDENCE",
        "lineage": lineage,
        "importance": importance,
        "parameter": copy.deepcopy(parameter),
        "originalParameter": copy.deepcopy(original_parameter),
        "factorDependencies": sorted(set(factors)),
        "horizons": [1, 5, 10, 20],
        "policyId": policy_id,
        "policyVersion": "1",
        "policyHash": _sha256(policy_material),
        "validationStatus": "UNVALIDATED",
        "validationArtifactId": None,
        "sampleSize": 0,
        "performance": None,
        "regimePerformance": {},
        "notes": list(notes),
    }


def _proposition_rows() -> List[Dict[str, Any]]:
    rows = [
        _proposition(
            proposition_id="SHO-D01-ORIGINAL",
            family="D01",
            claim="Two-market total short margin balance is below JPY 800 billion.",
            lineage="SHO_ORIGINAL",
            importance="P0",
            parameter=_registry_parameter("<", SHO_D01_THRESHOLD_JPY, "JPY"),
            original_parameter=_registry_parameter("<", SHO_D01_THRESHOLD_JPY, "JPY"),
            factors=("two_market_short_margin_balance",),
            notes=("Most important original SHO condition.",
                   "Never reduce SHO to condition counting."),
        ),
        _proposition(
            proposition_id="SHO-D02-ORIGINAL",
            family="D02",
            claim="ETF 1570 margin ratio is greater than or equal to 1.",
            lineage="SHO_ORIGINAL",
            importance="UNSPECIFIED",
            parameter=_registry_parameter(">=", 1, "RATIO"),
            original_parameter=_registry_parameter(">=", 1, "RATIO"),
            factors=("1570_margin_ratio", "two_market_short_margin_balance"),
            notes=("Missing point-in-time 1570 data remains MISSING.",),
        ),
        _proposition(
            proposition_id="SHO-D03-ORIGINAL",
            family="D03",
            claim="Japan relative strength can activate short-cover evidence.",
            lineage="SHO_ORIGINAL",
            importance="UNSPECIFIED",
            parameter="UNKNOWN",
            original_parameter="UNKNOWN",
            factors=("nikkei_225_index", "sp500_index", "relative_strength"),
            notes=("Direct index evidence is preferred.",),
        ),
        _proposition(
            proposition_id="SHO-D04-ORIGINAL",
            family="D04",
            claim="Nikkei 225 theoretical value is EPS multiplied by the 17x through 21x PER ladder.",
            lineage="SHO_ORIGINAL",
            importance="UNSPECIFIED",
            parameter={"multiples": [17, 18, 19, 20, 21], "unit": "PER_X"},
            original_parameter={"multiples": [17, 18, 19, 20, 21], "unit": "PER_X"},
            factors=("nikkei_225_eps", "nikkei_225_per", "nikkei_225_index"),
            notes=("Never apply Nikkei valuation directly to ETF 1321.",),
        ),
        _proposition(
            proposition_id="SHO-D05-ORIGINAL",
            family="D05",
            claim="Published foreign-investor flow is confirmation evidence.",
            lineage="SHO_ORIGINAL",
            importance="UNSPECIFIED",
            parameter={"publicationTimeGate": True},
            original_parameter={"publicationTimeGate": True},
            factors=("foreign_investor_flow", "publication_time"),
            notes=("Period end is never treated as availability time.",),
        ),
        _proposition(
            proposition_id="SHO-D06-ORIGINAL",
            family="D06",
            claim="VIX MACD golden cross warns of equity downside and dead cross supports recovery evidence.",
            lineage="SHO_ORIGINAL",
            importance="UNSPECIFIED",
            parameter="UNKNOWN",
            original_parameter="UNKNOWN",
            factors=("vix_level", "vix_velocity", "vix_percentile", "vix_regime", "vix_macd"),
            notes=("12/26/9 is not SHO-original without source confirmation.",),
        ),
        _proposition(
            proposition_id="SHO-D07-ORIGINAL",
            family="D07",
            claim="Earnings quality and subsequent market reaction form deterministic evidence when supported.",
            lineage="SHO_ORIGINAL",
            importance="UNSPECIFIED",
            parameter="UNKNOWN",
            original_parameter="UNKNOWN",
            factors=("earnings_quality", "price_reaction", "volume", "relative_reaction"),
            notes=("Never synthesize earnings quality.",),
        ),
    ]
    for threshold in D01_SENSITIVITY_THRESHOLDS_JPY:
        rows.append(_proposition(
            proposition_id=f"ARGUS-D01-SENS-{threshold // 1_000_000_000}B",
            family="D01",
            claim=f"Sensitivity candidate: two-market short margin balance is below JPY {threshold // 1_000_000_000} billion.",
            lineage="ARGUS_CANDIDATE",
            importance="RESEARCH",
            parameter=_registry_parameter("<", threshold, "JPY"),
            original_parameter=None,
            factors=("two_market_short_margin_balance",),
            notes=("Bounded sensitivity candidate; no automatic promotion.",),
        ))
    rows.extend([
        _proposition(
            proposition_id="ARGUS-D03-ETF-PROXY",
            family="D03",
            claim="ETF-linked relative strength may be retained as an explicitly labeled proxy candidate.",
            lineage="ARGUS_CANDIDATE",
            importance="RESEARCH",
            parameter={"analysisProxy": "1321", "comparisonProxy": "SPY"},
            original_parameter=None,
            factors=("1321_etf", "spy_etf", "relative_strength"),
            notes=("Never label the proxy as direct Nikkei 225 evidence.",),
        ),
        _proposition(
            proposition_id="ARGUS-D06-MACD-12-26-9",
            family="D06",
            claim="ARGUS research baseline computes VIX MACD with 12/26/9 parameters.",
            lineage="ARGUS_CANDIDATE",
            importance="RESEARCH",
            parameter={"fast": 12, "slow": 26, "signal": 9},
            original_parameter=None,
            factors=("vix_close_history",),
            notes=("Separate from the unknown SHO-original parameter.",),
        ),
    ])
    return sorted(rows, key=lambda row: row["id"])


def _registry_body() -> Dict[str, Any]:
    return {
        "schemaVersion": SHO_REGISTRY_SCHEMA,
        "registryVersion": SHO_REGISTRY_VERSION,
        "canonicalRfcSha256": CANONICAL_SHO_RFC_SHA256,
        "lineages": list(LINEAGES),
        "validationStatuses": list(VALIDATION_STATUSES),
        "automaticPromotion": False,
        "propositions": _proposition_rows(),
    }


SHO_REGISTRY_SHA256 = _sha256(_registry_body())


def sealed_proposition_registry() -> Dict[str, Any]:
    """Return a fresh copy of the sealed, RFC-bound registry."""
    body = _registry_body()
    if _sha256(body) != SHO_REGISTRY_SHA256:
        raise RuntimeError("sho_registry_internal_drift")
    return {**body, "registrySha256": SHO_REGISTRY_SHA256}


def validate_proposition_registry(value: Any) -> Tuple[bool, str]:
    if not isinstance(value, dict):
        return False, "registry_not_object"
    expected = sealed_proposition_registry()
    if value != expected:
        return False, "registry_not_exact_sealed_value"
    originals = [row for row in value["propositions"]
                 if row["lineage"] == "SHO_ORIGINAL"]
    if [row["family"] for row in originals] != [f"D0{i}" for i in range(1, 8)]:
        return False, "original_family_set_invalid"
    if any(row["validationStatus"] not in VALIDATION_STATUSES
           or row["lineage"] not in LINEAGES for row in value["propositions"]):
        return False, "registry_enum_invalid"
    return True, "valid"


def registry_canonical_bytes() -> bytes:
    return _canonical_bytes(sealed_proposition_registry())


def repository_coverage_audit() -> List[Dict[str, Any]]:
    """Exact repository coverage; runtime/provider potential is not availability."""
    rows = [
        ("nikkei_ohlcv", "MISSING", None, None, 0, None,
         "No committed direct Nikkei 225 OHLCV dataset."),
        ("topix_ohlcv", "MISSING", None, None, 0, None,
         "No committed direct TOPIX OHLCV dataset."),
        ("vix_history", "PARTIAL", None, None, 0, None,
         "Live/cache seams exist, but no durable committed VIX validation history."),
        ("two_market_margin_balances", "AVAILABLE", CREDIT_COVERAGE_START,
         CREDIT_COVERAGE_END, CREDIT_POINTS_PER_SERIES * 2, CREDIT_CSV_PATH,
         "1,217 official weekly short rows and 1,217 official weekly long rows."),
        ("credit_valuation_loss", "LICENSE_BLOCKED", None, None, 0, None,
         "Schema exists; redistributable history is not committed."),
        ("1570_margin_ratio", "MISSING", None, None, 0, None,
         "No committed point-in-time 1570 margin-ratio history."),
        ("foreign_investor_flow", "PARTIAL", None, None, 0, None,
         "Publication-gated ingestion exists; no committed validation history."),
        ("nikkei_eps_per", "LICENSE_BLOCKED", None, None, 0,
         "ops/imports/nikkei_per_pbr_licensed_template.csv",
         "Template only; direct licensed observations are absent."),
        ("individual_stock_margin", "PARTIAL", None, None, 0, None,
         "Live per-symbol seam exists; no committed historical archive."),
        ("jsf_balance", "PARTIAL", None, None, 0, None,
         "Live daily seam exists; no committed historical archive."),
        ("reverse_fee", "MISSING", None, None, 0, None,
         "Reverse stock-lending fee is not ingested."),
        ("earnings_quality", "PARTIAL", None, None, 0, None,
         "Event/reaction evidence exists; comprehensive quality history does not."),
        ("sector_style", "PARTIAL", None, None, 0, None,
         "Proxy/rotation seams exist; complete PIT sector/style history does not."),
        ("breadth", "PARTIAL", None, None, 0, None,
         "Aggregate machinery exists; full raw licensed history stays outside Git."),
        ("ten_year_multi_source_pit_archive", "MISSING", None, None, 0, None,
         "No complete ten-year direct-index/VIX/flow/earnings PIT archive in Git."),
    ]
    return [{
        "dataId": data_id,
        "status": status,
        "coverageStart": start,
        "coverageEnd": end,
        "rowCount": count,
        "repositoryPath": path,
        "sha256": CREDIT_CSV_SHA256 if data_id == "two_market_margin_balances" else None,
        "note": note,
    } for data_id, status, start, end, count, path, note in rows]


def coverage_artifact() -> Dict[str, Any]:
    registry_index = [{key: copy.deepcopy(row[key]) for key in (
        "id", "family", "lineage", "policyId", "policyHash",
        "validationStatus")}
        for row in sealed_proposition_registry()["propositions"]]
    body = {
        "schemaVersion": COVERAGE_SCHEMA,
        "canonicalRfcSha256": CANONICAL_SHO_RFC_SHA256,
        "registryVersion": SHO_REGISTRY_VERSION,
        "registrySha256": SHO_REGISTRY_SHA256,
        "registrySealed": True,
        "registryIndex": registry_index,
        "scope": "repository_only_no_runtime_inference",
        "coverage": repository_coverage_audit(),
        "dataGates": [
            "1570_pit_margin_history",
            "durable_vix_history",
            "source_confirmed_sho_vix_macd_parameters",
            "direct_verified_nikkei_topix_history_and_rights",
            "nikkei_valuation_licensed_fields",
            "comprehensive_earnings_quality_history",
            "complete_sector_style_history",
            "complete_ten_year_multi_source_pit_archive",
            "reverse_fee_history",
            "tachibana_actual_field_behavior",
        ],
    }
    return {**body, "artifactId": "sho-coverage-" + _sha256(body)}


def point_in_time_rows(rows: Iterable[Mapping[str, Any]], cutoff: str) \
        -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Select the newest knowable revision per logical observation.

    At least one explicit publication/availability/knowledge time is required.
    Malformed, future, and ambiguous rows are excluded, never coerced.
    """
    limit = _cutoff(cutoff)
    source = list(rows or [])
    admitted: Dict[Tuple[str, str, str], Tuple[datetime, int, Dict[str, Any]]] = {}
    seen_revision_hashes: Dict[Tuple[str, str, str, int], str] = {}
    excluded_future = excluded_malformed = 0
    for raw in source:
        if not isinstance(raw, Mapping):
            excluded_malformed += 1
            continue
        known = _knowledge_time(raw)
        if known is None:
            excluded_malformed += 1
            continue
        if known > limit:
            excluded_future += 1
            continue
        revision = raw.get("revision", 0)
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
            excluded_malformed += 1
            continue
        # A correction cannot inherit the original row's publication time.
        # Every revision needs its own explicit first-known instant.
        if revision > 0 and (
                not raw.get("knownAt") or _instant(raw.get("knownAt")) is None):
            excluded_malformed += 1
            continue
        instrument = str(raw.get("instrumentId") or raw.get("instrument") or
                         raw.get("symbol") or "")
        field = str(raw.get("seriesId") or raw.get("field") or raw.get("kind") or "")
        if not field and all(key in raw for key in
                             ("open", "high", "low", "close", "volume")):
            field = "OHLCV_BAR"
        if not field and any(key in raw for key in
                             ("epsActual", "epsEstimate", "earningsQuality")):
            field = "EARNINGS_EVENT"
        period = str(raw.get("periodEnd") or raw.get("date") or "")[:10]
        if not instrument:
            instrument = "MARKET"
        try:
            observed_date = datetime.strptime(period, "%Y-%m-%d").date()
        except (TypeError, ValueError, OverflowError):
            observed_date = None
        if not field or len(period) != 10 or observed_date is None or \
                observed_date.isoformat() != period:
            excluded_malformed += 1
            continue
        # A date-only market observation identifies its exchange session, not
        # an end-of-day publication instant.  Same-session use is lawful when
        # the separate knowledge timestamp is already within the cutoff.
        if observed_date > limit.date():
            excluded_future += 1
            continue
        key = (instrument.upper(), field, period)
        candidate = (known, revision, copy.deepcopy(dict(raw)))
        try:
            candidate_hash = _sha256(candidate[2])
        except (TypeError, ValueError, OverflowError):
            excluded_malformed += 1
            continue
        revision_key = (*key, revision)
        seen_hash = seen_revision_hashes.get(revision_key)
        if seen_hash is not None and seen_hash != candidate_hash:
            raise ValueError("conflicting_row_revision")
        seen_revision_hashes[revision_key] = candidate_hash
        previous = admitted.get(key)
        if previous is not None and revision == previous[1]:
            previous_hash = _sha256(previous[2])
            if candidate_hash != previous_hash:
                raise ValueError("conflicting_row_revision")
            continue
        candidate_rank = (revision, known, candidate_hash)
        previous_rank = ((previous[1], previous[0], _sha256(previous[2]))
                         if previous is not None else None)
        if previous_rank is None or candidate_rank > previous_rank:
            admitted[key] = candidate
    selected = [item[2] for item in admitted.values()]
    selected.sort(key=lambda row: (
        str(row.get("periodEnd") or row.get("date") or ""),
        str(row.get("instrumentId") or row.get("instrument") or
            row.get("symbol") or "").upper(),
        str(row.get("seriesId") or row.get("field") or row.get("kind") or ""),
        int(row.get("revision") or 0),
    ))
    proof_body = {
        "policyId": "sho-explicit-publication-pit-v1",
        "cutoff": cutoff,
        "inputCount": len(source),
        "includedCount": len(selected),
        "excludedFutureCount": excluded_future,
        "excludedMalformedCount": excluded_malformed,
        "futureRowsAdmitted": False,
        "datasetHash": _sha256(selected),
    }
    return selected, {**proof_body, "proofId": "sho-pit-" + _sha256(proof_body)}


def _series_history(rows: Sequence[Mapping[str, Any]], series_id: str) \
        -> List[Dict[str, Any]]:
    result = []
    for row in rows:
        if (row.get("seriesId") or row.get("field")) != series_id:
            continue
        value = _finite(row.get("value"))
        if value is None:
            continue
        result.append({**dict(row), "value": value})
    return sorted(result, key=lambda row: str(row.get("periodEnd") or ""))


def _change(history: Sequence[Mapping[str, Any]], periods: int) -> Optional[float]:
    if len(history) <= periods:
        return None
    return float(history[-1]["value"]) - float(history[-1 - periods]["value"])


def _threshold_streak(history: Sequence[Mapping[str, Any]], *, below: bool) -> int:
    count = 0
    for row in reversed(history):
        value = float(row["value"])
        matches = value < SHO_D01_THRESHOLD_JPY if below else value >= SHO_D01_THRESHOLD_JPY
        if not matches:
            break
        count += 1
    return count


def evaluate_d01(rows: Iterable[Mapping[str, Any]], *, cutoff: str,
                 valuation_loss_status: str = "LICENSE_BLOCKED") -> Dict[str, Any]:
    if valuation_loss_status not in {"LICENSE_BLOCKED", "MISSING", "UNKNOWN"}:
        raise ValueError("invalid_valuation_loss_status")
    visible, proof = point_in_time_rows(rows, cutoff)
    shorts = _series_history(visible, "credit.short_balance")
    longs = _series_history(visible, "credit.long_balance")
    losses = _series_history(visible, "credit.valuation_loss_pct")
    short = shorts[-1]["value"] if shorts else None
    long = longs[-1]["value"] if longs else None
    ratio = (long / short if long is not None and short and short > 0 else None)
    features = {
        "shortBalance": short,
        "longBalance": long,
        "marginRatio": round(ratio, 6) if ratio is not None else None,
        "valuationLossPct": losses[-1]["value"] if losses else None,
        "shortBalance1wChange": _change(shorts, 1),
        "shortBalance4wChange": _change(shorts, 4),
        "longBalance1wChange": _change(longs, 1),
        "longBalance4wChange": _change(longs, 4),
        "below800bStreak": _threshold_streak(shorts, below=True) if shorts else 0,
        "aboveOrEqual800bStreak": _threshold_streak(shorts, below=False) if shorts else 0,
        "distanceFrom800b": short - SHO_D01_THRESHOLD_JPY if short is not None else None,
    }
    candidates = [{
        "propositionId": f"ARGUS-D01-SENS-{threshold // 1_000_000_000}B",
        "lineage": "ARGUS_CANDIDATE",
        "thresholdJpy": threshold,
        "conditionMet": short < threshold if short is not None else None,
        "validationStatus": "UNVALIDATED",
    } for threshold in D01_SENSITIVITY_THRESHOLDS_JPY]
    return {
        "family": "D01",
        "propositionId": "SHO-D01-ORIGINAL",
        "lineage": "SHO_ORIGINAL",
        "importance": "P0",
        "status": "AVAILABLE" if short is not None else "MISSING",
        "conditionMet": short < SHO_D01_THRESHOLD_JPY if short is not None else None,
        "threshold": {"operator": "<", "value": SHO_D01_THRESHOLD_JPY, "unit": "JPY"},
        "features": features,
        "featureStatuses": {
            "shortBalance": "AVAILABLE" if short is not None else "MISSING",
            "longBalance": "AVAILABLE" if long is not None else "MISSING",
            "valuationLossPct": ("AVAILABLE" if losses
                                  else valuation_loss_status),
        },
        "sensitivityCandidates": candidates,
        "validationStatus": "UNVALIDATED",
        "pointInTimeProof": proof,
        "missing": ([] if short is not None else ["two_market_short_margin_balance"])
        + ([] if long is not None else ["two_market_long_margin_balance"])
        + ([] if losses or valuation_loss_status != "MISSING"
           else ["credit_valuation_loss"]),
        "licenseBlocked": ([] if losses or valuation_loss_status != "LICENSE_BLOCKED"
                           else ["credit_valuation_loss"]),
    }


def evaluate_d02(rows: Iterable[Mapping[str, Any]], *, cutoff: str) -> Dict[str, Any]:
    visible, proof = point_in_time_rows(rows, cutoff)
    candidates: List[Tuple[datetime, float, Dict[str, Any]]] = []
    for row in visible:
        instrument = str(row.get("instrumentId") or row.get("instrument") or
                         row.get("symbol") or "").upper()
        field = str(row.get("field") or row.get("seriesId") or "")
        if instrument not in {"1570", "JP:1570:ETF"} and not field.startswith("1570"):
            continue
        if field not in {"margin_ratio", "1570.margin_ratio", "marginRatio"}:
            continue
        value = _finite(row.get("value", row.get("marginRatio")))
        known = _knowledge_time(row)
        if value is not None and known is not None:
            candidates.append((known, value, dict(row)))
    latest = max(candidates, key=lambda item: item[0]) if candidates else None
    ratio = latest[1] if latest else None
    return {
        "family": "D02",
        "propositionId": "SHO-D02-ORIGINAL",
        "lineage": "SHO_ORIGINAL",
        "instrumentId": "1570",
        "status": "AVAILABLE" if ratio is not None else "MISSING",
        "marginRatio": ratio,
        "conditionMet": ratio >= 1 if ratio is not None else None,
        "threshold": {"operator": ">=", "value": 1, "unit": "RATIO"},
        "inferred": False,
        "validationStatus": "UNVALIDATED",
        "pointInTimeProof": proof,
        "missing": [] if ratio is not None else ["1570_pit_margin_ratio"],
    }


def _value_and_time(value: Optional[Mapping[str, Any]], cutoff: str) \
        -> Optional[Dict[str, Any]]:
    if not isinstance(value, Mapping):
        return None
    visible, _ = point_in_time_rows([value], cutoff)
    if not visible:
        return None
    number = _finite(visible[0].get("value"))
    return {**visible[0], "value": number} if number is not None else None


def evaluate_d03(*, cutoff: str,
                 direct_evidence: Optional[Mapping[str, Any]] = None,
                 proxy_evidence: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    direct_identity_ok = (isinstance(direct_evidence, Mapping)
                          and _identity_matches(
                              direct_evidence, "NIKKEI_225_INDEX"))
    proxy_identity_ok = (isinstance(proxy_evidence, Mapping)
                         and _identity_matches(proxy_evidence, "1321"))
    direct = (_value_and_time(direct_evidence, cutoff)
              if direct_identity_ok else None)
    proxy = (_value_and_time(proxy_evidence, cutoff)
             if proxy_identity_ok else None)
    if direct is not None:
        source_type, lineage, proposition = (
            "DIRECT_INDEX", "SHO_ORIGINAL", "SHO-D03-ORIGINAL")
        selected = direct
    elif proxy is not None:
        source_type, lineage, proposition = (
            "ETF_PROXY", "ARGUS_CANDIDATE", "ARGUS-D03-ETF-PROXY")
        selected = proxy
    else:
        source_type, lineage, proposition, selected = (
            "NONE", "SHO_ORIGINAL", "SHO-D03-ORIGINAL", None)
    return {
        "family": "D03",
        "propositionId": proposition,
        "lineage": lineage,
        "status": "AVAILABLE" if selected is not None else "MISSING",
        "sourceType": source_type,
        "relativeStrengthValue": selected["value"] if selected else None,
        # v13.5.44: deterministic ARGUS candidate condition — the analysis
        # instrument outperformed the comparison over the window (value > 0).
        # The SHO-original threshold stays UNKNOWN; this is labelled research.
        "conditionMet": (selected["value"] > 0) if selected else None,
        "conditionRule": "relative_strength_20d > 0 (analysis outperforms comparison)",
        "conditionLineage": "ARGUS_CANDIDATE",
        "sourceRef": selected.get("sourceRef") if selected else None,
        "directIdentityRejected": direct_evidence is not None and not direct_identity_ok,
        "proxyIdentityRejected": proxy_evidence is not None and not proxy_identity_ok,
        "activationSwitch": None,
        "validationStatus": "UNVALIDATED",
        "missing": [] if selected else ["japan_relative_strength"],
        "note": ("Proxy candidate; not direct Nikkei evidence."
                 if source_type == "ETF_PROXY" else None),
    }


def _derived_valuation_evidence(value: Any, cutoff: str) -> Optional[Dict[str, Any]]:
    """v13.5.44: ARGUS-derived Japan valuation (argus_japan_valuation) when no
    licensed Nikkei EPS is available.  Explicit argument first; otherwise the
    module store the boot warm publishes.  Only AVAILABLE evidence whose
    knowledge time is not after the cutoff is admitted."""
    candidate = value
    if candidate is None:
        try:
            import argus_japan_valuation
            candidate = argus_japan_valuation.current_evidence()
        except Exception:
            candidate = None
    if not isinstance(candidate, Mapping) or candidate.get("status") != "AVAILABLE":
        return None
    if candidate.get("conditionMet") is None:
        return None
    available = candidate.get("availableFrom")
    known = str(candidate.get("knownAt") or "")[:10]
    if available and known:
        visible, _ = point_in_time_rows(
            [{"instrumentId": "JP_UNIVERSE", "seriesId": "derived_valuation",
              "periodEnd": known, "availableFrom": available, "value": 0}], cutoff)
        if not visible:
            return None
    return dict(candidate)


def evaluate_d04(*, cutoff: str, analysis_instrument: str,
                 eps_evidence: Optional[Mapping[str, Any]] = None,
                 index_evidence: Optional[Mapping[str, Any]] = None,
                 license_status: str = "LICENSE_BLOCKED",
                 derived_valuation: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    if license_status not in {"AVAILABLE", "LICENSE_BLOCKED", "MISSING"}:
        raise ValueError("invalid_nikkei_valuation_license_status")
    if analysis_instrument != "NIKKEI_225_INDEX":
        return {
            "family": "D04", "propositionId": "SHO-D04-ORIGINAL",
            "lineage": "SHO_ORIGINAL", "analysisInstrument": analysis_instrument,
            "status": "MISSING", "levels": [], "validationStatus": "UNVALIDATED",
            "missing": ["nikkei_index_identity_required"],
            "identityViolationPrevented": analysis_instrument in {"1321", "JP:1321:ETF"},
        }
    eps_identity_ok = (isinstance(eps_evidence, Mapping)
                       and _identity_matches(eps_evidence, "NIKKEI_225_INDEX"))
    index_identity_ok = (isinstance(index_evidence, Mapping)
                         and _identity_matches(index_evidence, "NIKKEI_225_INDEX"))
    eps = _value_and_time(eps_evidence, cutoff) if eps_identity_ok else None
    index = _value_and_time(index_evidence, cutoff) if index_identity_ok else None
    if license_status == "LICENSE_BLOCKED" or eps is None:
        derived = _derived_valuation_evidence(derived_valuation, cutoff)
        if derived is not None:
            return {
                "family": "D04", "propositionId": "SHO-D04-ORIGINAL",
                "lineage": "ARGUS_CANDIDATE",
                "analysisInstrument": analysis_instrument,
                "status": "AVAILABLE",
                "derivation": derived.get("derivation"),
                "eps": None, "indexLevel": index["value"] if index else None,
                "levels": [], "validationStatus": "UNVALIDATED",
                "conditionMet": derived.get("conditionMet"),
                "conditionRule": derived.get("conditionRule"),
                "conditionLineage": "ARGUS_CANDIDATE",
                "derived": {key: derived.get(key) for key in (
                    "medianForwardPer", "interquartileRange", "highValuationShare",
                    "coverage", "universeSize", "ladder", "knownAt", "computedAt")},
                "nikkeiOfficialPer": "NOT_CLAIMED",
                "licensedNikkeiEps": license_status,
                "missing": [],
                "epsIdentityRejected": eps_evidence is not None and not eps_identity_ok,
                "indexIdentityRejected": index_evidence is not None and not index_identity_ok,
                "identityViolationPrevented": False,
            }
        return {
            "family": "D04", "propositionId": "SHO-D04-ORIGINAL",
            "lineage": "SHO_ORIGINAL", "analysisInstrument": analysis_instrument,
            "status": "LICENSE_BLOCKED" if license_status == "LICENSE_BLOCKED" else "MISSING",
            "eps": None, "indexLevel": index["value"] if index else None,
            "levels": [], "validationStatus": "UNVALIDATED",
            "missing": ["licensed_nikkei_eps_per"],
            "epsIdentityRejected": eps_evidence is not None and not eps_identity_ok,
            "indexIdentityRejected": index_evidence is not None and not index_identity_ok,
            "identityViolationPrevented": False,
        }
    levels = [{
        "multiple": multiple,
        "theoreticalValue": round(eps["value"] * multiple, 6),
        "distanceToIndex": (round(eps["value"] * multiple - index["value"], 6)
                            if index else None),
    } for multiple in (17, 18, 19, 20, 21)]
    return {
        "family": "D04", "propositionId": "SHO-D04-ORIGINAL",
        "lineage": "SHO_ORIGINAL", "analysisInstrument": analysis_instrument,
        "status": "AVAILABLE", "eps": eps["value"],
        "indexLevel": index["value"] if index else None,
        "levels": levels, "validationStatus": "UNVALIDATED",
        "missing": [] if index else ["nikkei_index_level"],
        "epsIdentityRejected": eps_evidence is not None and not eps_identity_ok,
        "indexIdentityRejected": index_evidence is not None and not index_identity_ok,
        "identityViolationPrevented": False,
    }


def evaluate_d05(rows: Iterable[Mapping[str, Any]], *, cutoff: str) -> Dict[str, Any]:
    visible, proof = point_in_time_rows(rows, cutoff)
    history = _series_history(visible, "flow.foreign")
    latest = history[-1] if history else None
    value = latest["value"] if latest else None
    return {
        "family": "D05", "propositionId": "SHO-D05-ORIGINAL",
        "lineage": "SHO_ORIGINAL",
        "status": "AVAILABLE" if latest else "MISSING",
        "flowValue": value,
        "direction": ("INFLOW" if value is not None and value > 0 else
                      "OUTFLOW" if value is not None and value < 0 else
                      "FLAT" if value == 0 else None),
        # v13.5.44: confirmation evidence = published net foreign INFLOW.
        "conditionMet": (value > 0) if value is not None else None,
        "conditionRule": "latest published foreign-investor net flow > 0 (INFLOW)",
        "conditionLineage": "SHO_ORIGINAL",
        "periodEnd": latest.get("periodEnd") if latest else None,
        "availableFrom": latest.get("availableFrom") if latest else None,
        "publicationTimeGated": True,
        "validationStatus": "UNVALIDATED",
        "pointInTimeProof": proof,
        "missing": [] if latest else ["foreign_investor_flow"],
    }


def _ema(values: Sequence[float], window: int) -> List[float]:
    if not values:
        return []
    alpha = 2.0 / (window + 1)
    current = float(values[0])
    out = []
    for value in values:
        current = float(value) * alpha + current * (1 - alpha)
        out.append(current)
    return out


def _macd(values: Sequence[float], params: Tuple[int, int, int]) \
        -> List[Dict[str, float]]:
    fast, slow, signal_window = params
    if min(params) <= 0 or fast >= slow:
        raise ValueError("invalid_macd_parameters")
    fast_values, slow_values = _ema(values, fast), _ema(values, slow)
    line = [a - b for a, b in zip(fast_values, slow_values)]
    signal = _ema(line, signal_window)
    return [{"line": a, "signal": b, "histogram": a - b}
            for a, b in zip(line, signal)]


def _macd_transition(rows: Sequence[Mapping[str, float]]) -> Optional[str]:
    if len(rows) < 2:
        return None
    previous, current = rows[-2], rows[-1]
    if previous["line"] >= previous["signal"] and current["line"] < current["signal"]:
        return "DEAD_CROSS"
    if previous["line"] <= previous["signal"] and current["line"] > current["signal"]:
        return "GOLDEN_CROSS"
    return None


def _close_history(rows: Iterable[Mapping[str, Any]], cutoff: str) \
        -> Tuple[List[Tuple[str, float]], Dict[str, Any]]:
    visible, proof = point_in_time_rows(rows, cutoff)
    out = []
    for row in visible:
        value = _finite(row.get("close", row.get("value")))
        date = str(row.get("periodEnd") or row.get("date") or "")[:10]
        if value is not None and value > 0 and len(date) == 10:
            out.append((date, value))
    return sorted(out), proof


def evaluate_d06(rows: Iterable[Mapping[str, Any]], *, cutoff: str) -> Dict[str, Any]:
    source = list(rows or [])
    identified = [row for row in source if isinstance(row, Mapping)
                  and _vix_identity_matches(row)]
    history, proof = _close_history(identified, cutoff)
    closes = [value for _, value in history]
    if not closes:
        return {
            "family": "D06", "propositionId": "SHO-D06-ORIGINAL",
            "lineage": "SHO_ORIGINAL", "status": "MISSING",
            "originalParameter": "UNKNOWN", "argusBaseline": None,
            "validationStatus": "UNVALIDATED", "pointInTimeProof": proof,
            "identityRejectedRowCount": len(source) - len(identified),
            "missing": ["vix_history"],
        }
    level = closes[-1]
    previous = closes[-2] if len(closes) > 1 else level
    window = closes[-60:]
    percentile = round(100 * sum(value <= level for value in window) / len(window), 3)
    velocity = level - previous
    regime = ("SHOCK" if level >= 30 else "ELEVATED" if level >= 25 or
              (level >= 18 and percentile >= 80) else
              "CALM" if level < 14 else "NORMAL")
    macd_rows = _macd(closes, ARGUS_MACD_BASELINE)
    transition = _macd_transition(macd_rows)
    return {
        "family": "D06", "propositionId": "SHO-D06-ORIGINAL",
        "lineage": "SHO_ORIGINAL", "status": "AVAILABLE",
        "originalParameter": "UNKNOWN",
        "level": round(level, 6), "velocity": round(velocity, 6),
        "percentile": percentile, "regime": regime,
        "shoOriginalTransition": None,
        # v13.5.44: ARGUS 12/26/9 baseline — VIX MACD histogram below zero
        # (dead-cross side) is the recovery-supportive condition; a golden
        # cross (histogram >= 0) is the warning side.  SHO-original stays UNKNOWN.
        "conditionMet": macd_rows[-1]["histogram"] < 0,
        "conditionRule": "VIX MACD(12,26,9) histogram < 0 (dead-cross side)",
        "conditionLineage": "ARGUS_CANDIDATE",
        "argusBaseline": {
            "propositionId": "ARGUS-D06-MACD-12-26-9",
            "lineage": "ARGUS_CANDIDATE",
            "parameters": {"fast": 12, "slow": 26, "signal": 9},
            "transition": transition,
            "line": round(macd_rows[-1]["line"], 8),
            "signal": round(macd_rows[-1]["signal"], 8),
            "histogram": round(macd_rows[-1]["histogram"], 8),
            "validationStatus": "UNVALIDATED",
        },
        "validationStatus": "UNVALIDATED", "pointInTimeProof": proof,
        "identityRejectedRowCount": len(source) - len(identified),
        "missing": ["source_confirmed_sho_vix_macd_parameters"],
    }


def _bar_return(bars: Sequence[Mapping[str, Any]], start_index: int,
                horizon: int) -> Optional[float]:
    if start_index < 0 or start_index + horizon >= len(bars):
        return None
    start = _finite(bars[start_index].get("close"))
    end = _finite(bars[start_index + horizon].get("close"))
    if start is None or end is None or start <= 0:
        return None
    return round((end / start - 1) * 100, 6)


def _statements_warm_state(value: Any) -> Optional[Dict[str, Any]]:
    """Warm state of the statements feed (explicit argument or module store)."""
    candidate = value
    if candidate is None:
        try:
            import argus_japan_valuation
            candidate = argus_japan_valuation.statements_state()
        except Exception:
            candidate = None
    if not isinstance(candidate, Mapping) or not candidate.get("warmedAt"):
        return None
    return {"warmedAt": str(candidate.get("warmedAt")),
            "rowCount": int(candidate.get("rowCount") or 0),
            "source": str(candidate.get("source") or "")[:40] or None}


def evaluate_d07(*, cutoff: str,
                 earnings_event: Optional[Mapping[str, Any]] = None,
                 stock_bars: Iterable[Mapping[str, Any]] = (),
                 sector_bars: Iterable[Mapping[str, Any]] = (),
                 index_bars: Iterable[Mapping[str, Any]] = (),
                 statements_state: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """Evaluate supported earnings reaction without synthesizing quality."""
    event_visible, _ = point_in_time_rows(
        [earnings_event] if isinstance(earnings_event, Mapping) else [], cutoff)
    if not event_visible:
        warm = _statements_warm_state(statements_state)
        if warm is not None:
            # v13.5.44: the feed was read for the window and holds no
            # supported disclosure — a truthful NOT_APPLICABLE, not a
            # provider outage.
            return {
                "family": "D07", "propositionId": "SHO-D07-ORIGINAL",
                "lineage": "SHO_ORIGINAL", "status": "NOT_APPLICABLE",
                "earningsQuality": None, "reaction": None,
                "conditionMet": None,
                "validationStatus": "UNVALIDATED",
                "statementsFeed": warm,
                "missing": ["no_supported_earnings_event_in_window"],
            }
        return {
            "family": "D07", "propositionId": "SHO-D07-ORIGINAL",
            "lineage": "SHO_ORIGINAL", "status": "MISSING",
            "earningsQuality": None, "reaction": None,
            "validationStatus": "UNVALIDATED",
            "missing": ["supported_earnings_event"],
        }
    event = event_visible[-1]
    event_instrument = _instrument_code(event)
    if not event_instrument or event_instrument == "MARKET":
        return {
            "family": "D07", "propositionId": "SHO-D07-ORIGINAL",
            "lineage": "SHO_ORIGINAL", "status": "MISSING",
            "earningsQuality": None, "reaction": None,
            "validationStatus": "UNVALIDATED",
            "missing": ["earnings_event_instrument_identity"],
        }
    stock_source = list(stock_bars or [])
    identified_stock = [row for row in stock_source if isinstance(row, Mapping)
                        and _identity_matches(row, event_instrument)]
    normalized = normalize_complete_ohlcv(identified_stock, cutoff=cutoff)
    bars = normalized["bars"]
    event_date = str(event.get("periodEnd") or event.get("date") or "")[:10]
    index = next((position for position, bar in enumerate(bars)
                  if bar["date"] >= event_date), None)
    if index is None:
        return {
            "family": "D07", "propositionId": "SHO-D07-ORIGINAL",
            "lineage": "SHO_ORIGINAL", "status": "MISSING",
            "earningsQuality": None, "reaction": None,
            "validationStatus": "UNVALIDATED",
            "missing": ["post_earnings_complete_ohlcv"],
        }
    actual = _finite(event.get("epsActual"))
    estimate = _finite(event.get("epsEstimate"))
    supported_quality = event.get("qualitySupported") is True
    quality = copy.deepcopy(event.get("earningsQuality")) if supported_quality else None
    before = bars[index - 1] if index > 0 else None
    day = bars[index]
    gap = (round((day["open"] / before["close"] - 1) * 100, 6)
           if before else None)
    gap_retention = (round((day["close"] - before["close"])
                           / (day["open"] - before["close"]), 6)
                     if before and day["open"] != before["close"] else None)
    prior_volumes = [bar["volume"] for bar in bars[max(0, index - 20):index]]
    volume_ratio = (round(day["volume"] / statistics.mean(prior_volumes), 6)
                    if prior_volumes and statistics.mean(prior_volumes) > 0 else None)

    def comparison_return(rows: Iterable[Mapping[str, Any]], horizon: int) -> Optional[float]:
        other = normalize_complete_ohlcv(rows, cutoff=cutoff)["bars"]
        other_index = next((position for position, bar in enumerate(other)
                            if bar["date"] >= event_date), None)
        return (_bar_return(other, other_index, horizon)
                if other_index is not None else None)

    returns = {str(horizon): _bar_return(bars, index, horizon)
               for horizon in (1, 3, 5)}
    sector_return = comparison_return(sector_bars, 5)
    index_return = comparison_return(index_bars, 5)
    reaction5 = returns["5"]
    # v13.5.48: deterministic ARGUS candidate condition — the post-disclosure
    # reaction is positive (5-session return when available, else 1-session).
    # SHO-original earnings-quality parameters stay UNKNOWN; no consensus
    # dataset is contracted, so beat/miss is never synthesized.
    reaction_basis = ("5d" if reaction5 is not None else
                      "1d" if returns["1"] is not None else None)
    reaction_value = reaction5 if reaction5 is not None else returns["1"]
    return {
        "family": "D07", "propositionId": "SHO-D07-ORIGINAL",
        "lineage": "SHO_ORIGINAL", "status": "AVAILABLE",
        "conditionMet": (reaction_value > 0) if reaction_value is not None else None,
        "conditionRule": f"post-disclosure return ({reaction_basis or 'n/a'}) > 0",
        "conditionLineage": "ARGUS_CANDIDATE",
        "eventDate": event_date,
        "earningsQuality": quality,
        "earningsQualityStatus": "AVAILABLE" if quality is not None else "MISSING",
        "stockIdentityRejectedRowCount": len(stock_source) - len(identified_stock),
        "supportedBeatMiss": (
            "BEAT" if actual is not None and estimate is not None and actual > estimate
            else "MISS" if actual is not None and estimate is not None and actual < estimate
            else "INLINE" if actual is not None and estimate is not None else None),
        "reaction": {
            "return1dPct": returns["1"], "return3dPct": returns["3"],
            "return5dPct": reaction5, "gapPct": gap,
            "gapRetention": gap_retention, "volumeRatio20": volume_ratio,
            "relativeToSector5dPct": (round(reaction5 - sector_return, 6)
                                      if reaction5 is not None and sector_return is not None else None),
            "relativeToIndex5dPct": (round(reaction5 - index_return, 6)
                                     if reaction5 is not None and index_return is not None else None),
        },
        "validationStatus": "UNVALIDATED",
        "missing": ([] if quality is not None else ["supported_earnings_quality"])
        + ([] if sector_return is not None else ["sector_reaction"])
        + ([] if index_return is not None else ["index_reaction"]),
    }


def evaluate_d01_d07(*, cutoff: str,
                     two_market_rows: Iterable[Mapping[str, Any]] = (),
                     margin_1570_rows: Iterable[Mapping[str, Any]] = (),
                     relative_strength_direct: Optional[Mapping[str, Any]] = None,
                     relative_strength_proxy: Optional[Mapping[str, Any]] = None,
                     nikkei_eps: Optional[Mapping[str, Any]] = None,
                     nikkei_index: Optional[Mapping[str, Any]] = None,
                     nikkei_license_status: str = "LICENSE_BLOCKED",
                     foreign_flow_rows: Iterable[Mapping[str, Any]] = (),
                     vix_rows: Iterable[Mapping[str, Any]] = (),
                     earnings_event: Optional[Mapping[str, Any]] = None,
                     earnings_bars: Iterable[Mapping[str, Any]] = (),
                     sector_bars: Iterable[Mapping[str, Any]] = (),
                     comparison_index_bars: Iterable[Mapping[str, Any]] = ()) \
        -> Dict[str, Any]:
    families = {
        "D01": evaluate_d01(two_market_rows, cutoff=cutoff),
        "D02": evaluate_d02(margin_1570_rows, cutoff=cutoff),
        "D03": evaluate_d03(
            cutoff=cutoff, direct_evidence=relative_strength_direct,
            proxy_evidence=relative_strength_proxy),
        "D04": evaluate_d04(
            cutoff=cutoff, analysis_instrument="NIKKEI_225_INDEX",
            eps_evidence=nikkei_eps, index_evidence=nikkei_index,
            license_status=nikkei_license_status),
        "D05": evaluate_d05(foreign_flow_rows, cutoff=cutoff),
        "D06": evaluate_d06(vix_rows, cutoff=cutoff),
        "D07": evaluate_d07(
            cutoff=cutoff, earnings_event=earnings_event,
            stock_bars=earnings_bars, sector_bars=sector_bars,
            index_bars=comparison_index_bars),
    }
    body = {
        "schemaVersion": SHO_EVIDENCE_SCHEMA,
        "canonicalRfcSha256": CANONICAL_SHO_RFC_SHA256,
        "registrySha256": SHO_REGISTRY_SHA256,
        "informationCutoff": cutoff,
        "families": families,
        "action": None,
        "automaticAiCalls": 0,
    }
    return {**body, "artifactId": "sho-evidence-" + _sha256(body)}


def normalize_complete_ohlcv(rows: Iterable[Mapping[str, Any]], *, cutoff: str) \
        -> Dict[str, Any]:
    """PIT-normalize complete OHLCV; never fill any O/H/L/C/V component."""
    visible, pit_proof = point_in_time_rows(rows, cutoff)
    accepted: Dict[str, Dict[str, Any]] = {}
    ambiguous_dates = set()
    reasons: Dict[str, int] = {}

    def reject(reason: str) -> None:
        reasons[reason] = reasons.get(reason, 0) + 1

    for raw in visible:
        date = str(raw.get("date") or raw.get("periodEnd") or "")[:10]
        values = {key: _finite(raw.get(key)) for key in
                  ("open", "high", "low", "close", "volume")}
        if len(date) != 10:
            reject("invalid_date")
            continue
        if any(values[key] is None for key in values):
            reject("incomplete_ohlcv")
            continue
        open_, high, low, close, volume = (values[key] for key in
                                           ("open", "high", "low", "close", "volume"))
        assert None not in (open_, high, low, close, volume)
        if min(open_, high, low, close) <= 0 or volume < 0:
            reject("non_positive_price_or_negative_volume")
            continue
        if high < max(open_, close) or low > min(open_, close) or high < low:
            reject("invalid_ohlc_geometry")
            continue
        if date in ambiguous_dates:
            reject("ambiguous_duplicate_date")
            continue
        if date in accepted:
            del accepted[date]
            ambiguous_dates.add(date)
            reject("ambiguous_duplicate_date")
            reject("ambiguous_duplicate_date")
            continue
        accepted[date] = {
            "date": date, "open": open_, "high": high, "low": low,
            "close": close, "volume": volume,
            "availableFrom": raw.get("availableFrom"),
            "knownAt": raw.get("knownAt"), "publishedAt": raw.get("publishedAt"),
            "sourceRef": raw.get("sourceRef") or raw.get("source") or raw.get("sourceId"),
            "datasetId": raw.get("datasetId"),
            "revision": int(raw.get("revision") or 0),
            "adjusted": bool(raw.get("adjusted", False)),
        }
    bars = [accepted[key] for key in sorted(accepted)]
    proof_body = {
        "policyId": "sho-complete-ohlcv-v1",
        "pointInTimeProofId": pit_proof["proofId"],
        "pointInTimeProof": pit_proof,
        "visibleCount": pit_proof["includedCount"],
        "acceptedCount": len(bars),
        "rejectedCount": pit_proof["includedCount"] - len(bars),
        "rejectionReasons": dict(sorted(reasons.items())),
        "filledFields": [],
        "datasetHash": _sha256(bars),
    }
    return {
        "bars": bars,
        "proof": {**proof_body, "proofId": "sho-ohlcv-" + _sha256(proof_body)},
    }


def _sma(values: Sequence[float], window: int) -> List[Optional[float]]:
    out: List[Optional[float]] = [None] * len(values)
    running = 0.0
    for index, value in enumerate(values):
        running += value
        if index >= window:
            running -= values[index - window]
        if index + 1 >= window:
            out[index] = running / window
    return out


def _rsi(values: Sequence[float], window: int = 14) -> List[Optional[float]]:
    out: List[Optional[float]] = [None] * len(values)
    if len(values) <= window:
        return out
    gains = [max(values[index] - values[index - 1], 0.0)
             for index in range(1, len(values))]
    losses = [max(values[index - 1] - values[index], 0.0)
              for index in range(1, len(values))]
    average_gain = sum(gains[:window]) / window
    average_loss = sum(losses[:window]) / window

    def score(gain: float, loss: float) -> float:
        if loss == 0:
            return 100.0 if gain > 0 else 50.0
        return 100.0 - 100.0 / (1.0 + gain / loss)

    out[window] = score(average_gain, average_loss)
    for index in range(window + 1, len(values)):
        average_gain = (average_gain * (window - 1) + gains[index - 1]) / window
        average_loss = (average_loss * (window - 1) + losses[index - 1]) / window
        out[index] = score(average_gain, average_loss)
    return out


def _atr(bars: Sequence[Mapping[str, float]], window: int = 14) \
        -> List[Optional[float]]:
    out: List[Optional[float]] = [None] * len(bars)
    true_ranges = []
    for index, bar in enumerate(bars):
        previous = bars[index - 1]["close"] if index else bar["close"]
        true_ranges.append(max(
            bar["high"] - bar["low"], abs(bar["high"] - previous),
            abs(bar["low"] - previous)))
    if len(true_ranges) < window:
        return out
    current = sum(true_ranges[:window]) / window
    out[window - 1] = current
    for index in range(window, len(true_ranges)):
        current = (current * (window - 1) + true_ranges[index]) / window
        out[index] = current
    return out


def _sar(bars: Sequence[Mapping[str, float]]) -> List[Optional[float]]:
    if len(bars) < 2:
        return [None] * len(bars)
    out: List[Optional[float]] = [None] * len(bars)
    upward = bars[1]["close"] >= bars[0]["close"]
    acceleration = 0.02
    extreme = bars[0]["high"] if upward else bars[0]["low"]
    value = bars[0]["low"] if upward else bars[0]["high"]
    for index in range(1, len(bars)):
        value += acceleration * (extreme - value)
        if upward:
            value = min(value, bars[index - 1]["low"], bars[max(0, index - 2)]["low"])
            if bars[index]["low"] < value:
                upward, value, extreme, acceleration = False, extreme, bars[index]["low"], 0.02
            elif bars[index]["high"] > extreme:
                extreme = bars[index]["high"]
                acceleration = min(0.2, acceleration + 0.02)
        else:
            value = max(value, bars[index - 1]["high"], bars[max(0, index - 2)]["high"])
            if bars[index]["high"] > value:
                upward, value, extreme, acceleration = True, extreme, bars[index]["high"], 0.02
            elif bars[index]["low"] < extreme:
                extreme = bars[index]["low"]
                acceleration = min(0.2, acceleration + 0.02)
        out[index] = value
    return out


def _instrument_code(row: Mapping[str, Any]) -> str:
    return str(row.get("instrumentId") or row.get("instrument") or
               row.get("symbol") or "").upper()


def _identity_matches(row: Mapping[str, Any], identity: str) -> bool:
    observed = _instrument_code(row)
    accepted = {identity.upper()}
    if identity.isdigit():
        accepted.add(f"JP:{identity}:ETF")
    return observed in accepted


def _vix_identity_matches(row: Mapping[str, Any]) -> bool:
    return _instrument_code(row) in {"VIX", "VIX_INDEX", "^VIX", "CBOE:VIX:INDEX"}


def _rolling_midpoint(bars: Sequence[Mapping[str, Any]], window: int) \
        -> List[Optional[float]]:
    out: List[Optional[float]] = [None] * len(bars)
    for index in range(window - 1, len(bars)):
        sample = bars[index + 1 - window:index + 1]
        out[index] = (max(float(row["high"]) for row in sample)
                      + min(float(row["low"]) for row in sample)) / 2
    return out


def _technical_rows(bars: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """Build deterministic indicators from already strict complete OHLCV."""
    closes = [float(bar["close"]) for bar in bars]
    ma5, ma20, ma25 = _sma(closes, 5), _sma(closes, 20), _sma(closes, 25)
    rsi14, atr14, sar = _rsi(closes), _atr(bars), _sar(bars)
    macd = _macd(closes, ARGUS_MACD_BASELINE) if closes else []
    tenkan = _rolling_midpoint(bars, 9)
    kijun = _rolling_midpoint(bars, 26)
    span_b = _rolling_midpoint(bars, 52)
    result: List[Dict[str, Any]] = []
    for index, bar in enumerate(bars):
        middle = ma20[index]
        deviation = None
        if middle is not None:
            sample = closes[index - 19:index + 1]
            deviation = statistics.pstdev(sample)
        macd_ready = index + 1 >= sum(ARGUS_MACD_BASELINE[:2])
        span_a = ((tenkan[index] + kijun[index]) / 2
                  if tenkan[index] is not None and kijun[index] is not None
                  else None)
        result.append({
            "date": bar["date"],
            "open": bar["open"], "high": bar["high"], "low": bar["low"],
            "close": bar["close"], "volume": bar["volume"],
            "ma5": ma5[index], "ma20": middle, "ma25": ma25[index],
            "bollingerMiddle": middle,
            "bollingerLower2": middle - 2 * deviation
            if middle is not None and deviation is not None else None,
            "bollingerUpper2": middle + 2 * deviation
            if middle is not None and deviation is not None else None,
            "rsi14": rsi14[index], "atr14": atr14[index], "sar": sar[index],
            "macdLine": macd[index]["line"] if macd_ready else None,
            "macdSignal": macd[index]["signal"] if macd_ready else None,
            "macdHistogram": macd[index]["histogram"] if macd_ready else None,
            "ichimokuTenkan": tenkan[index], "ichimokuKijun": kijun[index],
            "ichimokuSpanA": span_a, "ichimokuSpanB": span_b[index],
        })
    return result


def _cross_above(previous_a: Any, previous_b: Any,
                 current_a: Any, current_b: Any) -> Optional[bool]:
    values = tuple(_finite(value) for value in
                   (previous_a, previous_b, current_a, current_b))
    if any(value is None for value in values):
        return None
    prior_a, prior_b, latest_a, latest_b = values
    assert None not in values
    return prior_a <= prior_b and latest_a > latest_b


def _cross_below(previous_a: Any, previous_b: Any,
                 current_a: Any, current_b: Any) -> Optional[bool]:
    values = tuple(_finite(value) for value in
                   (previous_a, previous_b, current_a, current_b))
    if any(value is None for value in values):
        return None
    prior_a, prior_b, latest_a, latest_b = values
    assert None not in values
    return prior_a >= prior_b and latest_a < latest_b


def _histogram_duration(rows: Sequence[Mapping[str, Any]], *, positive: bool) -> int:
    duration = 0
    for row in reversed(rows):
        value = _finite(row.get("macdHistogram"))
        if value is None or (value > 0) != positive or value == 0:
            break
        duration += 1
    return duration


def _recent_opposite_macd_cross(rows: Sequence[Mapping[str, Any]],
                                *, bullish_now: bool,
                                lookback: int = 3) -> Optional[bool]:
    ready = [row for row in rows if row.get("macdLine") is not None
             and row.get("macdSignal") is not None]
    if len(ready) < 3:
        return None
    start = max(1, len(ready) - lookback - 1)
    transitions = []
    for index in range(start, len(ready) - 1):
        up = _cross_above(
            ready[index - 1]["macdLine"], ready[index - 1]["macdSignal"],
            ready[index]["macdLine"], ready[index]["macdSignal"])
        down = _cross_below(
            ready[index - 1]["macdLine"], ready[index - 1]["macdSignal"],
            ready[index]["macdLine"], ready[index]["macdSignal"])
        if up:
            transitions.append("UP")
        if down:
            transitions.append("DOWN")
    wanted = "DOWN" if bullish_now else "UP"
    return wanted in transitions


def _condition(name: str, value: Optional[bool], *, date: Optional[str],
               details: Optional[Mapping[str, Any]] = None,
               lineage: str = "ARGUS_CANDIDATE") -> Dict[str, Any]:
    return {
        "indicator": name,
        "status": "AVAILABLE" if value is not None else "MISSING",
        "conditionMet": value,
        "evidenceDate": date if value is not None else None,
        "lineage": lineage,
        "validationStatus": "UNVALIDATED",
        "details": copy.deepcopy(dict(details or {})),
    }


def reversal_evidence(*, cutoff: str,
                      nikkei_rows: Iterable[Mapping[str, Any]] = (),
                      vix_rows: Iterable[Mapping[str, Any]] = ()) -> Dict[str, Any]:
    """Compute strict, point-in-time reversal evidence on two independent axes.

    Both instruments require complete O/H/L/C/V rows.  The VIX MACD parameters
    remain an explicitly unvalidated ARGUS candidate because the RFC does not
    establish the SHO-original parameters.
    """
    nikkei_source = list(nikkei_rows or [])
    vix_source = list(vix_rows or [])
    nikkei_identified = [row for row in nikkei_source
                         if isinstance(row, Mapping)
                         and _identity_matches(row, "NIKKEI_225_INDEX")]
    vix_identified = [row for row in vix_source
                      if isinstance(row, Mapping) and _vix_identity_matches(row)]
    nikkei_normalized = normalize_complete_ohlcv(
        nikkei_identified, cutoff=cutoff)
    vix_normalized = normalize_complete_ohlcv(vix_identified, cutoff=cutoff)
    nikkei = _technical_rows(nikkei_normalized["bars"])
    vix = _technical_rows(vix_normalized["bars"])
    n_previous = nikkei[-2] if len(nikkei) >= 2 else None
    n_current = nikkei[-1] if nikkei else None
    v_previous = vix[-2] if len(vix) >= 2 else None
    v_current = vix[-1] if vix else None

    band_walk_end = None
    sar_flip = nikkei_gc = bb_reclaim = ma25_reclaim = ma5_ma25_gc = None
    bb_failure = ma25_failure = None
    if n_previous and n_current:
        band_walk_end = _cross_above(
            n_previous["close"], n_previous["bollingerLower2"],
            n_current["close"], n_current["bollingerLower2"])
        sar_flip = _cross_above(
            n_previous["close"], n_previous["sar"],
            n_current["close"], n_current["sar"])
        nikkei_gc = _cross_above(
            n_previous["macdLine"], n_previous["macdSignal"],
            n_current["macdLine"], n_current["macdSignal"])
        bb_reclaim = _cross_above(
            n_previous["close"], n_previous["bollingerMiddle"],
            n_current["close"], n_current["bollingerMiddle"])
        ma25_reclaim = _cross_above(
            n_previous["close"], n_previous["ma25"],
            n_current["close"], n_current["ma25"])
        ma5_ma25_gc = _cross_above(
            n_previous["ma5"], n_previous["ma25"],
            n_current["ma5"], n_current["ma25"])
        bb_failure = _cross_below(
            n_previous["close"], n_previous["bollingerMiddle"],
            n_current["close"], n_current["bollingerMiddle"])
        ma25_failure = _cross_below(
            n_previous["close"], n_previous["ma25"],
            n_current["close"], n_current["ma25"])

    vix_dc = None
    if v_previous and v_current:
        vix_dc = _cross_below(
            v_previous["macdLine"], v_previous["macdSignal"],
            v_current["macdLine"], v_current["macdSignal"])

    resistance = None
    rsi_breakout = None
    if len(nikkei) >= 4 and n_current and n_previous:
        prior_values = [row["rsi14"] for row in nikkei[-22:-2]
                        if row.get("rsi14") is not None]
        if prior_values and n_previous.get("rsi14") is not None \
                and n_current.get("rsi14") is not None:
            resistance = max(prior_values)
            rsi_breakout = (n_previous["rsi14"] <= resistance
                            and n_current["rsi14"] > resistance)

    n_hist_slope = (n_current["macdHistogram"] - n_previous["macdHistogram"]
                    if n_current and n_previous
                    and n_current.get("macdHistogram") is not None
                    and n_previous.get("macdHistogram") is not None else None)
    v_hist_slope = (v_current["macdHistogram"] - v_previous["macdHistogram"]
                    if v_current and v_previous
                    and v_current.get("macdHistogram") is not None
                    and v_previous.get("macdHistogram") is not None else None)
    nikkei_fake = (_recent_opposite_macd_cross(nikkei, bullish_now=True)
                    if nikkei_gc else False if nikkei_gc is False else None)
    vix_fake = (_recent_opposite_macd_cross(vix, bullish_now=False)
                if vix_dc else False if vix_dc is False else None)
    n_date = n_current["date"] if n_current else None
    v_date = v_current["date"] if v_current else None
    factors = {
        "bandWalkEnding": _condition(
            "DOWNSIDE_BOLLINGER_MINUS_2_BAND_WALK_END", band_walk_end,
            date=n_date),
        "vixMacdDeadCross": _condition(
            "VIX_MACD_DEAD_CROSS", vix_dc, date=v_date,
            details={
                "parameters": {"fast": 12, "slow": 26, "signal": 9},
                "parameterLineage": "ARGUS_CANDIDATE",
                "shoOriginalParameters": "UNKNOWN",
                "histogramSlope": v_hist_slope,
                "histogramExpansion": (-v_hist_slope > 0
                                       if v_hist_slope is not None else None),
                "duration": _histogram_duration(vix, positive=False),
                "fakeCrossObserved": vix_fake,
                "fakeCrossProbability": None,
            }),
        "sarBullishFlip": _condition("PARABOLIC_SAR_BULLISH_FLIP", sar_flip,
                                      date=n_date),
        "nikkeiMacdGoldenCross": _condition(
            "NIKKEI_MACD_GOLDEN_CROSS", nikkei_gc, date=n_date,
            details={
                "parameters": {"fast": 12, "slow": 26, "signal": 9},
                "histogramSlope": n_hist_slope,
                "histogramExpansion": (n_hist_slope > 0
                                       if n_hist_slope is not None else None),
                "duration": _histogram_duration(nikkei, positive=True),
                "fakeCrossObserved": nikkei_fake,
                "fakeCrossProbability": None,
            }),
        "rsiResistanceBreakout": _condition(
            "RSI14_RESISTANCE_BREAKOUT", rsi_breakout, date=n_date,
            details={"resistance": resistance,
                     "current": n_current.get("rsi14") if n_current else None}),
        "bollingerMiddleReclaim": _condition(
            "BOLLINGER_MIDDLE_RECLAIM", bb_reclaim, date=n_date),
        "ma25Reclaim": _condition("MA25_RECLAIM", ma25_reclaim, date=n_date),
        "ma5Ma25GoldenCross": _condition(
            "MA5_MA25_GOLDEN_CROSS", ma5_ma25_gc, date=n_date),
        "reclaimFailure": _condition(
            "BOLLINGER_OR_MA25_RECLAIM_FAILURE",
            (bb_failure or ma25_failure)
            if bb_failure is not None and ma25_failure is not None else None,
            date=n_date,
            details={"bollingerMiddleFailure": bb_failure,
                     "ma25Failure": ma25_failure}),
    }
    body = {
        "schemaVersion": REVERSAL_SCHEMA,
        "canonicalRfcSha256": CANONICAL_SHO_RFC_SHA256,
        "informationCutoff": cutoff,
        "strictCompleteOhlcv": True,
        "nikkeiProof": nikkei_normalized["proof"],
        "vixProof": vix_normalized["proof"],
        "nikkeiIdentityRejectedRowCount": (
            len(nikkei_source) - len(nikkei_identified)),
        "vixIdentityRejectedRowCount": len(vix_source) - len(vix_identified),
        "factors": factors,
        "validationStatus": "UNVALIDATED",
        "probability": None,
    }
    return {**body, "artifactId": "sho-reversal-evidence-" + _sha256(body)}


def classify_reversal_state(evidence: Mapping[str, Any], *,
                            downside_background: str) -> Dict[str, Any]:
    """Reduce reversal evidence without allowing slow downside to veto it."""
    if downside_background not in {"FRAGILE", "DOWNSIDE_TRIGGERED",
                                   "SELL_OFF_ACTIVE", "MIXED"}:
        raise ValueError("invalid_downside_background")
    factors = evidence.get("factors") if isinstance(evidence, Mapping) else None
    if not isinstance(factors, Mapping):
        factors = {}

    def met(name: str) -> bool:
        factor = factors.get(name)
        return isinstance(factor, Mapping) and factor.get("conditionMet") is True

    early_names = (
        "bandWalkEnding", "vixMacdDeadCross", "sarBullishFlip",
        "nikkeiMacdGoldenCross",
    )
    continuation_names = (
        "rsiResistanceBreakout", "bollingerMiddleReclaim", "ma25Reclaim",
        "ma5Ma25GoldenCross",
    )
    early = [name for name in early_names if met(name)]
    continuation = [name for name in continuation_names if met(name)]
    false_rally = met("reclaimFailure") or any(
        isinstance(factors.get(name), Mapping)
        and isinstance(factors[name].get("details"), Mapping)
        and factors[name]["details"].get("fakeCrossObserved") is True
        for name in ("vixMacdDeadCross", "nikkeiMacdGoldenCross")
    )
    available = sum(
        isinstance(value, Mapping) and value.get("status") == "AVAILABLE"
        for value in factors.values()
    )
    if false_rally and len(early) < 2:
        state, rationale = "FALSE_RALLY", "failed reclaim or recent opposite cross"
    elif len(early) >= 3 and len(continuation) >= 1:
        state, rationale = "CONFIRMED_ADVANCE", "broad early reversal plus continuation"
    elif len(early) >= 2:
        state, rationale = "TECHNICAL_REBOUND", "independent early factors aligned"
    elif len(early) == 1:
        state, rationale = "REVERSAL_EARLY", "one early factor activated"
    elif len(continuation) >= 3:
        state, rationale = "CONFIRMED_ADVANCE", "broad continuation confirmation"
    elif continuation:
        state, rationale = "RECOVERY_TEST", "late recovery evidence without early cluster"
    elif available == 0:
        state, rationale = "MIXED", "reversal evidence is data-gated"
    else:
        state, rationale = downside_background, "no reversal factor supersedes background"
    return {
        "state": state,
        "status": "AVAILABLE" if available else "DATA_GATED",
        "earlyFactors": early,
        "continuationFactors": continuation,
        "independentEarlyFactorCount": len(early),
        "continuationFactorCount": len(continuation),
        "falseRallyEvidence": false_rally,
        "rationale": rationale,
        "probability": None,
        "validationStatus": "UNVALIDATED",
        "slowDownsideVetoApplied": False,
    }


def build_reversal_engine(*, cutoff: str, analysis_instrument: str,
                          downside_background: str,
                          nikkei_rows: Iterable[Mapping[str, Any]] = (),
                          vix_rows: Iterable[Mapping[str, Any]] = ()) -> Dict[str, Any]:
    if not isinstance(analysis_instrument, str) or not analysis_instrument \
            or analysis_instrument != analysis_instrument.strip() \
            or len(analysis_instrument) > 120:
        raise ValueError("invalid_analysis_instrument")
    evidence = reversal_evidence(
        cutoff=cutoff, nikkei_rows=nikkei_rows, vix_rows=vix_rows)
    axis = classify_reversal_state(
        evidence, downside_background=downside_background)
    body = {
        "schemaVersion": REVERSAL_SCHEMA,
        "canonicalRfcSha256": CANONICAL_SHO_RFC_SHA256,
        "analysisInstrument": analysis_instrument,
        "informationCutoff": cutoff,
        "downsideAxis": {
            "state": downside_background,
            "computedIndependently": True,
        },
        "reversalAxis": axis,
        "evidenceArtifactId": evidence["artifactId"],
        "evidenceArtifact": evidence,
        "evidence": evidence["factors"],
        "stateMayJump": True,
        "oneStepTransitionRequired": False,
        "action": None,
        "automaticAiCalls": 0,
    }
    artifact = _BuilderIssuedReversalArtifact({
        **body, "artifactId": "sho-reversal-" + _sha256(body),
    })
    artifact._authority_seal = _REVERSAL_ARTIFACT_SEAL
    artifact._body_digest = _sha256(artifact)
    return artifact


def _sha256_text(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(
        character in "0123456789abcdef" for character in value)


def _exact_nonnegative_integer(value: Any) -> bool:
    return type(value) is int and value >= 0


def _finite_or_none(value: Any) -> bool:
    return value is None or (
        type(value) in (int, float) and math.isfinite(float(value)))


def _validate_pit_proof(value: Any, information_cutoff: Any) -> bool:
    expected = {
        "cutoff", "datasetHash", "excludedFutureCount",
        "excludedMalformedCount", "futureRowsAdmitted", "includedCount",
        "inputCount", "policyId", "proofId",
    }
    if not isinstance(value, Mapping) or set(value) != expected:
        return False
    proof = dict(value)
    count_keys = (
        "excludedFutureCount", "excludedMalformedCount", "includedCount",
        "inputCount",
    )
    if not all(_exact_nonnegative_integer(proof.get(key))
               for key in count_keys) or \
            proof["includedCount"] > proof["inputCount"] or \
            proof["excludedFutureCount"] > proof["inputCount"] or \
            proof["excludedMalformedCount"] > proof["inputCount"] or \
            proof["includedCount"] + proof["excludedFutureCount"] + \
            proof["excludedMalformedCount"] > proof["inputCount"] or \
            proof.get("futureRowsAdmitted") is not False or \
            proof.get("policyId") != "sho-explicit-publication-pit-v1" or \
            proof.get("cutoff") != information_cutoff or \
            not _sha256_text(proof.get("datasetHash")):
        return False
    body = copy.deepcopy(proof)
    proof_id = body.pop("proofId", None)
    return proof_id == "sho-pit-" + _sha256(body)


def _validate_ohlcv_proof(value: Any, information_cutoff: Any) -> bool:
    expected = {
        "acceptedCount", "datasetHash", "filledFields",
        "pointInTimeProof", "pointInTimeProofId", "policyId", "proofId",
        "rejectedCount", "rejectionReasons", "visibleCount",
    }
    if not isinstance(value, Mapping) or set(value) != expected:
        return False
    proof = dict(value)
    counts = tuple(proof.get(key) for key in (
        "acceptedCount", "rejectedCount", "visibleCount"))
    reasons = proof.get("rejectionReasons")
    if not all(_exact_nonnegative_integer(item) for item in counts) or \
            counts[0] + counts[1] != counts[2] or \
            not isinstance(reasons, Mapping) or \
            not all(isinstance(key, str) and key and
                    _exact_nonnegative_integer(count)
                    for key, count in reasons.items()) or \
            sum(reasons.values()) != counts[1] or \
            proof.get("filledFields") != [] or \
            proof.get("policyId") != "sho-complete-ohlcv-v1" or \
            not _sha256_text(proof.get("datasetHash")) or \
            not _validate_pit_proof(
                proof.get("pointInTimeProof"), information_cutoff) or \
            proof.get("pointInTimeProofId") != proof[
                "pointInTimeProof"].get("proofId") or \
            proof.get("visibleCount") != proof[
                "pointInTimeProof"].get("includedCount"):
        return False
    body = copy.deepcopy(proof)
    proof_id = body.pop("proofId", None)
    return proof_id == "sho-ohlcv-" + _sha256(body)


def _factor_date_is_bounded(value: Any, cutoff: datetime) -> bool:
    if not isinstance(value, str) or len(value) != 10:
        return False
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d").date()
    except (TypeError, ValueError, OverflowError):
        return False
    return parsed.isoformat() == value and parsed <= cutoff.date()


def _validate_reversal_factor(name: str, value: Any,
                              cutoff: datetime) -> bool:
    indicators = {
        "bandWalkEnding": "DOWNSIDE_BOLLINGER_MINUS_2_BAND_WALK_END",
        "vixMacdDeadCross": "VIX_MACD_DEAD_CROSS",
        "sarBullishFlip": "PARABOLIC_SAR_BULLISH_FLIP",
        "nikkeiMacdGoldenCross": "NIKKEI_MACD_GOLDEN_CROSS",
        "rsiResistanceBreakout": "RSI14_RESISTANCE_BREAKOUT",
        "bollingerMiddleReclaim": "BOLLINGER_MIDDLE_RECLAIM",
        "ma25Reclaim": "MA25_RECLAIM",
        "ma5Ma25GoldenCross": "MA5_MA25_GOLDEN_CROSS",
        "reclaimFailure": "BOLLINGER_OR_MA25_RECLAIM_FAILURE",
    }
    expected = {
        "conditionMet", "details", "evidenceDate", "indicator", "lineage",
        "status", "validationStatus",
    }
    if name not in indicators or not isinstance(value, Mapping) or \
            set(value) != expected:
        return False
    factor = dict(value)
    condition = factor.get("conditionMet")
    evidence_date = factor.get("evidenceDate")
    if condition is not None and type(condition) is not bool:
        return False
    if factor.get("indicator") != indicators[name] or \
            factor.get("lineage") != "ARGUS_CANDIDATE" or \
            factor.get("validationStatus") != "UNVALIDATED" or \
            not isinstance(factor.get("details"), Mapping) or \
            (condition is None and (
                factor.get("status") != "MISSING" or evidence_date is not None)) or \
            (type(condition) is bool and (
                factor.get("status") != "AVAILABLE" or
                not _factor_date_is_bounded(evidence_date, cutoff))):
        return False
    details = dict(factor["details"])
    if name in {
            "bandWalkEnding", "sarBullishFlip", "bollingerMiddleReclaim",
            "ma25Reclaim", "ma5Ma25GoldenCross"}:
        return details == {}
    if name == "rsiResistanceBreakout":
        return set(details) == {"current", "resistance"} and all(
            _finite_or_none(details[key]) for key in details)
    if name == "reclaimFailure":
        if set(details) != {"bollingerMiddleFailure", "ma25Failure"} or \
                any(item is not None and type(item) is not bool
                    for item in details.values()):
            return False
        left, right = (details["bollingerMiddleFailure"],
                       details["ma25Failure"])
        derived = (left or right) if left is not None and right is not None \
            else None
        return condition is derived or condition == derived
    macd_common = {
        "duration", "fakeCrossObserved", "fakeCrossProbability",
        "histogramExpansion", "histogramSlope", "parameters",
    }
    expected_details = (macd_common | {
        "parameterLineage", "shoOriginalParameters"}
        if name == "vixMacdDeadCross" else macd_common)
    if set(details) != expected_details or \
            details.get("parameters") != {"fast": 12, "slow": 26, "signal": 9} or \
            not _exact_nonnegative_integer(details.get("duration")) or \
            details.get("fakeCrossProbability") is not None or \
            not _finite_or_none(details.get("histogramSlope")) or \
            any(details.get(key) is not None and
                type(details.get(key)) is not bool
                for key in ("fakeCrossObserved", "histogramExpansion")):
        return False
    if name == "vixMacdDeadCross" and (
            details.get("parameterLineage") != "ARGUS_CANDIDATE" or
            details.get("shoOriginalParameters") != "UNKNOWN"):
        return False
    return True


def _validate_reversal_evidence_artifact(value: Any,
                                         cutoff: datetime) -> bool:
    expected = {
        "artifactId", "canonicalRfcSha256", "factors",
        "informationCutoff", "nikkeiIdentityRejectedRowCount",
        "nikkeiProof", "probability", "schemaVersion", "strictCompleteOhlcv",
        "validationStatus", "vixIdentityRejectedRowCount", "vixProof",
    }
    if not isinstance(value, Mapping) or set(value) != expected:
        return False
    artifact = dict(value)
    factor_names = {
        "bandWalkEnding", "vixMacdDeadCross", "sarBullishFlip",
        "nikkeiMacdGoldenCross", "rsiResistanceBreakout",
        "bollingerMiddleReclaim", "ma25Reclaim", "ma5Ma25GoldenCross",
        "reclaimFailure",
    }
    factors = artifact.get("factors")
    structurally_valid = (
        artifact.get("schemaVersion") == REVERSAL_SCHEMA and
        artifact.get("canonicalRfcSha256") == CANONICAL_SHO_RFC_SHA256 and
        artifact.get("strictCompleteOhlcv") is True and
        artifact.get("validationStatus") == "UNVALIDATED" and
        artifact.get("probability") is None and
        _exact_nonnegative_integer(
            artifact.get("nikkeiIdentityRejectedRowCount")) and
        _exact_nonnegative_integer(
            artifact.get("vixIdentityRejectedRowCount")) and
        _validate_ohlcv_proof(
            artifact.get("nikkeiProof"), artifact.get("informationCutoff")) and
        _validate_ohlcv_proof(
            artifact.get("vixProof"), artifact.get("informationCutoff")) and
        isinstance(factors, Mapping) and set(factors) == factor_names and
        all(_validate_reversal_factor(name, factors[name], cutoff)
            for name in factor_names) and
        _content_id_valid(artifact, "sho-reversal-evidence-")
    )
    if not structurally_valid:
        return False
    nikkei_count = artifact["nikkeiProof"]["acceptedCount"]
    vix_count = artifact["vixProof"]["acceptedCount"]
    minimum_rows = {
        "bandWalkEnding": (nikkei_count, 21),
        "sarBullishFlip": (nikkei_count, 3),
        "nikkeiMacdGoldenCross": (nikkei_count, 39),
        "rsiResistanceBreakout": (nikkei_count, 17),
        "bollingerMiddleReclaim": (nikkei_count, 21),
        "ma25Reclaim": (nikkei_count, 26),
        "ma5Ma25GoldenCross": (nikkei_count, 26),
        "reclaimFailure": (nikkei_count, 26),
        "vixMacdDeadCross": (vix_count, 39),
    }
    return all(
        factors[name]["status"] == (
            "AVAILABLE" if count >= minimum else "MISSING")
        for name, (count, minimum) in minimum_rows.items()
    )


def validate_reversal_artifact(value: Any) -> Dict[str, Any]:
    """Validate the compact content-addressed SHO reversal artifact."""
    expected = {
        "action", "analysisInstrument", "artifactId", "automaticAiCalls",
        "canonicalRfcSha256", "downsideAxis", "evidence",
        "evidenceArtifact", "evidenceArtifactId", "informationCutoff",
        "oneStepTransitionRequired", "reversalAxis", "schemaVersion",
        "stateMayJump",
    }
    if not isinstance(value, Mapping) or set(value) != expected:
        raise ValueError("invalid_reversal_artifact_fields")
    artifact = copy.deepcopy(dict(value))
    if artifact.get("schemaVersion") != REVERSAL_SCHEMA or \
            artifact.get("canonicalRfcSha256") != CANONICAL_SHO_RFC_SHA256 or \
            not isinstance(artifact.get("analysisInstrument"), str) or \
            not artifact["analysisInstrument"] or \
            artifact["analysisInstrument"] != \
            artifact["analysisInstrument"].strip() or \
            len(artifact["analysisInstrument"]) > 120:
        raise ValueError("invalid_reversal_artifact_identity")
    cutoff = _cutoff(artifact.get("informationCutoff"))
    if artifact.get("action") is not None or \
            artifact.get("automaticAiCalls") != 0 or \
            artifact.get("stateMayJump") is not True or \
            artifact.get("oneStepTransitionRequired") is not False or \
            not isinstance(artifact.get("downsideAxis"), Mapping) or \
            not isinstance(artifact.get("reversalAxis"), Mapping) or \
            not isinstance(artifact.get("evidence"), Mapping):
        raise ValueError("invalid_reversal_artifact_semantics")
    downside = artifact["downsideAxis"]
    if set(downside) != {"computedIndependently", "state"} or \
            downside.get("computedIndependently") is not True or \
            downside.get("state") not in {
                "FRAGILE", "DOWNSIDE_TRIGGERED", "SELL_OFF_ACTIVE", "MIXED"}:
        raise ValueError("invalid_reversal_downside_axis")
    evidence_artifact = artifact.get("evidenceArtifact")
    if not isinstance(evidence_artifact, Mapping) or \
            not _validate_reversal_evidence_artifact(
                evidence_artifact, cutoff) or \
            not _content_id_valid(
                evidence_artifact, "sho-reversal-evidence-") or \
            artifact.get("evidenceArtifactId") != evidence_artifact.get(
                "artifactId") or \
            artifact.get("evidence") != evidence_artifact.get("factors") or \
            evidence_artifact.get("canonicalRfcSha256") != \
            CANONICAL_SHO_RFC_SHA256 or \
            evidence_artifact.get("informationCutoff") != artifact.get(
                "informationCutoff"):
        raise ValueError("invalid_reversal_evidence_artifact")
    band = artifact["evidence"].get("bandWalkEnding")
    condition = band.get("conditionMet") if isinstance(band, Mapping) else None
    if not isinstance(band, Mapping) or set(band) != {
            "conditionMet", "details", "evidenceDate", "indicator",
            "lineage", "status", "validationStatus"} or \
            condition not in (True, False, None) or \
            (condition is not None and not isinstance(condition, bool)) or \
            band.get("indicator") != \
            "DOWNSIDE_BOLLINGER_MINUS_2_BAND_WALK_END" or \
            band.get("lineage") != "ARGUS_CANDIDATE" or \
            band.get("validationStatus") != "UNVALIDATED" or \
            not isinstance(band.get("details"), Mapping) or \
            (condition is None and (
                band.get("status") != "MISSING" or
                band.get("evidenceDate") is not None)) or \
            (isinstance(condition, bool) and (
                band.get("status") != "AVAILABLE" or
                not isinstance(band.get("evidenceDate"), str))):
        raise ValueError("invalid_band_walk_ending_evidence")
    if band.get("evidenceDate") is not None:
        evidence_date = _instant(band["evidenceDate"])
        if evidence_date is None or evidence_date.date() > cutoff.date():
            raise ValueError("band_walk_evidence_after_cutoff")
    expected_axis = classify_reversal_state(
        evidence_artifact, downside_background=downside["state"])
    if artifact.get("reversalAxis") != expected_axis:
        raise ValueError("invalid_reversal_axis")
    if not _content_id_valid(artifact, "sho-reversal-"):
        raise ValueError("invalid_reversal_artifact_id")
    return artifact


def is_builder_issued_reversal_artifact(value: Any) -> bool:
    """Return whether ``value`` is an unmodified canonical-builder result."""
    try:
        return bool(
            isinstance(value, _BuilderIssuedReversalArtifact)
            and getattr(value, "_authority_seal", None) is _REVERSAL_ARTIFACT_SEAL
            and getattr(value, "_body_digest", None) == _sha256(value)
            and validate_reversal_artifact(value) == value
        )
    except (TypeError, ValueError):
        return False


def _target_candidate(family: str, label: str, level: Any,
                      *, provenance: str = "DERIVED",
                      source_ref: Optional[str] = None) -> Optional[Dict[str, Any]]:
    value = _finite(level)
    if value is None or value <= 0:
        return None
    return {
        "family": family,
        "theoryRef": label,
        "level": round(value, 8),
        "provenance": provenance,
        "sourceRef": source_ref,
    }


def build_target_zones(*, cutoff: str, analysis_instrument: str,
                       bars: Iterable[Mapping[str, Any]] = (),
                       swing_low: Optional[float] = None,
                       swing_high: Optional[float] = None,
                       previous_high: Optional[float] = None,
                       gap_evidence: Iterable[Mapping[str, Any]] = (),
                       observed_volume_profile: Iterable[Mapping[str, Any]] = (),
                       eps_evidence: Optional[Mapping[str, Any]] = None,
                       valuation_license_status: str = "LICENSE_BLOCKED") \
        -> Dict[str, Any]:
    """Create deterministic upside zones; validation metrics remain null."""
    if valuation_license_status not in {"AVAILABLE", "LICENSE_BLOCKED", "MISSING"}:
        raise ValueError("invalid_nikkei_valuation_license_status")
    source_bars = list(bars or [])
    identity_bars = [row for row in source_bars if isinstance(row, Mapping)
                     and _identity_matches(row, analysis_instrument)]
    normalized = normalize_complete_ohlcv(identity_bars, cutoff=cutoff)
    technical = _technical_rows(normalized["bars"])
    current = technical[-1] if technical else None
    current_price = _finite(current.get("close")) if current else None
    atr14 = _finite(current.get("atr14")) if current else None
    missing: List[str] = []
    candidates: List[Dict[str, Any]] = []

    def add(candidate: Optional[Dict[str, Any]]) -> None:
        if candidate is not None and current_price is not None \
                and candidate["level"] > current_price:
            candidates.append(candidate)

    if current is not None:
        add(_target_candidate("BOLLINGER", "BOLLINGER_MIDDLE",
                              current.get("bollingerMiddle")))
        add(_target_candidate("MOVING_AVERAGE", "MA25", current.get("ma25")))
        for label in ("ichimokuTenkan", "ichimokuKijun",
                      "ichimokuSpanA", "ichimokuSpanB"):
            add(_target_candidate("ICHIMOKU", label.upper(), current.get(label)))
        if atr14 is not None:
            add(_target_candidate("ATR", "ATR_1", current_price + atr14))
            add(_target_candidate("ATR", "ATR_2", current_price + 2 * atr14))
        else:
            missing.append("atr14_history")
    else:
        missing.append("complete_ohlcv")

    low, high = _finite(swing_low), _finite(swing_high)
    if low is not None and high is not None and 0 < low < high:
        for ratio in (0.382, 0.5, 0.618, 0.786, 1.0):
            add(_target_candidate(
                "FIBONACCI", f"FIB_{ratio:g}", low + ratio * (high - low)))
    else:
        missing.append("explicit_valid_swing_low_high")

    prior = _finite(previous_high)
    if prior is not None:
        add(_target_candidate("PRICE_STRUCTURE", "PREVIOUS_HIGH", prior))
    else:
        missing.append("previous_high")

    gap_source = list(gap_evidence or [])
    gap_identity_rows = [row for row in gap_source if isinstance(row, Mapping)
                         and _identity_matches(row, analysis_instrument)]
    visible_gaps, gap_proof = point_in_time_rows(gap_identity_rows, cutoff)
    for row in visible_gaps:
        if row.get("filled") is not False:
            continue
        add(_target_candidate(
            "GAP", str(row.get("gapId") or "UNFILLED_GAP"),
            row.get("level", row.get("value")), provenance="OBSERVED",
            source_ref=row.get("sourceRef")))

    profile_source = list(observed_volume_profile or [])
    profile_identity_rows = [row for row in profile_source
                             if isinstance(row, Mapping)
                             and _identity_matches(row, analysis_instrument)]
    visible_profile, profile_proof = point_in_time_rows(
        profile_identity_rows, cutoff)
    for row in visible_profile:
        if row.get("provenance") != "OBSERVED" or not row.get("sourceRef"):
            continue
        add(_target_candidate(
            "VOLUME_PROFILE", str(row.get("levelId") or "OBSERVED_NODE"),
            row.get("level", row.get("value")), provenance="OBSERVED",
            source_ref=row.get("sourceRef")))

    eps_identity_ok = (isinstance(eps_evidence, Mapping)
                       and _identity_matches(eps_evidence, "NIKKEI_225_INDEX"))
    eps = _value_and_time(eps_evidence, cutoff) if eps_identity_ok else None
    if analysis_instrument == "NIKKEI_225_INDEX" \
            and valuation_license_status == "AVAILABLE" and eps is not None:
        for multiple in (17, 18, 19, 20, 21):
            add(_target_candidate(
                "VALUATION", f"NIKKEI_EPS_X_PER_{multiple}",
                eps["value"] * multiple, provenance="OBSERVED",
                source_ref=eps.get("sourceRef")))
    elif analysis_instrument == "NIKKEI_225_INDEX":
        missing.append("licensed_nikkei_eps_per")
    elif eps_evidence is not None:
        missing.append("nikkei_valuation_not_applicable_to_proxy_or_topix")

    candidates.sort(key=lambda row: (row["level"], row["theoryRef"]))
    clusters: List[List[Dict[str, Any]]] = []
    if atr14 is not None and atr14 > 0:
        tolerance = 0.5 * atr14
        for candidate in candidates:
            if clusters and candidate["level"] - clusters[-1][-1]["level"] <= tolerance:
                clusters[-1].append(candidate)
            else:
                clusters.append([candidate])
    else:
        tolerance = None

    zones = []
    for index, cluster in enumerate(clusters, start=1):
        levels = [row["level"] for row in cluster]
        if len(levels) == 1 or max(levels) == min(levels):
            assert atr14 is not None
            pad = max(levels[0] * 0.0005, atr14 * 0.05)
            lower, upper = levels[0] - pad, levels[0] + pad
        else:
            lower, upper = min(levels), max(levels)
        center = statistics.mean(levels)
        distance_atr = ((center - current_price) / atr14
                        if current_price is not None and atr14 else None)
        horizon = (1 if distance_atr is not None and distance_atr <= 1 else
                   5 if distance_atr is not None and distance_atr <= 2 else
                   10 if distance_atr is not None and distance_atr <= 4 else
                   20 if distance_atr is not None and distance_atr <= 8 else 40)
        refs = sorted({row["theoryRef"] for row in cluster})
        families = sorted({row["family"] for row in cluster})
        zones.append({
            "zoneId": f"TZ{index:02d}",
            "lower": round(lower, 8), "center": round(center, 8),
            "upper": round(upper, 8), "horizonSessions": horizon,
            "theoryRefs": refs, "theoryFamilies": families,
            "independentTheoryCount": len(families),
            "hitProbability": None, "breakProbability": None,
            "medianTimeToTarget": None, "maeBeforeTarget": None,
            "sampleSize": 0, "confidenceInterval": None,
            "hit_probability": None, "break_probability": None,
            "median_time_to_target": None, "mae_before_target": None,
            "MAE_before_target": None,
            "sample_size": 0, "confidence_interval": None,
            "validationStatus": "UNVALIDATED",
            "validationArtifactId": None,
            "policyId": TARGET_CLUSTER_POLICY_ID,
            "policyHash": TARGET_CLUSTER_POLICY_SHA256,
        })

    body = {
        "schemaVersion": TARGET_LADDER_SCHEMA,
        "canonicalRfcSha256": CANONICAL_SHO_RFC_SHA256,
        "informationCutoff": cutoff,
        "analysisInstrument": analysis_instrument,
        "analysisPrice": current_price,
        "strictCompleteOhlcv": True,
        "identityRejectedRowCount": len(source_bars) - len(identity_bars),
        "barProof": normalized["proof"],
        "gapPointInTimeProof": gap_proof,
        "gapIdentityRejectedRowCount": len(gap_source) - len(gap_identity_rows),
        "volumeProfilePointInTimeProof": profile_proof,
        "volumeProfileIdentityRejectedRowCount": (
            len(profile_source) - len(profile_identity_rows)),
        "epsIdentityRejected": eps_evidence is not None and not eps_identity_ok,
        "clusterPolicy": copy.deepcopy(TARGET_CLUSTER_POLICY),
        "clusterPolicyHash": TARGET_CLUSTER_POLICY_SHA256,
        "candidateLevels": candidates,
        "zones": zones,
        "status": ("AVAILABLE" if zones else
                   "DATA_GATED" if current_price is not None else "MISSING"),
        "validationStatus": "UNVALIDATED",
        "probabilitiesWithheldPendingValidation": True,
        "missing": sorted(set(missing)),
        "action": None,
    }
    return {**body, "artifactId": "sho-targets-" + _sha256(body)}


def build_direct_index_model(*, cutoff: str, analysis_instrument: str,
                             direct_rows: Iterable[Mapping[str, Any]] = (),
                             proxy_rows: Iterable[Mapping[str, Any]] = (),
                             topix_evidence: Iterable[Mapping[str, Any]] = ()) \
        -> Dict[str, Any]:
    """Keep direct index evidence and tradable proxy evidence non-substitutable."""
    if analysis_instrument not in ANALYSIS_INSTRUMENTS:
        raise ValueError("analysis_instrument_must_be_direct_nikkei_or_topix")
    proxy = DIRECT_INDEX_TO_PROXY[analysis_instrument]
    direct_source = list(direct_rows or [])
    proxy_source = list(proxy_rows or [])
    direct_identity_rows = [dict(row) for row in direct_source
                            if isinstance(row, Mapping)
                            and _identity_matches(row, analysis_instrument)]
    proxy_identity_rows = [dict(row) for row in proxy_source
                           if isinstance(row, Mapping)
                           and _identity_matches(row, proxy)]
    direct = normalize_complete_ohlcv(direct_identity_rows, cutoff=cutoff)
    tradable = normalize_complete_ohlcv(proxy_identity_rows, cutoff=cutoff)
    direct_latest = direct["bars"][-1] if direct["bars"] else None
    proxy_latest = tradable["bars"][-1] if tradable["bars"] else None

    topix_dimensions = {
        name: {"status": "MISSING", "value": None, "provenance": None,
               "sourceRef": None}
        for name in (
            "breadth", "core30", "large70", "mid400", "small", "value",
            "growth", "sectors33", "nikkeiTopixRelativeStrength",
            "foreignFlows", "rotation",
        )
    }
    topix_source = list(topix_evidence or [])
    topix_identity_rows = [row for row in topix_source
                           if isinstance(row, Mapping)
                           and _identity_matches(row, "TOPIX_INDEX")]
    topix_visible, topix_proof = point_in_time_rows(topix_identity_rows, cutoff)
    if analysis_instrument == "TOPIX_INDEX":
        aliases = {
            "breadth": "breadth", "core30": "core30", "large70": "large70",
            "mid400": "mid400", "small": "small", "value": "value",
            "growth": "growth", "sectors33": "sectors33",
            "nikkei_topix_relative_strength": "nikkeiTopixRelativeStrength",
            "foreign_flows": "foreignFlows", "rotation": "rotation",
        }
        for row in topix_visible:
            key = aliases.get(str(row.get("field") or row.get("seriesId") or ""))
            if key is None:
                continue
            provenance = str(row.get("provenance") or "UNKNOWN").upper()
            topix_dimensions[key] = {
                "status": "AVAILABLE", "value": copy.deepcopy(row.get("value")),
                "provenance": provenance if provenance in PROVENANCE_CLASSES else "UNKNOWN",
                "sourceRef": row.get("sourceRef"),
            }

    body = {
        "schemaVersion": DIRECT_INDEX_SCHEMA,
        "canonicalRfcSha256": CANONICAL_SHO_RFC_SHA256,
        "informationCutoff": cutoff,
        "analysisInstrument": {
            "instrumentId": analysis_instrument, "instrumentType": "INDEX",
            "status": "AVAILABLE" if direct_latest else "DATA_GATED",
            "latestClose": direct_latest["close"] if direct_latest else None,
            "barProof": direct["proof"],
            "identityRejectedRowCount": len(direct_source) - len(direct_identity_rows),
        },
        "tradableProxy": {
            "instrumentId": proxy, "instrumentType": "ETF",
            "status": "AVAILABLE" if proxy_latest else "MISSING",
            "latestClose": proxy_latest["close"] if proxy_latest else None,
            "barProof": tradable["proof"],
            "identityRejectedRowCount": len(proxy_source) - len(proxy_identity_rows),
        },
        "proxyUsedAsDirectIndex": False,
        "valuationAppliedToProxy": False,
        "topixDimensions": topix_dimensions if analysis_instrument == "TOPIX_INDEX" else None,
        "topixPointInTimeProof": topix_proof,
        "topixIdentityRejectedRowCount": len(topix_source) - len(topix_identity_rows),
        "topixTheoreticalValue": None,
        "status": "AVAILABLE" if direct_latest else "DATA_GATED",
        "missing": ([] if direct_latest else ["direct_verified_index_ohlcv"]),
        "action": None,
    }
    return {**body, "artifactId": "sho-direct-index-" + _sha256(body)}


def validate_evidence_provenance(
        rows: Iterable[Mapping[str, Any]], *, cutoff: str) -> Dict[str, Any]:
    """Validate stock-lens provenance without upgrading inference to fact."""
    limit = _cutoff(cutoff)
    source = list(rows or [])
    buckets: Dict[str, List[Dict[str, Any]]] = {
        "observed": [], "derived": [], "inferred": [], "unknown": [],
        "rejected": [],
    }
    admitted: Dict[str, Tuple[datetime, int, Dict[str, Any]]] = {}
    for raw in source:
        if not isinstance(raw, Mapping):
            buckets["rejected"].append({"reason": "not_object"})
            continue
        row = copy.deepcopy(dict(raw))
        try:
            _canonical_bytes(row)
        except (TypeError, ValueError, OverflowError):
            buckets["rejected"].append({"reason": "not_canonical_json"})
            continue
        evidence_id = str(row.get("evidenceId") or row.get("field") or "")
        provenance = str(row.get("provenance") or "UNKNOWN").upper()
        known = _knowledge_time(row)
        revision = row.get("revision", 0)
        if not evidence_id:
            buckets["rejected"].append({**row, "reason": "missing_evidence_id"})
            continue
        if "value" not in row or row.get("value") is None:
            buckets["rejected"].append({**row, "reason": "missing_value"})
            continue
        if known is None:
            buckets["rejected"].append({**row, "reason": "missing_or_invalid_knowledge_time"})
            continue
        if known > limit:
            buckets["rejected"].append({**row, "reason": "future_at_cutoff"})
            continue
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
            buckets["rejected"].append({**row, "reason": "invalid_revision"})
            continue
        if provenance == "OBSERVED" and (
                not row.get("sourceRef") or _instant(row.get("availableFrom")) is None):
            buckets["rejected"].append({
                **row, "reason": "observed_requires_source_ref_and_available_from"})
            continue
        if provenance == "DERIVED" and not (
                isinstance(row.get("derivedFrom"), (list, tuple))
                and len(row["derivedFrom"]) > 0):
            buckets["rejected"].append({
                **row, "reason": "derived_requires_derived_from"})
            continue
        if provenance == "INFERRED" and not row.get("inferenceMethod"):
            buckets["rejected"].append({
                **row, "reason": "inferred_requires_method"})
            continue
        if provenance not in PROVENANCE_CLASSES:
            buckets["unknown"].append({**row, "provenance": "UNKNOWN"})
            continue
        previous = admitted.get(evidence_id)
        candidate = (known, revision, {**row, "evidenceId": evidence_id,
                                       "provenance": provenance})
        if previous is None or (revision, known) > (previous[1], previous[0]):
            admitted[evidence_id] = candidate
    for _, _, row in sorted(admitted.values(), key=lambda item: (
            item[0], item[2]["evidenceId"])):
        buckets[row["provenance"].lower()].append(row)
    proof_body = {
        "policyId": "sho-stock-evidence-provenance-v1",
        "cutoff": cutoff,
        "inputCount": len(source),
        "observedCount": len(buckets["observed"]),
        "derivedCount": len(buckets["derived"]),
        "inferredCount": len(buckets["inferred"]),
        "unknownCount": len(buckets["unknown"]),
        "rejectedCount": len(buckets["rejected"]),
        "inferredPromotedToObserved": False,
        "datasetHash": _sha256({key: buckets[key] for key in
                                ("observed", "derived", "inferred", "unknown")}),
    }
    return {**buckets, "proof": {
        **proof_body, "proofId": "sho-provenance-" + _sha256(proof_body)}}


def _classify_supply_state(
        provenance: Mapping[str, Sequence[Mapping[str, Any]]]) -> Dict[str, Any]:
    usable = list(provenance.get("observed", ())) + list(
        provenance.get("derived", ()))
    latest = {str(row.get("evidenceId")): row for row in usable}

    def number(name: str) -> Optional[float]:
        row = latest.get(name)
        return _finite(row.get("value")) if row else None

    ratio = number("margin_ratio")
    long_change = number("margin_long_1w_change")
    long_change_pct = number("margin_long_1w_change_pct")
    return_5d = number("return_5d_pct")
    relative = number("relative_strength_20d")
    volume_ratio = number("volume_ratio_20")
    state = None
    rule = None
    if (return_5d is not None and return_5d <= -5
            and volume_ratio is not None and volume_ratio >= 1.5
            and long_change is not None and long_change < 0):
        state, rule = "FORCED_LIQUIDATION", SUPPLY_STATE_POLICY["rules"][0]
    elif (long_change is not None and long_change < 0
          and return_5d is not None and return_5d >= -2):
        state, rule = "SUPPLY_CLEANUP", SUPPLY_STATE_POLICY["rules"][1]
    elif ((ratio is not None and ratio >= 3)
          or (long_change_pct is not None and long_change_pct >= 10)):
        state, rule = "CROWDED_LONG", SUPPLY_STATE_POLICY["rules"][2]
    elif (return_5d is not None and return_5d > 0
          and relative is not None and relative > 0
          and volume_ratio is not None and volume_ratio >= 1.2):
        state, rule = "REACCUMULATION", SUPPLY_STATE_POLICY["rules"][3]
    elif ratio is not None and ratio < 1:
        state, rule = "LIGHT_SUPPLY", SUPPLY_STATE_POLICY["rules"][4]
    elif ((return_5d is not None and return_5d > 0)
          or (relative is not None and relative > 0)):
        state, rule = "REPAIRING", SUPPLY_STATE_POLICY["rules"][5]
    drivers = sorted(name for name in (
        "margin_ratio", "margin_long_1w_change", "margin_long_1w_change_pct",
        "return_5d_pct", "relative_strength_20d", "volume_ratio_20",
    ) if name in latest)
    return {
        "state": state,
        "status": "AVAILABLE" if state else "MISSING",
        "matchedRule": rule,
        "driverEvidenceIds": drivers,
        "inferredDriverCount": 0,
        "policyId": SUPPLY_STATE_POLICY["policyId"],
        "policyHash": SUPPLY_STATE_POLICY_SHA256,
        "lineage": "ARGUS_CANDIDATE",
        "validationStatus": "UNVALIDATED",
        "probability": None,
    }


def _stage_status(provenance: Mapping[str, Any]) -> str:
    usable = sum(len(provenance.get(key, ())) for key in
                 ("observed", "derived", "inferred"))
    if usable:
        return "AVAILABLE"
    if provenance.get("unknown"):
        return "UNKNOWN"
    return "MISSING"


def build_stock_lens(*, cutoff: str, symbol: str,
                     market_state: Any,
                     sector_style_evidence: Iterable[Mapping[str, Any]] = (),
                     supply_evidence: Iterable[Mapping[str, Any]] = (),
                     technical_earnings_evidence: Iterable[Mapping[str, Any]] = (),
                     target_invalidation_evidence: Iterable[Mapping[str, Any]] = ()) \
        -> Dict[str, Any]:
    """Build the five-stage stock lens with provenance-preserving evidence."""
    if isinstance(market_state, Mapping):
        axis = market_state.get("reversalAxis")
        state = axis.get("state") if isinstance(axis, Mapping) else market_state.get("state")
    else:
        state = market_state
    state = str(state) if state in SHO_STATES else None
    sector = validate_evidence_provenance(sector_style_evidence, cutoff=cutoff)
    supply = validate_evidence_provenance(supply_evidence, cutoff=cutoff)
    technical = validate_evidence_provenance(
        technical_earnings_evidence, cutoff=cutoff)
    targets = validate_evidence_provenance(
        target_invalidation_evidence, cutoff=cutoff)
    supply_state = _classify_supply_state(supply)
    stages = [
        {"order": 1, "stage": "SHO_JP_MARKET_STATE",
         "status": "AVAILABLE" if state else "MISSING", "value": state},
        {"order": 2, "stage": "SECTOR_STYLE_STATE",
         "status": _stage_status(sector), "evidence": sector},
        {"order": 3, "stage": "STOCK_SUPPLY_DEMAND",
         "status": supply_state["status"], "state": supply_state,
         "evidence": supply},
        {"order": 4, "stage": "STOCK_TECHNICAL_EARNINGS",
         "status": _stage_status(technical), "evidence": technical},
        {"order": 5, "stage": "STOCK_TARGET_INVALIDATION",
         "status": _stage_status(targets), "evidence": targets},
    ]
    missing_stages = [row["stage"] for row in stages
                      if row["status"] != "AVAILABLE"]
    available_stage_count = len(stages) - len(missing_stages)
    body = {
        "schemaVersion": STOCK_LENS_SCHEMA,
        "canonicalRfcSha256": CANONICAL_SHO_RFC_SHA256,
        "informationCutoff": cutoff,
        "symbol": symbol,
        "hierarchy": [row["stage"] for row in stages],
        "stages": stages,
        "supplyState": supply_state,
        "supplyStatePolicy": copy.deepcopy(SUPPLY_STATE_POLICY),
        "supplyStatePolicyHash": SUPPLY_STATE_POLICY_SHA256,
        "status": ("AVAILABLE" if not missing_stages else
                   "PARTIAL" if available_stage_count else "MISSING"),
        "missingStages": missing_stages,
        "inferredForeignFlowPresentedAsObserved": False,
        "confidence": None,
        "validationStatus": "UNVALIDATED",
        "action": None,
        "automaticAiCalls": 0,
    }
    return {**body, "artifactId": "sho-stock-lens-" + _sha256(body)}


def _content_id_valid(artifact: Any, prefix: str) -> bool:
    if not isinstance(artifact, Mapping):
        return False
    body = copy.deepcopy(dict(artifact))
    actual = body.pop("artifactId", None)
    try:
        return actual == prefix + _sha256(body)
    except (TypeError, ValueError, OverflowError):
        return False


def project_today_sda_safe(*, cutoff: str,
                           evidence: Optional[Mapping[str, Any]] = None,
                           reversal: Optional[Mapping[str, Any]] = None,
                           target_ladder: Optional[Mapping[str, Any]] = None,
                           direct_index: Optional[Mapping[str, Any]] = None,
                           stock_lens: Optional[Mapping[str, Any]] = None) \
        -> Dict[str, Any]:
    """Project compact read-only evidence for Today/SDA consumers.

    The seam carries no executable authority, action, position sizing, order,
    environment access, implicit clock, or AI call.
    """
    _cutoff(cutoff)
    supplied = {
        "evidence": (evidence, "sho-evidence-"),
        "reversal": (reversal, "sho-reversal-"),
        "targetLadder": (target_ladder, "sho-targets-"),
        "directIndex": (direct_index, "sho-direct-index-"),
        "stockLens": (stock_lens, "sho-stock-lens-"),
    }
    admitted: Dict[str, Mapping[str, Any]] = {}
    rejected = []
    for name, (artifact, prefix) in supplied.items():
        if artifact is None:
            continue
        if not isinstance(artifact, Mapping) \
                or artifact.get("informationCutoff") != cutoff \
                or artifact.get("canonicalRfcSha256") != CANONICAL_SHO_RFC_SHA256 \
                or not _content_id_valid(artifact, prefix):
            rejected.append(name)
            continue
        admitted[name] = artifact
    family_projection = {}
    if "evidence" in admitted:
        for family, row in admitted["evidence"].get("families", {}).items():
            family_projection[family] = {
                "status": row.get("status"),
                "conditionMet": row.get("conditionMet"),
                "lineage": row.get("lineage"),
                "validationStatus": row.get("validationStatus"),
            }
    reversal_projection = None
    if "reversal" in admitted:
        reversal_projection = {
            "downsideState": admitted["reversal"].get("downsideAxis", {}).get("state"),
            "reversalState": admitted["reversal"].get("reversalAxis", {}).get("state"),
            "probability": None,
            "validationStatus": admitted["reversal"].get(
                "reversalAxis", {}).get("validationStatus"),
        }
    target_projection = []
    if "targetLadder" in admitted:
        target_projection = [{
            key: copy.deepcopy(zone.get(key)) for key in (
                "zoneId", "lower", "center", "upper", "horizonSessions",
                "theoryRefs", "hitProbability", "breakProbability",
                "validationStatus")
        } for zone in admitted["targetLadder"].get("zones", [])]
    identity_projection = None
    if "directIndex" in admitted:
        identity_projection = {
            "analysisInstrument": copy.deepcopy(
                admitted["directIndex"].get("analysisInstrument")),
            "tradableProxy": copy.deepcopy(
                admitted["directIndex"].get("tradableProxy")),
            "proxyUsedAsDirectIndex": False,
        }
    stock_projection = None
    if "stockLens" in admitted:
        stock_projection = {
            "symbol": admitted["stockLens"].get("symbol"),
            "supplyState": admitted["stockLens"].get("supplyState", {}).get("state"),
            "hierarchy": copy.deepcopy(admitted["stockLens"].get("hierarchy")),
            "status": admitted["stockLens"].get("status"),
        }
    body = {
        "schemaVersion": CONSUMER_PROJECTION_SCHEMA,
        "canonicalRfcSha256": CANONICAL_SHO_RFC_SHA256,
        "informationCutoff": cutoff,
        "consumerRoles": ["TODAY_READ_ONLY", "SDA_READ_ONLY"],
        "sourceArtifactIds": sorted(
            value["artifactId"] for value in admitted.values()),
        "rejectedArtifacts": sorted(rejected),
        "families": family_projection,
        # v13.5.38: the same seven families re-labeled for the owner as
        # MARKET SIGNALS SIG-01..07 with a computed count (pure, no authority).
        "marketSignals": argus_market_signals.project_market_signals(
            family_projection),
        "reversal": reversal_projection,
        "targetZones": target_projection,
        "indexIdentity": identity_projection,
        "stockLens": stock_projection,
        "status": "AVAILABLE" if admitted else "MISSING",
        "actionAuthority": False,
        "action": None,
        "automaticAiCalls": 0,
    }
    return {**body, "artifactId": "sho-consumer-projection-" + _sha256(body)}


__all__ = [
    "ANALYSIS_INSTRUMENTS",
    "CANONICAL_SHO_RFC_SHA256",
    "CREDIT_COVERAGE_END",
    "CREDIT_COVERAGE_START",
    "CREDIT_CSV_PATH",
    "CREDIT_CSV_SHA256",
    "CREDIT_POINTS_PER_SERIES",
    "DIRECT_INDEX_TO_PROXY",
    "SHO_REGISTRY_SHA256",
    "SHO_REGISTRY_VERSION",
    "SHO_STATES",
    "SUPPLY_STATES",
    "build_direct_index_model",
    "build_reversal_engine",
    "build_stock_lens",
    "build_target_zones",
    "classify_reversal_state",
    "coverage_artifact",
    "evaluate_d01",
    "evaluate_d02",
    "evaluate_d03",
    "evaluate_d04",
    "evaluate_d05",
    "evaluate_d06",
    "evaluate_d07",
    "evaluate_d01_d07",
    "normalize_complete_ohlcv",
    "point_in_time_rows",
    "project_today_sda_safe",
    "is_builder_issued_reversal_artifact",
    "registry_canonical_bytes",
    "repository_coverage_audit",
    "reversal_evidence",
    "sealed_proposition_registry",
    "validate_evidence_provenance",
    "validate_proposition_registry",
    "validate_reversal_artifact",
]
