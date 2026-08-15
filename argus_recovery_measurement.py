"""Standalone Recovery Phase A measurement core (private shadow state only).

This module has no runtime hooks, environment reads, routes, recovery claims, or
authority decisions.  It accepts typed measurement metadata, binds every
artifact to the accepted Registry Core policy, and produces deterministic,
strictly bounded JSON for an optional diagnostic storage adapter.
"""
from __future__ import annotations

from dataclasses import dataclass
import datetime as dt
import hashlib
import json
import math
import re
from typing import Any, Dict, Iterable, Iterator, Mapping, Optional, Sequence, Tuple

import argus_recovery_registry as registry


UTC = dt.timezone.utc
_REGISTRY_POLICY_PROVIDER = registry.registry_policy_sha256

SCHEMA_VERSION = "argus-recovery-measurement-shadow-v1"
RETENTION_POLICY_VERSION = "argus-recovery-measurement-retention-v1"
SAMPLING_POLICY_VERSION = "argus-recovery-checkpoint-sampling-policy-v1"
MODE = "SHADOW"
PROOF_STATUS = "NOT_PROVEN"
COVERAGE_STATUS = "INCOMPLETE"

MAX_SAFE_INTEGER = (1 << 53) - 1
MAX_PERSISTED_BYTES = 12 * 1024 * 1024
FIXED_SHELL_BUDGET = 64 * 1024
BUCKETS_BUDGET = 4 * 1024 * 1024
DAILY_DISTRIBUTIONS_BUDGET = 1536 * 1024
CHECKPOINT_SAMPLES_BUDGET = 5 * 1024 * 1024
RECENT_MUTATIONS_BUDGET = 1024 * 1024
RESERVE_BUDGET = MAX_PERSISTED_BYTES - (
    FIXED_SHELL_BUDGET + BUCKETS_BUDGET +
    DAILY_DISTRIBUTIONS_BUDGET + CHECKPOINT_SAMPLES_BUDGET +
    RECENT_MUTATIONS_BUDGET)

BUCKET_MINUTES = 5
RETENTION_DAYS = 31
MAX_BUCKETS = 8_928
MAX_RECENT_MUTATIONS = 256
MAX_CHECKPOINT_SAMPLES = 2_048
MAX_DAILY_DISTRIBUTIONS = 32
MAX_MUTATION_CLASSES = 27
MAX_HISTOGRAM_BINS = 25
MAX_CHECKPOINT_SECTION_KEYS = 48
MAX_DETAILED_SESSION_SAMPLES_PER_DAY = 2
FUTURE_WAL_RECORD_FRAMING_ESTIMATE_BYTES = 64
MAX_JSON_DEPTH = 12
MAX_JSON_NODES = 2_000_000
MAX_STREAM_SCALAR_CHARS = 128 * 1024
MAX_STREAM_CHUNK_BYTES = 1024 * 1024

_SHA256_RE = re.compile(r"[0-9a-f]{64}", re.ASCII)
_BUILD_SHA_RE = re.compile(r"[0-9a-f]{40}", re.ASCII)
_IDENTIFIER_RE = re.compile(
    r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", re.ASCII)

PLAINTEXT_BYTE_HISTOGRAM_UPPER_BOUNDS = (
    64, 128, 256, 512, 1_024, 2_048, 4_096, 8_192, 16_384,
    32_768, 65_536, 131_072, 262_144, 524_288, 1_048_576,
    2_097_152, 4_194_304, 8_388_608, 16_777_216, 33_554_432,
    67_108_864, 134_217_728, 268_435_456, 536_870_912,
    MAX_SAFE_INTEGER,
)
LATENCY_MICROS_HISTOGRAM_UPPER_BOUNDS = (
    100, 250, 500, 1_000, 2_000, 5_000, 10_000, 20_000, 50_000,
    100_000, 200_000, 500_000, 1_000_000, 2_000_000, 5_000_000,
    10_000_000, 20_000_000, 30_000_000, 60_000_000, 120_000_000,
    300_000_000, 600_000_000, 1_200_000_000, 3_600_000_000,
    MAX_SAFE_INTEGER,
)
assert len(PLAINTEXT_BYTE_HISTOGRAM_UPPER_BOUNDS) == MAX_HISTOGRAM_BINS
assert len(LATENCY_MICROS_HISTOGRAM_UPPER_BOUNDS) == MAX_HISTOGRAM_BINS

COVERAGE_CLASSIFICATIONS = frozenset({
    "OBSERVED_DURABLE", "OBSERVED_UNDURABLE", "UNKNOWN",
})
INVALIDATION_CODES = frozenset({
    "none", "artifact_invalid", "registry_policy_mismatch",
    "configuration_rejected", "persistence_failed",
})
DETAIL_REASONS = frozenset({
    "NONE", "JP_SESSION_BOUNDARY", "US_SESSION_BOUNDARY",
    "ACCOUNTING_SCHEMA_OR_BUILD_CHANGE", "OWNER_AUTHORIZED",
})
STATUS_CODES = frozenset({
    "ok", "recorded", "invalid_observation", "counter_overflow",
    "invalid_artifact", "registry_policy_mismatch", "size_rejected",
    "configuration_rejected", "not_found", "io_failure",
    "serialization_failure", "persisted", "persistence_failed",
})

_TOP_KEYS = frozenset({
    "schemaVersion", "measurementSchemaSha256", "measurementGenerationId",
    "registryPolicySha256", "instrumentationCoverageSha256",
    "producerBuildSha", "generationStartedAt", "createdAt", "updatedAt",
    "retentionPolicyVersion", "samplingPolicyVersion", "authoritative",
    "mode", "coverageStatus", "proofStatus", "acceptanceClockStarted",
    "coverage", "invalidation", "intervalBuckets", "dailyDistributions",
    "recentMutations", "checkpointSamples", "aggregateCounters",
})
_COVERAGE_KEYS = frozenset({
    "latestObservedAuthoritativeMutationAt",
    "oldestObservedUndurableMutationAt", "legacyRemoteAckAt",
    "instrumentedMutationClassIds", "expectedMutationClassCount",
    "allExpectedMutationClassesObserved",
})
_INVALIDATION_KEYS = frozenset({"code", "at"})
_AGGREGATE_KEYS = frozenset({
    "lifetimeMutationCount", "lifetimeEstimatedPlaintextBytes",
    "lifetimeRecordCount", "lifetimeSuccessCount", "lifetimeFailureCount",
    "retainedMutationCount", "retainedEstimatedPlaintextBytes",
    "retainedRecordCount", "retainedBucketCount",
    "retainedRecentMutationCount", "retainedCheckpointSampleCount",
    "droppedForRetentionCount", "measurementErrorCount",
    "persistenceFailureCount",
})
_BUCKET_KEYS = frozenset({
    "bucketStart", "mutationCount", "estimatedPlaintextBytes",
    "candidateWalPlaintextBytesEstimate", "recordCount",
    "latencyMicrosTotal", "successCount", "failureCount",
    "maxSingleMutationPlaintextBytesEstimate", "byMutationClass",
    "plaintextBytesHistogram", "latencyMicrosHistogram",
})
_DISTRIBUTION_KEYS = frozenset({
    "mutationCount", "estimatedPlaintextBytes",
    "candidateWalPlaintextBytesEstimate", "recordCount",
    "latencyMicrosTotal", "successCount", "failureCount",
    "maxSingleMutationPlaintextBytesEstimate", "plaintextBytesHistogram",
    "latencyMicrosHistogram",
})
_DAILY_KEYS = frozenset({"day", "byMutationClass"})
_RECENT_KEYS = frozenset({
    "observedAt", "mutationClassId", "targetStateIds",
    "estimatedPlaintextBytes", "candidateWalPlaintextBytesEstimate",
    "recordCount", "latencyMicros", "success", "coverageClassification",
    "currentWalCoverage", "localSequence",
})
_CHECKPOINT_KEYS = frozenset({
    "sampleId", "observedAt", "success", "detailed", "detailReason",
    "checkpointSerializedBytes", "sectionSerializedBytes",
    "serializationDurationMicros", "sectionAccountingDurationMicros",
    "writeSealDurationMicros", "fsyncReadbackDurationMicros",
    "peakRssBytes", "localWalBytes", "localWalRecords",
    "localWalHighWater", "legacyRemoteAckSequence", "legacyRemoteAckAt",
    "legacyRemoteAckIsExactWalDurability",
})

_SCHEMA_CONTRACT = {
    "schemaVersion": SCHEMA_VERSION,
    "topLevelKeys": sorted(_TOP_KEYS),
    "retentionPolicyVersion": RETENTION_POLICY_VERSION,
    "samplingPolicyVersion": SAMPLING_POLICY_VERSION,
    "limits": {
        "artifactBytes": MAX_PERSISTED_BYTES,
        "buckets": MAX_BUCKETS,
        "dailyDistributions": MAX_DAILY_DISTRIBUTIONS,
        "recentMutations": MAX_RECENT_MUTATIONS,
        "checkpointSamples": MAX_CHECKPOINT_SAMPLES,
        "mutationClasses": MAX_MUTATION_CLASSES,
        "histogramBins": MAX_HISTOGRAM_BINS,
        "checkpointSectionKeys": MAX_CHECKPOINT_SECTION_KEYS,
    },
    "authoritative": False,
    "mode": MODE,
    "proofStatus": PROOF_STATUS,
}
MEASUREMENT_SCHEMA_SHA256 = hashlib.sha256(json.dumps(
    _SCHEMA_CONTRACT, ensure_ascii=False, allow_nan=False, sort_keys=True,
    separators=(",", ":")).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    code: str


@dataclass(frozen=True)
class RetentionEvidence:
    input_rows: int
    retained_rows: int
    row_encodes: int
    collection_passes: int
    bulk_removed_rows: int
    final_document_encodes: int
    final_bytes: int


@dataclass(frozen=True)
class RetentionPlan:
    status: str
    artifact: Optional[Dict[str, Any]]
    canonical_bytes: Optional[bytes]
    evidence: RetentionEvidence


@dataclass(frozen=True)
class DetailedSamplingContext:
    jp_session_boundary: bool = False
    us_session_boundary: bool = False
    accounting_schema_changed: bool = False
    producer_build_changed: bool = False
    owner_authorized: bool = False
    detailed_session_samples_today: int = 0


@dataclass(frozen=True)
class DetailedSamplingDecision:
    requested: bool
    reason: str
    normal_session_limit: int


@dataclass(frozen=True)
class CheckpointAccounting:
    total_serialized_bytes: int
    registered_section_bytes: Dict[str, int]
    output_chunk_limit_bytes: int
    full_size_buffers: int


def _exact_dict(value: Any, keys: Iterable[str]) -> bool:
    return type(value) is dict and frozenset(value) == frozenset(keys)


def _valid_int(value: Any, *, maximum: int = MAX_SAFE_INTEGER) -> bool:
    return type(value) is int and 0 <= value <= maximum


def _checked_add(*values: int) -> Optional[int]:
    total = 0
    for value in values:
        if not _valid_int(value) or total > MAX_SAFE_INTEGER - value:
            return None
        total += value
    return total


def _valid_optional_int(value: Any) -> bool:
    return value is None or _valid_int(value)


def _valid_identifier(value: Any) -> bool:
    return type(value) is str and _IDENTIFIER_RE.fullmatch(value) is not None


def _valid_sha256(value: Any) -> bool:
    return type(value) is str and _SHA256_RE.fullmatch(value) is not None


def _parse_timestamp(value: Any) -> Optional[dt.datetime]:
    if type(value) is not str or len(value) != 20 or not value.endswith("Z"):
        return None
    try:
        parsed = dt.datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return None
    parsed = parsed.replace(tzinfo=UTC)
    return parsed if 2000 <= parsed.year <= 2100 else None


def canonical_timestamp(value: dt.datetime) -> str:
    if type(value) is not dt.datetime or value.tzinfo is None:
        raise ValueError("timestamp_invalid")
    normalized = value.astimezone(UTC).replace(microsecond=0)
    if not 2000 <= normalized.year <= 2100:
        raise ValueError("timestamp_invalid")
    return normalized.strftime("%Y-%m-%dT%H:%M:%SZ")


def _valid_timestamp(value: Any, *, optional: bool = False) -> bool:
    return value is None if optional and value is None else \
        _parse_timestamp(value) is not None


def _bounded_json_shape(value: Any) -> bool:
    """Reject hostile depth, cycles, non-string keys, and oversized containers."""
    stack = [(value, 0)]
    active: set[int] = set()
    nodes = 0
    while stack:
        current, depth = stack.pop()
        nodes += 1
        if nodes > MAX_JSON_NODES or depth > MAX_JSON_DEPTH:
            return False
        if type(current) is dict:
            if len(current) > 128:
                return False
            identity = id(current)
            if identity in active:
                return False
            active.add(identity)
            stack.append((_ContainerExit(identity), depth))
            for key, item in current.items():
                if type(key) is not str or len(key) > 128:
                    return False
                stack.append((item, depth + 1))
        elif type(current) is list:
            if len(current) > MAX_BUCKETS:
                return False
            identity = id(current)
            if identity in active:
                return False
            active.add(identity)
            stack.append((_ContainerExit(identity), depth))
            for item in current:
                stack.append((item, depth + 1))
        elif isinstance(current, _ContainerExit):
            active.discard(current.identity)
        elif current is not None and type(current) not in (
                str, int, float, bool):
            return False
        elif type(current) is float and not math.isfinite(current):
            return False
    return True


@dataclass(frozen=True)
class _ContainerExit:
    identity: int


def _empty_histogram() -> list[int]:
    return [0] * MAX_HISTOGRAM_BINS


def _histogram_index(value: int, bounds: Sequence[int]) -> int:
    low, high = 0, len(bounds)
    while low < high:
        middle = (low + high) // 2
        if value <= bounds[middle]:
            high = middle
        else:
            low = middle + 1
    return min(low, len(bounds) - 1)


def _histogram_with_increment(
        histogram: Sequence[int], value: int,
        bounds: Sequence[int]) -> Optional[list[int]]:
    if type(histogram) is not list or len(histogram) != MAX_HISTOGRAM_BINS:
        return None
    updated = list(histogram)
    index = _histogram_index(value, bounds)
    incremented = _checked_add(updated[index], 1)
    if incremented is None:
        return None
    updated[index] = incremented
    return updated


def _valid_histogram(value: Any, count: int) -> bool:
    return type(value) is list and len(value) == MAX_HISTOGRAM_BINS and \
        all(_valid_int(item) for item in value) and sum(value) == count


def _empty_distribution() -> Dict[str, Any]:
    return {
        "mutationCount": 0,
        "estimatedPlaintextBytes": 0,
        "candidateWalPlaintextBytesEstimate": 0,
        "recordCount": 0,
        "latencyMicrosTotal": 0,
        "successCount": 0,
        "failureCount": 0,
        "maxSingleMutationPlaintextBytesEstimate": 0,
        "plaintextBytesHistogram": _empty_histogram(),
        "latencyMicrosHistogram": _empty_histogram(),
    }


def _increment_distribution(
        current: Mapping[str, Any], *, estimated_bytes: int,
        candidate_bytes: int, record_count: int, latency_micros: int,
        success: bool) -> Optional[Dict[str, Any]]:
    updated = {
        "mutationCount": _checked_add(current["mutationCount"], 1),
        "estimatedPlaintextBytes": _checked_add(
            current["estimatedPlaintextBytes"], estimated_bytes),
        "candidateWalPlaintextBytesEstimate": _checked_add(
            current["candidateWalPlaintextBytesEstimate"], candidate_bytes),
        "recordCount": _checked_add(current["recordCount"], record_count),
        "latencyMicrosTotal": _checked_add(
            current["latencyMicrosTotal"], latency_micros),
        "successCount": _checked_add(
            current["successCount"], 1 if success else 0),
        "failureCount": _checked_add(
            current["failureCount"], 0 if success else 1),
        "maxSingleMutationPlaintextBytesEstimate": max(
            current["maxSingleMutationPlaintextBytesEstimate"],
            estimated_bytes),
        "plaintextBytesHistogram": _histogram_with_increment(
            current["plaintextBytesHistogram"], estimated_bytes,
            PLAINTEXT_BYTE_HISTOGRAM_UPPER_BOUNDS),
        "latencyMicrosHistogram": _histogram_with_increment(
            current["latencyMicrosHistogram"], latency_micros,
            LATENCY_MICROS_HISTOGRAM_UPPER_BOUNDS),
    }
    return None if any(value is None for value in updated.values()) else updated


def _valid_distribution(value: Any) -> bool:
    if not _exact_dict(value, _DISTRIBUTION_KEYS):
        return False
    scalar_keys = _DISTRIBUTION_KEYS - frozenset({
        "plaintextBytesHistogram", "latencyMicrosHistogram"})
    if any(not _valid_int(value[key]) for key in scalar_keys):
        return False
    count = value["mutationCount"]
    if count <= 0 or value["successCount"] + value["failureCount"] != count:
        return False
    if not _valid_histogram(value["plaintextBytesHistogram"], count) or \
            not _valid_histogram(value["latencyMicrosHistogram"], count):
        return False
    estimated = value["estimatedPlaintextBytes"]
    maximum = value["maxSingleMutationPlaintextBytesEstimate"]
    candidate = value["candidateWalPlaintextBytesEstimate"]
    records = value["recordCount"]
    expected_candidate = _checked_add(
        estimated, records * FUTURE_WAL_RECORD_FRAMING_ESTIMATE_BYTES)
    return maximum <= estimated <= count * maximum and \
        expected_candidate is not None and candidate == expected_candidate


def _valid_bucket(value: Any, mutation_ids: frozenset[str]) -> bool:
    if not _exact_dict(value, _BUCKET_KEYS) or \
            not _valid_timestamp(value["bucketStart"]):
        return False
    parsed = _parse_timestamp(value["bucketStart"])
    if parsed is None or parsed.second or parsed.microsecond or \
            parsed.minute % BUCKET_MINUTES:
        return False
    distribution = {
        key: value[key] for key in _DISTRIBUTION_KEYS
    }
    if not _valid_distribution(distribution):
        return False
    by_class = value["byMutationClass"]
    return type(by_class) is dict and 0 < len(by_class) <= MAX_MUTATION_CLASSES and \
        frozenset(by_class) <= mutation_ids and \
        all(_valid_int(count) and count > 0 for count in by_class.values()) and \
        sum(by_class.values()) == value["mutationCount"]


def _valid_daily(value: Any, mutation_ids: frozenset[str]) -> bool:
    if not _exact_dict(value, _DAILY_KEYS) or type(value["day"]) is not str:
        return False
    try:
        day = dt.date.fromisoformat(value["day"])
    except ValueError:
        return False
    by_class = value["byMutationClass"]
    return day.isoformat() == value["day"] and type(by_class) is dict and \
        0 < len(by_class) <= MAX_MUTATION_CLASSES and \
        frozenset(by_class) <= mutation_ids and \
        all(_valid_distribution(item) for item in by_class.values())


def _valid_recent(
        value: Any, mutations: Mapping[str, Any],
        created: dt.datetime, updated: dt.datetime) -> bool:
    if not _exact_dict(value, _RECENT_KEYS) or \
            not _valid_timestamp(value["observedAt"]):
        return False
    observed = _parse_timestamp(value["observedAt"])
    mutation = mutations.get(value["mutationClassId"])
    if observed is None or not created <= observed <= updated or mutation is None:
        return False
    targets = value["targetStateIds"]
    if type(targets) is not list or targets != list(mutation.targetStateIds):
        return False
    if type(value["success"]) is not bool or \
            value["coverageClassification"] not in COVERAGE_CLASSIFICATIONS or \
            value["currentWalCoverage"] != mutation.currentWalCoverage.value or \
            not _valid_optional_int(value["localSequence"]):
        return False
    for key in ("estimatedPlaintextBytes", "candidateWalPlaintextBytesEstimate",
                "recordCount", "latencyMicros"):
        if not _valid_int(value[key]):
            return False
    expected = _checked_add(
        value["estimatedPlaintextBytes"],
        value["recordCount"] * FUTURE_WAL_RECORD_FRAMING_ESTIMATE_BYTES)
    return expected is not None and \
        value["candidateWalPlaintextBytesEstimate"] == expected


def _valid_checkpoint(
        value: Any, registered_keys: frozenset[str],
        created: dt.datetime, updated: dt.datetime) -> bool:
    if not _exact_dict(value, _CHECKPOINT_KEYS) or \
            not _valid_identifier(value["sampleId"]) or \
            not _valid_timestamp(value["observedAt"]):
        return False
    observed = _parse_timestamp(value["observedAt"])
    if observed is None or not created <= observed <= updated or \
            type(value["success"]) is not bool or \
            type(value["detailed"]) is not bool or \
            value["detailReason"] not in DETAIL_REASONS:
        return False
    if value["detailed"] != (value["detailReason"] != "NONE"):
        return False
    required_ints = (
        "checkpointSerializedBytes", "serializationDurationMicros",
        "sectionAccountingDurationMicros", "writeSealDurationMicros",
        "fsyncReadbackDurationMicros", "localWalBytes", "localWalRecords",
        "localWalHighWater",
    )
    if any(not _valid_int(value[key]) for key in required_ints) or \
            not _valid_optional_int(value["peakRssBytes"]) or \
            not _valid_optional_int(value["legacyRemoteAckSequence"]) or \
            not _valid_timestamp(value["legacyRemoteAckAt"], optional=True) or \
            value["legacyRemoteAckIsExactWalDurability"] is not False:
        return False
    ack_at = _parse_timestamp(value["legacyRemoteAckAt"])
    ack_sequence = value["legacyRemoteAckSequence"]
    if (ack_at is None) != (ack_sequence is None) or \
            (ack_at is not None and ack_at > observed) or \
            (ack_sequence is not None and
             ack_sequence > value["localWalHighWater"]):
        return False
    sections = value["sectionSerializedBytes"]
    if type(sections) is not dict or len(sections) > MAX_CHECKPOINT_SECTION_KEYS or \
            frozenset(sections) - registered_keys or \
            any(not _valid_int(size) for size in sections.values()) or \
            sum(sections.values()) > value["checkpointSerializedBytes"]:
        return False
    return value["detailed"] or not sections


def new_artifact(
        *, measurement_generation_id: str, producer_build_sha: str,
        instrumentation_coverage_sha256: str, created_at: dt.datetime,
        registry_policy_sha256: Optional[str] = None,
        invalidation_code: str = "none") -> Dict[str, Any]:
    """Create a deterministic empty artifact; all identity/time is caller input."""
    timestamp = canonical_timestamp(created_at)
    policy_sha = registry.registry_policy_sha256() \
        if registry_policy_sha256 is None else registry_policy_sha256
    if not _valid_identifier(measurement_generation_id) or \
            type(producer_build_sha) is not str or \
            _BUILD_SHA_RE.fullmatch(producer_build_sha) is None or \
            not _valid_sha256(instrumentation_coverage_sha256) or \
            not _valid_sha256(policy_sha) or \
            invalidation_code not in INVALIDATION_CODES:
        raise ValueError("measurement_identity_invalid")
    mutation_count = len(registry.mutations())
    if mutation_count > MAX_MUTATION_CLASSES or registry.validate_registry():
        raise ValueError("registry_contract_invalid")
    counters = {key: 0 for key in _AGGREGATE_KEYS}
    artifact = {
        "schemaVersion": SCHEMA_VERSION,
        "measurementSchemaSha256": MEASUREMENT_SCHEMA_SHA256,
        "measurementGenerationId": measurement_generation_id,
        "registryPolicySha256": policy_sha,
        "instrumentationCoverageSha256": instrumentation_coverage_sha256,
        "producerBuildSha": producer_build_sha,
        "generationStartedAt": timestamp,
        "createdAt": timestamp,
        "updatedAt": timestamp,
        "retentionPolicyVersion": RETENTION_POLICY_VERSION,
        "samplingPolicyVersion": SAMPLING_POLICY_VERSION,
        "authoritative": False,
        "mode": MODE,
        "coverageStatus": COVERAGE_STATUS,
        "proofStatus": PROOF_STATUS,
        "acceptanceClockStarted": False,
        "coverage": {
            "latestObservedAuthoritativeMutationAt": None,
            "oldestObservedUndurableMutationAt": None,
            "legacyRemoteAckAt": None,
            "instrumentedMutationClassIds": [],
            "expectedMutationClassCount": mutation_count,
            "allExpectedMutationClassesObserved": False,
        },
        "invalidation": {
            "code": invalidation_code,
            "at": None if invalidation_code == "none" else timestamp,
        },
        "intervalBuckets": [],
        "dailyDistributions": [],
        "recentMutations": [],
        "checkpointSamples": [],
        "aggregateCounters": counters,
    }
    if not validate_artifact(artifact, expected_registry_policy_sha256=policy_sha).valid:
        raise ValueError("measurement_artifact_invalid")
    return artifact


def validate_artifact(
        value: Any, *, expected_registry_policy_sha256: Optional[str] = None
        ) -> ValidationResult:
    """Total, closed validator for an untrusted measurement artifact."""
    try:
        valid = _validate_artifact_strict(value)
    except (ArithmeticError, KeyError, TypeError, ValueError, RecursionError):
        valid = False
    if not valid:
        return ValidationResult(False, "invalid_artifact")
    expected = registry.registry_policy_sha256() \
        if expected_registry_policy_sha256 is None \
        else expected_registry_policy_sha256
    if not _valid_sha256(expected) or value["registryPolicySha256"] != expected:
        return ValidationResult(False, "registry_policy_mismatch")
    return ValidationResult(True, "ok")


def _validate_artifact_strict(value: Any) -> bool:
    if not _bounded_json_shape(value) or not _exact_dict(value, _TOP_KEYS):
        return False
    if value["schemaVersion"] != SCHEMA_VERSION or \
            value["measurementSchemaSha256"] != MEASUREMENT_SCHEMA_SHA256 or \
            not _valid_identifier(value["measurementGenerationId"]) or \
            not _valid_sha256(value["registryPolicySha256"]) or \
            not _valid_sha256(value["instrumentationCoverageSha256"]) or \
            type(value["producerBuildSha"]) is not str or \
            _BUILD_SHA_RE.fullmatch(value["producerBuildSha"]) is None or \
            value["retentionPolicyVersion"] != RETENTION_POLICY_VERSION or \
            value["samplingPolicyVersion"] != SAMPLING_POLICY_VERSION or \
            value["authoritative"] is not False or value["mode"] != MODE or \
            value["coverageStatus"] != COVERAGE_STATUS or \
            value["proofStatus"] != PROOF_STATUS or \
            value["acceptanceClockStarted"] is not False:
        return False
    timestamps = (
        value["generationStartedAt"], value["createdAt"], value["updatedAt"])
    if any(not _valid_timestamp(item) for item in timestamps):
        return False
    generation_started, created, updated = map(_parse_timestamp, timestamps)
    if generation_started is None or created is None or updated is None or \
            generation_started != created or created > updated:
        return False

    mutations = registry.mutation_by_id()
    mutation_ids = frozenset(mutations)
    if registry.validate_registry() or len(mutation_ids) > MAX_MUTATION_CLASSES:
        return False
    registered_keys = frozenset(registry.registered_checkpoint_keys())
    if len(registered_keys) > MAX_CHECKPOINT_SECTION_KEYS:
        return False

    coverage = value["coverage"]
    if not _exact_dict(coverage, _COVERAGE_KEYS) or \
            coverage["expectedMutationClassCount"] != len(mutation_ids) or \
            type(coverage["allExpectedMutationClassesObserved"]) is not bool:
        return False
    instrumented = coverage["instrumentedMutationClassIds"]
    if type(instrumented) is not list or instrumented != sorted(instrumented) or \
            len(instrumented) != len(set(instrumented)) or \
            len(instrumented) > MAX_MUTATION_CLASSES or \
            any(type(item) is not str or item not in mutation_ids
                for item in instrumented) or \
            coverage["allExpectedMutationClassesObserved"] != \
            (frozenset(instrumented) == mutation_ids):
        return False
    coverage_times = [
        coverage["latestObservedAuthoritativeMutationAt"],
        coverage["oldestObservedUndurableMutationAt"],
        coverage["legacyRemoteAckAt"],
    ]
    if any(not _valid_timestamp(item, optional=True) for item in coverage_times):
        return False
    parsed_coverage_times = [_parse_timestamp(item) for item in coverage_times]
    if any(item is not None and not created <= item <= updated
           for item in parsed_coverage_times):
        return False
    latest, oldest_undurable, _legacy_ack = parsed_coverage_times
    if oldest_undurable is not None and \
            (latest is None or oldest_undurable > latest):
        return False

    invalidation = value["invalidation"]
    if not _exact_dict(invalidation, _INVALIDATION_KEYS) or \
            invalidation["code"] not in INVALIDATION_CODES or \
            not _valid_timestamp(invalidation["at"], optional=True) or \
            (invalidation["code"] == "none") != (invalidation["at"] is None):
        return False
    invalidation_at = _parse_timestamp(invalidation["at"])
    if invalidation_at is not None and not created <= invalidation_at <= updated:
        return False

    buckets = value["intervalBuckets"]
    daily = value["dailyDistributions"]
    recent = value["recentMutations"]
    checkpoints = value["checkpointSamples"]
    if type(buckets) is not list or len(buckets) > MAX_BUCKETS or \
            type(daily) is not list or len(daily) > MAX_DAILY_DISTRIBUTIONS or \
            type(recent) is not list or len(recent) > MAX_RECENT_MUTATIONS or \
            type(checkpoints) is not list or \
            len(checkpoints) > MAX_CHECKPOINT_SAMPLES:
        return False
    if any(not _valid_bucket(row, mutation_ids) for row in buckets) or \
            any(not _valid_daily(row, mutation_ids) for row in daily) or \
            any(not _valid_recent(row, mutations, created, updated)
                for row in recent) or \
            any(not _valid_checkpoint(row, registered_keys, created, updated)
                for row in checkpoints):
        return False
    if [row["bucketStart"] for row in buckets] != \
            sorted({row["bucketStart"] for row in buckets}) or \
            [row["day"] for row in daily] != \
            sorted({row["day"] for row in daily}) or \
            [_recent_sort_key(row) for row in recent] != sorted(
                _recent_sort_key(row) for row in recent) or \
            [(row["observedAt"], row["sampleId"]) for row in checkpoints] != \
            sorted((row["observedAt"], row["sampleId"])
                   for row in checkpoints) or \
            len({row["sampleId"] for row in checkpoints}) != len(checkpoints):
        return False
    created_bucket = _floor_bucket(created)
    if any(_parse_timestamp(row["bucketStart"]) < created_bucket or
           _parse_timestamp(row["bucketStart"]) > updated for row in buckets):
        return False
    if any(dt.date.fromisoformat(row["day"]) < created.date() or
           dt.date.fromisoformat(row["day"]) > updated.date() for row in daily):
        return False

    counters = value["aggregateCounters"]
    if not _exact_dict(counters, _AGGREGATE_KEYS) or \
            any(not _valid_int(item) for item in counters.values()):
        return False
    retained_mutations = sum(
        distribution["mutationCount"] for row in daily
        for distribution in row["byMutationClass"].values())
    retained_bytes = sum(
        distribution["estimatedPlaintextBytes"] for row in daily
        for distribution in row["byMutationClass"].values())
    retained_records = sum(
        distribution["recordCount"] for row in daily
        for distribution in row["byMutationClass"].values())
    expected = {
        "retainedMutationCount": retained_mutations,
        "retainedEstimatedPlaintextBytes": retained_bytes,
        "retainedRecordCount": retained_records,
        "retainedBucketCount": len(buckets),
        "retainedRecentMutationCount": len(recent),
        "retainedCheckpointSampleCount": len(checkpoints),
    }
    if any(counters[key] != count for key, count in expected.items()) or \
            counters["lifetimeMutationCount"] < retained_mutations or \
            counters["lifetimeEstimatedPlaintextBytes"] < retained_bytes or \
            counters["lifetimeRecordCount"] < retained_records or \
            counters["lifetimeSuccessCount"] + \
            counters["lifetimeFailureCount"] != \
            counters["lifetimeMutationCount"]:
        return False
    bucket_mutations = sum(row["mutationCount"] for row in buckets)
    bucket_bytes = sum(row["estimatedPlaintextBytes"] for row in buckets)
    bucket_records = sum(row["recordCount"] for row in buckets)
    if counters["lifetimeMutationCount"] < bucket_mutations or \
            counters["lifetimeEstimatedPlaintextBytes"] < bucket_bytes or \
            counters["lifetimeRecordCount"] < bucket_records or \
            (counters["lifetimeMutationCount"] == 0) != \
            (latest is None) or \
            (counters["lifetimeMutationCount"] == 0) != \
            (len(instrumented) == 0):
        return False
    if recent and latest is not None and \
            latest < max(_parse_timestamp(row["observedAt"])
                         for row in recent):
        return False
    return True


def _canonical_bytes_unchecked(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, allow_nan=False, sort_keys=True,
        separators=(",", ":")).encode("utf-8")


def canonical_artifact_bytes(value: Any) -> bytes:
    result = validate_artifact(value)
    if not result.valid:
        raise ValueError(result.code)
    encoded = _canonical_bytes_unchecked(value)
    if len(encoded) > MAX_PERSISTED_BYTES:
        raise ValueError("size_rejected")
    return encoded


def _floor_bucket(value: dt.datetime, minutes: int = BUCKET_MINUTES
                  ) -> dt.datetime:
    normalized = value.astimezone(UTC).replace(second=0, microsecond=0)
    return normalized.replace(minute=(normalized.minute // minutes) * minutes)


def _find_row(rows: Sequence[Mapping[str, Any]], field: str,
              target: str) -> Tuple[int, bool]:
    low, high = 0, len(rows)
    while low < high:
        middle = (low + high) // 2
        if rows[middle][field] < target:
            low = middle + 1
        else:
            high = middle
    return low, low < len(rows) and rows[low][field] == target


def _recent_sort_key(row: Mapping[str, Any]) -> Tuple[Any, ...]:
    return (
        row["observedAt"], row["mutationClassId"],
        -1 if row["localSequence"] is None else row["localSequence"],
        row["estimatedPlaintextBytes"], row["recordCount"],
        row["latencyMicros"], row["success"],
        row["coverageClassification"],
    )


def _insert_sorted(
        rows: Sequence[Mapping[str, Any]], row: Mapping[str, Any],
        key_function) -> list[Mapping[str, Any]]:
    key = key_function(row)
    low, high = 0, len(rows)
    while low < high:
        middle = (low + high) // 2
        if key_function(rows[middle]) <= key:
            low = middle + 1
        else:
            high = middle
    return [*rows[:low], row, *rows[low:]]


def _daily_totals(rows: Sequence[Mapping[str, Any]]) -> Tuple[int, int, int]:
    mutations = estimated = records = 0
    for row in rows:
        for distribution in row["byMutationClass"].values():
            mutations += distribution["mutationCount"]
            estimated += distribution["estimatedPlaintextBytes"]
            records += distribution["recordCount"]
    return mutations, estimated, records


class MeasurementAccumulator:
    """Bounded metadata-only accumulator; not instantiated by runtime in PR C."""

    def __init__(self, artifact: Dict[str, Any]):
        validation = validate_artifact(artifact)
        if not validation.valid:
            raise ValueError(validation.code)
        self.artifact = artifact
        self._registry_policy_sha256 = artifact["registryPolicySha256"]
        self._mutations = registry.mutation_by_id()
        self._mutation_ids = frozenset(self._mutations)
        self._registered_checkpoint_keys = frozenset(
            registry.registered_checkpoint_keys())

    def _live_registry_policy_matches_generation(self) -> bool:
        """Fail closed if this generation is no longer bound to live policy."""
        try:
            provider = registry.registry_policy_sha256
            # Registry Core's production declarations are immutable and its
            # exported digest is the current process policy identity.  An
            # alternate/live provider is evaluated on every boundary, which
            # also makes in-process policy transitions fail closed in tests.
            if provider is _REGISTRY_POLICY_PROVIDER:
                live_policy = registry.REGISTRY_POLICY_SHA256
            else:
                live_policy = provider()
        except Exception:
            return False
        return type(self.artifact) is dict and \
            live_policy == self._registry_policy_sha256 and \
            self.artifact.get("registryPolicySha256") == \
            self._registry_policy_sha256

    def record_mutation(
            self, mutation_class_id: str, *, estimated_plaintext_bytes: int,
            record_count: int, latency_micros: int, success: bool,
            coverage_classification: str, observed_at: dt.datetime,
            local_sequence: Optional[int] = None) -> str:
        """Record only typed scalar metadata; no payload parameter exists."""
        if not self._live_registry_policy_matches_generation():
            return "registry_policy_mismatch"
        mutation = self._mutations.get(mutation_class_id) \
            if type(mutation_class_id) is str else None
        try:
            observed_text = canonical_timestamp(observed_at)
        except ValueError:
            return "invalid_observation"
        if mutation is None or not all(_valid_int(value) for value in (
                estimated_plaintext_bytes, record_count, latency_micros)) or \
                type(success) is not bool or \
                type(coverage_classification) is not str or \
                coverage_classification not in COVERAGE_CLASSIFICATIONS or \
                not _valid_optional_int(local_sequence):
            return "invalid_observation"
        created = _parse_timestamp(self.artifact["createdAt"])
        observed = _parse_timestamp(observed_text)
        if created is None or observed is None or observed < created:
            return "invalid_observation"
        candidate_bytes = _checked_add(
            estimated_plaintext_bytes,
            record_count * FUTURE_WAL_RECORD_FRAMING_ESTIMATE_BYTES)
        if candidate_bytes is None:
            return "counter_overflow"

        recent_row = {
            "observedAt": observed_text,
            "mutationClassId": mutation_class_id,
            "targetStateIds": list(mutation.targetStateIds),
            "estimatedPlaintextBytes": estimated_plaintext_bytes,
            "candidateWalPlaintextBytesEstimate": candidate_bytes,
            "recordCount": record_count,
            "latencyMicros": latency_micros,
            "success": success,
            "coverageClassification": coverage_classification,
            "currentWalCoverage": mutation.currentWalCoverage.value,
            "localSequence": local_sequence,
        }

        updated_at = max(
            observed, _parse_timestamp(self.artifact["updatedAt"]) or observed)
        if not _valid_recent(
                recent_row, self._mutations, created, updated_at):
            return "invalid_observation"

        bucket_text = canonical_timestamp(_floor_bucket(observed))
        buckets = self.artifact["intervalBuckets"]
        bucket_index, bucket_exists = _find_row(
            buckets, "bucketStart", bucket_text)
        if bucket_exists:
            current_bucket = buckets[bucket_index]
        else:
            current_bucket = {
                "bucketStart": bucket_text,
                **_empty_distribution(),
                "byMutationClass": {},
            }
        incremented = _increment_distribution(
            {key: current_bucket[key] for key in _DISTRIBUTION_KEYS},
            estimated_bytes=estimated_plaintext_bytes,
            candidate_bytes=candidate_bytes, record_count=record_count,
            latency_micros=latency_micros, success=success)
        class_count = _checked_add(
            current_bucket["byMutationClass"].get(mutation_class_id, 0), 1)
        if incremented is None or class_count is None:
            return "counter_overflow"
        replacement_bucket = {
            "bucketStart": bucket_text,
            **incremented,
            "byMutationClass": {
                **current_bucket["byMutationClass"],
                mutation_class_id: class_count,
            },
        }
        if not _valid_bucket(replacement_bucket, self._mutation_ids):
            return "invalid_observation"
        bucket_drops = max(
            0, len(buckets) + (0 if bucket_exists else 1) - MAX_BUCKETS)

        day_text = observed.date().isoformat()
        daily_rows = self.artifact["dailyDistributions"]
        daily_index, daily_exists = _find_row(daily_rows, "day", day_text)
        current_daily = daily_rows[daily_index] if daily_exists else {
            "day": day_text, "byMutationClass": {}}
        current_distribution = current_daily["byMutationClass"].get(
            mutation_class_id, _empty_distribution())
        daily_distribution = _increment_distribution(
            current_distribution, estimated_bytes=estimated_plaintext_bytes,
            candidate_bytes=candidate_bytes, record_count=record_count,
            latency_micros=latency_micros, success=success)
        if daily_distribution is None:
            return "counter_overflow"
        replacement_daily = {
            "day": day_text,
            "byMutationClass": {
                **current_daily["byMutationClass"],
                mutation_class_id: daily_distribution,
            },
        }
        if not _valid_daily(replacement_daily, self._mutation_ids):
            return "invalid_observation"
        new_daily = list(daily_rows)
        if daily_exists:
            new_daily[daily_index] = replacement_daily
        else:
            new_daily.insert(daily_index, replacement_daily)
        daily_drops = max(0, len(new_daily) - MAX_DAILY_DISTRIBUTIONS)
        if daily_drops:
            new_daily = new_daily[daily_drops:]

        new_recent = _insert_sorted(
            self.artifact["recentMutations"], recent_row, _recent_sort_key)
        recent_drops = max(0, len(new_recent) - MAX_RECENT_MUTATIONS)
        if recent_drops:
            new_recent = new_recent[recent_drops:]

        counters = dict(self.artifact["aggregateCounters"])
        increments = {
            "lifetimeMutationCount": 1,
            "lifetimeEstimatedPlaintextBytes": estimated_plaintext_bytes,
            "lifetimeRecordCount": record_count,
            "lifetimeSuccessCount": 1 if success else 0,
            "lifetimeFailureCount": 0 if success else 1,
            "droppedForRetentionCount": (
                bucket_drops + daily_drops + recent_drops),
        }
        for key, increment in increments.items():
            updated_counter = _checked_add(counters[key], increment)
            if updated_counter is None:
                return "counter_overflow"
            counters[key] = updated_counter
        retained_mutations, retained_bytes, retained_records = _daily_totals(
            new_daily)
        counters.update({
            "retainedMutationCount": retained_mutations,
            "retainedEstimatedPlaintextBytes": retained_bytes,
            "retainedRecordCount": retained_records,
            "retainedBucketCount": len(buckets) +
                (0 if bucket_exists else 1) - bucket_drops,
            "retainedRecentMutationCount": len(new_recent),
        })

        coverage = dict(self.artifact["coverage"])
        latest = _parse_timestamp(
            coverage["latestObservedAuthoritativeMutationAt"])
        coverage["latestObservedAuthoritativeMutationAt"] = \
            canonical_timestamp(max(observed, latest or observed))
        if coverage_classification == "OBSERVED_UNDURABLE":
            oldest = _parse_timestamp(
                coverage["oldestObservedUndurableMutationAt"])
            coverage["oldestObservedUndurableMutationAt"] = \
                canonical_timestamp(min(observed, oldest or observed))
        instrumented = sorted(set(
            coverage["instrumentedMutationClassIds"]) | {mutation_class_id})
        coverage["instrumentedMutationClassIds"] = instrumented
        coverage["allExpectedMutationClassesObserved"] = \
            len(instrumented) == coverage["expectedMutationClassCount"] and \
            frozenset(instrumented) == self._mutation_ids

        # Every fallible validation/counter operation above precedes mutation.
        if bucket_exists:
            buckets[bucket_index] = replacement_bucket
        else:
            buckets.insert(bucket_index, replacement_bucket)
        if bucket_drops:
            del buckets[:bucket_drops]
        self.artifact["dailyDistributions"] = new_daily
        self.artifact["recentMutations"] = new_recent
        self.artifact["aggregateCounters"] = counters
        self.artifact["coverage"] = coverage
        self.artifact["updatedAt"] = canonical_timestamp(updated_at)
        return "recorded"

    def record_checkpoint(
            self, sample_id: str, *, observed_at: dt.datetime, success: bool,
            detailed: bool, detail_reason: str,
            checkpoint_serialized_bytes: int,
            section_serialized_bytes: Mapping[str, int],
            serialization_duration_micros: int,
            section_accounting_duration_micros: int,
            write_seal_duration_micros: int,
            fsync_readback_duration_micros: int,
            peak_rss_bytes: Optional[int], local_wal_bytes: int,
            local_wal_records: int, local_wal_high_water: int,
            legacy_remote_ack_sequence: Optional[int],
            legacy_remote_ack_at: Optional[dt.datetime]) -> str:
        if not self._live_registry_policy_matches_generation():
            return "registry_policy_mismatch"
        try:
            observed_text = canonical_timestamp(observed_at)
            ack_text = None if legacy_remote_ack_at is None else \
                canonical_timestamp(legacy_remote_ack_at)
        except ValueError:
            return "invalid_observation"
        if type(section_serialized_bytes) is not dict or \
                type(success) is not bool or type(detailed) is not bool or \
                type(detail_reason) is not str or \
                detail_reason not in DETAIL_REASONS or \
                len(section_serialized_bytes) > MAX_CHECKPOINT_SECTION_KEYS or \
                any(type(key) is not str or
                    key not in self._registered_checkpoint_keys or
                    not _valid_int(value)
                    for key, value in section_serialized_bytes.items()):
            return "invalid_observation"
        sample = {
            "sampleId": sample_id,
            "observedAt": observed_text,
            "success": success,
            "detailed": detailed,
            "detailReason": detail_reason,
            "checkpointSerializedBytes": checkpoint_serialized_bytes,
            "sectionSerializedBytes": dict(sorted(
                section_serialized_bytes.items())),
            "serializationDurationMicros": serialization_duration_micros,
            "sectionAccountingDurationMicros":
                section_accounting_duration_micros,
            "writeSealDurationMicros": write_seal_duration_micros,
            "fsyncReadbackDurationMicros": fsync_readback_duration_micros,
            "peakRssBytes": peak_rss_bytes,
            "localWalBytes": local_wal_bytes,
            "localWalRecords": local_wal_records,
            "localWalHighWater": local_wal_high_water,
            "legacyRemoteAckSequence": legacy_remote_ack_sequence,
            "legacyRemoteAckAt": ack_text,
            "legacyRemoteAckIsExactWalDurability": False,
        }
        created = _parse_timestamp(self.artifact["createdAt"])
        observed = _parse_timestamp(observed_text)
        updated = _parse_timestamp(self.artifact["updatedAt"])
        if created is None or observed is None or observed < created:
            return "invalid_observation"
        new_updated = max(observed, updated or observed)
        if not _valid_checkpoint(
                sample, self._registered_checkpoint_keys,
                created, new_updated):
            return "invalid_observation"
        if any(row["sampleId"] == sample_id
               for row in self.artifact["checkpointSamples"]):
            return "invalid_observation"
        samples = _insert_sorted(
            self.artifact["checkpointSamples"], sample,
            lambda row: (row["observedAt"], row["sampleId"]))
        drops = max(0, len(samples) - MAX_CHECKPOINT_SAMPLES)
        if drops:
            samples = samples[drops:]
        counters = dict(self.artifact["aggregateCounters"])
        dropped = _checked_add(counters["droppedForRetentionCount"], drops)
        if dropped is None:
            return "counter_overflow"
        counters["droppedForRetentionCount"] = dropped
        counters["retainedCheckpointSampleCount"] = len(samples)
        coverage = dict(self.artifact["coverage"])
        current_ack = _parse_timestamp(coverage["legacyRemoteAckAt"])
        if legacy_remote_ack_at is not None:
            coverage["legacyRemoteAckAt"] = canonical_timestamp(max(
                legacy_remote_ack_at.astimezone(UTC).replace(microsecond=0),
                current_ack or legacy_remote_ack_at.astimezone(UTC).replace(
                    microsecond=0)))
        self.artifact["checkpointSamples"] = samples
        self.artifact["aggregateCounters"] = counters
        self.artifact["coverage"] = coverage
        self.artifact["updatedAt"] = canonical_timestamp(new_updated)
        return "recorded"


def detailed_sampling_policy(
        context: DetailedSamplingContext) -> DetailedSamplingDecision:
    """Pure request policy; it imports no market clock and performs no I/O."""
    if type(context) is not DetailedSamplingContext or any(
            type(value) is not bool for value in (
                context.jp_session_boundary, context.us_session_boundary,
                context.accounting_schema_changed,
                context.producer_build_changed, context.owner_authorized)) or \
            not _valid_int(context.detailed_session_samples_today,
                           maximum=MAX_DETAILED_SESSION_SAMPLES_PER_DAY):
        raise ValueError("sampling_context_invalid")
    if context.owner_authorized:
        reason = "OWNER_AUTHORIZED"
    elif context.accounting_schema_changed or context.producer_build_changed:
        reason = "ACCOUNTING_SCHEMA_OR_BUILD_CHANGE"
    elif context.detailed_session_samples_today < \
            MAX_DETAILED_SESSION_SAMPLES_PER_DAY and \
            context.jp_session_boundary:
        reason = "JP_SESSION_BOUNDARY"
    elif context.detailed_session_samples_today < \
            MAX_DETAILED_SESSION_SAMPLES_PER_DAY and \
            context.us_session_boundary:
        reason = "US_SESSION_BOUNDARY"
    else:
        reason = "NONE"
    return DetailedSamplingDecision(
        requested=reason != "NONE", reason=reason,
        normal_session_limit=MAX_DETAILED_SESSION_SAMPLES_PER_DAY)


def _merge_distribution(target: Dict[str, Any], source: Mapping[str, Any]
                        ) -> None:
    for key in (
            "mutationCount", "estimatedPlaintextBytes",
            "candidateWalPlaintextBytesEstimate", "recordCount",
            "latencyMicrosTotal", "successCount", "failureCount"):
        target[key] += source[key]
    target["maxSingleMutationPlaintextBytesEstimate"] = max(
        target["maxSingleMutationPlaintextBytesEstimate"],
        source["maxSingleMutationPlaintextBytesEstimate"])
    for key in ("plaintextBytesHistogram", "latencyMicrosHistogram"):
        target[key] = [left + right for left, right in zip(
            target[key], source[key])]


def _histogram_quantile(
        histogram: Sequence[int], bounds: Sequence[int], quantile: float
        ) -> Optional[int]:
    total = sum(histogram)
    if total <= 0:
        return None
    target = max(1, math.ceil(total * quantile))
    seen = 0
    for index, count in enumerate(histogram):
        seen += count
        if seen >= target:
            return bounds[index]
    return bounds[-1]


def distribution_summary(distribution: Mapping[str, Any]) -> Dict[str, Any]:
    if not _valid_distribution(distribution):
        raise ValueError("distribution_invalid")
    return {
        "mutationCount": distribution["mutationCount"],
        "estimatedPlaintextBytes": distribution["estimatedPlaintextBytes"],
        "candidateWalPlaintextBytesEstimate":
            distribution["candidateWalPlaintextBytesEstimate"],
        "recordCount": distribution["recordCount"],
        "successCount": distribution["successCount"],
        "failureCount": distribution["failureCount"],
        "maxSingleMutationPlaintextBytesEstimate":
            distribution["maxSingleMutationPlaintextBytesEstimate"],
        "plaintextBytesApproxP50UpperBound": _histogram_quantile(
            distribution["plaintextBytesHistogram"],
            PLAINTEXT_BYTE_HISTOGRAM_UPPER_BOUNDS, .50),
        "plaintextBytesApproxP95UpperBound": _histogram_quantile(
            distribution["plaintextBytesHistogram"],
            PLAINTEXT_BYTE_HISTOGRAM_UPPER_BOUNDS, .95),
        "plaintextBytesApproxP99UpperBound": _histogram_quantile(
            distribution["plaintextBytesHistogram"],
            PLAINTEXT_BYTE_HISTOGRAM_UPPER_BOUNDS, .99),
        "latencyMicrosApproxP50UpperBound": _histogram_quantile(
            distribution["latencyMicrosHistogram"],
            LATENCY_MICROS_HISTOGRAM_UPPER_BOUNDS, .50),
        "latencyMicrosApproxP95UpperBound": _histogram_quantile(
            distribution["latencyMicrosHistogram"],
            LATENCY_MICROS_HISTOGRAM_UPPER_BOUNDS, .95),
        "latencyMicrosApproxP99UpperBound": _histogram_quantile(
            distribution["latencyMicrosHistogram"],
            LATENCY_MICROS_HISTOGRAM_UPPER_BOUNDS, .99),
        "histogramQuantilesAreUpperBounds": True,
        "walSizeSemantics": "plaintext_candidate_estimate_not_encrypted_wal",
    }


def interval_rollups(artifact: Any, minutes: int) -> list[Dict[str, Any]]:
    if minutes not in (5, 15, 30):
        raise ValueError("interval_invalid")
    validation = validate_artifact(artifact)
    if not validation.valid:
        raise ValueError(validation.code)
    grouped: Dict[str, Dict[str, Any]] = {}
    for bucket in artifact["intervalBuckets"]:
        parsed = _parse_timestamp(bucket["bucketStart"])
        assert parsed is not None
        interval_start = canonical_timestamp(_floor_bucket(parsed, minutes))
        target = grouped.setdefault(interval_start, {
            "intervalStart": interval_start,
            **_empty_distribution(),
            "byMutationClass": {},
        })
        _merge_distribution(target, {
            key: bucket[key] for key in _DISTRIBUTION_KEYS})
        for mutation_id, count in bucket["byMutationClass"].items():
            target["byMutationClass"][mutation_id] = \
                target["byMutationClass"].get(mutation_id, 0) + count
    result = []
    for interval_start in sorted(grouped):
        row = grouped[interval_start]
        result.append({
            "intervalStart": interval_start,
            "byMutationClass": dict(sorted(row["byMutationClass"].items())),
            **distribution_summary({
                key: row[key] for key in _DISTRIBUTION_KEYS}),
        })
    return result


def _collection_encoded_bytes(encoded_rows: Sequence[bytes]) -> int:
    return 2 + sum(map(len, encoded_rows)) + max(0, len(encoded_rows) - 1)


def _fit_category(
        rows: Sequence[Dict[str, Any]], budget: int
        ) -> Tuple[list[Dict[str, Any]], int, int]:
    encoded = [_canonical_bytes_unchecked(row) for row in rows]
    total = _collection_encoded_bytes(encoded)
    drop = 0
    while drop < len(encoded) and total > budget:
        total -= len(encoded[drop])
        if len(encoded) - drop > 1:
            total -= 1
        drop += 1
    return list(rows[drop:]), len(encoded), drop


def plan_retention(artifact: Any, *, now: dt.datetime) -> RetentionPlan:
    """Plan one O(N) prune and one O(S) final encoding without source mutation."""
    try:
        now_text = canonical_timestamp(now)
    except ValueError:
        now_text = ""
    validation = validate_artifact(artifact)
    input_rows = sum(len(artifact.get(key, []))
                     if type(artifact) is dict else 0 for key in (
                         "intervalBuckets", "dailyDistributions",
                         "recentMutations", "checkpointSamples"))
    empty_evidence = RetentionEvidence(
        input_rows=input_rows, retained_rows=0, row_encodes=0,
        collection_passes=0, bulk_removed_rows=0,
        final_document_encodes=0, final_bytes=0)
    if not now_text or not validation.valid:
        return RetentionPlan(validation.code if not validation.valid else
                             "invalid_observation", None, None, empty_evidence)
    normalized_now = _parse_timestamp(now_text)
    assert normalized_now is not None
    cutoff = normalized_now - dt.timedelta(days=RETENTION_DAYS)
    bucket_cutoff = canonical_timestamp(_floor_bucket(cutoff))
    timestamp_cutoff = canonical_timestamp(cutoff)
    day_cutoff = (normalized_now.date() - dt.timedelta(
        days=MAX_DAILY_DISTRIBUTIONS - 1)).isoformat()

    time_pruned = {
        "intervalBuckets": [row for row in artifact["intervalBuckets"]
                            if row["bucketStart"] >= bucket_cutoff][
                                -MAX_BUCKETS:],
        "dailyDistributions": [row for row in artifact["dailyDistributions"]
                               if row["day"] >= day_cutoff][
                                   -MAX_DAILY_DISTRIBUTIONS:],
        "recentMutations": [row for row in artifact["recentMutations"]
                            if row["observedAt"] >= timestamp_cutoff][
                                -MAX_RECENT_MUTATIONS:],
        "checkpointSamples": [row for row in artifact["checkpointSamples"]
                              if row["observedAt"] >= timestamp_cutoff][
                                  -MAX_CHECKPOINT_SAMPLES:],
    }
    budgets = {
        "intervalBuckets": BUCKETS_BUDGET,
        "dailyDistributions": DAILY_DISTRIBUTIONS_BUDGET,
        "recentMutations": RECENT_MUTATIONS_BUDGET,
        "checkpointSamples": CHECKPOINT_SAMPLES_BUDGET,
    }
    retained: Dict[str, list[Dict[str, Any]]] = {}
    row_encodes = size_drops = 0
    for key in (
            "intervalBuckets", "dailyDistributions", "recentMutations",
            "checkpointSamples"):
        fitted, encoded_count, dropped = _fit_category(
            time_pruned[key], budgets[key])
        retained[key] = fitted
        row_encodes += encoded_count
        size_drops += dropped
    retained_rows = sum(map(len, retained.values()))
    bulk_removed = input_rows - retained_rows

    candidate = dict(artifact)
    candidate.update(retained)
    counters = dict(candidate["aggregateCounters"])
    retained_mutations, retained_bytes, retained_records = _daily_totals(
        retained["dailyDistributions"])
    dropped_counter = _checked_add(
        counters["droppedForRetentionCount"], bulk_removed)
    if dropped_counter is None:
        return RetentionPlan("counter_overflow", None, None, empty_evidence)
    counters.update({
        "retainedMutationCount": retained_mutations,
        "retainedEstimatedPlaintextBytes": retained_bytes,
        "retainedRecordCount": retained_records,
        "retainedBucketCount": len(retained["intervalBuckets"]),
        "retainedRecentMutationCount": len(retained["recentMutations"]),
        "retainedCheckpointSampleCount": len(retained["checkpointSamples"]),
        "droppedForRetentionCount": dropped_counter,
    })
    candidate["aggregateCounters"] = counters

    shell = dict(candidate)
    for key in retained:
        shell[key] = []
    if len(_canonical_bytes_unchecked(shell)) > FIXED_SHELL_BUDGET:
        return RetentionPlan("size_rejected", None, None, empty_evidence)
    candidate_validation = validate_artifact(candidate)
    if not candidate_validation.valid:
        return RetentionPlan(
            candidate_validation.code, None, None, empty_evidence)
    try:
        encoded = _canonical_bytes_unchecked(candidate)
    except (RecursionError, TypeError, ValueError):
        return RetentionPlan(
            "serialization_failure", None, None, empty_evidence)
    evidence = RetentionEvidence(
        input_rows=input_rows, retained_rows=retained_rows,
        row_encodes=row_encodes, collection_passes=4,
        bulk_removed_rows=bulk_removed, final_document_encodes=1,
        final_bytes=len(encoded))
    if len(encoded) > MAX_PERSISTED_BYTES:
        return RetentionPlan("size_rejected", None, None, evidence)
    return RetentionPlan("ok", candidate, encoded, evidence)


def _iter_encoded_bytes(value: Any) -> Iterator[bytes]:
    encoder = json.JSONEncoder(
        ensure_ascii=False, allow_nan=False, sort_keys=True,
        separators=(",", ":"), check_circular=True)
    try:
        for text in encoder.iterencode(value):
            encoded = text.encode("utf-8")
            if len(encoded) > MAX_STREAM_CHUNK_BYTES:
                raise ValueError("stream_scalar_too_large")
            if encoded:
                yield encoded
    except (OverflowError, RecursionError, TypeError, ValueError) as exc:
        if type(exc) is ValueError and str(exc) == "stream_scalar_too_large":
            raise
        raise ValueError("stream_value_invalid") from exc


def iter_canonical_json_chunks(
        value: Any, *, chunk_bytes: int = MAX_STREAM_CHUNK_BYTES
        ) -> Iterator[bytes]:
    """Yield canonical JSON in bounded chunks without a full-size buffer."""
    if type(chunk_bytes) is not int or not 1 <= chunk_bytes <= \
            MAX_STREAM_CHUNK_BYTES:
        raise ValueError("stream_chunk_bound_invalid")
    pending = bytearray()
    for token in _iter_encoded_bytes(value):
        offset = 0
        while offset < len(token):
            available = chunk_bytes - len(pending)
            take = min(available, len(token) - offset)
            pending.extend(token[offset:offset + take])
            offset += take
            if len(pending) == chunk_bytes:
                yield bytes(pending)
                pending.clear()
    if pending:
        yield bytes(pending)


def streaming_canonical_size(value: Any) -> int:
    # Counting consumes encoder tokens directly and does not allocate output
    # chunks.  The bounded-chunk API above remains available to future writers.
    return sum(len(token) for token in _iter_encoded_bytes(value))


def streaming_checkpoint_accounting(
        checkpoint: Mapping[str, Any], *,
        registered_section_keys: Optional[Iterable[str]] = None
        ) -> CheckpointAccounting:
    """Count top-level canonical bytes and registered sections in one pass."""
    if type(checkpoint) is not dict or any(type(key) is not str
                                           for key in checkpoint):
        raise ValueError("checkpoint_shape_invalid")
    registered = frozenset(
        registry.registered_checkpoint_keys() if
        registered_section_keys is None else registered_section_keys)
    if len(registered) > MAX_CHECKPOINT_SECTION_KEYS or any(
            type(key) is not str or len(key) > 64 for key in registered):
        raise ValueError("checkpoint_section_plan_invalid")
    total = 2  # opening and closing braces
    section_sizes: Dict[str, int] = {}
    for index, key in enumerate(sorted(checkpoint)):
        if index:
            total += 1
        key_bytes = _canonical_bytes_unchecked(key)
        total += len(key_bytes) + 1  # key and colon
        value_bytes = 0
        for token in _iter_encoded_bytes(checkpoint[key]):
            value_bytes += len(token)
        total += value_bytes
        if key in registered:
            section_sizes[key] = value_bytes
    return CheckpointAccounting(
        total_serialized_bytes=total,
        registered_section_bytes=section_sizes,
        output_chunk_limit_bytes=MAX_STREAM_CHUNK_BYTES,
        full_size_buffers=0)
