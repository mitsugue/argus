"""Minimal runtime adapter for Recovery Phase A shadow measurement.

The adapter deliberately has no authority role.  Callers invoke its mutation
hooks only *after* the existing authoritative operation has succeeded and
invoke its checkpoint flush only after checkpoint authority is complete.  All
adapter failures are contained and the proof boundary remains a null verifier.
"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
import datetime as dt
import hashlib
import json
import re
import secrets
import threading
import time
from typing import Any, Optional, Tuple

import argus_recovery_measurement as measurement
import argus_recovery_measurement_storage as storage
import argus_recovery_proof as proof
import argus_recovery_registry as registry


FEATURE_FLAG_NAME = "ARGUS_RECOVERY_PHASE_A_MEASUREMENT_ENABLED"
FEATURE_FLAG_ENABLED_VALUE = "1"
CANONICAL_ARTIFACT_PATH = storage.CANONICAL_ARTIFACT_PATH

EXPECTED_REGISTRY_MUTATION_COUNT = 27
MAX_PENDING_SAMPLING_DECISIONS = 64
UNOBSERVED_DURATION_MICROS = 0
UNOBSERVED_FSYNC_READBACK_DURATION_MICROS = UNOBSERVED_DURATION_MICROS
_BUILD_SHA_RE = re.compile(r"^[0-9a-f]{40}$", re.ASCII)


@dataclass(frozen=True)
class ProducerSeam:
    mutation_class_id: str
    scanner_function: str
    success_boundary: str
    selector: str


# This tuple is the complete Phase A instrumentation surface.  Registry rows
# outside it remain explicitly uninstrumented and therefore INCOMPLETE.
PRODUCER_SEAMS: Tuple[ProducerSeam, ...] = (
    ProducerSeam(
        "core.ops_journal_transition", "_journal",
        "after journal authority and required WAL/checkpoint success", "all"),
    ProducerSeam(
        "market.ledger_update", "_investor_types_autorefresh",
        "after verified legacy checkpoint",
        "eventType=market_ledger_investor_types_autorefresh"),
    ProducerSeam(
        "core.mission_transition", "_append_tick_wal",
        "after WAL append and fsync success", "kind=mission_transition"),
    ProducerSeam(
        "core.batch_cursor", "_append_tick_wal",
        "after WAL append and fsync success", "kind=batch_cursor"),
    ProducerSeam(
        "durability.receipt_ack", "_persist_with_remote_receipt_drain",
        "after receipt drain returns verified", "status=verified"),
    ProducerSeam(
        "startup.restore_transition", "_startup_bootstrap",
        "after terminal ready or ready_degraded startup", "once"),
)
INSTRUMENTED_MUTATION_CLASS_IDS = tuple(
    seam.mutation_class_id for seam in PRODUCER_SEAMS)

_INSTRUMENTATION_DOCUMENT = {
    "schemaVersion": "argus-recovery-phase-a-instrumentation-v1",
    "expectedRegistryMutationCount": EXPECTED_REGISTRY_MUTATION_COUNT,
    "producers": [
        {
            "mutationClassId": seam.mutation_class_id,
            "scannerFunction": seam.scanner_function,
            "successBoundary": seam.success_boundary,
            "selector": seam.selector,
        }
        for seam in PRODUCER_SEAMS
    ],
}
INSTRUMENTATION_COVERAGE_SHA256 = hashlib.sha256(json.dumps(
    _INSTRUMENTATION_DOCUMENT, ensure_ascii=False, allow_nan=False,
    sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()

_NORMAL_DETAIL_REASONS = frozenset({
    "JP_SESSION_BOUNDARY", "US_SESSION_BOUNDARY",
})
_NULL_PROOF_DOCUMENT = {
    "status": "NOT_PROVEN",
    "hardRpoClaimPermitted": False,
}


@dataclass(frozen=True)
class AdapterStatus:
    enabled: bool
    active: bool
    code: str
    canonical_artifact_path: str
    measurement_generation_id: Optional[str]
    registry_policy_sha256: Optional[str]
    instrumentation_coverage_sha256: str


@dataclass(frozen=True)
class CheckpointSamplingDecision:
    status: str
    requested: bool
    reason: str
    generation_id: Optional[str]
    token: Optional[str]


@dataclass(frozen=True)
class CheckpointAccountingObservation:
    status: str
    generation_id: Optional[str]
    token: Optional[str]
    total_serialized_bytes: int
    registered_section_bytes: Tuple[Tuple[str, int], ...]
    accounting_duration_micros: int
    full_size_buffers: int


@dataclass(frozen=True)
class CheckpointCommitResult:
    status: str
    persisted: bool
    bytes_written: int
    detailed: bool
    detail_reason: str


def feature_enabled(value: Any = None) -> bool:
    """Only the exact opt-in value enables measurement; absence is disabled."""
    return type(value) is str and value == FEATURE_FLAG_ENABLED_VALUE


def null_recovery_proof_document() -> dict[str, Any]:
    """Expose only the Proof Core's fail-closed public null result."""
    try:
        result = proof.proof_result_document(None)
        if type(result) is dict and set(result) == set(_NULL_PROOF_DOCUMENT) \
                and result["status"] == "NOT_PROVEN" \
                and result["hardRpoClaimPermitted"] is False:
            return dict(result)
    except Exception:
        pass
    return dict(_NULL_PROOF_DOCUMENT)


def _valid_build_sha(value: Any) -> bool:
    return type(value) is str and _BUILD_SHA_RE.fullmatch(value) is not None


def _valid_int(value: Any) -> bool:
    return type(value) is int and 0 <= value <= measurement.MAX_SAFE_INTEGER


def _valid_optional_int(value: Any) -> bool:
    return value is None or _valid_int(value)


def _canonical_time(value: Any) -> Optional[str]:
    if type(value) is not dt.datetime:
        return None
    try:
        return measurement.canonical_timestamp(value)
    except (TypeError, ValueError):
        return None


def _generation_id(*, policy_sha256: str, producer_build_sha: str) -> str:
    identity = {
        "instrumentationCoverageSha256":
            INSTRUMENTATION_COVERAGE_SHA256,
        "measurementSchemaSha256": measurement.MEASUREMENT_SCHEMA_SHA256,
        "producerBuildSha": producer_build_sha,
        "registryPolicySha256": policy_sha256,
    }
    digest = hashlib.sha256(json.dumps(
        identity, ensure_ascii=False, allow_nan=False, sort_keys=True,
        separators=(",", ":")).encode("utf-8")).hexdigest()
    return "measurement-" + digest[:32]


def _coverage_classification(mutation_id: str) -> Optional[str]:
    row = registry.mutation_by_id().get(mutation_id)
    if row is None:
        return None
    if row.currentWalCoverage in (
            registry.WalCoverage.COMPLETE,
            registry.WalCoverage.INDEPENDENT_DURABLE_SOURCE):
        return "OBSERVED_DURABLE"
    if row.currentWalCoverage in (
            registry.WalCoverage.PARTIAL,
            registry.WalCoverage.NOT_DURABLE_FOR_EXACT_REPLAY):
        return "OBSERVED_UNDURABLE"
    if row.currentWalCoverage is registry.WalCoverage.UNKNOWN:
        return "UNKNOWN"
    return None


def _registry_identity() -> Optional[str]:
    try:
        if registry.validate_registry() or \
                len(registry.mutations()) != EXPECTED_REGISTRY_MUTATION_COUNT:
            return None
        mutation_index = registry.mutation_by_id()
        if len(mutation_index) != EXPECTED_REGISTRY_MUTATION_COUNT or \
                frozenset(INSTRUMENTED_MUTATION_CLASS_IDS) - \
                frozenset(mutation_index):
            return None
        policy = registry.registry_policy_sha256()
        if type(policy) is not str or len(policy) != 64 or any(
                character not in "0123456789abcdef" for character in policy):
            return None
        return policy
    except Exception:
        return None


class RecoveryPhaseAAdapter:
    """Thread-safe, optional connector around the already-built cores."""

    def __init__(
            self, *, producer_build_sha: Any,
            started_at: Any, feature_flag_value: Any = None):
        self._lock = threading.RLock()
        self._enabled = feature_enabled(feature_flag_value)
        self._active = False
        self._code = "disabled"
        self._producer_build_sha: Optional[str] = None
        self._registry_policy_sha256: Optional[str] = None
        self._generation_id: Optional[str] = None
        self._decision: Optional[storage.PathDecision] = None
        self._accumulator: Optional[measurement.MeasurementAccumulator] = None
        self._identity_detail_pending = False
        self._producer_build_detail_pending = False
        self._sampling_serial = 0
        self._pending_sampling: OrderedDict[
            str, Tuple[str, str, str]] = OrderedDict()
        if not self._enabled:
            return
        if not _valid_build_sha(producer_build_sha) or \
                _canonical_time(started_at) is None:
            self._code = "build_identity_unavailable"
            return
        self._producer_build_sha = producer_build_sha
        self._start(started_at)

    def _start(self, started_at: dt.datetime) -> None:
        """Contain every optional diagnostics startup failure."""
        try:
            policy = _registry_identity()
            if policy is None:
                self._code = "registry_contract_unavailable"
                return
            generation = _generation_id(
                policy_sha256=policy,
                producer_build_sha=self._producer_build_sha or "")
            decision = storage.resolve_measurement_path()
            if type(decision) is not storage.PathDecision or \
                    not decision.accepted:
                self._code = "diagnostics_configuration_rejected"
                return
            if storage.prepare_diagnostics_namespace(decision) != "ok":
                self._code = "diagnostics_io_failure"
                return
            loaded = storage.load_artifact(decision)
            artifact = loaded.artifact if loaded.status == "loaded" else None
            identity_match = self._artifact_identity_matches(
                artifact, policy=policy, generation=generation)
            if not identity_match:
                old_build = artifact.get("producerBuildSha") \
                    if type(artifact) is dict else None
                invalidation = self._invalidation_code(
                    loaded.status, artifact, policy)
                artifact = measurement.new_artifact(
                    measurement_generation_id=generation,
                    producer_build_sha=self._producer_build_sha or "",
                    instrumentation_coverage_sha256=
                        INSTRUMENTATION_COVERAGE_SHA256,
                    created_at=started_at,
                    registry_policy_sha256=policy,
                    invalidation_code=invalidation)
                self._identity_detail_pending = True
                self._producer_build_detail_pending = \
                    type(old_build) is str and \
                    old_build != self._producer_build_sha
            assert artifact is not None
            self._accumulator = measurement.MeasurementAccumulator(artifact)
            self._registry_policy_sha256 = policy
            self._generation_id = generation
            self._decision = decision
            self._active = True
            self._code = "ready"
        except Exception:
            self._active = False
            self._code = "diagnostics_io_failure"

    @staticmethod
    def _invalidation_code(
            load_status: Any, artifact: Any, policy: str) -> str:
        if load_status == "registry_policy_mismatch" or (
                type(artifact) is dict and
                artifact.get("registryPolicySha256") != policy):
            return "registry_policy_mismatch"
        if load_status == "not_found":
            return "none"
        if load_status in ("configuration_rejected",):
            return "configuration_rejected"
        if load_status in ("io_failure",):
            return "persistence_failed"
        return "artifact_invalid"

    def _artifact_identity_matches(
            self, artifact: Any, *, policy: str, generation: str) -> bool:
        if type(artifact) is not dict:
            return False
        return all((
            artifact.get("schemaVersion") == measurement.SCHEMA_VERSION,
            artifact.get("measurementSchemaSha256") ==
                measurement.MEASUREMENT_SCHEMA_SHA256,
            artifact.get("registryPolicySha256") == policy,
            artifact.get("producerBuildSha") == self._producer_build_sha,
            artifact.get("instrumentationCoverageSha256") ==
                INSTRUMENTATION_COVERAGE_SHA256,
            artifact.get("measurementGenerationId") == generation,
        ))

    def _ensure_current_identity_locked(self, observed_at: Any) -> bool:
        observed_text = _canonical_time(observed_at)
        if not self._active or observed_text is None or \
                self._producer_build_sha is None:
            return False
        policy = _registry_identity()
        if policy is None:
            self._active = False
            self._code = "registry_contract_unavailable"
            return False
        generation = _generation_id(
            policy_sha256=policy,
            producer_build_sha=self._producer_build_sha)
        artifact = self._accumulator.artifact \
            if self._accumulator is not None else None
        if self._artifact_identity_matches(
                artifact, policy=policy, generation=generation):
            return True
        try:
            reset = measurement.new_artifact(
                measurement_generation_id=generation,
                producer_build_sha=self._producer_build_sha,
                instrumentation_coverage_sha256=
                    INSTRUMENTATION_COVERAGE_SHA256,
                created_at=observed_at,
                registry_policy_sha256=policy,
                invalidation_code=(
                    "registry_policy_mismatch"
                    if policy != self._registry_policy_sha256
                    else "artifact_invalid"))
            self._accumulator = measurement.MeasurementAccumulator(reset)
            self._registry_policy_sha256 = policy
            self._generation_id = generation
            self._identity_detail_pending = True
            self._pending_sampling.clear()
            self._code = "ready"
            return True
        except Exception:
            self._active = False
            self._code = "registry_contract_unavailable"
            return False

    def status(self) -> AdapterStatus:
        with self._lock:
            return AdapterStatus(
                enabled=self._enabled, active=self._active, code=self._code,
                canonical_artifact_path=CANONICAL_ARTIFACT_PATH,
                measurement_generation_id=self._generation_id,
                registry_policy_sha256=self._registry_policy_sha256,
                instrumentation_coverage_sha256=
                    INSTRUMENTATION_COVERAGE_SHA256)

    def record_mutation_after_authority(
            self, mutation_class_id: Any, *,
            estimated_plaintext_bytes: Any, record_count: Any,
            latency_micros: Any, observed_at: Any,
            local_sequence: Any = None) -> str:
        """Record one of five exact producers after its authority succeeds."""
        try:
            with self._lock:
                if not self._active:
                    return "disabled"
                if type(mutation_class_id) is not str or \
                        mutation_class_id not in \
                        INSTRUMENTED_MUTATION_CLASS_IDS or not all(
                            _valid_int(value) for value in (
                                estimated_plaintext_bytes, record_count,
                                latency_micros)) or \
                        not _valid_optional_int(local_sequence):
                    return "invalid_observation"
                if not self._ensure_current_identity_locked(observed_at) or \
                        self._accumulator is None:
                    return "measurement_unavailable"
                coverage = _coverage_classification(mutation_class_id)
                if coverage is None:
                    return "measurement_unavailable"
                return self._accumulator.record_mutation(
                    mutation_class_id,
                    estimated_plaintext_bytes=estimated_plaintext_bytes,
                    record_count=record_count, latency_micros=latency_micros,
                    success=True, coverage_classification=coverage,
                    observed_at=observed_at, local_sequence=local_sequence)
        except Exception:
            return "measurement_unavailable"

    def checkpoint_sampling_decision(
            self, *, observed_at: Any,
            jp_session_boundary: Any = False,
            us_session_boundary: Any = False,
            owner_authorized: Any = False) -> CheckpointSamplingDecision:
        """Request detail without changing checkpoint authority or outcome."""
        none = CheckpointSamplingDecision(
            "not_requested", False, "NONE", None, None)
        try:
            if any(type(value) is not bool for value in (
                    jp_session_boundary, us_session_boundary,
                    owner_authorized)):
                return CheckpointSamplingDecision(
                    "invalid_observation", False, "NONE", None, None)
            observed_text = _canonical_time(observed_at)
            if observed_text is None:
                return CheckpointSamplingDecision(
                    "invalid_observation", False, "NONE", None, None)
            with self._lock:
                if not self._active:
                    return none
                if not self._ensure_current_identity_locked(observed_at) or \
                        self._accumulator is None or \
                        self._generation_id is None:
                    return CheckpointSamplingDecision(
                        "measurement_unavailable", False, "NONE", None, None)
                day = observed_text[:10]
                normal_today = sum(
                    1 for sample in
                    self._accumulator.artifact["checkpointSamples"]
                    if sample["observedAt"][:10] == day and
                    sample["detailReason"] in _NORMAL_DETAIL_REASONS)
                normal_today = min(
                    normal_today,
                    measurement.MAX_DETAILED_SESSION_SAMPLES_PER_DAY)
                core_decision = measurement.detailed_sampling_policy(
                    measurement.DetailedSamplingContext(
                        jp_session_boundary=jp_session_boundary,
                        us_session_boundary=us_session_boundary,
                        accounting_schema_changed=
                            self._identity_detail_pending and not
                            self._producer_build_detail_pending,
                        producer_build_changed=
                            self._producer_build_detail_pending,
                        owner_authorized=owner_authorized,
                        detailed_session_samples_today=normal_today))
                if not core_decision.requested:
                    return CheckpointSamplingDecision(
                        "not_requested", False, "NONE",
                        self._generation_id, None)
                self._sampling_serial = (
                    self._sampling_serial % measurement.MAX_SAFE_INTEGER) + 1
                token = "sampling-%016x" % self._sampling_serial
                while token in self._pending_sampling:
                    self._sampling_serial = (
                        self._sampling_serial %
                        measurement.MAX_SAFE_INTEGER) + 1
                    token = "sampling-%016x" % self._sampling_serial
                self._pending_sampling[token] = (
                    self._generation_id, core_decision.reason, day)
                while len(self._pending_sampling) > \
                        MAX_PENDING_SAMPLING_DECISIONS:
                    self._pending_sampling.popitem(last=False)
                return CheckpointSamplingDecision(
                    "requested", True, core_decision.reason,
                    self._generation_id, token)
        except Exception:
            return CheckpointSamplingDecision(
                "measurement_unavailable", False, "NONE", None, None)

    def account_checkpoint(
            self, checkpoint: Any,
            sampling: Any) -> CheckpointAccountingObservation:
        """Transiently count an exact checkpoint; never retain its payload.

        This is the adapter's sole non-scalar input.  It exists only because
        Measurement Core must stream the already-built checkpoint mapping once
        without allocating a second full-size serialization buffer.
        """
        unavailable = CheckpointAccountingObservation(
            "measurement_unavailable", None, None, 0, (), 0, 0)
        try:
            if type(checkpoint) is not dict or \
                    type(sampling) is not CheckpointSamplingDecision or \
                    not sampling.requested or sampling.token is None or \
                    sampling.generation_id is None:
                return unavailable
            with self._lock:
                expected = self._pending_sampling.get(sampling.token)
                if expected is None or expected[0] != sampling.generation_id \
                        or expected[1] != sampling.reason or \
                        self._generation_id != sampling.generation_id:
                    return unavailable
            started = time.perf_counter_ns()
            accounted = measurement.streaming_checkpoint_accounting(checkpoint)
            elapsed = min(
                measurement.MAX_SAFE_INTEGER,
                max(0, (time.perf_counter_ns() - started) // 1000))
            sections = tuple(sorted(
                accounted.registered_section_bytes.items()))
            if accounted.full_size_buffers != 0 or not _valid_int(
                    accounted.total_serialized_bytes) or any(
                        type(key) is not str or not _valid_int(size)
                        for key, size in sections):
                return unavailable
            return CheckpointAccountingObservation(
                "accounted", sampling.generation_id, sampling.token,
                accounted.total_serialized_bytes, sections, elapsed,
                accounted.full_size_buffers)
        except Exception:
            return unavailable

    def abandon_checkpoint(self, sampling: Any) -> None:
        """Release a bounded sampling token after authority failure."""
        try:
            if type(sampling) is CheckpointSamplingDecision and \
                    sampling.token is not None:
                with self._lock:
                    self._pending_sampling.pop(sampling.token, None)
        except Exception:
            pass

    def record_checkpoint_after_authority(
            self, *, observed_at: Any, sampling: Any,
            accounting: Any = None,
            checkpoint_serialized_bytes: Any,
            serialization_duration_micros: Any,
            write_seal_duration_micros: Any,
            fsync_readback_duration_micros: Any,
            peak_rss_bytes: Any,
            local_wal_bytes: Any, local_wal_records: Any,
            local_wal_high_water: Any,
            legacy_remote_ack_sequence: Any = None,
            legacy_remote_ack_at: Any = None) -> CheckpointCommitResult:
        """Record and flush only after the checkpoint authority has succeeded.

        Until the scanner exposes an isolated fsync/readback timer, it must
        pass ``UNOBSERVED_FSYNC_READBACK_DURATION_MICROS``.  A broader
        checkpoint timer is not an estimate of this field.
        """
        failed = CheckpointCommitResult(
            "measurement_unavailable", False, 0, False, "NONE")
        try:
            scalars = (
                checkpoint_serialized_bytes, serialization_duration_micros,
                write_seal_duration_micros, fsync_readback_duration_micros,
                local_wal_bytes, local_wal_records, local_wal_high_water)
            if not all(_valid_int(value) for value in scalars) or \
                    not _valid_optional_int(peak_rss_bytes) or \
                    not _valid_optional_int(legacy_remote_ack_sequence) or \
                    _canonical_time(observed_at) is None or \
                    (legacy_remote_ack_at is not None and
                     _canonical_time(legacy_remote_ack_at) is None):
                return CheckpointCommitResult(
                    "invalid_observation", False, 0, False, "NONE")
            if type(sampling) is not CheckpointSamplingDecision:
                return CheckpointCommitResult(
                    "invalid_observation", False, 0, False, "NONE")
            with self._lock:
                if not self._active or \
                        not self._ensure_current_identity_locked(observed_at) \
                        or self._accumulator is None or \
                        self._decision is None:
                    return failed
                detailed, reason, sections, accounting_micros = \
                    self._consume_detail_locked(
                        sampling, accounting, checkpoint_serialized_bytes,
                        observed_at)
                sample_id = "sample-" + secrets.token_hex(16)
                record_status = self._accumulator.record_checkpoint(
                    sample_id, observed_at=observed_at, success=True,
                    detailed=detailed, detail_reason=reason,
                    checkpoint_serialized_bytes=checkpoint_serialized_bytes,
                    section_serialized_bytes=sections,
                    serialization_duration_micros=
                        serialization_duration_micros,
                    section_accounting_duration_micros=accounting_micros,
                    write_seal_duration_micros=write_seal_duration_micros,
                    fsync_readback_duration_micros=
                        fsync_readback_duration_micros,
                    peak_rss_bytes=peak_rss_bytes,
                    local_wal_bytes=local_wal_bytes,
                    local_wal_records=local_wal_records,
                    local_wal_high_water=local_wal_high_water,
                    legacy_remote_ack_sequence=legacy_remote_ack_sequence,
                    legacy_remote_ack_at=legacy_remote_ack_at)
                if record_status != "recorded":
                    return CheckpointCommitResult(
                        record_status, False, 0, False, "NONE")
                plan = measurement.plan_retention(
                    self._accumulator.artifact, now=observed_at)
                if plan.status != "ok" or plan.artifact is None:
                    return CheckpointCommitResult(
                        plan.status, False, 0, detailed, reason)
                candidate = measurement.MeasurementAccumulator(plan.artifact)
                persisted = storage.persist_retention_plan(
                    self._decision, plan)
                if persisted.status != "persisted":
                    return CheckpointCommitResult(
                        persisted.status, False, 0, detailed, reason)
                self._accumulator = candidate
                if detailed and reason == \
                        "ACCOUNTING_SCHEMA_OR_BUILD_CHANGE":
                    self._identity_detail_pending = False
                    self._producer_build_detail_pending = False
                return CheckpointCommitResult(
                    "persisted", True, persisted.bytes_written,
                    detailed, reason)
        except Exception:
            return failed

    def _consume_detail_locked(
            self, sampling: CheckpointSamplingDecision, accounting: Any,
            checkpoint_serialized_bytes: int,
            observed_at: dt.datetime) -> Tuple[
                bool, str, dict[str, int], int]:
        if not sampling.requested or sampling.token is None or \
                sampling.generation_id is None:
            return False, "NONE", {}, 0
        expected = self._pending_sampling.pop(sampling.token, None)
        if expected is None or expected[0] != self._generation_id or \
                expected[0] != sampling.generation_id or \
                expected[1] != sampling.reason:
            return False, "NONE", {}, 0
        reason = expected[1]
        if reason == "ACCOUNTING_SCHEMA_OR_BUILD_CHANGE" and not \
                self._identity_detail_pending:
            return False, "NONE", {}, 0
        if reason in _NORMAL_DETAIL_REASONS:
            day = (_canonical_time(observed_at) or "")[:10]
            normal_today = sum(
                1 for sample in self._accumulator.artifact[
                    "checkpointSamples"]
                if sample["observedAt"][:10] == day and
                sample["detailReason"] in _NORMAL_DETAIL_REASONS)
            if normal_today >= \
                    measurement.MAX_DETAILED_SESSION_SAMPLES_PER_DAY:
                return False, "NONE", {}, 0
        if type(accounting) is not CheckpointAccountingObservation or \
                accounting.status != "accounted" or \
                accounting.generation_id != self._generation_id or \
                accounting.token != sampling.token or \
                accounting.total_serialized_bytes != \
                    checkpoint_serialized_bytes or \
                accounting.full_size_buffers != 0 or \
                not _valid_int(accounting.accounting_duration_micros):
            return False, "NONE", {}, 0
        sections = dict(accounting.registered_section_bytes)
        if len(sections) != len(accounting.registered_section_bytes) or \
                len(sections) > measurement.MAX_CHECKPOINT_SECTION_KEYS or \
                any(type(key) is not str or not _valid_int(value)
                    for key, value in sections.items()):
            return False, "NONE", {}, 0
        return True, reason, sections, accounting.accounting_duration_micros


__all__ = (
    "AdapterStatus", "CANONICAL_ARTIFACT_PATH",
    "CheckpointAccountingObservation", "CheckpointCommitResult",
    "CheckpointSamplingDecision", "EXPECTED_REGISTRY_MUTATION_COUNT",
    "FEATURE_FLAG_ENABLED_VALUE", "FEATURE_FLAG_NAME",
    "INSTRUMENTATION_COVERAGE_SHA256",
    "INSTRUMENTED_MUTATION_CLASS_IDS", "PRODUCER_SEAMS",
    "RecoveryPhaseAAdapter", "feature_enabled",
    "null_recovery_proof_document",
    "UNOBSERVED_DURATION_MICROS",
    "UNOBSERVED_FSYNC_READBACK_DURATION_MICROS",
)
