"""v13.4.3 narrow Checkpoint V2 RSS-retention regression contracts."""
from __future__ import annotations

import copy
import fcntl
import gc
import hashlib
import json
import os
import pathlib
import sqlite3
import threading
from types import SimpleNamespace
from unittest import mock

import pytest

import argus_checkpoint_v2 as v2
from scripts.checkpoint_v2_resource_probe import (
    repeated_rss_bound_failure,
    runtime_resource_growth_failures,
)


def snapshot(index=0, payload_bytes=32_768):
    return {
        "schemaVersion": "argus-durable-v3",
        "marketLedger": {
            "observations": [{
                "id": f"observation-{index}",
                "payload": "m" * payload_bytes,
            }],
        },
        "missions": [{"missionId": f"mission-{index}"}],
    }


def resource_counts():
    gc.collect()
    connections = cursors = 0
    for value in gc.get_objects():
        try:
            connections += isinstance(value, sqlite3.Connection)
            cursors += isinstance(value, sqlite3.Cursor)
        except ReferenceError:
            continue
    fd_count = None
    for candidate in (pathlib.Path("/proc/self/fd"), pathlib.Path("/dev/fd")):
        try:
            fd_count = len(list(candidate.iterdir()))
            break
        except OSError:
            pass
    sqlite_mappings = None
    try:
        sqlite_mappings = sum(
            "checkpoint-v2.sqlite" in line
            for line in pathlib.Path("/proc/self/maps").read_text().splitlines())
    except (FileNotFoundError, OSError):
        pass
    return {
        "connections": connections,
        "cursors": cursors,
        "fds": fd_count,
        "threads": threading.active_count(),
        "sqliteMappings": sqlite_mappings,
    }


def test_consumption_is_explicit_and_default_call_remains_compatible(tmp_path):
    ordinary = snapshot()
    expected = copy.deepcopy(ordinary)
    v2.write_generation(str(tmp_path / "ordinary"), ordinary,
                        source_generation="legacy")
    assert ordinary == expected

    consumable = snapshot()
    expected = copy.deepcopy(consumable)
    result = v2.write_generation(
        str(tmp_path / "consumed"), consumable, source_generation="legacy",
        consume_snapshot=True)
    assert result["verified"] is True
    assert consumable == {}
    assert v2.restore_generation(str(tmp_path / "consumed"))["snapshot"] == \
        expected


def test_consumption_requires_mutable_mapping(tmp_path):
    with pytest.raises(v2.CheckpointV2Error) as raised:
        v2.write_generation(
            str(tmp_path), mock.MagicMock(spec=dict),
            source_generation="legacy", consume_snapshot=True)
    assert raised.value.classification == \
        "checkpoint_v2_consumable_snapshot_required"


@pytest.mark.parametrize("fault_after", ["segment", "transaction"])
def test_serialization_and_transaction_failure_release_snapshot_and_pending(
        tmp_path, fault_after):
    value = snapshot(payload_bytes=128_000)
    with pytest.raises(v2.CheckpointV2Error):
        v2.write_generation(
            str(tmp_path), value, source_generation="legacy",
            consume_snapshot=True, fault_after=fault_after)
    assert value == {}
    assert not list(tmp_path.glob(".v2-pending-*"))


def test_verification_and_post_manifest_failure_preserve_verified_disk_state(
        tmp_path):
    original = snapshot(1)
    v2.write_generation(str(tmp_path), original, source_generation="first")

    checksum_value = snapshot(2)
    with mock.patch.object(v2, "_file_stats",
                           side_effect=OSError("checksum unavailable")):
        with pytest.raises(v2.CheckpointV2Error) as raised:
            v2.write_generation(
                str(tmp_path), checksum_value, source_generation="checksum",
                consume_snapshot=True)
    assert raised.value.classification == "checkpoint_v2_checksum_failed"
    assert checksum_value == {}
    assert v2.restore_generation(str(tmp_path))["snapshot"] == original
    assert not list(tmp_path.glob(".v2-pending-*"))

    promoted_value = snapshot(3)
    real_prune = v2._prune_generations
    with mock.patch.object(
            v2, "_prune_generations",
            side_effect=OSError("injected after manifest promotion")):
        with pytest.raises(v2.CheckpointV2Error) as raised:
            v2.write_generation(
                str(tmp_path), promoted_value, source_generation="promoted",
                consume_snapshot=True)
    assert raised.value.classification == "checkpoint_v2_retention_prune_failed"
    assert promoted_value == {}
    assert v2.restore_generation(str(tmp_path))["snapshot"] == snapshot(3)
    assert not list(tmp_path.glob(".v2-pending-*"))
    real_prune(tmp_path, (v2.public_status(str(tmp_path))["generationId"],))


def test_writer_contention_and_validation_failure_release_throwaway_snapshot(
        tmp_path):
    tmp_path.mkdir(exist_ok=True)
    lock_path = tmp_path / "checkpoint-v2.writer.lock"
    with open(lock_path, "a+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        value = snapshot()
        with pytest.raises(v2.CheckpointV2Error) as raised:
            v2.write_generation(
                str(tmp_path), value, source_generation="busy",
                consume_snapshot=True)
        assert raised.value.classification == "checkpoint_v2_writer_busy"
        assert value == {}
    invalid = {"missions": [{} for _ in range(121)]}
    with pytest.raises(v2.CheckpointV2Error) as raised:
        v2.write_generation(
            str(tmp_path), invalid, source_generation="invalid",
            consume_snapshot=True)
    assert raised.value.classification == "checkpoint_v2_count_limit_exceeded"
    assert invalid == {}


def test_allocator_reclaim_is_scoped_and_reports_only_scalar_values():
    trim = mock.MagicMock(return_value=1)
    allocator = SimpleNamespace(malloc_trim=trim)
    with mock.patch.object(v2, "_process_rss_bytes",
                           side_effect=[100_000_000, 40_000_000]), \
            mock.patch.object(v2.ctypes, "CDLL", return_value=allocator), \
            mock.patch.object(v2.os, "uname",
                              return_value=SimpleNamespace(sysname="Linux")):
        report = v2._release_unused_allocator_memory(64 * 1024 ** 2)
    assert report == {
        "attempted": True,
        "supported": True,
        "sourceBytes": 64 * 1024 ** 2,
        "rssBeforeBytes": 100_000_000,
        "rssAfterBytes": 40_000_000,
        "rssReleasedBytes": 60_000_000,
        "reportedReleasedBytes": None,
    }
    trim.assert_called_once_with(0)
    with mock.patch.object(v2.ctypes, "CDLL") as loader:
        small = v2._release_unused_allocator_memory(1024)
    assert small["attempted"] is False
    loader.assert_not_called()
    assert all(value is None or isinstance(value, (bool, int))
               for value in report.values())


def test_resource_gate_uses_live_owners_not_raw_allocator_mapping_count():
    baseline = {
        "sqliteConnectionCount": 0, "sqliteCursorCount": 0,
        "threadCount": 1, "descriptorCount": 4, "futureCount": 0,
        "mappingCount": 199, "sqliteOrTempMappingCount": 0,
    }
    allocator_retention_only = dict(baseline, mappingCount=214)
    assert runtime_resource_growth_failures(
        baseline, allocator_retention_only) == []

    live_owner_growth = dict(
        allocator_retention_only, sqliteOrTempMappingCount=1)
    assert runtime_resource_growth_failures(
        baseline, live_owner_growth) == ["sqliteOrTempMappingCount"]


def test_eight_cycle_monotonic_rss_is_diagnostic_inside_proven_envelope():
    bounded = {
        "steadyStateGrowthBytes": 15_691_776,
        "strictlyMonotonicSteadyState": True,
    }
    assert repeated_rss_bound_failure(bounded) is None

    outside_envelope = dict(
        bounded, steadyStateGrowthBytes=128 * 1024 ** 2)
    assert repeated_rss_bound_failure(outside_envelope) == \
        "checkpoint_v2_steady_state_growth_exceeded"


def test_eight_cycles_bound_disk_metadata_and_runtime_resources(tmp_path):
    baseline = resource_counts()
    for index in range(8):
        value = snapshot(index, payload_bytes=256_000)
        result = v2.write_generation(
            str(tmp_path), value, source_generation=f"cycle-{index}",
            consume_snapshot=True,
            validation_context={"formalSoakState": "not_started"})
        assert result["verified"] is True
        assert value == {}
        assert v2.restore_generation(str(tmp_path))["verified"] is True
        assert not list(tmp_path.glob(".v2-pending-*"))
        assert len(list(tmp_path.glob("v2-generation-*"))) <= \
            v2.MAXIMUM_GENERATIONS
    manifest = json.loads((tmp_path / v2.MANIFEST_NAME).read_text())
    assert len(manifest["generationHistory"]) == v2.MAXIMUM_GENERATIONS
    assert len(list(tmp_path.glob("v2-generation-*"))) == \
        v2.MAXIMUM_GENERATIONS
    assert manifest["stage1Validation"]["formalSoakState"] == "not_started"
    status = v2.public_status(str(tmp_path))
    assert status["legacyRestoreAuthority"] is True
    assert status["v2RestoreAuthority"] is False
    assert status["formalSoakState"] == "not_started"
    ending = resource_counts()
    for field in ("connections", "cursors", "threads", "fds",
                  "sqliteMappings"):
        if baseline[field] is not None and ending[field] is not None:
            assert ending[field] <= baseline[field], (field, baseline, ending)


def test_ten_incident_temp_files_are_byte_immutable(tmp_path):
    legacy = tmp_path / "state.json"
    legacy.write_text("{}", encoding="utf-8")
    incident = []
    for index in range(10):
        path = tmp_path / f"state.json.incident-{index}.v1338-tmp"
        path.write_bytes(f"retained-{index}".encode("ascii"))
        incident.append(path)
    before = {path.name: (path.stat().st_ino, path.stat().st_mtime_ns,
                          hashlib.sha256(path.read_bytes()).hexdigest())
              for path in incident}
    value = snapshot()
    result = v2.write_generation(
        str(tmp_path / "v2"), value, source_generation="legacy",
        consume_snapshot=True, validation_context={
            "legacyCheckpointPath": str(legacy),
            "legacyTempDirectory": str(tmp_path),
            "formalSoakState": "not_started",
        })
    after = {path.name: (path.stat().st_ino, path.stat().st_mtime_ns,
                         hashlib.sha256(path.read_bytes()).hexdigest())
             for path in incident}
    assert after == before
    telemetry = result["resourceTelemetry"]
    assert telemetry["legacyTempBaselineCount"] == 10
    assert telemetry["legacyTempAfterCount"] == 10
    assert telemetry["newLegacyTempCount"] == 0
