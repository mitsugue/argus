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
    if len(plan.canonical_bytes) > measurement.MAX_PERSISTED_BYTES or \
            not measurement.validate_artifact(plan.artifact).valid:
        return PersistenceResult("serialization_failure")
    ops = operations or FileOperations()
    directory_fd = temp_fd = None
    temp_name = backup_name = None
    replaced = backup_created = False
    previous_existed = False
    try:
        directory_fd = _open_directory_chain(
            decision.diagnostics_root, create=False)
        protected = _protected_identities(decision.protected_paths)
        previous = _revalidate_leaf(
            directory_fd, decision.artifact_name, protected)
        previous_existed = previous is not None
        token = secrets.token_hex(12)
        temp_name = f".{decision.artifact_name}.measurement-tmp-{token}"
        backup_name = f".{decision.artifact_name}.measurement-previous-{token}"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | \
            getattr(os, "O_NOFOLLOW", 0)
        temp_fd = os.open(
            temp_name, flags, ARTIFACT_FILE_MODE, dir_fd=directory_fd)
        os.fchmod(temp_fd, ARTIFACT_FILE_MODE)
        view = memoryview(plan.canonical_bytes)
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
            ops.link(decision.artifact_name, backup_name, directory_fd)
            backup_created = True
            ops.fsync_directory(directory_fd)
        ops.replace(temp_name, decision.artifact_name, directory_fd)
        temp_name = None
        replaced = True
        installed = _revalidate_leaf(
            directory_fd, decision.artifact_name, protected)
        if installed is None or installed.st_size != len(plan.canonical_bytes):
            raise OSError(errno.EIO, "measurement_install_invalid")
        ops.fsync_directory(directory_fd)
        if backup_created:
            ops.unlink(backup_name, directory_fd)
            backup_name = None
        return PersistenceResult("persisted", len(plan.canonical_bytes))
    except (OSError, TypeError, ValueError):
        # A failure after replace restores the exact prior inode/bytes when one
        # existed; otherwise it restores absence.  Rollback remains diagnostic.
        if directory_fd is not None and replaced:
            try:
                if backup_created and backup_name is not None:
                    ops.replace(backup_name, decision.artifact_name,
                                directory_fd)
                    backup_name = None
                elif not previous_existed:
                    ops.unlink(decision.artifact_name, directory_fd)
                ops.fsync_directory(directory_fd)
            except OSError:
                pass
        return PersistenceResult("persistence_failed")
    finally:
        if temp_fd is not None:
            os.close(temp_fd)
        if directory_fd is not None:
            _cleanup(ops, directory_fd, (temp_name, backup_name))
            os.close(directory_fd)


def persist_artifact(
        decision: PathDecision, artifact: Any, *, now,
        operations: Optional[FileOperations] = None) -> PersistenceResult:
    plan = measurement.plan_retention(artifact, now=now)
    return persist_retention_plan(decision, plan, operations=operations)


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


def load_artifact(decision: PathDecision) -> LoadResult:
    if type(decision) is not PathDecision or not decision.accepted or \
            decision.artifact_name is None:
        return LoadResult("configuration_rejected", None)
    descriptor = file_descriptor = None
    try:
        descriptor = _open_directory_chain(
            decision.diagnostics_root, create=False)
        protected = _protected_identities(decision.protected_paths)
        before = _revalidate_leaf(
            descriptor, decision.artifact_name, protected)
        if before is None:
            return LoadResult("not_found", None)
        if before.st_size > measurement.MAX_PERSISTED_BYTES:
            return LoadResult("invalid_artifact", None)
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        file_descriptor = os.open(
            decision.artifact_name, flags, dir_fd=descriptor)
        opened = os.fstat(file_descriptor)
        if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1 or \
                (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
            return LoadResult("configuration_rejected", None)
        chunks = []
        remaining = measurement.MAX_PERSISTED_BYTES + 1
        while remaining:
            chunk = os.read(file_descriptor, min(1024 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        encoded = b"".join(chunks)
        if len(encoded) > measurement.MAX_PERSISTED_BYTES:
            return LoadResult("invalid_artifact", None)
        value = json.loads(
            encoded.decode("utf-8"), object_pairs_hook=_closed_object,
            parse_constant=_reject_constant)
        validation = measurement.validate_artifact(value)
        return LoadResult(
            "loaded" if validation.valid else validation.code,
            value if validation.valid else None)
    except FileNotFoundError:
        return LoadResult("not_found", None)
    except (_DuplicateKey, UnicodeDecodeError, json.JSONDecodeError,
            RecursionError, TypeError, ValueError):
        return LoadResult("invalid_artifact", None)
    except OSError:
        return LoadResult("io_failure", None)
    finally:
        if file_descriptor is not None:
            os.close(file_descriptor)
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
