"""Strict schema, aggregation, retention, and accounting tests for PR C."""
from __future__ import annotations

import copy
import datetime as dt
import hashlib
import inspect
import json
import os
import subprocess
import sys
import time

import pytest

import argus_recovery_measurement as measurement
import argus_recovery_registry as registry


UTC = dt.timezone.utc
START = dt.datetime(2026, 8, 15, 0, 0, 0, tzinfo=UTC)
BUILD_SHA = "a" * 40
COVERAGE_SHA = "b" * 64


def _empty():
    return measurement.new_artifact(
        measurement_generation_id="measurement-generation-0001",
        producer_build_sha=BUILD_SHA,
        instrumentation_coverage_sha256=COVERAGE_SHA,
        created_at=START)


def _populated():
    artifact = _empty()
    accumulator = measurement.MeasurementAccumulator(artifact)
    assert accumulator.record_mutation(
        "core.batch_cursor", estimated_plaintext_bytes=42,
        record_count=2, latency_micros=750, success=True,
        coverage_classification="OBSERVED_UNDURABLE", observed_at=START,
        local_sequence=7) == "recorded"
    assert accumulator.record_checkpoint(
        "checkpoint-sample-0001", observed_at=START, success=True,
        detailed=True, detail_reason="JP_SESSION_BOUNDARY",
        checkpoint_serialized_bytes=10_000,
        section_serialized_bytes={"marketLedger": 2000, "missions": 500},
        serialization_duration_micros=1000,
        section_accounting_duration_micros=1200,
        write_seal_duration_micros=1400,
        fsync_readback_duration_micros=1600,
        peak_rss_bytes=20_000_000, local_wal_bytes=123,
        local_wal_records=4, local_wal_high_water=7,
        legacy_remote_ack_sequence=6,
        legacy_remote_ack_at=START) == "recorded"
    assert measurement.validate_artifact(artifact).valid
    return artifact


def test_schema_identity_budget_and_non_authoritative_contract_are_explicit():
    artifact = _empty()
    assert artifact["schemaVersion"] == \
        "argus-recovery-measurement-shadow-v1"
    assert artifact["measurementSchemaSha256"] == \
        measurement.MEASUREMENT_SCHEMA_SHA256
    assert artifact["registryPolicySha256"] == \
        registry.registry_policy_sha256()
    assert artifact["authoritative"] is False
    assert artifact["mode"] == "SHADOW"
    assert artifact["coverageStatus"] == "INCOMPLETE"
    assert artifact["proofStatus"] == "NOT_PROVEN"
    assert artifact["acceptanceClockStarted"] is False
    assert measurement.MAX_PERSISTED_BYTES == 12 * 1024 * 1024
    assert measurement.RESERVE_BUDGET == 448 * 1024
    assert measurement.MAX_BUCKETS == 8_928
    assert measurement.MAX_RECENT_MUTATIONS == 256
    assert measurement.MAX_CHECKPOINT_SAMPLES == 2_048
    assert measurement.MAX_DAILY_DISTRIBUTIONS == 32
    assert measurement.MAX_MUTATION_CLASSES == len(registry.mutations()) == 27
    assert measurement.MAX_CHECKPOINT_SECTION_KEYS == \
        len(registry.registered_checkpoint_keys()) == 48


def test_recording_api_is_metadata_only_and_never_accepts_payload_or_error():
    mutation_parameters = inspect.signature(
        measurement.MeasurementAccumulator.record_mutation).parameters
    checkpoint_parameters = inspect.signature(
        measurement.MeasurementAccumulator.record_checkpoint).parameters
    forbidden = {
        "payload", "content", "owner_content", "holdings", "url",
        "prompt", "model_output", "source_text", "recovery_plaintext",
        "exception", "error", "error_message",
    }
    assert not forbidden & set(mutation_parameters)
    assert not forbidden & set(checkpoint_parameters)
    secret = "OWNER-HOLDING-URL-PROMPT-MODEL-OUTPUT-SECRET"
    artifact = _empty()
    accumulator = measurement.MeasurementAccumulator(artifact)
    assert accumulator.record_mutation(
        "ai.result_and_cost", estimated_plaintext_bytes=len(secret),
        record_count=1, latency_micros=1, success=False,
        coverage_classification="UNKNOWN", observed_at=START) == "recorded"
    assert secret not in measurement.canonical_artifact_bytes(
        artifact).decode("utf-8")


@pytest.mark.parametrize("case,mutate", [
    ("numeric_string", lambda value: value["recentMutations"][0].__setitem__(
        "recordCount", "2")),
    ("boolean_string", lambda value: value["recentMutations"][0].__setitem__(
        "success", "true")),
    ("bool_as_int", lambda value: value["recentMutations"][0].__setitem__(
        "latencyMicros", True)),
    ("nan", lambda value: value["recentMutations"][0].__setitem__(
        "latencyMicros", float("nan"))),
    ("infinity", lambda value: value["checkpointSamples"][0].__setitem__(
        "serializationDurationMicros", float("inf"))),
    ("negative", lambda value: value["checkpointSamples"][0].__setitem__(
        "localWalBytes", -1)),
    ("absurd", lambda value: value["aggregateCounters"].__setitem__(
        "measurementErrorCount", measurement.MAX_SAFE_INTEGER + 1)),
    ("nested_unknown", lambda value: value["checkpointSamples"][0].__setitem__(
        "privateFutureField", "secret")),
    ("missing", lambda value: value["coverage"].pop(
        "expectedMutationClassCount")),
    ("wrong_container", lambda value: value.__setitem__(
        "intervalBuckets", {})),
    ("malformed_timestamp", lambda value: value.__setitem__(
        "updatedAt", "2026-08-15")),
    ("coverage_relationship", lambda value: value["coverage"].__setitem__(
        "oldestObservedUndurableMutationAt", "2026-08-16T00:00:00Z")),
    ("aggregate_relationship", lambda value: value[
        "aggregateCounters"].__setitem__("retainedMutationCount", 99)),
    ("checkpoint_sections", lambda value: value["checkpointSamples"][0][
        "sectionSerializedBytes"].__setitem__("marketLedger", 20_000)),
    ("false_remote_authority", lambda value: value["checkpointSamples"][0].
        __setitem__("legacyRemoteAckIsExactWalDurability", True)),
    ("sequence_scalar", lambda value: value["recentMutations"][0].__setitem__(
        "localSequence", "7")),
    ("target_mismatch", lambda value: value["recentMutations"][0].__setitem__(
        "targetStateIds", [])),
    ("histogram_count", lambda value: value["intervalBuckets"][0][
        "plaintextBytesHistogram"].__setitem__(0, 9)),
    ("excessive_depth", lambda value: value["invalidation"].__setitem__(
        "at", [[[[[[[[[[[[[["too-deep"]]]]]]]]]]]]]])),
])
def test_closed_schema_rejects_hostile_values(case, mutate):
    artifact = _populated()
    mutate(artifact)
    result = measurement.validate_artifact(artifact)
    assert result == measurement.ValidationResult(False, "invalid_artifact"), case


def test_closed_schema_rejects_oversized_collections_and_unknown_top_level():
    artifact = _populated()
    artifact["recentMutations"] = artifact["recentMutations"] * 257
    assert not measurement.validate_artifact(artifact).valid
    artifact = _populated()
    artifact["ownerPayload"] = "forbidden"
    assert not measurement.validate_artifact(artifact).valid


def test_policy_digest_mismatch_invalidates_artifact_without_reinterpretation(
        monkeypatch):
    artifact = _populated()
    old_digest = artifact["registryPolicySha256"]
    assert measurement.validate_artifact(artifact).valid
    monkeypatch.setattr(
        registry, "registry_policy_sha256", lambda: "f" * 64)
    result = measurement.validate_artifact(artifact)
    assert result == measurement.ValidationResult(
        False, "registry_policy_mismatch")
    assert artifact["registryPolicySha256"] == old_digest
    with pytest.raises(ValueError, match="registry_policy_mismatch"):
        measurement.MeasurementAccumulator(artifact)


def test_live_policy_drift_blocks_every_mutating_boundary_until_new_generation(
        monkeypatch):
    policy_state = {"sha256": registry.registry_policy_sha256()}
    monkeypatch.setattr(
        registry, "registry_policy_sha256",
        lambda: policy_state["sha256"])
    artifact = _empty()
    accumulator = measurement.MeasurementAccumulator(artifact)
    assert accumulator.record_mutation(
        "core.batch_cursor", estimated_plaintext_bytes=1, record_count=1,
        latency_micros=1, success=True,
        coverage_classification="UNKNOWN", observed_at=START) == "recorded"
    before_drift = measurement._canonical_bytes_unchecked(artifact)
    policy_b = "f" * 64
    policy_state["sha256"] = policy_b

    assert accumulator.record_mutation(
        "core.batch_cursor", estimated_plaintext_bytes=2, record_count=1,
        latency_micros=2, success=True,
        coverage_classification="UNKNOWN",
        observed_at=START + dt.timedelta(minutes=5)) == \
        "registry_policy_mismatch"
    assert accumulator.record_checkpoint(
        "checkpoint-after-drift", observed_at=START, success=True,
        detailed=False, detail_reason="NONE",
        checkpoint_serialized_bytes=10,
        section_serialized_bytes={},
        serialization_duration_micros=1,
        section_accounting_duration_micros=1,
        write_seal_duration_micros=1,
        fsync_readback_duration_micros=1,
        peak_rss_bytes=None, local_wal_bytes=0,
        local_wal_records=0, local_wal_high_water=0,
        legacy_remote_ack_sequence=None,
        legacy_remote_ack_at=None) == "registry_policy_mismatch"
    assert measurement._canonical_bytes_unchecked(artifact) == before_drift

    generation_b = measurement.new_artifact(
        measurement_generation_id="measurement-generation-policy-b",
        producer_build_sha=BUILD_SHA,
        instrumentation_coverage_sha256=COVERAGE_SHA,
        created_at=START)
    assert generation_b["registryPolicySha256"] == policy_b
    replacement = measurement.MeasurementAccumulator(generation_b)
    assert replacement.record_mutation(
        "core.batch_cursor", estimated_plaintext_bytes=2, record_count=1,
        latency_micros=2, success=True,
        coverage_classification="UNKNOWN", observed_at=START) == "recorded"
    assert measurement.validate_artifact(generation_b).valid


def test_recording_rejects_before_mutation_and_handles_clock_jump():
    artifact = _empty()
    accumulator = measurement.MeasurementAccumulator(artifact)
    before = measurement._canonical_bytes_unchecked(artifact)
    assert accumulator.record_mutation(
        "core.batch_cursor", estimated_plaintext_bytes=-1, record_count=1,
        latency_micros=1, success=True, coverage_classification="UNKNOWN",
        observed_at=START) == "invalid_observation"
    assert measurement._canonical_bytes_unchecked(artifact) == before
    assert accumulator.record_mutation(
        "core.batch_cursor", estimated_plaintext_bytes=1, record_count=1,
        latency_micros=1, success=True, coverage_classification="UNKNOWN",
        observed_at=START - dt.timedelta(seconds=1)) == "invalid_observation"
    assert measurement._canonical_bytes_unchecked(artifact) == before
    jump = START + dt.timedelta(days=90)
    assert accumulator.record_mutation(
        "core.batch_cursor", estimated_plaintext_bytes=1, record_count=1,
        latency_micros=1, success=True,
        coverage_classification="OBSERVED_UNDURABLE", observed_at=jump) == \
        "recorded"
    plan = measurement.plan_retention(artifact, now=jump)
    assert plan.status == "ok"
    assert plan.evidence.collection_passes == 4
    assert plan.evidence.final_document_encodes == 1


def test_aggregation_intervals_histograms_and_plaintext_semantics():
    artifact = _empty()
    accumulator = measurement.MeasurementAccumulator(artifact)
    for offset, size, success in ((0, 10, True), (6, 100, False),
                                  (17, 1_000, True)):
        assert accumulator.record_mutation(
            "core.batch_cursor", estimated_plaintext_bytes=size,
            record_count=1, latency_micros=size * 10, success=success,
            coverage_classification="UNKNOWN",
            observed_at=START + dt.timedelta(minutes=offset)) == "recorded"
    assert [len(measurement.interval_rollups(artifact, minutes))
            for minutes in (5, 15, 30)] == [3, 2, 1]
    thirty = measurement.interval_rollups(artifact, 30)[0]
    assert thirty["mutationCount"] == 3
    assert thirty["estimatedPlaintextBytes"] == 1_110
    assert thirty["candidateWalPlaintextBytesEstimate"] == \
        1_110 + 3 * measurement.FUTURE_WAL_RECORD_FRAMING_ESTIMATE_BYTES
    assert thirty["successCount"] == 2
    assert thirty["failureCount"] == 1
    assert thirty["maxSingleMutationPlaintextBytesEstimate"] == 1_000
    assert thirty["plaintextBytesApproxP95UpperBound"] >= 1_000
    assert thirty["walSizeSemantics"] == \
        "plaintext_candidate_estimate_not_encrypted_wal"


def test_checkpoint_sampling_policy_is_pure_bounded_and_not_a_cadence_choice():
    owner = measurement.detailed_sampling_policy(
        measurement.DetailedSamplingContext(owner_authorized=True,
                                            detailed_session_samples_today=2))
    assert (owner.requested, owner.reason) == (True, "OWNER_AUTHORIZED")
    changed = measurement.detailed_sampling_policy(
        measurement.DetailedSamplingContext(
            producer_build_changed=True, detailed_session_samples_today=2))
    assert changed.reason == "ACCOUNTING_SCHEMA_OR_BUILD_CHANGE"
    jp = measurement.detailed_sampling_policy(
        measurement.DetailedSamplingContext(jp_session_boundary=True))
    us = measurement.detailed_sampling_policy(
        measurement.DetailedSamplingContext(
            us_session_boundary=True, detailed_session_samples_today=1))
    capped = measurement.detailed_sampling_policy(
        measurement.DetailedSamplingContext(
            us_session_boundary=True, detailed_session_samples_today=2))
    assert jp.reason == "JP_SESSION_BOUNDARY"
    assert us.reason == "US_SESSION_BOUNDARY"
    assert capped == measurement.DetailedSamplingDecision(False, "NONE", 2)


def test_streaming_size_accounting_is_exact_bounded_and_source_unchanged():
    checkpoint = {
        "schemaVersion": "argus-durable-v3",
        "marketLedger": [{"id": index, "value": f"unique-{index}-日本語"}
                         for index in range(100)],
        "missions": {"open": [1, 2, 3], "closed": []},
        "termOverlay": {"private": "counted-not-returned"},
    }
    before = copy.deepcopy(checkpoint)
    canonical = json.dumps(
        checkpoint, ensure_ascii=False, allow_nan=False, sort_keys=True,
        separators=(",", ":")).encode("utf-8")
    chunks = list(measurement.iter_canonical_json_chunks(
        checkpoint, chunk_bytes=97))
    assert b"".join(chunks) == canonical
    assert max(map(len, chunks)) <= 97
    accounting = measurement.streaming_checkpoint_accounting(checkpoint)
    assert accounting.total_serialized_bytes == len(canonical)
    assert accounting.registered_section_bytes["marketLedger"] == len(
        json.dumps(checkpoint["marketLedger"], ensure_ascii=False,
                   sort_keys=True, separators=(",", ":")).encode("utf-8"))
    assert accounting.full_size_buffers == 0
    assert accounting.output_chunk_limit_bytes <= 1024 * 1024
    assert checkpoint == before


def test_streaming_rejects_nonfinite_cycle_and_giant_scalar():
    with pytest.raises(ValueError, match="stream_value_invalid"):
        measurement.streaming_canonical_size({"bad": float("nan")})
    cycle = []
    cycle.append(cycle)
    with pytest.raises(ValueError, match="stream_value_invalid"):
        measurement.streaming_canonical_size(cycle)
    with pytest.raises(ValueError, match="stream_scalar_too_large"):
        measurement.streaming_canonical_size(
            "x" * (measurement.MAX_STREAM_CHUNK_BYTES + 1))


def test_retention_max_state_is_bulk_bounded_deterministic_and_linear_passed():
    artifact = _empty()
    accumulator = measurement.MeasurementAccumulator(artifact)
    for index in range(measurement.MAX_BUCKETS + 50):
        observed = START + dt.timedelta(minutes=5 * index)
        assert accumulator.record_mutation(
            "core.batch_cursor", estimated_plaintext_bytes=100 + index % 100,
            record_count=1, latency_micros=200 + index % 50, success=True,
            coverage_classification="UNKNOWN", observed_at=observed,
            local_sequence=index) == "recorded"
    assert len(artifact["intervalBuckets"]) == measurement.MAX_BUCKETS
    assert len(artifact["recentMutations"]) == \
        measurement.MAX_RECENT_MUTATIONS
    assert len(artifact["dailyDistributions"]) <= \
        measurement.MAX_DAILY_DISTRIBUTIONS
    now = START + dt.timedelta(minutes=5 * (measurement.MAX_BUCKETS + 49))
    first = measurement.plan_retention(artifact, now=now)
    second = measurement.plan_retention(artifact, now=now)
    assert first.status == second.status == "ok"
    assert first.canonical_bytes == second.canonical_bytes
    assert first.evidence.collection_passes == 4
    assert first.evidence.row_encodes <= first.evidence.input_rows
    assert first.evidence.final_document_encodes == 1
    assert first.evidence.final_bytes <= measurement.MAX_PERSISTED_BYTES
    assert first.evidence.retained_rows <= 12_096
    assert measurement.validate_artifact(first.artifact).valid


def test_tie_timestamps_have_deterministic_oldest_removal():
    artifact = _empty()
    accumulator = measurement.MeasurementAccumulator(artifact)
    for index in range(measurement.MAX_RECENT_MUTATIONS + 3):
        assert accumulator.record_mutation(
            "core.batch_cursor", estimated_plaintext_bytes=index,
            record_count=1, latency_micros=index, success=True,
            coverage_classification="UNKNOWN", observed_at=START,
            local_sequence=index) == "recorded"
    sequences = [row["localSequence"] for row in artifact["recentMutations"]]
    assert sequences == list(range(3, measurement.MAX_RECENT_MUTATIONS + 3))


def test_canonical_artifact_is_cross_process_hash_seed_deterministic():
    artifact = _populated()
    encoded = measurement.canonical_artifact_bytes(artifact)
    expected = hashlib.sha256(encoded).hexdigest()
    program = """
import datetime as dt, hashlib
import argus_recovery_measurement as m
a=m.new_artifact(measurement_generation_id='measurement-generation-0001',producer_build_sha='a'*40,instrumentation_coverage_sha256='b'*64,created_at=dt.datetime(2026,8,15,tzinfo=dt.timezone.utc))
x=m.MeasurementAccumulator(a)
x.record_mutation('core.batch_cursor',estimated_plaintext_bytes=42,record_count=2,latency_micros=750,success=True,coverage_classification='OBSERVED_UNDURABLE',observed_at=dt.datetime(2026,8,15,tzinfo=dt.timezone.utc),local_sequence=7)
x.record_checkpoint('checkpoint-sample-0001',observed_at=dt.datetime(2026,8,15,tzinfo=dt.timezone.utc),success=True,detailed=True,detail_reason='JP_SESSION_BOUNDARY',checkpoint_serialized_bytes=10000,section_serialized_bytes={'marketLedger':2000,'missions':500},serialization_duration_micros=1000,section_accounting_duration_micros=1200,write_seal_duration_micros=1400,fsync_readback_duration_micros=1600,peak_rss_bytes=20000000,local_wal_bytes=123,local_wal_records=4,local_wal_high_water=7,legacy_remote_ack_sequence=6,legacy_remote_ack_at=dt.datetime(2026,8,15,tzinfo=dt.timezone.utc))
print(hashlib.sha256(m.canonical_artifact_bytes(a)).hexdigest())
"""
    for seed in ("0", "1", "42", "random"):
        environment = os.environ.copy()
        environment["PYTHONHASHSEED"] = seed
        completed = subprocess.run(
            [sys.executable, "-c", program], cwd=os.getcwd(),
            env=environment, check=True, capture_output=True, text=True)
        assert completed.stdout.strip() == expected


def test_max_state_hot_path_operation_is_bounded_without_full_serialization(
        monkeypatch):
    artifact = _empty()
    accumulator = measurement.MeasurementAccumulator(artifact)
    for index in range(measurement.MAX_BUCKETS):
        assert accumulator.record_mutation(
            "core.batch_cursor", estimated_plaintext_bytes=1,
            record_count=1, latency_micros=1, success=True,
            coverage_classification="UNKNOWN",
            observed_at=START + dt.timedelta(minutes=index * 5),
            local_sequence=index) == "recorded"
    monkeypatch.setattr(
        measurement, "_canonical_bytes_unchecked",
        lambda _value: pytest.fail("hot path serialized full document"))
    samples = []
    for index in range(30):
        started = time.perf_counter()
        assert accumulator.record_mutation(
            "core.batch_cursor", estimated_plaintext_bytes=2,
            record_count=1, latency_micros=2, success=True,
            coverage_classification="UNKNOWN",
            observed_at=START + dt.timedelta(
                minutes=(measurement.MAX_BUCKETS - 1) * 5),
            local_sequence=measurement.MAX_BUCKETS + index) == "recorded"
        samples.append((time.perf_counter() - started) * 1000)
    # Wall-clock is evidence only; the serialization tripwire is authoritative.
    assert len(samples) == 30
