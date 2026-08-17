"""Focused runtime-boundary tests for the Recovery Phase A adapter."""
from __future__ import annotations

import concurrent.futures
import datetime as dt
import inspect
import json
from pathlib import Path
import sys
import types

import pytest

import argus_recovery_measurement as measurement
import argus_recovery_measurement_storage as storage
import argus_recovery_phase_a_adapter as phase_a
import argus_recovery_registry as registry


_moomoo = types.ModuleType("moomoo")
_moomoo.OpenQuoteContext = lambda *args, **kwargs: None
_moomoo.OpenSecTradeContext = lambda *args, **kwargs: None
_moomoo.RET_OK = 0
sys.modules.setdefault("moomoo", _moomoo)
import scanner


UTC = dt.timezone.utc
START = dt.datetime(2026, 8, 15, 0, 0, 0, tzinfo=UTC)
BUILD_A = "a" * 40
BUILD_B = "b" * 40
CHECKPOINT = {
    "marketLedger": {"rows": 3},
    "missions": [{"status": "complete"}],
    "nonRegisteredScalar": 7,
}
_REAL_RESOLVE_MEASUREMENT_PATH = storage.resolve_measurement_path


@pytest.fixture
def scanner_recovery_state():
    """Restore the mutable scanner seams touched by focused integration tests."""
    saved_context = dict(scanner._MISSION_TICK_CONTEXT)
    saved_startup = dict(scanner._STARTUP)
    saved_startup_recorded = scanner._RECOVERY_PHASE_A_STARTUP_RECORDED
    scanner._recovery_phase_a_take_checkpoint()
    try:
        yield
    finally:
        scanner._recovery_phase_a_take_checkpoint()
        scanner._MISSION_TICK_CONTEXT.clear()
        scanner._MISSION_TICK_CONTEXT.update(saved_context)
        scanner._STARTUP.clear()
        scanner._STARTUP.update(saved_startup)
        scanner._RECOVERY_PHASE_A_STARTUP_RECORDED = \
            saved_startup_recorded


class _ScannerAdapterProbe:
    def __init__(self, *, raise_mutation=False, raise_checkpoint=False):
        self.mutations = []
        self.checkpoints = []
        self.abandoned = []
        self.raise_mutation = raise_mutation
        self.raise_checkpoint = raise_checkpoint

    def status(self):
        return types.SimpleNamespace(active=True)

    def record_mutation_after_authority(self, mutation_class_id, **kwargs):
        self.mutations.append((mutation_class_id, kwargs))
        if self.raise_mutation:
            raise RuntimeError("diagnostics mutation failure")
        return "recorded"

    def record_checkpoint_after_authority(self, **kwargs):
        assert scanner._DURABLE_CHECKPOINT_LOCK._is_owned() is False
        self.checkpoints.append(kwargs)
        if self.raise_checkpoint:
            raise RuntimeError("diagnostics persistence failure")
        return types.SimpleNamespace(status="persisted")

    def abandon_checkpoint(self, sampling):
        self.abandoned.append(sampling)


def _temporary_decision(tmp_path):
    plan = storage.authoritative_path_plan(
        persistent_root=str(tmp_path / "authority"),
        temporary_root=str(tmp_path / "temporary"))
    decision = _REAL_RESOLVE_MEASUREMENT_PATH(
        diagnostics_root=str(tmp_path / "diagnostics" / "measurement"),
        protected_paths=plan)
    assert decision.accepted
    return decision


def _start_adapter(
        monkeypatch, tmp_path, *, build=BUILD_A, started_at=START):
    decision = _temporary_decision(tmp_path)
    calls = []

    def exact_resolver(*args, **kwargs):
        calls.append((args, kwargs))
        assert args == ()
        assert kwargs == {}
        return decision

    monkeypatch.setattr(
        phase_a.storage, "resolve_measurement_path", exact_resolver)
    adapter = phase_a.RecoveryPhaseAAdapter(
        producer_build_sha=build, started_at=started_at,
        feature_flag_value="1")
    assert calls == [((), {})]
    assert adapter.status().active is True
    return adapter, decision


def _commit(
        adapter, observed_at, *, jp=False, us=False, owner=False,
        checkpoint=CHECKPOINT):
    sampling = adapter.checkpoint_sampling_decision(
        observed_at=observed_at, jp_session_boundary=jp,
        us_session_boundary=us, owner_authorized=owner)
    accounting = adapter.account_checkpoint(checkpoint, sampling) \
        if sampling.requested else None
    checkpoint_size = measurement.streaming_checkpoint_accounting(
        checkpoint).total_serialized_bytes
    result = adapter.record_checkpoint_after_authority(
        observed_at=observed_at, sampling=sampling, accounting=accounting,
        checkpoint_serialized_bytes=checkpoint_size,
        serialization_duration_micros=11,
        write_seal_duration_micros=12,
        fsync_readback_duration_micros=
            phase_a.UNOBSERVED_FSYNC_READBACK_DURATION_MICROS,
        peak_rss_bytes=20_000_000,
        local_wal_bytes=100, local_wal_records=2,
        local_wal_high_water=8)
    return sampling, accounting, result


@pytest.mark.parametrize("raw", [None, "", "0", "true", "TRUE", 1, True])
def test_feature_flag_is_exact_and_default_disabled_without_io(
        monkeypatch, raw):
    def forbidden_resolver(*_args, **_kwargs):
        raise AssertionError("disabled adapter touched diagnostics storage")

    monkeypatch.setattr(
        phase_a.storage, "resolve_measurement_path", forbidden_resolver)
    adapter = phase_a.RecoveryPhaseAAdapter(
        producer_build_sha=BUILD_A, started_at=START,
        feature_flag_value=raw)
    status = adapter.status()
    assert phase_a.feature_enabled(raw) is False
    assert status.enabled is False
    assert status.active is False
    assert status.code == "disabled"
    assert adapter.record_mutation_after_authority(
        "core.batch_cursor", estimated_plaintext_bytes=1,
        record_count=1, latency_micros=1,
        observed_at=START) == "disabled"


@pytest.mark.parametrize("bad_build", [None, "", "A" * 40, "a" * 39,
                                        "g" * 40, True])
def test_missing_or_malformed_exact_build_disables_measurement_boot(
        monkeypatch, bad_build):
    def forbidden_resolver(*_args, **_kwargs):
        raise AssertionError("invalid build touched diagnostics storage")

    monkeypatch.setattr(
        phase_a.storage, "resolve_measurement_path", forbidden_resolver)
    adapter = phase_a.RecoveryPhaseAAdapter(
        producer_build_sha=bad_build, started_at=START,
        feature_flag_value="1")
    assert adapter.status().enabled is True
    assert adapter.status().active is False
    assert adapter.status().code == "build_identity_unavailable"


def test_startup_uses_only_canonical_resolver_and_in_process_rlock(
        monkeypatch, tmp_path):
    adapter, _decision = _start_adapter(monkeypatch, tmp_path)
    status = adapter.status()
    assert status.canonical_artifact_path == \
        "/var/data/diagnostics/recovery-measurement/measurement-v1.json"
    assert phase_a.CANONICAL_ARTIFACT_PATH == \
        storage.CANONICAL_ARTIFACT_PATH
    assert adapter._lock.acquire(blocking=False) is True
    adapter._lock.release()


def test_exact_five_scalar_producers_bind_registry_and_remain_incomplete(
        monkeypatch, tmp_path):
    adapter, decision = _start_adapter(monkeypatch, tmp_path)
    expected = (
        "core.ops_journal_transition",
        "core.mission_transition",
        "core.batch_cursor",
        "durability.receipt_ack",
        "startup.restore_transition",
    )
    assert phase_a.INSTRUMENTED_MUTATION_CLASS_IDS == expected
    assert len(registry.mutations()) == phase_a.EXPECTED_REGISTRY_MUTATION_COUNT \
        == 27
    for index, mutation_id in enumerate(expected):
        assert adapter.record_mutation_after_authority(
            mutation_id, estimated_plaintext_bytes=100 + index,
            record_count=1, latency_micros=20 + index,
            observed_at=START, local_sequence=index) == "recorded"

    # Mutations are memory-only until a successful authority checkpoint flush.
    assert storage.load_artifact(decision).status == "not_found"
    sampling, accounting, committed = _commit(adapter, START)
    assert sampling.reason == "ACCOUNTING_SCHEMA_OR_BUILD_CHANGE"
    assert accounting.status == "accounted"
    assert committed == phase_a.CheckpointCommitResult(
        "persisted", True, committed.bytes_written, True,
        "ACCOUNTING_SCHEMA_OR_BUILD_CHANGE")

    loaded = storage.load_artifact(decision)
    assert loaded.status == "loaded"
    artifact = loaded.artifact
    assert artifact is not None
    assert artifact["registryPolicySha256"] == \
        registry.registry_policy_sha256()
    assert artifact["instrumentationCoverageSha256"] == \
        phase_a.INSTRUMENTATION_COVERAGE_SHA256
    assert artifact["authoritative"] is False
    assert artifact["mode"] == "SHADOW"
    assert artifact["coverageStatus"] == "INCOMPLETE"
    assert artifact["proofStatus"] == "NOT_PROVEN"
    assert artifact["acceptanceClockStarted"] is False
    assert artifact["aggregateCounters"]["lifetimeMutationCount"] == 5
    assert artifact["coverage"]["instrumentedMutationClassIds"] == \
        sorted(expected)
    assert artifact["coverage"]["expectedMutationClassCount"] == 27
    assert artifact["coverage"]["allExpectedMutationClassesObserved"] \
        is False
    classifications = {
        row["mutationClassId"]: row["coverageClassification"]
        for row in artifact["recentMutations"]
    }
    assert classifications == {
        "core.ops_journal_transition": "OBSERVED_UNDURABLE",
        "core.mission_transition": "OBSERVED_UNDURABLE",
        "core.batch_cursor": "OBSERVED_UNDURABLE",
        "durability.receipt_ack": "OBSERVED_DURABLE",
        "startup.restore_transition": "UNKNOWN",
    }


def test_mutation_boundary_is_scalar_only_and_rejects_sixth_class(
        monkeypatch, tmp_path):
    adapter, _decision = _start_adapter(monkeypatch, tmp_path)
    parameters = inspect.signature(
        phase_a.RecoveryPhaseAAdapter.
        record_mutation_after_authority).parameters
    assert set(parameters) == {
        "self", "mutation_class_id", "estimated_plaintext_bytes",
        "record_count", "latency_micros", "observed_at",
        "local_sequence",
    }
    assert not {
        "payload", "metadata", "context", "exception", "error",
        "success", "proof", "remote_healthy",
    } & set(parameters)
    assert adapter.record_mutation_after_authority(
        "market.ledger_update", estimated_plaintext_bytes=1,
        record_count=1, latency_micros=1,
        observed_at=START) == "invalid_observation"
    assert adapter.record_mutation_after_authority(
        "core.batch_cursor", estimated_plaintext_bytes=True,
        record_count=1, latency_micros=1,
        observed_at=START) == "invalid_observation"


def test_sealed_mapping_is_one_transient_identity_preserving_input(
        monkeypatch, tmp_path):
    adapter, _decision = _start_adapter(monkeypatch, tmp_path)
    sampling = adapter.checkpoint_sampling_decision(observed_at=START)
    sealed = {
        "missions": {"transient-owner-sentinel": "never-retained"},
        "marketLedger": [1, 2, 3],
    }
    original = measurement.streaming_checkpoint_accounting
    calls = []

    def identity_probe(value, **kwargs):
        calls.append(value is sealed)
        return original(value, **kwargs)

    monkeypatch.setattr(
        phase_a.measurement, "streaming_checkpoint_accounting",
        identity_probe)
    observation = adapter.account_checkpoint(sealed, sampling)
    assert calls == [True]
    assert observation.status == "accounted"
    assert observation.full_size_buffers == 0
    assert "transient-owner-sentinel" not in repr(observation)
    assert "never-retained" not in repr(observation)
    assert "transient-owner-sentinel" not in repr(adapter.__dict__)
    assert "never-retained" not in repr(adapter.__dict__)


def test_sampling_caps_normal_sessions_but_allows_identity_and_owner(
        monkeypatch, tmp_path):
    adapter, _decision = _start_adapter(monkeypatch, tmp_path)
    identity, _accounting, committed = _commit(adapter, START)
    assert identity.reason == "ACCOUNTING_SCHEMA_OR_BUILD_CHANGE"
    assert committed.detailed is True

    jp, _accounting, committed = _commit(
        adapter, START + dt.timedelta(hours=1), jp=True)
    assert jp.reason == "JP_SESSION_BOUNDARY"
    assert committed.detailed is True
    us, _accounting, committed = _commit(
        adapter, START + dt.timedelta(hours=2), us=True)
    assert us.reason == "US_SESSION_BOUNDARY"
    assert committed.detailed is True

    capped = adapter.checkpoint_sampling_decision(
        observed_at=START + dt.timedelta(hours=3),
        jp_session_boundary=True)
    assert capped.requested is False
    assert capped.reason == "NONE"
    owner = adapter.checkpoint_sampling_decision(
        observed_at=START + dt.timedelta(hours=3),
        owner_authorized=True)
    assert owner.requested is True
    assert owner.reason == "OWNER_AUTHORIZED"


def test_build_drift_rotates_generation_and_requires_detailed_sample(
        monkeypatch, tmp_path):
    adapter_a, decision = _start_adapter(monkeypatch, tmp_path, build=BUILD_A)
    _commit(adapter_a, START)
    generation_a = adapter_a.status().measurement_generation_id

    adapter_b, decision_b = _start_adapter(
        monkeypatch, tmp_path, build=BUILD_B,
        started_at=START + dt.timedelta(seconds=10))
    assert decision_b == decision
    generation_b = adapter_b.status().measurement_generation_id
    assert generation_b != generation_a
    sampling, _accounting, result = _commit(
        adapter_b, START + dt.timedelta(seconds=10))
    assert sampling.reason == "ACCOUNTING_SCHEMA_OR_BUILD_CHANGE"
    assert result.persisted is True
    artifact = storage.load_artifact(decision).artifact
    assert artifact is not None
    assert artifact["producerBuildSha"] == BUILD_B
    assert artifact["measurementGenerationId"] == generation_b
    assert artifact["invalidation"]["code"] == "artifact_invalid"
    assert artifact["aggregateCounters"]["lifetimeMutationCount"] == 0


@pytest.mark.parametrize("drift,expected_invalidation", [
    ("measurement_generation", "artifact_invalid"),
    ("instrumentation", "artifact_invalid"),
    ("schema", "artifact_invalid"),
    ("registry_policy", "registry_policy_mismatch"),
])
def test_loaded_identity_drift_rotates_without_reinterpreting_rows(
        monkeypatch, tmp_path, drift, expected_invalidation):
    decision = _temporary_decision(tmp_path)
    assert storage.prepare_diagnostics_namespace(decision) == "ok"
    policy = registry.registry_policy_sha256()
    artifact = measurement.new_artifact(
        measurement_generation_id=(
            "foreign-generation" if drift == "measurement_generation"
            else "source-generation"),
        producer_build_sha=BUILD_A,
        instrumentation_coverage_sha256=(
            "f" * 64 if drift == "instrumentation"
            else phase_a.INSTRUMENTATION_COVERAGE_SHA256),
        created_at=START,
        registry_policy_sha256=(
            "e" * 64 if drift == "registry_policy" else policy))
    if drift != "registry_policy":
        assert measurement.MeasurementAccumulator(artifact).record_mutation(
            "core.batch_cursor", estimated_plaintext_bytes=99,
            record_count=1, latency_micros=1, success=True,
            coverage_classification="OBSERVED_UNDURABLE",
            observed_at=START) == "recorded"
    if drift == "schema":
        artifact["schemaVersion"] = "old-measurement-schema"
    if drift in ("schema", "registry_policy"):
        Path(decision.artifact_path).write_text(json.dumps(
            artifact, ensure_ascii=False, allow_nan=False,
            sort_keys=True, separators=(",", ":")), encoding="utf-8")
    else:
        assert storage.persist_artifact(
            decision, artifact, now=START).status == "persisted"

    def exact_resolver(*args, **kwargs):
        assert args == () and kwargs == {}
        return decision

    monkeypatch.setattr(
        phase_a.storage, "resolve_measurement_path", exact_resolver)
    adapter = phase_a.RecoveryPhaseAAdapter(
        producer_build_sha=BUILD_A,
        started_at=START + dt.timedelta(seconds=1),
        feature_flag_value="1")
    sampling, _accounting, result = _commit(
        adapter, START + dt.timedelta(seconds=1))
    assert sampling.reason == "ACCOUNTING_SCHEMA_OR_BUILD_CHANGE"
    assert result.persisted is True
    rotated = storage.load_artifact(decision).artifact
    assert rotated is not None
    assert rotated["measurementGenerationId"] == \
        adapter.status().measurement_generation_id
    assert rotated["instrumentationCoverageSha256"] == \
        phase_a.INSTRUMENTATION_COVERAGE_SHA256
    assert rotated["registryPolicySha256"] == policy
    assert rotated["invalidation"]["code"] == expected_invalidation
    assert rotated["aggregateCounters"]["lifetimeMutationCount"] == 0


def test_live_registry_policy_drift_resets_before_next_observation(
        monkeypatch, tmp_path):
    adapter, decision = _start_adapter(monkeypatch, tmp_path)
    old_generation = adapter.status().measurement_generation_id
    assert adapter.record_mutation_after_authority(
        "core.batch_cursor", estimated_plaintext_bytes=10,
        record_count=1, latency_micros=1,
        observed_at=START) == "recorded"
    monkeypatch.setattr(
        registry, "registry_policy_sha256", lambda: "f" * 64)
    changed = START + dt.timedelta(seconds=1)
    assert adapter.record_mutation_after_authority(
        "core.batch_cursor", estimated_plaintext_bytes=20,
        record_count=1, latency_micros=1,
        observed_at=changed) == "recorded"
    assert adapter.status().measurement_generation_id != old_generation
    sampling, _accounting, result = _commit(adapter, changed)
    assert sampling.reason == "ACCOUNTING_SCHEMA_OR_BUILD_CHANGE"
    assert result.persisted is True
    artifact = storage.load_artifact(decision).artifact
    assert artifact is not None
    assert artifact["registryPolicySha256"] == "f" * 64
    assert artifact["invalidation"]["code"] == \
        "registry_policy_mismatch"
    assert artifact["aggregateCounters"]["lifetimeMutationCount"] == 1


def test_optional_measurement_failures_never_escape_or_change_proof(
        monkeypatch, tmp_path):
    adapter, _decision = _start_adapter(monkeypatch, tmp_path)

    def explode(*_args, **_kwargs):
        raise RuntimeError("OWNER-SECRET-MUST-NOT-ESCAPE")

    monkeypatch.setattr(
        measurement.MeasurementAccumulator, "record_mutation", explode)
    assert adapter.record_mutation_after_authority(
        "core.batch_cursor", estimated_plaintext_bytes=1,
        record_count=1, latency_micros=1,
        observed_at=START) == "measurement_unavailable"

    monkeypatch.setattr(
        phase_a.proof, "proof_result_document",
        lambda _result: {
            "status": "PROVEN", "hardRpoClaimPermitted": True})
    assert phase_a.null_recovery_proof_document() == {
        "status": "NOT_PROVEN", "hardRpoClaimPermitted": False}


def test_persistence_failure_is_contained_after_authority(
        monkeypatch, tmp_path):
    adapter, decision = _start_adapter(monkeypatch, tmp_path)
    sampling = adapter.checkpoint_sampling_decision(observed_at=START)
    accounting = adapter.account_checkpoint(CHECKPOINT, sampling)
    total = accounting.total_serialized_bytes
    monkeypatch.setattr(
        phase_a.storage, "persist_retention_plan",
        lambda *_args, **_kwargs: storage.PersistenceResult(
            "persistence_failed"))
    result = adapter.record_checkpoint_after_authority(
        observed_at=START, sampling=sampling, accounting=accounting,
        checkpoint_serialized_bytes=total,
        serialization_duration_micros=1,
        write_seal_duration_micros=1,
        fsync_readback_duration_micros=
            phase_a.UNOBSERVED_FSYNC_READBACK_DURATION_MICROS,
        peak_rss_bytes=None, local_wal_bytes=0,
        local_wal_records=0, local_wal_high_water=0)
    assert result.status == "persistence_failed"
    assert result.persisted is False
    assert storage.load_artifact(decision).status == "not_found"


def test_rlock_serializes_eight_thread_scalar_mutation_producers(
        monkeypatch, tmp_path):
    adapter, decision = _start_adapter(monkeypatch, tmp_path)

    def record(index):
        return adapter.record_mutation_after_authority(
            "core.mission_transition", estimated_plaintext_bytes=index,
            record_count=1, latency_micros=1,
            observed_at=START, local_sequence=index)

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        statuses = list(executor.map(record, range(80)))
    assert statuses == ["recorded"] * 80
    _commit(adapter, START)
    artifact = storage.load_artifact(decision).artifact
    assert artifact is not None
    assert artifact["aggregateCounters"]["lifetimeMutationCount"] == 80
    assert artifact["aggregateCounters"]["lifetimeSuccessCount"] == 80


def test_null_verifier_has_no_evidence_or_raw_boolean_input():
    assert phase_a.null_recovery_proof_document() == {
        "status": "NOT_PROVEN", "hardRpoClaimPermitted": False}
    assert inspect.signature(
        phase_a.null_recovery_proof_document).parameters == {}
    source = inspect.getsource(phase_a)
    assert "_trusted_evidence_from_verifier" not in source
    assert phase_a.UNOBSERVED_DURATION_MICROS == 0
    assert phase_a.UNOBSERVED_FSYNC_READBACK_DURATION_MICROS == 0


def test_linux_4gib_measurement_job_is_exact_sha_and_terminally_gated():
    workflow = Path(".github/workflows/memory-attribution.yml").read_text(
        encoding="utf-8")
    job = workflow.split(
        "\n  linux-4gib-recovery-measurement:\n", 1)[1].split(
        "\n  linux-4gib-normalized-hash:\n", 1)[0]
    assert "--memory 4g --memory-swap 4g" in job
    assert 'test "$(cat /sys/fs/cgroup/memory.max)" = "4294967296"' \
        in job
    assert 'test "$(cat /sys/fs/cgroup/memory.swap.max)" = "0"' in job
    assert "pip install --quiet -r requirements.txt pytest" in job
    assert "scripts/recovery_measurement_benchmark.py" in job
    assert "scripts/recovery_measurement_retention_benchmark.py" in job
    assert 'report["oomDelta"] == 0' in job
    assert 'report["oomKillDelta"] == 0' in job
    assert "round1-recovery-measurement-proof-${{ github.sha }}" in job
    assert "artifacts/recovery-measurement-benchmark.json" in job
    assert "artifacts/recovery-measurement-retention-benchmark.json" in job
    assert "artifacts/round1-recovery-measurement-cgroup.json" in job


def test_scanner_constructs_adapter_once_from_exact_flag_and_build_only(
        monkeypatch, scanner_recovery_state):
    calls = []
    created = object()

    def construct(**kwargs):
        calls.append(kwargs)
        return created

    monkeypatch.setattr(
        scanner.argus_recovery_phase_a_adapter,
        "RecoveryPhaseAAdapter", construct)
    monkeypatch.setattr(scanner, "_backend_exact_sha", lambda: BUILD_A)
    monkeypatch.setattr(scanner, "_RECOVERY_PHASE_A_ADAPTER", None)
    monkeypatch.delenv(phase_a.FEATURE_FLAG_NAME, raising=False)
    assert scanner._recovery_phase_a_instance() is created
    assert scanner._recovery_phase_a_instance() is created
    assert len(calls) == 1
    assert calls[0]["producer_build_sha"] == BUILD_A
    assert calls[0]["feature_flag_value"] is None
    assert calls[0]["started_at"].tzinfo is not None
    assert set(calls[0]) == {
        "producer_build_sha", "started_at", "feature_flag_value"}

    monkeypatch.setattr(scanner, "_RECOVERY_PHASE_A_ADAPTER", None)
    monkeypatch.setenv(phase_a.FEATURE_FLAG_NAME, "1")
    assert scanner._recovery_phase_a_instance() is created
    assert calls[-1]["feature_flag_value"] == "1"


def test_scanner_runtime_binds_only_no_input_fail_closed_proof(
        monkeypatch):
    assert inspect.signature(
        scanner._recovery_phase_a_null_proof).parameters == {}
    public = {
        "schemaVersion": "public-v1",
        "recovery": {
            "mode": "legacy",
            "measurement": "shadow",
            "exactColdRecovery": "NOT_PROVEN",
            "hardRpoClaimPermitted": False,
        },
    }
    operational = {
        "schemaVersion": "operational-v1",
        "features": {
            "exactColdRecovery": "NOT_PROVEN",
            "hardRpoClaimPermitted": False,
        },
    }
    partial = {
        "recovery": {"exactColdRecovery": "PROVEN"},
    }
    dual = {
        "recovery": {},
        "features": {
            "exactColdRecovery": "PROVEN",
            "hardRpoClaimPermitted": True,
        },
    }
    public_keys = (set(public), set(public["recovery"]))
    operational_keys = (set(operational), set(operational["features"]))
    partial_keys = (set(partial), set(partial["recovery"]))
    dual_keys = (set(dual), set(dual["recovery"]), set(dual["features"]))
    monkeypatch.setattr(
        scanner.argus_recovery_phase_a_adapter,
        "null_recovery_proof_document",
        lambda: {"status": "PROVEN", "hardRpoClaimPermitted": True})
    assert scanner._recovery_phase_a_bind_null_proof(public) is public
    assert scanner._recovery_phase_a_bind_null_proof(operational) \
        is operational
    assert scanner._recovery_phase_a_bind_null_proof(partial) is partial
    assert scanner._recovery_phase_a_bind_null_proof(dual) is dual
    assert public["recovery"]["exactColdRecovery"] == "NOT_PROVEN"
    assert public["recovery"]["hardRpoClaimPermitted"] is False
    assert operational["features"]["exactColdRecovery"] == "NOT_PROVEN"
    assert operational["features"]["hardRpoClaimPermitted"] is False
    assert partial["recovery"] == {"exactColdRecovery": "NOT_PROVEN"}
    assert dual["recovery"] == {}
    assert dual["features"]["exactColdRecovery"] == "NOT_PROVEN"
    assert dual["features"]["hardRpoClaimPermitted"] is False
    assert (set(public), set(public["recovery"])) == public_keys
    assert (set(operational), set(operational["features"])) == \
        operational_keys
    assert (set(partial), set(partial["recovery"])) == partial_keys
    assert (set(dual), set(dual["recovery"]), set(dual["features"])) == \
        dual_keys
    assert "_trusted_evidence_from_verifier" not in inspect.getsource(scanner)


def test_scanner_checkpoint_handoff_uses_exact_mapping_then_retains_scalars(
        monkeypatch, scanner_recovery_state):
    sampling = phase_a.CheckpointSamplingDecision(
        "requested", True, "JP_SESSION_BOUNDARY",
        "measurement-generation", "sampling-token")
    accounting = phase_a.CheckpointAccountingObservation(
        "accounted", "measurement-generation", "sampling-token",
        321, (("missions", 123),), 9, 0)
    sealed = {"missions": {"secret-transient-sentinel": "never-retain"}}
    seen = []

    class Probe(_ScannerAdapterProbe):
        def checkpoint_sampling_decision(self, **kwargs):
            seen.append(("decision", kwargs))
            return sampling

        def account_checkpoint(self, checkpoint, decision):
            assert checkpoint is sealed
            assert decision is sampling
            seen.append(("account", checkpoint is sealed))
            return accounting

    probe = Probe()
    monkeypatch.setattr(scanner, "_RECOVERY_PHASE_A_ADAPTER", probe)
    scanner._MISSION_TICK_CONTEXT.update({
        "recoveryMeasurementJPPostSession": True,
        "recoveryMeasurementUSPostSession": False,
        "recoveryMeasurementOwnerAuthorized": True,
    })
    scanner._recovery_phase_a_prepare_checkpoint(
        sealed, seal_duration_micros=17,
        wal_bytes=101, wal_records=3, wal_high_water=8)
    pending = scanner._RECOVERY_PHASE_A_CHECKPOINT_LOCAL.pending
    assert pending == (sampling, accounting, 17, 101, 3, 8)
    assert all(value is not sealed for value in pending)
    assert "secret-transient-sentinel" not in repr(pending)
    assert "never-retain" not in repr(pending)
    assert seen[0][1]["jp_session_boundary"] is True
    assert seen[0][1]["owner_authorized"] is True
    assert seen[1] == ("account", True)
    assert scanner._MISSION_TICK_CONTEXT[
        "recoveryMeasurementJPPostSession"] is False
    assert scanner._MISSION_TICK_CONTEXT[
        "recoveryMeasurementUSPostSession"] is False
    assert scanner._MISSION_TICK_CONTEXT[
        "recoveryMeasurementOwnerAuthorized"] is False


def test_scanner_checkpoint_accounting_exception_releases_sampling_token(
        monkeypatch, scanner_recovery_state):
    sampling = phase_a.CheckpointSamplingDecision(
        "requested", True, "JP_SESSION_BOUNDARY",
        "measurement-generation", "sampling-token")

    class Probe(_ScannerAdapterProbe):
        def checkpoint_sampling_decision(self, **_kwargs):
            return sampling

        def account_checkpoint(self, _checkpoint, _decision):
            raise RuntimeError("optional accounting failure")

    probe = Probe()
    monkeypatch.setattr(scanner, "_RECOVERY_PHASE_A_ADAPTER", probe)
    scanner._recovery_phase_a_prepare_checkpoint(
        {"transient": "mapping"}, seal_duration_micros=1,
        wal_bytes=2, wal_records=3, wal_high_water=4)
    assert not hasattr(
        scanner._RECOVERY_PHASE_A_CHECKPOINT_LOCAL, "pending")
    assert probe.abandoned == [sampling]


@pytest.mark.parametrize("wal_compaction,expected", [
    (None, (101, 3, 8)),
    ({"bytes": 77, "remainingRecords": 2, "receiptSequence": 11},
     (77, 2, 11)),
])
def test_scanner_checkpoint_finalizer_uses_truthful_scalar_sources(
        monkeypatch, scanner_recovery_state, wal_compaction, expected):
    probe = _ScannerAdapterProbe()
    sampling = object()
    accounting = object()
    monkeypatch.setattr(scanner, "_RECOVERY_PHASE_A_ADAPTER", probe)
    monkeypatch.setattr(
        scanner, "_recovery_phase_a_peak_rss_bytes", lambda: 4096)
    monkeypatch.setitem(scanner._REMOTE_CYCLE, "readBackVerified", False)
    scanner._RECOVERY_PHASE_A_CHECKPOINT_LOCAL.pending = (
        sampling, accounting, 17, 101, 3, 8)
    checkpoint = {"verified": True, "snapshotBytes": 555}
    if wal_compaction is not None:
        checkpoint["walCompaction"] = wal_compaction
    scanner._recovery_phase_a_finalize_checkpoint(checkpoint)
    assert len(probe.checkpoints) == 1
    recorded = probe.checkpoints[0]
    assert recorded["sampling"] is sampling
    assert recorded["accounting"] is accounting
    assert recorded["checkpoint_serialized_bytes"] == 555
    assert recorded["serialization_duration_micros"] == 0
    assert recorded["write_seal_duration_micros"] == 17
    assert recorded["fsync_readback_duration_micros"] == 0
    assert recorded["peak_rss_bytes"] == 4096
    assert (recorded["local_wal_bytes"],
            recorded["local_wal_records"],
            recorded["local_wal_high_water"]) == expected
    assert recorded["legacy_remote_ack_sequence"] is None
    assert recorded["legacy_remote_ack_at"] is None


def test_scanner_checkpoint_unverified_abandons_without_diagnostics_write(
        monkeypatch, scanner_recovery_state):
    probe = _ScannerAdapterProbe()
    sampling = object()
    monkeypatch.setattr(scanner, "_RECOVERY_PHASE_A_ADAPTER", probe)
    scanner._RECOVERY_PHASE_A_CHECKPOINT_LOCAL.pending = (
        sampling, None, 1, 2, 3, 4)
    scanner._recovery_phase_a_finalize_checkpoint({"verified": False})
    assert probe.checkpoints == []
    assert probe.abandoned == [sampling]


def test_scanner_finalizer_clears_token_if_adapter_deactivates_before_commit(
        monkeypatch, tmp_path, scanner_recovery_state):
    adapter, _decision = _start_adapter(monkeypatch, tmp_path)
    sampling = adapter.checkpoint_sampling_decision(observed_at=START)
    assert sampling.token in adapter._pending_sampling
    accounting = adapter.account_checkpoint(CHECKPOINT, sampling)
    adapter._active = False
    monkeypatch.setattr(scanner, "_RECOVERY_PHASE_A_ADAPTER", adapter)
    scanner._RECOVERY_PHASE_A_CHECKPOINT_LOCAL.pending = (
        sampling, accounting, 1, 2, 3, 4)
    scanner._recovery_phase_a_finalize_checkpoint({
        "verified": True, "snapshotBytes": 5})
    assert sampling.token not in adapter._pending_sampling


def test_scanner_peak_rss_is_platform_normalized_peak_not_current(
        monkeypatch):
    usage = types.SimpleNamespace(ru_maxrss=123)
    monkeypatch.setattr(scanner.resource, "getrusage", lambda _who: usage)
    monkeypatch.setattr(scanner.sys, "platform", "darwin")
    assert scanner._recovery_phase_a_peak_rss_bytes() == 123
    monkeypatch.setattr(scanner.sys, "platform", "linux")
    assert scanner._recovery_phase_a_peak_rss_bytes() == 123 * 1024
    source = inspect.getsource(scanner._recovery_phase_a_peak_rss_bytes)
    assert "current_rss_bytes" not in source
    assert "ru_maxrss" in source


def test_non_tick_checkpoint_diagnostics_runs_after_authority_lock_release(
        monkeypatch, scanner_recovery_state):
    probe = _ScannerAdapterProbe()
    sampling = object()
    monkeypatch.setattr(scanner, "_RECOVERY_PHASE_A_ADAPTER", probe)
    monkeypatch.setattr(
        scanner, "_memory_operation_begin", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        scanner, "_memory_operation_complete", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        scanner, "_memory_attribution_path_capture",
        lambda *_args, **_kwargs: None)
    scanner._MISSION_TICK_CONTEXT.update({
        "active": False, "ownerThread": None})

    def authority():
        assert scanner._DURABLE_CHECKPOINT_LOCK._is_owned() is True
        scanner._RECOVERY_PHASE_A_CHECKPOINT_LOCAL.pending = (
            sampling, None, 3, 4, 5, 6)
        return {"verified": True, "snapshotBytes": 10}

    monkeypatch.setattr(scanner, "_osint_persist_locked", authority)
    result = scanner._osint_persist()
    assert result["verified"] is True
    assert len(probe.checkpoints) == 1


def test_mission_tick_checkpoint_diagnostics_runs_after_outer_lock_release(
        monkeypatch, scanner_recovery_state):
    probe = _ScannerAdapterProbe()
    sampling = object()
    events = []
    monkeypatch.setattr(scanner, "_RECOVERY_PHASE_A_ADAPTER", probe)
    monkeypatch.setattr(scanner, "_require_admin", lambda: (True, None, 200))
    monkeypatch.setattr(scanner, "_DURABILITY_PRODUCTION", False)
    monkeypatch.setitem(scanner._SHUTDOWN, "requested", False)
    monkeypatch.setattr(
        scanner, "_memory_attribution_scalar_snapshot", lambda: {})
    monkeypatch.setattr(
        scanner, "_memory_attribution_capture",
        lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        scanner, "_memory_attribution_record_id", lambda: None)
    monkeypatch.setattr(
        scanner, "_memory_attribution_finish_mission",
        lambda **_kwargs: None)
    monkeypatch.setattr(
        scanner.argus_tick_durability, "read_valid_wal",
        lambda _path: {"maximumSequence": 0, "bytes": 0,
                       "records": []})

    class Lease:
        job_id = "recovery-measurement-lock-test"
        metadata = {}

        def acquire(self):
            return True

        def release(self):
            events.append((
                "lease_release",
                scanner._DURABLE_CHECKPOINT_LOCK._is_owned()))

    monkeypatch.setattr(
        scanner.argus_tick_durability, "TickLease",
        lambda *_args, **_kwargs: Lease())

    def authority_impl():
        assert scanner._DURABLE_CHECKPOINT_LOCK._is_owned() is True
        assert scanner._mission_tick_context_active() is True
        scanner._RECOVERY_PHASE_A_CHECKPOINT_LOCAL.pending = (
            sampling, None, 3, 4, 5, 6)
        scanner._MISSION_TICK_CONTEXT["checkpoint"] = {
            "verified": True, "snapshotBytes": 10}
        return "tick-result"

    monkeypatch.setattr(
        scanner, "_api_argus_admin_missions_tick_impl", authority_impl)
    with scanner.app.test_request_context(
            "/api/argus/admin/missions/tick",
            method="POST", json={"triggerSource": "manual"}):
        assert scanner.api_argus_admin_missions_tick() == "tick-result"
    assert events == [("lease_release", True)]
    assert len(probe.checkpoints) == 1


def test_pre_authority_wal_and_journal_gates_never_call_adapter(
        monkeypatch, scanner_recovery_state):
    class NoPreAuthorityCalls(_ScannerAdapterProbe):
        def status(self):
            raise AssertionError("adapter called before authority")

    probe = NoPreAuthorityCalls()
    monkeypatch.setattr(scanner, "_RECOVERY_PHASE_A_ADAPTER", probe)
    monkeypatch.setenv(phase_a.FEATURE_FLAG_NAME, "1")
    monkeypatch.setenv("RENDER_GIT_COMMIT", BUILD_A)
    scanner._MISSION_TICK_CONTEXT.update({
        "walSequence": 12,
        "recoveryMeasurementWalBytes": 100,
        "recoveryMeasurementWalSequence": 12,
    })
    wal = scanner._recovery_phase_a_begin_wal_observation(
        "mission_transition")
    batch = scanner._recovery_phase_a_begin_wal_observation("batch_cursor")
    ignored = scanner._recovery_phase_a_begin_wal_observation(
        "journal_transition")
    journal = scanner._recovery_phase_a_begin_journal_observation()
    assert type(wal) is tuple and wal[:2] == (
        "core.mission_transition", 100)
    assert type(batch) is tuple and batch[:2] == ("core.batch_cursor", 100)
    assert ignored is None
    assert type(journal) is int
    begin_wal = inspect.getsource(
        scanner._recovery_phase_a_begin_wal_observation)
    begin_journal = inspect.getsource(
        scanner._recovery_phase_a_begin_journal_observation)
    assert ".status(" not in begin_wal + begin_journal
    assert "_recovery_phase_a_file_size" not in begin_wal


def test_wal_observation_freezes_append_scalars_before_heartbeat(
        monkeypatch, scanner_recovery_state):
    events = []

    class Probe(_ScannerAdapterProbe):
        def status(self):
            raise AssertionError("adapter called before WAL append")

        def record_mutation_after_authority(
                self, mutation_class_id, **kwargs):
            events.append("measurement")
            return super().record_mutation_after_authority(
                mutation_class_id, **kwargs)

    class Lease:
        def heartbeat(self):
            events.append("heartbeat")

    probe = Probe()
    monkeypatch.setattr(scanner, "_RECOVERY_PHASE_A_ADAPTER", probe)
    monkeypatch.setenv(phase_a.FEATURE_FLAG_NAME, "1")
    monkeypatch.setenv("RENDER_GIT_COMMIT", BUILD_A)
    scanner._MISSION_TICK_CONTEXT.update({
        "active": True,
        "ownerThread": scanner.threading.get_ident(),
        "jobId": "wal-observation-test",
        "walSequence": 4,
        "walEventCount": 0,
        "walAppendMs": 0,
        "lease": Lease(),
        "missionWindowId": "window-test",
        "recoveryMeasurementWalBytes": 100,
        "recoveryMeasurementWalSequence": 4,
    })
    ticks = iter((1_000_000_000, 1_005_000_000))
    monkeypatch.setattr(scanner.time, "monotonic_ns", lambda: next(ticks))
    legacy_ticks = iter((10.0, 10.005))

    def legacy_monotonic():
        marker = "legacy_start" if "legacy_start" not in events \
            else "legacy_complete"
        events.append(marker)
        return next(legacy_ticks)

    monkeypatch.setattr(scanner.time, "monotonic", legacy_monotonic)

    def append(*_args, **_kwargs):
        events.append("append_return")
        return {"sequence": 5}

    def file_size(_path):
        events.append("after_size")
        return 135

    monkeypatch.setattr(scanner.argus_tick_durability, "append_wal", append)
    monkeypatch.setattr(scanner, "_recovery_phase_a_file_size", file_size)
    result = scanner._append_tick_wal(
        "mission_transition", {"ignoredByMeasurement": "payload"})
    assert result == {"sequence": 5}
    assert events == [
        "legacy_start", "append_return", "legacy_complete",
        "after_size", "heartbeat", "measurement"]
    assert len(probe.mutations) == 1
    mutation_id, scalars = probe.mutations[0]
    assert mutation_id == "core.mission_transition"
    assert scalars["estimated_plaintext_bytes"] == 35
    assert scalars["latency_micros"] == 5000
    assert scalars["local_sequence"] == 5
    assert scanner._MISSION_TICK_CONTEXT["walAppendMs"] == 5.0
    assert scanner._MISSION_TICK_CONTEXT[
        "recoveryMeasurementWalBytes"] == 135


def test_wal_observation_survives_heartbeat_failure_without_masking_it(
        monkeypatch, scanner_recovery_state):
    probe = _ScannerAdapterProbe()
    monkeypatch.setattr(scanner, "_RECOVERY_PHASE_A_ADAPTER", probe)
    monkeypatch.setenv(phase_a.FEATURE_FLAG_NAME, "1")
    monkeypatch.setenv("RENDER_GIT_COMMIT", BUILD_A)

    class Lease:
        def heartbeat(self):
            raise RuntimeError("legacy heartbeat failure")

    scanner._MISSION_TICK_CONTEXT.update({
        "active": True,
        "ownerThread": scanner.threading.get_ident(),
        "jobId": "wal-heartbeat-test",
        "walSequence": 8,
        "walEventCount": 0,
        "walAppendMs": 0,
        "lease": Lease(),
        "missionWindowId": "window-test",
        "recoveryMeasurementWalBytes": 20,
        "recoveryMeasurementWalSequence": 8,
    })
    monkeypatch.setattr(
        scanner.argus_tick_durability, "append_wal",
        lambda *_args, **_kwargs: {"sequence": 9})
    monkeypatch.setattr(
        scanner, "_recovery_phase_a_file_size", lambda _path: 25)
    with pytest.raises(RuntimeError, match="legacy heartbeat failure"):
        scanner._append_tick_wal("batch_cursor", {"x": 1})
    assert len(probe.mutations) == 1
    mutation_id, scalars = probe.mutations[0]
    assert mutation_id == "core.batch_cursor"
    assert scalars["estimated_plaintext_bytes"] == 5
    assert scalars["local_sequence"] == 9


def test_wal_byte_delta_is_zero_after_uninstrumented_sequence_intervenes(
        monkeypatch, scanner_recovery_state):
    monkeypatch.setattr(
        scanner, "_RECOVERY_PHASE_A_ADAPTER", _ScannerAdapterProbe())
    monkeypatch.setenv(phase_a.FEATURE_FLAG_NAME, "1")
    monkeypatch.setenv("RENDER_GIT_COMMIT", BUILD_A)
    scanner._MISSION_TICK_CONTEXT.update({
        # Sequence 5 was an uninstrumented journal_transition; the last
        # measured byte cursor is therefore pinned to sequence 4.
        "walSequence": 5,
        "recoveryMeasurementWalBytes": 100,
        "recoveryMeasurementWalSequence": 4,
    })
    ticks = iter((2_000_000_000, 2_001_000_000))
    monkeypatch.setattr(scanner.time, "monotonic_ns", lambda: next(ticks))
    monkeypatch.setattr(
        scanner, "_recovery_phase_a_file_size", lambda _path: 140)
    begun = scanner._recovery_phase_a_begin_wal_observation(
        "mission_transition")
    assert begun[:2] == ("core.mission_transition", None)
    completed = scanner._recovery_phase_a_complete_wal_observation(begun, 6)
    assert completed == ("core.mission_transition", 0, 1000)
    assert scanner._MISSION_TICK_CONTEXT[
        "recoveryMeasurementWalBytes"] == 140
    assert scanner._MISSION_TICK_CONTEXT[
        "recoveryMeasurementWalSequence"] == 6


@pytest.mark.parametrize("tick,verified,expected_finish,raises", [
    (False, False, False, False),
    (False, True, True, False),
    (True, True, True, False),
    (True, True, False, True),
])
def test_journal_measurement_requires_its_full_authority_boundary(
        monkeypatch, scanner_recovery_state,
        tick, verified, expected_finish, raises):
    finished = []
    monkeypatch.setattr(
        scanner, "_mission_tick_context_active", lambda: tick)
    monkeypatch.setattr(
        scanner, "_recovery_phase_a_begin_journal_observation", lambda: 7)
    monkeypatch.setattr(
        scanner, "_recovery_phase_a_finish_journal_observation",
        lambda started, sequence: finished.append((started, sequence)))
    monkeypatch.setattr(scanner, "_next_ops_sequence", lambda _key: 19)
    monkeypatch.setattr(
        scanner.argus_state_journal, "event",
        lambda **_kwargs: {"idempotencyKey": "journal-test"})
    monkeypatch.setattr(
        scanner.argus_state_journal, "append",
        lambda _rows, _event: True)
    monkeypatch.setattr(
        scanner, "_osint_persist", lambda: {"verified": verified})

    def append_tick(*_args, **_kwargs):
        if raises:
            raise RuntimeError("authority failure")
        return {"verified": True}

    monkeypatch.setattr(scanner, "_append_tick_wal", append_tick)
    if raises:
        with pytest.raises(RuntimeError, match="authority failure"):
            scanner._journal("event", "mission", "m-1", {"x": 1})
    else:
        scanner._journal("event", "mission", "m-1", {"x": 1})
    assert finished == ([(7, 19)] if expected_finish else [])


def test_verified_receipt_uses_exact_zero_count_sequence_and_completion_time(
        monkeypatch, scanner_recovery_state):
    probe = _ScannerAdapterProbe()
    completed_at = dt.datetime.now(UTC)
    monkeypatch.setattr(scanner, "_RECOVERY_PHASE_A_ADAPTER", probe)
    scanner._recovery_phase_a_record_verified_receipt({
        "status": "verified",
        "coalescedReceiptCount": 0,
        "flushDurationMs": 1.25,
        "verifiedWalSequence": 23,
    }, completed_at)
    scanner._recovery_phase_a_record_verified_receipt({
        "status": "pending",
        "coalescedReceiptCount": 99,
    }, completed_at)
    assert len(probe.mutations) == 1
    mutation_id, scalars = probe.mutations[0]
    assert mutation_id == "durability.receipt_ack"
    assert scalars["record_count"] == 0
    assert scalars["latency_micros"] == 1250
    assert scalars["local_sequence"] == 23
    assert scalars["observed_at"] is completed_at

    source = inspect.getsource(scanner._persist_with_remote_receipt_drain)
    complete_index = source.index("_complete_remote_receipt_drain")
    observer_index = source.index(
        "_recovery_phase_a_record_verified_receipt")
    assert complete_index < observer_index
    observer_call = source[observer_index:]
    assert "datetime.now(pytz.utc)" in observer_call
    assert "now_iso)" not in observer_call.split("\n", 2)[1]


def test_startup_observation_is_once_only_and_never_failed_safe(
        monkeypatch, scanner_recovery_state):
    probe = _ScannerAdapterProbe()
    monkeypatch.setattr(scanner, "_RECOVERY_PHASE_A_ADAPTER", probe)
    scanner._RECOVERY_PHASE_A_STARTUP_RECORDED = False
    scanner._STARTUP.update({
        "state": "ready_degraded",
        "restoreDurationMs": 7,
        "restoreCompletedAt": START.isoformat(),
    })
    monkeypatch.setitem(scanner._MISSION_BATCH_STATE, "walAppliedSequence", 4)
    scanner._recovery_phase_a_record_startup_if_ready()
    scanner._recovery_phase_a_record_startup_if_ready()
    assert len(probe.mutations) == 1
    mutation_id, scalars = probe.mutations[0]
    assert mutation_id == "startup.restore_transition"
    assert scalars["latency_micros"] == 7000
    assert scalars["local_sequence"] == 4

    scanner._RECOVERY_PHASE_A_STARTUP_RECORDED = False
    scanner._STARTUP["state"] = "failed_safe"
    scanner._recovery_phase_a_record_startup_if_ready()
    assert len(probe.mutations) == 1
    source = inspect.getsource(scanner._startup_bootstrap)
    assert source.rfind("_recovery_phase_a_record_startup_if_ready()") > \
        source.rfind('_STARTUP["state"] = "ready"')


def test_post_session_sampling_marks_only_normal_success_not_warmup(
        scanner_recovery_state):
    scanner._MISSION_TICK_CONTEXT.update({
        "recoveryMeasurementJPPostSession": False,
        "recoveryMeasurementUSPostSession": False,
    })
    scanner._recovery_phase_a_mark_post_session({
        "missionType": "post_session_snapshot", "market": "JP"})
    assert scanner._MISSION_TICK_CONTEXT[
        "recoveryMeasurementJPPostSession"] is True
    scanner._recovery_phase_a_mark_post_session({
        "missionType": "post_session_snapshot", "market": "US"})
    assert scanner._MISSION_TICK_CONTEXT[
        "recoveryMeasurementUSPostSession"] is True
    scanner._recovery_phase_a_mark_post_session({
        "missionType": "pre_session_forecast", "market": "JP"})

    source = inspect.getsource(scanner._api_argus_admin_missions_tick_impl)
    assert source.count("_recovery_phase_a_mark_post_session(m)") == 1
    warmup_index = source.index('m["checkpoint"] = "warmup_queued"')
    warmup_continue = source.index("continue", warmup_index)
    assert "_recovery_phase_a_mark_post_session" not in \
        source[warmup_index:warmup_continue]
    mark_index = source.index("_recovery_phase_a_mark_post_session(m)")
    successful_persist_index = source.rfind(
        "_persist_mission_transition", 0, mark_index)
    assert warmup_continue < successful_persist_index < mark_index


def test_owner_sampling_requires_admin_diagnostic_and_exact_build(
        monkeypatch):
    monkeypatch.setenv("RENDER_GIT_COMMIT", BUILD_A)
    request_body = {"diagnostic": True, "expectedBuildSha": BUILD_A}
    assert scanner._recovery_phase_a_owner_sampling_authorized(
        request_body, True) is True
    assert scanner._recovery_phase_a_owner_sampling_authorized(
        request_body, False) is False
    assert scanner._recovery_phase_a_owner_sampling_authorized(
        {**request_body, "diagnostic": False}, True) is False
    assert scanner._recovery_phase_a_owner_sampling_authorized(
        {**request_body, "expectedBuildSha": BUILD_A[:7]}, True) is False
    assert scanner._recovery_phase_a_owner_sampling_authorized(
        {**request_body, "expectedBuildSha": BUILD_B}, True) is False


def test_scanner_measurement_helpers_fail_open_after_authority(
        monkeypatch, scanner_recovery_state):
    probe = _ScannerAdapterProbe(
        raise_mutation=True, raise_checkpoint=True)
    monkeypatch.setattr(scanner, "_RECOVERY_PHASE_A_ADAPTER", probe)
    scanner._recovery_phase_a_record(
        "core.batch_cursor", estimated_plaintext_bytes=1,
        record_count=1, latency_micros=1,
        observed_at=START, local_sequence=1)
    sampling = object()
    scanner._RECOVERY_PHASE_A_CHECKPOINT_LOCAL.pending = (
        sampling, None, 1, 2, 3, 4)
    scanner._recovery_phase_a_finalize_checkpoint({
        "verified": True, "snapshotBytes": 5})
    assert len(probe.mutations) == 1
    assert len(probe.checkpoints) == 1
    assert probe.abandoned == [sampling]
