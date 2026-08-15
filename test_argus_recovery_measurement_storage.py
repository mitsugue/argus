"""Hostile path and fail-safe persistence tests for Measurement Core."""
from __future__ import annotations

import datetime as dt
import dataclasses
import errno
import json
import os
import pathlib
import stat
import subprocess
import sys

import pytest

import argus_recovery_measurement as measurement
import argus_recovery_measurement_storage as storage


UTC = dt.timezone.utc
NOW = dt.datetime(2026, 8, 15, tzinfo=UTC)


def _artifact(generation="generation-0001"):
    return measurement.new_artifact(
        measurement_generation_id=generation,
        producer_build_sha="a" * 40,
        instrumentation_coverage_sha256="b" * 64,
        created_at=NOW)


def _decision(tmp_path):
    diagnostics = tmp_path / "diagnostics" / "recovery-measurement"
    plan = storage.authoritative_path_plan(
        persistent_root=str(tmp_path / "authority"),
        temporary_root=str(tmp_path / "temporary"))
    decision = storage.resolve_measurement_path(
        diagnostics_root=str(diagnostics), protected_paths=plan)
    assert decision.accepted
    assert storage.prepare_diagnostics_namespace(decision) == "ok"
    return decision


def _persist(decision, artifact, *, operations=None):
    return storage.persist_artifact(
        decision, artifact, now=NOW, operations=operations)


def test_canonical_contract_and_permissions(tmp_path):
    pure = storage.resolve_measurement_path(inspect_filesystem=False)
    assert pure.accepted
    assert pure.artifact_path == \
        "/var/data/diagnostics/recovery-measurement/measurement-v1.json"
    decision = _decision(tmp_path)
    result = _persist(decision, _artifact())
    assert result.status == "persisted"
    assert stat_mode(pathlib.Path(decision.diagnostics_root)) == 0o700
    assert stat_mode(pathlib.Path(decision.artifact_path)) == 0o600


def stat_mode(path):
    return path.stat().st_mode & 0o777


def test_authoritative_plan_covers_all_required_families(tmp_path):
    families = {entry.family for entry in storage.authoritative_path_plan(
        persistent_root=str(tmp_path / "authority"),
        temporary_root=str(tmp_path / "temporary"))}
    required = {
        "sealed_checkpoint", "checkpoint_file_seal",
        "checkpoint_quarantine", "checkpoint_temp", "wal",
        "wal_compaction_temp", "wal_anchor", "writer_lock", "lease",
        "cursor", "durability_receipt", "receipt_queue",
        "recovery_artifact", "recovery_artifact_temp", "nonce_state",
        "nonce_history", "nonce_history_head", "nonce_reservation_lock",
        "nonce_reservation_anchor", "predictions", "foundation_sidecar",
        "checkpoint_v2", "checkpoint_v2_writer_lock",
        "checkpoint_v2_runtime", "checkpoint_v2_manifest",
        "checkpoint_v2_manifest_temp",
        "checkpoint_v2_manifest_writer_lock",
        "checkpoint_v2_runtime_writer_lock",
        "checkpoint_v2_pending_generation", "checkpoint_v2_generation",
        "checkpoint_v2_isolated_job",
        "known_temporary_store",
    }
    assert required <= families


@pytest.mark.parametrize("family", [
    "sealed_checkpoint", "wal", "durability_receipt", "receipt_queue",
    "recovery_artifact", "nonce_state", "nonce_history",
    "nonce_history_head", "nonce_reservation_anchor", "predictions",
    "foundation_sidecar", "checkpoint_v2_writer_lock",
])
def test_exact_authority_collisions_are_rejected_and_sentinels_unchanged(
        tmp_path, family):
    root = tmp_path / family
    root.mkdir()
    candidate = root / "measurement-v1.json"
    candidate.write_bytes(b"AUTHORITY-SENTINEL")
    before = (candidate.read_bytes(), candidate.stat().st_ino)
    plan = (storage.ProtectedPath(family, str(candidate)),)
    decision = storage.resolve_measurement_path(
        diagnostics_root=str(root), protected_paths=plan)
    assert not decision.accepted
    assert decision.status == "configuration_rejected"
    assert storage.persist_artifact(
        decision, _artifact(), now=NOW).status == "configuration_rejected"
    assert (candidate.read_bytes(), candidate.stat().st_ino) == before


def test_v2_subtree_ancestor_descendant_and_temp_prefix_collisions(tmp_path):
    v2 = tmp_path / "checkpoint-v2"
    v2.mkdir()
    decision = storage.resolve_measurement_path(
        diagnostics_root=str(v2),
        protected_paths=(storage.ProtectedPath(
            "checkpoint_v2", str(v2), "subtree"),))
    assert not decision.accepted


def test_real_checkpoint_v2_family_and_aliases_are_immutable(tmp_path):
    authority = tmp_path / "authority"
    v2 = authority / "argus_checkpoint_v2"
    pending = v2 / (".v2-pending-" + "1" * 32)
    generation = v2 / ("v2-generation-" + "2" * 32)
    job = v2 / (".v2-isolated-job-" + "3" * 32)
    for directory in (pending, generation, job):
        directory.mkdir(parents=True, exist_ok=True)
    sentinels = {
        v2 / "checkpoint-v2-manifest.json": b"MANIFEST-SENTINEL",
        v2 / "checkpoint-v2.writer.lock": b"LOCK-SENTINEL",
        v2 / "checkpoint-v2-manifest.json.writer.lock":
            b"MANIFEST-LOCK-SENTINEL",
        v2 / "checkpoint-v2-manifest.json.7.token.v1338-tmp":
            b"TEMP-SENTINEL",
        pending / "measurement-v1.json": b"PENDING-SENTINEL",
        generation / "measurement-v1.json": b"GENERATION-SENTINEL",
        job / "measurement-v1.json": b"JOB-SENTINEL",
    }
    for path, payload in sentinels.items():
        path.write_bytes(payload)
    before = {
        path: (path.read_bytes(), path.stat().st_ino)
        for path in sentinels
    }
    plan = storage.authoritative_path_plan(
        persistent_root=str(authority),
        temporary_root=str(tmp_path / "temporary"))

    attempts = [
        storage.resolve_measurement_path(
            diagnostics_root=str(v2), override=path.name,
            protected_paths=plan)
        for path in sentinels if path.parent == v2
    ]
    attempts.extend(storage.resolve_measurement_path(
        diagnostics_root=str(directory), protected_paths=plan)
        for directory in (v2, pending, generation, job))
    attempts.append(storage.resolve_measurement_path(
        diagnostics_root=str(authority),
        override="argus_checkpoint_v2", protected_paths=plan))
    for decision in attempts:
        assert not decision.accepted
        assert decision.status == "configuration_rejected"
        assert storage.persist_artifact(
            decision, _artifact(), now=NOW).status == \
            "configuration_rejected"

    alias_root = tmp_path / "alias-diagnostics"
    alias_root.mkdir()
    alias = alias_root / "measurement-v1.json"
    manifest = v2 / "checkpoint-v2-manifest.json"
    os.link(manifest, alias)
    alias_before = (alias.read_bytes(), alias.stat().st_ino)
    alias_decision = storage.resolve_measurement_path(
        diagnostics_root=str(alias_root), protected_paths=plan)
    assert not alias_decision.accepted
    assert alias_decision.status == "configuration_rejected"
    assert (alias.read_bytes(), alias.stat().st_ino) == alias_before
    assert {
        path: (path.read_bytes(), path.stat().st_ino)
        for path in sentinels
    } == before
    root = tmp_path / "diagnostics"
    root.mkdir()
    decision = storage.resolve_measurement_path(
        diagnostics_root=str(root), override="authority.tmp.json",
        protected_paths=())
    assert not decision.accepted


@pytest.mark.parametrize("override", [
    "../authority.json", "nested/measurement.json", "/tmp/outside.json",
    ".measurement-v1.json", "measurement-v1.tmp.json",
    "measurement-v1.lock.json", "measurement-v1.previous.json",
    "measurement-v1.pending.json", "measurement-v1.txt",
])
def test_lexical_override_attacks_are_rejected_before_io(
        tmp_path, override, monkeypatch):
    root = tmp_path / "diagnostics"

    def forbidden_lstat(_path):
        raise AssertionError("rejected path performed I/O")

    monkeypatch.setattr(storage.os, "lstat", forbidden_lstat)
    decision = storage.resolve_measurement_path(
        diagnostics_root=str(root), override=override,
        protected_paths=(), inspect_filesystem=True)
    assert not decision.accepted
    assert decision.artifact_path is None


def test_symlink_components_and_leaf_are_rejected(tmp_path):
    actual = tmp_path / "actual"
    actual.mkdir()
    linked = tmp_path / "linked"
    linked.symlink_to(actual, target_is_directory=True)
    assert not storage.resolve_measurement_path(
        diagnostics_root=str(linked), protected_paths=()).accepted
    leaf = actual / "measurement-v1.json"
    target = tmp_path / "target"
    target.write_bytes(b"sentinel")
    leaf.symlink_to(target)
    assert not storage.resolve_measurement_path(
        diagnostics_root=str(actual), protected_paths=()).accepted
    assert target.read_bytes() == b"sentinel"


def test_hardlink_fifo_directory_socket_and_device_are_rejected(
        tmp_path, monkeypatch):
    for kind in ("hardlink", "fifo", "directory"):
        root = tmp_path / kind
        root.mkdir()
        leaf = root / "measurement-v1.json"
        if kind == "hardlink":
            sentinel = tmp_path / "authority-sentinel"
            sentinel.write_bytes(b"AUTHORITY")
            os.link(sentinel, leaf)
        elif kind == "fifo":
            os.mkfifo(leaf)
        elif kind == "directory":
            leaf.mkdir()
        assert not storage.resolve_measurement_path(
            diagnostics_root=str(root), protected_paths=()).accepted
    socket_root = tmp_path / "socket"
    socket_root.mkdir()
    socket_leaf = socket_root / "measurement-v1.json"
    real_lstat = storage.os.lstat
    socket_stat = os.stat_result((
        stat.S_IFSOCK | 0o600, 99, 99, 1, 0, 0, 0, 0, 0, 0))

    def fake_lstat(path):
        return socket_stat if os.fspath(path) == str(socket_leaf) else \
            real_lstat(path)

    monkeypatch.setattr(storage.os, "lstat", fake_lstat)
    assert not storage.resolve_measurement_path(
        diagnostics_root=str(socket_root), protected_paths=()).accepted
    assert not storage.resolve_measurement_path(
        diagnostics_root="/dev", override="/dev/null",
        protected_paths=()).accepted


class _FailWrite(storage.FileOperations):
    def write(self, descriptor, data):
        raise OSError(errno.ENOSPC, "disk full")


class _FailFileFsync(storage.FileOperations):
    def fsync_file(self, descriptor):
        raise OSError(errno.EIO, "fsync failed")


class _FailReplace(storage.FileOperations):
    def replace(self, source, destination, directory_fd):
        raise OSError(errno.EIO, "replace failed")


class _FailSecondDirectoryFsync(storage.FileOperations):
    def __init__(self):
        self.calls = 0

    def fsync_directory(self, descriptor):
        self.calls += 1
        if self.calls == 2:
            raise OSError(errno.EIO, "post-replace directory fsync failed")
        super().fsync_directory(descriptor)


class _FailPostFsyncAndRollbackReplace(storage.FileOperations):
    def __init__(self):
        self.directory_fsync_calls = 0
        self.replace_calls = 0

    def fsync_directory(self, descriptor):
        self.directory_fsync_calls += 1
        if self.directory_fsync_calls == 2:
            raise OSError(errno.EIO, "post-replace fsync failed")
        super().fsync_directory(descriptor)

    def replace(self, source, destination, directory_fd):
        self.replace_calls += 1
        if self.replace_calls == 2:
            raise OSError(errno.EIO, "rollback replace failed")
        super().replace(source, destination, directory_fd)


class _FailPostAndRollbackDirectoryFsync(storage.FileOperations):
    def __init__(self):
        self.calls = 0

    def fsync_directory(self, descriptor):
        self.calls += 1
        if self.calls in (2, 3):
            raise OSError(errno.EIO, "directory fsync failed")
        super().fsync_directory(descriptor)


class _FailRecoveryCleanup(storage.FileOperations):
    def unlink(self, name, directory_fd):
        if name.endswith(storage.RECOVERY_FILE_SUFFIX):
            raise OSError(errno.EIO, "recovery cleanup failed")
        super().unlink(name, directory_fd)


class _FailInstallAndRecoveryCleanup(_FailRecoveryCleanup):
    def replace(self, source, destination, directory_fd):
        raise OSError(errno.EIO, "install replace failed")


@pytest.mark.parametrize("operations", [
    _FailWrite(), _FailFileFsync(), _FailReplace(),
    _FailSecondDirectoryFsync(),
])
def test_disk_write_rename_and_fsync_failures_preserve_previous_inode_and_bytes(
        tmp_path, operations):
    decision = _decision(tmp_path)
    original = _artifact("generation-original")
    assert _persist(decision, original).status == "persisted"
    path = pathlib.Path(decision.artifact_path)
    before = (path.read_bytes(), path.stat().st_ino)
    replacement = _artifact("generation-replacement")
    result = _persist(decision, replacement, operations=operations)
    assert result.status == "persistence_failed"
    assert (path.read_bytes(), path.stat().st_ino) == before
    assert not [entry for entry in path.parent.iterdir()
                if entry.name.startswith(".measurement-v1.json.measurement-")]


def test_serializer_or_plan_failure_performs_no_io_and_preserves_previous(
        tmp_path, monkeypatch):
    decision = _decision(tmp_path)
    assert _persist(decision, _artifact("generation-original")).status == \
        "persisted"
    path = pathlib.Path(decision.artifact_path)
    before = (path.read_bytes(), path.stat().st_ino)
    invalid = _artifact("generation-invalid")
    invalid["unknown"] = "owner content"

    def forbidden_open(*_args, **_kwargs):
        raise AssertionError("invalid artifact reached filesystem")

    monkeypatch.setattr(storage, "_open_directory_chain", forbidden_open)
    result = storage.persist_artifact(decision, invalid, now=NOW)
    assert result.status == "invalid_artifact"
    assert (path.read_bytes(), path.stat().st_ino) == before


def test_retention_plan_bytes_are_bound_before_any_filesystem_mutation(
        tmp_path, monkeypatch):
    decision = _decision(tmp_path)
    original = _artifact("generation-original")
    assert _persist(decision, original).status == "persisted"
    path = pathlib.Path(decision.artifact_path)
    before = (path.read_bytes(), path.stat().st_ino)
    artifact = _artifact("generation-replacement")
    correct = measurement.plan_retention(artifact, now=NOW)
    different = measurement.plan_retention(
        _artifact("generation-different"), now=NOW)
    hostile = (
        b"arbitrary <=12MiB payload",
        different.canonical_bytes,
        correct.canonical_bytes[:-1] + bytes([
            correct.canonical_bytes[-1] ^ 1]),
    )
    real_open = storage._open_directory_chain

    def forbidden_open(*_args, **_kwargs):
        raise AssertionError("mismatched bytes reached filesystem")

    monkeypatch.setattr(storage, "_open_directory_chain", forbidden_open)
    for encoded in hostile:
        bad_plan = dataclasses.replace(correct, canonical_bytes=encoded)
        result = storage.persist_retention_plan(decision, bad_plan)
        assert result.status == "serialization_failure"
        assert (path.read_bytes(), path.stat().st_ino) == before
    monkeypatch.setattr(storage, "_open_directory_chain", real_open)
    assert storage.persist_retention_plan(decision, correct).status == \
        "persisted"
    assert path.read_bytes() == correct.canonical_bytes


@pytest.mark.parametrize("operations,expected_recovery", [
    (_FailPostFsyncAndRollbackReplace(), True),
    (_FailPostAndRollbackDirectoryFsync(), False),
    (_FailRecoveryCleanup(), True),
    (_FailInstallAndRecoveryCleanup(), True),
])
def test_failure_matrix_never_deletes_last_known_good(
        tmp_path, operations, expected_recovery):
    decision = _decision(tmp_path)
    original = _artifact("generation-original")
    assert _persist(decision, original).status == "persisted"
    path = pathlib.Path(decision.artifact_path)
    previous_bytes = path.read_bytes()
    recovery = path.parent / (
        f".{path.name}{storage.RECOVERY_FILE_SUFFIX}")
    result = _persist(
        decision, _artifact("generation-replacement"),
        operations=operations)
    assert result.status == "persistence_failed"
    assert path.read_bytes() == previous_bytes or \
        recovery.read_bytes() == previous_bytes
    assert recovery.exists() is expected_recovery
    if recovery.exists():
        assert recovery.read_bytes() == previous_bytes
        loaded = storage.load_artifact(decision)
        assert loaded.status == "loaded"
        assert loaded.artifact == original
        assert path.read_bytes() == previous_bytes
        assert not recovery.exists()


def test_recovery_slot_rejects_user_destination_and_unsafe_substitution(
        tmp_path, monkeypatch):
    decision = _decision(tmp_path)
    assert not storage.resolve_measurement_path(
        diagnostics_root=decision.diagnostics_root,
        override=f".measurement-v1.json{storage.RECOVERY_FILE_SUFFIX}",
        protected_paths=decision.protected_paths).accepted
    assert _persist(decision, _artifact("generation-original")).status == \
        "persisted"
    path = pathlib.Path(decision.artifact_path)
    previous = path.read_bytes()
    recovery = path.parent / (
        f".{path.name}{storage.RECOVERY_FILE_SUFFIX}")
    external = tmp_path / "external"
    external.write_bytes(previous)
    attacks = ("symlink", "hardlink", "fifo", "directory")
    for attack in attacks:
        if os.path.lexists(recovery):
            if recovery.is_dir() and not recovery.is_symlink():
                recovery.rmdir()
            else:
                recovery.unlink()
        if attack == "symlink":
            recovery.symlink_to(external)
        elif attack == "hardlink":
            os.link(external, recovery)
        elif attack == "fifo":
            os.mkfifo(recovery)
        else:
            recovery.mkdir()
        assert _persist(
            decision, _artifact(f"generation-{attack}")).status == \
            "persistence_failed"
        assert path.read_bytes() == previous
        assert external.read_bytes() == previous
    recovery.rmdir()
    real_stat = storage.os.stat
    socket_stat = os.stat_result((
        stat.S_IFSOCK | 0o600, 99, 99, 1, 0, 0, 0, 0, 0, 0))

    def fake_stat(name, *args, **kwargs):
        return socket_stat if name == "recovery.sock" else \
            real_stat(name, *args, **kwargs)

    monkeypatch.setattr(storage.os, "stat", fake_stat)
    with pytest.raises(OSError):
        storage._raw_leaf_stat(0, "recovery.sock", frozenset())
    device_fd = os.open("/dev", os.O_RDONLY)
    try:
        with pytest.raises(OSError):
            storage._raw_leaf_stat(device_fd, "null", frozenset())
    finally:
        os.close(device_fd)


class _SwapToAuthorityHardlink(storage.FileOperations):
    def __init__(self, destination, authority):
        self.destination = destination
        self.authority = authority

    def fsync_file(self, descriptor):
        super().fsync_file(descriptor)
        os.unlink(self.destination)
        os.link(self.authority, self.destination)


def test_post_validation_hardlink_swap_never_writes_authority(tmp_path):
    decision = _decision(tmp_path)
    assert _persist(decision, _artifact("generation-original")).status == \
        "persisted"
    authority = tmp_path / "authority-sentinel"
    authority.write_bytes(b"AUTHORITATIVE-BYTES")
    before = (authority.read_bytes(), authority.stat().st_ino)
    operations = _SwapToAuthorityHardlink(
        decision.artifact_path, str(authority))
    result = _persist(
        decision, _artifact("generation-replacement"), operations=operations)
    assert result.status == "persistence_failed"
    assert (authority.read_bytes(), authority.stat().st_ino) == before


def test_load_rejects_duplicate_keys_nonfinite_and_policy_drift_then_resets(
        tmp_path):
    decision = _decision(tmp_path)
    path = pathlib.Path(decision.artifact_path)
    path.write_text('{"schemaVersion":"x","schemaVersion":"y"}',
                    encoding="utf-8")
    assert storage.load_artifact(decision).status == "invalid_artifact"
    reset = storage.load_or_reset(
        decision, measurement_generation_id="reset-generation",
        producer_build_sha="a" * 40,
        instrumentation_coverage_sha256="b" * 64, reset_at=NOW)
    assert reset.status == "invalid_artifact"
    assert reset.artifact["mode"] == "SHADOW"
    assert reset.artifact["invalidation"]["code"] == "artifact_invalid"
    assert reset.artifact["registryPolicySha256"] == \
        measurement.registry.registry_policy_sha256()

    drifted = _artifact("old-policy-generation")
    drifted["registryPolicySha256"] = "f" * 64
    path.write_bytes(measurement._canonical_bytes_unchecked(drifted))
    assert storage.load_artifact(decision).status == \
        "registry_policy_mismatch"
    reset = storage.load_or_reset(
        decision, measurement_generation_id="new-policy-generation",
        producer_build_sha="a" * 40,
        instrumentation_coverage_sha256="b" * 64, reset_at=NOW)
    assert reset.status == "registry_policy_mismatch"
    assert reset.artifact["invalidation"]["code"] == \
        "registry_policy_mismatch"
    assert measurement.validate_artifact(reset.artifact).valid


def test_missing_artifact_resets_to_empty_shadow_without_invalidation(tmp_path):
    decision = _decision(tmp_path)
    result = storage.load_or_reset(
        decision, measurement_generation_id="new-generation",
        producer_build_sha="a" * 40,
        instrumentation_coverage_sha256="b" * 64, reset_at=NOW)
    assert result.status == "not_found"
    assert result.artifact["invalidation"] == {"code": "none", "at": None}
    assert result.artifact["intervalBuckets"] == []


def test_benchmark_harness_smoke_is_reproducible_and_buffer_bounded():
    completed = subprocess.run(
        [sys.executable, "scripts/recovery_measurement_benchmark.py",
         "--smoke", "--samples", "1"], check=True,
        capture_output=True, text=True)
    report = json.loads(completed.stdout)
    assert report["passed"] is True
    assert report["fullSizeBuffers"] == 0
    assert report["outputChunkLimitBytes"] <= 1024 * 1024
