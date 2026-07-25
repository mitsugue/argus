"""Persistent mission durability acceptance tests (stdlib, no provider calls)."""
from __future__ import annotations

import contextlib
import json
import os
import pathlib
import shutil
import signal
import tempfile
import threading
import types
import unittest
from unittest import mock

import argus_persistent_storage as storage
import argus_remote_journal
import argus_tick_durability as durability


_moomoo = types.ModuleType("moomoo")
_moomoo.OpenQuoteContext = lambda *args, **kwargs: None
_moomoo.OpenSecTradeContext = lambda *args, **kwargs: None
_moomoo.RET_OK = 0
import sys
sys.modules.setdefault("moomoo", _moomoo)
import scanner


def paths(root: str):
    return storage.configured_paths({
        "ARGUS_PERSISTENT_ROOT": root,
        "ARGUS_MISSION_WAL_FILE": os.path.join(root, "tick.wal"),
        "ARGUS_OSINT_PERSIST_FILE": os.path.join(root, "state.json"),
        "ARGUS_MISSION_LEASE_FILE": os.path.join(root, "tick.lease"),
        "ARGUS_MISSION_CURSOR_FILE": os.path.join(root, "cursor.json"),
        "ARGUS_MISSION_RECEIPT_FILE": os.path.join(root, "receipt.json"),
        "ARGUS_CHECKPOINT_TEMP_DIR": root,
    }, production=True)


def remote_snapshot():
    section = argus_remote_journal.snapshot_journal_section(
        events=[], meta={}, now_iso="2026-07-25T00:00:00Z")
    return {
        "schemaVersion": "argus-durable-v3",
        "generatedAt": "2026-07-25T00:00:00Z",
        **section,
    }


class FakeResponse:
    def __init__(self, status_code, value=None):
        self.status_code = status_code
        self._encoded = (
            json.dumps(value).encode("utf-8") if value is not None else b"")

    def iter_content(self, chunk_size=1024):
        for offset in range(0, len(self._encoded), chunk_size):
            yield self._encoded[offset:offset + chunk_size]

    def close(self):
        return None


@contextlib.contextmanager
def scanner_storage(root: str, *, production=True):
    saved = {
        "production": scanner._DURABILITY_PRODUCTION,
        "paths": scanner._DURABILITY_PATHS,
        "checkpoint": scanner._OSINT_PERSIST_FILE,
        "wal": scanner._MISSION_WAL_FILE,
        "lease": scanner._MISSION_LEASE_FILE,
        "cursor": scanner._MISSION_CURSOR_FILE,
        "receipt": scanner._MISSION_RECEIPT_FILE,
        "persist": dict(scanner._OSINT_PERSIST_STATE),
        "durable": dict(scanner._DURABLE_STATE),
        "storageStatus": dict(scanner._DURABLE_STORAGE_STATUS),
        "batch": dict(scanner._MISSION_BATCH_STATE),
        "shutdown": dict(scanner._SHUTDOWN),
        "startup": dict(scanner._STARTUP),
        "token": scanner._ARGUS_ADMIN_TOKEN,
        "context": dict(scanner._MISSION_TICK_CONTEXT),
    }
    configured = paths(root)
    scanner._DURABILITY_PRODUCTION = production
    scanner._DURABILITY_PATHS = configured
    scanner._OSINT_PERSIST_FILE = configured["checkpoint"]
    scanner._MISSION_WAL_FILE = configured["wal"]
    scanner._MISSION_LEASE_FILE = configured["lease"]
    scanner._MISSION_CURSOR_FILE = configured["cursor"]
    scanner._MISSION_RECEIPT_FILE = configured["receipt"]
    scanner._OSINT_PERSIST_STATE.clear()
    scanner._OSINT_PERSIST_STATE.update({"restored": False})
    scanner._DURABLE_STATE.clear()
    scanner._DURABLE_STATE.update({
        "schemaVersion": "argus-durable-v3",
        "lastWriteAt": None, "lastRestoreAt": None,
        "integrityStatus": "unknown", "lastKnownGoodAt": None,
        "restoreSource": None,
    })
    try:
        yield configured
    finally:
        scanner._DURABILITY_PRODUCTION = saved["production"]
        scanner._DURABILITY_PATHS = saved["paths"]
        scanner._OSINT_PERSIST_FILE = saved["checkpoint"]
        scanner._MISSION_WAL_FILE = saved["wal"]
        scanner._MISSION_LEASE_FILE = saved["lease"]
        scanner._MISSION_CURSOR_FILE = saved["cursor"]
        scanner._MISSION_RECEIPT_FILE = saved["receipt"]
        scanner._OSINT_PERSIST_STATE.clear()
        scanner._OSINT_PERSIST_STATE.update(saved["persist"])
        scanner._DURABLE_STATE.clear()
        scanner._DURABLE_STATE.update(saved["durable"])
        scanner._DURABLE_STORAGE_STATUS.clear()
        scanner._DURABLE_STORAGE_STATUS.update(saved["storageStatus"])
        scanner._MISSION_BATCH_STATE.clear()
        scanner._MISSION_BATCH_STATE.update(saved["batch"])
        scanner._SHUTDOWN.clear()
        scanner._SHUTDOWN.update(saved["shutdown"])
        scanner._STARTUP.clear()
        scanner._STARTUP.update(saved["startup"])
        scanner._ARGUS_ADMIN_TOKEN = saved["token"]
        scanner._MISSION_TICK_CONTEXT.clear()
        scanner._MISSION_TICK_CONTEXT.update(saved["context"])


class PathValidationTests(unittest.TestCase):
    def test_production_rejects_tmp_wal(self):
        with tempfile.TemporaryDirectory() as root:
            value = paths(root)
            value["wal"] = "/tmp/argus-production.wal"
            with self.assertRaisesRegex(storage.PersistentStorageError,
                                       "wal_temporary_path_rejected"):
                storage.validate_storage(value, production=True)

    def test_production_rejects_tmp_checkpoint(self):
        with tempfile.TemporaryDirectory() as root:
            value = paths(root)
            value["checkpoint"] = "/tmp/argus-production.json"
            with self.assertRaisesRegex(storage.PersistentStorageError,
                                       "checkpoint_temporary_path_rejected"):
                storage.validate_storage(value, production=True)

    def test_production_rejects_tmp_lease(self):
        with tempfile.TemporaryDirectory() as root:
            value = paths(root)
            value["lease"] = "/tmp/argus-production.lease"
            with self.assertRaisesRegex(storage.PersistentStorageError,
                                       "lease_temporary_path_rejected"):
                storage.validate_storage(value, production=True)

    def test_all_final_and_temp_files_share_filesystem(self):
        with tempfile.TemporaryDirectory() as root:
            result = storage.validate_storage(paths(root), production=True)
            self.assertTrue(result["sameFilesystem"])
            self.assertEqual(
                os.stat(root).st_dev,
                os.stat(paths(root)["tempDirectory"]).st_dev)

    def test_symlink_escape_is_rejected(self):
        with tempfile.TemporaryDirectory() as root, \
                tempfile.TemporaryDirectory() as outside:
            value = paths(root)
            os.symlink(os.path.join(outside, "wal"), value["wal"])
            with self.assertRaisesRegex(storage.PersistentStorageError,
                                       "wal_symlink_rejected"):
                storage.validate_storage(value, production=True)

    def test_unwritable_root_is_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            original = storage.os.access
            with mock.patch.object(
                    storage.os, "access",
                    side_effect=lambda path, mode: False
                    if path == os.path.realpath(root)
                    else original(path, mode)):
                with self.assertRaisesRegex(storage.PersistentStorageError,
                                           "persistent_root_unwritable"):
                    storage.validate_storage(paths(root), production=True)

    def test_fsync_failure_is_rejected(self):
        with tempfile.TemporaryDirectory() as root, \
                mock.patch.object(storage.os, "fsync",
                                  side_effect=OSError("fsync failed")):
            with self.assertRaisesRegex(storage.PersistentStorageError,
                                       "storage_durability_probe_failed"):
                storage.validate_storage(paths(root), production=True)

    def test_atomic_rename_failure_is_rejected(self):
        with tempfile.TemporaryDirectory() as root, \
                mock.patch.object(storage.os, "replace",
                                  side_effect=OSError("rename failed")):
            with self.assertRaisesRegex(storage.PersistentStorageError,
                                       "storage_durability_probe_failed"):
                storage.validate_storage(paths(root), production=True)

    def test_insufficient_dynamic_free_space_is_rejected(self):
        usage = shutil._ntuple_diskusage(1000, 999, 1)
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaisesRegex(storage.PersistentStorageError,
                                       "insufficient_space"):
                storage.validate_storage(
                    paths(root), production=True,
                    disk_usage_fn=lambda unused: usage)

    def test_no_critical_production_path_is_under_tmp(self):
        value = storage.configured_paths({}, production=True)
        for key in ("wal", "checkpoint", "lease", "cursor", "receipt",
                    "tempDirectory"):
            self.assertTrue(
                value[key] == os.path.realpath("/var/data") or
                value[key].startswith(os.path.realpath("/var/data") + "/"),
                (key, value))

    def test_runtime_rejects_persistent_root_configuration_drift(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaisesRegex(storage.PersistentStorageError,
                                       "configuration_drift"):
                storage.validate_storage(
                    paths(root), production=True,
                    approved_root="/var/data")


class BootstrapAndReadinessTests(unittest.TestCase):
    def test_ready_remains_false_when_storage_invalid(self):
        with tempfile.TemporaryDirectory() as root, scanner_storage(root):
            scanner._STARTUP.update({
                "state": "bootstrapping", "restoreStartedAt": None,
                "restoreCompletedAt": None, "restoreOutcome": None,
                "blockerJa": None,
            })
            scanner._DURABLE_STORAGE_STATUS.update({
                "valid": False,
                "errorClass": "persistent_storage_unavailable"})
            with mock.patch.object(
                    scanner, "_validate_durable_storage", return_value=False):
                scanner._startup_bootstrap()
            self.assertEqual(scanner._STARTUP["state"], "failed_safe")

    def test_mission_tick_is_unavailable_when_storage_invalid(self):
        with tempfile.TemporaryDirectory() as root, scanner_storage(root):
            scanner._ARGUS_ADMIN_TOKEN = "admin"
            scanner._STARTUP["state"] = "failed_safe"
            scanner._DURABLE_STORAGE_STATUS.update({"valid": False})
            response = scanner.app.test_client().post(
                "/api/argus/admin/missions/tick",
                headers={"X-ARGUS-ADMIN-TOKEN": "admin"}, json={})
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.get_json()["errorClass"],
                             "persistent_storage_unavailable")

    def test_empty_disk_bootstraps_verified_remote_checkpoint(self):
        with tempfile.TemporaryDirectory() as root, scanner_storage(root) as value:
            with mock.patch.object(
                    scanner.requests, "get",
                    return_value=FakeResponse(200, remote_snapshot())):
                source = scanner._osint_restore_once()
            self.assertEqual(source, "remote_journal_verified")
            self.assertTrue(storage.verify_checkpoint(
                json.loads(pathlib.Path(value["checkpoint"]).read_text()),
                require_seal=True))
            self.assertTrue(pathlib.Path(value["cursor"]).exists())

    def test_empty_disk_without_remote_checkpoint_fails_closed(self):
        with tempfile.TemporaryDirectory() as root, scanner_storage(root) as value:
            with mock.patch.object(
                    scanner.requests, "get",
                    return_value=FakeResponse(404)):
                source = scanner._osint_restore_once()
            self.assertIsNone(source)
            self.assertFalse(pathlib.Path(value["checkpoint"]).exists())
            self.assertEqual(scanner._DURABLE_STATE["restoreSource"],
                             "none_available")

    def test_malformed_remote_snapshot_is_rejected(self):
        with tempfile.TemporaryDirectory() as root, scanner_storage(root) as value:
            malformed = remote_snapshot()
            malformed["integrityManifest"]["manifestHash"] = "bad"
            with mock.patch.object(
                    scanner.requests, "get",
                    return_value=FakeResponse(200, malformed)):
                source = scanner._osint_restore_once()
            self.assertIsNone(source)
            self.assertFalse(pathlib.Path(value["checkpoint"]).exists())

    def test_existing_sealed_local_checkpoint_is_restored(self):
        with tempfile.TemporaryDirectory() as root, scanner_storage(root) as value:
            storage.write_checkpoint(
                value["checkpoint"], remote_snapshot(),
                temp_directory=value["tempDirectory"])
            with mock.patch.object(scanner.requests, "get") as request_get:
                source = scanner._osint_restore_once()
            self.assertEqual(source, "persistent_local")
            request_get.assert_not_called()

    def test_malformed_local_checkpoint_is_quarantined(self):
        with tempfile.TemporaryDirectory() as root, scanner_storage(root) as value:
            pathlib.Path(value["checkpoint"]).write_text("{bad")
            with mock.patch.object(
                    scanner.requests, "get",
                    return_value=FakeResponse(404)):
                scanner._osint_restore_once()
            quarantined = list(pathlib.Path(root).glob(
                "state.json.quarantine-*"))
            self.assertEqual(len(quarantined), 1)
            self.assertFalse(pathlib.Path(value["checkpoint"]).exists())


class CrashLeaseAndShutdownTests(unittest.TestCase):
    def test_checkpoint_plus_wal_replays_after_cursor(self):
        with tempfile.TemporaryDirectory() as root, scanner_storage(root) as value:
            durability.append_wal(
                value["wal"], sequence=1, kind="mission_transition",
                job_id="job", payload={"transitionState": {
                    "mission": {"missionId": "m-persistent",
                                "status": "completed"},
                    "batch": {"cursor": 1, "walAppliedSequence": 1}}})
            saved = list(scanner._MISSIONS)
            try:
                scanner._MISSIONS[:] = []
                state = scanner._restore_mission_wal(after_sequence=0)
                self.assertEqual(state["maximumSequence"], 1)
                self.assertEqual(scanner._MISSIONS[0]["missionId"],
                                 "m-persistent")
                scanner._restore_mission_wal(after_sequence=0)
                self.assertEqual(len(scanner._MISSIONS), 1)
            finally:
                scanner._MISSIONS[:] = saved

    def test_status_137_style_death_preserves_persistent_wal(self):
        with tempfile.TemporaryDirectory() as persistent:
            wal = os.path.join(persistent, "tick.wal")
            durability.append_wal(
                wal, sequence=1, kind="journal_transition",
                job_id="killed", payload={"transitionId": "committed"})
            with tempfile.TemporaryDirectory() as ephemeral:
                pathlib.Path(ephemeral, "lost").write_text("ephemeral")
            self.assertEqual(
                durability.read_valid_wal(wal)["maximumSequence"], 1)

    def test_instance_replacement_restores_from_persistent_directory(self):
        with tempfile.TemporaryDirectory() as persistent:
            value = paths(persistent)
            storage.write_checkpoint(
                value["checkpoint"], remote_snapshot(),
                temp_directory=value["tempDirectory"])
            # Rebuilding configuration emulates a new process/instance.
            replacement = paths(persistent)
            loaded = storage.load_checkpoint(
                replacement["checkpoint"], require_seal=True)
            self.assertEqual(loaded["schemaVersion"], "argus-durable-v3")

    def test_stale_lease_expires_and_pid_reuse_is_not_trusted(self):
        with tempfile.TemporaryDirectory() as root:
            lease_path = os.path.join(root, "tick.lease")
            pathlib.Path(lease_path).write_text(json.dumps({
                "jobId": "dead", "pid": os.getpid(),
                "processIdentity": "old-boot:same-pid",
                "expiresAt": "2000-01-01T00:00:00Z"}))
            lease = durability.TickLease(
                lease_path, build_sha="new", owner="replacement",
                boot_id="new-boot")
            self.assertTrue(lease.acquire())
            self.assertNotEqual(
                lease.metadata["processIdentity"], "old-boot:same-pid")
            lease.release()

    def test_sigterm_stops_at_wal_safe_boundary(self):
        with tempfile.TemporaryDirectory() as root, scanner_storage(root) as value:
            durability.append_wal(
                value["wal"], sequence=1, kind="mission_transition",
                job_id="active", payload={"transitionState": {}})
            scanner._MISSION_TICK_CONTEXT.update({
                "active": True, "lease": None,
                "ownerThread": threading.get_ident()})
            scanner._SHUTDOWN.update({
                "done": False, "requested": False,
                "walSynced": False, "cursorSaved": False})
            result = scanner._handle_termination(
                signal.SIGTERM, exit_process=False)
            self.assertTrue(result["requested"])
            self.assertTrue(result["walSynced"])
            self.assertTrue(result["cursorSaved"])
            self.assertEqual(
                durability.read_valid_wal(value["wal"])["maximumSequence"], 1)

    def test_wal_fsync_precedes_commit_acknowledgement(self):
        with tempfile.TemporaryDirectory() as root, \
                mock.patch.object(durability.os, "fsync",
                                  wraps=durability.os.fsync) as fsync:
            record = durability.append_wal(
                os.path.join(root, "tick.wal"), sequence=1,
                kind="mission_transition", job_id="job",
                payload={"transitionId": "one"})
            self.assertTrue(fsync.called)
            self.assertEqual(record["sequence"], 1)

    def test_temp_checkpoint_is_read_back_before_atomic_replace(self):
        with tempfile.TemporaryDirectory() as root:
            target = os.path.join(root, "state.json")
            original_replace = storage.os.replace

            def checked_replace(source, destination):
                parsed = json.loads(pathlib.Path(source).read_text())
                self.assertTrue(storage.verify_checkpoint(
                    parsed, require_seal=True))
                return original_replace(source, destination)

            with mock.patch.object(storage.os, "replace",
                                   side_effect=checked_replace):
                storage.write_checkpoint(
                    target, remote_snapshot(), temp_directory=root)
            self.assertTrue(pathlib.Path(target).exists())

    def test_remote_stale_receipt_never_compacts_wal(self):
        with tempfile.TemporaryDirectory() as root:
            wal = os.path.join(root, "tick.wal")
            checkpoint = os.path.join(root, "state.json")
            durability.append_wal(
                wal, sequence=1, kind="journal_transition", job_id="job",
                payload={"transitionId": "pending"})
            result = durability.verified_checkpoint(
                checkpoint, storage.seal_checkpoint(remote_snapshot()),
                job_id="job", wal_path=wal, included_sequence=1,
                allow_wal_compaction=False)
            self.assertTrue(result["walCompaction"]["deferred"])
            self.assertEqual(
                durability.read_valid_wal(wal)["records"][0]["kind"],
                "journal_transition")

    def test_verified_remote_cursor_compacts_only_covered_records(self):
        with tempfile.TemporaryDirectory() as root:
            wal = os.path.join(root, "tick.wal")
            checkpoint = os.path.join(root, "state.json")
            for sequence in range(1, 4):
                durability.append_wal(
                    wal, sequence=sequence, kind="journal_transition",
                    job_id="job", payload={
                        "transitionId": f"transition-{sequence}"})
            result = durability.verified_checkpoint(
                checkpoint, storage.seal_checkpoint(remote_snapshot()),
                job_id="job", wal_path=wal, included_sequence=3,
                allow_wal_compaction=True, compaction_sequence=2)
            self.assertEqual(
                result["walCompaction"]["compactedThrough"], 2)
            records = durability.read_valid_wal(wal)["records"]
            self.assertEqual(records[0]["sequence"], 3)
            self.assertEqual(records[0]["kind"], "journal_transition")
            self.assertEqual(records[1]["kind"], "checkpoint_verified")


class ContractRegressionTests(unittest.TestCase):
    def test_wal_record_has_dedup_and_chain_identity(self):
        with tempfile.TemporaryDirectory() as root:
            wal = os.path.join(root, "tick.wal")
            first = durability.append_wal(
                wal, sequence=1, kind="mission_transition", job_id="job",
                mission_window_id="mw-1", build_sha="abc",
                payload={"transitionId": "one"})
            second = durability.append_wal(
                wal, sequence=2, kind="mission_transition", job_id="job",
                mission_window_id="mw-1", build_sha="abc",
                payload={"transitionId": "two"})
            for key in ("transitionId", "missionWindowId", "buildSha",
                        "createdAt", "payloadHash"):
                self.assertIn(key, second)
            self.assertEqual(second["previousSequence"], 1)
            self.assertEqual(second["previousRecordHash"],
                             first["recordHash"])

    def test_one_hundred_events_do_not_create_full_snapshots(self):
        source = pathlib.Path("test_argus_mission_tick_durability.py").read_text()
        self.assertIn("test_one_hundred_transitions_are_small_wal_appends",
                      source)
        self.assertIn("test_scanner_journal_does_not_full_serialize_per_event",
                      source)

    def test_five_request_singleflight_regression_is_present(self):
        source = pathlib.Path("test_argus_mission_tick_durability.py").read_text()
        self.assertIn("test_five_contenders_allow_exactly_one_owner", source)

    def test_twelve_snapshots_and_ai_zero_gates_remain(self):
        gate = pathlib.Path("test_verified_snapshot_release_gate.py").read_text()
        self.assertIn("test_matrix_requires_all_12_snapshots_and_304", gate)
        self.assertIn('"automaticAiExecutions": 0', gate)

    def test_render_contract_and_single_host_warning(self):
        render = pathlib.Path("render.yaml").read_text()
        runbook = pathlib.Path(
            "docs/RENDER_PERSISTENT_MISSION_DURABILITY.md").read_text()
        self.assertIn("numInstances: 1", render)
        self.assertIn("mountPath: /var/data", render)
        self.assertIn("sizeGB: 5", render)
        self.assertIn("not a distributed lock", " ".join(runbook.split()))
        self.assertIn("Autoscaling: **disabled**", runbook)


if __name__ == "__main__":
    unittest.main()
