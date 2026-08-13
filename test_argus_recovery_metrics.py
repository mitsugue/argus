"""Privacy, bounding, interval and recovery-claim tests for Phase A metrics."""

import datetime as dt
import inspect
import json
import time

import pytest

import argus_recovery_metrics as metrics


UTC = dt.timezone.utc


class Clock:
    def __init__(self, value):
        self.value = value

    def __call__(self):
        return self.value


def test_measurement_api_has_no_payload_and_private_content_never_persists(tmp_path):
    signature = inspect.signature(metrics.RecoveryMeasurementStore.record_mutation)
    assert "payload" not in signature.parameters
    sentinel = "OWNER-HOLDING-SECRET-URL-PROMPT-MODEL-OUTPUT"
    path = tmp_path / "measurement.json"
    store = metrics.RecoveryMeasurementStore(str(path))
    byte_count = metrics.serialized_size_estimate({"private": sentinel})
    store.record_mutation(
        "ai.result_and_cost", plaintext_bytes_estimate=byte_count,
        latency_ms=1.25)
    assert store.maybe_persist(force=True)
    encoded = path.read_text(encoding="utf-8")
    assert sentinel not in encoded
    loaded = json.loads(encoded)
    recent = loaded["recentMutations"][-1]
    assert recent["targetStateIds"] == []
    assert recent["redactedTargetCount"] == 3
    assert "payload" not in encoded.lower()
    public = store.summary()["mutationDistributions"]
    assert "ai.result_and_cost" not in public
    assert public["private.redacted"]["mutationCount"] == 1


def test_size_interval_and_candidate_plaintext_aggregation_across_clock_edges():
    clock = Clock(dt.datetime(2026, 8, 13, 11, 59, 59, tzinfo=UTC))
    store = metrics.RecoveryMeasurementStore(None, clock=clock)
    store.record_mutation(
        "market.ledger_update", plaintext_bytes_estimate=100,
        transition_count=2, record_count=2, observed_at=clock.value)
    clock.value = dt.datetime(2026, 8, 13, 12, 0, 1, tzinfo=UTC)
    store.record_mutation(
        "market.ledger_update", plaintext_bytes_estimate=300,
        observed_at=clock.value)
    summary = store.summary(legacy_remote_ack_sequence=7,
                            local_wal_high_water=10)
    five = summary["intervalStatistics"]["5"]
    fifteen = summary["intervalStatistics"]["15"]
    thirty = summary["intervalStatistics"]["30"]
    assert five["intervalCount"] == 2
    assert five["mutationCount"] == {"p50": 1, "p95": 1, "p99": 1,
                                      "max": 1}
    assert fifteen["intervalCount"] == 2  # 11:45 and 12:00 boundaries
    assert thirty["intervalCount"] == 2
    assert summary["legacySequenceLag"] == 3
    assert summary["candidateWalEstimatesArePlaintextOnly"] is True
    assert summary["encryptedWalBytesClaimed"] is False
    distribution = summary["mutationDistributions"]["market.ledger_update"]
    assert distribution["mutationCount"] == 2
    assert distribution["plaintextBytesEstimate"] == 400
    assert distribution["maxSingleMutationPlaintextBytesEstimate"] == 300


def test_recent_samples_and_time_retention_are_bounded():
    clock = Clock(dt.datetime(2026, 8, 13, 0, 0, tzinfo=UTC))
    store = metrics.RecoveryMeasurementStore(None, clock=clock)
    old = clock.value - dt.timedelta(days=metrics.RETENTION_DAYS + 1)
    store.record_mutation("core.batch_cursor", plaintext_bytes_estimate=1,
                          observed_at=old)
    for number in range(metrics.MAX_RECENT_MUTATIONS + 25):
        clock.value += dt.timedelta(seconds=1)
        store.record_mutation(
            "core.batch_cursor", plaintext_bytes_estimate=number,
            observed_at=clock.value)
    with store._lock:  # bounded internal artifact is part of the storage contract
        store._ensure_loaded()
        assert len(store._document["recentMutations"]) == \
            metrics.MAX_RECENT_MUTATIONS
        assert all(row["bucketStart"] >= "2026-08-13"
                   for row in store._document["buckets"])
    assert store.summary()["mutationDistributions"]["core.batch_cursor"][
        "mutationCount"] == metrics.MAX_RECENT_MUTATIONS + 25


def test_five_minute_bucket_count_has_a_hard_bound(monkeypatch):
    monkeypatch.setattr(metrics, "MAX_BUCKETS", 4)
    clock = Clock(dt.datetime(2026, 8, 13, 0, 0, tzinfo=UTC))
    store = metrics.RecoveryMeasurementStore(None, clock=clock)
    for _ in range(7):
        store.record_mutation(
            "core.batch_cursor", plaintext_bytes_estimate=1,
            observed_at=clock.value)
        clock.value += dt.timedelta(minutes=5)
    with store._lock:
        store._ensure_loaded()
        assert len(store._document["buckets"]) == 4


@pytest.mark.parametrize("contents", [
    "{partial", "[]", '{"schemaVersion":"wrong"}',
    json.dumps({"schemaVersion": metrics.SCHEMA, "authoritative": False,
                "coverage": "SHADOW_INCOMPLETE", "buckets": "not-a-list"}),
])
def test_malformed_or_partial_metrics_file_is_ignored_without_startup_failure(
        tmp_path, contents):
    path = tmp_path / "measurement.json"
    path.write_text(contents, encoding="utf-8")
    store = metrics.RecoveryMeasurementStore(str(path))
    summary = store.summary()
    assert summary["status"] == "SHADOW"
    assert summary["coverage"] == "INCOMPLETE"
    assert summary["loadStatus"].startswith("invalid")
    assert summary["hardRpoClaimPermitted"] is False


def test_atomic_restart_readback_and_file_mode(tmp_path):
    path = tmp_path / "measurement.json"
    store = metrics.RecoveryMeasurementStore(str(path))
    store.record_mutation("core.batch_cursor", plaintext_bytes_estimate=42)
    assert store.maybe_persist(force=True)
    assert path.stat().st_size <= metrics.MAX_PERSISTED_BYTES
    assert path.stat().st_mode & 0o777 == 0o600
    restarted = metrics.RecoveryMeasurementStore(str(path))
    summary = restarted.summary()
    assert summary["loadStatus"] == "loaded"
    assert summary["mutationDistributions"]["core.batch_cursor"][
        "mutationCount"] == 1


def test_hostile_content_bearing_field_is_rejected_on_readback(tmp_path):
    path = tmp_path / "measurement.json"
    store = metrics.RecoveryMeasurementStore(str(path))
    store.record_mutation("core.batch_cursor", plaintext_bytes_estimate=7)
    assert store.maybe_persist(force=True)
    document = json.loads(path.read_text(encoding="utf-8"))
    document["recentMutations"][0]["prompt"] = "must-never-load"
    path.write_text(json.dumps(document), encoding="utf-8")
    restarted = metrics.RecoveryMeasurementStore(str(path))
    assert restarted.summary()["loadStatus"] == "invalid_schema"


def test_checkpoint_accounting_large_sections_and_legacy_prediction_count(tmp_path):
    blob = {
        "marketLedger": {"observations": [{"id": "a"}]},
        "verifiedViewSnapshots": {"current": {"JP": {"id": "v"}}},
        "assetChartReports": {"records": {}},
        "chartIntelligence": {"snapshots": []},
        "marketReplay": {"contexts": {}},
        "todayIntelligence": {"snapshots": []},
        "missions": [],
    }
    sizes = metrics.checkpoint_section_sizes(blob)
    assert set(metrics.LARGE_SECTION_KEYS) <= set(sizes)
    assert sizes["marketLedger"] == metrics.serialized_size_estimate(
        blob["marketLedger"])
    predictions = tmp_path / "predictions.jsonl"
    predictions.write_bytes(b'{"private":"one"}\n\n{"private":"two"}\n')
    measured = metrics.measure_jsonl_metadata(str(predictions))
    assert measured["recordCount"] == 2
    assert measured["bytes"] == predictions.stat().st_size
    assert "private" not in measured

    store = metrics.RecoveryMeasurementStore(str(tmp_path / "metrics.json"))
    store.record_checkpoint(
        checkpoint_bytes=1234, section_sizes=sizes,
        source_assembly_ms=1, section_accounting_ms=2, seal_ms=3,
        atomic_write_readback_ms=4, local_wal_bytes=55,
        local_wal_record_count=6, local_wal_high_water=9,
        legacy_remote_ack_sequence=7,
        legacy_remote_ack_at="2026-08-13T00:00:00Z",
        legacy_predictions=measured)
    sample = store.summary()["latestCheckpointMeasurement"]
    assert sample["dominantSectionSerializedBytes"]["marketLedger"] > 0
    assert sample["legacyRemoteAckSequence"] == 7
    assert sample["legacyRemoteAckIsExactWalDurability"] is False
    assert sample["legacyPredictionsJsonl"]["recordCount"] == 2
    assert "atomicWriteFsyncReadbackMs" in sample


def test_oversized_legacy_prediction_file_is_not_read(tmp_path):
    path = tmp_path / "predictions.jsonl"
    path.write_bytes(b"x" * 1025)
    result = metrics.measure_jsonl_metadata(str(path), maximum_bytes=1024)
    assert result["bytes"] == 1025
    assert result["recordCount"] == 0
    assert result["complete"] is False


def test_legacy_ack_never_implies_exact_cold_recovery_or_hard_rpo():
    diagnostic = metrics.exact_cold_recovery_diagnostic(
        checkpoint_mode="legacy_only",
        legacy_remote_status="verified_within_target",
        encrypted_sidecar_status="not_configured",
        stage1_state="disabled")
    assert diagnostic["legacyRemoteHealth"] == "verified_within_target"
    assert diagnostic["legacyRemoteHealthIsExactColdRecoveryProof"] is False
    assert diagnostic["status"] == "not_proven"
    assert diagnostic["hardRpoClaimPermitted"] is False
    assert "authoritative_mutation_coverage_incomplete" in \
        diagnostic["reasonCodes"]


def test_partial_future_evidence_is_only_shadow_and_full_proof_is_explicit():
    shadow = metrics.exact_cold_recovery_diagnostic(
        checkpoint_mode="shadow_full_plus_wal",
        legacy_remote_status="verified_within_target",
        encrypted_sidecar_status="verified",
        stage1_state="disabled", exact_full_generation_verified=True)
    assert shadow["status"] == "shadow"
    assert shadow["hardRpoClaimPermitted"] is False
    proven = metrics.exact_cold_recovery_diagnostic(
        checkpoint_mode="future_exact_full_plus_wal",
        legacy_remote_status="verified_within_target",
        encrypted_sidecar_status="verified", stage1_state="disabled",
        mutation_coverage_complete=True,
        exact_full_generation_verified=True,
        exact_wal_tail_verified=True,
        exact_authority_manifest_verified=True)
    assert proven["status"] == "proven"
    assert proven["hardRpoClaimPermitted"] is True

    hostile_legacy = metrics.exact_cold_recovery_diagnostic(
        checkpoint_mode="legacy_only", legacy_remote_status="healthy",
        encrypted_sidecar_status="verified", stage1_state="disabled",
        mutation_coverage_complete=True,
        exact_full_generation_verified=True,
        exact_wal_tail_verified=True,
        exact_authority_manifest_verified=True)
    assert hostile_legacy["status"] != "proven"
    assert hostile_legacy["hardRpoClaimPermitted"] is False


def test_unknown_mutation_class_fails_loud_but_does_not_create_a_file(tmp_path):
    path = tmp_path / "metrics.json"
    store = metrics.RecoveryMeasurementStore(str(path))
    with pytest.raises(ValueError, match="unregistered_mutation_class"):
        store.record_mutation("future.unknown", plaintext_bytes_estimate=1)
    assert not path.exists()


def test_no_new_external_dependency_or_credentials_are_needed():
    source = inspect.getsource(metrics)
    assert "requests" not in source
    assert "boto" not in source
    assert "API_KEY" not in source
    assert "SECRET_KEY" not in source


def test_metadata_aggregation_hot_path_is_bounded_and_submillisecond_average():
    store = metrics.RecoveryMeasurementStore(None)
    started = time.perf_counter()
    for _ in range(1000):
        store.record_mutation(
            "core.batch_cursor", plaintext_bytes_estimate=256,
            latency_ms=.25)
    elapsed = time.perf_counter() - started
    # A deliberately loose hostile-regression ceiling. Typical local execution
    # is below 0.1 ms/event; this allows slow shared CI by an order of magnitude.
    assert elapsed / 1000 < .001
