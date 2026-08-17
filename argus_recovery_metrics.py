"""Bounded, privacy-safe recovery measurement (non-authoritative shadow only).

Only counters, timestamps, stable registry identifiers and byte estimates are
accepted.  This module intentionally has no payload parameter and never stores
checkpoint/WAL content, URLs, prompts, holdings, research or model output.
"""

from __future__ import annotations

import datetime as dt
from functools import lru_cache
import json
import math
import os
import resource
import sys
import threading
import time
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Tuple

import argus_persistent_storage
import argus_recovery_registry


SCHEMA = "argus-recovery-measurement-shadow-v1"
RETENTION_DAYS = 31
BUCKET_MINUTES = 5
MAX_BUCKETS = RETENTION_DAYS * 24 * (60 // BUCKET_MINUTES)
MAX_DAILY_DISTRIBUTIONS = RETENTION_DAYS + 1
MAX_RECENT_MUTATIONS = 256
MAX_CHECKPOINT_SAMPLES = 2048
MAX_PERSISTED_BYTES = 12 * 1024 * 1024
# Keep every persisted/public number exactly representable by common JSON
# consumers and reject attacker-controlled arbitrary-precision values.
MAX_METRIC_NUMBER = (1 << 53) - 1
PERSIST_INTERVAL_SECONDS = 5 * 60
FUTURE_RECORD_FRAMING_ESTIMATE_BYTES = 256
PUBLIC_REDACTED_IDENTIFIER = "private.redacted"
LARGE_SECTION_KEYS = (
    "marketLedger", "verifiedViewSnapshots", "assetChartReports",
    "chartIntelligence", "marketReplay", "todayIntelligence")
_HISTOGRAM_UPPER_BOUNDS = (
    0, 64, 128, 256, 512, 1024, 2048, 4096, 8192, 16384, 32768,
    65536, 131072, 262144, 524288, 1048576, 2097152, 4194304,
    8388608, 16777216, 33554432, 67108864, 134217728, 268435456,
    536870912)
UTC = dt.timezone.utc


def _utc_now() -> dt.datetime:
    return dt.datetime.now(UTC)


def _iso(value: dt.datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _parse_iso(value: Any) -> Optional[dt.datetime]:
    try:
        parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
    except (TypeError, ValueError):
        return None


def _valid_timestamp(value: Any, *, optional: bool = False) -> bool:
    if value is None:
        return optional
    if not isinstance(value, str) or len(value) > 40 or "T" not in value or \
            not value.endswith("Z"):
        return False
    parsed = _parse_iso(value)
    return parsed is not None and parsed.tzinfo is not None and \
        2000 <= parsed.year <= 2100 and _iso(parsed) == value


def _valid_nonnegative_int(value: Any, *, maximum: int = MAX_METRIC_NUMBER
                           ) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and \
        0 <= value <= maximum


def _valid_nonnegative_number(value: Any, *, maximum: float = MAX_METRIC_NUMBER
                              ) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and \
        math.isfinite(float(value)) and 0 <= float(value) <= float(maximum)


def _exact_keys(value: Any, keys: Iterable[str]) -> bool:
    return isinstance(value, dict) and set(value) == set(keys)


@lru_cache(maxsize=None)
def _public_telemetry_identifier(kind: str, identifier: str) -> str:
    """Return the sole canonical public label for registry identifiers.

    Unknown/future identifiers fail closed into one aggregate bucket.  State
    privacy flags and mutation telemetry policy remain authoritative; public
    projections never infer safety from a name or call site.
    """
    candidate = str(identifier or "")
    allowed = False
    if kind == "mutation":
        definition = argus_recovery_registry.mutation_by_class().get(candidate)
        allowed = bool(
            definition is not None and
            argus_recovery_registry.mutation_allows_public_telemetry(
                definition))
    elif kind == "state":
        definition = argus_recovery_registry.state_by_id().get(candidate)
        allowed = bool(
            definition is not None and
            argus_recovery_registry.state_allows_public_telemetry(definition))
    elif kind == "checkpoint_section":
        owners = [row for row in argus_recovery_registry.states()
                  if candidate in row.checkpointKeys]
        allowed = bool(owners) and all(
            _public_telemetry_identifier("state", row.stateId) == row.stateId
            for row in owners)
    return candidate if allowed else PUBLIC_REDACTED_IDENTIFIER


def _public_identifier_counts(kind: str, values: Mapping[str, Any]
                              ) -> Dict[str, int]:
    projected: Dict[str, int] = {}
    for identifier, value in sorted(values.items()):
        label = _public_telemetry_identifier(kind, str(identifier))
        projected[label] = projected.get(label, 0) + int(value)
    return projected


def _canonical_size(value: Any) -> int:
    encoder = json.JSONEncoder(
        ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sum(len(chunk.encode("utf-8")) for chunk in encoder.iterencode(value))


def serialized_size_estimate(value: Any) -> int:
    """Return canonical plaintext bytes without retaining or returning content."""
    return _canonical_size(value)


def checkpoint_section_sizes(blob: Mapping[str, Any]) -> Dict[str, int]:
    """Deterministic top-level accounting, sampled only at checkpoint assembly."""
    known_keys = sorted({key for row in argus_recovery_registry.states()
                         for key in row.checkpointKeys})
    return {key: _canonical_size(blob[key]) for key in known_keys if key in blob}


def peak_rss_bytes() -> Optional[int]:
    try:
        value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        # macOS reports bytes; Linux and most BSD production images report KiB.
        return value if sys.platform == "darwin" else value * 1024
    except (AttributeError, OSError, TypeError, ValueError):
        return None


def measure_jsonl_metadata(path: Optional[str], *,
                           maximum_bytes: int = 64 * 1024 * 1024
                           ) -> Dict[str, Any]:
    """Count bytes/non-empty records without parsing or retaining private rows."""
    result = {"configured": bool(path), "exists": False, "bytes": 0,
              "recordCount": 0, "complete": True}
    if not path:
        return result
    try:
        size = os.path.getsize(path)
        result.update({"exists": True, "bytes": int(size)})
        if size > int(maximum_bytes):
            result["complete"] = False
            result["reason"] = "measurement_maximum_exceeded"
            return result
        count = 0
        with open(path, "rb") as handle:
            for line in handle:
                if line.strip():
                    count += 1
        result["recordCount"] = count
    except FileNotFoundError:
        pass
    except OSError:
        result.update({"complete": False, "reason": "measurement_io_error"})
    return result


def _histogram() -> Dict[str, int]:
    return {str(value): 0 for value in _HISTOGRAM_UPPER_BOUNDS}


def _histogram_add(histogram: Dict[str, int], value: float) -> None:
    safe = max(0, int(math.ceil(float(value or 0))))
    upper = next((bound for bound in _HISTOGRAM_UPPER_BOUNDS
                  if safe <= bound), _HISTOGRAM_UPPER_BOUNDS[-1])
    histogram[str(upper)] = int(histogram.get(str(upper)) or 0) + 1


def _histogram_quantile(histogram: Mapping[str, int], quantile: float
                        ) -> Optional[int]:
    total = sum(max(0, int(value or 0)) for value in histogram.values())
    if total <= 0:
        return None
    target = max(1, int(math.ceil(total * float(quantile))))
    seen = 0
    for bound in _HISTOGRAM_UPPER_BOUNDS:
        seen += max(0, int(histogram.get(str(bound)) or 0))
        if seen >= target:
            return bound
    return _HISTOGRAM_UPPER_BOUNDS[-1]


def _distribution_summary(row: Mapping[str, Any]) -> Dict[str, Any]:
    histogram = row.get("plaintextBytesHistogram") or {}
    return {
        "mutationCount": int(row.get("mutationCount") or 0),
        "plaintextBytesEstimate": int(row.get("plaintextBytesEstimate") or 0),
        "candidateRecordPlaintextBytesEstimate": int(
            row.get("candidateRecordPlaintextBytesEstimate") or 0),
        "maxSingleMutationPlaintextBytesEstimate": int(
            row.get("maxSingleMutationPlaintextBytesEstimate") or 0),
        "mutationPlaintextBytesApproxP50": _histogram_quantile(histogram, .50),
        "mutationPlaintextBytesApproxP95": _histogram_quantile(histogram, .95),
        "mutationPlaintextBytesApproxP99": _histogram_quantile(histogram, .99),
        "histogramQuantilesAreUpperBounds": True,
    }


def _new_distribution() -> Dict[str, Any]:
    return {
        "mutationCount": 0, "plaintextBytesEstimate": 0,
        "candidateRecordPlaintextBytesEstimate": 0,
        "maxSingleMutationPlaintextBytesEstimate": 0,
        "plaintextBytesHistogram": _histogram(),
        "latencyMsHistogram": _histogram(),
    }


def _merge_distribution(target: Dict[str, Any], source: Mapping[str, Any]) -> None:
    target["mutationCount"] += int(source.get("mutationCount") or 0)
    target["plaintextBytesEstimate"] += int(
        source.get("plaintextBytesEstimate") or 0)
    target["candidateRecordPlaintextBytesEstimate"] += int(
        source.get("candidateRecordPlaintextBytesEstimate") or 0)
    target["maxSingleMutationPlaintextBytesEstimate"] = max(
        target["maxSingleMutationPlaintextBytesEstimate"],
        int(source.get("maxSingleMutationPlaintextBytesEstimate") or 0))
    for field in ("plaintextBytesHistogram", "latencyMsHistogram"):
        source_histogram = source.get(field) or {}
        for bound in _HISTOGRAM_UPPER_BOUNDS:
            key = str(bound)
            target[field][key] += int(source_histogram.get(key) or 0)


def _empty_document(now: dt.datetime) -> Dict[str, Any]:
    return {
        "schemaVersion": SCHEMA,
        "authoritative": False,
        "coverage": "SHADOW_INCOMPLETE",
        "createdAt": _iso(now),
        "updatedAt": _iso(now),
        "retentionDays": RETENTION_DAYS,
        "bucketMinutes": BUCKET_MINUTES,
        "acceptanceClockStarted": False,
        "buckets": [],
        "dailyDistributions": {},
        "recentMutations": [],
        "checkpointSamples": [],
        "measurementErrors": 0,
    }


def _validate_document(value: Any) -> bool:
    """Validate every persisted v1 field without coercion or partial trust."""
    try:
        return _validate_document_strict(value)
    except Exception:
        # This validator handles untrusted local shadow state.  It must be total:
        # malformed containers are discarded and never become startup failures.
        return False


def _validate_document_strict(value: Any) -> bool:
    top_keys = {
        "schemaVersion", "authoritative", "coverage", "createdAt",
        "updatedAt", "retentionDays", "bucketMinutes",
        "acceptanceClockStarted", "buckets", "dailyDistributions",
        "recentMutations", "checkpointSamples", "measurementErrors"}
    if not _exact_keys(value, top_keys) or value["schemaVersion"] != SCHEMA or \
            value["authoritative"] is not False or \
            value["coverage"] != "SHADOW_INCOMPLETE" or \
            type(value["retentionDays"]) is not int or \
            value["retentionDays"] != RETENTION_DAYS or \
            type(value["bucketMinutes"]) is not int or \
            value["bucketMinutes"] != BUCKET_MINUTES or \
            value["acceptanceClockStarted"] is not False or \
            not _valid_timestamp(value["createdAt"]) or \
            not _valid_timestamp(value["updatedAt"]) or \
            not _valid_nonnegative_int(value["measurementErrors"]):
        return False
    created_at = _parse_iso(value["createdAt"])
    updated_at = _parse_iso(value["updatedAt"])
    if created_at > updated_at or \
            updated_at > _utc_now() + dt.timedelta(days=1):
        return False
    for key, maximum in (("buckets", MAX_BUCKETS),
                         ("recentMutations", MAX_RECENT_MUTATIONS),
                         ("checkpointSamples", MAX_CHECKPOINT_SAMPLES)):
        if not isinstance(value[key], list) or len(value[key]) > maximum:
            return False
    daily_distributions = value["dailyDistributions"]
    if not isinstance(daily_distributions, dict) or \
            len(daily_distributions) > MAX_DAILY_DISTRIBUTIONS:
        return False

    mutation_index = argus_recovery_registry.mutation_by_class()
    known_mutations = set(mutation_index)
    known_coverage = {row.value for row in argus_recovery_registry.WalCoverage}
    state_index = argus_recovery_registry.state_by_id()
    histogram_keys = {str(bound) for bound in _HISTOGRAM_UPPER_BOUNDS}

    def valid_histogram(histogram: Any, mutation_count: int) -> bool:
        return _exact_keys(histogram, histogram_keys) and all(
            _valid_nonnegative_int(count) for count in histogram.values()) and \
            sum(histogram.values()) == mutation_count

    recent_required = {
        "observedAt", "mutationClass", "targetStateIds",
        "redactedTargetCount", "plaintextBytesEstimate",
        "candidateRecordPlaintextBytesEstimate", "transitionCount",
        "recordCount", "latencyMs", "success", "currentWalCoverage"}
    recent_allowed = recent_required | {"localSequence"}
    previous_observed: Optional[dt.datetime] = None
    for row in value["recentMutations"]:
        if not isinstance(row, dict) or set(row) not in (
                recent_required, recent_allowed):
            return False
        definition = mutation_index.get(row["mutationClass"])
        if definition is None or not _valid_timestamp(row["observedAt"]) or \
                row["success"] not in (True, False) or \
                not isinstance(row["success"], bool) or \
                not _valid_nonnegative_number(row["latencyMs"]):
            return False
        observed = _parse_iso(row["observedAt"])
        if observed > updated_at or \
                (previous_observed is not None and
                 observed < previous_observed):
            return False
        previous_observed = observed
        safe_targets = [target for target in definition.targetStateIds
                        if state_index[target].allowedInTelemetry]
        if row["targetStateIds"] != safe_targets or \
                not _valid_nonnegative_int(row["redactedTargetCount"]) or \
                row["redactedTargetCount"] != (
                    len(definition.targetStateIds) - len(safe_targets)) or \
                row["currentWalCoverage"] != definition.currentWalCoverage.value:
            return False
        for key in ("plaintextBytesEstimate", "transitionCount", "recordCount",
                    "candidateRecordPlaintextBytesEstimate"):
            if not _valid_nonnegative_int(row[key]):
                return False
        expected_candidate = row["plaintextBytesEstimate"] + \
            row["recordCount"] * FUTURE_RECORD_FRAMING_ESTIMATE_BYTES
        if expected_candidate > MAX_METRIC_NUMBER or \
                row["candidateRecordPlaintextBytesEstimate"] != expected_candidate:
            return False
        if "localSequence" in row and not _valid_nonnegative_int(
                row["localSequence"]):
            return False

    bucket_keys = {
        "bucketStart", "mutationCount", "transitionCount", "recordCount",
        "successCount", "failureCount", "plaintextBytesEstimate",
        "candidateRecordPlaintextBytesEstimate",
        "maxSingleMutationPlaintextBytesEstimate", "byMutationClass",
        "byWalCoverage"}
    bucket_numbers = bucket_keys - {
        "bucketStart", "byMutationClass", "byWalCoverage"}
    previous_bucket: Optional[dt.datetime] = None
    for row in value["buckets"]:
        if not _exact_keys(row, bucket_keys) or \
                not _valid_timestamp(row["bucketStart"]) or any(
                    not _valid_nonnegative_int(row[key])
                    for key in bucket_numbers):
            return False
        bucket_at = _parse_iso(row["bucketStart"])
        if bucket_at > updated_at or bucket_at.second or \
                bucket_at.microsecond or \
                bucket_at.minute % BUCKET_MINUTES or \
                (previous_bucket is not None and bucket_at <= previous_bucket):
            return False
        previous_bucket = bucket_at
        by_class = row["byMutationClass"]
        by_coverage = row["byWalCoverage"]
        if not isinstance(by_class, dict) or not set(by_class) <= known_mutations or \
                not isinstance(by_coverage, dict) or \
                not set(by_coverage) <= known_coverage or any(
                    not _valid_nonnegative_int(count) or count == 0
                    for count in list(by_class.values()) +
                    list(by_coverage.values())):
            return False
        mutation_count = row["mutationCount"]
        if mutation_count == 0 or sum(by_class.values()) != mutation_count or \
                sum(by_coverage.values()) != mutation_count or \
                row["successCount"] + row["failureCount"] != mutation_count or \
                row["maxSingleMutationPlaintextBytesEstimate"] > \
                row["plaintextBytesEstimate"] or \
                row["plaintextBytesEstimate"] > mutation_count * \
                row["maxSingleMutationPlaintextBytesEstimate"]:
            return False
        expected_candidate = row["plaintextBytesEstimate"] + \
            row["recordCount"] * FUTURE_RECORD_FRAMING_ESTIMATE_BYTES
        if expected_candidate > MAX_METRIC_NUMBER or \
                row["candidateRecordPlaintextBytesEstimate"] != expected_candidate:
            return False
        expected_coverage: Dict[str, int] = {}
        for mutation_class, count in by_class.items():
            coverage = mutation_index[mutation_class].currentWalCoverage.value
            expected_coverage[coverage] = expected_coverage.get(coverage, 0) + count
        if by_coverage != expected_coverage:
            return False

    distribution_keys = {
        "mutationCount", "plaintextBytesEstimate",
        "candidateRecordPlaintextBytesEstimate",
        "maxSingleMutationPlaintextBytesEstimate", "plaintextBytesHistogram",
        "latencyMsHistogram"}
    distribution_numbers = distribution_keys - {
        "plaintextBytesHistogram", "latencyMsHistogram"}
    for day, daily in daily_distributions.items():
        if not isinstance(day, str):
            return False
        try:
            parsed_day = dt.date.fromisoformat(day)
        except ValueError:
            return False
        if parsed_day.isoformat() != day or parsed_day > updated_at.date() or \
                not isinstance(daily, dict) or \
                not daily or not set(daily) <= known_mutations:
            return False
        for row in daily.values():
            if not _exact_keys(row, distribution_keys) or any(
                    not _valid_nonnegative_int(row[key])
                    for key in distribution_numbers):
                return False
            mutation_count = row["mutationCount"]
            if mutation_count == 0 or \
                    row["candidateRecordPlaintextBytesEstimate"] < \
                    row["plaintextBytesEstimate"] or \
                    (row["candidateRecordPlaintextBytesEstimate"] -
                     row["plaintextBytesEstimate"]) % \
                    FUTURE_RECORD_FRAMING_ESTIMATE_BYTES or \
                    row["maxSingleMutationPlaintextBytesEstimate"] > \
                    row["plaintextBytesEstimate"] or \
                    row["plaintextBytesEstimate"] > mutation_count * \
                    row["maxSingleMutationPlaintextBytesEstimate"] or \
                    not valid_histogram(
                        row["plaintextBytesHistogram"], mutation_count) or \
                    not valid_histogram(row["latencyMsHistogram"], mutation_count):
                return False

    checkpoint_keys = {
        "observedAt", "success", "checkpointSerializedBytes",
        "sectionSerializedBytes", "dominantSectionSerializedBytes",
        "sourceAssemblyMs", "sectionAccountingMs", "sealMs",
        "atomicWriteFsyncReadbackMs", "peakRssBytes", "localWalBytes",
        "localWalRecordCount", "localWalHighWater",
        "legacyRemoteAckSequence", "legacyRemoteAckAt",
        "legacyRemoteAckIsExactWalDurability", "legacyPredictionsJsonl"}
    checkpoint_ints = {
        "checkpointSerializedBytes", "localWalBytes", "localWalRecordCount",
        "localWalHighWater", "legacyRemoteAckSequence"}
    checkpoint_durations = {
        "sourceAssemblyMs", "sectionAccountingMs", "sealMs",
        "atomicWriteFsyncReadbackMs"}
    allowed_sections = {key for row in argus_recovery_registry.states()
                        for key in row.checkpointKeys}
    prediction_keys = {"configured", "exists", "bytes", "recordCount",
                       "complete"}
    previous_checkpoint: Optional[dt.datetime] = None
    for row in value["checkpointSamples"]:
        if not _exact_keys(row, checkpoint_keys) or \
                not _valid_timestamp(row["observedAt"]) or \
                not isinstance(row["success"], bool) or any(
                    not _valid_nonnegative_int(row[key])
                    for key in checkpoint_ints) or any(
                    not _valid_nonnegative_number(row[key])
                    for key in checkpoint_durations) or \
                (row["peakRssBytes"] is not None and
                 not _valid_nonnegative_int(row["peakRssBytes"])) or \
                row["legacyRemoteAckIsExactWalDurability"] is not False or \
                not _valid_timestamp(row["legacyRemoteAckAt"], optional=True):
            return False
        observed = _parse_iso(row["observedAt"])
        if observed > updated_at or \
                (previous_checkpoint is not None and
                 observed < previous_checkpoint):
            return False
        previous_checkpoint = observed
        ack_at = _parse_iso(row["legacyRemoteAckAt"])
        if ack_at is not None and ack_at > observed:
            return False
        sections = row["sectionSerializedBytes"]
        dominant = row["dominantSectionSerializedBytes"]
        if not isinstance(sections, dict) or not set(sections) <= allowed_sections or \
                any(not _valid_nonnegative_int(size)
                    for size in sections.values()) or \
                not _exact_keys(dominant, set(LARGE_SECTION_KEYS)) or any(
                    not _valid_nonnegative_int(size)
                    for size in dominant.values()) or \
                any(dominant[key] != sections.get(key, 0)
                    for key in LARGE_SECTION_KEYS) or \
                sum(sections.values()) > row["checkpointSerializedBytes"]:
            return False
        predictions = row["legacyPredictionsJsonl"]
        if not _exact_keys(predictions, prediction_keys) or any(
                not isinstance(predictions[key], bool)
                for key in ("configured", "exists", "complete")) or \
                not _valid_nonnegative_int(predictions["bytes"]) or \
                not _valid_nonnegative_int(predictions["recordCount"]):
            return False
        if (not predictions["exists"] and (
                predictions["bytes"] or predictions["recordCount"])) or \
                (predictions["exists"] and not predictions["configured"]) or \
                predictions["recordCount"] > predictions["bytes"]:
            return False
    # Any value that can be produced by the bounded public rollups must remain
    # an exact, non-saturating JSON integer. Reject the whole artifact instead
    # of independently clipping fields and breaking aggregate relationships.
    for minutes in (5, 15, 30):
        for row in _rollup_buckets(value["buckets"], minutes):
            if any(not _valid_nonnegative_int(item)
                   for key, item in row.items()
                   if key not in ("intervalStart", "byMutationClass")) or \
                    any(not _valid_nonnegative_int(item)
                        for item in row["byMutationClass"].values()):
                return False
    projected_distributions: Dict[str, Dict[str, Any]] = {}
    for daily in daily_distributions.values():
        for key, distribution in daily.items():
            public_key = _public_telemetry_identifier("mutation", key)
            target = projected_distributions.setdefault(
                public_key, _new_distribution())
            _merge_distribution(target, distribution)
    for distribution in projected_distributions.values():
        scalar_keys = (
            "mutationCount", "plaintextBytesEstimate",
            "candidateRecordPlaintextBytesEstimate",
            "maxSingleMutationPlaintextBytesEstimate")
        if any(not _valid_nonnegative_int(distribution[key])
               for key in scalar_keys) or any(
                   not _valid_nonnegative_int(count)
                   for field in ("plaintextBytesHistogram",
                                 "latencyMsHistogram")
                   for count in distribution[field].values()):
            return False
    return True


def _bucket_start(value: dt.datetime, minutes: int = BUCKET_MINUTES) -> dt.datetime:
    epoch = int(value.timestamp())
    width = int(minutes) * 60
    return dt.datetime.fromtimestamp(epoch - epoch % width, tz=UTC)


def _new_bucket(start: dt.datetime) -> Dict[str, Any]:
    return {
        "bucketStart": _iso(start),
        "mutationCount": 0,
        "transitionCount": 0,
        "recordCount": 0,
        "successCount": 0,
        "failureCount": 0,
        "plaintextBytesEstimate": 0,
        "candidateRecordPlaintextBytesEstimate": 0,
        "maxSingleMutationPlaintextBytesEstimate": 0,
        "byMutationClass": {},
        "byWalCoverage": {},
    }


def _rollup_buckets(buckets: Iterable[Mapping[str, Any]], minutes: int
                    ) -> List[Dict[str, Any]]:
    rows: Dict[str, Dict[str, Any]] = {}
    for bucket in buckets:
        parsed = _parse_iso(bucket.get("bucketStart"))
        if parsed is None:
            continue
        key = _iso(_bucket_start(parsed, minutes))
        row = rows.setdefault(key, {
            "intervalStart": key, "mutationCount": 0, "transitionCount": 0,
            "recordCount": 0, "successCount": 0, "failureCount": 0,
            "plaintextBytesEstimate": 0,
            "candidateSegmentPlaintextBytesEstimate": 0,
            "maxSingleMutationPlaintextBytesEstimate": 0,
            "byMutationClass": {},
        })
        for field in ("mutationCount", "transitionCount", "recordCount",
                      "successCount", "failureCount", "plaintextBytesEstimate"):
            row[field] += int(bucket.get(field) or 0)
        row["candidateSegmentPlaintextBytesEstimate"] += int(
            bucket.get("candidateRecordPlaintextBytesEstimate") or 0)
        row["maxSingleMutationPlaintextBytesEstimate"] = max(
            row["maxSingleMutationPlaintextBytesEstimate"],
            int(bucket.get("maxSingleMutationPlaintextBytesEstimate") or 0))
        projected_counts = _public_identifier_counts(
            "mutation", bucket.get("byMutationClass") or {})
        for mutation_class, count in projected_counts.items():
            row["byMutationClass"][mutation_class] = int(
                row["byMutationClass"].get(mutation_class) or 0) + count
    return [rows[key] for key in sorted(rows)]


def _numeric_summary(values: Iterable[int]) -> Dict[str, Optional[int]]:
    ordered = sorted(int(value) for value in values)
    if not ordered:
        return {"p50": None, "p95": None, "p99": None, "max": None}

    def at(q: float) -> int:
        return ordered[max(0, int(math.ceil(len(ordered) * q)) - 1)]
    return {"p50": at(.50), "p95": at(.95), "p99": at(.99),
            "max": ordered[-1]}


def _interval_statistics(buckets: Iterable[Mapping[str, Any]], minutes: int
                         ) -> Dict[str, Any]:
    rows = _rollup_buckets(buckets, minutes)
    return {
        "intervalMinutes": minutes,
        "intervalCount": len(rows),
        "mutationCount": _numeric_summary(row["mutationCount"] for row in rows),
        "plaintextBytesEstimate": _numeric_summary(
            row["plaintextBytesEstimate"] for row in rows),
        "recordCount": _numeric_summary(row["recordCount"] for row in rows),
        "candidateSegmentPlaintextBytesEstimate": _numeric_summary(
            row["candidateSegmentPlaintextBytesEstimate"] for row in rows),
        "latest": rows[-1] if rows else None,
        "encryptedBytesClaimed": False,
    }


def _mutation_increment_fits_public_aggregates(
        document: Mapping[str, Any], *, observed: dt.datetime,
        mutation_class: str, size: int, transitions: int, records: int,
        candidate: int, success: bool) -> bool:
    """Bound the derived public totals without scanning the whole document.

    The interval check touches at most six five-minute buckets. The distribution
    check touches the fixed 32-day registry matrix. This keeps the WAL-adjacent
    metadata path independent of retained checkpoint samples/recent history.
    """
    interval_increments = {
        "mutationCount": 1,
        "transitionCount": transitions,
        "recordCount": records,
        "successCount": 1 if success else 0,
        "failureCount": 0 if success else 1,
        "plaintextBytesEstimate": size,
        "candidateRecordPlaintextBytesEstimate": candidate,
    }
    buckets = document["buckets"]

    def lower_bound(key: str) -> int:
        low, high = 0, len(buckets)
        while low < high:
            middle = (low + high) // 2
            if buckets[middle]["bucketStart"] < key:
                low = middle + 1
            else:
                high = middle
        return low

    for minutes in (5, 15, 30):
        target = _bucket_start(observed, minutes)
        target_end = target + dt.timedelta(minutes=minutes)
        totals = {key: 0 for key in interval_increments}
        start_index = lower_bound(_iso(target))
        end_index = lower_bound(_iso(target_end))
        for bucket in buckets[start_index:end_index]:
            for key in totals:
                totals[key] += int(bucket[key])
        if any(totals[key] + increment > MAX_METRIC_NUMBER
               for key, increment in interval_increments.items()):
            return False

    public_label = _public_telemetry_identifier("mutation", mutation_class)
    distribution_totals = {
        "mutationCount": 0,
        "plaintextBytesEstimate": 0,
        "candidateRecordPlaintextBytesEstimate": 0,
    }
    for daily in document["dailyDistributions"].values():
        for identifier, distribution in daily.items():
            if _public_telemetry_identifier("mutation", identifier) != \
                    public_label:
                continue
            for key in distribution_totals:
                distribution_totals[key] += int(distribution[key])
    distribution_increments = {
        "mutationCount": 1,
        "plaintextBytesEstimate": size,
        "candidateRecordPlaintextBytesEstimate": candidate,
    }
    return all(distribution_totals[key] + increment <= MAX_METRIC_NUMBER
               for key, increment in distribution_increments.items())


def _public_checkpoint_measurement(row: Optional[Mapping[str, Any]]
                                   ) -> Optional[Dict[str, Any]]:
    """Reconstruct a fixed typed projection; never return the persisted row."""
    if row is None:
        return None
    sections = _public_identifier_counts(
        "checkpoint_section", row["sectionSerializedBytes"])
    dominant = _public_identifier_counts(
        "checkpoint_section", row["dominantSectionSerializedBytes"])
    return {
        "observedAt": _iso(_parse_iso(row["observedAt"])),
        "success": bool(row["success"]),
        "checkpointSerializedBytes": int(row["checkpointSerializedBytes"]),
        "sectionSerializedBytes": sections,
        "dominantSectionSerializedBytes": dominant,
        "sourceAssemblyMs": float(row["sourceAssemblyMs"]),
        "sectionAccountingMs": float(row["sectionAccountingMs"]),
        "sealMs": float(row["sealMs"]),
        "atomicWriteFsyncReadbackMs": float(
            row["atomicWriteFsyncReadbackMs"]),
        "peakRssBytes": (None if row["peakRssBytes"] is None else
                         int(row["peakRssBytes"])),
        "localWalBytes": int(row["localWalBytes"]),
        "localWalRecordCount": int(row["localWalRecordCount"]),
        "localWalHighWater": int(row["localWalHighWater"]),
        "legacyRemoteAckSequence": int(row["legacyRemoteAckSequence"]),
        "legacyRemoteAckAt": (None if row["legacyRemoteAckAt"] is None else
                              _iso(_parse_iso(row["legacyRemoteAckAt"]))),
        "legacyRemoteAckIsExactWalDurability": False,
    }


def public_recovery_measurement_unavailable() -> Dict[str, Any]:
    """Return a fixed conservative response when shadow diagnostics fail."""
    return {
        "schemaVersion": SCHEMA,
        "status": "SHADOW",
        "coverage": "INCOMPLETE",
        "authoritative": False,
        "hardRpoClaim": None,
        "hardRpoClaimPermitted": False,
        "latestObservedLocalMutationAt": None,
        "latestObservedLocalMutationAtIsBucketApproximation": True,
        "oldestObservedAuthoritativeMutationAgeSeconds": None,
        "oldestAgeIsBucketApproximation": True,
        "latestLegacyRemoteAckAt": None,
        "legacyRemoteAckSequence": 0,
        "localWalHighWater": 0,
        "legacySequenceLag": 0,
        "legacyRemoteAckIsExactWalDurability": False,
        "retentionDays": RETENTION_DAYS,
        "acceptanceClockStarted": False,
        "loadStatus": "unavailable",
        "measurementErrors": 1,
        "intervalStatistics": {
            str(minutes): _interval_statistics([], minutes)
            for minutes in (5, 15, 30)},
        "mutationDistributions": {},
        "latestCheckpointMeasurement": None,
        "candidateWalEstimatesArePlaintextOnly": True,
        "candidateWalEstimateCoverage": "INCOMPLETE",
        "encryptedWalBytesClaimed": False,
    }


def exact_cold_recovery_diagnostic(*, checkpoint_mode: str,
                                   legacy_remote_status: str,
                                   encrypted_sidecar_status: str,
                                   stage1_state: str,
                                   mutation_coverage_complete: bool = False,
                                   exact_full_generation_verified: bool = False,
                                   exact_wal_tail_verified: bool = False,
                                   exact_authority_manifest_verified: bool = False
                                   ) -> Dict[str, Any]:
    exact_inputs = (mutation_coverage_complete,
                    exact_full_generation_verified,
                    exact_wal_tail_verified,
                    exact_authority_manifest_verified)
    # A legacy-only selector cannot become exact merely because scalar booleans
    # were accidentally supplied by a caller.
    proven = all(exact_inputs) and checkpoint_mode != "legacy_only"
    any_shadow = any(exact_inputs)
    status = "proven" if proven else ("shadow" if any_shadow else "not_proven")
    reasons = []
    if checkpoint_mode == "legacy_only":
        reasons.append("legacy_checkpoint_mode")
    if encrypted_sidecar_status in ("not_configured", "not_issued", "absent", ""):
        reasons.append("encrypted_sidecar_not_current_authority")
    if not mutation_coverage_complete:
        reasons.append("authoritative_mutation_coverage_incomplete")
    if not exact_full_generation_verified:
        reasons.append("exact_full_generation_not_verified")
    if not exact_wal_tail_verified:
        reasons.append("exact_remote_wal_tail_not_verified")
    if not exact_authority_manifest_verified:
        reasons.append("exact_authority_manifest_not_verified")
    return {
        "status": status,
        "authoritative": False,
        "legacyRemoteHealth": legacy_remote_status or "unknown",
        "legacyRemoteHealthIsExactColdRecoveryProof": False,
        "checkpointMode": checkpoint_mode or "unknown",
        "encryptedSidecarStatus": encrypted_sidecar_status or "unknown",
        "stage1State": stage1_state or "unknown",
        "mutationCoverage": ("complete" if mutation_coverage_complete
                             else "incomplete"),
        "hardRpoClaimPermitted": bool(proven),
        "reasonCodes": sorted(set(reasons)),
    }


class RecoveryMeasurementStore:
    """Thread-safe bounded aggregator with optional atomic local persistence."""

    def __init__(self, path: Optional[str], *,
                 clock: Callable[[], dt.datetime] = _utc_now):
        self.path = os.path.abspath(path) if path else None
        self.clock = clock
        self._lock = threading.Lock()
        self._document: Optional[Dict[str, Any]] = None
        self._load_status = "not_loaded"
        self._last_persist_monotonic = 0.0

    def _ensure_loaded(self) -> None:
        if self._document is not None:
            return
        now = self.clock()
        self._document = _empty_document(now)
        if not self.path:
            self._load_status = "disabled"
            return
        try:
            if os.path.islink(self.path):
                self._load_status = "invalid_symlink"
                return
            if not os.path.exists(self.path):
                self._load_status = "not_found"
                return
            if os.path.getsize(self.path) > MAX_PERSISTED_BYTES:
                self._load_status = "invalid_oversized"
                return
            with open(self.path, encoding="utf-8") as handle:
                loaded = json.load(handle)
            if not _validate_document(loaded):
                self._load_status = "invalid_schema"
                return
            self._document = loaded
            self._load_status = "loaded"
            self._prune(now)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError,
                RecursionError):
            self._load_status = "invalid_or_partial"

    def _prune(self, now: dt.datetime) -> None:
        assert self._document is not None
        cutoff = now.astimezone(UTC) - dt.timedelta(days=RETENTION_DAYS)
        self._document["buckets"] = [
            row for row in self._document.get("buckets") or []
            if (_parse_iso(row.get("bucketStart")) or dt.datetime.min.replace(
                tzinfo=UTC)) >= cutoff][-MAX_BUCKETS:]
        self._document["recentMutations"] = [
            row for row in self._document.get("recentMutations") or []
            if (_parse_iso(row.get("observedAt")) or dt.datetime.min.replace(
                tzinfo=UTC)) >= cutoff][-MAX_RECENT_MUTATIONS:]
        self._document["checkpointSamples"] = [
            row for row in self._document.get("checkpointSamples") or []
            if (_parse_iso(row.get("observedAt")) or dt.datetime.min.replace(
                tzinfo=UTC)) >= cutoff][-MAX_CHECKPOINT_SAMPLES:]
        cutoff_day = cutoff.date().isoformat()
        daily = self._document.get("dailyDistributions") or {}
        self._document["dailyDistributions"] = {
            key: daily[key] for key in sorted(daily)
            if key >= cutoff_day}
        if len(self._document["dailyDistributions"]) > \
                MAX_DAILY_DISTRIBUTIONS:
            keys = sorted(self._document["dailyDistributions"])[
                -MAX_DAILY_DISTRIBUTIONS:]
            self._document["dailyDistributions"] = {
                key: self._document["dailyDistributions"][key] for key in keys}
        prior_updated = _parse_iso(self._document.get("updatedAt"))
        self._document["updatedAt"] = _iso(max(
            now.astimezone(UTC), prior_updated or now.astimezone(UTC)))

    def _note_error(self) -> None:
        if self._document is not None:
            self._document["measurementErrors"] = min(
                MAX_METRIC_NUMBER, int(
                    self._document.get("measurementErrors") or 0) + 1)

    def record_mutation(self, mutation_class: str, *,
                        plaintext_bytes_estimate: int,
                        transition_count: int = 1,
                        record_count: int = 1,
                        latency_ms: float = 0.0,
                        success: bool = True,
                        observed_at: Optional[dt.datetime] = None,
                        local_sequence: Optional[int] = None) -> bool:
        """Record metadata only; unknown classes fail loud to the caller."""
        definition = argus_recovery_registry.mutation_by_class().get(
            str(mutation_class))
        if definition is None:
            raise ValueError("unregistered_mutation_class")
        if not _valid_nonnegative_int(plaintext_bytes_estimate) or \
                not _valid_nonnegative_int(transition_count) or \
                not _valid_nonnegative_int(record_count) or \
                not _valid_nonnegative_number(latency_ms) or \
                not isinstance(success, bool) or \
                (local_sequence is not None and
                 not _valid_nonnegative_int(local_sequence)):
            raise ValueError("invalid_recovery_measurement")
        size = plaintext_bytes_estimate
        transitions = transition_count
        records = record_count
        latency = float(latency_ms)
        observed = observed_at or self.clock()
        if not isinstance(observed, dt.datetime):
            raise ValueError("invalid_recovery_measurement")
        if observed.tzinfo is None:
            observed = observed.replace(tzinfo=UTC)
        candidate = size + records * FUTURE_RECORD_FRAMING_ESTIMATE_BYTES
        if candidate > MAX_METRIC_NUMBER or \
                not _valid_timestamp(_iso(observed)) or \
                observed.astimezone(UTC) > \
                _utc_now() + dt.timedelta(days=1) or \
                observed.astimezone(UTC) < \
                self.clock().astimezone(UTC) - dt.timedelta(
                    days=RETENTION_DAYS):
            raise ValueError("invalid_recovery_measurement")
        state_index = argus_recovery_registry.state_by_id()
        safe_targets = [target for target in definition.targetStateIds
                        if state_index[target].allowedInTelemetry]
        redacted_targets = len(definition.targetStateIds) - len(safe_targets)
        with self._lock:
            self._ensure_loaded()
            assert self._document is not None
            previous = {
                key: self._document[key] for key in (
                    "buckets", "dailyDistributions", "recentMutations",
                    "checkpointSamples", "updatedAt")}
            try:
                self._prune(observed)
                start = _bucket_start(observed)
                key = _iso(start)
                buckets = self._document["buckets"]
                bucket = next((row for row in reversed(buckets)
                               if row.get("bucketStart") == key), None)
                if bucket is None:
                    bucket = _new_bucket(start)
                day = observed.astimezone(UTC).date().isoformat()
                all_daily = self._document["dailyDistributions"]
                if day not in all_daily and len(all_daily) >= \
                        MAX_DAILY_DISTRIBUTIONS:
                    del all_daily[sorted(all_daily)[0]]
                daily = all_daily.get(day) or {}
                distribution = daily.get(definition.mutationClass) or \
                    _new_distribution()
                increments = (
                    (bucket["mutationCount"], 1),
                    (bucket["transitionCount"], transitions),
                    (bucket["recordCount"], records),
                    (bucket["successCount" if success else "failureCount"], 1),
                    (bucket["plaintextBytesEstimate"], size),
                    (bucket["candidateRecordPlaintextBytesEstimate"], candidate),
                    (int(bucket["byMutationClass"].get(
                        definition.mutationClass) or 0), 1),
                    (int(bucket["byWalCoverage"].get(
                        definition.currentWalCoverage.value) or 0), 1),
                    (distribution["mutationCount"], 1),
                    (distribution["plaintextBytesEstimate"], size),
                    (distribution["candidateRecordPlaintextBytesEstimate"],
                     candidate),
                )
                if any(current + increment > MAX_METRIC_NUMBER
                       for current, increment in increments) or not \
                        _mutation_increment_fits_public_aggregates(
                            self._document, observed=observed,
                            mutation_class=definition.mutationClass,
                            size=size, transitions=transitions,
                            records=records, candidate=candidate,
                            success=success):
                    raise ValueError("invalid_recovery_measurement")
            except Exception:
                self._document.update(previous)
                raise
            if bucket not in buckets:
                buckets.append(bucket)
                buckets.sort(key=lambda row: str(row.get("bucketStart") or ""))
                self._document["buckets"] = buckets[-MAX_BUCKETS:]
            bucket["mutationCount"] += 1
            bucket["transitionCount"] += transitions
            bucket["recordCount"] += records
            bucket["successCount" if success else "failureCount"] += 1
            bucket["plaintextBytesEstimate"] += size
            bucket["candidateRecordPlaintextBytesEstimate"] += candidate
            bucket["maxSingleMutationPlaintextBytesEstimate"] = max(
                bucket["maxSingleMutationPlaintextBytesEstimate"], size)
            bucket["byMutationClass"][definition.mutationClass] = int(
                bucket["byMutationClass"].get(definition.mutationClass) or 0) + 1
            coverage = definition.currentWalCoverage.value
            bucket["byWalCoverage"][coverage] = int(
                bucket["byWalCoverage"].get(coverage) or 0) + 1
            distribution = self._document["dailyDistributions"].setdefault(
                day, {}).setdefault(definition.mutationClass, _new_distribution())
            distribution["mutationCount"] += 1
            distribution["plaintextBytesEstimate"] += size
            distribution["candidateRecordPlaintextBytesEstimate"] += candidate
            distribution["maxSingleMutationPlaintextBytesEstimate"] = max(
                distribution["maxSingleMutationPlaintextBytesEstimate"], size)
            _histogram_add(distribution["plaintextBytesHistogram"], size)
            _histogram_add(distribution["latencyMsHistogram"], latency)
            recent = {
                "observedAt": _iso(observed),
                "mutationClass": definition.mutationClass,
                "targetStateIds": safe_targets,
                "redactedTargetCount": redacted_targets,
                "plaintextBytesEstimate": size,
                "candidateRecordPlaintextBytesEstimate": candidate,
                "transitionCount": transitions,
                "recordCount": records,
                "latencyMs": round(latency, 3),
                "success": bool(success),
                "currentWalCoverage": coverage,
            }
            if local_sequence is not None:
                recent["localSequence"] = max(0, int(local_sequence))
            self._document["recentMutations"].append(recent)
            self._document["recentMutations"].sort(
                key=lambda row: str(row.get("observedAt") or ""))
            self._document["recentMutations"] = self._document[
                "recentMutations"][-MAX_RECENT_MUTATIONS:]
            prior_updated = _parse_iso(self._document.get("updatedAt"))
            self._document["updatedAt"] = _iso(max(
                observed.astimezone(UTC), prior_updated or
                observed.astimezone(UTC)))
        # Hot mutations update memory only. Persistence is forced by the
        # already-existing checkpoint boundary; diagnostics never add WAL-path
        # fsync latency per record.
        return True

    def record_checkpoint(self, *, checkpoint_bytes: int,
                          section_sizes: Mapping[str, int],
                          source_assembly_ms: float,
                          section_accounting_ms: float,
                          seal_ms: float,
                          atomic_write_readback_ms: float,
                          local_wal_bytes: int,
                          local_wal_record_count: int,
                          local_wal_high_water: int,
                          legacy_remote_ack_sequence: int,
                          legacy_remote_ack_at: Optional[str],
                          legacy_predictions: Mapping[str, Any],
                          success: bool = True,
                          observed_at: Optional[dt.datetime] = None) -> bool:
        observed = observed_at or self.clock()
        if not isinstance(observed, dt.datetime):
            raise ValueError("invalid_recovery_measurement")
        if observed.tzinfo is None:
            observed = observed.replace(tzinfo=UTC)
        allowed_sections = {key for row in argus_recovery_registry.states()
                            for key in row.checkpointKeys}
        parsed_ack_at = _parse_iso(legacy_remote_ack_at)
        integer_inputs = (
            checkpoint_bytes, local_wal_bytes, local_wal_record_count,
            local_wal_high_water, legacy_remote_ack_sequence)
        duration_inputs = (
            source_assembly_ms, section_accounting_ms, seal_ms,
            atomic_write_readback_ms)
        if any(not _valid_nonnegative_int(value) for value in integer_inputs) or \
                any(not _valid_nonnegative_number(value)
                    for value in duration_inputs) or \
                not isinstance(success, bool) or \
                not _valid_timestamp(_iso(observed)) or \
                observed.astimezone(UTC) > \
                _utc_now() + dt.timedelta(days=1) or \
                observed.astimezone(UTC) < \
                self.clock().astimezone(UTC) - dt.timedelta(
                    days=RETENTION_DAYS) or \
                (legacy_remote_ack_at is not None and (
                    not _valid_timestamp(legacy_remote_ack_at) or
                    parsed_ack_at is None or parsed_ack_at > observed)):
            raise ValueError("invalid_recovery_measurement")
        safe_sections: Dict[str, int] = {}
        for key, value in section_sizes.items():
            if str(key) not in allowed_sections:
                continue
            if not _valid_nonnegative_int(value):
                raise ValueError("invalid_recovery_measurement")
            safe_sections[str(key)] = value
        if sum(safe_sections.values()) > checkpoint_bytes:
            raise ValueError("invalid_recovery_measurement")
        prediction_keys = {
            "configured", "exists", "bytes", "recordCount", "complete"}
        prediction_allowed_keys = prediction_keys | {"reason"}
        if not isinstance(legacy_predictions, Mapping) or \
                not prediction_keys <= set(legacy_predictions) or \
                not set(legacy_predictions) <= prediction_allowed_keys or \
                ("reason" in legacy_predictions and
                 legacy_predictions["reason"] not in (
                     "measurement_maximum_exceeded",
                     "measurement_io_error")) or any(
                not isinstance(legacy_predictions[key], bool)
                for key in ("configured", "exists", "complete")) or \
                not _valid_nonnegative_int(legacy_predictions["bytes"]) or \
                not _valid_nonnegative_int(
                    legacy_predictions["recordCount"]):
            raise ValueError("invalid_recovery_measurement")
        if (not legacy_predictions["exists"] and (
                legacy_predictions["bytes"] or
                legacy_predictions["recordCount"])) or \
                (legacy_predictions["exists"] and
                 not legacy_predictions["configured"]) or \
                legacy_predictions["recordCount"] > \
                legacy_predictions["bytes"]:
            raise ValueError("invalid_recovery_measurement")
        sample = {
            "observedAt": _iso(observed), "success": success,
            "checkpointSerializedBytes": checkpoint_bytes,
            "sectionSerializedBytes": dict(sorted(safe_sections.items())),
            "dominantSectionSerializedBytes": {
                key: safe_sections.get(key, 0)
                for key in LARGE_SECTION_KEYS},
            "sourceAssemblyMs": round(float(source_assembly_ms), 3),
            "sectionAccountingMs": round(float(section_accounting_ms), 3),
            "sealMs": round(float(seal_ms), 3),
            # Existing writer combines stream serialization, file flush/fsync,
            # hash readback, replace and parent fsync; do not invent a split.
            "atomicWriteFsyncReadbackMs": round(
                float(atomic_write_readback_ms), 3),
            "peakRssBytes": (lambda value: value if
                              value is None or
                              _valid_nonnegative_int(value) else None)(
                                  peak_rss_bytes()),
            "localWalBytes": local_wal_bytes,
            "localWalRecordCount": local_wal_record_count,
            "localWalHighWater": local_wal_high_water,
            "legacyRemoteAckSequence": legacy_remote_ack_sequence,
            "legacyRemoteAckAt": (_iso(parsed_ack_at)
                                  if parsed_ack_at is not None else None),
            "legacyRemoteAckIsExactWalDurability": False,
            "legacyPredictionsJsonl": {
                key: legacy_predictions[key] for key in sorted(prediction_keys)
            },
        }
        with self._lock:
            self._ensure_loaded()
            assert self._document is not None
            before = json.loads(json.dumps(
                self._document, ensure_ascii=False, allow_nan=False))
            self._prune(observed)
            self._document["checkpointSamples"].append(sample)
            self._document["checkpointSamples"].sort(
                key=lambda row: str(row.get("observedAt") or ""))
            self._document["checkpointSamples"] = self._document[
                "checkpointSamples"][-MAX_CHECKPOINT_SAMPLES:]
            prior_updated = _parse_iso(self._document.get("updatedAt"))
            self._document["updatedAt"] = _iso(max(
                observed.astimezone(UTC), prior_updated or
                observed.astimezone(UTC)))
            if not _validate_document(self._document):
                self._document = before
                raise ValueError("invalid_recovery_measurement")
        return self.maybe_persist(force=True) if self.path else True

    def _bounded_snapshot(self) -> Dict[str, Any]:
        assert self._document is not None
        snapshot = json.loads(json.dumps(self._document, ensure_ascii=False))
        # Size is an independent cap in addition to time/count retention.  Drop
        # oldest observations only; aggregates remain bounded by registry size.
        while _canonical_size(snapshot) > MAX_PERSISTED_BYTES:
            if snapshot.get("recentMutations"):
                snapshot["recentMutations"] = snapshot["recentMutations"][1:]
            elif snapshot.get("checkpointSamples"):
                snapshot["checkpointSamples"] = snapshot["checkpointSamples"][1:]
            elif snapshot.get("buckets"):
                snapshot["buckets"] = snapshot["buckets"][1:]
            else:
                raise ValueError("measurement_document_exceeds_bound")
        return snapshot

    def maybe_persist(self, *, force: bool = False) -> bool:
        if not self.path:
            return False
        now_mono = time.monotonic()
        if not force and now_mono - self._last_persist_monotonic < \
                PERSIST_INTERVAL_SECONDS:
            return False
        with self._lock:
            self._ensure_loaded()
            assert self._document is not None
            try:
                snapshot = self._bounded_snapshot()
                os.makedirs(os.path.dirname(self.path), exist_ok=True)
                argus_persistent_storage.atomic_write_json(
                    self.path, snapshot,
                    temp_directory=os.path.dirname(self.path),
                    validator=_validate_document,
                    maximum_bytes=MAX_PERSISTED_BYTES,
                    file_mode=0o600,
                    temp_label="recovery-measurement")
                self._last_persist_monotonic = now_mono
                self._load_status = "persisted"
                return True
            except Exception:
                self._note_error()
                self._load_status = "persist_failed"
                return False

    def public_summary(self, *, legacy_remote_ack_at: Optional[str] = None,
                       legacy_remote_ack_sequence: int = 0,
                       local_wal_high_water: int = 0) -> Dict[str, Any]:
        """Return the canonical allowlisted public recovery projection."""
        now = self.clock()
        with self._lock:
            self._ensure_loaded()
            assert self._document is not None
            self._prune(now)
            if not _validate_document(self._document):
                return public_recovery_measurement_unavailable()
            buckets = list(self._document["buckets"])
            raw_distributions: Dict[str, Dict[str, Any]] = {}
            mutation_index = argus_recovery_registry.mutation_by_class()
            for daily in self._document["dailyDistributions"].values():
                for key, value in sorted(daily.items()):
                    public_key = _public_telemetry_identifier("mutation", key)
                    _merge_distribution(
                        raw_distributions.setdefault(
                            public_key, _new_distribution()), value)
            distributions = {}
            for key, value in sorted(raw_distributions.items()):
                definition = mutation_index.get(key)
                distributions[key] = {
                    **_distribution_summary(value),
                    "currentWalCoverage": (
                        definition.currentWalCoverage.value
                        if definition is not None else "REDACTED_MIXED"),
                    "exactReplayPayloadCoverageObserved": bool(
                        definition is not None and
                        definition.currentWalCoverage ==
                        argus_recovery_registry.WalCoverage.COMPLETE),
                }
            recent = list(self._document["recentMutations"])
            checkpoints = list(self._document["checkpointSamples"])
            load_status = self._load_status
            errors = int(self._document.get("measurementErrors") or 0)
        # A redacted/private event must not leak its exact activity timestamp.
        # The public observation clock is therefore derived from the same
        # five-minute aggregate boundary used by the public interval report.
        latest_mutation_at = (
            _iso(_bucket_start(_parse_iso(recent[-1]["observedAt"])))
            if recent else None)
        parsed_runtime_ack = _parse_iso(legacy_remote_ack_at)
        safe_ack_at = (
            legacy_remote_ack_at if
            _valid_timestamp(legacy_remote_ack_at, optional=True) and
            (parsed_runtime_ack is None or
             parsed_runtime_ack <= now.astimezone(UTC) + dt.timedelta(days=1))
            else None)
        ack_time = _parse_iso(safe_ack_at)
        safe_ack_sequence = (legacy_remote_ack_sequence if
                             _valid_nonnegative_int(legacy_remote_ack_sequence)
                             else 0)
        safe_local_high_water = (local_wal_high_water if
                                 _valid_nonnegative_int(local_wal_high_water)
                                 else 0)
        oldest_after_ack = None
        for row in buckets:
            bucket_at = _parse_iso(row.get("bucketStart"))
            if int(row.get("mutationCount") or 0) and bucket_at is not None and \
                    (ack_time is None or bucket_at > ack_time):
                oldest_after_ack = bucket_at
                break
        age_seconds = None
        if oldest_after_ack is not None:
            age_seconds = max(0, int((now.astimezone(UTC) -
                                      oldest_after_ack).total_seconds()))
        return {
            "schemaVersion": SCHEMA,
            "status": "SHADOW",
            "coverage": "INCOMPLETE",
            "authoritative": False,
            "hardRpoClaim": None,
            "hardRpoClaimPermitted": False,
            "latestObservedLocalMutationAt": latest_mutation_at,
            "latestObservedLocalMutationAtIsBucketApproximation": True,
            "oldestObservedAuthoritativeMutationAgeSeconds": age_seconds,
            "oldestAgeIsBucketApproximation": True,
            "latestLegacyRemoteAckAt": safe_ack_at,
            "legacyRemoteAckSequence": int(safe_ack_sequence),
            "localWalHighWater": int(safe_local_high_water),
            "legacySequenceLag": max(
                0, int(safe_local_high_water) - int(safe_ack_sequence)),
            "legacyRemoteAckIsExactWalDurability": False,
            "retentionDays": RETENTION_DAYS,
            "acceptanceClockStarted": False,
            "loadStatus": load_status,
            "measurementErrors": errors,
            "intervalStatistics": {
                str(minutes): _interval_statistics(buckets, minutes)
                for minutes in (5, 15, 30)},
            "mutationDistributions": distributions,
            "latestCheckpointMeasurement": _public_checkpoint_measurement(
                checkpoints[-1] if checkpoints else None),
            "candidateWalEstimatesArePlaintextOnly": True,
            "candidateWalEstimateCoverage": "INCOMPLETE",
            "encryptedWalBytesClaimed": False,
        }

    def summary(self, *, legacy_remote_ack_at: Optional[str] = None,
                legacy_remote_ack_sequence: int = 0,
                local_wal_high_water: int = 0) -> Dict[str, Any]:
        """Compatibility name for the same canonical public projection."""
        return self.public_summary(
            legacy_remote_ack_at=legacy_remote_ack_at,
            legacy_remote_ack_sequence=legacy_remote_ack_sequence,
            local_wal_high_water=local_wal_high_water)


__all__ = [
    "RecoveryMeasurementStore", "checkpoint_section_sizes",
    "exact_cold_recovery_diagnostic", "measure_jsonl_metadata",
    "peak_rss_bytes", "public_recovery_measurement_unavailable",
    "serialized_size_estimate", "SCHEMA",
]
