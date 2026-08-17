# -*- coding: utf-8 -*-
"""Deterministic, offline research compute for ARGUS Round 2.

This module deliberately has no provider, backend, credential, environment, or
wall-clock dependency.  Callers must supply every identity and timestamp.  Raw
rows are point-in-time filtered, scored, and then discarded; returned artifacts
contain compact metrics and cryptographic receipts only.
"""
from __future__ import annotations

import copy
import csv
import hashlib
import json
import math
import statistics
from datetime import date, datetime, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from argus_risk_discipline import (
    RiskDisciplineValidationError,
    validate_risk_kernel,
)
from argus_sho import validate_reversal_artifact


MANIFEST_SCHEMA = "argus-round2-research-manifest-v1"
RESULT_SCHEMA = "argus-round2-research-result-v1"
COVERAGE_SCHEMA = "argus-round2-research-coverage-v1"
INPUT_RECEIPT_SCHEMA = "argus-round2-research-input-receipt-v1"
PIT_POLICY_ID = "known-at-revision-cutoff-v1"
PARTITION_POLICY_SCHEMA = "argus-round2-partitions-v1"
TURTLE_SCHEMA = "argus-turtle-shadow-v1"

BASE_HORIZONS = (1, 5, 10, 20)
OPTIONAL_HORIZON = 40
PARTITION_NAMES = ("DEVELOPMENT", "HOLDOUT", "GOLDEN", "EMBARGO")
COUNTERFACTUAL_STRATEGIES = (
    "BUY_NOW",
    "BUY_ON_SHO_REVERSAL",
    "BUY_ON_VIX_DC",
    "BUY_ON_SAR_FLIP",
    "BUY_ON_MACD_GC",
    "BUY_ON_25MA_RECLAIM",
    "BUY_ON_TURTLE_CONFIRMATION",
    "WAIT",
)
SIGNAL_FIELDS = {
    "BUY_ON_SHO_REVERSAL": "shoReversal",
    "BUY_ON_VIX_DC": "vixDecreasingConfirmation",
    "BUY_ON_SAR_FLIP": "sarFlip",
    "BUY_ON_MACD_GC": "macdGoldenCross",
    "BUY_ON_25MA_RECLAIM": "ma25Reclaim",
}
ALLOWED_SIGNAL_FIELDS = frozenset(SIGNAL_FIELDS.values())
MANIFEST_FIELDS = frozenset({
    "schemaVersion", "researchId", "datasetVersion", "datasets",
    "informationCutoffAt", "pitPolicyId", "propositionRegistryVersion",
    "policyVersion", "parameterVersion", "buildSha", "calendarVersion",
    "adjustmentPolicy", "executionPolicy", "costBps", "slippageBps",
    "seed", "horizons", "horizon40Preregistered",
    "horizon40PreregistrationId", "partitionPolicy", "goldenPolicy",
    "freeze", "retune", "parameters",
})

MAX_DATASETS = 32
MAX_BARS = 250000
MAX_EVENTS = 4096
MAX_EVENT_DETAILS = 128
MAX_TURTLE_SIGNAL_DETAILS = 256
MAX_ARTIFACT_BYTES = 2 * 1024 * 1024
MAX_DATASET_BYTES = 256 * 1024 * 1024
MAX_TOTAL_DATASET_BYTES = 512 * 1024 * 1024
_HEX64 = frozenset("0123456789abcdef")
_RAW_INPUT_AUTHORITY = object()


class ResearchContractError(ValueError):
    """A fail-closed research-contract violation."""


def canonical_bytes(value: Any) -> bytes:
    """Return the one canonical JSON encoding used for identities/artifacts."""
    try:
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, OverflowError) as exc:
        raise ResearchContractError("non_canonical_value") from exc


def sha256_hex(value: Any) -> str:
    raw = value if isinstance(value, bytes) else canonical_bytes(value)
    return hashlib.sha256(raw).hexdigest()


def _is_digest(value: Any, length: int = 64) -> bool:
    text = str(value or "")
    return len(text) == length and all(ch in _HEX64 for ch in text)


def _text(value: Any, label: str, maximum: int = 160) -> str:
    if not isinstance(value, str) or not value or value != value.strip() or \
            len(value) > maximum:
        raise ResearchContractError("invalid_" + label)
    return value


def _number(value: Any, label: str) -> float:
    if isinstance(value, bool):
        raise ResearchContractError("invalid_" + label)
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ResearchContractError("invalid_" + label) from exc
    if not math.isfinite(result):
        raise ResearchContractError("invalid_" + label)
    return result


def _round(value: Optional[float], digits: int = 6) -> Optional[float]:
    return None if value is None else round(float(value), digits)


def _timestamp(value: Any, label: str) -> datetime:
    text = _text(value, label, 64)
    if len(text) == 10:
        raise ResearchContractError(label + "_timezone_required")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except (TypeError, ValueError, OverflowError) as exc:
        raise ResearchContractError("invalid_" + label) from exc
    if parsed.tzinfo is None:
        raise ResearchContractError(label + "_timezone_required")
    return parsed.astimezone(timezone.utc)


def _date(value: Any, label: str) -> date:
    text = _text(value, label, 10)
    try:
        parsed = date.fromisoformat(text)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ResearchContractError("invalid_" + label) from exc
    if parsed.isoformat() != text:
        raise ResearchContractError("invalid_" + label)
    return parsed


def _copy_json(value: Any) -> Any:
    return json.loads(canonical_bytes(value).decode("utf-8"))


def _bounded_collect(rows: Iterable[Any], maximum: int, label: str) -> List[Any]:
    """Materialize at most ``maximum`` rows; abort before an unbounded source."""
    if isinstance(rows, list):
        if len(rows) > maximum:
            raise ResearchContractError(label + "_bound_exceeded")
        return rows
    result = []
    for row in rows:
        if len(result) >= maximum:
            raise ResearchContractError(label + "_bound_exceeded")
        result.append(row)
    return result


def _validate_datasets(value: Any) -> List[Dict[str, Any]]:
    if not isinstance(value, list) or not value or len(value) > MAX_DATASETS:
        raise ResearchContractError("invalid_datasets")
    rows: List[Dict[str, Any]] = []
    seen = set()
    seen_paths = set()
    required = {
        "datasetId", "kind", "path", "sha256", "sourceKind",
        "rightsStatus", "partitionScope",
    }
    for raw in value:
        if not isinstance(raw, dict) or set(raw) != required:
            raise ResearchContractError("invalid_dataset_descriptor")
        dataset_id = _text(raw.get("datasetId"), "dataset_id", 120)
        if dataset_id in seen:
            raise ResearchContractError("duplicate_dataset_id")
        seen.add(dataset_id)
        kind = raw.get("kind")
        if kind not in ("bars", "events"):
            raise ResearchContractError("invalid_dataset_kind")
        path = _text(raw.get("path"), "dataset_path", 240)
        if path.startswith("/") or ".." in path.split("/") or \
                path.startswith("~"):
            raise ResearchContractError("unsafe_dataset_path")
        if path in seen_paths:
            raise ResearchContractError("duplicate_dataset_path")
        seen_paths.add(path)
        digest = str(raw.get("sha256") or "")
        if not _is_digest(digest):
            raise ResearchContractError("invalid_dataset_sha256")
        source_kind = _text(raw.get("sourceKind"), "source_kind", 80)
        rights = raw.get("rightsStatus")
        if rights not in ("PUBLIC", "LICENSED_PRIVATE", "OWNER_SUPPLIED",
                          "TEST_ONLY"):
            raise ResearchContractError("invalid_rights_status")
        partition_scope = raw.get("partitionScope")
        if partition_scope not in ("NON_GOLDEN", "GOLDEN"):
            raise ResearchContractError("invalid_dataset_partition_scope")
        rows.append({
            "datasetId": dataset_id,
            "kind": kind,
            "partitionScope": partition_scope,
            "path": path,
            "rightsStatus": rights,
            "sha256": digest,
            "sourceKind": source_kind,
        })
    rows.sort(key=lambda row: (
        row["partitionScope"], row["kind"], row["datasetId"], row["path"]))
    return rows


def _validate_ranges(value: Any) -> List[Dict[str, str]]:
    if not isinstance(value, list) or len(value) < 4 or len(value) > 16:
        raise ResearchContractError("invalid_partition_ranges")
    rows: List[Tuple[date, date, str]] = []
    counts = {name: 0 for name in PARTITION_NAMES}
    for raw in value:
        if not isinstance(raw, dict) or set(raw) != {
                "name", "startDate", "endDate"}:
            raise ResearchContractError("invalid_partition_range")
        name = raw.get("name")
        if name not in PARTITION_NAMES:
            raise ResearchContractError("invalid_partition_name")
        start = _date(raw.get("startDate"), "partition_start")
        end = _date(raw.get("endDate"), "partition_end")
        if end < start:
            raise ResearchContractError("inverted_partition_range")
        counts[name] += 1
        rows.append((start, end, name))
    rows.sort(key=lambda row: (row[0], row[1], row[2]))
    for previous, current in zip(rows, rows[1:]):
        if current[0] <= previous[1]:
            raise ResearchContractError("overlapping_partition_ranges")
    if counts["DEVELOPMENT"] != 1 or counts["HOLDOUT"] != 1 or \
            counts["GOLDEN"] != 1 or counts["EMBARGO"] < 1:
        raise ResearchContractError("incomplete_partition_policy")
    if [row[2] for row in rows] != [
            "DEVELOPMENT", "EMBARGO", "HOLDOUT", "EMBARGO", "GOLDEN"]:
        raise ResearchContractError("invalid_partition_sequence")
    golden = next(row for row in rows if row[2] == "GOLDEN")
    if golden[0] < date(2026, 7, 20) or golden[1] > date(2026, 8, 31):
        raise ResearchContractError("golden_window_not_late_july_august_2026")
    return [{"name": name, "startDate": start.isoformat(),
             "endDate": end.isoformat()} for start, end, name in rows]


def _validate_walk_forward(value: Any, development: Dict[str, str]) \
        -> List[Dict[str, str]]:
    if not isinstance(value, list) or not value or len(value) > 32:
        raise ResearchContractError("invalid_walk_forward_folds")
    dev_start = _date(development["startDate"], "development_start")
    dev_end = _date(development["endDate"], "development_end")
    result = []
    seen = set()
    fields = (
        "trainStartDate", "trainEndDate", "validationStartDate",
        "validationEndDate", "forwardStartDate", "forwardEndDate",
    )
    for raw in value:
        if not isinstance(raw, dict) or set(raw) != set(fields) | {"foldId"}:
            raise ResearchContractError("invalid_walk_forward_fold")
        fold_id = _text(raw.get("foldId"), "fold_id", 80)
        if fold_id in seen:
            raise ResearchContractError("duplicate_fold_id")
        seen.add(fold_id)
        dates = [_date(raw.get(field), field) for field in fields]
        if not (dates[0] <= dates[1] < dates[2] <= dates[3] < dates[4]
                <= dates[5]):
            raise ResearchContractError("non_chronological_walk_forward_fold")
        if dates[0] < dev_start or dates[-1] > dev_end:
            raise ResearchContractError("walk_forward_outside_development")
        row = {"foldId": fold_id}
        row.update({field: parsed.isoformat()
                    for field, parsed in zip(fields, dates)})
        result.append(row)
    result.sort(key=lambda row: (row["forwardEndDate"], row["foldId"]))
    return result


def _validate_partition_policy(value: Any, horizons: Sequence[int]) \
        -> Dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {
            "schemaVersion", "policyId", "embargoSessions", "ranges",
            "walkForwardFolds"}:
        raise ResearchContractError("invalid_partition_policy")
    if value.get("schemaVersion") != PARTITION_POLICY_SCHEMA:
        raise ResearchContractError("invalid_partition_policy_schema")
    policy_id = _text(value.get("policyId"), "partition_policy_id", 120)
    embargo = value.get("embargoSessions")
    if isinstance(embargo, bool) or not isinstance(embargo, int) or \
            embargo < max(horizons) or embargo > 260:
        raise ResearchContractError("insufficient_embargo_sessions")
    ranges = _validate_ranges(value.get("ranges"))
    for row in ranges:
        if row["name"] != "EMBARGO":
            continue
        calendar_days = (
            _date(row["endDate"], "embargo_end")
            - _date(row["startDate"], "embargo_start")).days + 1
        if calendar_days < embargo:
            raise ResearchContractError(
                "insufficient_embargo_calendar_span")
    development = next(row for row in ranges
                       if row["name"] == "DEVELOPMENT")
    folds = _validate_walk_forward(value.get("walkForwardFolds"), development)
    return {
        "schemaVersion": PARTITION_POLICY_SCHEMA,
        "policyId": policy_id,
        "embargoSessions": embargo,
        "ranges": ranges,
        "walkForwardFolds": folds,
    }


def _validate_parameters(value: Any, horizons: Sequence[int]) -> Dict[str, Any]:
    fields = {
        "targetPct", "invalidationPct", "newLowLookback",
        "rallyThresholdPct", "reversalThresholdPct",
        "waitFailureThresholdPct", "counterfactualHorizon", "turtle",
    }
    if not isinstance(value, dict) or set(value) != fields:
        raise ResearchContractError("invalid_parameters")
    target = _number(value.get("targetPct"), "target_pct")
    invalidation = _number(value.get("invalidationPct"), "invalidation_pct")
    rally = _number(value.get("rallyThresholdPct"), "rally_threshold")
    reversal = _number(value.get("reversalThresholdPct"), "reversal_threshold")
    wait_failure = _number(value.get("waitFailureThresholdPct"),
                           "wait_failure_threshold")
    if target <= 0 or invalidation >= 0 or rally <= 0 or reversal <= 0 or \
            wait_failure <= 0:
        raise ResearchContractError("invalid_research_thresholds")
    lookback = value.get("newLowLookback")
    cf_horizon = value.get("counterfactualHorizon")
    if isinstance(lookback, bool) or not isinstance(lookback, int) or \
            not 2 <= lookback <= 260:
        raise ResearchContractError("invalid_new_low_lookback")
    if cf_horizon not in horizons or cf_horizon not in BASE_HORIZONS:
        raise ResearchContractError("invalid_counterfactual_horizon")
    turtle = value.get("turtle")
    expected_turtle = {
        "entryLookbacks": [20, 55], "exitLookbacks": [10, 20],
        "atrPeriod": 20, "entryRule": "20_or_55_day_high_break",
        "exitRule": "10_or_20_day_low_break", "shadowOnly": True,
        "hardVeto": False,
    }
    if turtle != expected_turtle:
        raise ResearchContractError("invalid_turtle_parameters")
    return {
        "counterfactualHorizon": cf_horizon,
        "invalidationPct": _round(invalidation),
        "newLowLookback": lookback,
        "rallyThresholdPct": _round(rally),
        "reversalThresholdPct": _round(reversal),
        "targetPct": _round(target),
        "turtle": _copy_json(expected_turtle),
        "waitFailureThresholdPct": _round(wait_failure),
    }


def _horizons(manifest: Mapping[str, Any]) -> Tuple[int, ...]:
    raw = manifest.get("horizons")
    if not isinstance(raw, list) or any(
            isinstance(item, bool) or not isinstance(item, int) for item in raw):
        raise ResearchContractError("invalid_horizons")
    values = tuple(raw)
    if values not in (BASE_HORIZONS, BASE_HORIZONS + (OPTIONAL_HORIZON,)):
        raise ResearchContractError("invalid_horizons")
    preregistered = manifest.get("horizon40Preregistered")
    prereg_id = manifest.get("horizon40PreregistrationId")
    if OPTIONAL_HORIZON in values:
        if preregistered is not True:
            raise ResearchContractError("horizon_40_not_preregistered")
        _text(prereg_id, "horizon_40_preregistration_id", 160)
    elif preregistered is not False or prereg_id is not None:
        raise ResearchContractError("unexpected_horizon_40_preregistration")
    return values


def _manifest_core(manifest: Mapping[str, Any]) -> Dict[str, Any]:
    """Validate and normalize every non-lifecycle manifest field."""
    if not isinstance(manifest, Mapping) or set(manifest) != MANIFEST_FIELDS:
        raise ResearchContractError("invalid_manifest_fields")
    if manifest.get("schemaVersion") != MANIFEST_SCHEMA:
        raise ResearchContractError("invalid_manifest_schema")
    horizons = _horizons(manifest)
    build_sha = str(manifest.get("buildSha") or "")
    if not _is_digest(build_sha, length=40):
        raise ResearchContractError("build_sha_must_be_exact")
    cutoff = _timestamp(manifest.get("informationCutoffAt"),
                        "information_cutoff")
    if manifest.get("pitPolicyId") != PIT_POLICY_ID:
        raise ResearchContractError("unsupported_pit_policy")
    execution = manifest.get("executionPolicy")
    if execution != "next_session_open":
        raise ResearchContractError(
            "execution_policy_requires_next_session_open")
    cost = _number(manifest.get("costBps"), "cost_bps")
    slippage = _number(manifest.get("slippageBps"), "slippage_bps")
    if not 0 <= cost <= 1000 or not 0 <= slippage <= 1000:
        raise ResearchContractError("invalid_cost_or_slippage")
    seed = manifest.get("seed")
    if isinstance(seed, bool) or not isinstance(seed, int) or \
            not 0 <= seed <= 2 ** 31 - 1:
        raise ResearchContractError("invalid_seed")
    core = {
        "adjustmentPolicy": _text(manifest.get("adjustmentPolicy"),
                                  "adjustment_policy", 120),
        "buildSha": build_sha,
        "calendarVersion": _text(manifest.get("calendarVersion"),
                                 "calendar_version", 120),
        "costBps": _round(cost),
        "datasetVersion": _text(manifest.get("datasetVersion"),
                                "dataset_version", 120),
        "datasets": _validate_datasets(manifest.get("datasets")),
        "executionPolicy": execution,
        "horizon40Preregistered": bool(
            manifest.get("horizon40Preregistered")),
        "horizon40PreregistrationId": (
            manifest.get("horizon40PreregistrationId")),
        "horizons": list(horizons),
        "informationCutoffAt": cutoff.isoformat().replace("+00:00", "Z"),
        "parameterVersion": _text(manifest.get("parameterVersion"),
                                  "parameter_version", 120),
        "parameters": _validate_parameters(manifest.get("parameters"),
                                           horizons),
        "partitionPolicy": _validate_partition_policy(
            manifest.get("partitionPolicy"), horizons),
        "pitPolicyId": PIT_POLICY_ID,
        "policyVersion": _text(manifest.get("policyVersion"),
                               "policy_version", 120),
        "propositionRegistryVersion": _text(
            manifest.get("propositionRegistryVersion"),
            "proposition_registry_version", 120),
        "researchId": _text(manifest.get("researchId"), "research_id", 120),
        "schemaVersion": MANIFEST_SCHEMA,
        "seed": seed,
        "slippageBps": _round(slippage),
    }
    return core


def policy_identity(manifest: Mapping[str, Any]) -> str:
    core = _manifest_core(manifest)
    golden = manifest.get("goldenPolicy")
    if not isinstance(golden, Mapping):
        raise ResearchContractError("invalid_golden_policy")
    golden_case = {
        "caseId": _text(golden.get("caseId"), "golden_case_id", 160),
        "expectedEventId": _text(
            golden.get("expectedEventId"), "golden_expected_event_id", 120),
        "expectedInstrumentId": _text(
            golden.get("expectedInstrumentId"),
            "golden_expected_instrument_id", 120).upper(),
    }
    material = {key: core[key] for key in (
        "adjustmentPolicy", "buildSha", "calendarVersion", "costBps",
        "executionPolicy", "horizon40Preregistered",
        "horizon40PreregistrationId", "horizons", "parameterVersion",
        "parameters", "partitionPolicy", "pitPolicyId", "policyVersion",
        "propositionRegistryVersion", "seed", "slippageBps",
    )}
    material["goldenCase"] = golden_case
    return "rp-" + sha256_hex(material)


def research_data_identity(manifest: Mapping[str, Any]) -> str:
    core = _manifest_core(manifest)
    return "rd-" + sha256_hex({
        "datasetVersion": core["datasetVersion"],
        "datasets": core["datasets"],
        "informationCutoffAt": core["informationCutoffAt"],
        "policyIdentity": policy_identity(manifest),
        "researchId": core["researchId"],
    })


def research_identity(manifest: Mapping[str, Any]) -> str:
    core = _manifest_core(manifest)
    policy_id = policy_identity(manifest)
    data_id = research_data_identity(manifest)
    lifecycle = _validate_lifecycle(manifest, policy_id, data_id)
    return "rr-" + sha256_hex({
        "lifecycle": lifecycle,
        "policyIdentity": policy_id,
        "researchDataIdentity": data_id,
        "researchId": core["researchId"],
    })


def _validate_lifecycle(manifest: Mapping[str, Any], policy_id: str,
                        research_data_id: str) \
        -> Dict[str, Any]:
    freeze = manifest.get("freeze")
    if not isinstance(freeze, dict) or set(freeze) != {
            "status", "policyIdentity", "frozenAt", "holdoutStatus",
            "holdoutResultDigest", "holdoutRecordedAt",
            "researchDataIdentity"}:
        raise ResearchContractError("invalid_freeze_contract")
    status = freeze.get("status")
    if status not in ("DRAFT", "FROZEN"):
        raise ResearchContractError("invalid_freeze_status")
    holdout_status = freeze.get("holdoutStatus")
    if holdout_status not in ("UNTOUCHED", "PASSED", "FAILED"):
        raise ResearchContractError("invalid_holdout_status")
    frozen_at = None
    holdout_recorded_at = None
    if status == "DRAFT":
        if any(freeze.get(key) is not None for key in (
                "policyIdentity", "frozenAt", "holdoutResultDigest",
                "holdoutRecordedAt", "researchDataIdentity")) or \
                holdout_status != "UNTOUCHED":
            raise ResearchContractError("invalid_draft_freeze_contract")
    else:
        if freeze.get("policyIdentity") != policy_id:
            raise ResearchContractError("frozen_policy_identity_mismatch")
        if freeze.get("researchDataIdentity") != research_data_id:
            raise ResearchContractError("frozen_data_identity_mismatch")
        frozen_at = _timestamp(freeze.get("frozenAt"), "frozen_at")
        if holdout_status == "UNTOUCHED":
            if freeze.get("holdoutResultDigest") is not None or \
                    freeze.get("holdoutRecordedAt") is not None:
                raise ResearchContractError("untouched_holdout_has_result")
        else:
            if not _is_digest(freeze.get("holdoutResultDigest")):
                raise ResearchContractError("invalid_holdout_result_digest")
            holdout_recorded_at = _timestamp(
                freeze.get("holdoutRecordedAt"), "holdout_recorded_at")
            if holdout_recorded_at < frozen_at:
                raise ResearchContractError(
                    "holdout_recorded_before_policy_freeze")
    lifecycle_ranges = _validate_ranges(
        manifest["partitionPolicy"]["ranges"])
    embargo_ranges = [row for row in lifecycle_ranges
                      if row["name"] == "EMBARGO"]
    golden_range = next(row for row in lifecycle_ranges
                        if row["name"] == "GOLDEN")
    first_embargo_start = _timestamp(
        embargo_ranges[0]["startDate"] + "T00:00:00Z",
        "first_embargo_start")
    if frozen_at is not None and frozen_at > first_embargo_start:
        raise ResearchContractError("policy_frozen_after_holdout_isolation")
    last_embargo_end = _date(
        embargo_ranges[-1]["endDate"], "last_embargo_end")
    if holdout_recorded_at is not None and \
            holdout_recorded_at.date() <= last_embargo_end:
        raise ResearchContractError("holdout_recorded_before_embargo_end")

    golden = manifest.get("goldenPolicy")
    if not isinstance(golden, dict) or set(golden) != {
            "caseId", "expectedEventId", "expectedInstrumentId", "access",
            "openedAt", "openedForPolicyIdentity",
            "openedForResearchDataIdentity"}:
        raise ResearchContractError("invalid_golden_policy")
    case_id = _text(golden.get("caseId"), "golden_case_id", 160)
    expected_event_id = _text(
        golden.get("expectedEventId"), "golden_expected_event_id", 120)
    expected_instrument_id = _text(
        golden.get("expectedInstrumentId"),
        "golden_expected_instrument_id", 120).upper()
    access = golden.get("access")
    if access not in ("SEALED", "OPEN"):
        raise ResearchContractError("invalid_golden_access")
    if access == "SEALED":
        if golden.get("openedAt") is not None or \
                golden.get("openedForPolicyIdentity") is not None or \
                golden.get("openedForResearchDataIdentity") is not None:
            raise ResearchContractError("sealed_golden_has_open_metadata")
    else:
        if status != "FROZEN" or holdout_status != "PASSED":
            raise ResearchContractError("golden_requires_passed_frozen_holdout")
        golden_commitment_kinds = {
            row["kind"] for row in _validate_datasets(manifest["datasets"])
            if row["partitionScope"] == "GOLDEN"
        }
        if golden_commitment_kinds != {"bars", "events"}:
            raise ResearchContractError("golden_dataset_commitments_missing")
        if golden.get("openedForPolicyIdentity") != policy_id:
            raise ResearchContractError("golden_policy_identity_mismatch")
        if golden.get("openedForResearchDataIdentity") != research_data_id:
            raise ResearchContractError("golden_data_identity_mismatch")
        opened_at = _timestamp(golden.get("openedAt"), "golden_opened_at")
        if holdout_recorded_at is None or opened_at <= holdout_recorded_at:
            raise ResearchContractError("golden_opened_before_holdout_result")
        if opened_at.date() < _date(
                golden_range["startDate"], "golden_start"):
            raise ResearchContractError("golden_opened_before_reserved_window")

    retune = manifest.get("retune")
    if not isinstance(retune, dict) or set(retune) != {
            "priorPolicyIdentity", "reason"}:
        raise ResearchContractError("invalid_retune_contract")
    prior = retune.get("priorPolicyIdentity")
    reason = retune.get("reason")
    if (prior is None) != (reason is None):
        raise ResearchContractError("incomplete_retune_contract")
    if prior is not None:
        if not isinstance(prior, str) or not prior.startswith("rp-") or \
                not _is_digest(prior[3:]):
            raise ResearchContractError("invalid_prior_policy_identity")
        _text(reason, "retune_reason", 240)
        if prior == policy_id:
            raise ResearchContractError("retune_requires_new_policy_identity")
        if access != "SEALED":
            raise ResearchContractError("retune_must_reseal_golden")
    return {
        "freeze": _copy_json(freeze),
        "goldenPolicy": {
            "access": access,
            "caseId": case_id,
            "expectedEventId": expected_event_id,
            "expectedInstrumentId": expected_instrument_id,
            "openedAt": golden.get("openedAt"),
            "openedForPolicyIdentity": golden.get(
                "openedForPolicyIdentity"),
            "openedForResearchDataIdentity": golden.get(
                "openedForResearchDataIdentity"),
        },
        "retune": _copy_json(retune),
    }


def validate_manifest(manifest: Mapping[str, Any]) -> Dict[str, Any]:
    core = _manifest_core(manifest)
    policy_id = policy_identity(manifest)
    data_id = research_data_identity(manifest)
    lifecycle = _validate_lifecycle(manifest, policy_id, data_id)
    result = dict(core)
    result.update(lifecycle)
    result["policyIdentity"] = policy_id
    result["researchDataIdentity"] = data_id
    result["researchIdentity"] = research_identity(manifest)
    return result


def _manifest_document(contract: Mapping[str, Any]) -> Dict[str, Any]:
    """Project the exact normalized manifest bound into every artifact."""
    return {key: _copy_json(contract[key]) for key in sorted(MANIFEST_FIELDS)}


def freeze_manifest(manifest: Mapping[str, Any], *, frozen_at: str) \
        -> Dict[str, Any]:
    normalized = validate_manifest(manifest)
    if normalized["freeze"]["status"] != "DRAFT":
        raise ResearchContractError("manifest_already_frozen")
    _timestamp(frozen_at, "frozen_at")
    result = _copy_json(manifest)
    result["freeze"] = {
        "status": "FROZEN",
        "policyIdentity": normalized["policyIdentity"],
        "frozenAt": frozen_at,
        "holdoutStatus": "UNTOUCHED",
        "holdoutResultDigest": None,
        "holdoutRecordedAt": None,
        "researchDataIdentity": normalized["researchDataIdentity"],
    }
    validate_manifest(result)
    return result


def record_holdout_result(manifest: Mapping[str, Any], *, status: str,
                          dataset_payloads: Mapping[str, bytes],
                          recorded_at: str) -> Dict[str, Any]:
    normalized = validate_manifest(manifest)
    if normalized["freeze"]["status"] != "FROZEN" or \
            normalized["freeze"]["holdoutStatus"] != "UNTOUCHED":
        raise ResearchContractError("holdout_result_is_immutable")
    if status not in ("PASSED", "FAILED"):
        raise ResearchContractError("invalid_holdout_result_status")
    result_artifact = build_verified_research_artifact(
        manifest, dataset_payloads)
    if result_artifact["identity"]["researchIdentity"] != \
            normalized["researchIdentity"] or \
            result_artifact["goldenCase"]["access"] != "SEALED":
        raise ResearchContractError("holdout_result_identity_mismatch")
    holdout_proof = result_artifact["holdoutProof"]
    if status == "PASSED" and holdout_proof["eligibleForPass"] is not True:
        raise ResearchContractError("holdout_not_eligible_for_pass")
    recorded = _timestamp(recorded_at, "holdout_recorded_at")
    latest_input = _timestamp(
        holdout_proof["latestInputKnownAt"], "holdout_latest_input")
    if recorded < latest_input:
        raise ResearchContractError("holdout_recorded_before_latest_input")
    result_digest = holdout_proof["resultDigest"]
    result = _copy_json(manifest)
    result["freeze"].update({
        "holdoutStatus": status,
        "holdoutResultDigest": result_digest,
        "holdoutRecordedAt": recorded_at,
    })
    validate_manifest(result)
    return result


def open_golden(manifest: Mapping[str, Any], *, opened_at: str) \
        -> Dict[str, Any]:
    normalized = validate_manifest(manifest)
    if normalized["goldenPolicy"]["access"] != "SEALED":
        raise ResearchContractError("golden_already_open")
    if normalized["freeze"]["status"] != "FROZEN" or \
            normalized["freeze"]["holdoutStatus"] != "PASSED":
        raise ResearchContractError("golden_requires_passed_frozen_holdout")
    _timestamp(opened_at, "golden_opened_at")
    result = _copy_json(manifest)
    result["goldenPolicy"].update({
        "access": "OPEN",
        "openedAt": opened_at,
        "openedForPolicyIdentity": normalized["policyIdentity"],
        "openedForResearchDataIdentity": normalized[
            "researchDataIdentity"],
    })
    validate_manifest(result)
    return result


def validate_retune(previous: Mapping[str, Any], current: Mapping[str, Any]) \
        -> Dict[str, Any]:
    before = validate_manifest(previous)
    after = validate_manifest(current)
    changed = before["policyIdentity"] != after["policyIdentity"]
    if before["freeze"]["holdoutStatus"] == "FAILED" and not changed:
        raise ResearchContractError("failed_holdout_requires_new_policy_identity")
    if not changed:
        before_freeze = before["freeze"]
        after_freeze = after["freeze"]
        if before_freeze["status"] == "FROZEN" and \
                after_freeze["status"] != "FROZEN":
            raise ResearchContractError("research_lifecycle_rollback")
        before_holdout = before_freeze["holdoutStatus"]
        after_holdout = after_freeze["holdoutStatus"]
        allowed_holdout = {
            "UNTOUCHED": {"UNTOUCHED", "PASSED", "FAILED"},
            "PASSED": {"PASSED"},
            "FAILED": {"FAILED"},
        }
        if after_holdout not in allowed_holdout[before_holdout]:
            raise ResearchContractError("research_lifecycle_rollback")
        if before["goldenPolicy"]["access"] == "OPEN" and \
                after["goldenPolicy"]["access"] != "OPEN":
            raise ResearchContractError("research_lifecycle_rollback")
        if before["goldenPolicy"]["access"] == "OPEN" and \
                before["researchIdentity"] != after["researchIdentity"]:
            raise ResearchContractError("opened_golden_is_immutable")
    if changed:
        if after["retune"]["priorPolicyIdentity"] != before["policyIdentity"]:
            raise ResearchContractError("material_change_requires_retune_lineage")
        if after["goldenPolicy"]["access"] != "SEALED":
            raise ResearchContractError("material_change_must_reseal_golden")
    elif after["retune"]["priorPolicyIdentity"] is not None:
        raise ResearchContractError("spurious_retune_lineage")
    return {
        "changed": changed,
        "currentPolicyIdentity": after["policyIdentity"],
        "previousPolicyIdentity": before["policyIdentity"],
        "valid": True,
    }


def partition_for_date(value: Any, policy: Mapping[str, Any]) -> Optional[str]:
    day = _date(value, "partition_date")
    matches = [row["name"] for row in policy.get("ranges", [])
               if _date(row["startDate"], "partition_start") <= day <=
               _date(row["endDate"], "partition_end")]
    if len(matches) > 1:
        raise ResearchContractError("overlapping_partition_ranges")
    return matches[0] if matches else None


def _normalize_signals(value: Any) -> Dict[str, bool]:
    if value in (None, {}):
        return {}
    if not isinstance(value, dict) or not set(value).issubset(
            ALLOWED_SIGNAL_FIELDS):
        raise ResearchContractError("invalid_bar_signals")
    if any(not isinstance(flag, bool) for flag in value.values()):
        raise ResearchContractError("invalid_bar_signals")
    return {key: value[key] for key in sorted(value) if value[key]}


def _normalize_bar(raw: Mapping[str, Any]) -> Dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise ResearchContractError("invalid_bar")
    required = {
        "datasetId", "instrumentId", "date", "availableFrom",
        "decisionCutoffAt", "revision", "open", "high", "low", "close",
    }
    allowed = required | {"knownAt", "sourceId", "volume", "signals"}
    if not required.issubset(raw) or not set(raw).issubset(allowed):
        raise ResearchContractError("invalid_bar_fields")
    dataset_id = _text(raw.get("datasetId"), "bar_dataset_id", 120)
    instrument = _text(raw.get("instrumentId"), "instrument_id", 120).upper()
    day = _date(raw.get("date"), "bar_date").isoformat()
    available = _timestamp(raw.get("availableFrom"), "available_from")
    decision_cutoff = _timestamp(
        raw.get("decisionCutoffAt"), "bar_decision_cutoff")
    if decision_cutoff.date().isoformat() != day:
        raise ResearchContractError("bar_decision_cutoff_outside_session")
    known = available
    if raw.get("knownAt") not in (None, ""):
        known = max(known, _timestamp(raw.get("knownAt"), "known_at"))
    revision = raw.get("revision")
    if isinstance(revision, bool) or not isinstance(revision, int) or \
            revision < 0:
        raise ResearchContractError("invalid_bar_revision")
    if revision > 0 and raw.get("knownAt") in (None, ""):
        raise ResearchContractError("revision_known_at_required")
    op = _number(raw.get("open"), "bar_open")
    high = _number(raw.get("high"), "bar_high")
    low = _number(raw.get("low"), "bar_low")
    close = _number(raw.get("close"), "bar_close")
    if min(op, high, low, close) <= 0 or high < max(op, low, close) or \
            low > min(op, high, close):
        raise ResearchContractError("incomplete_or_invalid_ohlc")
    volume = None
    if raw.get("volume") not in (None, ""):
        volume = _number(raw.get("volume"), "bar_volume")
        if volume < 0:
            raise ResearchContractError("invalid_bar_volume")
    return {
        "availableFrom": available.isoformat().replace("+00:00", "Z"),
        "close": _round(close),
        "datasetId": dataset_id,
        "date": day,
        "decisionCutoffAt": decision_cutoff.isoformat().replace(
            "+00:00", "Z"),
        "effectiveKnownAt": known.isoformat().replace("+00:00", "Z"),
        "high": _round(high),
        "instrumentId": instrument,
        "low": _round(low),
        "open": _round(op),
        "revision": revision,
        "signals": _normalize_signals(raw.get("signals")),
        "sourceId": (None if raw.get("sourceId") in (None, "") else
                     _text(raw.get("sourceId"), "bar_source_id", 200)),
        "volume": _round(volume),
    }


def normalize_point_in_time_bars(rows: Iterable[Mapping[str, Any]], *,
                                 cutoff_at: str) \
        -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    cutoff = _timestamp(cutoff_at, "information_cutoff")
    source = _bounded_collect(rows, MAX_BARS, "bar")
    selected: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
    session_cutoffs: Dict[Tuple[str, str, str], str] = {}
    future = 0
    late_revision = 0
    superseded = 0
    duplicates = 0
    for raw in source:
        if not isinstance(raw, Mapping):
            raise ResearchContractError("invalid_bar")
        row = _normalize_bar(raw)
        key = (row["datasetId"], row["instrumentId"], row["date"])
        previous_cutoff = session_cutoffs.get(key)
        if previous_cutoff is None:
            session_cutoffs[key] = row["decisionCutoffAt"]
        elif previous_cutoff != row["decisionCutoffAt"]:
            raise ResearchContractError("bar_decision_cutoff_changed")
        known = _timestamp(row["effectiveKnownAt"], "effective_known_at")
        decision_cutoff = _timestamp(
            row["decisionCutoffAt"], "bar_decision_cutoff")
        if known > cutoff or decision_cutoff > cutoff:
            future += 1
            continue
        if known > decision_cutoff:
            late_revision += 1
            continue
        previous = selected.get(key)
        if previous is None:
            selected[key] = row
        elif row["revision"] > previous["revision"]:
            selected[key] = row
            superseded += 1
        elif row["revision"] < previous["revision"]:
            superseded += 1
        elif row == previous:
            duplicates += 1
        else:
            raise ResearchContractError("conflicting_same_revision_bar")
    result = sorted(selected.values(), key=lambda row: (
        row["instrumentId"], row["date"], row["datasetId"]))
    session_keys = set()
    for row in result:
        session_key = (row["instrumentId"], row["date"])
        if session_key in session_keys:
            raise ResearchContractError("overlapping_bar_sources")
        session_keys.add(session_key)
    proof = {
        "admittedRowCount": len(result),
        "datasetHash": sha256_hex(result),
        "duplicateRowCount": duplicates,
        "excludedAfterDecisionCutoffCount": late_revision,
        "futureRowsAdmitted": False,
        "pitPolicyId": PIT_POLICY_ID,
        "revisionSelection": (
            "highest_revision_visible_at_session_decision_cutoff_per_"
            "dataset_instrument_date"),
        "sourceRowCount": len(source),
        "supersededRevisionCount": superseded,
        "excludedFutureCount": future,
        "verified": True,
    }
    return result, proof


def _golden_risk_kernel(value: Any, *, instrument: str,
                        event_cutoff: datetime) -> Optional[Dict[str, Any]]:
    if value is None:
        return None
    keys = {
        "asOf", "confidenceCapBps", "conflictReasonCodes", "constraint",
        "finalActionAuthority", "informationCutoffAt", "missingReasonCodes",
        "policy", "primitiveFactors", "privacyClass", "riskKernelId",
        "schemaVersion", "status", "subject",
    }
    if not isinstance(value, Mapping) or set(value) != keys:
        raise ResearchContractError("invalid_golden_risk_kernel")
    artifact = _copy_json(value)
    try:
        validate_risk_kernel(artifact)
    except RiskDisciplineValidationError as exc:
        raise ResearchContractError("invalid_golden_risk_kernel") from exc
    body = {key: artifact[key] for key in artifact if key != "riskKernelId"}
    if artifact.get("riskKernelId") != "rk-" + sha256_hex(body) or \
            artifact.get("schemaVersion") != "argus-risk-kernel-v1" or \
            artifact.get("privacyClass") != "DEVICE_LOCAL_DERIVED" or \
            artifact.get("finalActionAuthority") is not False or \
            artifact.get("status") != "READY" or \
            artifact.get("constraint") not in {
                "NONE", "BLOCK_BUY", "WAIT_REQUIRED",
                "REDUCE_RISK", "EXIT_RISK"}:
        raise ResearchContractError("invalid_golden_risk_kernel")
    subject = artifact.get("subject")
    instrument_market = instrument.split(":", 1)[0] \
        if ":" in instrument else None
    if not isinstance(subject, dict) or set(subject) != {
            "instrumentId", "kind", "market"} or \
            subject.get("kind") != "ASSET" or \
            subject.get("instrumentId") != instrument or \
            (instrument_market in {"JP", "US"} and
             subject.get("market") != instrument_market):
        raise ResearchContractError("golden_risk_subject_mismatch")
    as_of = _timestamp(artifact.get("asOf"), "golden_risk_as_of")
    cutoff = _timestamp(
        artifact.get("informationCutoffAt"), "golden_risk_cutoff")
    if cutoff != as_of or as_of > event_cutoff or \
            artifact["asOf"] != as_of.isoformat().replace("+00:00", "Z"):
        raise ResearchContractError("golden_risk_cutoff_mismatch")
    return artifact


def _golden_sho_reversal(value: Any, *, instrument: str,
                         event_cutoff: datetime) -> Optional[Dict[str, Any]]:
    if value is None:
        return None
    keys = {
        "action", "analysisInstrument", "artifactId", "automaticAiCalls",
        "canonicalRfcSha256", "downsideAxis", "evidence",
        "evidenceArtifact", "evidenceArtifactId", "informationCutoff",
        "oneStepTransitionRequired", "reversalAxis", "schemaVersion",
        "stateMayJump",
    }
    if not isinstance(value, Mapping) or set(value) != keys:
        raise ResearchContractError("invalid_golden_sho_reversal")
    artifact = _copy_json(value)
    try:
        validate_reversal_artifact(artifact)
    except ValueError as exc:
        raise ResearchContractError("invalid_golden_sho_reversal") from exc
    body = {key: artifact[key] for key in artifact if key != "artifactId"}
    cutoff = _timestamp(
        artifact.get("informationCutoff"), "golden_sho_cutoff")
    evidence = artifact.get("evidence")
    band = evidence.get("bandWalkEnding") \
        if isinstance(evidence, dict) else None
    if artifact.get("artifactId") != "sho-reversal-" + sha256_hex(body) or \
            artifact.get("schemaVersion") != "argus-sho-reversal-v1" or \
            artifact.get("canonicalRfcSha256") != (
                "69a631ebc549b3bede6356cabf338e38d9418fc3683821198ef9a3c1eb440d51") or \
            artifact.get("analysisInstrument") != instrument or \
            cutoff != event_cutoff or \
            artifact.get("informationCutoff") != \
            cutoff.isoformat().replace("+00:00", "Z") or \
            artifact.get("action") is not None or \
            artifact.get("automaticAiCalls") != 0 or \
            not isinstance(band, dict) or \
            band.get("conditionMet") not in (True, False, None) or \
            (band.get("conditionMet") is None) != (
                band.get("evidenceDate") is None):
        raise ResearchContractError("invalid_golden_sho_reversal")
    if band.get("evidenceDate") is not None:
        evidence_date = _date(
            band["evidenceDate"], "golden_band_walk_evidence_date")
        if evidence_date > cutoff.date():
            raise ResearchContractError(
                "golden_band_walk_evidence_after_cutoff")
    return artifact


def _normalize_event(raw: Mapping[str, Any], cutoff: datetime,
                     policy: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    required = {
        "datasetId", "eventId", "instrumentId", "signalDate", "availableFrom",
        "decisionCutoffAt",
    }
    allowed = required | {
        "expectedDirection", "probability", "targetPct", "invalidationPct",
        "regime", "ablationTags", "validatedReversal", "evidenceRefs",
        "riskKernelArtifact", "shoReversalArtifact",
    }
    if not isinstance(raw, Mapping) or not required.issubset(raw) or \
            not set(raw).issubset(allowed):
        raise ResearchContractError("invalid_event_fields")
    available = _timestamp(raw.get("availableFrom"), "event_available_from")
    if available > cutoff:
        return None
    decision_cutoff = _timestamp(
        raw.get("decisionCutoffAt"), "event_decision_cutoff")
    if decision_cutoff > cutoff:
        return None
    if available > decision_cutoff:
        raise ResearchContractError("event_available_after_decision_cutoff")
    event_id = _text(raw.get("eventId"), "event_id", 120)
    dataset_id = _text(raw.get("datasetId"), "event_dataset_id", 120)
    instrument = _text(raw.get("instrumentId"), "instrument_id", 120).upper()
    signal_date = _date(raw.get("signalDate"), "signal_date").isoformat()
    if decision_cutoff.date().isoformat() != signal_date:
        raise ResearchContractError(
            "event_decision_cutoff_outside_signal_session")
    direction = raw.get("expectedDirection", "UP")
    if direction not in ("UP", "DOWN"):
        raise ResearchContractError("invalid_expected_direction")
    probability = None
    if raw.get("probability") is not None:
        probability = _number(raw.get("probability"), "event_probability")
        if not 0 <= probability <= 1:
            raise ResearchContractError("invalid_event_probability")
    target = None if raw.get("targetPct") is None else _number(
        raw.get("targetPct"), "event_target_pct")
    invalidation = None if raw.get("invalidationPct") is None else _number(
        raw.get("invalidationPct"), "event_invalidation_pct")
    if target is not None and target <= 0:
        raise ResearchContractError("invalid_event_target_pct")
    if invalidation is not None and invalidation >= 0:
        raise ResearchContractError("invalid_event_invalidation_pct")
    regime = raw.get("regime", "UNKNOWN")
    regime = _text(regime, "event_regime", 80)
    tags = raw.get("ablationTags", [])
    if not isinstance(tags, list) or len(tags) > 16:
        raise ResearchContractError("invalid_ablation_tags")
    clean_tags = sorted(set(_text(tag, "ablation_tag", 80) for tag in tags))
    refs = raw.get("evidenceRefs", [])
    if not isinstance(refs, list) or len(refs) > 32:
        raise ResearchContractError("invalid_evidence_refs")
    clean_refs = sorted(set(_text(ref, "evidence_ref", 200) for ref in refs))
    if not isinstance(raw.get("validatedReversal", False), bool):
        raise ResearchContractError("invalid_validated_reversal")
    risk_kernel = _golden_risk_kernel(
        raw.get("riskKernelArtifact"), instrument=instrument,
        event_cutoff=decision_cutoff)
    sho_reversal = _golden_sho_reversal(
        raw.get("shoReversalArtifact"), instrument=instrument,
        event_cutoff=decision_cutoff)
    return {
        "ablationTags": clean_tags,
        "availableFrom": available.isoformat().replace("+00:00", "Z"),
        "decisionCutoffAt": decision_cutoff.isoformat().replace(
            "+00:00", "Z"),
        "datasetId": dataset_id,
        "eventId": event_id,
        "evidenceRefs": clean_refs,
        "expectedDirection": direction,
        "instrumentId": instrument,
        "invalidationPct": _round(invalidation),
        "partition": partition_for_date(signal_date, policy),
        "probability": _round(probability),
        "regime": regime,
        "riskKernelArtifact": risk_kernel,
        "signalDate": signal_date,
        "targetPct": _round(target),
        "shoReversalArtifact": sho_reversal,
        "validatedReversal": bool(raw.get("validatedReversal", False)),
    }


def normalize_point_in_time_events(rows: Iterable[Mapping[str, Any]], *,
                                   cutoff_at: str,
                                   partition_policy: Mapping[str, Any]) \
        -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    cutoff = _timestamp(cutoff_at, "information_cutoff")
    source = _bounded_collect(rows, MAX_EVENTS, "event")
    selected = {}
    excluded = 0
    duplicates = 0
    for raw in source:
        row = _normalize_event(raw, cutoff, partition_policy)
        if row is None:
            excluded += 1
            continue
        prior = selected.get(row["eventId"])
        if prior is None:
            selected[row["eventId"]] = row
        elif prior == row:
            duplicates += 1
        else:
            raise ResearchContractError("conflicting_event_id")
    result = sorted(selected.values(), key=lambda row: (
        row["signalDate"], row["instrumentId"], row["eventId"]))
    return result, {
        "admittedEventCount": len(result),
        "duplicateEventCount": duplicates,
        "eventHash": sha256_hex(result),
        "excludedFutureCount": excluded,
        "futureEventsAdmitted": False,
        "pitPolicyId": PIT_POLICY_ID,
        "sourceEventCount": len(source),
        "verified": True,
    }


def _bars_by_instrument(bars: Sequence[Dict[str, Any]]) \
        -> Dict[str, List[Dict[str, Any]]]:
    result: Dict[str, List[Dict[str, Any]]] = {}
    for row in bars:
        result.setdefault(row["instrumentId"], []).append(row)
    for rows in result.values():
        rows.sort(key=lambda row: row["date"])
    return result


def _validate_embargo_bar_sessions(
        by_instrument: Mapping[str, Sequence[Dict[str, Any]]],
        partition_policy: Mapping[str, Any]) -> None:
    required = partition_policy["embargoSessions"]
    embargoes = [row for row in partition_policy["ranges"]
                 if row["name"] == "EMBARGO"]
    for rows in by_instrument.values():
        dates = {row["date"] for row in rows}
        for embargo in embargoes:
            admitted = sum(
                1 for value in dates
                if embargo["startDate"] <= value <= embargo["endDate"])
            if admitted < required:
                raise ResearchContractError(
                    "insufficient_embargo_bar_sessions")


def _true_range(current: Dict[str, Any], previous_close: Optional[float]) -> float:
    values = [current["high"] - current["low"]]
    if previous_close is not None:
        values.extend((abs(current["high"] - previous_close),
                       abs(current["low"] - previous_close)))
    return max(values)


def turtle_shadow(bars: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Compute supplied Turtle rules as non-authoritative shadow evidence."""
    signals = []
    signal_day_count = 0
    counts = {"entry20": 0, "entry55": 0, "exit10": 0, "exit20": 0}
    by_instrument = _bars_by_instrument(bars)
    for instrument in sorted(by_instrument):
        rows = by_instrument[instrument]
        atr = None
        for index, row in enumerate(rows):
            tr = _true_range(row, rows[index - 1]["close"] if index else None)
            if index == 19:
                atr = statistics.fmean(
                    _true_range(rows[pos], rows[pos - 1]["close"] if pos else None)
                    for pos in range(20))
            elif index > 19 and atr is not None:
                atr = ((atr * 19.0) + tr) / 20.0
            entry20 = index >= 20 and row["high"] > max(
                item["high"] for item in rows[index - 20:index])
            entry55 = index >= 55 and row["high"] > max(
                item["high"] for item in rows[index - 55:index])
            exit10 = index >= 10 and row["low"] < min(
                item["low"] for item in rows[index - 10:index])
            exit20 = index >= 20 and row["low"] < min(
                item["low"] for item in rows[index - 20:index])
            flags = {"entry20": entry20, "entry55": entry55,
                     "exit10": exit10, "exit20": exit20}
            for key, active in flags.items():
                if active:
                    counts[key] += 1
            if any(flags.values()):
                signal_day_count += 1
            if any(flags.values()) and len(signals) < MAX_TURTLE_SIGNAL_DETAILS:
                signals.append({
                    "atrN": _round(atr),
                    "date": row["date"],
                    "entry20": entry20,
                    "entry55": entry55,
                    "exit10": exit10,
                    "exit20": exit20,
                    "instrumentId": instrument,
                })
    return {
        "hardVeto": False,
        "parameters": {
            "atrPeriod": 20,
            "entryLookbacks": [20, 55],
            "exitLookbacks": [10, 20],
        },
        "schemaVersion": TURTLE_SCHEMA,
        "shadowOnly": True,
        "signalDayCount": signal_day_count,
        "signalCounts": counts,
        "signals": signals,
        "signalsTruncated": signal_day_count > len(signals),
        "unknownHistoricalRules": [
            "original_unit_limit", "original_pyramiding", "original_stop_rule",
            "original_portfolio_heat", "original_execution_details",
        ],
        "validationStatus": "UNVALIDATED_UNTIL_LAWFUL_OHLC_HOLDOUT",
    }


def _turtle_entry_dates(bars: Sequence[Dict[str, Any]]) \
        -> Dict[str, Dict[str, str]]:
    """Return uncapped entry date->system map for internal counterfactuals."""
    result: Dict[str, Dict[str, str]] = {}
    for instrument, rows in sorted(_bars_by_instrument(bars).items()):
        dates = result.setdefault(instrument, {})
        for index, row in enumerate(rows):
            entry20 = index >= 20 and row["high"] > max(
                item["high"] for item in rows[index - 20:index])
            entry55 = index >= 55 and row["high"] > max(
                item["high"] for item in rows[index - 55:index])
            if entry20 or entry55:
                dates[row["date"]] = "55_DAY" if entry55 else "20_DAY"
    return result


def _path_metrics(rows: Sequence[Dict[str, Any]], start_index: int,
                  horizon: int, entry_price: float, direction: str,
                  target_pct: float, invalidation_pct: float,
                  new_low_lookback: int) -> Optional[Dict[str, Any]]:
    if horizon <= 0:
        return None
    end_index = start_index + horizon
    if end_index >= len(rows):
        return None
    path = rows[start_index + 1:end_index + 1]
    if len(path) != horizon:
        return None
    sign = 1.0 if direction == "UP" else -1.0
    end_return = sign * (path[-1]["close"] / entry_price - 1.0) * 100.0
    if direction == "UP":
        excursions = [(row["high"] / entry_price - 1.0) * 100.0
                      for row in path]
        adverse = [(row["low"] / entry_price - 1.0) * 100.0
                   for row in path]
        target_levels = [entry_price * (1 + target_pct / 100.0)]
        invalidation_level = entry_price * (1 + invalidation_pct / 100.0)
        target_hits = [row["high"] >= target_levels[0] for row in path]
        target_breaks = [row["close"] >= target_levels[0] for row in path]
        invalidation_hits = [row["low"] <= invalidation_level for row in path]
    else:
        excursions = [(1.0 - row["low"] / entry_price) * 100.0
                      for row in path]
        adverse = [(1.0 - row["high"] / entry_price) * 100.0
                   for row in path]
        target_level = entry_price * (1 - target_pct / 100.0)
        invalidation_level = entry_price * (1 - invalidation_pct / 100.0)
        target_hits = [row["low"] <= target_level for row in path]
        target_breaks = [row["close"] <= target_level for row in path]
        invalidation_hits = [row["high"] >= invalidation_level for row in path]
    mfe = max(0.0, max(excursions))
    mae = min(0.0, min(adverse))
    max_dd = 0.0
    if direction == "UP":
        peak = entry_price
        for row in path:
            peak = max(peak, row["high"])
            max_dd = min(max_dd, (row["low"] / peak - 1.0) * 100.0)
    else:
        trough = entry_price
        for row in path:
            trough = min(trough, row["low"])
            max_dd = min(max_dd, (1.0 - row["high"] / trough) * 100.0)
    prior = rows[max(0, start_index - new_low_lookback + 1):start_index + 1]
    prior_low = min(row["low"] for row in prior) if prior else entry_price
    new_low = min(row["low"] for row in path) < prior_low

    def first_true(flags: Sequence[bool]) -> Optional[int]:
        for offset, active in enumerate(flags, 1):
            if active:
                return offset
        return None

    target_at = first_true(target_hits)
    invalidation_at = first_true(invalidation_hits)
    ambiguous = target_at is not None and target_at == invalidation_at
    return {
        "ambiguousTargetInvalidation": ambiguous,
        "endReturnPct": _round(end_return),
        "falsePositive": end_return <= 0 or invalidation_at is not None,
        "invalidationHit": invalidation_at is not None,
        "maePct": _round(mae),
        "maxDrawdownPct": _round(max_dd),
        "mfePct": _round(mfe),
        "newLow": new_low,
        "outcomeDate": path[-1]["date"],
        "targetBreak": any(target_breaks),
        "targetHit": target_at is not None,
        "timeToInvalidationSessions": invalidation_at,
        "timeToTargetSessions": target_at,
    }


def _event_metrics(event: Dict[str, Any], rows: Sequence[Dict[str, Any]],
                   horizons: Sequence[int], params: Mapping[str, Any]) \
        -> Dict[str, Any]:
    index_by_date = {row["date"]: index for index, row in enumerate(rows)}
    start_index = index_by_date.get(event["signalDate"])
    target = event["targetPct"] if event["targetPct"] is not None else \
        params["targetPct"]
    invalidation = (event["invalidationPct"]
                    if event["invalidationPct"] is not None
                    else params["invalidationPct"])
    result = {
        "ablationTags": event["ablationTags"],
        "availableFrom": event["availableFrom"],
        "counterfactualSessionDates": (
            [] if start_index is None else [
                row["date"] for row in rows[
                    start_index:start_index
                    + max(max(horizons), params[
                        "counterfactualHorizon"]) + 1]
            ]),
        "datasetId": event["datasetId"],
        "decisionCutoffAt": event["decisionCutoffAt"],
        "eventId": event["eventId"],
        "evidenceRefs": event["evidenceRefs"],
        "expectedDirection": event["expectedDirection"],
        "horizons": {},
        "instrumentId": event["instrumentId"],
        "invalidationPct": invalidation,
        "partition": event["partition"],
        "regime": event["regime"],
        "riskKernelArtifact": event["riskKernelArtifact"],
        "signalDate": event["signalDate"],
        "shoReversalArtifact": event["shoReversalArtifact"],
        "targetPct": target,
        "validatedReversal": event["validatedReversal"],
    }
    if start_index is None:
        result["status"] = "UNSCORABLE_SIGNAL_BAR_MISSING"
        return result
    for horizon in horizons:
        metrics = _path_metrics(
            rows, start_index, horizon, rows[start_index]["close"],
            event["expectedDirection"], target, invalidation,
            params["newLowLookback"])
        if metrics is None:
            result["horizons"][str(horizon)] = {"status": "UNSCORABLE_INCOMPLETE_PATH"}
            continue
        probability = event["probability"]
        outcome = 1.0 if metrics["endReturnPct"] > 0 else 0.0
        bounded_probability = (None if probability is None else
                               max(1e-12, min(1.0 - 1e-12, probability)))
        metrics.update({
            "brier": (None if probability is None else _round(
                (probability - outcome) ** 2)),
            "logLoss": (None if bounded_probability is None else _round(
                -(outcome * math.log(bounded_probability)
                  + (1.0 - outcome) * math.log(1.0 - bounded_probability)))),
            "missedOpportunity": metrics["mfePct"] >= params[
                "waitFailureThresholdPct"],
            "probability": event["probability"],
            "rally": metrics["mfePct"] >= params["rallyThresholdPct"],
            "reversal": (metrics["maePct"] <= -params["reversalThresholdPct"]
                         and metrics["endReturnPct"] > 0),
            "status": ("AMBIGUOUS" if metrics[
                "ambiguousTargetInvalidation"] else "OBSERVED"),
        })
        metrics["falseRally"] = bool(
            metrics["rally"] and metrics["falsePositive"])
        metrics["falseReversal"] = bool(
            event["validatedReversal"] and metrics["falsePositive"])
        result["horizons"][str(horizon)] = metrics
    result["status"] = "EVALUATED"
    return result


def _mean(values: Iterable[Optional[float]]) -> Optional[float]:
    clean = [float(value) for value in values if value is not None]
    return _round(statistics.fmean(clean)) if clean else None


def _median(values: Iterable[Optional[float]]) -> Optional[float]:
    clean = [float(value) for value in values if value is not None]
    return _round(statistics.median(clean)) if clean else None


def _rate(values: Iterable[bool]) -> Optional[float]:
    clean = list(values)
    return _round(sum(1 for value in clean if value) / len(clean)) if clean else None


def _wilson(successes: int, total: int) -> Optional[List[float]]:
    if total <= 0:
        return None
    z = 1.959963984540054
    p = successes / total
    denominator = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denominator
    radius = z * math.sqrt((p * (1 - p) + z * z / (4 * total)) / total) / denominator
    return [_round(max(0.0, center - radius)),
            _round(min(1.0, center + radius))]


def _calibration(rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    eligible = [row for row in rows if row.get("probability") is not None]
    bins = []
    weighted_error = 0.0
    for lower in (0.0, 0.2, 0.4, 0.6, 0.8):
        upper = lower + 0.2
        members = [row for row in eligible if lower <= row["probability"] <= upper
                   and (lower == 0.8 or row["probability"] < upper)]
        if not members:
            continue
        forecast = statistics.fmean(row["probability"] for row in members)
        observed = statistics.fmean(
            1.0 if row["endReturnPct"] > 0 else 0.0 for row in members)
        weighted_error += len(members) * abs(forecast - observed)
        bins.append({
            "count": len(members), "forecastMean": _round(forecast),
            "lower": _round(lower), "observedRate": _round(observed),
            "upper": _round(upper),
        })
    return {
        "bins": bins,
        "ece": (_round(weighted_error / len(eligible)) if eligible else None),
        "sampleCount": len(eligible),
    }


def _aggregate_horizon(event_rows: Sequence[Dict[str, Any]], horizon: int) \
        -> Dict[str, Any]:
    observed = []
    unscorable = 0
    ambiguous = 0
    for event in event_rows:
        row = event.get("horizons", {}).get(str(horizon), {})
        if row.get("status") in ("OBSERVED", "AMBIGUOUS"):
            observed.append(row)
            ambiguous += int(row.get("status") == "AMBIGUOUS")
        else:
            unscorable += 1
    wins = sum(1 for row in observed if row["endReturnPct"] > 0)
    by_regime = {}
    tags = {}
    for event in event_rows:
        row = event.get("horizons", {}).get(str(horizon), {})
        if row.get("status") not in ("OBSERVED", "AMBIGUOUS"):
            continue
        by_regime.setdefault(event["regime"], []).append(row["endReturnPct"])
        for tag in event["ablationTags"]:
            tags.setdefault(tag, []).append(row["endReturnPct"])
    return {
        "ambiguousCount": ambiguous,
        "brierMean": _mean(row.get("brier") for row in observed),
        "calibration": _calibration(observed),
        "falsePositiveRate": _rate(row["falsePositive"] for row in observed),
        "falseRallyRate": _rate(row["falseRally"] for row in observed),
        "falseReversalRate": _rate(
            row["falseReversal"] for row in observed),
        "logLossMean": _mean(row.get("logLoss") for row in observed),
        "maeMeanPct": _mean(row["maePct"] for row in observed),
        "maxDrawdownMeanPct": _mean(row["maxDrawdownPct"] for row in observed),
        "medianReturnPct": _median(row["endReturnPct"] for row in observed),
        "mfeMeanPct": _mean(row["mfePct"] for row in observed),
        "missedOpportunityRate": _rate(
            row["missedOpportunity"] for row in observed),
        "newLowRate": _rate(row["newLow"] for row in observed),
        "regimes": [{
            "meanReturnPct": _mean(values), "regime": key,
            "sampleCount": len(values),
        } for key, values in sorted(by_regime.items())],
        "returnMeanPct": _mean(row["endReturnPct"] for row in observed),
        "reversalRate": _rate(row["reversal"] for row in observed),
        "rallyRate": _rate(row["rally"] for row in observed),
        "sampleCount": len(event_rows),
        "scoreableCount": len(observed),
        "targetBreakRate": _rate(row["targetBreak"] for row in observed),
        "targetHitRate": _rate(row["targetHit"] for row in observed),
        "timeToTargetMedianSessions": _median(
            row["timeToTargetSessions"] for row in observed),
        "unscorableCount": unscorable,
        "winRate": _round(wins / len(observed)) if observed else None,
        "winRateCi95Wilson": _wilson(wins, len(observed)),
        "ablations": [{
            "meanReturnPct": _mean(values), "sampleCount": len(values),
            "tag": key,
        } for key, values in sorted(tags.items())[:32]],
    }


def _aggregate_events(event_rows: Sequence[Dict[str, Any]],
                      horizons: Sequence[int]) -> Dict[str, Any]:
    return {str(horizon): _aggregate_horizon(event_rows, horizon)
            for horizon in horizons}


def _fold_summary(events: Sequence[Dict[str, Any]], folds: Sequence[Dict[str, Any]],
                  horizons: Sequence[int]) -> List[Dict[str, Any]]:
    result = []
    for fold in folds:
        stages = {}
        for stage, start_key, end_key in (
                ("TRAIN", "trainStartDate", "trainEndDate"),
                ("VALIDATION", "validationStartDate", "validationEndDate"),
                ("FORWARD", "forwardStartDate", "forwardEndDate")):
            members = [event for event in events
                       if fold[start_key] <= event["signalDate"] <= fold[end_key]]
            bounded_members = []
            for event in members:
                bounded = dict(event)
                bounded["horizons"] = {}
                for horizon in horizons:
                    outcome = event.get("horizons", {}).get(str(horizon), {})
                    if outcome.get("outcomeDate") and \
                            outcome["outcomeDate"] > fold[end_key]:
                        bounded["horizons"][str(horizon)] = {
                            "status": "UNSCORABLE_STAGE_BOUNDARY"}
                    else:
                        bounded["horizons"][str(horizon)] = outcome
                bounded_members.append(bounded)
            stages[stage] = {
                "eventCount": len(members),
                "metrics": (_aggregate_events(bounded_members, horizons)
                            if stage != "TRAIN" else None),
            }
        result.append({"foldId": fold["foldId"], "stages": stages})
    return result


def _entry_index(rows: Sequence[Dict[str, Any]], anchor: int, trigger: int,
                 execution_policy: str) -> Optional[int]:
    index = trigger if execution_policy == "signal_close" else trigger + 1
    return index if anchor <= index < len(rows) else None


def _counterfactual_for_event(event: Dict[str, Any], rows: Sequence[Dict[str, Any]],
                              turtle_dates: Mapping[str, str],
                              params: Mapping[str, Any],
                              execution_policy: str, cost_bps: float,
                              slippage_bps: float) -> Dict[str, Any]:
    date_index = {row["date"]: index for index, row in enumerate(rows)}
    anchor = date_index.get(event["signalDate"])
    horizon = params["counterfactualHorizon"]
    if anchor is None or anchor + horizon >= len(rows):
        return {"eventId": event["eventId"], "status": "UNSCORABLE_INCOMPLETE_PATH",
                "strategies": []}
    terminal = anchor + horizon
    target_pct = event["targetPct"] if event["targetPct"] is not None else \
        params["targetPct"]
    invalidation_pct = (event["invalidationPct"]
                        if event["invalidationPct"] is not None else
                        params["invalidationPct"])
    triggers: Dict[str, Optional[int]] = {"BUY_NOW": anchor, "WAIT": None}
    for strategy, field in SIGNAL_FIELDS.items():
        triggers[strategy] = next((index for index in range(anchor, terminal + 1)
                                   if rows[index]["signals"].get(field)), None)
    triggers["BUY_ON_TURTLE_CONFIRMATION"] = next((
        index for index in range(anchor, terminal + 1)
        if rows[index]["date"] in turtle_dates), None)

    round_trip_cost_pct = 2.0 * (cost_bps + slippage_bps) / 100.0
    results = []
    buy_now = None
    for strategy in COUNTERFACTUAL_STRATEGIES:
        if strategy == "WAIT":
            continue
        trigger = triggers[strategy]
        entry = None if trigger is None else _entry_index(
            rows, anchor, trigger, execution_policy)
        if entry is None or entry > terminal:
            row = {
                "avoidedMaePct": None, "delaySessions": None,
                "entryDate": None, "entryPrice": None, "failure": False,
                "exitDate": None, "exitRule": None,
                "foregoneReturnPct": None, "invalidationHit": None,
                "maePct": None, "maxDrawdownPct": None, "mfePct": None,
                "missedMfePct": None, "ownerPnl": False,
                "strategy": strategy, "targetHit": None,
                "terminalReturnPct": None, "terminalStatus": "NO_TRIGGER",
                "timeToTargetSessions": None,
            }
        else:
            entry_price = (rows[entry]["close"] if execution_policy ==
                           "signal_close" else rows[entry]["open"])
            strategy_terminal = terminal
            terminal_price = rows[terminal]["close"]
            exit_date = None
            exit_rule = None
            if strategy == "BUY_ON_TURTLE_CONFIRMATION" and trigger is not None:
                system = turtle_dates.get(rows[trigger]["date"])
                exit_lookback = 20 if system == "55_DAY" else 10
                exit_trigger = next((index for index in range(entry, terminal + 1)
                                     if index >= exit_lookback and rows[index]["low"] < min(
                                         item["low"] for item in rows[
                                             index - exit_lookback:index])), None)
                if exit_trigger is not None:
                    candidate_exit = _entry_index(
                        rows, entry, exit_trigger, execution_policy)
                    if candidate_exit is not None and candidate_exit <= terminal:
                        strategy_terminal = candidate_exit
                        exit_date = rows[candidate_exit]["date"]
                        exit_rule = f"{exit_lookback}_DAY_LOW_EXIT"
                        terminal_price = (rows[candidate_exit]["close"]
                                          if execution_policy == "signal_close"
                                          else rows[candidate_exit]["open"])
            metric_start = entry if execution_policy == "signal_close" else entry - 1
            metric_terminal = (strategy_terminal if execution_policy == "signal_close"
                               or exit_date is None else strategy_terminal - 1)
            local_horizon = metric_terminal - metric_start
            metrics = _path_metrics(
                rows, metric_start, local_horizon, entry_price, "UP", target_pct,
                invalidation_pct, params["newLowLookback"])
            if metrics is None:
                row = {"strategy": strategy, "terminalStatus": "UNSCORABLE",
                       "ownerPnl": False}
            else:
                row = {
                    "avoidedMaePct": None,
                    "delaySessions": entry - anchor,
                    "entryDate": rows[entry]["date"],
                    "entryPrice": _round(entry_price),
                    "exitDate": exit_date,
                    "exitRule": exit_rule,
                    "failure": False,
                    "foregoneReturnPct": None,
                    "invalidationHit": metrics["invalidationHit"],
                    "maePct": metrics["maePct"],
                    "maxDrawdownPct": metrics["maxDrawdownPct"],
                    "mfePct": metrics["mfePct"],
                    "missedMfePct": None,
                    "ownerPnl": False,
                    "strategy": strategy,
                    "targetHit": metrics["targetHit"],
                    "terminalReturnPct": _round(
                        (terminal_price / entry_price - 1.0) * 100.0
                        - round_trip_cost_pct),
                    "terminalStatus": (
                        exit_rule if exit_rule is not None else
                        "AMBIGUOUS" if metrics[
                            "ambiguousTargetInvalidation"] else "ENTERED"),
                    "timeToTargetSessions": metrics["timeToTargetSessions"],
                }
        if strategy == "BUY_NOW":
            buy_now = row
        results.append(row)
    if buy_now is None or buy_now.get("mfePct") is None:
        return {"eventId": event["eventId"], "status": "UNSCORABLE_BUY_NOW",
                "strategies": results}
    for row in results:
        if row.get("mfePct") is not None:
            row["missedMfePct"] = _round(max(
                0.0, buy_now["mfePct"] - row["mfePct"]))
            row["avoidedMaePct"] = _round(max(
                0.0, abs(buy_now["maePct"]) - abs(row["maePct"])))
            row["foregoneReturnPct"] = _round(
                buy_now["terminalReturnPct"] - row["terminalReturnPct"])
        else:
            row["missedMfePct"] = buy_now["mfePct"]
            row["avoidedMaePct"] = abs(buy_now["maePct"])
            row["foregoneReturnPct"] = buy_now["terminalReturnPct"]
    wait_failure = bool(
        event["validatedReversal"]
        and buy_now["mfePct"] >= params["waitFailureThresholdPct"])
    results.append({
        "avoidedMaePct": abs(buy_now["maePct"]),
        "cashReturnAssumptionPct": 0.0,
        "delaySessions": None,
        "entryDate": None,
        "entryPrice": None,
        "failure": wait_failure,
        "foregoneReturnPct": buy_now["terminalReturnPct"],
        "invalidationHit": False,
        "maePct": 0.0,
        "maxDrawdownPct": 0.0,
        "mfePct": 0.0,
        "missedMfePct": buy_now["mfePct"],
        "ownerPnl": False,
        "strategy": "WAIT",
        "targetHit": False,
        "terminalReturnPct": 0.0,
        "terminalStatus": ("MISSED_VALIDATED_REVERSAL" if wait_failure
                           else "WAITED_IN_CASH"),
        "timeToTargetSessions": None,
    })
    results.sort(key=lambda row: COUNTERFACTUAL_STRATEGIES.index(row["strategy"]))
    return {
        "eventId": event["eventId"],
        "horizonSessions": horizon,
        "ownerPnl": False,
        "status": "EVALUATED",
        "strategies": results,
    }


def _counterfactual_summary(rows: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    result = []
    for strategy in COUNTERFACTUAL_STRATEGIES:
        members = [item for event in rows for item in event.get("strategies", [])
                   if item.get("strategy") == strategy]
        result.append({
            "evaluatedCount": sum(1 for item in members
                                  if item.get("terminalReturnPct") is not None),
            "failureCount": sum(1 for item in members if item.get("failure")),
            "meanAvoidedMaePct": _mean(item.get("avoidedMaePct") for item in members),
            "meanDelaySessions": _mean(item.get("delaySessions") for item in members),
            "meanForegoneReturnPct": _mean(
                item.get("foregoneReturnPct") for item in members),
            "meanMaePct": _mean(item.get("maePct") for item in members),
            "meanMaxDrawdownPct": _mean(
                item.get("maxDrawdownPct") for item in members),
            "meanMfePct": _mean(item.get("mfePct") for item in members),
            "meanMissedMfePct": _mean(
                item.get("missedMfePct") for item in members),
            "meanTerminalReturnPct": _mean(
                item.get("terminalReturnPct") for item in members),
            "ownerPnl": False,
            "strategy": strategy,
        })
    return result


def _partition_priority_details(
        events: Sequence[Dict[str, Any]],
        counterfactuals: Sequence[Dict[str, Any]]) \
        -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Retain Golden/Holdout audit rows before Development under the cap."""
    selected: List[Dict[str, Any]] = []
    for partition in ("GOLDEN", "HOLDOUT", "DEVELOPMENT"):
        for row in events:
            if row.get("partition") == partition:
                selected.append(row)
                if len(selected) >= MAX_EVENT_DETAILS:
                    break
        if len(selected) >= MAX_EVENT_DETAILS:
            break
    selected_ids = {row["eventId"] for row in selected}
    counterfactual_by_id = {
        row.get("eventId"): row for row in counterfactuals
        if row.get("eventId") in selected_ids
    }
    retained_counterfactuals = [
        counterfactual_by_id[row["eventId"]] for row in selected
        if row["eventId"] in counterfactual_by_id]
    return selected, retained_counterfactuals


def _partition_has_input(rows: Sequence[Mapping[str, Any]],
                         partition_policy: Mapping[str, Any], name: str) -> bool:
    for raw in rows:
        day = raw.get("date") if "date" in raw else raw.get("signalDate")
        if day and partition_for_date(day, partition_policy) == name:
            return True
    return False


def _coerce_csv_row(row: Mapping[str, str]) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    numeric = {
        "open", "high", "low", "close", "volume", "probability",
        "targetPct", "invalidationPct",
    }
    signals: Dict[str, bool] = {}
    for key, raw in row.items():
        if key is None:
            continue
        value = raw.strip() if isinstance(raw, str) else raw
        if value == "":
            continue
        if key == "revision":
            try:
                result[key] = int(value)
            except (TypeError, ValueError) as exc:
                raise ResearchContractError("invalid_csv_revision") from exc
        elif key in numeric:
            try:
                result[key] = float(value)
            except (TypeError, ValueError) as exc:
                raise ResearchContractError("invalid_csv_number") from exc
        elif key == "validatedReversal":
            if str(value).lower() not in ("true", "false"):
                raise ResearchContractError("invalid_csv_boolean")
            result[key] = str(value).lower() == "true"
        elif key.startswith("signal."):
            name = key.split(".", 1)[1]
            if str(value).lower() not in ("true", "false"):
                raise ResearchContractError("invalid_csv_signal")
            signals[name] = str(value).lower() == "true"
        elif key in ("ablationTags", "evidenceRefs"):
            result[key] = [
                item.strip() for item in str(value).split("|")
                if item.strip()]
        else:
            result[key] = value
    if signals:
        result["signals"] = signals
    return result


def _decode_dataset_payload(descriptor: Mapping[str, Any], raw: bytes) \
        -> List[Dict[str, Any]]:
    if not isinstance(raw, bytes) or len(raw) > MAX_DATASET_BYTES:
        raise ResearchContractError("dataset_byte_bound_exceeded")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ResearchContractError("dataset_not_utf8") from exc
    suffix = str(descriptor["path"]).lower().rsplit(".", 1)[-1]
    if suffix == "json":
        try:
            document = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ResearchContractError("dataset_invalid_json") from exc
        if isinstance(document, list):
            rows = document
        elif isinstance(document, dict) and isinstance(
                document.get(descriptor["kind"]), list):
            rows = document[descriptor["kind"]]
        else:
            raise ResearchContractError("dataset_json_shape_invalid")
    elif suffix == "jsonl":
        rows = []
        for line in text.splitlines():
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ResearchContractError(
                    "dataset_jsonl_line_invalid") from exc
    elif suffix == "csv":
        rows = [_coerce_csv_row(row) for row in csv.DictReader(
            text.splitlines())]
    else:
        raise ResearchContractError("unsupported_dataset_format")
    maximum = MAX_BARS if descriptor["kind"] == "bars" else MAX_EVENTS
    if len(rows) > maximum or not all(isinstance(row, dict) for row in rows):
        raise ResearchContractError("dataset_row_contract_invalid")
    result = []
    for raw_row in rows:
        row = dict(raw_row)
        if "datasetId" not in row:
            row["datasetId"] = descriptor["datasetId"]
        elif row["datasetId"] != descriptor["datasetId"]:
            raise ResearchContractError("dataset_id_mismatch")
        result.append(row)
    return result


def build_research_artifact(manifest: Mapping[str, Any],
                            bars: Iterable[Mapping[str, Any]],
                            events: Iterable[Mapping[str, Any]]) -> Dict[str, Any]:
    """Run one deterministic research evaluation and return a compact artifact."""
    contract = validate_manifest(manifest)
    raw_bars = _bounded_collect(bars, MAX_BARS, "bar")
    raw_events = _bounded_collect(events, MAX_EVENTS, "event")
    if contract["goldenPolicy"]["access"] == "SEALED" and (
            _partition_has_input(raw_bars, contract["partitionPolicy"], "GOLDEN")
            or _partition_has_input(raw_events, contract["partitionPolicy"],
                                    "GOLDEN")):
        raise ResearchContractError("sealed_golden_input_forbidden")
    if contract["freeze"]["status"] == "DRAFT" and (
            _partition_has_input(raw_bars, contract["partitionPolicy"],
                                 "HOLDOUT")
            or _partition_has_input(raw_events, contract["partitionPolicy"],
                                    "HOLDOUT")):
        raise ResearchContractError("holdout_requires_frozen_policy")
    pit_bars, bar_proof = normalize_point_in_time_bars(
        raw_bars, cutoff_at=contract["informationCutoffAt"])
    pit_events, event_proof = normalize_point_in_time_events(
        raw_events, cutoff_at=contract["informationCutoffAt"],
        partition_policy=contract["partitionPolicy"])
    declared_datasets = {
        row["datasetId"]: row for row in contract["datasets"]
    }
    for row in pit_bars:
        descriptor = declared_datasets.get(row["datasetId"])
        if descriptor is None or descriptor["kind"] != "bars":
            raise ResearchContractError("undeclared_bar_dataset")
        partition = partition_for_date(
            row["date"], contract["partitionPolicy"])
        expected_scope = "GOLDEN" if partition == "GOLDEN" \
            else "NON_GOLDEN"
        if descriptor["partitionScope"] != expected_scope:
            raise ResearchContractError("bar_dataset_partition_scope_mismatch")
    for row in pit_events:
        descriptor = declared_datasets.get(row["datasetId"])
        if descriptor is None or descriptor["kind"] != "events":
            raise ResearchContractError("undeclared_event_dataset")
        expected_scope = "GOLDEN" if row["partition"] == "GOLDEN" \
            else "NON_GOLDEN"
        if descriptor["partitionScope"] != expected_scope:
            raise ResearchContractError(
                "event_dataset_partition_scope_mismatch")
    by_instrument = _bars_by_instrument(pit_bars)
    _validate_embargo_bar_sessions(
        by_instrument, contract["partitionPolicy"])
    turtle = turtle_shadow(pit_bars)
    turtle_dates = _turtle_entry_dates(pit_bars)

    evaluated = []
    counterfactuals = []
    excluded_counts = {"EMBARGO": 0, "OUT_OF_SCOPE": 0, "SEALED_GOLDEN": 0}
    for event in pit_events:
        partition = event["partition"]
        if partition is None:
            excluded_counts["OUT_OF_SCOPE"] += 1
            continue
        if partition == "EMBARGO":
            excluded_counts["EMBARGO"] += 1
            continue
        if partition == "GOLDEN" and contract["goldenPolicy"]["access"] != "OPEN":
            excluded_counts["SEALED_GOLDEN"] += 1
            continue
        rows = by_instrument.get(event["instrumentId"], [])
        scored = _event_metrics(event, rows, contract["horizons"],
                                contract["parameters"])
        evaluated.append(scored)
        counterfactuals.append(_counterfactual_for_event(
            event, rows, turtle_dates.get(event["instrumentId"], {}),
            contract["parameters"], contract["executionPolicy"],
            contract["costBps"], contract["slippageBps"]))

    retained_events, retained_counterfactuals = \
        _partition_priority_details(evaluated, counterfactuals)
    golden_expected_id = contract["goldenPolicy"]["expectedEventId"]
    golden_expected_instrument = contract["goldenPolicy"][
        "expectedInstrumentId"]
    golden_matches = [
        row for row in evaluated
        if row.get("partition") == "GOLDEN"
        and row.get("eventId") == golden_expected_id
        and row.get("instrumentId") == golden_expected_instrument
    ]
    golden_counterfactual = next((
        row for row in counterfactuals
        if row.get("eventId") == golden_expected_id), None)
    golden_risk_artifact = (
        golden_matches[0].get("riskKernelArtifact")
        if len(golden_matches) == 1 else None)
    golden_sho_artifact = (
        golden_matches[0].get("shoReversalArtifact")
        if len(golden_matches) == 1 else None)
    golden_fully_scored = bool(
        len(golden_matches) == 1
        and golden_matches[0].get("validatedReversal") is True
        and isinstance(golden_risk_artifact, dict)
        and isinstance(golden_sho_artifact, dict)
        and all(
            outcome.get("status") in {"OBSERVED", "AMBIGUOUS"}
            for outcome in golden_matches[0].get("horizons", {}).values()))
    golden_eligible = bool(
        golden_fully_scored and golden_counterfactual is not None
        and golden_counterfactual.get("status") == "EVALUATED")
    if contract["goldenPolicy"]["access"] == "OPEN" and not golden_eligible:
        raise ResearchContractError("golden_case_not_fully_evaluable")
    golden_acceptance = {
        "bandWalkEndingDetected": None,
        "bandWalkEndingFirstObservedDate": None,
        "evaluationStatus": "SEALED",
        "ma25ReclaimDetected": None,
        "macdGoldenCrossDetected": None,
        "riskKernelArtifactId": None,
        "riskOffFirstObservedDate": None,
        "riskOffSufficient": None,
        "sarFlipDetected": None,
        "shoReversalArtifactId": None,
        "vixDecreasingConfirmationDetected": None,
        "waitMissedOpportunityMeasured": None,
    }
    if golden_eligible:
        golden_event = golden_matches[0]
        risk_sufficient = golden_risk_artifact["constraint"] in {
            "REDUCE_RISK", "EXIT_RISK"}
        risk_date = golden_risk_artifact["asOf"][:10]
        band_factor = golden_sho_artifact["evidence"]["bandWalkEnding"]
        band_detected = band_factor["conditionMet"] is True
        band_date = band_factor["evidenceDate"]
        strategies = {
            row["strategy"]: row
            for row in golden_counterfactual.get("strategies", [])
        }
        golden_acceptance = {
            "bandWalkEndingDetected": band_detected,
            "bandWalkEndingFirstObservedDate": (
                band_date if band_detected else None),
            "evaluationStatus": "EVALUATED",
            "ma25ReclaimDetected": strategies.get(
                "BUY_ON_25MA_RECLAIM", {}).get("entryDate") is not None,
            "macdGoldenCrossDetected": strategies.get(
                "BUY_ON_MACD_GC", {}).get("entryDate") is not None,
            "riskKernelArtifactId": golden_risk_artifact["riskKernelId"],
            "riskOffFirstObservedDate": (
                risk_date if risk_sufficient else None),
            "riskOffSufficient": risk_sufficient,
            "sarFlipDetected": strategies.get(
                "BUY_ON_SAR_FLIP", {}).get("entryDate") is not None,
            "shoReversalArtifactId": golden_sho_artifact["artifactId"],
            "vixDecreasingConfirmationDetected": strategies.get(
                "BUY_ON_VIX_DC", {}).get("entryDate") is not None,
            "waitMissedOpportunityMeasured": strategies.get(
                "WAIT", {}).get("missedMfePct") is not None,
        }

    partitions = {}
    for name in ("DEVELOPMENT", "HOLDOUT", "GOLDEN"):
        members = [row for row in evaluated if row["partition"] == name]
        if name == "GOLDEN" and contract["goldenPolicy"]["access"] != "OPEN":
            partitions[name] = {
                "access": "SEALED", "eventCount": 0, "metrics": None,
            }
        else:
            partitions[name] = {
                "access": "OPEN", "eventCount": len(members),
                "metrics": _aggregate_events(members, contract["horizons"]),
            }
    partition_proofs = {}
    for name in ("DEVELOPMENT", "HOLDOUT", "GOLDEN"):
        members = [row for row in evaluated if row["partition"] == name]
        member_ids = {row["eventId"] for row in members}
        comparisons = [row for row in counterfactuals
                       if row["eventId"] in member_ids]
        retained_member_count = sum(
            1 for row in retained_events if row["partition"] == name)
        retained_comparison_count = sum(
            1 for row in retained_counterfactuals
            if row["eventId"] in member_ids)
        partition_proofs[name] = {
            "counterfactualCount": len(comparisons),
            "counterfactualDigest": sha256_hex(comparisons),
            "counterfactualsTruncated": (
                retained_comparison_count < len(comparisons)),
            "evaluatedCounterfactualCount": sum(
                1 for row in comparisons if row.get("status") == "EVALUATED"),
            "eventCount": len(members),
            "eventDetailsDigest": sha256_hex(members),
            "eventDetailsTruncated": retained_member_count < len(members),
            "retainedCounterfactualCount": retained_comparison_count,
            "retainedEventDetailCount": retained_member_count,
        }
    holdout_events = [row for row in evaluated
                      if row["partition"] == "HOLDOUT"]
    holdout_event_ids = {row["eventId"] for row in holdout_events}
    holdout_counterfactuals = [
        row for row in counterfactuals
        if row["eventId"] in holdout_event_ids]
    non_golden_bars = [
        row for row in pit_bars
        if partition_for_date(
            row["date"], contract["partitionPolicy"]) != "GOLDEN"]
    non_golden_events = [
        row for row in pit_events if row["partition"] != "GOLDEN"]
    holdout_digest = sha256_hex({
        "counterfactualDigest": partition_proofs["HOLDOUT"][
            "counterfactualDigest"],
        "eventDetailsDigest": partition_proofs["HOLDOUT"][
            "eventDetailsDigest"],
        "inputHash": sha256_hex({
            "bars": non_golden_bars,
            "events": non_golden_events,
        }),
        "latestInputKnownAt": max(
            [row["effectiveKnownAt"] for row in non_golden_bars]
            + [row["availableFrom"] for row in non_golden_events]),
        "metrics": partitions["HOLDOUT"],
    })
    holdout_metrics = partitions["HOLDOUT"]["metrics"]
    fully_scored_horizons = [
        horizon for horizon in contract["horizons"]
        if holdout_metrics[str(horizon)]["scoreableCount"] > 0]
    holdout_eligible = bool(holdout_events) and \
        fully_scored_horizons == contract["horizons"] and \
        partition_proofs["HOLDOUT"]["counterfactualCount"] == \
        len(holdout_events) and \
        partition_proofs["HOLDOUT"]["evaluatedCounterfactualCount"] == \
        len(holdout_events)
    holdout_proof = {
        "counterfactualDigest": partition_proofs["HOLDOUT"][
            "counterfactualDigest"],
        "eligibleForPass": holdout_eligible,
        "evaluatedCounterfactualCount": partition_proofs["HOLDOUT"][
            "evaluatedCounterfactualCount"],
        "eventCount": len(holdout_events),
        "eventDetailsDigest": partition_proofs["HOLDOUT"][
            "eventDetailsDigest"],
        "fullyScoredHorizons": fully_scored_horizons,
        "inputHash": sha256_hex({
            "bars": non_golden_bars,
            "events": non_golden_events,
        }),
        "latestInputKnownAt": max(
            [row["effectiveKnownAt"] for row in non_golden_bars]
            + [row["availableFrom"] for row in non_golden_events]),
        "resultDigest": holdout_digest,
    }
    recorded_holdout_digest = contract["freeze"]["holdoutResultDigest"]
    if contract["freeze"]["holdoutStatus"] != "UNTOUCHED" and \
            recorded_holdout_digest != holdout_digest:
        raise ResearchContractError("recorded_holdout_digest_mismatch")
    body = {
        "artifactType": "offline_research_summary",
        "counterfactuals": {
            "assumptions": {
                "costBps": contract["costBps"],
                "executionPolicy": contract["executionPolicy"],
                "roundTripCostAndSlippagePct": _round(
                    2.0 * (contract["costBps"] + contract["slippageBps"])
                    / 100.0),
                "slippageBps": contract["slippageBps"],
            },
            "ownerPnl": False,
            "perEvent": retained_counterfactuals,
            "perEventTruncated": len(counterfactuals) > len(
                retained_counterfactuals),
            "strategies": _counterfactual_summary(counterfactuals),
        },
        "coverage": {
            "barCount": len(pit_bars),
            "eventCount": len(pit_events),
            "excludedEventCounts": excluded_counts,
            "instruments": sorted(by_instrument),
        },
        "dataIdentity": {
            "barDatasetHash": bar_proof["datasetHash"],
            "declaredDatasets": contract["datasets"],
            "eventHash": event_proof["eventHash"],
        },
        "eventDetails": retained_events,
        "eventDetailsTruncated": len(evaluated) > len(retained_events),
        "goldenCase": {
            "acceptanceChecks": golden_acceptance,
            "access": contract["goldenPolicy"]["access"],
            "caseId": contract["goldenPolicy"]["caseId"],
            "eligible": golden_eligible,
            "evaluatedEventCount": sum(
                1 for row in evaluated if row["partition"] == "GOLDEN"),
            "expectedEventId": golden_expected_id,
            "expectedInstrumentId": golden_expected_instrument,
            "fullyScoredHorizons": (
                contract["horizons"] if golden_fully_scored else []),
            "openedForPolicyIdentity": contract["goldenPolicy"][
                "openedForPolicyIdentity"],
            "openedForResearchDataIdentity": contract["goldenPolicy"][
                "openedForResearchDataIdentity"],
        },
        "holdoutProof": holdout_proof,
        "holdoutResultDigest": holdout_digest,
        "identity": {
            "buildSha": contract["buildSha"],
            "calendarVersion": contract["calendarVersion"],
            "informationCutoffAt": contract["informationCutoffAt"],
            "policyIdentity": contract["policyIdentity"],
            "researchDataIdentity": contract["researchDataIdentity"],
            "researchIdentity": contract["researchIdentity"],
        },
        "manifestContract": _manifest_document(contract),
        "partitions": partitions,
        "partitionProofs": partition_proofs,
        "pointInTimeProof": {
            "bars": bar_proof, "events": event_proof,
            "futureInputAdmitted": False,
        },
        "schemaVersion": RESULT_SCHEMA,
        "turtleShadow": turtle,
        "validationProtocol": {
            "embargoSessions": contract["partitionPolicy"]["embargoSessions"],
            "horizons": contract["horizons"],
            "holdoutStatusAtRun": contract["freeze"]["holdoutStatus"],
            "policyFrozen": contract["freeze"]["status"] == "FROZEN",
            "walkForward": _fold_summary(
                evaluated, contract["partitionPolicy"]["walkForwardFolds"],
                contract["horizons"]),
        },
    }
    digest = sha256_hex(body)
    artifact = dict(body)
    artifact["artifactDigest"] = digest
    artifact["artifactId"] = "ra-" + digest[:32]
    raw = canonical_bytes(artifact)
    if len(raw) > MAX_ARTIFACT_BYTES:
        raise ResearchContractError("research_artifact_too_large")
    return artifact


def build_verified_research_artifact(
        manifest: Mapping[str, Any],
        dataset_payloads: Mapping[str, bytes]) -> Dict[str, Any]:
    """Build from exact hash-verified raw dataset bytes, never caller rows."""
    contract = validate_manifest(manifest)
    if not isinstance(dataset_payloads, Mapping) or any(
            not isinstance(key, str) or not isinstance(value, bytes)
            for key, value in dataset_payloads.items()):
        raise ResearchContractError("invalid_dataset_payloads")
    golden_open = contract["goldenPolicy"]["access"] == "OPEN"
    verified_descriptors = [
        row for row in contract["datasets"]
        if golden_open or row["partitionScope"] != "GOLDEN"]
    expected_ids = {row["datasetId"] for row in verified_descriptors}
    if set(dataset_payloads) != expected_ids:
        raise ResearchContractError("dataset_payload_set_mismatch")
    bars: List[Dict[str, Any]] = []
    events: List[Dict[str, Any]] = []
    receipts = []
    total_bytes = 0
    for descriptor in verified_descriptors:
        raw = dataset_payloads[descriptor["datasetId"]]
        total_bytes += len(raw)
        if total_bytes > MAX_TOTAL_DATASET_BYTES:
            raise ResearchContractError("total_dataset_byte_bound_exceeded")
        digest = sha256_hex(raw)
        if digest != descriptor["sha256"]:
            raise ResearchContractError("dataset_sha256_mismatch")
        rows = _decode_dataset_payload(descriptor, raw)
        target = bars if descriptor["kind"] == "bars" else events
        target.extend(rows)
        receipts.append({
            "bytes": len(raw),
            "datasetId": descriptor["datasetId"],
            "kind": descriptor["kind"],
            "partitionScope": descriptor["partitionScope"],
            "rowCount": len(rows),
            "sha256": digest,
        })
    if not bars:
        raise ResearchContractError("bars_dataset_required")
    if len(bars) > MAX_BARS or len(events) > MAX_EVENTS:
        raise ResearchContractError("dataset_row_bound_exceeded")
    unbound = build_research_artifact(manifest, bars, events)
    sealed_commitments = [{
        "datasetId": row["datasetId"],
        "kind": row["kind"],
        "partitionScope": row["partitionScope"],
        "sha256": row["sha256"],
    } for row in contract["datasets"]
        if not golden_open and row["partitionScope"] == "GOLDEN"]
    receipt = {
        "authority": "HASH_VERIFIED_OFFLINE_INPUT",
        "barDatasetHash": unbound["dataIdentity"]["barDatasetHash"],
        "datasetCount": len(receipts),
        "datasets": receipts,
        "eventHash": unbound["dataIdentity"]["eventHash"],
        "schemaVersion": INPUT_RECEIPT_SCHEMA,
        "sealedCommitments": sealed_commitments,
        "totalBytes": total_bytes,
    }
    return bind_input_receipt(
        unbound, receipt, _authority=_RAW_INPUT_AUTHORITY)


def _input_receipt_valid(receipt: Any, artifact: Mapping[str, Any]) -> bool:
    if not isinstance(receipt, dict) or set(receipt) != {
            "authority", "barDatasetHash", "datasetCount", "datasets",
            "eventHash", "schemaVersion", "sealedCommitments",
            "totalBytes"} or \
            receipt.get("schemaVersion") != INPUT_RECEIPT_SCHEMA or \
            receipt.get("authority") != "HASH_VERIFIED_OFFLINE_INPUT":
        return False
    datasets = receipt.get("datasets")
    if not isinstance(datasets, list) or len(datasets) > MAX_DATASETS or \
            isinstance(receipt.get("datasetCount"), bool) or \
            receipt.get("datasetCount") != len(datasets):
        return False
    declared = artifact.get("dataIdentity", {}).get("declaredDatasets")
    golden_open = artifact.get("goldenCase", {}).get("access") == "OPEN"
    expected_verified = [
        row for row in declared or [] if isinstance(row, dict)
        and (golden_open or row.get("partitionScope") != "GOLDEN")]
    expected_sealed = [
        row for row in declared or [] if isinstance(row, dict)
        and not golden_open and row.get("partitionScope") == "GOLDEN"]
    declared_keys = [(
        row.get("datasetId"), row.get("kind"),
        row.get("partitionScope"), row.get("sha256"))
        for row in expected_verified]
    receipt_keys = []
    total_bytes = 0
    row_counts = {"bars": 0, "events": 0}
    for row in datasets:
        if not isinstance(row, dict) or set(row) != {
                "bytes", "datasetId", "kind", "partitionScope",
                "rowCount", "sha256"} or \
                row.get("kind") not in row_counts or \
                row.get("partitionScope") not in {
                    "NON_GOLDEN", "GOLDEN"} or \
                not isinstance(row.get("bytes"), int) or \
                isinstance(row.get("bytes"), bool) or row["bytes"] < 0 or \
                not isinstance(row.get("rowCount"), int) or \
                isinstance(row.get("rowCount"), bool) or \
                row["rowCount"] < 0 or \
                not isinstance(row.get("sha256"), str) or \
                not _is_digest(row["sha256"]):
            return False
        receipt_keys.append((
            row["datasetId"], row["kind"], row["partitionScope"],
            row["sha256"]))
        total_bytes += row["bytes"]
        row_counts[row["kind"]] += row["rowCount"]
    pit = artifact.get("pointInTimeProof") or {}
    bars_proof = pit.get("bars") or {}
    events_proof = pit.get("events") or {}
    sealed = receipt.get("sealedCommitments")
    expected_sealed_keys = [(
        row.get("datasetId"), row.get("kind"),
        row.get("partitionScope"), row.get("sha256"))
        for row in expected_sealed]
    if not isinstance(sealed, list) or len(sealed) > MAX_DATASETS:
        return False
    sealed_keys = []
    for row in sealed:
        if not isinstance(row, dict) or set(row) != {
                "datasetId", "kind", "partitionScope", "sha256"} or \
                row.get("kind") not in row_counts or \
                row.get("partitionScope") != "GOLDEN" or \
                not isinstance(row.get("sha256"), str) or \
                not _is_digest(row["sha256"]):
            return False
        sealed_keys.append((
            row.get("datasetId"), row.get("kind"),
            row.get("partitionScope"), row.get("sha256")))
    return bool(
        receipt_keys == declared_keys
        and sealed_keys == expected_sealed_keys
        and receipt.get("totalBytes") == total_bytes
        and row_counts["bars"] == bars_proof.get("sourceRowCount")
        and row_counts["events"] == events_proof.get("sourceEventCount")
        and receipt.get("barDatasetHash") == artifact.get(
            "dataIdentity", {}).get("barDatasetHash")
        and receipt.get("eventHash") == artifact.get(
            "dataIdentity", {}).get("eventHash"))


def bind_input_receipt(artifact: Mapping[str, Any],
                       receipt: Mapping[str, Any], *,
                       _authority: object = None) -> Dict[str, Any]:
    if _authority is not _RAW_INPUT_AUTHORITY:
        raise ResearchContractError("raw_input_verification_required")
    if not isinstance(artifact, Mapping) or "inputReceipt" in artifact:
        raise ResearchContractError("invalid_unbound_research_artifact")
    result = _copy_json(artifact)
    result.pop("artifactDigest", None)
    result.pop("artifactId", None)
    result["inputReceipt"] = _copy_json(receipt)
    if not _input_receipt_valid(result["inputReceipt"], result):
        raise ResearchContractError("invalid_research_input_receipt")
    identity = result.get("identity")
    if not isinstance(identity, dict) or "inputIdentity" in identity:
        raise ResearchContractError("invalid_unbound_research_identity")
    identity["inputIdentity"] = "ri-" + sha256_hex({
        "inputReceipt": result["inputReceipt"],
        "researchIdentity": identity.get("researchIdentity"),
    })
    digest = sha256_hex(result)
    result["artifactDigest"] = digest
    result["artifactId"] = "ra-" + digest[:32]
    if not verify_research_artifact(result):
        raise ResearchContractError("bound_artifact_verification_failed")
    return result


def verify_research_artifact(value: Any) -> bool:
    required = {
        "artifactDigest", "artifactId", "artifactType", "counterfactuals",
        "coverage", "dataIdentity", "eventDetails", "eventDetailsTruncated",
        "goldenCase", "holdoutProof", "holdoutResultDigest", "identity",
        "manifestContract", "partitionProofs", "partitions", "pointInTimeProof",
        "schemaVersion", "turtleShadow", "validationProtocol",
    }
    required.add("inputReceipt")
    if not isinstance(value, dict) or set(value) != required:
        return False
    if value.get("schemaVersion") != RESULT_SCHEMA or \
            value.get("artifactType") != "offline_research_summary":
        return False
    try:
        def exact_digest(item: Any, prefix: str = "", length: int = 64) -> bool:
            if not isinstance(item, str):
                return False
            payload = item[len(prefix):] if prefix and item.startswith(prefix) \
                else item if not prefix else ""
            return len(payload) == length and all(ch in _HEX64 for ch in payload)

        def count(item: Any) -> bool:
            return isinstance(item, int) and not isinstance(item, bool) and item >= 0

        def canonical_time(item: Any) -> bool:
            if not isinstance(item, str):
                return False
            parsed = _timestamp(item, "artifact_timestamp")
            return parsed.isoformat().replace("+00:00", "Z") == item

        def finite_number(item: Any) -> bool:
            return isinstance(item, (int, float)) and \
                not isinstance(item, bool) and math.isfinite(float(item))

        def optional_number(item: Any) -> bool:
            return item is None or finite_number(item)

        def optional_count(item: Any) -> bool:
            return item is None or count(item)

        def bounded_rate(item: Any) -> bool:
            return item is None or (finite_number(item) and 0 <= item <= 1)

        outcome_keys = {
            "ambiguousTargetInvalidation", "brier", "endReturnPct",
            "falsePositive", "falseRally", "falseReversal",
            "invalidationHit", "logLoss", "maePct", "maxDrawdownPct",
            "mfePct", "missedOpportunity", "newLow", "outcomeDate",
            "probability", "rally", "reversal", "status", "targetBreak",
            "targetHit", "timeToInvalidationSessions",
            "timeToTargetSessions",
        }

        def valid_outcome(item: Any) -> bool:
            if not isinstance(item, dict):
                return False
            if set(item) == {"status"}:
                return item["status"] in {
                    "UNSCORABLE_INCOMPLETE_PATH",
                    "UNSCORABLE_STAGE_BOUNDARY"}
            if set(item) != outcome_keys or item.get("status") not in {
                    "OBSERVED", "AMBIGUOUS"}:
                return False
            boolean_keys = {
                "ambiguousTargetInvalidation", "falsePositive",
                "falseRally", "falseReversal", "invalidationHit",
                "missedOpportunity", "newLow", "rally", "reversal",
                "targetBreak", "targetHit",
            }
            return bool(
                all(isinstance(item[key], bool) for key in boolean_keys)
                and all(optional_number(item[key]) for key in (
                    "brier", "endReturnPct", "logLoss", "maePct",
                    "maxDrawdownPct", "mfePct"))
                and bounded_rate(item["probability"])
                and isinstance(item["outcomeDate"], str)
                and _date(item["outcomeDate"], "artifact_outcome_date")
                and optional_count(item["timeToInvalidationSessions"])
                and optional_count(item["timeToTargetSessions"]))

        event_keys = {
            "ablationTags", "availableFrom", "datasetId",
            "counterfactualSessionDates", "decisionCutoffAt", "eventId",
            "evidenceRefs",
            "expectedDirection", "horizons", "instrumentId",
            "invalidationPct", "partition", "regime", "signalDate",
            "riskKernelArtifact", "shoReversalArtifact", "status",
            "targetPct", "validatedReversal",
        }

        def valid_event_detail(item: Any, horizon_keys: set) -> bool:
            if not isinstance(item, dict) or set(item) != event_keys or \
                    item.get("partition") not in {
                        "DEVELOPMENT", "HOLDOUT", "GOLDEN"} or \
                    not isinstance(item.get("eventId"), str) or \
                    not isinstance(item.get("datasetId"), str) or \
                    not isinstance(item.get("instrumentId"), str) or \
                    item.get("expectedDirection") not in {"UP", "DOWN"} or \
                    not finite_number(item.get("targetPct")) or \
                    item["targetPct"] <= 0 or \
                    not finite_number(item.get("invalidationPct")) or \
                    item["invalidationPct"] >= 0 or \
                    not isinstance(item.get("validatedReversal"), bool) or \
                    not isinstance(item.get("regime"), str) or \
                    not isinstance(item.get("ablationTags"), list) or \
                    not all(isinstance(row, str)
                            for row in item["ablationTags"]) or \
                    not isinstance(item.get("evidenceRefs"), list) or \
                    not all(isinstance(row, str)
                            for row in item["evidenceRefs"]) or \
                    not canonical_time(item.get("availableFrom")) or \
                    not canonical_time(item.get("decisionCutoffAt")) or \
                    not isinstance(item.get("signalDate"), str):
                return False
            session_dates = item.get("counterfactualSessionDates")
            max_session_count = max(
                max(contract["horizons"]),
                contract["parameters"]["counterfactualHorizon"]) + 1
            if not isinstance(session_dates, list) or \
                    len(session_dates) > max_session_count or \
                    session_dates != sorted(set(session_dates)) or \
                    not all(isinstance(row, str) for row in session_dates):
                return False
            for row in session_dates:
                _date(row, "artifact_counterfactual_session_date")
            signal_date = _date(
                item["signalDate"], "artifact_signal_date").isoformat()
            available = _timestamp(
                item["availableFrom"], "artifact_event_available")
            decision_cutoff = _timestamp(
                item["decisionCutoffAt"], "artifact_event_decision_cutoff")
            descriptor = next((
                row for row in contract["datasets"]
                if row["datasetId"] == item["datasetId"]), None)
            expected_scope = "GOLDEN" if item["partition"] == "GOLDEN" \
                else "NON_GOLDEN"
            if available > decision_cutoff or \
                    decision_cutoff > _timestamp(
                        contract["informationCutoffAt"],
                        "artifact_information_cutoff") or \
                    decision_cutoff.date().isoformat() != signal_date or \
                    partition_for_date(signal_date,
                                       contract["partitionPolicy"]) != \
                    item["partition"] or descriptor is None or \
                    descriptor["kind"] != "events" or \
                    descriptor["partitionScope"] != expected_scope:
                return False
            risk_artifact = _golden_risk_kernel(
                item.get("riskKernelArtifact"),
                instrument=item["instrumentId"],
                event_cutoff=decision_cutoff)
            sho_artifact = _golden_sho_reversal(
                item.get("shoReversalArtifact"),
                instrument=item["instrumentId"],
                event_cutoff=decision_cutoff)
            if item["partition"] == "GOLDEN":
                if risk_artifact is None or sho_artifact is None:
                    return False
            elif risk_artifact is not None or sho_artifact is not None:
                return False
            horizons_value = item.get("horizons")
            if item.get("status") == "UNSCORABLE_SIGNAL_BAR_MISSING":
                return horizons_value == {} and session_dates == []
            return bool(item.get("status") == "EVALUATED"
                        and session_dates
                        and session_dates[0] == signal_date
                        and isinstance(horizons_value, dict)
                        and set(horizons_value) == horizon_keys
                        and all(valid_outcome(row)
                                for row in horizons_value.values()))

        buy_strategy_keys = {
            "avoidedMaePct", "delaySessions", "entryDate", "entryPrice",
            "exitDate", "exitRule", "failure", "foregoneReturnPct",
            "invalidationHit", "maePct", "maxDrawdownPct", "mfePct",
            "missedMfePct", "ownerPnl", "strategy", "targetHit",
            "terminalReturnPct", "terminalStatus", "timeToTargetSessions",
        }
        wait_strategy_keys = (buy_strategy_keys - {"exitDate", "exitRule"}) | {
            "cashReturnAssumptionPct"}

        def valid_strategy(item: Any) -> bool:
            if not isinstance(item, dict) or item.get("strategy") not in \
                    COUNTERFACTUAL_STRATEGIES or \
                    item.get("ownerPnl") is not False or \
                    not isinstance(item.get("failure"), bool):
                return False
            expected = wait_strategy_keys if item["strategy"] == "WAIT" \
                else buy_strategy_keys
            if set(item) != expected:
                return False
            bool_or_none = (bool, type(None))
            if not bool(
                all(optional_number(item[key]) for key in (
                    "avoidedMaePct", "entryPrice",
                    "foregoneReturnPct", "maePct", "maxDrawdownPct",
                    "mfePct", "missedMfePct", "terminalReturnPct",
                    "timeToTargetSessions"))
                and optional_count(item["delaySessions"])
                and isinstance(item["invalidationHit"], bool_or_none)
                and isinstance(item["targetHit"], bool_or_none)
                and (item["entryDate"] is None or
                     isinstance(item["entryDate"], str))
                and isinstance(item["terminalStatus"], str)
                and (item["strategy"] != "WAIT" or
                     item["cashReturnAssumptionPct"] == 0.0)):
                return False
            if item["entryDate"] is not None:
                _date(item["entryDate"], "artifact_strategy_entry_date")
            exit_date = item.get("exitDate")
            exit_rule = item.get("exitRule")
            if (exit_date is None) != (exit_rule is None):
                return False
            if exit_date is not None:
                _date(exit_date, "artifact_strategy_exit_date")
                if item["strategy"] != "BUY_ON_TURTLE_CONFIRMATION" or \
                        exit_rule not in {
                            "10_DAY_LOW_EXIT", "20_DAY_LOW_EXIT"} or \
                        exit_date <= item["entryDate"] or \
                        item["terminalStatus"] != exit_rule:
                    return False
            if item["strategy"] == "WAIT":
                return item["entryDate"] is None and \
                    item["delaySessions"] is None and \
                    item["terminalStatus"] in {
                        "MISSED_VALIDATED_REVERSAL", "WAITED_IN_CASH"}
            if item["entryDate"] is None:
                return item["delaySessions"] is None and \
                    item["terminalStatus"] == "NO_TRIGGER" and \
                    exit_date is None
            return bool(item["delaySessions"] is not None
                        and item["delaySessions"] >= 1
                        and finite_number(item["entryPrice"])
                        and item["entryPrice"] > 0
                        and (exit_rule is not None or
                             item["terminalStatus"] in {
                                 "ENTERED", "AMBIGUOUS"}))

        def valid_counterfactual(item: Any) -> bool:
            if not isinstance(item, dict) or \
                    not isinstance(item.get("eventId"), str):
                return False
            if item.get("status") in {
                    "UNSCORABLE_INCOMPLETE_PATH", "UNSCORABLE_BUY_NOW"}:
                return set(item) == {"eventId", "status", "strategies"} and \
                    item.get("strategies") == []
            strategies = item.get("strategies")
            return bool(set(item) == {
                "eventId", "horizonSessions", "ownerPnl", "status",
                "strategies"}
                and item.get("status") == "EVALUATED"
                and item.get("ownerPnl") is False
                and count(item.get("horizonSessions"))
                and isinstance(strategies, list)
                and [row.get("strategy") for row in strategies
                     if isinstance(row, dict)] ==
                    list(COUNTERFACTUAL_STRATEGIES)
                and all(valid_strategy(row) for row in strategies))

        metric_keys = {
            "ablations", "ambiguousCount", "brierMean", "calibration",
            "falsePositiveRate", "falseRallyRate", "falseReversalRate",
            "logLossMean", "maeMeanPct", "maxDrawdownMeanPct",
            "medianReturnPct", "mfeMeanPct", "missedOpportunityRate",
            "newLowRate", "rallyRate", "regimes", "returnMeanPct",
            "reversalRate", "sampleCount", "scoreableCount",
            "targetBreakRate", "targetHitRate",
            "timeToTargetMedianSessions", "unscorableCount", "winRate",
            "winRateCi95Wilson",
        }

        def valid_metric(item: Any) -> bool:
            if not isinstance(item, dict) or set(item) != metric_keys or \
                    not all(count(item.get(key)) for key in (
                        "ambiguousCount", "sampleCount", "scoreableCount",
                        "unscorableCount")) or \
                    item["sampleCount"] != item["scoreableCount"] + \
                    item["unscorableCount"] or \
                    item["ambiguousCount"] > item["scoreableCount"]:
                return False
            rate_keys = {
                "falsePositiveRate", "falseRallyRate",
                "falseReversalRate", "missedOpportunityRate", "newLowRate",
                "rallyRate", "reversalRate", "targetBreakRate",
                "targetHitRate", "winRate"}
            number_keys = {
                "brierMean", "logLossMean", "maeMeanPct",
                "maxDrawdownMeanPct", "medianReturnPct", "mfeMeanPct",
                "returnMeanPct", "timeToTargetMedianSessions"}
            if not all(bounded_rate(item[key]) for key in rate_keys) or \
                    not all(optional_number(item[key]) for key in number_keys):
                return False
            interval = item.get("winRateCi95Wilson")
            if interval is not None and (
                    not isinstance(interval, list) or len(interval) != 2 or
                    not all(finite_number(row) and 0 <= row <= 1
                            for row in interval) or interval[0] > interval[1]):
                return False
            calibration = item.get("calibration")
            if not isinstance(calibration, dict) or set(calibration) != {
                    "bins", "ece", "sampleCount"} or \
                    not count(calibration.get("sampleCount")) or \
                    calibration["sampleCount"] > item["scoreableCount"] or \
                    not bounded_rate(calibration.get("ece")) or \
                    not isinstance(calibration.get("bins"), list):
                return False
            for row in calibration["bins"]:
                if not isinstance(row, dict) or set(row) != {
                        "count", "forecastMean", "lower", "observedRate",
                        "upper"} or not count(row.get("count")) or \
                        row["count"] <= 0 or \
                        not all(bounded_rate(row.get(key)) for key in (
                            "forecastMean", "lower", "observedRate",
                            "upper")) or row["lower"] > row["upper"]:
                    return False
            regimes = item.get("regimes")
            ablations = item.get("ablations")
            if not isinstance(regimes, list) or not isinstance(
                    ablations, list) or len(ablations) > 32:
                return False
            if not all(isinstance(row, dict) and set(row) == {
                    "meanReturnPct", "regime", "sampleCount"}
                    and isinstance(row.get("regime"), str)
                    and count(row.get("sampleCount"))
                    and optional_number(row.get("meanReturnPct"))
                    for row in regimes):
                return False
            return all(isinstance(row, dict) and set(row) == {
                "meanReturnPct", "sampleCount", "tag"}
                and isinstance(row.get("tag"), str)
                and count(row.get("sampleCount"))
                and optional_number(row.get("meanReturnPct"))
                for row in ablations)

        manifest_contract = value.get("manifestContract")
        if not isinstance(manifest_contract, dict) or \
                set(manifest_contract) != MANIFEST_FIELDS:
            return False
        contract = validate_manifest(manifest_contract)
        if _manifest_document(contract) != manifest_contract:
            return False

        identity = value.get("identity")
        if not isinstance(identity, dict) or set(identity) != {
                "buildSha", "calendarVersion", "informationCutoffAt",
                "inputIdentity", "policyIdentity", "researchDataIdentity",
                "researchIdentity"} or \
                not exact_digest(identity.get("buildSha"), length=40) or \
                not exact_digest(identity.get("inputIdentity"), "ri-") or \
                not exact_digest(identity.get("policyIdentity"), "rp-") or \
                not exact_digest(
                    identity.get("researchDataIdentity"), "rd-") or \
                not exact_digest(identity.get("researchIdentity"), "rr-") or \
                not isinstance(identity.get("calendarVersion"), str) or \
                not canonical_time(identity.get("informationCutoffAt")):
            return False
        expected_input_identity = "ri-" + sha256_hex({
            "inputReceipt": value.get("inputReceipt"),
            "researchIdentity": identity["researchIdentity"],
        })
        if identity["inputIdentity"] != expected_input_identity:
            return False
        if identity != {
                "buildSha": contract["buildSha"],
                "calendarVersion": contract["calendarVersion"],
                "informationCutoffAt": contract["informationCutoffAt"],
                "inputIdentity": identity["inputIdentity"],
                "policyIdentity": contract["policyIdentity"],
                "researchDataIdentity": contract["researchDataIdentity"],
                "researchIdentity": contract["researchIdentity"],
        }:
            return False

        protocol = value.get("validationProtocol")
        if not isinstance(protocol, dict) or set(protocol) != {
                "embargoSessions", "horizons", "holdoutStatusAtRun",
                "policyFrozen", "walkForward"}:
            return False
        horizons = protocol.get("horizons")
        if tuple(horizons or ()) not in (
                BASE_HORIZONS, BASE_HORIZONS + (OPTIONAL_HORIZON,)) or \
                not count(protocol.get("embargoSessions")) or \
                protocol["embargoSessions"] < max(horizons) or \
                protocol.get("holdoutStatusAtRun") not in {
                    "UNTOUCHED", "PASSED", "FAILED"} or \
                not isinstance(protocol.get("policyFrozen"), bool) or \
                not isinstance(protocol.get("walkForward"), list):
            return False
        if protocol["policyFrozen"] is False and \
                protocol["holdoutStatusAtRun"] != "UNTOUCHED":
            return False
        if protocol["horizons"] != contract["horizons"] or \
                protocol["embargoSessions"] != contract[
                    "partitionPolicy"]["embargoSessions"] or \
                protocol["policyFrozen"] is not (
                    contract["freeze"]["status"] == "FROZEN") or \
                protocol["holdoutStatusAtRun"] != contract[
                    "freeze"]["holdoutStatus"]:
            return False
        folds = protocol["walkForward"]
        expected_folds = contract["partitionPolicy"]["walkForwardFolds"]
        if [row.get("foldId") for row in folds if isinstance(row, dict)] != \
                [row["foldId"] for row in expected_folds]:
            return False
        for fold in folds:
            if not isinstance(fold, dict) or set(fold) != {
                    "foldId", "stages"} or \
                    not isinstance(fold.get("stages"), dict) or \
                    set(fold["stages"]) != {"TRAIN", "VALIDATION", "FORWARD"}:
                return False
            for name, stage in fold["stages"].items():
                if not isinstance(stage, dict) or set(stage) != {
                        "eventCount", "metrics"} or \
                        not count(stage.get("eventCount")):
                    return False
                if name == "TRAIN":
                    if stage["metrics"] is not None:
                        return False
                elif not isinstance(stage["metrics"], dict) or \
                        set(stage["metrics"]) != {
                            str(row) for row in contract["horizons"]} or \
                        not all(valid_metric(row)
                                for row in stage["metrics"].values()):
                    return False

        expected_horizon_keys = {str(item) for item in contract["horizons"]}
        details = value.get("eventDetails")
        counter = value.get("counterfactuals")
        turtle = value.get("turtleShadow")
        if not isinstance(details, list) or len(details) > MAX_EVENT_DETAILS or \
                not isinstance(value.get("eventDetailsTruncated"), bool) or \
                not all(valid_event_detail(row, expected_horizon_keys)
                        for row in details) or \
                len({row["eventId"] for row in details}) != len(details) or \
                not isinstance(counter, dict) or set(counter) != {
                    "assumptions", "ownerPnl", "perEvent",
                    "perEventTruncated", "strategies"} or \
                counter.get("ownerPnl") is not False or \
                not isinstance(counter.get("perEventTruncated"), bool) or \
                not isinstance(counter.get("perEvent"), list) or \
                len(counter["perEvent"]) > MAX_EVENT_DETAILS or \
                not all(valid_counterfactual(row)
                        for row in counter["perEvent"]):
            return False
        if not value["eventDetailsTruncated"] and \
                protocol["walkForward"] != _fold_summary(
                    details, contract["partitionPolicy"][
                        "walkForwardFolds"], horizons):
            return False
        event_by_id = {row["eventId"]: row for row in details}
        counter_by_id = {row["eventId"]: row for row in counter["perEvent"]}
        if set(event_by_id) != set(counter_by_id):
            return False
        parameters = contract["parameters"]
        for event in details:
            session_dates = event["counterfactualSessionDates"]
            for horizon_text, outcome in event["horizons"].items():
                if outcome.get("status") not in {"OBSERVED", "AMBIGUOUS"}:
                    continue
                horizon = int(horizon_text)
                probability = outcome["probability"]
                positive = 1.0 if outcome["endReturnPct"] > 0 else 0.0
                bounded_probability = (
                    None if probability is None else
                    max(1e-12, min(1.0 - 1e-12, probability)))
                expected_brier = (
                    None if probability is None else
                    _round((probability - positive) ** 2))
                expected_log_loss = (
                    None if bounded_probability is None else _round(-(
                        positive * math.log(bounded_probability)
                        + (1.0 - positive)
                        * math.log(1.0 - bounded_probability))))
                false_positive = bool(
                    outcome["endReturnPct"] <= 0
                    or outcome["invalidationHit"])
                if outcome["status"] != (
                        "AMBIGUOUS" if outcome[
                            "ambiguousTargetInvalidation"] else "OBSERVED") or \
                        outcome["falsePositive"] is not false_positive or \
                        outcome["invalidationHit"] is not (
                            outcome["timeToInvalidationSessions"] is not None) or \
                        outcome["targetHit"] is not (
                            outcome["timeToTargetSessions"] is not None) or \
                        outcome["rally"] is not (
                            outcome["mfePct"] >= parameters[
                                "rallyThresholdPct"]) or \
                        outcome["missedOpportunity"] is not (
                            outcome["mfePct"] >= parameters[
                                "waitFailureThresholdPct"]) or \
                        outcome["reversal"] is not (
                            outcome["maePct"] <= -parameters[
                                "reversalThresholdPct"]
                            and outcome["endReturnPct"] > 0) or \
                        outcome["falseRally"] is not (
                            outcome["rally"] and false_positive) or \
                        outcome["falseReversal"] is not (
                            event["validatedReversal"] and false_positive) or \
                        outcome["brier"] != expected_brier or \
                        outcome["logLoss"] != expected_log_loss or \
                        len(session_dates) <= horizon or \
                        outcome["outcomeDate"] != session_dates[horizon]:
                    return False
        for event_id, comparison in counter_by_id.items():
            event = event_by_id[event_id]
            if comparison.get("status") != "EVALUATED":
                continue
            if comparison.get("horizonSessions") != contract[
                    "parameters"]["counterfactualHorizon"]:
                return False
            session_dates = event["counterfactualSessionDates"]
            if len(session_dates) < comparison["horizonSessions"] + 1:
                return False
            comparison_dates = session_dates[
                :comparison["horizonSessions"] + 1]
            strategies_by_name = {
                row["strategy"]: row for row in comparison["strategies"]
            }
            for strategy, row in strategies_by_name.items():
                entry_date = row.get("entryDate")
                if strategy == "WAIT":
                    if row["failure"] and not event["validatedReversal"]:
                        return False
                    continue
                if entry_date is not None and (
                        entry_date <= event["signalDate"] or
                        row.get("delaySessions") is None or
                        row["delaySessions"] < 1 or
                        row["delaySessions"] >= len(comparison_dates) or
                        entry_date != comparison_dates[
                            row["delaySessions"]]):
                    return False
                if strategy == "BUY_NOW" and (
                        entry_date is None or row.get("delaySessions") != 1):
                    return False
                exit_date = row.get("exitDate")
                if exit_date is not None and (
                        exit_date not in comparison_dates or
                        comparison_dates.index(exit_date) <=
                        row["delaySessions"]):
                    return False
        strategy_summary_keys = {
            "evaluatedCount", "failureCount", "meanAvoidedMaePct",
            "meanDelaySessions", "meanForegoneReturnPct", "meanMaePct",
            "meanMaxDrawdownPct", "meanMfePct", "meanMissedMfePct",
            "meanTerminalReturnPct", "ownerPnl", "strategy"}
        summaries = counter.get("strategies")
        if not isinstance(summaries, list) or \
                [row.get("strategy") for row in summaries
                 if isinstance(row, dict)] != \
                list(COUNTERFACTUAL_STRATEGIES):
            return False
        for row in summaries:
            if not isinstance(row, dict) or set(row) != \
                    strategy_summary_keys or row.get("ownerPnl") is not False or \
                    not count(row.get("evaluatedCount")) or \
                    not count(row.get("failureCount")) or \
                    row["failureCount"] > row["evaluatedCount"] or \
                    not all(optional_number(row.get(key)) for key in (
                        "meanAvoidedMaePct", "meanDelaySessions",
                        "meanForegoneReturnPct", "meanMaePct",
                        "meanMaxDrawdownPct", "meanMfePct",
                        "meanMissedMfePct", "meanTerminalReturnPct")):
                return False
        assumptions = counter.get("assumptions")
        if not isinstance(assumptions, dict) or set(assumptions) != {
                "costBps", "executionPolicy",
                "roundTripCostAndSlippagePct", "slippageBps"} or \
                assumptions.get("executionPolicy") != "next_session_open":
            return False
        cost = _number(assumptions.get("costBps"), "artifact_cost")
        slippage = _number(
            assumptions.get("slippageBps"), "artifact_slippage")
        if _number(assumptions.get("roundTripCostAndSlippagePct"),
                   "artifact_round_trip") != _round(
                       2.0 * (cost + slippage) / 100.0):
            return False
        if cost != contract["costBps"] or \
                slippage != contract["slippageBps"] or \
                assumptions["executionPolicy"] != contract[
                    "executionPolicy"]:
            return False

        if not isinstance(turtle, dict) or set(turtle) != {
                "hardVeto", "parameters", "schemaVersion", "shadowOnly",
                "signalCounts", "signalDayCount", "signals",
                "signalsTruncated",
                "unknownHistoricalRules", "validationStatus"} or \
                turtle.get("schemaVersion") != TURTLE_SCHEMA or \
                turtle.get("hardVeto") is not False or \
                turtle.get("shadowOnly") is not True or \
                not isinstance(turtle.get("signals"), list) or \
                len(turtle["signals"]) > MAX_TURTLE_SIGNAL_DETAILS or \
                not count(turtle.get("signalDayCount")) or \
                not isinstance(turtle.get("signalsTruncated"), bool):
            return False
        expected_turtle = contract["parameters"]["turtle"]
        if turtle.get("parameters") != {
                "atrPeriod": expected_turtle["atrPeriod"],
                "entryLookbacks": expected_turtle["entryLookbacks"],
                "exitLookbacks": expected_turtle["exitLookbacks"],
        }:
            return False
        signal_counts = turtle.get("signalCounts")
        if not isinstance(signal_counts, dict) or set(signal_counts) != {
                "entry20", "entry55", "exit10", "exit20"} or \
                not all(count(row) for row in signal_counts.values()) or \
                turtle.get("unknownHistoricalRules") != [
                    "original_unit_limit", "original_pyramiding",
                    "original_stop_rule", "original_portfolio_heat",
                    "original_execution_details"] or \
                turtle.get("validationStatus") != \
                "UNVALIDATED_UNTIL_LAWFUL_OHLC_HOLDOUT":
            return False
        turtle_signal_keys = {
            "atrN", "date", "entry20", "entry55", "exit10", "exit20",
            "instrumentId"}
        for signal in turtle["signals"]:
            if not isinstance(signal, dict) or set(signal) != \
                    turtle_signal_keys or \
                    not optional_number(signal.get("atrN")) or \
                    not isinstance(signal.get("instrumentId"), str) or \
                    not isinstance(signal.get("date"), str) or \
                    not all(isinstance(signal.get(key), bool) for key in (
                        "entry20", "entry55", "exit10", "exit20")) or \
                    not any(signal[key] for key in (
                        "entry20", "entry55", "exit10", "exit20")):
                return False
            _date(signal["date"], "artifact_turtle_date")
        visible_signal_counts = {
            key: sum(1 for row in turtle["signals"] if row[key])
            for key in ("entry20", "entry55", "exit10", "exit20")
        }
        if len({(row["instrumentId"], row["date"])
                for row in turtle["signals"]}) != len(turtle["signals"]) or \
                turtle["signalDayCount"] < len(turtle["signals"]) or \
                any(visible_signal_counts[key] > signal_counts[key]
                    for key in signal_counts) or \
                (not turtle["signalsTruncated"] and
                 visible_signal_counts != signal_counts) or \
                turtle["signalsTruncated"] is not (
                    turtle["signalDayCount"] > len(turtle["signals"])):
            return False

        pit = value.get("pointInTimeProof")
        if not isinstance(pit, dict) or set(pit) != {
                "bars", "events", "futureInputAdmitted"} or \
                pit.get("futureInputAdmitted") is not False:
            return False
        bars_proof = pit.get("bars")
        events_proof = pit.get("events")
        if not isinstance(bars_proof, dict) or set(bars_proof) != {
                "admittedRowCount", "datasetHash", "duplicateRowCount",
                "excludedAfterDecisionCutoffCount", "excludedFutureCount",
                "futureRowsAdmitted", "pitPolicyId", "revisionSelection",
                "sourceRowCount", "supersededRevisionCount", "verified"} or \
                bars_proof.get("futureRowsAdmitted") is not False or \
                bars_proof.get("verified") is not True or \
                bars_proof.get("pitPolicyId") != PIT_POLICY_ID or \
                not exact_digest(bars_proof.get("datasetHash")) or \
                not all(count(bars_proof.get(key)) for key in (
                    "admittedRowCount", "duplicateRowCount",
                    "excludedAfterDecisionCutoffCount", "excludedFutureCount",
                    "sourceRowCount", "supersededRevisionCount")) or \
                bars_proof["admittedRowCount"] > bars_proof["sourceRowCount"]:
            return False
        if bars_proof["sourceRowCount"] != sum((
                bars_proof["admittedRowCount"],
                bars_proof["duplicateRowCount"],
                bars_proof["excludedAfterDecisionCutoffCount"],
                bars_proof["excludedFutureCount"],
                bars_proof["supersededRevisionCount"])):
            return False
        if not isinstance(events_proof, dict) or set(events_proof) != {
                "admittedEventCount", "duplicateEventCount", "eventHash",
                "excludedFutureCount", "futureEventsAdmitted", "pitPolicyId",
                "sourceEventCount", "verified"} or \
                events_proof.get("futureEventsAdmitted") is not False or \
                events_proof.get("verified") is not True or \
                events_proof.get("pitPolicyId") != PIT_POLICY_ID or \
                not exact_digest(events_proof.get("eventHash")) or \
                not all(count(events_proof.get(key)) for key in (
                    "admittedEventCount", "duplicateEventCount",
                    "excludedFutureCount", "sourceEventCount")) or \
                events_proof["admittedEventCount"] > \
                events_proof["sourceEventCount"]:
            return False
        if events_proof["sourceEventCount"] != sum((
                events_proof["admittedEventCount"],
                events_proof["duplicateEventCount"],
                events_proof["excludedFutureCount"])):
            return False

        data = value.get("dataIdentity")
        if not isinstance(data, dict) or set(data) != {
                "barDatasetHash", "declaredDatasets", "eventHash"} or \
                data.get("barDatasetHash") != bars_proof["datasetHash"] or \
                data.get("eventHash") != events_proof["eventHash"] or \
                _validate_datasets(data.get("declaredDatasets")) != \
                data.get("declaredDatasets") or \
                data.get("declaredDatasets") != contract["datasets"]:
            return False
        coverage = value.get("coverage")
        if not isinstance(coverage, dict) or set(coverage) != {
                "barCount", "eventCount", "excludedEventCounts",
                "instruments"} or \
                coverage.get("barCount") != bars_proof["admittedRowCount"] or \
                coverage.get("eventCount") != events_proof[
                    "admittedEventCount"] or \
                not isinstance(coverage.get("instruments"), list) or \
                coverage["instruments"] != sorted(set(
                    coverage["instruments"])) or \
                not all(isinstance(row, str)
                        for row in coverage["instruments"]):
            return False
        excluded_counts = coverage.get("excludedEventCounts")
        if not isinstance(excluded_counts, dict) or set(excluded_counts) != {
                "EMBARGO", "OUT_OF_SCOPE", "SEALED_GOLDEN"} or \
                not all(count(row) for row in excluded_counts.values()):
            return False
        if excluded_counts["SEALED_GOLDEN"] != 0 or \
                turtle["signalDayCount"] > coverage["barCount"]:
            return False

        partitions = value.get("partitions")
        partition_proofs = value.get("partitionProofs")
        if not isinstance(partitions, dict) or set(partitions) != {
                "DEVELOPMENT", "HOLDOUT", "GOLDEN"} or \
                not isinstance(partition_proofs, dict) or \
                set(partition_proofs) != {
                    "DEVELOPMENT", "HOLDOUT", "GOLDEN"}:
            return False
        expected_horizon_keys = {str(item) for item in horizons}
        for name in ("DEVELOPMENT", "HOLDOUT", "GOLDEN"):
            part = partitions.get(name)
            part_proof = partition_proofs.get(name)
            if not isinstance(part, dict) or set(part) != {
                    "access", "eventCount", "metrics"} or \
                    not count(part.get("eventCount")) or \
                    not isinstance(part_proof, dict) or set(part_proof) != {
                        "counterfactualCount", "counterfactualDigest",
                        "counterfactualsTruncated",
                        "evaluatedCounterfactualCount", "eventCount",
                        "eventDetailsDigest", "eventDetailsTruncated",
                        "retainedCounterfactualCount",
                        "retainedEventDetailCount"} or \
                    not all(count(part_proof.get(key)) for key in (
                        "counterfactualCount",
                        "evaluatedCounterfactualCount", "eventCount",
                        "retainedCounterfactualCount",
                        "retainedEventDetailCount")) or \
                    not isinstance(
                        part_proof.get("counterfactualsTruncated"), bool) or \
                    not isinstance(
                        part_proof.get("eventDetailsTruncated"), bool) or \
                    not exact_digest(part_proof.get("counterfactualDigest")) or \
                    not exact_digest(part_proof.get("eventDetailsDigest")) or \
                    part_proof["eventCount"] != part["eventCount"] or \
                    part_proof["evaluatedCounterfactualCount"] > \
                    part_proof["counterfactualCount"] or \
                    part_proof["retainedCounterfactualCount"] > \
                    part_proof["counterfactualCount"] or \
                    part_proof["retainedEventDetailCount"] > \
                    part_proof["eventCount"]:
                return False
            matching = [row for row in details if row["partition"] == name]
            if len(matching) != part_proof["retainedEventDetailCount"] or \
                    part_proof["eventDetailsTruncated"] is not (
                        len(matching) < part["eventCount"]) or \
                    (not part_proof["eventDetailsTruncated"] and
                     part_proof["eventDetailsDigest"] !=
                     sha256_hex(matching)):
                return False
            if part["access"] == "OPEN":
                if not isinstance(part["metrics"], dict) or \
                        set(part["metrics"]) != expected_horizon_keys:
                    return False
                if not all(valid_metric(metric)
                           for metric in part["metrics"].values()) or \
                        (not part_proof["eventDetailsTruncated"] and
                         part["metrics"] != _aggregate_events(
                             matching, horizons)):
                    return False
            elif part["access"] != "SEALED" or \
                    part["eventCount"] != 0 or part["metrics"] is not None:
                return False

        total_partition_events = sum(
            row["eventCount"] for row in partition_proofs.values())
        total_partition_counterfactuals = sum(
            row["counterfactualCount"] for row in partition_proofs.values())
        if value["eventDetailsTruncated"] is not (
                len(details) < total_partition_events) or \
                counter["perEventTruncated"] is not (
                    len(counter["perEvent"]) <
                    total_partition_counterfactuals):
            return False
        if total_partition_events + sum(excluded_counts.values()) != \
                events_proof["admittedEventCount"]:
            return False

        visible_ids = {row["eventId"]: row["partition"] for row in details}
        visible_counter_by_partition = {
            name: [row for row in counter["perEvent"]
                   if visible_ids.get(row["eventId"]) == name]
            for name in ("DEVELOPMENT", "HOLDOUT", "GOLDEN")
        }
        for name, rows in visible_counter_by_partition.items():
            part_proof = partition_proofs[name]
            if len(rows) != part_proof["retainedCounterfactualCount"] or \
                    part_proof["counterfactualsTruncated"] is not (
                        len(rows) < part_proof["counterfactualCount"]):
                return False
        if not counter["perEventTruncated"]:
            if total_partition_counterfactuals != len(counter["perEvent"]):
                return False
            for name, rows in visible_counter_by_partition.items():
                if partition_proofs[name]["counterfactualCount"] != len(rows) or \
                        partition_proofs[name]["counterfactualDigest"] != \
                        sha256_hex(rows):
                    return False
            if counter["strategies"] != _counterfactual_summary(
                    counter["perEvent"]):
                return False
        elif len(counter["perEvent"]) > sum(
                row["counterfactualCount"]
                for row in partition_proofs.values()):
            return False

        golden = value.get("goldenCase")
        if not isinstance(golden, dict) or set(golden) != {
                "acceptanceChecks", "access", "caseId", "eligible",
                "evaluatedEventCount",
                "expectedEventId", "expectedInstrumentId",
                "fullyScoredHorizons",
                "openedForPolicyIdentity",
                "openedForResearchDataIdentity"} or \
                not isinstance(golden.get("caseId"), str) or \
                not isinstance(golden.get("eligible"), bool) or \
                not count(golden.get("evaluatedEventCount")) or \
                golden["evaluatedEventCount"] != \
                partitions["GOLDEN"]["eventCount"] or \
                golden["access"] != partitions["GOLDEN"]["access"] or \
                golden["access"] != contract["goldenPolicy"]["access"] or \
                golden["caseId"] != contract["goldenPolicy"]["caseId"] or \
                golden["expectedEventId"] != contract[
                    "goldenPolicy"]["expectedEventId"] or \
                golden["expectedInstrumentId"] != contract[
                    "goldenPolicy"]["expectedInstrumentId"]:
            return False
        checks = golden.get("acceptanceChecks")
        check_keys = {
            "bandWalkEndingDetected", "bandWalkEndingFirstObservedDate",
            "evaluationStatus", "ma25ReclaimDetected",
            "macdGoldenCrossDetected", "riskKernelArtifactId",
            "riskOffFirstObservedDate",
            "riskOffSufficient", "sarFlipDetected",
            "shoReversalArtifactId",
            "vixDecreasingConfirmationDetected",
            "waitMissedOpportunityMeasured",
        }
        if not isinstance(checks, dict) or set(checks) != check_keys:
            return False
        if golden["access"] == "SEALED":
            if golden["openedForPolicyIdentity"] is not None or \
                    golden["openedForResearchDataIdentity"] is not None or \
                    golden["eligible"] is not False or \
                    golden["fullyScoredHorizons"] != [] or \
                    checks != {
                        "bandWalkEndingDetected": None,
                        "bandWalkEndingFirstObservedDate": None,
                        "evaluationStatus": "SEALED",
                        "ma25ReclaimDetected": None,
                        "macdGoldenCrossDetected": None,
                        "riskKernelArtifactId": None,
                        "riskOffFirstObservedDate": None,
                        "riskOffSufficient": None,
                        "sarFlipDetected": None,
                        "shoReversalArtifactId": None,
                        "vixDecreasingConfirmationDetected": None,
                        "waitMissedOpportunityMeasured": None,
                    }:
                return False
        elif golden["access"] == "OPEN":
            if golden["openedForPolicyIdentity"] != \
                    identity["policyIdentity"] or \
                    golden["openedForResearchDataIdentity"] != \
                    identity["researchDataIdentity"] or \
                    golden["eligible"] is not True or \
                    golden["evaluatedEventCount"] < 1 or \
                    golden["fullyScoredHorizons"] != horizons or \
                    checks.get("evaluationStatus") != "EVALUATED" or \
                    not exact_digest(
                        checks.get("riskKernelArtifactId"), "rk-") or \
                    not exact_digest(
                        checks.get("shoReversalArtifactId"),
                        "sho-reversal-") or \
                    not all(isinstance(checks.get(key), bool) for key in (
                        "bandWalkEndingDetected", "ma25ReclaimDetected",
                        "macdGoldenCrossDetected", "riskOffSufficient",
                        "sarFlipDetected",
                        "vixDecreasingConfirmationDetected",
                        "waitMissedOpportunityMeasured")) or \
                    (checks["riskOffFirstObservedDate"] is None) is not (
                        checks["riskOffSufficient"] is False) or \
                    (checks["bandWalkEndingFirstObservedDate"] is None) is not (
                        checks["bandWalkEndingDetected"] is False):
                return False
            for key in ("riskOffFirstObservedDate",
                        "bandWalkEndingFirstObservedDate"):
                if checks[key] is not None:
                    _date(checks[key], "artifact_golden_acceptance_date")
            golden_details = [
                row for row in details
                if row.get("partition") == "GOLDEN"
                and row.get("eventId") == golden["expectedEventId"]
                and row.get("instrumentId") == golden[
                    "expectedInstrumentId"]]
            golden_counterfactuals = [
                row for row in counter["perEvent"]
                if row.get("eventId") == golden["expectedEventId"]]
            if len(golden_details) != 1 or \
                    golden_details[0].get("validatedReversal") is not True or \
                    len(golden_counterfactuals) != 1 or \
                    golden_counterfactuals[0].get("status") != "EVALUATED" or \
                    any(outcome.get("status") not in {
                        "OBSERVED", "AMBIGUOUS"}
                        for outcome in golden_details[0].get(
                            "horizons", {}).values()):
                return False
            golden_detail = golden_details[0]
            risk_artifact = golden_detail["riskKernelArtifact"]
            sho_artifact = golden_detail["shoReversalArtifact"]
            band_factor = sho_artifact["evidence"]["bandWalkEnding"]
            risk_sufficient = risk_artifact["constraint"] in {
                "REDUCE_RISK", "EXIT_RISK"}
            band_detected = band_factor["conditionMet"] is True
            if checks["riskKernelArtifactId"] != risk_artifact[
                    "riskKernelId"] or \
                    checks["shoReversalArtifactId"] != sho_artifact[
                        "artifactId"] or \
                    checks["riskOffSufficient"] is not risk_sufficient or \
                    checks["riskOffFirstObservedDate"] != (
                        risk_artifact["asOf"][:10]
                        if risk_sufficient else None) or \
                    checks["bandWalkEndingDetected"] is not band_detected or \
                    checks["bandWalkEndingFirstObservedDate"] != (
                        band_factor["evidenceDate"]
                        if band_detected else None):
                return False
            golden_strategies = {
                row["strategy"]: row
                for row in golden_counterfactuals[0]["strategies"]
            }
            expected_checks = {
                "ma25ReclaimDetected": golden_strategies[
                    "BUY_ON_25MA_RECLAIM"]["entryDate"] is not None,
                "macdGoldenCrossDetected": golden_strategies[
                    "BUY_ON_MACD_GC"]["entryDate"] is not None,
                "sarFlipDetected": golden_strategies[
                    "BUY_ON_SAR_FLIP"]["entryDate"] is not None,
                "vixDecreasingConfirmationDetected": golden_strategies[
                    "BUY_ON_VIX_DC"]["entryDate"] is not None,
                "waitMissedOpportunityMeasured": golden_strategies[
                    "WAIT"]["missedMfePct"] is not None,
            }
            if any(checks[key] is not expected
                   for key, expected in expected_checks.items()):
                return False
            golden_range = next(
                row for row in contract["partitionPolicy"]["ranges"]
                if row["name"] == "GOLDEN")
            risk_date = checks["riskOffFirstObservedDate"]
            band_date = checks["bandWalkEndingFirstObservedDate"]
            if risk_date is not None and not (
                    golden_range["startDate"] <= risk_date <=
                    golden_detail["signalDate"]):
                return False
            if band_date is not None and not (
                    golden_range["startDate"] <= band_date <=
                    golden_range["endDate"]):
                return False
        else:
            return False

        proof = value.get("holdoutProof")
        if not isinstance(proof, dict) or set(proof) != {
                "counterfactualDigest", "eligibleForPass",
                "evaluatedCounterfactualCount", "eventCount",
                "eventDetailsDigest", "fullyScoredHorizons", "inputHash",
                "latestInputKnownAt", "resultDigest"} or \
                not isinstance(proof.get("eligibleForPass"), bool) or \
                not count(proof.get("evaluatedCounterfactualCount")) or \
                not count(proof.get("eventCount")) or \
                proof["eventCount"] != partitions["HOLDOUT"]["eventCount"] or \
                proof["eventCount"] != partition_proofs["HOLDOUT"][
                    "eventCount"] or \
                proof["evaluatedCounterfactualCount"] != \
                partition_proofs["HOLDOUT"][
                    "evaluatedCounterfactualCount"] or \
                proof.get("counterfactualDigest") != \
                partition_proofs["HOLDOUT"]["counterfactualDigest"] or \
                proof.get("eventDetailsDigest") != \
                partition_proofs["HOLDOUT"]["eventDetailsDigest"] or \
                not exact_digest(proof.get("inputHash")) or \
                not canonical_time(proof.get("latestInputKnownAt")) or \
                not exact_digest(proof.get("resultDigest")) or \
                value.get("holdoutResultDigest") != proof["resultDigest"]:
            return False
        holdout_metrics = partitions["HOLDOUT"]["metrics"]
        scored_horizons = [item for item in horizons
                           if holdout_metrics[str(item)][
                               "scoreableCount"] > 0]
        expected_eligible = proof["eventCount"] > 0 and \
            scored_horizons == horizons and \
            partition_proofs["HOLDOUT"]["counterfactualCount"] == \
            proof["eventCount"] and \
            proof["evaluatedCounterfactualCount"] == proof["eventCount"]
        if proof["fullyScoredHorizons"] != scored_horizons or \
                proof["eligibleForPass"] is not expected_eligible or \
                (protocol["policyFrozen"] is False and
                 proof["eligibleForPass"] is True):
            return False
        expected_holdout_digest = sha256_hex({
            "counterfactualDigest": proof["counterfactualDigest"],
            "eventDetailsDigest": proof["eventDetailsDigest"],
            "inputHash": proof["inputHash"],
            "latestInputKnownAt": proof["latestInputKnownAt"],
            "metrics": partitions["HOLDOUT"],
        })
        if proof["resultDigest"] != expected_holdout_digest:
            return False
    except (ResearchContractError, TypeError, ValueError, KeyError,
            IndexError, OverflowError):
        return False

    def forbidden(node: Any) -> bool:
        if isinstance(node, dict):
            if {"open", "high", "low", "close"}.issubset(node):
                return True
            if "ownerPnl" in node and node["ownerPnl"] is not False:
                return True
            return any(forbidden(item) for item in node.values())
        if isinstance(node, list):
            return any(forbidden(item) for item in node)
        return False

    if forbidden(value):
        return False
    if not _input_receipt_valid(value.get("inputReceipt"), value):
        return False
    digest = value.get("artifactDigest")
    artifact_id = value.get("artifactId")
    body = {key: item for key, item in value.items()
            if key not in ("artifactDigest", "artifactId")}
    try:
        return bool(isinstance(digest, str) and _is_digest(digest)
                    and artifact_id == "ra-" + digest[:32]
                    and sha256_hex(body) == digest
                    and len(canonical_bytes(value)) <= MAX_ARTIFACT_BYTES)
    except (ResearchContractError, TypeError, ValueError):
        return False


def verify_coverage_artifact(value: Any) -> bool:
    if not isinstance(value, dict) or value.get("schemaVersion") != COVERAGE_SCHEMA:
        return False
    digest = value.get("coverageDigest")
    body = {key: item for key, item in value.items() if key != "coverageDigest"}
    return bool(_is_digest(digest) and sha256_hex(body) == digest)
