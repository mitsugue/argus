"""Persistent mission durability acceptance tests (stdlib, no provider calls)."""
from __future__ import annotations

import contextlib
import copy
import hashlib
import json
import os
import pathlib
import shutil
import signal
import subprocess
import tempfile
import threading
import tracemalloc
import types
import unittest
from unittest import mock

import argus_persistent_storage as storage
import argus_checkpoint_v2
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
        "ARGUS_REMOTE_RECEIPT_QUEUE_FILE": os.path.join(
            root, "receipt-queue.json"),
        "ARGUS_CHECKPOINT_TEMP_DIR": root,
    }, production=True)


def validate_simulated_disk(value, **kwargs):
    return storage.validate_storage(
        value, production=True, allow_temporary_root_for_test=True, **kwargs)


def remote_snapshot(wal_sequence=0):
    section = argus_remote_journal.snapshot_journal_section(
        events=[], meta={}, now_iso="2026-07-25T00:00:00Z")
    return {
        "schemaVersion": "argus-durable-v3",
        "generatedAt": "2026-07-25T00:00:00Z",
        "missionTickDurability": {
            "schemaVersion": "argus-mission-batch-v1",
            "walAppliedSequence": int(wal_sequence),
            "remoteWalAppliedSequence": int(wal_sequence),
        },
        **section,
    }


def write_legacy_file_seal(path, *, source_path="/tmp/legacy.json"):
    checkpoint = pathlib.Path(path)
    manifest = {
        "schemaVersion": storage.LEGACY_FILE_SEAL_SCHEMA,
        "algorithm": "sha256",
        "checkpointSchemaVersion": "argus-durable-v3",
        "checkpointPath": os.path.abspath(str(checkpoint)),
        "sourcePath": source_path,
        "sourceMtimeUtc": "2026-07-26T00:00:00Z",
        "createdAt": "2026-07-26T00:01:00Z",
        "fileBytes": checkpoint.stat().st_size,
        "fileSha256": storage._stream_sha256(str(checkpoint)),
    }
    manifest["recordHash"] = hashlib.sha256(
        storage._canonical(manifest)).hexdigest()
    pathlib.Path(
        str(checkpoint) + storage.LEGACY_FILE_SEAL_SUFFIX
    ).write_text(json.dumps(manifest), encoding="utf-8")
    return manifest


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
        "receiptQueue": scanner._REMOTE_RECEIPT_QUEUE_FILE,
        "receiptQueueState": copy.deepcopy(scanner._REMOTE_RECEIPT_QUEUE),
        "persist": dict(scanner._OSINT_PERSIST_STATE),
        "durable": dict(scanner._DURABLE_STATE),
        "storageStatus": dict(scanner._DURABLE_STORAGE_STATUS),
        "batch": dict(scanner._MISSION_BATCH_STATE),
        "remoteCycle": dict(scanner._REMOTE_CYCLE),
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
    scanner._REMOTE_RECEIPT_QUEUE_FILE = configured["receiptQueue"]
    scanner._REMOTE_RECEIPT_QUEUE = \
        scanner.argus_remote_receipt_queue.empty_store()
    scanner._OSINT_PERSIST_STATE.clear()
    scanner._OSINT_PERSIST_STATE.update({"restored": False})
    scanner._DURABLE_STATE.clear()
    scanner._DURABLE_STATE.update({
        "schemaVersion": "argus-durable-v3",
        "lastWriteAt": None, "lastRestoreAt": None,
        "integrityStatus": "unknown", "lastKnownGoodAt": None,
        "restoreSource": None,
    })
    scanner._REMOTE_CYCLE.clear()
    scanner._REMOTE_CYCLE.update({
        "remoteCommitSha": None, "committedAt": None,
        "readBackAt": None, "readBackVerified": False,
        "walReadBackVerified": False,
        "expectedHash": None, "actualHash": None,
        "remoteWalAppliedSequence": 0, "verifiedWalSequence": 0,
        "compactReceiptHash": None, "pendingCount": 0,
        "acknowledgedCount": 0, "errorClass": None,
        "walErrorClass": None,
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
        scanner._REMOTE_RECEIPT_QUEUE_FILE = saved["receiptQueue"]
        scanner._REMOTE_RECEIPT_QUEUE = saved["receiptQueueState"]
        scanner._OSINT_PERSIST_STATE.clear()
        scanner._OSINT_PERSIST_STATE.update(saved["persist"])
        scanner._DURABLE_STATE.clear()
        scanner._DURABLE_STATE.update(saved["durable"])
        scanner._DURABLE_STORAGE_STATUS.clear()
        scanner._DURABLE_STORAGE_STATUS.update(saved["storageStatus"])
        scanner._MISSION_BATCH_STATE.clear()
        scanner._MISSION_BATCH_STATE.update(saved["batch"])
        scanner._REMOTE_CYCLE.clear()
        scanner._REMOTE_CYCLE.update(saved["remoteCycle"])
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
                validate_simulated_disk(value)

    def test_production_rejects_tmp_checkpoint(self):
        with tempfile.TemporaryDirectory() as root:
            value = paths(root)
            value["checkpoint"] = "/tmp/argus-production.json"
            with self.assertRaisesRegex(storage.PersistentStorageError,
                                       "checkpoint_temporary_path_rejected"):
                validate_simulated_disk(value)

    def test_production_rejects_tmp_lease(self):
        with tempfile.TemporaryDirectory() as root:
            value = paths(root)
            value["lease"] = "/tmp/argus-production.lease"
            with self.assertRaisesRegex(storage.PersistentStorageError,
                                       "lease_temporary_path_rejected"):
                validate_simulated_disk(value)

    def test_all_final_and_temp_files_share_filesystem(self):
        with tempfile.TemporaryDirectory() as root:
            result = validate_simulated_disk(paths(root))
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
                validate_simulated_disk(value)

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
                    validate_simulated_disk(paths(root))

    def test_fsync_failure_is_rejected(self):
        with tempfile.TemporaryDirectory() as root, \
                mock.patch.object(storage.os, "fsync",
                                  side_effect=OSError("fsync failed")):
            with self.assertRaisesRegex(storage.PersistentStorageError,
                                       "storage_durability_probe_failed"):
                validate_simulated_disk(paths(root))

    def test_atomic_rename_failure_is_rejected(self):
        with tempfile.TemporaryDirectory() as root, \
                mock.patch.object(storage.os, "replace",
                                  side_effect=OSError("rename failed")):
            with self.assertRaisesRegex(storage.PersistentStorageError,
                                       "storage_durability_probe_failed"):
                validate_simulated_disk(paths(root))

    def test_insufficient_dynamic_free_space_is_rejected(self):
        usage = shutil._ntuple_diskusage(1000, 999, 1)
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaisesRegex(storage.PersistentStorageError,
                                       "insufficient_space"):
                validate_simulated_disk(
                    paths(root),
                    disk_usage_fn=lambda unused: usage)

    def test_no_critical_production_path_is_under_tmp(self):
        value = storage.configured_paths({}, production=True)
        for key in ("wal", "checkpoint", "lease", "cursor", "receipt",
                    "receiptQueue",
                    "tempDirectory"):
            self.assertTrue(
                value[key] == os.path.realpath("/var/data") or
                value[key].startswith(os.path.realpath("/var/data") + "/"),
                (key, value))


class CheckpointV2Stage1IntegrationTests(unittest.TestCase):
    def test_stage1_dual_write_is_non_authoritative_and_verified(self):
        with tempfile.TemporaryDirectory() as root, \
                mock.patch.object(scanner, "_CHECKPOINT_V2_STAGE1_ENABLED", True), \
                mock.patch.object(scanner, "_CHECKPOINT_V2_ROOT",
                                  os.path.join(root, "v2")):
            blob = storage.seal_checkpoint(remote_snapshot())
            expected = copy.deepcopy(blob)
            legacy_result = {"verified": True, "snapshotHash": "legacy-hash"}
            result = scanner._checkpoint_v2_dual_write(blob, legacy_result)
            self.assertEqual(result["state"], "stage1_dual_write")
            self.assertTrue(result["lastWriteVerified"])
            self.assertTrue(legacy_result["verified"])
            self.assertEqual(blob, {})
            self.assertEqual(
                argus_checkpoint_v2.restore_generation(
                    os.path.join(root, "v2"))["snapshot"], expected)

    def test_stage1_v2_failure_does_not_turn_legacy_success_into_failure(self):
        with mock.patch.object(scanner, "_CHECKPOINT_V2_STAGE1_ENABLED", True), \
                mock.patch.object(
                    argus_checkpoint_v2, "write_generation",
                    side_effect=argus_checkpoint_v2.CheckpointV2Error(
                        "checkpoint_v2_total_limit_exceeded")):
            legacy_result = {"verified": True, "snapshotHash": "legacy-hash"}
            result = scanner._checkpoint_v2_dual_write(
                storage.seal_checkpoint(remote_snapshot()), legacy_result)
            self.assertEqual(result["state"], "validation_failed")
            self.assertEqual(result["lastErrorClass"],
                             "checkpoint_v2_total_limit_exceeded")
            self.assertTrue(legacy_result["verified"])

    def test_all_v2_validation_failures_are_structured_and_legacy_isolated(self):
        classifications = (
            "checkpoint_v2_writer_busy",
            "checkpoint_v2_total_limit_exceeded",
            "checkpoint_v2_database_limit_exceeded",
            "checkpoint_v2_row_too_large",
            "checkpoint_v2_disk_reserve_insufficient",
            "checkpoint_v2_transaction_failed",
            "checkpoint_v2_fsync_failed",
            "checkpoint_v2_manifest_promotion_failed",
            "checkpoint_v2_database_hash_mismatch",
            "checkpoint_v2_row_hash_mismatch",
            "checkpoint_v2_isolated_restore_failed",
        )
        saved = copy.deepcopy(scanner._CHECKPOINT_V2_STAGE1_CONTROL)
        try:
            for classification in classifications:
                with self.subTest(classification=classification), \
                        mock.patch.object(
                            scanner, "_CHECKPOINT_V2_STAGE1_ENABLED", True), \
                        mock.patch.object(
                            argus_checkpoint_v2, "write_generation",
                            side_effect=argus_checkpoint_v2.CheckpointV2Error(
                                classification, phase="injected")):
                    legacy_result = {
                        "verified": True, "snapshotHash": "legacy-hash",
                        "walCompaction": {"verified": True}}
                    result = scanner._checkpoint_v2_dual_write(
                        storage.seal_checkpoint(remote_snapshot()),
                        legacy_result)
                    self.assertEqual(result["state"], "validation_failed")
                    self.assertEqual(result["lastErrorClass"], classification)
                    self.assertEqual(result["lastErrorDetails"],
                                     {"phase": "injected"})
                    self.assertFalse(result["formalSoakArmed"])
                    self.assertTrue(result["authorityPromotionBlocked"])
                    self.assertTrue(legacy_result["verified"])
                    self.assertTrue(
                        legacy_result["walCompaction"]["verified"])
        finally:
            scanner._CHECKPOINT_V2_STAGE1_CONTROL.clear()
            scanner._CHECKPOINT_V2_STAGE1_CONTROL.update(saved)

    def test_runtime_rejects_persistent_root_configuration_drift(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaisesRegex(storage.PersistentStorageError,
                                       "configuration_drift"):
                validate_simulated_disk(
                    paths(root),
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

    def test_legacy_checkpoint_with_matching_file_seal_is_restored_once(self):
        with tempfile.TemporaryDirectory() as root, scanner_storage(root) as value:
            checkpoint = pathlib.Path(value["checkpoint"])
            checkpoint.write_text(
                json.dumps(remote_snapshot()), encoding="utf-8")
            write_legacy_file_seal(checkpoint)
            with mock.patch.object(scanner.requests, "get") as request_get:
                source = scanner._osint_restore_once()
            self.assertEqual(source, "persistent_local_legacy_verified")
            self.assertEqual(
                scanner._DURABLE_STATE["legacyCheckpointMigration"]["status"],
                "verified")
            self.assertTrue(
                scanner._DURABLE_STATE["legacyCheckpointMigration"][
                    "requiresSealedRewrite"])
            self.assertEqual(scanner._DURABLE_STATE["missionWalReplayed"], 0)
            request_get.assert_not_called()

    def test_unsealed_checkpoint_without_legacy_file_seal_is_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            checkpoint = pathlib.Path(root, "state.json")
            checkpoint.write_text(
                json.dumps(remote_snapshot()), encoding="utf-8")
            with self.assertRaisesRegex(
                    storage.PersistentStorageError,
                    "legacy_checkpoint_seal_missing"):
                storage.load_checkpoint(
                    str(checkpoint), require_seal=True,
                    allow_legacy_file_seal=True)

    def test_legacy_file_seal_rejects_modified_checkpoint(self):
        with tempfile.TemporaryDirectory() as root:
            checkpoint = pathlib.Path(root, "state.json")
            checkpoint.write_text(
                json.dumps(remote_snapshot()), encoding="utf-8")
            write_legacy_file_seal(checkpoint)
            checkpoint.write_text(
                json.dumps({**remote_snapshot(), "tampered": True}),
                encoding="utf-8")
            with self.assertRaisesRegex(
                    storage.PersistentStorageError,
                    "legacy_checkpoint_file_hash_mismatch"):
                storage.load_checkpoint(
                    str(checkpoint), require_seal=True,
                    allow_legacy_file_seal=True)

    def test_legacy_file_seal_is_bound_to_exact_checkpoint_path(self):
        with tempfile.TemporaryDirectory() as root:
            checkpoint = pathlib.Path(root, "state.json")
            checkpoint.write_text(
                json.dumps(remote_snapshot()), encoding="utf-8")
            manifest = write_legacy_file_seal(checkpoint)
            manifest["checkpointPath"] = str(
                pathlib.Path(root, "different.json"))
            unsigned = {
                key: value for key, value in manifest.items()
                if key != "recordHash"
            }
            manifest["recordHash"] = hashlib.sha256(
                storage._canonical(unsigned)).hexdigest()
            pathlib.Path(
                str(checkpoint) + storage.LEGACY_FILE_SEAL_SUFFIX
            ).write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(
                    storage.PersistentStorageError,
                    "legacy_checkpoint_seal_invalid"):
                storage.load_checkpoint(
                    str(checkpoint), require_seal=True,
                    allow_legacy_file_seal=True)

    def test_legacy_checkpoint_symlink_is_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            target = pathlib.Path(root, "target.json")
            target.write_text(json.dumps(remote_snapshot()), encoding="utf-8")
            checkpoint = pathlib.Path(root, "state.json")
            checkpoint.symlink_to(target)
            with self.assertRaisesRegex(
                    storage.PersistentStorageError,
                    "local_checkpoint_symlink_rejected"):
                storage.load_checkpoint(
                    str(checkpoint), require_seal=True,
                    allow_legacy_file_seal=True)

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
    def test_124_mib_class_checkpoint_has_bounded_serialization_memory(self):
        with tempfile.TemporaryDirectory() as root:
            target = os.path.join(root, "state.json")
            shared_mebibyte = "x" * (1024 * 1024)
            value = storage.seal_checkpoint({
                "schemaVersion": "argus-durable-v3",
                "blocks": [shared_mebibyte] * 124,
            })
            tracemalloc.start()
            try:
                result = storage.atomic_write_json(
                    target, value, temp_directory=root,
                    validator=lambda row: storage.verify_checkpoint(
                        row, require_seal=True))
                _, peak = tracemalloc.get_traced_memory()
            finally:
                tracemalloc.stop()
            self.assertGreater(result["bytes"], 124 * 1024 * 1024)
            self.assertLess(peak, 24 * 1024 * 1024)
            self.assertTrue(result["readBackVerified"])

    def test_maximum_checkpoint_guard_preserves_last_known_good(self):
        with tempfile.TemporaryDirectory() as root:
            target = pathlib.Path(root, "state.json")
            target.write_text('{"verified":"old"}', encoding="utf-8")
            with self.assertRaisesRegex(
                    storage.PersistentStorageError,
                    "checkpoint_maximum_bytes_exceeded"):
                storage.atomic_write_json(
                    str(target), {"value": "x" * 2048},
                    temp_directory=root, maximum_bytes=1024)
            self.assertEqual(target.read_text(), '{"verified":"old"}')
            self.assertEqual(list(pathlib.Path(root).glob(
                "state.json.*.v1338-tmp")), [])

    def test_oversized_single_scalar_is_rejected_before_encoding(self):
        with tempfile.TemporaryDirectory() as root:
            target = pathlib.Path(root, "state.json")
            target.write_text('{"verified":"old"}', encoding="utf-8")
            with self.assertRaisesRegex(
                    storage.PersistentStorageError,
                    "checkpoint_json_scalar_too_large"):
                storage.atomic_write_json(
                    str(target),
                    {"value": "x" *
                     (storage.MAXIMUM_JSON_SCALAR_CHARS + 1)},
                    temp_directory=root)
            self.assertEqual(target.read_text(), '{"verified":"old"}')
            self.assertEqual(list(pathlib.Path(root).glob(
                "state.json.*.v1338-tmp")), [])

    def test_checkpoint_writer_lock_rejects_concurrent_writer(self):
        with tempfile.TemporaryDirectory() as root:
            target = os.path.join(root, "state.json")
            lock = open(target + ".writer.lock", "a+b")
            try:
                storage.fcntl.flock(
                    lock.fileno(), storage.fcntl.LOCK_EX |
                    storage.fcntl.LOCK_NB)
                with self.assertRaisesRegex(
                        storage.PersistentStorageError,
                        "checkpoint_writer_busy"):
                    storage.atomic_write_json(
                        target, {"value": 1}, temp_directory=root)
            finally:
                storage.fcntl.flock(lock.fileno(), storage.fcntl.LOCK_UN)
                lock.close()

    def test_pre_hotfix_temp_is_retained_as_incident_evidence(self):
        with tempfile.TemporaryDirectory() as root:
            final = pathlib.Path(root, "state.json")
            abandoned = pathlib.Path(
                root, f"state.json.4242.{'a' * 32}.tmp")
            abandoned.write_bytes(b"do-not-load")
            before = abandoned.stat()
            result = storage.reconcile_abandoned_checkpoint_temps(
                str(final), temp_directory=root, cleanup=True,
                now=before.st_mtime + 30 * 24 * 60 * 60,
                owner_probe=lambda *args, **kwargs: False)
            after = abandoned.stat()
            self.assertEqual(result["removedCount"], 0)
            self.assertEqual(result["retainedIncidentEvidenceCount"], 1)
            self.assertEqual(result["entries"][0]["classification"],
                             "retained_incident_evidence")
            self.assertFalse(result["entries"][0]["contentOpenAttempted"])
            self.assertEqual((before.st_dev, before.st_ino, before.st_mtime_ns),
                             (after.st_dev, after.st_ino, after.st_mtime_ns))

    def test_incident_evidence_sparse_file_is_never_opened(self):
        with tempfile.TemporaryDirectory() as root:
            final = pathlib.Path(root, "state.json")
            evidence = pathlib.Path(
                root, f"state.json.4242.{'b' * 32}.tmp")
            with evidence.open("wb") as handle:
                handle.truncate(2 * 1024 * 1024 * 1024)
            before = evidence.stat()
            with mock.patch.object(
                    storage.os, "open",
                    side_effect=AssertionError("incident content opened")):
                result = storage.reconcile_abandoned_checkpoint_temps(
                    str(final), temp_directory=root, cleanup=True,
                    owner_probe=lambda *args, **kwargs: False)
            after = evidence.stat()
            self.assertEqual(result["retainedIncidentEvidenceCount"], 1)
            self.assertFalse(result["entries"][0]["contentOpenAttempted"])
            self.assertEqual(
                (before.st_dev, before.st_ino, before.st_size,
                 before.st_mtime_ns, before.st_atime_ns),
                (after.st_dev, after.st_ino, after.st_size,
                 after.st_mtime_ns, after.st_atime_ns))

    def test_post_hotfix_temp_cleanup_requires_age_and_ownership_proof(self):
        with tempfile.TemporaryDirectory() as root:
            final = pathlib.Path(root, "state.json")
            abandoned = pathlib.Path(
                root, f"state.json.4242.{'a' * 32}.v1338-tmp")
            abandoned.write_bytes(b"bounded-post-hotfix-temp")
            written_at = abandoned.stat().st_mtime
            fresh = storage.reconcile_abandoned_checkpoint_temps(
                str(final), temp_directory=root, cleanup=True,
                now=written_at + storage.POST_HOTFIX_TEMP_RETENTION_SECONDS - 1,
                owner_probe=lambda *args, **kwargs: False)
            self.assertEqual(fresh["removedCount"], 0)
            self.assertEqual(fresh["entries"][0]["classification"],
                             "retained_post_hotfix_temp")
            old = storage.reconcile_abandoned_checkpoint_temps(
                str(final), temp_directory=root, cleanup=True,
                now=written_at + storage.POST_HOTFIX_TEMP_RETENTION_SECONDS + 1,
                owner_probe=lambda *args, **kwargs: False)
            self.assertEqual(old["removedCount"], 1)
            self.assertFalse(abandoned.exists())

    def test_absent_linux_writer_pid_proves_temp_has_no_owner(self):
        with mock.patch.object(
                storage.os.path, "isdir",
                side_effect=lambda path: path == "/proc"), \
                mock.patch.object(storage.os.path, "exists",
                                  return_value=False):
            self.assertFalse(storage._writer_pid_has_open_inode(
                4242, device=1, inode=2))

    def test_interrupted_writer_temp_is_reconciled_without_loading(self):
        with tempfile.TemporaryDirectory() as root, \
                mock.patch.object(storage.os, "replace",
                                  side_effect=KeyboardInterrupt):
            target = os.path.join(root, "state.json")
            with self.assertRaises(KeyboardInterrupt):
                storage.atomic_write_json(
                    target, {"value": "partial"}, temp_directory=root)
            leftovers = list(pathlib.Path(root).glob(
                "state.json.*.v1338-tmp"))
            self.assertEqual(len(leftovers), 1)
            written_at = leftovers[0].stat().st_mtime
            result = storage.reconcile_abandoned_checkpoint_temps(
                target, temp_directory=root, cleanup=True,
                now=written_at + storage.POST_HOTFIX_TEMP_RETENTION_SECONDS + 1,
                owner_probe=lambda *args, **kwargs: False)
            self.assertEqual(result["removedCount"], 1)

    def test_real_checkpoint_memory_probe_scenarios(self):
        helper = pathlib.Path(__file__).parent / "scripts" / \
            "checkpoint_memory_probe.py"
        reports = {}
        for mode in ("production", "oversized", "interrupted", "repeated"):
            completed = subprocess.run(
                [sys.executable, str(helper), "--mode", mode],
                cwd=str(pathlib.Path(__file__).parent), text=True,
                capture_output=True, check=True, timeout=180)
            reports[mode] = json.loads(completed.stdout)
        self.assertGreater(reports["production"]["writtenBytes"],
                           124 * 1024 * 1024)
        self.assertLess(reports["production"]["writtenBytes"],
                        storage.DEFAULT_MAXIMUM_CHECKPOINT_BYTES)
        self.assertEqual(reports["production"]["fullSizeBuffers"], 0)
        self.assertEqual(reports["oversized"]["classification"],
                         "checkpoint_maximum_bytes_exceeded")
        self.assertLessEqual(reports["oversized"]["writtenBytes"],
                             storage.DEFAULT_MAXIMUM_CHECKPOINT_BYTES)
        self.assertTrue(reports["oversized"]["previousCheckpointPreserved"])
        self.assertEqual(reports["oversized"]["tempCount"], 0)
        self.assertEqual(reports["interrupted"]["classification"],
                         "interrupted_serialization")
        self.assertEqual(reports["interrupted"]["tempCount"], 1)
        self.assertLess(reports["repeated"]["rssGrowthBytes"],
                        32 * 1024 * 1024)

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

    def test_compact_receipt_is_fsynced_then_compacts_exact_cursor_once(self):
        with tempfile.TemporaryDirectory() as root, scanner_storage(root) as value:
            for sequence in range(1, 4):
                durability.append_wal(
                    value["wal"], sequence=sequence,
                    kind="journal_transition", job_id="job",
                    payload={"transitionId": f"transition-{sequence}"})
            remote = remote_snapshot(wal_sequence=2)
            compact = argus_remote_journal.compact_readback_snapshot(remote)
            manifest_hash = compact["integrityManifest"]["manifestHash"]
            scanner._REMOTE_CYCLE.update({
                "remoteCommitSha": "a" * 40,
                "committedAt": "2026-07-25T00:01:00Z",
                "expectedHash": manifest_hash,
                "verifiedWalSequence": 0,
            })

            ack = scanner._remote_readback_ack(
                now_iso="2026-07-25T00:02:00Z", blob=compact)
            self.assertEqual(ack["verificationStatus"], "verified")
            self.assertTrue(scanner._REMOTE_CYCLE["readBackVerified"])
            self.assertTrue(scanner._REMOTE_CYCLE["walReadBackVerified"])
            self.assertEqual(
                scanner._REMOTE_CYCLE["remoteWalAppliedSequence"], 2)
            self.assertEqual(scanner._REMOTE_CYCLE["verifiedWalSequence"], 2)
            persisted = json.loads(pathlib.Path(value["receipt"]).read_text())
            self.assertTrue(durability.verify_remote_receipt(persisted))
            self.assertEqual(scanner._verified_persistent_wal_sequence(), 2)

            first = scanner._osint_persist()
            self.assertTrue(first["verified"])
            self.assertEqual(first["walCompaction"]["compactedThrough"], 2)
            records = durability.read_valid_wal(value["wal"])["records"]
            self.assertEqual(
                len([row for row in records
                     if row["kind"] == "checkpoint_verified"]), 1)

            duplicate = scanner._osint_persist()
            self.assertTrue(duplicate["walCompaction"]["duplicate"])
            records = durability.read_valid_wal(value["wal"])["records"]
            self.assertEqual(
                len([row for row in records
                     if row["kind"] == "checkpoint_verified"]), 1)

    def test_legacy_compact_receipt_verifies_journal_but_not_wal_cursor(self):
        with tempfile.TemporaryDirectory() as root, scanner_storage(root):
            remote = remote_snapshot()
            remote.pop("missionTickDurability")
            compact = argus_remote_journal.compact_readback_snapshot(remote)
            scanner._REMOTE_CYCLE.update({
                "remoteCommitSha": "a" * 40,
                "committedAt": "2026-07-25T00:01:00Z",
                "expectedHash":
                    compact["integrityManifest"]["manifestHash"],
            })
            ack = scanner._remote_readback_ack(
                now_iso="2026-07-25T00:02:00Z", blob=compact)
            self.assertEqual(ack["verificationStatus"], "verified")
            self.assertTrue(scanner._REMOTE_CYCLE["readBackVerified"])
            self.assertFalse(
                scanner._REMOTE_CYCLE["walReadBackVerified"])
            self.assertEqual(
                scanner._REMOTE_CYCLE["walErrorClass"],
                "remote_wal_sequence_missing")
            self.assertEqual(scanner._verified_persistent_wal_sequence(), 0)

    def test_commit_receipt_fsyncs_intent_without_checkpoint_and_fails_closed(self):
        old_token = scanner._ARGUS_ADMIN_TOKEN
        old_cycle = dict(scanner._REMOTE_CYCLE)
        old_queue = copy.deepcopy(scanner._REMOTE_RECEIPT_QUEUE)
        scanner._ARGUS_ADMIN_TOKEN = "test-admin"
        try:
            order = []
            with mock.patch.object(
                    scanner, "_persist_remote_receipt_queue",
                    side_effect=lambda *args, **kwargs:
                    order.append("intent") or {"verified": True}), \
                    mock.patch.object(
                        scanner, "_backend_exact_sha", return_value="c" * 40), \
                    mock.patch.object(
                        scanner, "_osint_persist",
                        side_effect=lambda:
                        order.append("checkpoint") or {"verified": True}):
                response = scanner.app.test_client().post(
                    "/api/argus/admin/remote-journal/commit-receipt",
                    headers={"X-ARGUS-ADMIN-TOKEN": "test-admin",
                             "Idempotency-Key": "test-receipt-0001"},
                    json={"remoteCommitSha": "a" * 40,
                          "expectedHash": "b" * 16,
                          "backendBuildSha": "c" * 40,
                          "targetWalSequence": 42})
            self.assertEqual(response.status_code, 202)
            self.assertEqual(order, ["intent"])

            with mock.patch.object(
                    scanner, "_persist_remote_receipt_queue",
                    side_effect=OSError("fsync failed")), \
                    mock.patch.object(
                        scanner, "_backend_exact_sha", return_value="c" * 40), \
                    mock.patch.object(scanner, "_osint_persist") as checkpoint:
                response = scanner.app.test_client().post(
                    "/api/argus/admin/remote-journal/commit-receipt",
                    headers={"X-ARGUS-ADMIN-TOKEN": "test-admin",
                             "Idempotency-Key": "test-receipt-0002"},
                    json={"remoteCommitSha": "c" * 40,
                          "expectedHash": "d" * 16,
                          "backendBuildSha": "c" * 40,
                          "targetWalSequence": 43})
            self.assertEqual(response.status_code, 503)
            checkpoint.assert_not_called()
        finally:
            scanner._ARGUS_ADMIN_TOKEN = old_token
            scanner._REMOTE_CYCLE.clear()
            scanner._REMOTE_CYCLE.update(old_cycle)
            scanner._REMOTE_RECEIPT_QUEUE = old_queue

    def test_mismatch_tamper_and_sequence_regression_never_advance_wal(self):
        with tempfile.TemporaryDirectory() as root, scanner_storage(root) as value:
            remote = remote_snapshot(wal_sequence=4)
            compact = argus_remote_journal.compact_readback_snapshot(remote)
            manifest_hash = compact["integrityManifest"]["manifestHash"]
            scanner._REMOTE_CYCLE.update({
                "remoteCommitSha": "b" * 40,
                "committedAt": "2026-07-25T00:01:00Z",
                "expectedHash": "f" * 16,
                "verifiedWalSequence": 3,
            })
            scanner._remote_readback_ack(
                now_iso="2026-07-25T00:02:00Z", blob=compact)
            self.assertFalse(scanner._REMOTE_CYCLE["readBackVerified"])
            self.assertEqual(
                scanner._REMOTE_CYCLE["errorClass"],
                "receipt_hash_mismatch")
            self.assertEqual(scanner._verified_persistent_wal_sequence(), 0)

            tampered = json.loads(json.dumps(compact))
            tampered["missionTickDurability"][
                "remoteWalAppliedSequence"] = 999
            self.assertIsNone(scanner._remote_readback_ack(
                now_iso="2026-07-25T00:03:00Z", blob=tampered))
            self.assertEqual(
                scanner._REMOTE_CYCLE["errorClass"],
                "compact_receipt_invalid")

            scanner._REMOTE_CYCLE.update({
                "expectedHash": manifest_hash,
                "actualHash": manifest_hash,
                "verifiedWalSequence": 5,
                "remoteWalAppliedSequence": 5,
                "readBackVerified": True,
                "walReadBackVerified": True,
                "compactReceiptHash": "prior-proof",
                "errorClass": None, "walErrorClass": None,
            })
            scanner._remote_readback_ack(
                now_iso="2026-07-25T00:04:00Z", blob=compact)
            self.assertTrue(scanner._REMOTE_CYCLE["readBackVerified"])
            self.assertFalse(
                scanner._REMOTE_CYCLE["walReadBackVerified"])
            self.assertEqual(
                scanner._REMOTE_CYCLE["verifiedWalSequence"], 5)
            self.assertEqual(
                scanner._REMOTE_CYCLE["walErrorClass"],
                "remote_wal_sequence_regression")
            self.assertEqual(scanner._verified_persistent_wal_sequence(), 0)

    def test_status_137_restores_newer_verified_receipt_before_wal_replay(self):
        with tempfile.TemporaryDirectory() as root, scanner_storage(root) as value:
            checkpoint = remote_snapshot(wal_sequence=1)
            checkpoint["remoteJournalCycle"] = {
                "remoteCommitSha": "a" * 40,
                "committedAt": "2026-07-25T00:01:00Z",
                "expectedHash": "1" * 16,
                "actualHash": None,
                "readBackVerified": False,
                "remoteWalAppliedSequence": 0,
                "verifiedWalSequence": 0,
                "compactReceiptHash": None,
                "errorClass": None,
            }
            storage.write_checkpoint(
                value["checkpoint"], checkpoint,
                temp_directory=value["tempDirectory"])
            receipt = durability.remote_receipt_record(
                saved_at="2026-07-25T00:03:00Z",
                remote_commit_sha="b" * 40,
                committed_at="2026-07-25T00:02:00Z",
                expected_hash="2" * 16, actual_hash="2" * 16,
                read_back_at="2026-07-25T00:03:00Z",
                read_back_verified=True,
                remote_wal_applied_sequence=2,
                verified_wal_sequence=2,
                compact_receipt_hash="compact-proof",
                error_class=None)
            storage.atomic_write_json(
                value["receipt"], receipt,
                temp_directory=value["tempDirectory"],
                validator=durability.verify_remote_receipt)
            for sequence in (2, 3):
                durability.append_wal(
                    value["wal"], sequence=sequence,
                    kind="journal_transition", job_id="restored",
                    payload={"transitionId": f"restored-{sequence}"})

            source = scanner._osint_restore_once()
            self.assertEqual(source, "persistent_local")
            self.assertTrue(scanner._REMOTE_CYCLE["readBackVerified"])
            self.assertEqual(
                scanner._REMOTE_CYCLE["verifiedWalSequence"], 2)
            self.assertEqual(
                scanner._MISSION_BATCH_STATE["walAppliedSequence"], 3)
            self.assertIn(
                scanner._DURABLE_STATE["remoteReceiptRestore"],
                ("restored", "duplicate"))
            after_restart = scanner._osint_persist()
            self.assertEqual(
                after_restart["walCompaction"]["compactedThrough"], 2)

    def test_stale_and_tampered_persistent_receipts_are_ignored(self):
        with tempfile.TemporaryDirectory() as root, scanner_storage(root) as value:
            scanner._REMOTE_CYCLE.update({
                "remoteCommitSha": "c" * 40,
                "committedAt": "2026-07-25T00:05:00Z",
                "expectedHash": "3" * 16,
                "actualHash": "3" * 16,
                "readBackVerified": True,
                "remoteWalAppliedSequence": 7,
                "verifiedWalSequence": 7,
                "compactReceiptHash": "current-proof",
            })
            stale = durability.remote_receipt_record(
                saved_at="2026-07-25T00:03:00Z",
                remote_commit_sha="b" * 40,
                committed_at="2026-07-25T00:02:00Z",
                expected_hash="2" * 16, actual_hash="2" * 16,
                read_back_at="2026-07-25T00:03:00Z",
                read_back_verified=True,
                remote_wal_applied_sequence=6,
                verified_wal_sequence=6,
                compact_receipt_hash="stale-proof",
                error_class=None)
            storage.atomic_write_json(
                value["receipt"], stale,
                temp_directory=value["tempDirectory"],
                validator=durability.verify_remote_receipt)
            self.assertEqual(
                scanner._restore_persistent_remote_receipt()["status"],
                "stale")
            self.assertEqual(scanner._REMOTE_CYCLE["verifiedWalSequence"], 7)

            tampered = dict(stale)
            tampered["verifiedWalSequence"] = 99
            pathlib.Path(value["receipt"]).write_text(json.dumps(tampered))
            self.assertEqual(
                scanner._restore_persistent_remote_receipt()["status"],
                "tampered")
            self.assertEqual(scanner._REMOTE_CYCLE["verifiedWalSequence"], 7)


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

    def test_memory_snapshot_exports_remote_wal_cursor_for_compact_receipt(self):
        saved_batch = dict(scanner._MISSION_BATCH_STATE)
        saved_cycle = dict(scanner._REMOTE_CYCLE)
        try:
            scanner._MISSION_BATCH_STATE["walAppliedSequence"] = 41
            scanner._REMOTE_CYCLE["verifiedWalSequence"] = 17
            with scanner.app.test_client() as client:
                snapshot = client.get(
                    "/api/argus/osint/memory-snapshot").get_json()
            state = snapshot["missionTickDurability"]
            self.assertEqual(state["walAppliedSequence"], 41)
            self.assertEqual(state["remoteWalAppliedSequence"], 41)
            compact = argus_remote_journal.compact_readback_snapshot(
                snapshot)
            self.assertTrue(
                argus_remote_journal.verify_compact_readback_snapshot(
                    compact))
            self.assertEqual(
                compact["missionTickDurability"][
                    "remoteWalAppliedSequence"], 41)
        finally:
            scanner._MISSION_BATCH_STATE.clear()
            scanner._MISSION_BATCH_STATE.update(saved_batch)
            scanner._REMOTE_CYCLE.clear()
            scanner._REMOTE_CYCLE.update(saved_cycle)

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
