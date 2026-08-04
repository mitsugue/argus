"""Checkpoint V2 architecture, integrity and failure-matrix tests."""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import pathlib
import sqlite3
import shutil
import tempfile
import unittest
from unittest import mock

import argus_checkpoint_v2 as v2
import argus_persistent_storage as legacy_storage


def sample_snapshot(scale=1):
    return {
        "schemaVersion": "argus-durable-v3",
        "marketLedger": [
            {"symbol": f"JP:{index}", "history": ["x" * 1024] * scale}
            for index in range(12)
        ],
        "opsJournal": [
            {"sequence": index, "idempotencyKey": f"event-{index}"}
            for index in range(40)
        ],
        "remoteAck": {"maximumSequence": 39},
    }


class CheckpointV2Tests(unittest.TestCase):
    def test_disk_reserve_refuses_before_write_and_preserves_authority(self):
        with tempfile.TemporaryDirectory() as root:
            first = v2.write_generation(
                root, sample_snapshot(), source_generation="old")
            manifest_path = pathlib.Path(root, v2.MANIFEST_NAME)
            before = manifest_path.read_bytes()
            usage = shutil._ntuple_diskusage(
                5 * 1024 ** 3, 5 * 1024 ** 3 - 1024, 1024)
            with self.assertRaisesRegex(
                    v2.CheckpointV2Error,
                    "checkpoint_v2_disk_reserve_insufficient"):
                v2.write_generation(
                    root, sample_snapshot(scale=2), source_generation="new",
                    disk_usage_fn=lambda unused: usage)
            self.assertEqual(manifest_path.read_bytes(), before)
            self.assertEqual(v2.restore_generation(root)["generationId"],
                             first["generationId"])
            self.assertFalse(any(
                path.name.startswith(".v2-pending-")
                for path in pathlib.Path(root).iterdir()))

    def test_disk_budget_has_hard_count_bytes_and_reserve(self):
        with tempfile.TemporaryDirectory() as root:
            v2.write_generation(root, sample_snapshot(),
                                source_generation="old")
            status = v2.disk_budget_status(root)
            self.assertEqual(status["maximumRetainedGenerationCount"], 4)
            self.assertEqual(status["maximumRetainedGenerationBytes"],
                             4 * v2.MAXIMUM_TOTAL_BYTES)
            self.assertEqual(status["maximumInProgressGenerationBytes"],
                             v2.MAXIMUM_TOTAL_BYTES)
            self.assertEqual(status["minimumFreeSpaceReserve"], 1024 ** 3)
            self.assertLessEqual(status["retainedGenerationCount"], 4)

    def test_abandoned_v2_pending_is_bounded_and_incident_name_ignored(self):
        with tempfile.TemporaryDirectory() as root:
            pending = pathlib.Path(root, ".v2-pending-" + "a" * 32)
            pending.mkdir()
            (pending / v2.DATABASE_NAME).write_bytes(b"incomplete")
            incident = pathlib.Path(
                root, "argus_osint_memory.json.4242." + "b" * 32 + ".tmp")
            incident.write_bytes(b"immutable-incident")
            before = incident.stat()
            result = v2.write_generation(
                root, sample_snapshot(), source_generation="old")
            after = incident.stat()
            self.assertEqual(result["pendingReconciliation"], {
                "detectedCount": 1, "removedCount": 1,
                "malformedCount": 0})
            self.assertFalse(pending.exists())
            self.assertEqual(
                (before.st_ino, before.st_size, before.st_mtime_ns),
                (after.st_ino, after.st_size, after.st_mtime_ns))

    def test_manifest_provenance_counts_only_unique_natural_generations(self):
        with tempfile.TemporaryDirectory() as root:
            for index, source in enumerate(("manual", "ec2_systemd",
                                            "ec2_systemd", "ec2_systemd")):
                v2.write_generation(
                    root, sample_snapshot(), source_generation=str(index),
                    validation_context={
                        "triggerSource": source,
                        "missionWindowId": f"mw-{index}",
                        "natural": source == "ec2_systemd",
                        "formalSoakState": "not_started"})
            status = v2.public_status(root)
            self.assertEqual(status["naturalGenerationCount"], 3)
            self.assertTrue(status["legacyRestoreAuthority"])
            self.assertFalse(status["v2RestoreAuthority"])
            self.assertEqual(status["formalSoakState"], "not_started")

    def test_round_trip_manifest_rows_and_read_only_restore(self):
        with tempfile.TemporaryDirectory() as root:
            source = sample_snapshot(scale=800)
            written = v2.write_generation(
                root, source, source_generation="legacy-sha256:abc")
            restored = v2.restore_generation(root)
            self.assertEqual(restored["snapshot"], source)
            self.assertEqual(restored["sourceGeneration"],
                             "legacy-sha256:abc")
            manifest = json.loads(pathlib.Path(
                root, v2.MANIFEST_NAME).read_text())
            database = pathlib.Path(
                root, f"v2-generation-{written['generationId']}",
                v2.DATABASE_NAME)
            connection = sqlite3.connect(database)
            try:
                rows = connection.execute(
                    "SELECT payload,payload_bytes,payload_sha256 FROM rows"
                ).fetchall()
            finally:
                connection.close()
            self.assertTrue(rows)
            for payload, payload_bytes, payload_hash in rows:
                self.assertLessEqual(payload_bytes, v2.MAXIMUM_ROW_BYTES)
                self.assertEqual(len(payload), payload_bytes)
                self.assertEqual(hashlib.sha256(payload).hexdigest(),
                                 payload_hash)
            self.assertEqual(manifest["database"]["bytes"],
                             database.stat().st_size)

    def test_interruption_never_repoints_previous_manifest(self):
        for fault in ("segment", "transaction", "database_fsync",
                      "generation_rename"):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as root:
                old = sample_snapshot()
                first = v2.write_generation(root, old, source_generation="old")
                before = pathlib.Path(root, v2.MANIFEST_NAME).read_bytes()
                with self.assertRaises(v2.CheckpointV2Error):
                    v2.write_generation(
                        root, sample_snapshot(scale=2),
                        source_generation="new", fault_after=fault)
                self.assertEqual(
                    pathlib.Path(root, v2.MANIFEST_NAME).read_bytes(), before)
                restored = v2.restore_generation(root)
                self.assertEqual(restored["generationId"],
                                 first["generationId"])
                self.assertEqual(restored["snapshot"], old)
                self.assertFalse(any(
                    path.name.startswith(".v2-pending-")
                    for path in pathlib.Path(root).iterdir()))

    def test_tampered_database_is_rejected_before_deserialization(self):
        with tempfile.TemporaryDirectory() as root:
            written = v2.write_generation(
                root, sample_snapshot(), source_generation="old")
            database = pathlib.Path(
                root, f"v2-generation-{written['generationId']}",
                v2.DATABASE_NAME)
            with database.open("r+b") as handle:
                handle.seek(-1, os.SEEK_END)
                byte = handle.read(1)
                handle.seek(-1, os.SEEK_END)
                handle.write(bytes([byte[0] ^ 1]))
            with self.assertRaisesRegex(
                    v2.CheckpointV2Error,
                    "checkpoint_v2_database_hash_mismatch"):
                v2.restore_generation(root)

    def test_manifest_schema_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            v2.write_generation(root, sample_snapshot(),
                                source_generation="old")
            manifest_path = pathlib.Path(root, v2.MANIFEST_NAME)
            manifest = json.loads(manifest_path.read_text())
            manifest["schemaVersion"] = "future"
            manifest_path.write_text(json.dumps(manifest))
            with self.assertRaisesRegex(
                    v2.CheckpointV2Error,
                    "checkpoint_v2_manifest_schema_unsupported"):
                v2.restore_generation(root)

    def test_missing_database_is_classified(self):
        with tempfile.TemporaryDirectory() as root:
            written = v2.write_generation(
                root, sample_snapshot(), source_generation="old")
            pathlib.Path(
                root, f"v2-generation-{written['generationId']}",
                v2.DATABASE_NAME).unlink()
            with self.assertRaisesRegex(
                    v2.CheckpointV2Error, "checkpoint_v2_database_missing"):
                v2.restore_generation(root)

    def test_segment_hash_rejects_malformed_payload_even_with_db_hash(self):
        with tempfile.TemporaryDirectory() as root:
            written = v2.write_generation(
                root, sample_snapshot(), source_generation="old")
            database = pathlib.Path(
                root, f"v2-generation-{written['generationId']}",
                v2.DATABASE_NAME)
            connection = sqlite3.connect(database)
            try:
                connection.execute(
                    "UPDATE rows SET payload=? WHERE rowid=(SELECT MIN(rowid) FROM rows)",
                    (b"{malformed",))
                connection.commit()
            finally:
                connection.close()
            size, digest = v2._file_stats(str(database))
            manifest_path = pathlib.Path(root, v2.MANIFEST_NAME)
            manifest = json.loads(manifest_path.read_text())
            manifest["database"] = {"name": v2.DATABASE_NAME,
                                    "bytes": size, "sha256": digest}
            manifest_path.write_text(json.dumps(manifest))
            with self.assertRaisesRegex(
                    v2.CheckpointV2Error, "checkpoint_v2_row_hash_mismatch"):
                v2.restore_generation(root)

    def test_fsync_and_rename_failures_preserve_previous_manifest(self):
        for target, patcher in (
                ("fsync", mock.patch.object(
                    v2, "_fsync_directory", side_effect=OSError("fsync"))),
                ("rename", mock.patch.object(
                    v2.os, "replace", side_effect=OSError("rename")))):
            with self.subTest(target=target), tempfile.TemporaryDirectory() as root:
                first = v2.write_generation(
                    root, sample_snapshot(), source_generation="old")
                manifest = pathlib.Path(root, v2.MANIFEST_NAME).read_bytes()
                with patcher, self.assertRaises(v2.CheckpointV2Error):
                    v2.write_generation(
                        root, sample_snapshot(scale=2), source_generation="new")
                self.assertEqual(
                    pathlib.Path(root, v2.MANIFEST_NAME).read_bytes(), manifest)
                self.assertEqual(v2.restore_generation(root)["generationId"],
                                 first["generationId"])

    def test_structural_caps_fail_before_manifest_promotion(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaisesRegex(
                    v2.CheckpointV2Error,
                    "checkpoint_v2_count_limit_exceeded"):
                v2.write_generation(
                    root, {"missions": list(range(121))},
                    source_generation="old")
            self.assertFalse(pathlib.Path(root, v2.MANIFEST_NAME).exists())
        with tempfile.TemporaryDirectory() as root, mock.patch.dict(
                v2.SECTION_LIMITS, {"marketLedger": 64}):
            with self.assertRaisesRegex(
                    v2.CheckpointV2Error,
                    "checkpoint_v2_section_limit_exceeded"):
                v2.write_generation(
                    root, {"marketLedger": ["x" * 128]},
                    source_generation="old")
        with tempfile.TemporaryDirectory() as root, mock.patch.dict(
                v2.NESTED_COUNT_LIMITS,
                {"marketLedger": {"observations": 1}}):
            with self.assertRaisesRegex(
                    v2.CheckpointV2Error,
                    "checkpoint_v2_nested_count_limit_exceeded"):
                v2.write_generation(
                    root, {"marketLedger": {"observations": [{}, {}]}},
                    source_generation="old")

    def test_writer_contention_fails_fast(self):
        with tempfile.TemporaryDirectory() as root:
            lock_path = pathlib.Path(root, "checkpoint-v2.writer.lock")
            with lock_path.open("a+b") as lock:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                with self.assertRaisesRegex(
                        v2.CheckpointV2Error, "checkpoint_v2_writer_busy"):
                    v2.write_generation(
                        root, sample_snapshot(), source_generation="old")

    def test_stage1_does_not_modify_legacy_checkpoint_or_wal(self):
        with tempfile.TemporaryDirectory() as root:
            legacy = pathlib.Path(root, "argus_osint_memory.json")
            wal = pathlib.Path(root, "argus_mission_tick.wal")
            legacy.write_bytes(b"immutable-legacy")
            wal.write_bytes(b"immutable-wal")
            before = {
                legacy: hashlib.sha256(legacy.read_bytes()).hexdigest(),
                wal: hashlib.sha256(wal.read_bytes()).hexdigest(),
            }
            v2.write_generation(root, sample_snapshot(),
                                source_generation="legacy")
            self.assertEqual(
                {path: hashlib.sha256(path.read_bytes()).hexdigest()
                 for path in before}, before)

    def test_generation_retention_is_bounded_and_current_survives(self):
        with tempfile.TemporaryDirectory() as root:
            latest = None
            for index in range(v2.MAXIMUM_GENERATIONS + 3):
                latest = v2.write_generation(
                    root, sample_snapshot(), source_generation=str(index))
            generations = list(pathlib.Path(root).glob("v2-generation-*"))
            self.assertLessEqual(len(generations), v2.MAXIMUM_GENERATIONS)
            self.assertTrue(pathlib.Path(
                root, f"v2-generation-{latest['generationId']}").is_dir())
            self.assertEqual(v2.restore_generation(root)["sourceGeneration"],
                             str(v2.MAXIMUM_GENERATIONS + 2))

    def test_public_status_contains_no_paths_or_payload(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(v2.public_status(root)["state"], "not_created")
            v2.write_generation(root, sample_snapshot(),
                                source_generation="legacy")
            status = v2.public_status(root)
            self.assertEqual(status["state"], "stage1_dual_write")
            encoded = json.dumps(status)
            self.assertNotIn(root, encoded)
            self.assertNotIn("idempotencyKey", encoded)

    def test_rebuildable_cache_archives_verify_without_active_restore(self):
        with tempfile.TemporaryDirectory() as root:
            source = {
                "schemaVersion": "argus-durable-v3",
                "marketLedger": {"observations": []},
                "verifiedViewSnapshots": {"current": {}, "history": []},
                "assetChartReports": {"current": {}, "records": {}},
            }
            v2.write_generation(root, source, source_generation="legacy")
            restored = v2.restore_generation(root, include_archived=False)
            self.assertEqual(restored["snapshot"], {
                "schemaVersion": "argus-durable-v3",
                "marketLedger": {"observations": []},
            })
            self.assertEqual(restored["archivedSections"],
                             ["assetChartReports", "verifiedViewSnapshots"])

    def test_legacy_migration_is_idempotent_and_source_is_immutable(self):
        with tempfile.TemporaryDirectory() as root:
            old = pathlib.Path(root, "legacy.json")
            source = sample_snapshot()
            legacy_storage.write_checkpoint(str(old), source,
                                            temp_directory=root)
            before = (old.stat().st_ino, old.stat().st_mtime_ns,
                      hashlib.sha256(old.read_bytes()).hexdigest())
            v2_root = pathlib.Path(root, "v2")
            first = v2.migrate_legacy_checkpoint(str(old), str(v2_root))
            second = v2.migrate_legacy_checkpoint(str(old), str(v2_root))
            after = (old.stat().st_ino, old.stat().st_mtime_ns,
                     hashlib.sha256(old.read_bytes()).hexdigest())
            self.assertEqual(before, after)
            self.assertEqual(first["status"], "migrated")
            self.assertEqual(second["status"], "already_migrated")
            self.assertEqual(v2.restore_generation(str(v2_root))["snapshot"],
                             legacy_storage.load_checkpoint(
                                 str(old), require_seal=True))

    def test_interrupted_migration_preserves_old_and_previous_v2(self):
        with tempfile.TemporaryDirectory() as root:
            old = pathlib.Path(root, "legacy.json")
            legacy_storage.write_checkpoint(
                str(old), sample_snapshot(), temp_directory=root)
            v2_root = pathlib.Path(root, "v2")
            first = v2.migrate_legacy_checkpoint(str(old), str(v2_root))
            manifest = pathlib.Path(v2_root, v2.MANIFEST_NAME).read_bytes()
            legacy_storage.write_checkpoint(
                str(old), sample_snapshot(scale=2), temp_directory=root)
            with self.assertRaises(v2.CheckpointV2Error):
                v2.migrate_legacy_checkpoint(
                    str(old), str(v2_root), fault_after="database_fsync")
            self.assertEqual(
                pathlib.Path(v2_root, v2.MANIFEST_NAME).read_bytes(), manifest)
            self.assertEqual(v2.restore_generation(str(v2_root))["generationId"],
                             first["generationId"])


if __name__ == "__main__":
    unittest.main()
