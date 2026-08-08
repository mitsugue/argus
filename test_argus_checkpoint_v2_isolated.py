"""v13.4.5 short-lived Checkpoint V2 writer contracts."""
from __future__ import annotations

import fcntl
import json
import os
import pathlib
import signal
import subprocess
import sys
import threading
import time
import datetime as dt
from unittest import mock

import pytest

import argus_checkpoint_v2 as v2
import argus_checkpoint_v2_isolated as isolated
import argus_persistent_storage as storage
import argus_tick_durability as durability


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


def nonzero_source_contract(root: pathlib.Path, *, lower=5000, upper=5017,
                            durable_upper=None):
    source = root / "legacy.json"
    value = snapshot()
    value["missionTickDurability"]["walAppliedSequence"] = upper
    write = storage.write_checkpoint(
        str(source), value, temp_directory=str(root))
    wal = root / "wal.jsonl"
    durable_upper = upper if durable_upper is None else durable_upper
    for sequence in range(lower, durable_upper + 1):
        durability.append_wal(
            str(wal), sequence=sequence, kind="fixture_noop",
            payload={"fixture": True, "sequence": sequence},
            job_id="isolated-wal-fixture", build_sha=BUILD)
    # Model a real compacted boundary: the anchor record is no longer live,
    # while the first retained record still names and hashes it.
    lines = wal.read_bytes().splitlines(keepends=True)
    wal.write_bytes(b"".join(lines[1:]))
    receipt = {**write, "snapshotBytes": write["bytes"],
               "includedWalSequence": upper,
               "walCompaction": {"compactedThrough": lower}}
    return source, receipt, wal


def launch(root: pathlib.Path, source: pathlib.Path, receipt, *,
           wal_path=None, wal_upper_sequence=None, **kwargs):
    return isolated.launch_isolated_generation(
        str(root / "v2"), source_path=str(source),
        legacy_checkpoint=receipt,
        wal_path=str(wal_path or (root / "wal.jsonl")),
        wal_upper_sequence=(receipt["includedWalSequence"]
                            if wal_upper_sequence is None
                            else wal_upper_sequence),
        backend_build_sha=BUILD,
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


def test_nonzero_wal_range_is_reconstructed_exactly_before_promotion(tmp_path):
    source, receipt, wal = nonzero_source_contract(tmp_path)
    result = launch(tmp_path, source, receipt, wal_path=wal)
    validation = result["validation"]
    restored = v2.restore_generation(str(tmp_path / "v2"))
    assert result["verified"] is True
    assert validation["walLowerSequence"] == 5000
    assert validation["walTargetSequence"] == 5017
    assert validation["walReconstructedSequence"] == 5017
    assert validation["walHashVerified"] is True
    assert validation["walFramingVerified"] is True
    assert validation["walSequenceVerified"] is True
    assert restored["snapshot"]["missionTickDurability"][
        "walAppliedSequence"] == 5017
    assert not list((tmp_path / "v2").glob(".v2-isolated-job-*"))
    assert result["diskBudgetAfter"]["pendingGenerationCount"] == 0


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
    source, receipt, wal = nonzero_source_contract(tmp_path)
    receipt["snapshotHash"] = "0" * 64
    with pytest.raises(isolated.IsolatedWriterError) as raised:
        launch(tmp_path, source, receipt, wal_path=wal)
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


def _wal_rows(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def _write_wal_rows(path, rows):
    path.write_bytes(b"".join(
        durability._canonical(row) + b"\n" for row in rows))


@pytest.mark.parametrize("case", [
    "target_above_durable", "target_below_durable", "missing_sequence",
    "duplicate_sequence", "out_of_order_sequence", "corrupt_hash",
])
def test_nonzero_wal_negative_matrix_fails_closed_and_reconciles(
        tmp_path, case):
    target = 5018 if case == "target_above_durable" else 5017
    durable_upper = 5017 if case == "target_above_durable" else (
        5018 if case == "target_below_durable" else 5017)
    source, receipt, wal = nonzero_source_contract(
        tmp_path, upper=target, durable_upper=durable_upper)
    rows = _wal_rows(wal)
    if case == "missing_sequence":
        rows = [row for row in rows if row["sequence"] != 5009]
    elif case == "duplicate_sequence":
        rows.insert(5, dict(rows[4]))
    elif case == "out_of_order_sequence":
        rows[4], rows[5] = rows[5], rows[4]
    elif case == "corrupt_hash":
        rows[4]["recordHash"] = "0" * 64
    _write_wal_rows(wal, rows)
    manifest = tmp_path / "v2" / v2.MANIFEST_NAME
    before = manifest.read_bytes() if manifest.exists() else None
    with pytest.raises(isolated.IsolatedWriterError) as raised:
        launch(tmp_path, source, receipt, wal_path=wal)
    assert raised.value.classification == "WAL_boundary_invalid"
    assert (manifest.read_bytes() if manifest.exists() else None) == before
    isolated.reconcile_stale_jobs(str(tmp_path / "v2"))
    assert not list((tmp_path / "v2").glob(".v2-isolated-job-*"))


def test_checkpoint_receipt_target_mismatch_fails_before_child(tmp_path):
    source, receipt, wal = nonzero_source_contract(tmp_path)
    receipt["includedWalSequence"] = 5016
    with pytest.raises(isolated.IsolatedWriterError) as raised:
        launch(tmp_path, source, receipt, wal_path=wal,
               wal_upper_sequence=5017)
    assert raised.value.classification == "WAL_boundary_invalid"
    assert not (tmp_path / "v2" / v2.MANIFEST_NAME).exists()


@pytest.mark.parametrize("included", [None, "0", False, -1, "missing"])
def test_missing_or_coerced_boundary_is_never_inferred(tmp_path, included):
    source, receipt = source_contract(tmp_path)
    if included == "missing":
        receipt.pop("includedWalSequence")
    else:
        receipt["includedWalSequence"] = included
    with pytest.raises(isolated.IsolatedWriterError) as raised:
        isolated.launch_isolated_generation(
            str(tmp_path / "v2"), source_path=str(source),
            legacy_checkpoint=receipt, wal_path=str(tmp_path / "wal"),
            wal_upper_sequence=0, backend_build_sha=BUILD,
            backend_boot_id=BOOT, mission_window_id="mw-invalid-boundary",
            trigger_source="ec2_systemd")
    assert raised.value.classification == "WAL_boundary_invalid"


@pytest.mark.parametrize("build,boot", [
    ("b" * 40, BOOT), (BUILD, "stale-boot"),
])
def test_descriptor_from_wrong_build_or_stale_boot_is_rejected(
        tmp_path, build, boot):
    source, receipt, wal = nonzero_source_contract(tmp_path)
    root = tmp_path / "v2"
    job_id = "d" * 32
    job = root / f"{isolated.JOB_PREFIX}{job_id}"
    job.mkdir(parents=True)
    payload = isolated._descriptor_payload(
        persistent_root=tmp_path, v2_root=root, job_id=job_id,
        source_path=source, source_bytes=receipt["snapshotBytes"],
        source_sha256=receipt["snapshotHash"],
        source_generation=receipt["snapshotHash"], wal_path=wal,
        wal_lower=5000, wal_upper=5017, build_sha=build, boot_id=boot,
        mission_window_id="mw-stale-identity", trigger_source="ec2_systemd",
        formal_soak_state="not_started",
        deadline=(dt.datetime.now(dt.timezone.utc) +
                  dt.timedelta(minutes=1)).isoformat())
    descriptor = job / "descriptor.json"
    isolated._write_contract(
        descriptor, isolated.DESCRIPTOR_SCHEMA, payload)
    assert isolated.run_child(
        str(descriptor), expected_build_sha=BUILD,
        expected_boot_id=BOOT) == 2
    failure = isolated._read_contract(
        job / "result.json", isolated.RESULT_SCHEMA)
    assert failure["classification"] == "descriptor_identity_mismatch"
    assert not (root / v2.MANIFEST_NAME).exists()


def test_zero_is_exact_not_wildcard_for_nonzero_source(tmp_path):
    source, receipt, _ = nonzero_source_contract(tmp_path)
    receipt["includedWalSequence"] = 0
    receipt["walCompaction"]["compactedThrough"] = 0
    empty_wal = tmp_path / "empty-wal"
    with pytest.raises(isolated.IsolatedWriterError) as raised:
        launch(tmp_path, source, receipt, wal_path=empty_wal,
               wal_upper_sequence=0)
    assert raised.value.classification == "WAL_boundary_invalid"
    assert not (tmp_path / "v2" / v2.MANIFEST_NAME).exists()


def test_source_change_after_descriptor_validation_fails_closed(tmp_path):
    source, receipt, wal = nonzero_source_contract(tmp_path)
    outcome = {}

    def invoke():
        try:
            launch(tmp_path, source, receipt, wal_path=wal,
                   fault="source_pause")
        except BaseException as exc:  # captured only for the test thread
            outcome["error"] = exc

    worker = threading.Thread(target=invoke)
    worker.start()
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and not list(
            (tmp_path / "v2").glob(
                ".v2-isolated-job-*/source-validated.marker")):
        time.sleep(0.01)
    assert list((tmp_path / "v2").glob(
        ".v2-isolated-job-*/source-validated.marker"))
    changed = snapshot(index=9)
    changed["missionTickDurability"]["walAppliedSequence"] = 5017
    storage.write_checkpoint(
        str(source), changed, temp_directory=str(tmp_path))
    worker.join(timeout=20)
    assert not worker.is_alive()
    assert isinstance(outcome.get("error"), isolated.IsolatedWriterError)
    assert outcome["error"].classification == "source_changed"
    assert not (tmp_path / "v2" / v2.MANIFEST_NAME).exists()
    isolated.reconcile_stale_jobs(str(tmp_path / "v2"))


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
    source, receipt, wal = nonzero_source_contract(tmp_path)
    v2_root = tmp_path / "v2"
    v2_root.mkdir()
    with (v2_root / isolated.GLOBAL_LOCK_NAME).open("a+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(isolated.IsolatedWriterError) as raised:
            launch(tmp_path, source, receipt, wal_path=wal)
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
    source, receipt, wal = nonzero_source_contract(tmp_path)
    with pytest.raises(isolated.IsolatedWriterError) as raised:
        launch(tmp_path, source, receipt, wal_path=wal, fault=fault)
    assert raised.value.classification == classification
    assert not (tmp_path / "v2" / v2.MANIFEST_NAME).exists()


def test_timeout_terminates_reaps_and_does_not_promote(tmp_path):
    source, receipt, wal = nonzero_source_contract(tmp_path)
    with pytest.raises(isolated.IsolatedWriterError) as raised:
        isolated.launch_isolated_generation(
            str(tmp_path / "v2"), source_path=str(source),
            legacy_checkpoint=receipt, wal_path=str(wal),
            wal_upper_sequence=receipt["includedWalSequence"],
            backend_build_sha=BUILD,
            backend_boot_id=BOOT, mission_window_id="mw-timeout",
            trigger_source="ec2_systemd", timeout_seconds=1,
            fault="post_result_pause")
    assert raised.value.classification == "timeout"
    assert not (tmp_path / "v2" / v2.MANIFEST_NAME).exists()


@pytest.mark.skipif(not sys.platform.startswith("linux"),
                    reason="Linux parent-death signal contract")
def test_parent_kill_terminates_child_and_reconciliation_is_deterministic(
        tmp_path):
    source, receipt, wal = nonzero_source_contract(tmp_path)
    receipt_path = tmp_path / "receipt.json"
    receipt_path.write_text(json.dumps(receipt))
    code = (
        "import json,sys; import argus_checkpoint_v2_isolated as i; "
        "r=json.load(open(sys.argv[3])); "
        "i.launch_isolated_generation(sys.argv[1],source_path=sys.argv[2],"
        "legacy_checkpoint=r,wal_path=sys.argv[4],wal_upper_sequence=5017,"
        "backend_build_sha='a'*40,backend_boot_id='boot-test-1',"
        "mission_window_id='mw-parent-kill',trigger_source='ec2_systemd',"
        "timeout_seconds=60,fault='post_result_pause')")
    parent = subprocess.Popen([
        sys.executable, "-c", code, str(tmp_path / "v2"), str(source),
        str(receipt_path), str(wal)], cwd=str(pathlib.Path.cwd()))
    deadline = time.monotonic() + 20
    child_pid = None
    children_file = pathlib.Path(
        f"/proc/{parent.pid}/task/{parent.pid}/children")
    while time.monotonic() < deadline and child_pid is None:
        try:
            children = children_file.read_text().split()
            child_pid = int(children[0]) if children else None
        except (FileNotFoundError, ValueError):
            pass
        time.sleep(0.02)
    assert child_pid is not None
    os.kill(parent.pid, signal.SIGKILL)
    parent.wait(timeout=10)
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and pathlib.Path(
            f"/proc/{child_pid}").exists():
        time.sleep(0.05)
    assert not pathlib.Path(f"/proc/{child_pid}").exists()
    assert not (tmp_path / "v2" / v2.MANIFEST_NAME).exists()
    report = isolated.reconcile_stale_jobs(str(tmp_path / "v2"))
    assert report["removedCount"] == 1


def test_corrupt_descriptor_is_fail_closed(tmp_path):
    job = tmp_path / "v2" / (isolated.JOB_PREFIX + "a" * 32)
    job.mkdir(parents=True)
    descriptor = job / "descriptor.json"
    descriptor.write_text('{"schemaVersion":"wrong"}')
    assert isolated.run_child(str(descriptor)) == 2
    assert not (job / "candidate" / v2.MANIFEST_NAME).exists()


@pytest.mark.parametrize("field,replacement", [
    ("sourceSha256", "f" * 64),
    ("backendBuildSha", "b" * 40),
    ("backendBootId", "stale-boot"),
])
def test_corrupt_or_stale_result_identity_is_rejected_before_promotion(
        tmp_path, field, replacement):
    source, receipt = source_contract(tmp_path)
    real_read = isolated._read_contract

    def corrupt(path, schema):
        payload = real_read(path, schema)
        if schema == isolated.RESULT_SCHEMA:
            payload[field] = replacement
        return payload

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
