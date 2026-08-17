"""Isolated diagnostic path and atomic persistence for Measurement Core.

The adapter never reads environment variables and never imports scanner/runtime.
Callers supply a pure path decision.  Rejected decisions perform no I/O.
"""
from __future__ import annotations

from dataclasses import dataclass
import errno
import json
import os
import secrets
import stat
from typing import Any, Dict, Iterable, Optional, Sequence, Tuple

import argus_recovery_measurement as measurement


CANONICAL_DIAGNOSTICS_ROOT = "/var/data/diagnostics/recovery-measurement"
CANONICAL_ARTIFACT_PATH = (
    CANONICAL_DIAGNOSTICS_ROOT + "/measurement-v1.json")
DIAGNOSTICS_DIRECTORY_MODE = 0o700
ARTIFACT_FILE_MODE = 0o600
MAX_PATH_CHARS = 4096
MAX_FILE_NAME_CHARS = 160
RECOVERY_FILE_SUFFIX = ".measurement-recovery"


@dataclass(frozen=True)
class ProtectedPath:
    family: str
    path: str
    scope: str = "exact"  # exact, subtree, or prefix


@dataclass(frozen=True)
class PathDecision:
    accepted: bool
    status: str
    diagnostics_root: str
    artifact_path: Optional[str]
    artifact_name: Optional[str]
    protected_paths: Tuple[ProtectedPath, ...]


@dataclass(frozen=True)
class PersistenceResult:
    status: str
    bytes_written: int = 0


@dataclass(frozen=True)
class LoadResult:
    status: str
    artifact: Optional[Dict[str, Any]]


def _normal(path: str) -> str:
    return os.path.normpath(os.path.abspath(path))


def authoritative_path_plan(
        *, persistent_root: str = "/var/data", temporary_root: str = "/tmp",
        extra_paths: Iterable[ProtectedPath] = ()) -> Tuple[ProtectedPath, ...]:
    """Explicit current authority/storage families; no filename inference."""
    root = _normal(persistent_root)
    temp = _normal(temporary_root)

    def exact(family: str, name: str) -> ProtectedPath:
        return ProtectedPath(family, _normal(os.path.join(root, name)))

    def exact_at(family: str, parent: str, name: str) -> ProtectedPath:
        return ProtectedPath(family, _normal(os.path.join(parent, name)))

    checkpoint_v2_root = _normal(os.path.join(root, "argus_checkpoint_v2"))

    entries = [
        exact("sealed_checkpoint", "argus_osint_memory.json"),
        exact("checkpoint_file_seal",
              "argus_osint_memory.json.legacy-seal.json"),
        ProtectedPath("checkpoint_quarantine",
                      _normal(os.path.join(root,
                                           "argus_osint_memory.json.quarantine-")),
                      "prefix"),
        ProtectedPath("checkpoint_temp",
                      _normal(os.path.join(root, "argus_osint_memory.json.")),
                      "prefix"),
        exact("wal", "argus_mission_tick.wal"),
        ProtectedPath("wal_compaction_temp",
                      _normal(os.path.join(root, "argus_mission_tick.wal.")),
                      "prefix"),
        exact("wal_anchor", "argus_mission_tick.wal.anchor"),
        exact("writer_lock", "argus_mission_tick.wal.lock"),
        exact("lease", "argus_mission_tick.lease"),
        exact("cursor", "argus_mission_tick.cursor.json"),
        exact("durability_receipt", "argus_mission_tick.receipt.json"),
        exact("receipt_queue", "argus_remote_receipt_queue.json"),
        exact("recovery_artifact", "argus_remote_recovery.json"),
        ProtectedPath("recovery_artifact_temp",
                      _normal(os.path.join(root,
                                           "argus_remote_recovery.json.")),
                      "prefix"),
        exact("nonce_state", "argus_remote_recovery_nonce_state.json"),
        exact("nonce_history", "argus_remote_recovery_nonce_history.json"),
        exact("nonce_history_head",
              "argus_remote_recovery_nonce_history.head.json"),
        exact("nonce_reservation_lock",
              "argus_remote_recovery_nonce_state.json.reservation.lock"),
        exact("nonce_reservation_anchor",
              "argus_remote_recovery_nonce_state.json.reservation.lock.anchor"),
        exact("predictions", "predictions.jsonl"),
        exact("foundation_sidecar", "argus_foundation_jobs.json"),
        # Current runtime family from scanner._CHECKPOINT_V2_ROOT and the
        # bounded V2/isolated-writer implementations.  The subtree entry is
        # authoritative; explicit companions make repository drift auditable.
        ProtectedPath("checkpoint_v2_runtime", checkpoint_v2_root, "subtree"),
        exact_at("checkpoint_v2_manifest", checkpoint_v2_root,
                 "checkpoint-v2-manifest.json"),
        ProtectedPath(
            "checkpoint_v2_manifest_temp",
            _normal(os.path.join(
                checkpoint_v2_root, "checkpoint-v2-manifest.json.")),
            "prefix"),
        exact_at("checkpoint_v2_manifest_writer_lock", checkpoint_v2_root,
                 "checkpoint-v2-manifest.json.writer.lock"),
        exact_at("checkpoint_v2_runtime_writer_lock", checkpoint_v2_root,
                 "checkpoint-v2.writer.lock"),
        ProtectedPath(
            "checkpoint_v2_pending_generation",
            _normal(os.path.join(checkpoint_v2_root, ".v2-pending-")),
            "prefix"),
        ProtectedPath(
            "checkpoint_v2_generation",
            _normal(os.path.join(checkpoint_v2_root, "v2-generation-")),
            "prefix"),
        ProtectedPath(
            "checkpoint_v2_isolated_job",
            _normal(os.path.join(checkpoint_v2_root, ".v2-isolated-job-")),
            "prefix"),
        # Retain the pre-current reserved family so a downgrade cannot reuse
        # it for diagnostics.
        ProtectedPath("checkpoint_v2", _normal(os.path.join(
            root, "checkpoint-v2")), "subtree"),
        exact("checkpoint_v2_writer_lock", "checkpoint-v2.writer.lock"),
    ]
    temporary_names = (
        "scan_state.json", "argus_intel_store.json",
        "argus_entity_profiles.json", "argus_buy_candidates.json",
        "argus_watchtower.json", "argus_caos_sweeps.json",
        "argus_caos_patrol_ledger.json", "argus_ai_latest.json",
        "argus_event_analysis.json", "argus_macro_analysis.json",
        "argus_news_ja.json", "argus_official_events.json",
        "argus_mover_causes.json", "argus_mc_explain_requests.json",
        "argus_learning_memory.json", "predictions.jsonl",
    )
    entries.extend(ProtectedPath(
        "known_temporary_store", _normal(os.path.join(temp, name)))
        for name in temporary_names)
    entries.extend(extra_paths)
    normalized = []
    for entry in entries:
        if type(entry) is not ProtectedPath or entry.scope not in (
                "exact", "subtree", "prefix") or not entry.family:
            raise ValueError("protected_path_plan_invalid")
        normalized.append(ProtectedPath(
            entry.family, _normal(entry.path), entry.scope))
    return tuple(sorted(normalized, key=lambda row: (
        row.path, row.scope, row.family)))


def _is_relative_to(path: str, root: str) -> bool:
    try:
        return os.path.commonpath((path, root)) == root
    except ValueError:
        return False


def _overlaps_protected(candidate: str, entry: ProtectedPath) -> bool:
    protected = entry.path
    if entry.scope == "prefix":
        return candidate.startswith(protected) or protected.startswith(candidate)
    if entry.scope == "subtree":
        return _is_relative_to(candidate, protected) or \
            _is_relative_to(protected, candidate)
    return candidate == protected or _is_relative_to(candidate, protected) or \
        _is_relative_to(protected, candidate)


def _existing_component_is_safe(path: str, *, leaf: bool) -> bool:
    try:
        details = os.lstat(path)
    except FileNotFoundError:
        return True
    except OSError:
        return False
    if stat.S_ISLNK(details.st_mode):
        return False
    if leaf:
        return stat.S_ISREG(details.st_mode) and details.st_nlink == 1
    return stat.S_ISDIR(details.st_mode)


def _filesystem_path_is_safe(root: str, candidate: str,
                             protected: Sequence[ProtectedPath]) -> bool:
    current = os.path.sep
    root_parts = [part for part in root.split(os.path.sep) if part]
    for part in root_parts:
        current = os.path.join(current, part)
        if os.path.lexists(current) and not _existing_component_is_safe(
                current, leaf=False):
            return False
        if not os.path.lexists(current):
            break
    if os.path.lexists(candidate) and not _existing_component_is_safe(
            candidate, leaf=True):
        return False
    if not os.path.lexists(candidate):
        return True
    try:
        candidate_stat = os.lstat(candidate)
    except OSError:
        return False
    for entry in protected:
        if entry.scope != "exact" or not os.path.lexists(entry.path):
            continue
        try:
            protected_stat = os.lstat(entry.path)
        except OSError:
            return False
        if (candidate_stat.st_dev, candidate_stat.st_ino) == (
                protected_stat.st_dev, protected_stat.st_ino):
            return False
    return True


def resolve_measurement_path(
        *, diagnostics_root: str = CANONICAL_DIAGNOSTICS_ROOT,
        override: Optional[str] = None,
        protected_paths: Optional[Sequence[ProtectedPath]] = None,
        inspect_filesystem: bool = True) -> PathDecision:
    """Resolve a direct child of the dedicated namespace or reject fail-closed."""
    plan = tuple(authoritative_path_plan() if protected_paths is None
                 else protected_paths)
    try:
        if type(diagnostics_root) is not str or not diagnostics_root or \
                len(diagnostics_root) > MAX_PATH_CHARS or "\x00" in diagnostics_root:
            raise ValueError
        root = _normal(diagnostics_root)
        raw = "measurement-v1.json" if override is None else override
        if type(raw) is not str or not raw or len(raw) > MAX_PATH_CHARS or \
                "\x00" in raw:
            raise ValueError
        raw_parts = raw.replace("\\", "/").split("/")
        if ".." in raw_parts:
            raise ValueError
        candidate = _normal(raw if os.path.isabs(raw) else os.path.join(
            root, raw))
        name = os.path.basename(candidate)
        if os.path.dirname(candidate) != root or not name or \
                len(name) > MAX_FILE_NAME_CHARS or name.startswith(".") or \
                not name.endswith(".json") or any(
                    marker in name.lower() for marker in (
                        ".tmp", ".lock", ".previous", "quarantine",
                        "reservation", "pending")):
            raise ValueError
        if not _is_relative_to(candidate, root) or candidate == root or \
                any(_overlaps_protected(candidate, entry) for entry in plan):
            raise ValueError
        if inspect_filesystem and not _filesystem_path_is_safe(
                root, candidate, plan):
            raise ValueError
    except (OSError, TypeError, ValueError):
        safe_root = _normal(diagnostics_root) if type(diagnostics_root) is str \
            and diagnostics_root and "\x00" not in diagnostics_root else ""
        return PathDecision(
            False, "configuration_rejected", safe_root, None, None, plan)
    return PathDecision(True, "ok", root, candidate, name, plan)


def _open_directory_chain(path: str, *, create: bool) -> int:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | \
        getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(os.path.sep, flags)
    try:
        for part in [item for item in path.split(os.path.sep) if item]:
            if create:
                try:
                    os.mkdir(part, DIAGNOSTICS_DIRECTORY_MODE,
                             dir_fd=descriptor)
                except FileExistsError:
                    pass
            next_descriptor = os.open(part, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = next_descriptor
        return descriptor
    except Exception:
        os.close(descriptor)
        raise


def prepare_diagnostics_namespace(decision: PathDecision) -> str:
    """Create/chmod only an already accepted namespace via no-follow dirfds."""
    if type(decision) is not PathDecision or not decision.accepted:
        return "configuration_rejected"
    try:
        descriptor = _open_directory_chain(
            decision.diagnostics_root, create=True)
        try:
            os.fchmod(descriptor, DIAGNOSTICS_DIRECTORY_MODE)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except OSError:
        return "io_failure"
    return "ok"


def _protected_identities(plan: Sequence[ProtectedPath]) -> frozenset[Tuple[int, int]]:
    identities = set()
    for entry in plan:
        if entry.scope != "exact":
            continue
        try:
            details = os.lstat(entry.path)
        except FileNotFoundError:
            continue
        except OSError:
            raise
        identities.add((details.st_dev, details.st_ino))
    return frozenset(identities)


def _leaf_stat(directory_fd: int, name: str) -> Optional[os.stat_result]:
    try:
        details = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(details.st_mode) or details.st_nlink != 1:
        raise OSError(errno.EPERM, "measurement_destination_unsafe")
    return details


def _revalidate_leaf(
        directory_fd: int, name: str,
        protected_identities: frozenset[Tuple[int, int]]) -> Optional[os.stat_result]:
    details = _leaf_stat(directory_fd, name)
    if details is not None and (details.st_dev, details.st_ino) in \
            protected_identities:
        raise OSError(errno.EPERM, "measurement_authority_collision")
    return details


def _raw_leaf_stat(
        directory_fd: int, name: str,
        protected_identities: frozenset[Tuple[int, int]]) -> Optional[os.stat_result]:
    try:
        details = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(details.st_mode) or details.st_nlink not in (1, 2) or \
            (details.st_dev, details.st_ino) in protected_identities:
        raise OSError(errno.EPERM, "measurement_recovery_unsafe")
    return details


class _DuplicateKey(ValueError):
    pass


def _closed_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKey("duplicate_key")
        result[key] = value
    return result


def _reject_constant(_value):
    raise ValueError("non_finite_number")


def _read_leaf_bytes(
        directory_fd: int, name: str, before: os.stat_result) -> bytes:
    descriptor = None
    try:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(name, flags, dir_fd=directory_fd)
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or \
                (opened.st_dev, opened.st_ino, opened.st_nlink) != \
                (before.st_dev, before.st_ino, before.st_nlink) or \
                opened.st_size > measurement.MAX_PERSISTED_BYTES:
            raise OSError(errno.EPERM, "measurement_recovery_unsafe")
        chunks = []
        remaining = measurement.MAX_PERSISTED_BYTES + 1
        while remaining:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        after = os.fstat(descriptor)
        encoded = b"".join(chunks)
        if len(encoded) > measurement.MAX_PERSISTED_BYTES or \
                (after.st_dev, after.st_ino, after.st_size,
                 after.st_mtime_ns, after.st_nlink) != \
                (opened.st_dev, opened.st_ino, opened.st_size,
                 opened.st_mtime_ns, opened.st_nlink):
            raise OSError(errno.EPERM, "measurement_recovery_changed")
        return encoded
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _decode_artifact(encoded: bytes, *, live_policy: bool
                     ) -> Tuple[str, Optional[Dict[str, Any]]]:
    try:
        value = json.loads(
            encoded.decode("utf-8"), object_pairs_hook=_closed_object,
            parse_constant=_reject_constant)
        expected = None if live_policy else (
            value.get("registryPolicySha256") if type(value) is dict else "")
        validation = measurement.validate_artifact(
            value, expected_registry_policy_sha256=expected)
        return (
            "loaded" if validation.valid else validation.code,
            value if validation.valid else None)
    except (_DuplicateKey, UnicodeDecodeError, json.JSONDecodeError,
            RecursionError, TypeError, ValueError):
        return "invalid_artifact", None


class FileOperations:
    """Small injectable surface for deterministic fault tests."""

    def write(self, descriptor: int, data: bytes) -> int:
        return os.write(descriptor, data)

    def fsync_file(self, descriptor: int) -> None:
        os.fsync(descriptor)

    def fsync_directory(self, descriptor: int) -> None:
        os.fsync(descriptor)

    def replace(self, source: str, destination: str,
                directory_fd: int) -> None:
        os.replace(source, destination, src_dir_fd=directory_fd,
                   dst_dir_fd=directory_fd)

    def link(self, source: str, destination: str,
             directory_fd: int) -> None:
        os.link(source, destination, src_dir_fd=directory_fd,
                dst_dir_fd=directory_fd, follow_symlinks=False)

    def unlink(self, name: str, directory_fd: int) -> None:
        os.unlink(name, dir_fd=directory_fd)


def _reconcile_incomplete_transaction(
        operations: FileOperations, directory_fd: int, artifact_name: str,
        recovery_name: str,
        protected_identities: frozenset[Tuple[int, int]]) -> bool:
    """Restore a validated last-known-good copy or remove a duplicate link."""
    recovery = _raw_leaf_stat(
        directory_fd, recovery_name, protected_identities)
    if recovery is None:
        return True
    canonical = _raw_leaf_stat(
        directory_fd, artifact_name, protected_identities)
    same_inode = canonical is not None and \
        (canonical.st_dev, canonical.st_ino) == \
        (recovery.st_dev, recovery.st_ino)
    if same_inode:
        # A crash after backup-link durability but before replacement leaves
        # exactly two names for the prior canonical inode.
        if canonical.st_nlink != 2 or recovery.st_nlink != 2:
            return False
    elif recovery.st_nlink != 1 or \
            (canonical is not None and canonical.st_nlink != 1):
        return False
    try:
        encoded = _read_leaf_bytes(directory_fd, recovery_name, recovery)
    except OSError:
        return False
    if _decode_artifact(encoded, live_policy=False)[0] != "loaded":
        return False
    try:
        recovery_after = _raw_leaf_stat(
            directory_fd, recovery_name, protected_identities)
        canonical_after = _raw_leaf_stat(
            directory_fd, artifact_name, protected_identities)
        if recovery_after is None or \
                (recovery_after.st_dev, recovery_after.st_ino,
                 recovery_after.st_size, recovery_after.st_mtime_ns,
                 recovery_after.st_nlink) != \
                (recovery.st_dev, recovery.st_ino, recovery.st_size,
                 recovery.st_mtime_ns, recovery.st_nlink) or \
                ((canonical_after is None) != (canonical is None)) or \
                (canonical is not None and
                 (canonical_after.st_dev, canonical_after.st_ino,
                  canonical_after.st_size, canonical_after.st_mtime_ns,
                  canonical_after.st_nlink) !=
                 (canonical.st_dev, canonical.st_ino, canonical.st_size,
                  canonical.st_mtime_ns, canonical.st_nlink)):
            return False
        if same_inode:
            operations.unlink(recovery_name, directory_fd)
        else:
            # A distinct recovery inode means a prior replacement was not
            # reported durable.  Deterministically restore the prior artifact.
            operations.replace(recovery_name, artifact_name, directory_fd)
        operations.fsync_directory(directory_fd)
    except OSError:
        return False
    return True


def _cleanup(operations: FileOperations, directory_fd: int,
             names: Iterable[Optional[str]]) -> None:
    for name in names:
        if not name:
            continue
        try:
            operations.unlink(name, directory_fd)
        except FileNotFoundError:
            pass
        except OSError:
            pass


def persist_retention_plan(
        decision: PathDecision, plan: measurement.RetentionPlan, *,
        operations: Optional[FileOperations] = None) -> PersistenceResult:
    """Atomically replace only the accepted diagnostic leaf, with rollback."""
    if type(decision) is not PathDecision or not decision.accepted or \
            decision.artifact_name is None:
        return PersistenceResult("configuration_rejected")
    if type(plan) is not measurement.RetentionPlan or plan.status != "ok" or \
            plan.canonical_bytes is None or plan.artifact is None:
        return PersistenceResult(
            plan.status if type(plan) is measurement.RetentionPlan else
            "serialization_failure")
    try:
        # The artifact is the sole persistence authority.  A precomputed plan
        # buffer is only accepted when it is exactly that canonical encoding.
        canonical_bytes = measurement.canonical_artifact_bytes(plan.artifact)
    except (RecursionError, TypeError, ValueError):
        return PersistenceResult("serialization_failure")
    if plan.canonical_bytes != canonical_bytes:
        return PersistenceResult("serialization_failure")
    ops = operations or FileOperations()
    directory_fd = temp_fd = None
    temp_name = None
    recovery_name = \
        f".{decision.artifact_name}{RECOVERY_FILE_SUFFIX}"
    replaced = recovery_created = False
    previous_existed = False
    try:
        directory_fd = _open_directory_chain(
            decision.diagnostics_root, create=False)
        protected = _protected_identities(decision.protected_paths)
        if not _reconcile_incomplete_transaction(
                ops, directory_fd, decision.artifact_name, recovery_name,
                protected):
            return PersistenceResult("persistence_failed")
        previous = _revalidate_leaf(
            directory_fd, decision.artifact_name, protected)
        previous_existed = previous is not None
        token = secrets.token_hex(12)
        temp_name = f".{decision.artifact_name}.measurement-tmp-{token}"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | \
            getattr(os, "O_NOFOLLOW", 0)
        temp_fd = os.open(
            temp_name, flags, ARTIFACT_FILE_MODE, dir_fd=directory_fd)
        os.fchmod(temp_fd, ARTIFACT_FILE_MODE)
        view = memoryview(canonical_bytes)
        written = 0
        while written < len(view):
            count = ops.write(temp_fd, view[written:])
            if type(count) is not int or count <= 0:
                raise OSError(errno.EIO, "measurement_short_write")
            written += count
        ops.fsync_file(temp_fd)
        os.close(temp_fd)
        temp_fd = None

        # Close the validation/write race immediately before touching the leaf.
        _revalidate_leaf(directory_fd, decision.artifact_name, protected)
        if previous_existed:
            ops.link(decision.artifact_name, recovery_name, directory_fd)
            recovery_created = True
            ops.fsync_directory(directory_fd)
        ops.replace(temp_name, decision.artifact_name, directory_fd)
        temp_name = None
        replaced = True
        installed = _revalidate_leaf(
            directory_fd, decision.artifact_name, protected)
        if installed is None or installed.st_size != len(canonical_bytes):
            raise OSError(errno.EIO, "measurement_install_invalid")
        ops.fsync_directory(directory_fd)
        if recovery_created:
            try:
                ops.unlink(recovery_name, directory_fd)
            except OSError:
                # The new artifact is durable, but report failure while the
                # deterministic prior copy remains.  A later operation will
                # restore it, making this failed call externally atomic.
                return PersistenceResult("persistence_failed")
            recovery_created = False
            # The replacement was already durably committed.  Failure to
            # persist removal of the now-unlinked recovery name is harmless.
            try:
                ops.fsync_directory(directory_fd)
            except OSError:
                pass
        return PersistenceResult("persisted", len(canonical_bytes))
    except (OSError, TypeError, ValueError):
        # After replacement, preserve the recovery name unless restoring the
        # previous-valid inode and its directory entry both succeed.
        if directory_fd is not None and replaced:
            try:
                if recovery_created:
                    ops.replace(recovery_name, decision.artifact_name,
                                directory_fd)
                    recovery_created = False
                elif not previous_existed:
                    ops.unlink(decision.artifact_name, directory_fd)
                ops.fsync_directory(directory_fd)
            except OSError:
                pass
        elif directory_fd is not None and recovery_created:
            # Canonical still names the previous inode.  Cleanup is safe, but
            # failure leaves a second recoverable name rather than losing it.
            try:
                ops.unlink(recovery_name, directory_fd)
                recovery_created = False
                ops.fsync_directory(directory_fd)
            except OSError:
                pass
        return PersistenceResult("persistence_failed")
    finally:
        if temp_fd is not None:
            os.close(temp_fd)
        if directory_fd is not None:
            # Never generically clean the deterministic recovery slot: it may
            # be the only last-known-good inode after a failed rollback.
            _cleanup(ops, directory_fd, (temp_name,))
            os.close(directory_fd)


def persist_artifact(
        decision: PathDecision, artifact: Any, *, now,
        operations: Optional[FileOperations] = None) -> PersistenceResult:
    plan = measurement.plan_retention(artifact, now=now)
    return persist_retention_plan(decision, plan, operations=operations)


def load_artifact(decision: PathDecision) -> LoadResult:
    if type(decision) is not PathDecision or not decision.accepted or \
            decision.artifact_name is None:
        return LoadResult("configuration_rejected", None)
    descriptor = None
    try:
        descriptor = _open_directory_chain(
            decision.diagnostics_root, create=False)
        protected = _protected_identities(decision.protected_paths)
        recovery_name = \
            f".{decision.artifact_name}{RECOVERY_FILE_SUFFIX}"
        if not _reconcile_incomplete_transaction(
                FileOperations(), descriptor, decision.artifact_name,
                recovery_name, protected):
            return LoadResult("io_failure", None)
        before = _revalidate_leaf(
            descriptor, decision.artifact_name, protected)
        if before is None:
            return LoadResult("not_found", None)
        if before.st_size > measurement.MAX_PERSISTED_BYTES:
            return LoadResult("invalid_artifact", None)
        encoded = _read_leaf_bytes(descriptor, decision.artifact_name, before)
        status, value = _decode_artifact(encoded, live_policy=True)
        return LoadResult(status, value)
    except FileNotFoundError:
        return LoadResult("not_found", None)
    except OSError:
        return LoadResult("io_failure", None)
    finally:
        if descriptor is not None:
            os.close(descriptor)


def load_or_reset(
        decision: PathDecision, *, measurement_generation_id: str,
        producer_build_sha: str, instrumentation_coverage_sha256: str,
        reset_at) -> LoadResult:
    loaded = load_artifact(decision)
    if loaded.status == "loaded":
        return loaded
    invalidation = {
        "registry_policy_mismatch": "registry_policy_mismatch",
        "configuration_rejected": "configuration_rejected",
        "invalid_artifact": "artifact_invalid",
        "io_failure": "persistence_failed",
    }.get(loaded.status, "none")
    try:
        reset = measurement.new_artifact(
            measurement_generation_id=measurement_generation_id,
            producer_build_sha=producer_build_sha,
            instrumentation_coverage_sha256=instrumentation_coverage_sha256,
            created_at=reset_at, invalidation_code=invalidation)
    except ValueError:
        return LoadResult("invalid_artifact", None)
    return LoadResult(loaded.status, reset)
