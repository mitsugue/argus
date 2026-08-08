"""v13.4.5 short-lived Checkpoint V2 writer contracts."""
from __future__ import annotations

import fcntl
import json
import os
import pathlib
import signal
from unittest import mock

import pytest

import argus_checkpoint_v2 as v2
import argus_checkpoint_v2_isolated as isolated
import argus_persistent_storage as storage


BUILD = "a" * 40
BOOT = "boot-test-1"


def snapshot(index=0, payload_bytes=4096):
    return {
        "schemaVersion": "argus-durable-v3",
        "marketLedger": {
            "observations": [{"id": f"obs-{index}",
                              "payload": "x" * payload_bytes}],
            "turningPoints": [], "derivedMetrics": [],
        },
        "missions": [{"missionId": f"mission-{index}"}],
        "missionTickDurability": {"walAppliedSequence": 0},
    }


def source_contract(root: pathlib.Path, index=0, payload_bytes=4096):
    source = root / "legacy.json"
    write = storage.write_checkpoint(
        str(source), snapshot(index, payload_bytes), temp_directory=str(root))
    return source, {**write, "snapshotBytes": write["bytes"],
                    "includedWalSequence": 0,
                    "walCompaction": {"compactedThrough": 0}}


def launch(root: pathlib.Path, source: pathlib.Path, receipt, **kwargs):
    return isolated.launch_isolated_generation(
        str(root / "v2"), source_path=str(source),
        legacy_checkpoint=receipt, wal_path=str(root / "wal.jsonl"),
        wal_upper_sequence=0, backend_build_sha=BUILD,
        backend_boot_id=BOOT, mission_window_id="mw-2026-08-08T00:00:00Z",
        trigger_source="ec2_systemd", timeout_seconds=60, **kwargs)


def test_fresh_child_builds_and_parent_promotes_verified_generation(tmp_path):
    source, receipt = source_contract(tmp_path)
    parent_pid = os.getpid()
    result = launch(tmp_path, source, receipt)
    restored = v2.restore_generation(str(tmp_path / "v2"))
    assert result["verified"] is True
    assert result["writerMode"] == "isolated_process"
    assert result["validation"]["manifestPromoted"] is True
    assert result["validation"]["childProcessId"] != parent_pid
    assert restored["snapshot"] == storage.load_checkpoint(
        str(source), require_seal=True)
    assert not list((tmp_path / "v2").glob(".v2-isolated-job-*"))
    assert not list((tmp_path / "v2").glob(".v2-pending-*"))


def test_descriptor_and_result_are_small_integrity_checked_and_payload_free(
        tmp_path):
    source, receipt = source_contract(tmp_path)
    captured = {}
    real = isolated._write_contract

    def record(path, schema, payload):
        captured[schema] = json.loads(json.dumps(payload))
        return real(path, schema, payload)

    with mock.patch.object(isolated, "_write_contract", side_effect=record):
        launch(tmp_path, source, receipt)
    descriptor = captured[isolated.DESCRIPTOR_SCHEMA]
    assert len(isolated._canonical(descriptor)) < isolated.MAXIMUM_CONTRACT_BYTES
    encoded = json.dumps(descriptor)
    assert "observations" not in encoded
    assert "payload" not in encoded
    assert "token" not in encoded.lower()
    assert descriptor["sourceCheckpoint"]["sha256"] == receipt["snapshotHash"]


def test_wrong_source_hash_fails_without_manifest_or_in_process_fallback(tmp_path):
    source, receipt = source_contract(tmp_path)
    receipt["snapshotHash"] = "0" * 64
    with pytest.raises(isolated.IsolatedWriterError) as raised:
        launch(tmp_path, source, receipt)
    assert raised.value.classification == "source_hash_mismatch"
    assert not (tmp_path / "v2" / v2.MANIFEST_NAME).exists()


def test_source_wal_boundary_must_exactly_match_descriptor(tmp_path):
    source = tmp_path / "legacy.json"
    write = storage.write_checkpoint(
        str(source), snapshot(), temp_directory=str(tmp_path))
    loaded = storage.load_checkpoint(str(source), require_seal=True)
    loaded["missionTickDurability"]["walAppliedSequence"] = 1
    write = storage.write_checkpoint(
        str(source), loaded, temp_directory=str(tmp_path))
    receipt = {**write, "snapshotBytes": write["bytes"],
               "includedWalSequence": 0,
               "walCompaction": {"compactedThrough": 0}}
    with pytest.raises(isolated.IsolatedWriterError) as raised:
        launch(tmp_path, source, receipt)
    assert raised.value.classification == "WAL_boundary_invalid"
    assert not (tmp_path / "v2" / v2.MANIFEST_NAME).exists()


def test_spawn_failure_is_classified_without_starting_sampler(tmp_path):
    source, receipt = source_contract(tmp_path)
    with mock.patch.object(isolated.subprocess, "Popen",
                           side_effect=OSError("spawn failed")), \
            mock.patch.object(isolated._ParentSampler, "start") as start, \
            pytest.raises(isolated.IsolatedWriterError) as raised:
        launch(tmp_path, source, receipt)
    assert raised.value.classification == "child_spawn_failed"
    start.assert_not_called()


def test_writer_lock_collision_fails_fast_and_preserves_authority(tmp_path):
    source, receipt = source_contract(tmp_path)
    v2_root = tmp_path / "v2"
    v2_root.mkdir()
    with (v2_root / isolated.GLOBAL_LOCK_NAME).open("a+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(isolated.IsolatedWriterError) as raised:
            launch(tmp_path, source, receipt)
    assert raised.value.classification == "writer_lock_failed"
    assert not (v2_root / v2.MANIFEST_NAME).exists()


@pytest.mark.parametrize("fault,classification", [
    ("source_sigterm", "child_signal"),
    ("serialization_sigkill", "child_oom"),
    ("transaction_kill", "checkpoint_v2_transaction_failed"),
    ("post_transaction_kill", "checkpoint_v2_transaction_failed"),
])
def test_child_failure_never_promotes_or_retries_in_parent(
        tmp_path, fault, classification):
    source, receipt = source_contract(tmp_path)
    with pytest.raises(isolated.IsolatedWriterError) as raised:
        launch(tmp_path, source, receipt, fault=fault)
    assert raised.value.classification == classification
    assert not (tmp_path / "v2" / v2.MANIFEST_NAME).exists()


def test_timeout_terminates_reaps_and_does_not_promote(tmp_path):
    source, receipt = source_contract(tmp_path)
    with pytest.raises(isolated.IsolatedWriterError) as raised:
        isolated.launch_isolated_generation(
            str(tmp_path / "v2"), source_path=str(source),
            legacy_checkpoint=receipt, wal_path=str(tmp_path / "wal"),
            wal_upper_sequence=0, backend_build_sha=BUILD,
            backend_boot_id=BOOT, mission_window_id="mw-timeout",
            trigger_source="ec2_systemd", timeout_seconds=1,
            fault="post_result_pause")
    assert raised.value.classification == "timeout"
    assert not (tmp_path / "v2" / v2.MANIFEST_NAME).exists()


def test_corrupt_descriptor_is_fail_closed(tmp_path):
    job = tmp_path / "v2" / (isolated.JOB_PREFIX + "a" * 32)
    job.mkdir(parents=True)
    descriptor = job / "descriptor.json"
    descriptor.write_text('{"schemaVersion":"wrong"}')
    assert isolated.run_child(str(descriptor)) == 2
    assert not (job / "candidate" / v2.MANIFEST_NAME).exists()


def test_corrupt_result_is_rejected_before_promotion(tmp_path):
    source, receipt = source_contract(tmp_path)
    real_read = isolated._read_contract

    def corrupt(path, schema):
        value = real_read(path, schema)
        if schema == isolated.RESULT_SCHEMA:
            value["sourceSha256"] = "f" * 64
        return value

    with mock.patch.object(isolated, "_read_contract", side_effect=corrupt), \
            pytest.raises(isolated.IsolatedWriterError) as raised:
        launch(tmp_path, source, receipt)
    assert raised.value.classification == "result_identity_mismatch"
    assert not (tmp_path / "v2" / v2.MANIFEST_NAME).exists()


def test_stale_orphan_reconciliation_is_bounded_and_shape_confined(tmp_path):
    root = tmp_path / "v2"
    root.mkdir()
    stale = root / (isolated.JOB_PREFIX + "a" * 32)
    (stale / "candidate").mkdir(parents=True)
    (stale / "descriptor.json").write_text("{}")
    report = isolated.reconcile_stale_jobs(str(root))
    assert report == {"detectedCount": 1, "removedCount": 1,
                      "malformedCount": 0}
    outside = tmp_path / "incident-evidence"
    outside.write_text("preserve")
    assert outside.read_text() == "preserve"


def test_public_telemetry_is_bounded_and_contains_no_paths_or_payload(tmp_path):
    source, receipt = source_contract(tmp_path)
    result = launch(tmp_path, source, receipt)
    public = isolated.public_telemetry(result)
    assert public["writerMode"] == "isolated_process"
    encoded = json.dumps(public)
    assert str(tmp_path) not in encoded
    assert "observations" not in encoded
    assert "payload" not in encoded


def test_32_cycles_keep_one_parent_distinct_children_and_bounded_disk(tmp_path):
    source, receipt = source_contract(tmp_path, payload_bytes=32_768)
    parent_pid = os.getpid()
    child_pids = []
    rss_after = []
    for _ in range(32):
        result = launch(tmp_path, source, receipt)
        child_pids.append(result["validation"]["childProcessId"])
        rss_after.append(result["resourceTelemetry"]["processRssAfterBytes"])
        budget = v2.disk_budget_status(str(tmp_path / "v2"))
        assert budget["pendingGenerationCount"] == 0
        assert budget["retainedGenerationCount"] <= 4
        assert budget["freeBytes"] >= v2.MINIMUM_FREE_SPACE_RESERVE
        assert os.getpid() == parent_pid
    assert len(set(child_pids)) == 32
    measured = [value for value in rss_after[2:] if value is not None]
    if len(measured) > 1:
        assert max(measured) - min(measured) <= 128 * 1024 ** 2
    assert v2.restore_generation(str(tmp_path / "v2"))["verified"] is True


def test_scanner_production_path_has_no_direct_write_generation_call():
    source = pathlib.Path("scanner.py").read_text(encoding="utf-8")
    function = source.split("def _checkpoint_v2_dual_write", 1)[1].split(
        "\ndef _foundation_jobs_persist", 1)[0]
    assert "argus_checkpoint_v2.write_generation" not in function
    assert "launch_isolated_generation" in function
