"""Fail-closed persistent storage contract for mission-tick durability.

The live Render service is dashboard-managed.  This module proves only what
the running process can observe: path containment, filesystem durability
primitives, and free capacity.  It never claims that a Render Disk is attached
merely because ``render.yaml`` describes one.
"""
from __future__ import annotations

import contextlib
import datetime as dt
import fcntl
import hashlib
import json
import os
import re
import shutil
import tempfile
import time
import uuid
from typing import Any, Dict, Mapping, Optional


UTC = dt.timezone.utc
LOCAL_SEAL_SCHEMA = "argus-local-checkpoint-integrity-v1"
LEGACY_FILE_SEAL_SCHEMA = "argus-legacy-checkpoint-file-seal-v1"
LEGACY_FILE_SEAL_SUFFIX = ".legacy-seal.json"
MINIMUM_SAFETY_RESERVE = 64 * 1024 * 1024
MINIMUM_WAL_ALLOWANCE = 8 * 1024 * 1024
MAXIMUM_LEGACY_FILE_SEAL_BYTES = 64 * 1024
DEFAULT_MAXIMUM_CHECKPOINT_BYTES = 512 * 1024 * 1024
JSON_STREAM_CHUNK_BYTES = 1024 * 1024
MAXIMUM_JSON_SCALAR_CHARS = 8 * 1024 * 1024
POST_HOTFIX_TEMP_MARKER = "v1338"
POST_HOTFIX_TEMP_RETENTION_SECONDS = 24 * 60 * 60
#: 2026-10-20 (owner decision): the pre-v13.3.8 temporaries left by the
#: 2026-08-03 OOM incident are no longer needed as evidence (the hotfix has run
#: since August and no open item refers to them). At start they are released:
#: each is recorded (name, size, mtime, SHA-256) before removal, under the same
#: ownership, lock, age and identity rules. Only files written before the
#: cutoff below match; anything newer keeps the no-read evidence contract.
INCIDENT_EVIDENCE_RELEASED = True
INCIDENT_EVIDENCE_RELEASE_BEFORE = dt.datetime(2026, 8, 5, tzinfo=dt.timezone.utc).timestamp()


class PersistentStorageError(RuntimeError):
    """A redacted, operator-actionable persistent-storage failure."""

    error_class = "persistent_storage_unavailable"

    def __init__(self, reason: str, *, details: Optional[Mapping[str, Any]] = None):
        super().__init__(reason)
        self.reason = reason
        self.details = dict(details or {})


def _iso_now() -> str:
    return dt.datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _canonical_chunks(value: Any):
    """Yield canonical JSON without retaining the complete encoding in RAM."""
    encoder = json.JSONEncoder(
        ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    active = set()
    atomic_types = (int, float, bool, type(None))
    # Validate scalars/cycles during the bounded subtree walk, before each
    # encoder call. No second full-graph walk is needed. An invalid later
    # subtree aborts hashing or the atomic temporary writer, never commits it.
    # Encode bounded subtrees through the standard library's C encoder. The
    # previous deep iterencode chain crossed Python generators for every
    # punctuation token, once again for each integrity verification.
    def fits(current, remaining):
        remaining[0] -= 1
        if remaining[0] < 0:
            return False
        kind = type(current)
        if kind is str:
            if len(current) > MAXIMUM_JSON_SCALAR_CHARS:
                raise PersistentStorageError("checkpoint_json_scalar_too_large",
                    details={"maximumCharacters": MAXIMUM_JSON_SCALAR_CHARS})
            remaining[1] -= len(current)
            return remaining[1] >= 0
        if kind is dict or kind in (list, tuple):
            identity = id(current)
            if identity in active:
                raise PersistentStorageError("checkpoint_json_cycle_detected")
            active.add(identity)
            try:
                if kind is dict:
                    for key, item in current.items():
                        if not fits(key, remaining) or not fits(item, remaining):
                            return False
                else:
                    for item in current:
                        if not fits(item, remaining):
                            return False
            finally:
                active.remove(identity)
        elif kind not in atomic_types:
            # Subclasses and unsupported values retain the existing validator
            # and standard encoder path rather than entering the fast path.
            return False
        return True

    def parts(current):
        if fits(current, [1024, 32 * 1024]):
            yield encoder.encode(current)
        elif type(current) is dict and all(isinstance(key, str) for key in current):
            identity = id(current)
            active.add(identity)
            try:
                yield "{"
                for index, key in enumerate(sorted(current)):
                    if index:
                        yield ","
                    yield from parts(key)
                    yield ":"
                    yield from parts(current[key])
                yield "}"
            finally:
                active.remove(identity)
        elif type(current) in (list, tuple):
            identity = id(current)
            active.add(identity)
            try:
                yield "["
                # Share the traversal budget across adjacent items. This keeps
                # numeric paths and short records in bounded C-encoder batches
                # without building a second full list or JSON representation.
                batch = []
                remaining = [1024, 32 * 1024]
                emitted = False
                for item in current:
                    if fits(item, remaining):
                        batch.append(item)
                        continue
                    if batch:
                        if emitted:
                            yield ","
                        yield encoder.encode(batch)[1:-1]
                        emitted = True
                        batch = []
                    if emitted:
                        yield ","
                    yield from parts(item)
                    emitted = True
                    remaining = [1024, 32 * 1024]
                if batch:
                    if emitted:
                        yield ","
                    yield encoder.encode(batch)[1:-1]
                yield "]"
            finally:
                active.remove(identity)
        else:
            _validate_streamable_value(current)
            yield from encoder.iterencode(current)

    pending = []
    pending_chars = 0
    for text in parts(value):
        pending.append(text)
        pending_chars += len(text)
        if pending_chars >= 64 * 1024:
            encoded = "".join(pending).encode("utf-8")
            pending.clear()
            pending_chars = 0
            for offset in range(0, len(encoded), JSON_STREAM_CHUNK_BYTES):
                yield encoded[offset:offset + JSON_STREAM_CHUNK_BYTES]
    if pending:
        encoded = "".join(pending).encode("utf-8")
        for offset in range(0, len(encoded), JSON_STREAM_CHUNK_BYTES):
            yield encoded[offset:offset + JSON_STREAM_CHUNK_BYTES]


def _validate_streamable_value(value: Any) -> None:
    """Bound JSON scalar tokens before the encoder can allocate one whole.

    ``JSONEncoder.iterencode`` streams containers but emits each string as one
    token.  This stateless walk retains no second object graph and prevents a
    single source scalar from bypassing the streaming memory bound.
    """
    active = set()

    def visit(current: Any) -> None:
        kind = type(current)
        if kind in (int, float, bool, type(None)):
            return
        if kind is str or isinstance(current, str):
            if len(current) > MAXIMUM_JSON_SCALAR_CHARS:
                raise PersistentStorageError(
                    "checkpoint_json_scalar_too_large",
                    details={"maximumCharacters": MAXIMUM_JSON_SCALAR_CHARS})
            return
        if kind is dict or (kind is not list and kind is not tuple and isinstance(current, Mapping)):
            identity = id(current)
            if identity in active:
                raise PersistentStorageError("checkpoint_json_cycle_detected")
            active.add(identity)
            try:
                for key, item in current.items():
                    visit(key)
                    visit(item)
            finally:
                active.discard(identity)
        elif kind in (list, tuple) or isinstance(current, (list, tuple)):
            identity = id(current)
            if identity in active:
                raise PersistentStorageError("checkpoint_json_cycle_detected")
            active.add(identity)
            try:
                for item in current:
                    visit(item)
            finally:
                active.discard(identity)

    visit(value)


def _canonical_sha256(value: Any) -> str:
    digest = hashlib.sha256()
    for chunk in _canonical_chunks(value):
        digest.update(chunk)
    return digest.hexdigest()


def _without_seal(blob: Mapping[str, Any]) -> Dict[str, Any]:
    return {key: value for key, value in blob.items()
            if key != "localCheckpointIntegrity"}


def seal_checkpoint(blob: Mapping[str, Any]) -> Dict[str, Any]:
    sealed = dict(_without_seal(blob))
    sealed["localCheckpointIntegrity"] = {
        "schemaVersion": LOCAL_SEAL_SCHEMA,
        "algorithm": "sha256",
        "snapshotHash": _canonical_sha256(sealed),
    }
    return sealed


def verify_checkpoint(blob: Any, *, require_seal: bool = True) -> bool:
    if not isinstance(blob, dict) or \
            blob.get("schemaVersion") != "argus-durable-v3":
        return False
    seal = blob.get("localCheckpointIntegrity")
    if not isinstance(seal, dict):
        return not require_seal
    if seal.get("schemaVersion") != LOCAL_SEAL_SCHEMA or \
            seal.get("algorithm") != "sha256":
        return False
    expected = _canonical_sha256(_without_seal(blob))
    return bool(seal.get("snapshotHash") == expected)


def production_mode(environ: Optional[Mapping[str, str]] = None) -> bool:
    env = os.environ if environ is None else environ
    if str(env.get("ARGUS_DURABILITY_TEST_MODE", "")).strip() == "1":
        return False
    return str(env.get("RENDER", "")).strip().lower() in (
        "1", "true", "yes") or \
        str(env.get("ARGUS_RUNTIME_ENV", "")).strip().lower() == "production"


def configured_paths(
    environ: Optional[Mapping[str, str]] = None,
        *, production: Optional[bool] = None) -> Dict[str, str]:
    env = os.environ if environ is None else environ
    is_production = production_mode(env) if production is None else production
    root_default = "/var/data" if is_production else tempfile.gettempdir()
    root = os.path.realpath(str(
        env.get("ARGUS_PERSISTENT_ROOT") or root_default))

    def value(name: str, filename: str) -> str:
        return os.path.abspath(str(env.get(name) or os.path.join(root, filename)))

    return {
        "root": root,
        "wal": value("ARGUS_MISSION_WAL_FILE", "argus_mission_tick.wal"),
        "checkpoint": value(
            "ARGUS_OSINT_PERSIST_FILE", "argus_osint_memory.json"),
        "lease": value(
            "ARGUS_MISSION_LEASE_FILE", "argus_mission_tick.lease"),
        "cursor": value(
            "ARGUS_MISSION_CURSOR_FILE", "argus_mission_tick.cursor.json"),
        "receipt": value(
            "ARGUS_MISSION_RECEIPT_FILE", "argus_mission_tick.receipt.json"),
        "receiptQueue": value(
            "ARGUS_REMOTE_RECEIPT_QUEUE_FILE",
            "argus_remote_receipt_queue.json"),
        "recovery": value(
            "ARGUS_REMOTE_RECOVERY_FILE",
            "argus_remote_recovery.json"),
        "recoveryNonceState": value(
            "ARGUS_REMOTE_RECOVERY_NONCE_STATE_FILE",
            "argus_remote_recovery_nonce_state.json"),
        "recoveryNonceHistory": value(
            "ARGUS_REMOTE_RECOVERY_NONCE_HISTORY_FILE",
            "argus_remote_recovery_nonce_history.json"),
        "recoveryNonceHistoryHead": value(
            "ARGUS_REMOTE_RECOVERY_NONCE_HISTORY_HEAD_FILE",
            "argus_remote_recovery_nonce_history.head.json"),
        "tempDirectory": os.path.abspath(str(
            env.get("ARGUS_CHECKPOINT_TEMP_DIR") or root)),
    }


def _under(root: str, path: str) -> bool:
    try:
        return os.path.commonpath((root, path)) == root
    except ValueError:
        return False


def _resolve_candidate(path: str) -> str:
    parent = os.path.realpath(os.path.dirname(os.path.abspath(path)) or ".")
    return os.path.join(parent, os.path.basename(path))


def _file_bytes(path: str) -> int:
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def _stream_sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _legacy_file_seal_path(path: str) -> str:
    return os.path.abspath(path) + LEGACY_FILE_SEAL_SUFFIX


def _file_identity(stat_result: os.stat_result) -> tuple:
    return (
        stat_result.st_dev, stat_result.st_ino, stat_result.st_size,
        stat_result.st_mtime_ns,
    )


def verify_legacy_checkpoint_file_seal(
        path: str, *, expected_identity: Optional[tuple] = None
        ) -> Dict[str, Any]:
    """Verify the one-time 13.3.0 raw checkpoint migration receipt.

    The legacy process could only write an unsealed ``argus-durable-v3`` JSON
    file. Operations copied that stable file to the persistent disk with a
    streaming SHA-256 and an fsynced sidecar receipt. The sidecar is accepted
    only when it is bound to this exact path, size and byte hash; arbitrary
    unsealed checkpoints remain rejected.
    """
    checkpoint = os.path.abspath(path)
    sidecar = _legacy_file_seal_path(checkpoint)
    for candidate, reason in (
            (checkpoint, "legacy_checkpoint_symlink_rejected"),
            (sidecar, "legacy_checkpoint_seal_symlink_rejected")):
        if os.path.lexists(candidate) and os.path.islink(candidate):
            raise PersistentStorageError(reason)
    if not os.path.isfile(checkpoint):
        raise FileNotFoundError(checkpoint)
    if not os.path.isfile(sidecar):
        raise PersistentStorageError("legacy_checkpoint_seal_missing")
    if os.path.getsize(sidecar) > MAXIMUM_LEGACY_FILE_SEAL_BYTES:
        raise PersistentStorageError("legacy_checkpoint_seal_oversized")
    try:
        with open(sidecar, encoding="utf-8") as handle:
            manifest = json.load(handle)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PersistentStorageError(
            "legacy_checkpoint_seal_invalid") from exc
    if not isinstance(manifest, dict):
        raise PersistentStorageError("legacy_checkpoint_seal_invalid")
    unsigned = {
        key: value for key, value in manifest.items()
        if key != "recordHash"
    }
    record_hash = hashlib.sha256(_canonical(unsigned)).hexdigest()
    if manifest.get("schemaVersion") != LEGACY_FILE_SEAL_SCHEMA or \
            manifest.get("algorithm") != "sha256" or \
            manifest.get("checkpointSchemaVersion") != "argus-durable-v3" or \
            os.path.abspath(str(manifest.get("checkpointPath") or "")) != \
            checkpoint or \
            manifest.get("recordHash") != record_hash:
        raise PersistentStorageError("legacy_checkpoint_seal_invalid")
    before = os.stat(checkpoint, follow_symlinks=False)
    actual_hash = _stream_sha256(checkpoint)
    after = os.stat(checkpoint, follow_symlinks=False)
    stable_identity = _file_identity(before) == _file_identity(after)
    if expected_identity is not None:
        stable_identity = stable_identity and \
            _file_identity(after) == expected_identity
    if not stable_identity:
        raise PersistentStorageError("legacy_checkpoint_changed_during_read")
    if int(manifest.get("fileBytes") or -1) != after.st_size or \
            manifest.get("fileSha256") != actual_hash:
        raise PersistentStorageError("legacy_checkpoint_file_hash_mismatch")
    return {
        "verified": True,
        "schemaVersion": LEGACY_FILE_SEAL_SCHEMA,
        "checkpointPath": checkpoint,
        "sidecarPath": sidecar,
        "fileBytes": after.st_size,
        "fileSha256": actual_hash,
        "recordHash": record_hash,
    }


def _temp_bytes(directory: str, checkpoint_name: str) -> int:
    total = 0
    try:
        with os.scandir(directory) as entries:
            for entry in entries:
                if entry.name.startswith(checkpoint_name + ".") and \
                        (entry.name.endswith(".tmp") or
                         entry.name.endswith(".v1338-tmp") or
                         ".bootstrap-" in entry.name or
                         ".v1338-bootstrap-" in entry.name):
                    with contextlib.suppress(OSError):
                        total += entry.stat(follow_symlinks=False).st_size
    except OSError:
        return 0
    return total


def _maximum_checkpoint_bytes(environ: Optional[Mapping[str, str]] = None) -> int:
    env = os.environ if environ is None else environ
    raw = str(env.get("ARGUS_CHECKPOINT_MAX_BYTES") or "").strip()
    if not raw:
        return DEFAULT_MAXIMUM_CHECKPOINT_BYTES
    try:
        value = int(raw)
    except ValueError as exc:
        raise PersistentStorageError(
            "checkpoint_maximum_bytes_invalid") from exc
    if value < 1024 * 1024:
        raise PersistentStorageError("checkpoint_maximum_bytes_invalid")
    return value


def _writer_pid_has_open_inode(pid: int, *, device: int, inode: int):
    """Linux ownership proof for an old PID-stamped temporary file.

    ``None`` is deliberately fail-closed: platforms without procfs may report
    abandoned files, but may not delete them automatically.
    """
    proc_root = "/proc"
    if not os.path.isdir(proc_root):
        return None
    process_root = os.path.join(proc_root, str(int(pid)))
    if not os.path.exists(process_root):
        return False
    fd_root = os.path.join(process_root, "fd")
    if not os.path.isdir(fd_root):
        return None
    try:
        names = os.listdir(fd_root)
    except OSError:
        return None
    for name in names:
        try:
            fd_stat = os.stat(os.path.join(fd_root, name))
        except OSError:
            continue
        if fd_stat.st_dev == device and fd_stat.st_ino == inode:
            return True
    return False


def _release_incident_evidence(entry, metadata, writer_pid, owner_open, observed_at,
                               cleanup, directory) -> Dict[str, Any]:
    """Record, then remove, one owner-released pre-hotfix temporary."""
    descriptor = None
    lock_acquired = False
    digest = None
    removed = False
    try:
        descriptor = os.open(entry.path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        if _file_identity(os.fstat(descriptor)) == _file_identity(metadata):
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            lock_acquired = True
            sha = hashlib.sha256()
            while True:
                block = os.read(descriptor, 4 * 1024 * 1024)
                if not block:
                    break
                sha.update(block)
            digest = sha.hexdigest()
    except (BlockingIOError, OSError):
        lock_acquired = False
    age_seconds = max(0, int(observed_at - metadata.st_mtime))
    safe = bool(owner_open is False and lock_acquired and digest
                and age_seconds >= POST_HOTFIX_TEMP_RETENTION_SECONDS)
    record = {"name": entry.name, "writerPid": writer_pid, "bytes": metadata.st_size,
              "device": metadata.st_dev, "inode": metadata.st_ino,
              "mtimeNs": metadata.st_mtime_ns, "ctimeNs": metadata.st_ctime_ns,
              "ageSeconds": age_seconds, "sha256": digest,
              "writerHasOpenInode": owner_open, "exclusiveLockAcquired": lock_acquired,
              "contentOpenAttempted": True, "postHotfix": False,
              "retentionSeconds": POST_HOTFIX_TEMP_RETENTION_SECONDS,
              "retentionSatisfied": age_seconds >= POST_HOTFIX_TEMP_RETENTION_SECONDS,
              "classification": "released_incident_evidence" if safe else "retained_incident_evidence",
              "safeToRemove": safe, "removed": False}
    if cleanup and safe:
        # Recorded before removal (2026-10-20 owner): one line per file.
        print(json.dumps({"event": "incident_evidence_release",
                          **{k: record[k] for k in ("name", "bytes", "mtimeNs", "sha256")}},
                         sort_keys=True), flush=True)
        try:
            current = os.stat(entry.path, follow_symlinks=False)
            if _file_identity(current) == _file_identity(metadata):
                os.unlink(entry.path)
                _fsync_directory(directory)
                removed = True
        except OSError:
            removed = False
    if descriptor is not None:
        with contextlib.suppress(OSError):
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        with contextlib.suppress(OSError):
            os.close(descriptor)
    record["removed"] = removed
    return record


def reconcile_abandoned_checkpoint_temps(
        path: str, *, temp_directory: Optional[str] = None,
        cleanup: bool = False, now: Optional[float] = None,
        owner_probe=_writer_pid_has_open_inode,
        release_incident_evidence: bool = False) -> Dict[str, Any]:
    """Stat-only discovery and conservative recovery of writer temporaries.

    Pre-v13.3.8 temporaries are immutable incident evidence.  A post-hotfix
    file is removable only after the documented retention period, when its
    PID-stamped writer has no descriptor for the exact device/inode *and* an
    exclusive non-blocking flock succeeds.  Contents are never loaded.
    """
    final = os.path.abspath(path)
    directory = os.path.realpath(temp_directory or os.path.dirname(final))
    base = os.path.basename(final)
    pattern = re.compile(
        rf"^{re.escape(base)}\.(\d+)\.([0-9a-f]{{32}})\."
        rf"(?:(v1338)-)?(tmp|bootstrap-[A-Za-z0-9_.-]+)$")
    observed_at = float(time.time() if now is None else now)
    entries = []
    removed = 0
    retained = 0
    try:
        candidates = list(os.scandir(directory))
    except OSError as exc:
        return {"scanned": False, "errorClass": type(exc).__name__,
                "detectedCount": 0, "removedCount": 0,
                "retainedCount": 0, "entries": []}
    for entry in candidates:
        match = pattern.fullmatch(entry.name)
        if not match or entry.is_symlink():
            continue
        try:
            metadata = entry.stat(follow_symlinks=False)
        except OSError:
            continue
        if not entry.is_file(follow_symlinks=False):
            continue
        writer_pid = int(match.group(1))
        post_hotfix = match.group(3) == POST_HOTFIX_TEMP_MARKER
        owner_open = owner_probe(
            writer_pid, device=metadata.st_dev, inode=metadata.st_ino)
        lock_acquired = False
        content_open_attempted = False
        descriptor = None
        released = bool(release_incident_evidence and not post_hotfix
                        and metadata.st_mtime < INCIDENT_EVIDENCE_RELEASE_BEFORE)
        if released:
            entries.append(_release_incident_evidence(
                entry, metadata, writer_pid, owner_open, observed_at, cleanup, directory))
            if entries[-1]["removed"]:
                removed += 1
            else:
                retained += 1
            continue
        # A pre-hotfix file is immutable incident evidence.  Even opening its
        # inode would violate the evidence-retention contract and can update
        # access metadata on some filesystems.  Only V13.3.8-owned ordinary
        # temporaries enter the descriptor/flock cleanup path.
        if post_hotfix:
            content_open_attempted = True
            try:
                flags = os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
                descriptor = os.open(entry.path, flags)
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                lock_acquired = True
            except (BlockingIOError, OSError):
                lock_acquired = False
        age_seconds = max(0, int(observed_at - metadata.st_mtime))
        retention_satisfied = bool(
            post_hotfix and age_seconds >= POST_HOTFIX_TEMP_RETENTION_SECONDS)
        safe = bool(owner_open is False and lock_acquired and
                    retention_satisfied)
        classification = (
            "ordinary_post_hotfix_temp_cleanup_eligible" if safe else
            "retained_post_hotfix_temp" if post_hotfix else
            "retained_incident_evidence")
        removed_this = False
        if cleanup and safe:
            try:
                current = os.stat(entry.path, follow_symlinks=False)
                if _file_identity(current) == _file_identity(metadata):
                    os.unlink(entry.path)
                    _fsync_directory(directory)
                    removed += 1
                    removed_this = True
            except OSError:
                removed_this = False
        if not removed_this:
            retained += 1
        if descriptor is not None:
            with contextlib.suppress(OSError):
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            with contextlib.suppress(OSError):
                os.close(descriptor)
        entries.append({
            "name": entry.name,
            "writerPid": writer_pid,
            "bytes": metadata.st_size,
            "device": metadata.st_dev,
            "inode": metadata.st_ino,
            "mtimeNs": metadata.st_mtime_ns,
            "ctimeNs": metadata.st_ctime_ns,
            "ageSeconds": age_seconds,
            "writerHasOpenInode": owner_open,
            "exclusiveLockAcquired": lock_acquired,
            "contentOpenAttempted": content_open_attempted,
            "postHotfix": post_hotfix,
            "retentionSeconds": POST_HOTFIX_TEMP_RETENTION_SECONDS,
            "retentionSatisfied": retention_satisfied,
            "classification": classification,
            "safeToRemove": safe,
            "removed": removed_this,
        })
    return {"scanned": True, "errorClass": None,
            "detectedCount": len(entries), "removedCount": removed,
            "retainedCount": retained,
            "retainedIncidentEvidenceCount": sum(
                row["classification"] == "retained_incident_evidence"
                for row in entries),
            "releasedIncidentEvidenceCount": sum(
                1 for row in entries
                if row["classification"] == "released_incident_evidence" and row["removed"]),
            "releasedIncidentEvidenceBytes": sum(
                int(row["bytes"]) for row in entries
                if row["classification"] == "released_incident_evidence" and row["removed"]),
            "entries": entries}


# 2026-10-20 (owner): the recovery-pair save stages a full checkpoint copy and
# a sidecar candidate next to the checkpoint and removes them in `finally`; a
# process killed mid-save (deploy restart, OOM) leaves them behind, and the
# temporary reconciliation above never matched their names. 107 copies
# (about 9.4 GiB) filled the disk and the start stopped on free space. The
# same rules apply to them: the PID-stamped writer holds no descriptor for the
# exact inode, an exclusive non-blocking flock succeeds, the 24-hour retention
# has passed, and the identity is unchanged at removal. Pre-hotfix incident
# evidence never matches these names and stays untouched.
STAGING_RETENTION_SECONDS = POST_HOTFIX_TEMP_RETENTION_SECONDS
WORK_DIRECTORY_PREFIXES = (".analysis-recovery-", ".analysis-compact-")
WORK_DIRECTORY_MAX_FILES = 5000
#: The last start's reconciliation, kept even when the free-space check then fails.
LAST_RECONCILIATION: Dict[str, Any] = {}


def _record_before_removal(event: str, detected: int, detected_bytes: int, eligible: int,
                           eligible_bytes: int) -> None:
    """One log line with counts and sizes before anything is removed (no names)."""
    print(json.dumps({"event": event, "detectedCount": detected, "detectedBytes": detected_bytes,
                      "eligibleCount": eligible, "eligibleBytes": eligible_bytes},
                     sort_keys=True), flush=True)


def _flock_removable(path: str) -> bool:
    descriptor = None
    try:
        descriptor = os.open(path, os.O_RDWR | getattr(os, "O_NOFOLLOW", 0))
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        return True
    except (BlockingIOError, OSError):
        return False
    finally:
        if descriptor is not None:
            with contextlib.suppress(OSError):
                os.close(descriptor)


def _staging_patterns(checkpoint_name: str, sidecar_name: str):
    hexid = r"\.(\d+)\.[0-9a-f]{32}\."
    stage = (rf"(?:{re.escape(checkpoint_name)}{hexid}recovery-pair-checkpoint"
             rf"|{re.escape(sidecar_name)}{hexid}candidate)")
    return (re.compile(rf"^({stage})(\.writer\.lock)?$"),
            # A temporary of the staged copy itself (post-hotfix marker only).
            re.compile(rf"^{stage}\.(\d+)\.[0-9a-f]{{32}}\.v1338-(?:tmp|bootstrap-[A-Za-z0-9_.-]+)$"))


def reconcile_abandoned_recovery_staging(
        temp_directory: str, *, checkpoint_name: str, sidecar_name: str,
        cleanup: bool = False, now: Optional[float] = None,
        owner_probe=_writer_pid_has_open_inode) -> Dict[str, Any]:
    """Counts and sizes are recorded before anything is removed."""
    staged, nested = _staging_patterns(checkpoint_name, sidecar_name)
    observed_at = float(time.time() if now is None else now)
    rows = []
    try:
        candidates = list(os.scandir(os.path.realpath(temp_directory)))
    except OSError as exc:
        return {"scanned": False, "errorClass": type(exc).__name__, "detectedCount": 0,
                "detectedBytes": 0, "removedCount": 0, "removedBytes": 0,
                "retainedCount": 0, "retainedBytes": 0}
    for entry in candidates:
        match = staged.fullmatch(entry.name)
        writer_pid = None
        if match:
            groups = [g for g in match.groups()[1:] if g and g.isdigit()]
            writer_pid = int(groups[0]) if groups else None
        else:
            inner = nested.fullmatch(entry.name)
            if inner:
                digits = [g for g in inner.groups() if g and g.isdigit()]
                writer_pid = int(digits[-1]) if digits else None
        if writer_pid is None or entry.is_symlink() or not entry.is_file(follow_symlinks=False):
            continue
        try:
            metadata = entry.stat(follow_symlinks=False)
        except OSError:
            continue
        rows.append((entry, metadata, writer_pid))
    detected_bytes = sum(int(m.st_size) for _, m, _ in rows)
    eligible = []
    for entry, metadata, writer_pid in rows:
        owner_open = owner_probe(writer_pid, device=metadata.st_dev, inode=metadata.st_ino)
        age = max(0, int(observed_at - metadata.st_mtime))
        if owner_open is False and age >= STAGING_RETENTION_SECONDS and _flock_removable(entry.path):
            eligible.append((entry, metadata))
    if rows:
        _record_before_removal("abandoned_recovery_staging", len(rows), detected_bytes,
                               len(eligible), sum(int(m.st_size) for _, m in eligible))
    removed = removed_bytes = 0
    for entry, metadata in eligible:
        if cleanup:
            try:
                current = os.stat(entry.path, follow_symlinks=False)
                if _file_identity(current) == _file_identity(metadata):
                    os.unlink(entry.path)
                    removed += 1
                    removed_bytes += int(metadata.st_size)
            except OSError:
                pass
    if removed:
        with contextlib.suppress(OSError):
            _fsync_directory(os.path.realpath(temp_directory))
    return {"scanned": True, "errorClass": None, "detectedCount": len(rows),
            "detectedBytes": detected_bytes, "eligibleCount": len(eligible),
            "eligibleBytes": sum(int(m.st_size) for _, m in eligible),
            "removedCount": removed, "removedBytes": removed_bytes,
            "retainedCount": len(rows) - removed, "retainedBytes": detected_bytes - removed_bytes}


def _open_inodes_of_any_process() -> Optional[set]:
    """Every (device, inode) open in any process, or None when procfs cannot prove it."""
    if not os.path.isdir("/proc"):
        return None
    found = set()
    try:
        pids = [name for name in os.listdir("/proc") if name.isdigit()]
    except OSError:
        return None
    for pid in pids:
        fd_root = os.path.join("/proc", pid, "fd")
        try:
            names = os.listdir(fd_root)
        except FileNotFoundError:
            continue
        except OSError:
            return None
        for name in names:
            try:
                st = os.stat(os.path.join(fd_root, name))
            except OSError:
                continue
            found.add((st.st_dev, st.st_ino))
    return found


def reconcile_abandoned_work_directories(
        root: str, *, cleanup: bool = False, now: Optional[float] = None,
        open_inodes=_open_inodes_of_any_process) -> Dict[str, Any]:
    """Temporary work directories of the analysis-history recovery/compaction.

    Their names carry no writer PID, so the proof is stricter: no process has
    any of their files open (procfs over all processes; unprovable keeps
    them), every file and the directory are older than the retention, the
    files can be flocked, and each file is unchanged at removal."""
    observed_at = float(time.time() if now is None else now)
    root = os.path.realpath(root)
    directories = []
    try:
        entries = list(os.scandir(root))
    except OSError as exc:
        return {"scanned": False, "errorClass": type(exc).__name__, "detectedCount": 0,
                "detectedBytes": 0, "removedCount": 0, "removedBytes": 0,
                "retainedCount": 0, "retainedBytes": 0}
    for entry in entries:
        if (entry.name.startswith(WORK_DIRECTORY_PREFIXES) and not entry.is_symlink()
                and entry.is_dir(follow_symlinks=False)):
            directories.append(entry.path)
    inventory = []
    for directory in directories:
        files, newest, size, bounded = [], os.lstat(directory).st_mtime, 0, False
        for current, dirs, names in os.walk(directory, followlinks=False):
            for name in names:
                path = os.path.join(current, name)
                try:
                    st = os.lstat(path)
                except OSError:
                    continue
                if not os.path.isfile(path) or os.path.islink(path):
                    bounded = True          # anything unexpected keeps the directory
                    continue
                files.append((path, st))
                size += int(st.st_size)
                newest = max(newest, st.st_mtime)
            for name in dirs:
                with contextlib.suppress(OSError):
                    newest = max(newest, os.lstat(os.path.join(current, name)).st_mtime)
            if len(files) > WORK_DIRECTORY_MAX_FILES:
                bounded = True
                break
        inventory.append((directory, files, size, newest, bounded))
    detected_bytes = sum(item[2] for item in inventory)
    in_use = open_inodes() if inventory else set()
    eligible = []
    for directory, files, size, newest, bounded in inventory:
        if bounded or in_use is None or observed_at - newest < STAGING_RETENTION_SECONDS:
            continue
        if any((st.st_dev, st.st_ino) in in_use for _, st in files):
            continue
        if not all(_flock_removable(path) for path, _ in files):
            continue
        eligible.append((directory, files, size))
    if inventory:
        _record_before_removal("abandoned_work_directories", len(inventory), detected_bytes,
                               len(eligible), sum(item[2] for item in eligible))
    removed = removed_bytes = 0
    for directory, files, size in eligible:
        changed = False
        for path, st in files:
            try:
                if _file_identity(os.stat(path, follow_symlinks=False)) != _file_identity(st):
                    changed = True
                    break
            except OSError:
                changed = True
                break
        if changed or not cleanup:
            continue
        try:
            for path, _ in files:
                os.unlink(path)
            for current, dirs, _ in sorted(os.walk(directory), key=lambda w: -len(w[0])):
                os.rmdir(current)
            removed += 1
            removed_bytes += size
        except OSError:
            continue
    if removed:
        with contextlib.suppress(OSError):
            _fsync_directory(root)
    return {"scanned": True, "errorClass": None, "detectedCount": len(inventory),
            "detectedBytes": detected_bytes, "eligibleCount": len(eligible),
            "eligibleBytes": sum(item[2] for item in eligible),
            "removedCount": removed, "removedBytes": removed_bytes,
            "retainedCount": len(inventory) - removed, "retainedBytes": detected_bytes - removed_bytes,
            "openInodesProven": in_use is not None}


def required_free_bytes(*, checkpoint_bytes: int, wal_bytes: int) -> int:
    """Capacity for current + temp + WAL growth + a dynamic safety reserve."""
    checkpoint = max(1, int(checkpoint_bytes))
    wal = max(0, int(wal_bytes))
    safety = max(MINIMUM_SAFETY_RESERVE, checkpoint)
    wal_growth = max(MINIMUM_WAL_ALLOWANCE, wal * 4)
    return checkpoint * 2 + wal_growth + safety


def _fsync_directory(path: str) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def validate_storage(
        paths: Mapping[str, str], *, production: bool,
        disk_usage_fn=shutil.disk_usage,
        approved_root: Optional[str] = None,
        allow_temporary_root_for_test: bool = False) -> Dict[str, Any]:
    """Probe the runtime mount without exposing durable payload contents."""
    root = os.path.realpath(paths["root"])
    if approved_root is not None and root != os.path.realpath(approved_root):
        raise PersistentStorageError("persistent_root_configuration_drift")
    if not os.path.exists(root):
        raise PersistentStorageError("persistent_root_missing")
    if not os.path.isdir(root):
        raise PersistentStorageError("persistent_root_not_directory")
    if not os.access(root, os.W_OK | os.X_OK):
        raise PersistentStorageError("persistent_root_unwritable")

    resolved: Dict[str, str] = {"root": root}
    for key in (
            "wal", "checkpoint", "lease", "cursor", "receipt",
            "receiptQueue", "recovery", "recoveryNonceState",
            "recoveryNonceHistory", "recoveryNonceHistoryHead"):
        raw = os.path.abspath(paths[key])
        candidate = _resolve_candidate(raw)
        permitted_test_path = bool(
            allow_temporary_root_for_test and _under(root, candidate))
        if production and raw.startswith("/tmp/") and \
                not permitted_test_path:
            raise PersistentStorageError(f"{key}_temporary_path_rejected")
        if os.path.lexists(raw) and os.path.islink(raw):
            raise PersistentStorageError(f"{key}_symlink_rejected")
        if not _under(root, candidate):
            raise PersistentStorageError(f"{key}_outside_persistent_root")
        resolved[key] = candidate

    temp_directory = os.path.realpath(paths["tempDirectory"])
    if not _under(root, temp_directory):
        raise PersistentStorageError("temp_outside_persistent_root")
    if not os.path.isdir(temp_directory):
        raise PersistentStorageError("temp_directory_missing")
    resolved["tempDirectory"] = temp_directory

    root_device = os.stat(root).st_dev
    checkpoint_device = os.stat(
        os.path.dirname(resolved["checkpoint"])).st_dev
    temp_device = os.stat(temp_directory).st_dev
    if root_device != checkpoint_device or checkpoint_device != temp_device:
        raise PersistentStorageError("checkpoint_temp_filesystem_mismatch")

    probe_name = f".argus-storage-probe-{os.getpid()}-{uuid.uuid4().hex}"
    probe = os.path.join(temp_directory, probe_name)
    published = os.path.join(root, probe_name + ".published")
    payload = os.urandom(32)
    try:
        with open(probe, "xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        with open(probe, "rb") as handle:
            if handle.read() != payload:
                raise PersistentStorageError("storage_probe_readback_failed")
        os.replace(probe, published)
        _fsync_directory(root)
        with open(published, "rb") as handle:
            if handle.read() != payload:
                raise PersistentStorageError("atomic_rename_readback_failed")
        os.unlink(published)
        _fsync_directory(root)
    except PersistentStorageError:
        raise
    except PermissionError as exc:
        raise PersistentStorageError("persistent_root_unwritable") from exc
    except OSError as exc:
        raise PersistentStorageError(
            f"storage_durability_probe_failed:{type(exc).__name__}") from exc
    finally:
        with contextlib.suppress(OSError):
            os.unlink(probe)
        with contextlib.suppress(OSError):
            os.unlink(published)

    abandoned = reconcile_abandoned_checkpoint_temps(
        resolved["checkpoint"], temp_directory=temp_directory,
        cleanup=bool(production),
        release_incident_evidence=bool(production) and INCIDENT_EVIDENCE_RELEASED)
    staging = reconcile_abandoned_recovery_staging(
        temp_directory, checkpoint_name=os.path.basename(resolved["checkpoint"]),
        sidecar_name=os.path.basename(resolved.get("recovery") or "argus_remote_recovery.json"),
        cleanup=bool(production))
    work_directories = reconcile_abandoned_work_directories(root, cleanup=bool(production))
    LAST_RECONCILIATION.clear()
    LAST_RECONCILIATION.update(recoveryStaging=staging, workDirectories=work_directories)
    checkpoint_bytes = _file_bytes(resolved["checkpoint"])
    wal_bytes = _file_bytes(resolved["wal"])
    checkpoint_temp_bytes = _temp_bytes(
        temp_directory, os.path.basename(resolved["checkpoint"]))
    usage = disk_usage_fn(root)
    required = required_free_bytes(
        checkpoint_bytes=checkpoint_bytes, wal_bytes=wal_bytes)
    if int(usage.free) < required:
        raise PersistentStorageError("persistent_storage_insufficient_space")
    safety_ratio = round(int(usage.free) / required, 3) if required else None
    return {
        "valid": True,
        "errorClass": None,
        "validatedAt": _iso_now(),
        "paths": resolved,
        "sameFilesystem": True,
        "atomicRename": True,
        "fsync": True,
        "totalBytes": int(usage.total),
        "usedBytes": int(usage.used),
        "freeBytes": int(usage.free),
        "requiredFreeBytes": required,
        "checkpointBytes": checkpoint_bytes,
        "walBytes": wal_bytes,
        "checkpointTempBytes": checkpoint_temp_bytes,
        "abandonedTempReconciliation": abandoned,
        "abandonedRecoveryStaging": staging,
        "abandonedWorkDirectories": work_directories,
        "estimatedSafetyRatio": safety_ratio,
        "warning": "low_free_space" if safety_ratio is not None and
        safety_ratio < 2 else None,
        "lastSuccessfulFsync": _iso_now(),
    }


def atomic_write_json(
        path: str, value: Mapping[str, Any], *,
        temp_directory: Optional[str] = None,
        validator=None, temp_label: str = "tmp",
        maximum_bytes: Optional[int] = None,
        file_mode: Optional[int] = None) -> Dict[str, Any]:
    final = os.path.abspath(path)
    directory = os.path.realpath(temp_directory or os.path.dirname(final))
    if os.stat(directory).st_dev != os.stat(os.path.dirname(final)).st_dev:
        raise PersistentStorageError("checkpoint_temp_filesystem_mismatch")
    temporary = os.path.join(
        directory,
        f"{os.path.basename(final)}.{os.getpid()}.{uuid.uuid4().hex}."
        f"{POST_HOTFIX_TEMP_MARKER}-{temp_label}")
    maximum = int(maximum_bytes or _maximum_checkpoint_bytes())
    _validate_streamable_value(value)
    if validator is not None and not validator(value):
        raise PersistentStorageError("checkpoint_source_invalid")
    writer_lock_path = final + ".writer.lock"
    if os.path.lexists(writer_lock_path) and os.path.islink(writer_lock_path):
        raise PersistentStorageError("checkpoint_writer_lock_symlink_rejected")
    writer_lock_fd = os.open(
        writer_lock_path,
        os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
    writer_lock = os.fdopen(writer_lock_fd, "a+b")
    try:
        fcntl.flock(writer_lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        writer_lock.close()
        raise PersistentStorageError("checkpoint_writer_busy") from exc
    digest = hashlib.sha256()
    written = 0
    try:
        with open(temporary, "xb") as handle:
            if file_mode is not None:
                if isinstance(file_mode, bool) or not isinstance(
                        file_mode, int) or file_mode < 0 or file_mode > 0o777:
                    raise PersistentStorageError("checkpoint_file_mode_invalid")
                os.fchmod(handle.fileno(), file_mode)
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            for chunk in _canonical_chunks(value):
                if written + len(chunk) > maximum:
                    raise PersistentStorageError(
                        "checkpoint_maximum_bytes_exceeded",
                        details={"writtenBytes": written,
                                 "nextChunkBytes": len(chunk),
                                 "maximumBytes": maximum,
                                 "temporaryOutcome":
                                     "removed_current_writer_temp",
                                 "previousCheckpointAuthoritative": True,
                                 "walAuthoritative": True})
                handle.write(chunk)
                digest.update(chunk)
                written += len(chunk)
            handle.flush()
            os.fsync(handle.fileno())
        before = os.stat(temporary, follow_symlinks=False)
        read_back_hash = _stream_sha256(temporary)
        after = os.stat(temporary, follow_symlinks=False)
        if _file_identity(before) != _file_identity(after):
            raise PersistentStorageError("checkpoint_changed_during_readback")
        if read_back_hash != digest.hexdigest():
            raise PersistentStorageError("checkpoint_readback_hash_mismatch")
        os.replace(temporary, final)
        _fsync_directory(os.path.dirname(final))
    except Exception:
        with contextlib.suppress(OSError):
            os.unlink(temporary)
        raise
    finally:
        with contextlib.suppress(OSError):
            fcntl.flock(writer_lock.fileno(), fcntl.LOCK_UN)
        writer_lock.close()
    return {
        "path": final,
        "temporaryPath": temporary,
        "bytes": written,
        "snapshotHash": digest.hexdigest(),
        "readBackVerified": True,
        "maximumBytes": maximum,
        "verifiedAt": _iso_now(),
    }


def write_checkpoint(
        path: str, blob: Mapping[str, Any], *,
        temp_directory: Optional[str] = None) -> Dict[str, Any]:
    sealed = seal_checkpoint(blob)
    return atomic_write_json(
        path, sealed, temp_directory=temp_directory,
        validator=lambda value: verify_checkpoint(value, require_seal=True))


def load_checkpoint(
        path: str, *, require_seal: bool,
        allow_legacy_file_seal: bool = False) -> Dict[str, Any]:
    if os.path.lexists(path) and os.path.islink(path):
        raise PersistentStorageError("local_checkpoint_symlink_rejected")
    before_identity = _file_identity(
        os.stat(path, follow_symlinks=False))
    with open(path, encoding="utf-8") as handle:
        blob = json.load(handle)
    if verify_checkpoint(blob, require_seal=require_seal):
        return blob
    legacy_receipt = None
    if require_seal and allow_legacy_file_seal and \
            isinstance(blob, dict) and \
            "localCheckpointIntegrity" not in blob:
        # Do not apply parsed state until its raw bytes and migration receipt
        # have both been verified. A stable stat identity closes the race
        # between parsing and the streaming hash.
        legacy_receipt = verify_legacy_checkpoint_file_seal(
            path, expected_identity=before_identity)
    if legacy_receipt is not None and verify_checkpoint(
            blob, require_seal=False):
        return blob
    raise PersistentStorageError("local_checkpoint_integrity_invalid")


def quarantine(path: str) -> Optional[str]:
    if not os.path.exists(path):
        return None
    stamp = dt.datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    destination = f"{path}.quarantine-{stamp}-{uuid.uuid4().hex[:8]}"
    os.replace(path, destination)
    _fsync_directory(os.path.dirname(os.path.abspath(path)))
    return destination


def public_diagnostics(
        status: Mapping[str, Any], paths: Mapping[str, str],
        *, production: bool) -> Dict[str, Any]:
    expected_root = os.path.realpath("/var/data") if production else None
    configured_root = os.path.realpath(str(paths.get("root") or ""))
    drift = ([] if not production or configured_root == expected_root else
             ["persistentRoot"])
    return {
        "required": bool(production),
        "valid": bool(status.get("valid")),
        "errorClass": status.get("errorClass"),
        "errorReason": status.get("errorReason"),
        "persistentRoot": paths.get("root"),
        "walPath": paths.get("wal"),
        "checkpointPath": paths.get("checkpoint"),
        "leasePath": paths.get("lease"),
        "cursorPath": paths.get("cursor"),
        "receiptPath": paths.get("receipt"),
        "receiptQueuePath": paths.get("receiptQueue"),
        "recoveryPath": paths.get("recovery"),
        "sameFilesystem": status.get("sameFilesystem"),
        "atomicRename": status.get("atomicRename"),
        "fsync": status.get("fsync"),
        "totalBytes": status.get("totalBytes"),
        "usedBytes": status.get("usedBytes"),
        "freeBytes": status.get("freeBytes"),
        "requiredFreeBytes": status.get("requiredFreeBytes"),
        "checkpointBytes": status.get("checkpointBytes"),
        "walBytes": status.get("walBytes"),
        "checkpointTempBytes": status.get("checkpointTempBytes"),
        "abandonedCheckpointTemps": {
            key: (status.get("abandonedTempReconciliation") or {}).get(key)
            for key in ("scanned", "detectedCount", "removedCount",
                        "retainedCount", "retainedIncidentEvidenceCount",
                        "errorClass")
        },
        "estimatedSafetyRatio": status.get("estimatedSafetyRatio"),
        "warning": status.get("warning"),
        "lastSuccessfulFsync": status.get("lastSuccessfulFsync"),
        "lastCheckpointVerification": status.get(
            "lastCheckpointVerification"),
        "runtimeVerified": bool(status.get("valid")),
        "dashboardDiskAttached": (
            "runtime_path_verified" if status.get("valid") and production
            else "not_proven"),
        "configurationDrift": drift,
        "singleInstanceRuntimeProof": "dashboard_confirmation_required",
    }
