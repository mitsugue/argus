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


def _iso_now() -> str:
    return dt.datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _record_hash(record: Dict[str, Any]) -> str:
    unsigned = {key: value for key, value in record.items() if key != "recordHash"}
    return hashlib.sha256(_canonical(unsigned)).hexdigest()


def _fsync_parent(path: str) -> None:
    parent = os.path.dirname(os.path.abspath(path)) or "."
    try:
        descriptor = os.open(parent, os.O_RDONLY)
    except OSError:
        return
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


def append_wal(path: str, *, sequence: int, kind: str,
               payload: Dict[str, Any], job_id: str,
               occurred_at: Optional[str] = None) -> Dict[str, Any]:
    record = {
        "schemaVersion": "argus-mission-wal-v1",
        "sequence": int(sequence),
        "kind": str(kind),
        "jobId": str(job_id),
        "occurredAt": occurred_at or _iso_now(),
        "payload": payload,
    }
    record["recordHash"] = _record_hash(record)
    encoded = _canonical(record) + b"\n"
    with open(path, "ab", buffering=0) as handle:
        handle.write(encoded)
        os.fsync(handle.fileno())
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
        "occurredAt": str(receipt.get("verifiedAt") or _iso_now()),
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
                        included_sequence: int = 0) -> Dict[str, Any]:
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
    if wal_path:
        result["walCompaction"] = compact_verified_wal(
            wal_path,
            included_sequence=int(included_sequence),
            receipt={
                "jobId": job_id,
                "verifiedAt": verified_at,
                "snapshotHash": expected_hash,
                "includedWalSequence": int(included_sequence),
            },
        )
    return result


class TickLease:
    """A non-blocking OS lease held for one synchronous HTTP request."""

    def __init__(self, path: str, *, build_sha: Optional[str],
                 owner: str, ttl_seconds: int = 240):
        self.path = path
        self.build_sha = build_sha
        self.owner = owner
        self.ttl_seconds = max(30, int(ttl_seconds))
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
            "acquiredAt": acquired.isoformat().replace("+00:00", "Z"),
            "expiresAt": (
                acquired + dt.timedelta(seconds=self.ttl_seconds)
            ).isoformat().replace("+00:00", "Z"),
            "heartbeatAt": acquired.isoformat().replace("+00:00", "Z"),
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

    def __enter__(self) -> "TickLease":
        if not self.acquire():
            raise RuntimeError("mission_tick_busy")
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.release()
