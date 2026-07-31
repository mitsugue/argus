"""Small WAL, verified checkpoints, and cross-process mission-tick leases.

This module is deliberately stdlib-only.  The WAL contains only transition
records; the much larger ARGUS durable snapshot is written once at the end of
a bounded tick batch.
"""
from __future__ import annotations

import contextlib
import datetime as dt
import fcntl
import hashlib
import json
import os
import threading
import time
import uuid
from typing import Any, Dict, Iterable, List, Optional


UTC = dt.timezone.utc
_PROCESS_LOCK = threading.Lock()
REMOTE_RECEIPT_SCHEMA = "argus-mission-receipt-v2"


def _iso_now() -> str:
    return dt.datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _record_hash(record: Dict[str, Any]) -> str:
    unsigned = {key: value for key, value in record.items() if key != "recordHash"}
    return hashlib.sha256(_canonical(unsigned)).hexdigest()


def remote_receipt_record(*, saved_at: str,
                          remote_commit_sha: Optional[str],
                          committed_at: Optional[str],
                          expected_hash: Optional[str],
                          actual_hash: Optional[str],
                          read_back_at: Optional[str],
                          read_back_verified: bool,
                          remote_wal_applied_sequence: int,
                          verified_wal_sequence: int,
                          compact_receipt_hash: Optional[str],
                          error_class: Optional[str],
                          wal_read_back_verified: Optional[bool] = None,
                          wal_error_class: Optional[str] = None,
                          remote_durability_state: Optional[str] = None,
                          receipt_commit_sha: Optional[str] = None,
                          receipt_created_at: Optional[str] = None,
                          receipt_verified_at: Optional[str] = None,
                          receipt_age_seconds: Optional[int] = None,
                          receipt_attempts: int = 0,
                          receipt_error_class: Optional[str] = None
                          ) -> Dict[str, Any]:
    """Integrity-bound persistent proof for Remote Journal WAL coverage."""
    record = {
        "schemaVersion": REMOTE_RECEIPT_SCHEMA,
        "savedAt": str(saved_at),
        "remoteCommitSha": remote_commit_sha,
        "committedAt": committed_at,
        "expectedHash": expected_hash,
        "actualHash": actual_hash,
        "readBackAt": read_back_at,
        "readBackVerified": bool(read_back_verified),
        "walReadBackVerified": bool(
            read_back_verified if wal_read_back_verified is None
            else wal_read_back_verified),
        "remoteWalAppliedSequence": int(remote_wal_applied_sequence or 0),
        "verifiedWalSequence": int(verified_wal_sequence or 0),
        "compactReceiptHash": compact_receipt_hash,
        "errorClass": error_class,
        "walErrorClass": wal_error_class,
        "remoteDurabilityState": remote_durability_state,
        "receiptCommitSha": receipt_commit_sha,
        "receiptCreatedAt": receipt_created_at,
        "receiptVerifiedAt": receipt_verified_at,
        "receiptAgeSeconds": receipt_age_seconds,
        "receiptAttempts": int(receipt_attempts or 0),
        "receiptErrorClass": receipt_error_class,
    }
    record["recordHash"] = _record_hash(record)
    return record


def verify_remote_receipt(record: Any) -> bool:
    """Fail closed on malformed, tampered, or self-contradictory receipts."""
    if not isinstance(record, dict) or \
            record.get("schemaVersion") != REMOTE_RECEIPT_SCHEMA or \
            record.get("recordHash") != _record_hash(record):
        return False
    try:
        remote_sequence = int(record.get("remoteWalAppliedSequence") or 0)
        verified_sequence = int(record.get("verifiedWalSequence") or 0)
    except (TypeError, ValueError):
        return False
    if remote_sequence < 0 or verified_sequence < 0:
        return False
    try:
        receipt_attempts = int(record.get("receiptAttempts") or 0)
        receipt_age = record.get("receiptAgeSeconds")
        receipt_age = None if receipt_age is None else int(receipt_age)
    except (TypeError, ValueError):
        return False
    if receipt_attempts < 0 or (receipt_age is not None and receipt_age < 0):
        return False
    commit_sha = record.get("remoteCommitSha")
    receipt_commit_sha = record.get("receiptCommitSha")
    expected_hash = record.get("expectedHash")
    actual_hash = record.get("actualHash")
    if commit_sha is not None and (
            len(str(commit_sha)) != 40 or
            any(ch not in "0123456789abcdef" for ch in str(commit_sha))):
        return False
    if receipt_commit_sha is not None and (
            len(str(receipt_commit_sha)) != 40 or
            any(ch not in "0123456789abcdef"
                for ch in str(receipt_commit_sha))):
        return False
    if record.get("remoteDurabilityState") == "verified" and not (
            record.get("readBackVerified") is True and
            record.get("walReadBackVerified") is True and
            receipt_commit_sha == commit_sha and
            record.get("receiptVerifiedAt") and
            record.get("receiptErrorClass") is None):
        return False
    for value in (expected_hash, actual_hash):
        if value is not None and (
                len(str(value)) != 16 or
                any(ch not in "0123456789abcdef" for ch in str(value))):
            return False
    if record.get("readBackVerified") is True and not (
            expected_hash and actual_hash and expected_hash == actual_hash and
            record.get("errorClass") is None):
        return False
    if record.get("walReadBackVerified") is True:
        return bool(
            record.get("readBackVerified") is True and
            expected_hash and actual_hash and expected_hash == actual_hash and
            record.get("compactReceiptHash") and
            remote_sequence == verified_sequence and
            record.get("errorClass") is None and
            record.get("walErrorClass") is None)
    return True


def _fsync_parent(path: str) -> None:
    parent = os.path.dirname(os.path.abspath(path)) or "."
    descriptor = os.open(parent, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def current_rss_bytes() -> Optional[int]:
    """Return current Linux RSS without adding a monitoring dependency."""
    try:
        with open("/proc/self/statm", encoding="ascii") as handle:
            resident_pages = int(handle.read().split()[1])
        return resident_pages * int(os.sysconf("SC_PAGE_SIZE"))
    except (FileNotFoundError, OSError, ValueError, IndexError):
        return None


def _last_valid_record(path: str, *, before_sequence: int
                       ) -> Optional[Dict[str, Any]]:
    """Read backward so WAL append cost does not grow with retained history."""
    try:
        with open(path, "rb") as handle:
            handle.seek(0, os.SEEK_END)
            position = handle.tell()
            pending = b""
            while position > 0:
                size = min(64 * 1024, position)
                position -= size
                handle.seek(position)
                pending = handle.read(size) + pending
                lines = pending.split(b"\n")
                pending = lines[0]
                for raw in reversed(lines[1:]):
                    if not raw:
                        continue
                    try:
                        row = json.loads(raw.decode("utf-8"))
                        sequence = int(row.get("sequence") or 0)
                        if row.get("recordHash") == _record_hash(row) and \
                                0 < sequence < int(before_sequence):
                            return row
                    except (UnicodeDecodeError, json.JSONDecodeError,
                            TypeError, ValueError):
                        continue
            if pending:
                try:
                    row = json.loads(pending.decode("utf-8"))
                    sequence = int(row.get("sequence") or 0)
                    if row.get("recordHash") == _record_hash(row) and \
                            0 < sequence < int(before_sequence):
                        return row
                except (UnicodeDecodeError, json.JSONDecodeError,
                        TypeError, ValueError):
                    pass
    except FileNotFoundError:
        pass
    return None


def append_wal(path: str, *, sequence: int, kind: str,
               payload: Dict[str, Any], job_id: str,
               occurred_at: Optional[str] = None,
               transition_id: Optional[str] = None,
               mission_window_id: Optional[str] = None,
               build_sha: Optional[str] = None) -> Dict[str, Any]:
    previous = _last_valid_record(path, before_sequence=int(sequence))
    payload_hash = hashlib.sha256(_canonical(payload)).hexdigest()
    created_at = occurred_at or _iso_now()
    record = {
        "schemaVersion": "argus-mission-wal-v1",
        "sequence": int(sequence),
        "kind": str(kind),
        "jobId": str(job_id),
        "transitionId": str(
            transition_id or payload.get("transitionId") or
            f"{job_id}:{sequence}:{payload_hash[:16]}"),
        "missionWindowId": (
            mission_window_id or payload.get("missionWindowId") or
            (payload.get("transitionState") or {}).get(
                "missionWindowId")),
        "buildSha": build_sha,
        "createdAt": created_at,
        "occurredAt": created_at,
        "payloadHash": payload_hash,
        "previousSequence": (
            int(previous.get("sequence")) if previous is not None else None),
        "previousRecordHash": (
            previous.get("recordHash") if previous is not None else None),
        "payload": payload,
    }
    record["recordHash"] = _record_hash(record)
    encoded = _canonical(record) + b"\n"
    with open(path, "ab", buffering=0) as handle:
        handle.write(encoded)
        os.fsync(handle.fileno())
    _fsync_parent(path)
    return record


def read_valid_wal(path: str, *, after_sequence: int = 0
                   ) -> Dict[str, Any]:
    records: List[Dict[str, Any]] = []
    corrupt = 0
    maximum = int(after_sequence)
    try:
        with open(path, "rb") as handle:
            lines = handle.readlines()
    except FileNotFoundError:
        lines = []
    for raw in lines:
        try:
            record = json.loads(raw.decode("utf-8"))
            sequence = int(record.get("sequence") or 0)
            if (not isinstance(record, dict) or
                    record.get("schemaVersion") != "argus-mission-wal-v1" or
                    record.get("recordHash") != _record_hash(record) or
                    sequence <= 0):
                raise ValueError("invalid_wal_record")
            maximum = max(maximum, sequence)
            if sequence > int(after_sequence):
                records.append(record)
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
            corrupt += 1
    records.sort(key=lambda row: int(row["sequence"]))
    return {
        "records": records,
        "corruptCount": corrupt,
        "maximumSequence": maximum,
        "bytes": os.path.getsize(path) if os.path.exists(path) else 0,
    }


def compact_verified_wal(path: str, *, included_sequence: int,
                         receipt: Dict[str, Any]) -> Dict[str, Any]:
    """Compact only records covered by a successfully verified checkpoint."""
    complete = read_valid_wal(path)
    already_compacted = max((
        int((row.get("payload") or {}).get("includedWalSequence") or 0)
        for row in complete["records"]
        if row.get("kind") == "checkpoint_verified"
    ), default=0)
    if int(included_sequence) <= already_compacted:
        return {
            "compactedThrough": already_compacted,
            "remainingRecords": len(complete["records"]),
            "receiptSequence": int(complete.get("maximumSequence") or 0),
            "bytes": complete["bytes"],
            "duplicate": int(included_sequence) == already_compacted,
            "regressionIgnored": int(included_sequence) < already_compacted,
        }
    state = read_valid_wal(path, after_sequence=included_sequence)
    kept = list(state["records"])
    sequence = max(
        int(included_sequence),
        max((int(row["sequence"]) for row in kept), default=0),
    ) + 1
    checkpoint_receipt = {
        "schemaVersion": "argus-mission-wal-v1",
        "sequence": sequence,
        "kind": "checkpoint_verified",
        "jobId": str(receipt.get("jobId") or "checkpoint"),
        "transitionId": (
            f"checkpoint:{receipt.get('snapshotHash')}:{included_sequence}"),
        "missionWindowId": receipt.get("missionWindowId"),
        "buildSha": receipt.get("buildSha"),
        "createdAt": str(receipt.get("verifiedAt") or _iso_now()),
        "occurredAt": str(receipt.get("verifiedAt") or _iso_now()),
        "payloadHash": hashlib.sha256(_canonical(dict(receipt))).hexdigest(),
        "previousSequence": (
            int(kept[-1]["sequence"]) if kept else int(included_sequence)),
        "previousRecordHash": (
            kept[-1].get("recordHash") if kept else None),
        "payload": dict(receipt),
    }
    checkpoint_receipt["recordHash"] = _record_hash(checkpoint_receipt)
    kept.append(checkpoint_receipt)
    temporary = f"{path}.{os.getpid()}.{uuid.uuid4().hex}.compact"
    with open(temporary, "wb") as handle:
        for record in kept:
            handle.write(_canonical(record) + b"\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    _fsync_parent(path)
    return {
        "compactedThrough": int(included_sequence),
        "remainingRecords": len(kept),
        "receiptSequence": sequence,
        "bytes": os.path.getsize(path),
    }


def verified_checkpoint(path: str, blob: Dict[str, Any], *,
                        job_id: str, wal_path: Optional[str] = None,
                        included_sequence: int = 0,
                        allow_wal_compaction: bool = True,
                        compaction_sequence: Optional[int] = None,
                        build_sha: Optional[str] = None,
                        mission_window_id: Optional[str] = None) -> Dict[str, Any]:
    """Write, fsync, parse/hash read-back, then atomically replace the snapshot."""
    started = time.monotonic()
    encoded = _canonical(blob)
    serialization_ms = round((time.monotonic() - started) * 1000)
    expected_hash = hashlib.sha256(encoded).hexdigest()
    temporary = f"{path}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
    try:
        with open(temporary, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        with open(temporary, "rb") as handle:
            read_back = handle.read()
        parsed = json.loads(read_back.decode("utf-8"))
        read_back_hash = hashlib.sha256(_canonical(parsed)).hexdigest()
        if read_back_hash != expected_hash:
            raise ValueError("checkpoint_readback_hash_mismatch")
        os.replace(temporary, path)
        _fsync_parent(path)
    except Exception:
        with contextlib.suppress(OSError):
            os.unlink(temporary)
        raise
    verified_at = _iso_now()
    result = {
        "verified": True,
        "verifiedAt": verified_at,
        "snapshotBytes": len(encoded),
        "snapshotHash": expected_hash,
        "serializationMs": serialization_ms,
        "checkpointMs": round((time.monotonic() - started) * 1000),
        "includedWalSequence": int(included_sequence),
    }
    if wal_path and allow_wal_compaction:
        covered_sequence = min(
            int(included_sequence),
            int(compaction_sequence if compaction_sequence is not None
                else included_sequence))
        result["walCompaction"] = compact_verified_wal(
            wal_path,
            included_sequence=covered_sequence,
            receipt={
                "jobId": job_id,
                "verifiedAt": verified_at,
                "snapshotHash": expected_hash,
                "includedWalSequence": covered_sequence,
                "buildSha": build_sha,
                "missionWindowId": mission_window_id,
            },
        )
    elif wal_path:
        wal_state = read_valid_wal(wal_path)
        result["walCompaction"] = {
            "deferred": True,
            "reason": "remote_receipt_not_verified",
            "compactedThrough": 0,
            "remainingRecords": len(wal_state["records"]),
            "receiptSequence": int(included_sequence),
            "bytes": wal_state["bytes"],
        }
    return result


def sync_wal(path: str) -> Dict[str, Any]:
    """Flush an existing WAL and its directory without creating a fake record."""
    if not os.path.exists(path):
        return {"synced": True, "bytes": 0, "syncedAt": _iso_now()}
    with open(path, "rb") as handle:
        os.fsync(handle.fileno())
    _fsync_parent(path)
    return {
        "synced": True,
        "bytes": os.path.getsize(path),
        "syncedAt": _iso_now(),
    }


class TickLease:
    """A non-blocking OS lease held for one synchronous HTTP request."""

    def __init__(self, path: str, *, build_sha: Optional[str],
                 owner: str, ttl_seconds: int = 240,
                 boot_id: Optional[str] = None):
        self.path = path
        self.build_sha = build_sha
        self.owner = owner
        self.ttl_seconds = max(30, int(ttl_seconds))
        self.boot_id = boot_id or "unknown"
        self.process_identity = (
            f"{self.boot_id}:{os.getpid()}:{uuid.uuid4().hex[:12]}")
        self.job_id = f"tick-{uuid.uuid4().hex}"
        self._handle = None
        self._process_owned = False
        self.metadata: Dict[str, Any] = {}

    def acquire(self) -> bool:
        if not _PROCESS_LOCK.acquire(blocking=False):
            self.metadata = self.read_metadata()
            return False
        self._process_owned = True
        self._handle = open(self.path, "a+", encoding="utf-8")
        try:
            fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self._handle.close()
            self._handle = None
            _PROCESS_LOCK.release()
            self._process_owned = False
            self.metadata = self.read_metadata()
            return False
        acquired = dt.datetime.now(UTC)
        self.metadata = {
            "schemaVersion": "argus-mission-lease-v1",
            "jobId": self.job_id,
            "owner": self.owner,
            "processIdentity": self.process_identity,
            "bootId": self.boot_id,
            "acquiredAt": acquired.isoformat().replace("+00:00", "Z"),
            "expiresAt": (
                acquired + dt.timedelta(seconds=self.ttl_seconds)
            ).isoformat().replace("+00:00", "Z"),
            "heartbeatAt": acquired.isoformat().replace("+00:00", "Z"),
            "renewedAt": acquired.isoformat().replace("+00:00", "Z"),
            "buildSha": self.build_sha,
            "pid": os.getpid(),
        }
        self._write_metadata()
        return True

    def heartbeat(self) -> None:
        if self._handle is None:
            return
        now = dt.datetime.now(UTC)
        self.metadata["heartbeatAt"] = now.isoformat().replace("+00:00", "Z")
        self.metadata["renewedAt"] = now.isoformat().replace("+00:00", "Z")
        self.metadata["expiresAt"] = (
            now + dt.timedelta(seconds=self.ttl_seconds)
        ).isoformat().replace("+00:00", "Z")
        self._write_metadata()

    def _write_metadata(self) -> None:
        assert self._handle is not None
        self._handle.seek(0)
        self._handle.truncate()
        json.dump(self.metadata, self._handle, ensure_ascii=False, sort_keys=True)
        self._handle.flush()
        os.fsync(self._handle.fileno())
        _fsync_parent(self.path)

    def read_metadata(self) -> Dict[str, Any]:
        try:
            with open(self.path, encoding="utf-8") as handle:
                value = json.load(handle)
            return value if isinstance(value, dict) else {}
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return {}

    def release(self) -> None:
        if self._handle is not None:
            self.metadata["releasedAt"] = _iso_now()
            with contextlib.suppress(OSError):
                self._write_metadata()
            with contextlib.suppress(OSError):
                fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
            self._handle.close()
            self._handle = None
        if self._process_owned:
            _PROCESS_LOCK.release()
            self._process_owned = False

    def expire(self) -> None:
        """Mark the durable metadata expired; flock remains the real owner."""
        if self._handle is None:
            return
        now = _iso_now()
        self.metadata["renewedAt"] = now
        self.metadata["expiresAt"] = now
        self.metadata["shutdownRequestedAt"] = now
        with contextlib.suppress(OSError):
            self._write_metadata()

    def __enter__(self) -> "TickLease":
        if not self.acquire():
            raise RuntimeError("mission_tick_busy")
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.release()
