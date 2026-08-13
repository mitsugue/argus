"""Privacy, bounding, interval and recovery-claim tests for Phase A metrics."""

import copy
import datetime as dt
import inspect
import json
import time

import pytest

import argus_recovery_metrics as metrics
import argus_recovery_registry as registry


UTC = dt.timezone.utc


class Clock:
    def __init__(self, value):
        self.value = value

    def __call__(self):
        return self.value


def _persisted_metrics_fixture(tmp_path):
    now = dt.datetime(2026, 8, 13, 12, 0, 0, tzinfo=UTC)
    path = tmp_path / "measurement.json"
    store = metrics.RecoveryMeasurementStore(str(path), clock=Clock(now))
    store.record_mutation(
        "core.batch_cursor", plaintext_bytes_estimate=42,
        latency_ms=.5, local_sequence=7, observed_at=now)
    store.record_checkpoint(
        checkpoint_bytes=10_000,
        section_sizes={"marketLedger": 44, "termOverlay": 11,
                       "agentQueue": 22, "costPolicy": 33},
        source_assembly_ms=1.5, section_accounting_ms=2.5, seal_ms=3.5,
        atomic_write_readback_ms=4.5, local_wal_bytes=55,
        local_wal_record_count=6, local_wal_high_water=9,
        legacy_remote_ack_sequence=7,
        legacy_remote_ack_at="2026-08-13T11:59:00Z",
        legacy_predictions={"configured": True, "exists": True,
                            "bytes": 20, "recordCount": 2,
                            "complete": True},
        observed_at=now)
    assert path.exists()
    return path, json.loads(path.read_text(encoding="utf-8"))


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


def test_complete_public_projection_uses_one_fail_closed_identifier_policy():
    now = dt.datetime(2026, 8, 13, 12, 0, 0, tzinfo=UTC)
    store = metrics.RecoveryMeasurementStore(None, clock=Clock(now))
    private = [row for row in registry.mutations()
               if row.privacyClass != registry.PrivacyClass.PUBLIC_METADATA or
               row.payloadTelemetryPolicy !=
               registry.PayloadTelemetryPolicy.METADATA_ONLY or any(
                   metrics._public_telemetry_identifier("state", target) !=
                   target for target in row.targetStateIds)]
    for row in private:
        store.record_mutation(
            row.mutationClass, plaintext_bytes_estimate=10,
            observed_at=now)
    store.record_checkpoint(
        checkpoint_bytes=10_000,
        section_sizes={"marketLedger": 44, "termOverlay": 11,
                       "agentQueue": 22, "costPolicy": 33,
                       "urlCache": 55},
        source_assembly_ms=1, section_accounting_ms=2, seal_ms=3,
        atomic_write_readback_ms=4, local_wal_bytes=5,
        local_wal_record_count=6, local_wal_high_water=7,
        legacy_remote_ack_sequence=0, legacy_remote_ack_at=None,
        legacy_predictions={"configured": True, "exists": False,
                            "bytes": 0, "recordCount": 0,
                            "complete": True}, observed_at=now)

    public = store.public_summary()
    encoded = json.dumps(public, sort_keys=True)
    for row in private:
        assert row.mutationClass not in encoded
        for target in row.targetStateIds:
            assert target not in encoded
    for section in ("termOverlay", "agentQueue", "costPolicy", "urlCache"):
        assert section not in encoded

    redacted = metrics.PUBLIC_REDACTED_IDENTIFIER
    assert public["mutationDistributions"][redacted]["mutationCount"] == \
        len(private)
    for minutes in ("5", "15", "30"):
        assert public["intervalStatistics"][minutes]["latest"][
            "byMutationClass"] == {redacted: len(private)}
    checkpoint = public["latestCheckpointMeasurement"]
    assert checkpoint["sectionSerializedBytes"][redacted] == 121
    assert checkpoint["sectionSerializedBytes"]["marketLedger"] == 44
    assert "legacyPredictionsJsonl" not in checkpoint


def test_private_event_time_is_bucketed_and_public_failure_is_fixed_shape():
    observed = dt.datetime(
        2026, 8, 13, 12, 3, 17, 123456, tzinfo=UTC)
    store = metrics.RecoveryMeasurementStore(
        None, clock=Clock(observed))
    store.record_mutation(
        "security.nonce_reservation", plaintext_bytes_estimate=10,
        observed_at=observed)
    public = store.public_summary()
    assert public["latestObservedLocalMutationAt"] == \
        "2026-08-13T12:00:00Z"
    assert public["latestObservedLocalMutationAtIsBucketApproximation"] is True
    assert "12:03:17" not in json.dumps(public, sort_keys=True)
    fallback = metrics.public_recovery_measurement_unavailable()
    assert fallback["status"] == "SHADOW"
    assert fallback["coverage"] == "INCOMPLETE"
    assert fallback["hardRpoClaimPermitted"] is False


@pytest.mark.parametrize("case, mutate", [
    ("duration_string", lambda d: d["checkpointSamples"][-1].__setitem__(
        "sourceAssemblyMs", "OWNER_PRIVATE_SENTINEL")),
    ("section_value_string", lambda d: d["checkpointSamples"][-1][
        "sectionSerializedBytes"].__setitem__(
            "termOverlay", "OWNER_PRIVATE_SENTINEL")),
    ("boolean_string", lambda d: d["checkpointSamples"][-1].__setitem__(
        "success", "true")),
    ("boolean_integer", lambda d: d["checkpointSamples"][-1].__setitem__(
        "success", 1)),
    ("integer_string", lambda d: d["buckets"][-1].__setitem__(
        "mutationCount", "1")),
    ("sequence_string", lambda d: d["recentMutations"][-1].__setitem__(
        "localSequence", "7")),
    ("histogram_bool", lambda d: d["dailyDistributions"]["2026-08-13"][
        "core.batch_cursor"]["plaintextBytesHistogram"].__setitem__(
            "64", True)),
    ("nan_duration", lambda d: d["checkpointSamples"][-1].__setitem__(
        "sealMs", float("nan"))),
    ("infinite_duration", lambda d: d["checkpointSamples"][-1].__setitem__(
        "sectionAccountingMs", float("inf"))),
    ("negative_bytes", lambda d: d["checkpointSamples"][-1].__setitem__(
        "localWalBytes", -1)),
    ("nan_section_bytes", lambda d: d["checkpointSamples"][-1][
        "sectionSerializedBytes"].__setitem__("marketLedger", float("nan"))),
    ("absurd_integer", lambda d: d["checkpointSamples"][-1].__setitem__(
        "localWalHighWater", metrics.MAX_METRIC_NUMBER + 1)),
    ("bool_as_int", lambda d: d["checkpointSamples"][-1].__setitem__(
        "localWalRecordCount", True)),
    ("nested_unknown", lambda d: d["checkpointSamples"][-1].__setitem__(
        "futurePrivateField", "OWNER_PRIVATE_SENTINEL")),
    ("false_exact_durability", lambda d: d["checkpointSamples"][-1].__setitem__(
        "legacyRemoteAckIsExactWalDurability", True)),
    ("malformed_timestamp", lambda d: d["checkpointSamples"][-1].__setitem__(
        "observedAt", "2026-08-13")),
    ("unhashable_target", lambda d: d["recentMutations"][-1].__setitem__(
        "targetStateIds", [{}])),
    ("missing_required", lambda d: d["checkpointSamples"][-1].pop(
        "checkpointSerializedBytes")),
    ("top_level_bool_as_int", lambda d: d.__setitem__("retentionDays", True)),
])
def test_strict_persisted_schema_rejects_hostile_nested_values_without_echo(
        tmp_path, case, mutate):
    path, document = _persisted_metrics_fixture(tmp_path)
    mutate(document)
    path.write_text(json.dumps(document), encoding="utf-8")

    restarted = metrics.RecoveryMeasurementStore(str(path))
    public = restarted.public_summary()
    assert public["loadStatus"] == "invalid_schema", case
    assert public["latestCheckpointMeasurement"] is None
    assert "OWNER_PRIVATE_SENTINEL" not in json.dumps(public, sort_keys=True)


def test_strict_schema_accepts_only_canonical_typed_restart(tmp_path):
    path, document = _persisted_metrics_fixture(tmp_path)
    assert metrics._validate_document(document) is True
    restarted = metrics.RecoveryMeasurementStore(str(path))
    public = restarted.public_summary()
    assert public["loadStatus"] == "loaded"
    assert public["latestCheckpointMeasurement"][
        "checkpointSerializedBytes"] == 10_000
    assert public["intervalStatistics"]["5"]["mutationCount"]["max"] == 1
    distribution = public["mutationDistributions"]["private.redacted"]
    for key in ("mutationPlaintextBytesApproxP50",
                "mutationPlaintextBytesApproxP95",
                "mutationPlaintextBytesApproxP99"):
        assert distribution[key] is None or isinstance(distribution[key], int)


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
    distribution = summary["mutationDistributions"]["private.redacted"]
    assert distribution["mutationCount"] == 2
    assert distribution["plaintextBytesEstimate"] == 400
    assert distribution["maxSingleMutationPlaintextBytesEstimate"] == 300


def test_recent_samples_and_time_retention_are_bounded():
    clock = Clock(dt.datetime(2026, 8, 13, 0, 0, tzinfo=UTC))
    store = metrics.RecoveryMeasurementStore(None, clock=clock)
    old = clock.value - dt.timedelta(days=metrics.RETENTION_DAYS + 1)
    with pytest.raises(ValueError, match="invalid_recovery_measurement"):
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
    assert store.summary()["mutationDistributions"]["private.redacted"][
        "mutationCount"] == metrics.MAX_RECENT_MUTATIONS + 25


def test_live_producers_reject_nonfinite_future_and_inconsistent_inputs():
    now = dt.datetime.now(UTC).replace(microsecond=0)
    store = metrics.RecoveryMeasurementStore(None, clock=Clock(now))
    with pytest.raises(ValueError, match="invalid_recovery_measurement"):
        store.record_mutation(
            "core.batch_cursor", plaintext_bytes_estimate=1,
            latency_ms=float("inf"), observed_at=now)
    with pytest.raises(ValueError, match="invalid_recovery_measurement"):
        store.record_mutation(
            "core.batch_cursor", plaintext_bytes_estimate=1,
            observed_at=now + dt.timedelta(days=2))
    with store._lock:
        store._ensure_loaded()
        assert store._document["recentMutations"] == []
        assert metrics._validate_document(store._document)

    checkpoint = dict(
        checkpoint_bytes=10, section_sizes={"marketLedger": 11},
        source_assembly_ms=1, section_accounting_ms=2, seal_ms=3,
        atomic_write_readback_ms=4, local_wal_bytes=5,
        local_wal_record_count=6, local_wal_high_water=7,
        legacy_remote_ack_sequence=0, legacy_remote_ack_at=None,
        legacy_predictions={"configured": True, "exists": False,
                            "bytes": 0, "recordCount": 0,
                            "complete": True}, observed_at=now)
    with pytest.raises(ValueError, match="invalid_recovery_measurement"):
        store.record_checkpoint(**checkpoint)


def test_hot_producer_rejects_public_rollup_overflow_without_state_change():
    now = dt.datetime.now(UTC).replace(second=0, microsecond=0)
    now -= dt.timedelta(minutes=now.minute % metrics.BUCKET_MINUTES)
    store = metrics.RecoveryMeasurementStore(None, clock=Clock(now))
    with store._lock:
        store._ensure_loaded()
        store._document["buckets"] = [{
            "bucketStart": metrics._iso(now),
            "mutationCount": metrics.MAX_METRIC_NUMBER,
            "transitionCount": 0,
            "recordCount": 0,
            "successCount": metrics.MAX_METRIC_NUMBER,
            "failureCount": 0,
            "plaintextBytesEstimate": 0,
            "candidateRecordPlaintextBytesEstimate": 0,
            "maxSingleMutationPlaintextBytesEstimate": 0,
            "byMutationClass": {
                "core.batch_cursor": metrics.MAX_METRIC_NUMBER},
            "byWalCoverage": {
                registry.WalCoverage.PARTIAL.value:
                    metrics.MAX_METRIC_NUMBER},
        }]
        store._document["updatedAt"] = metrics._iso(now)
        assert metrics._validate_document(store._document)
        before = copy.deepcopy(store._document)
    with pytest.raises(ValueError, match="invalid_recovery_measurement"):
        store.record_mutation(
            "core.batch_cursor", plaintext_bytes_estimate=0,
            transition_count=0, record_count=0,
            observed_at=now + dt.timedelta(minutes=5))
    with store._lock:
        assert store._document == before


def test_deep_json_is_discarded_and_prediction_reason_is_sanitized(tmp_path):
    path = tmp_path / "measurement.json"
    path.write_text("[" * 1100 + "]" * 1100, encoding="utf-8")
    # Python may reject extreme nesting in json.load (invalid_or_partial) or
    # decode it and let the closed schema reject the non-document value
    # (invalid_schema). Both are total, content-free whole-artifact rejection.
    assert metrics.RecoveryMeasurementStore(str(path)).public_summary()[
        "loadStatus"] in ("invalid_or_partial", "invalid_schema")

    now = dt.datetime.now(UTC).replace(microsecond=0)
    store = metrics.RecoveryMeasurementStore(
        str(tmp_path / "valid.json"), clock=Clock(now))
    predictions = {
        "configured": True, "exists": True, "bytes": 65_000_000,
        "recordCount": 0, "complete": False,
        "reason": "measurement_maximum_exceeded"}
    assert store.record_checkpoint(
        checkpoint_bytes=100, section_sizes={}, source_assembly_ms=1,
        section_accounting_ms=2, seal_ms=3, atomic_write_readback_ms=4,
        local_wal_bytes=5, local_wal_record_count=6,
        local_wal_high_water=7, legacy_remote_ack_sequence=0,
        legacy_remote_ack_at=None, legacy_predictions=predictions,
        observed_at=now)
    persisted = json.loads((tmp_path / "valid.json").read_text())
    assert "reason" not in persisted["checkpointSamples"][-1][
        "legacyPredictionsJsonl"]


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
    assert summary["mutationDistributions"]["private.redacted"][
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

    metrics_path = tmp_path / "metrics.json"
    store = metrics.RecoveryMeasurementStore(str(metrics_path))
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
    assert "legacyPredictionsJsonl" not in sample
    persisted = json.loads(metrics_path.read_text(encoding="utf-8"))
    assert persisted["checkpointSamples"][-1]["legacyPredictionsJsonl"][
        "recordCount"] == 2
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
