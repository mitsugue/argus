"""The event memory ledger copied to the existing private store (13.8 §4-7).

2026-10-27 (owner): the event memory (the hash-chained ledger of market events
read from the news) is kept on the persistent disk; a copy now goes to the same
private store the other owner and analysis backups use, and comes back when the
disk copy is lost. The ledger is append-only, so it is split by whole lines into
chunks whose boundaries depend only on the bytes before them: earlier chunks
never change and only the new tail is written. A manifest names the chunks in
order with their digests. A restore checks every chunk digest, the whole-file
digest and the hash chain (read_ledger) before the file is installed. A local
ledger that is not a clean extension of the copy is never uploaded over it.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

from argus_causal_event_memory import read_ledger as _state_reader
from argus_causal_event_memory import verify_ledger as _stream_verifier

PREFIX = "market-analysis/v1/event-memory"
MANIFEST = PREFIX + "/manifest.json"
SCHEMA = "argus-event-memory-backup-v1"
CHUNK_TARGET = 400 * 1024          # under the store's 512 KiB object bound
MAX_CHUNKS = 700


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _iter_chunks(raw: bytes):
    """The existing whole-line chunk boundaries, without retaining every piece."""
    count, current = 0, bytearray()
    for line in raw.splitlines(keepends=True):
        if current and len(current) + len(line) > CHUNK_TARGET:
            count += 1
            if count > MAX_CHUNKS:
                raise ValueError("event_memory_backup_bound")
            yield bytes(current)
            current = bytearray()
        current.extend(line)
    if current:
        count += 1
        if count > MAX_CHUNKS:
            raise ValueError("event_memory_backup_bound")
        yield bytes(current)


def chunks(raw: bytes) -> List[bytes]:
    """Keep the original list API for callers that need every chunk."""
    return list(_iter_chunks(raw))


def _chunk_path(digest: str) -> str:
    return f"{PREFIX}/chunks/{digest}.ndjson"


def _manifest(raw: Optional[bytes]) -> Optional[Dict[str, Any]]:
    if raw is None:
        return None
    value = json.loads(raw)
    rows = value.get("chunks")
    if (value.get("schemaVersion") != SCHEMA or not isinstance(rows, list) or len(rows) > MAX_CHUNKS
            or not all(isinstance(r, dict) and set(r) == {"sha256", "bytes"} and isinstance(r["sha256"], str)
                       and len(r["sha256"]) == 64 and type(r["bytes"]) is int and 0 < r["bytes"] <= CHUNK_TARGET + 96 * 1024
                       for r in rows)
            or type(value.get("totalBytes")) is not int or value["totalBytes"] != sum(r["bytes"] for r in rows)
            or not isinstance(value.get("totalSha256"), str) or type(value.get("records")) is not int):
        raise ValueError("event_memory_backup_manifest_invalid")
    return value


def _encode(value: Mapping[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def synchronize(path: str, remote: Any, *, read_ledger: Callable[[str], Mapping[str, Any]]) -> Dict[str, Any]:
    """Upload a verified local extension, restore a lost local copy, or report why not."""
    remote.require_private()
    manifest_raw, version = remote.get(MANIFEST)
    manifest = _manifest(manifest_raw)
    try:
        with open(path, "rb") as handle:
            raw = handle.read()
    except FileNotFoundError:
        if manifest is None or not manifest["chunks"]:
            return {"status": "EMPTY"}
        return _restore(path, remote, manifest, read_ledger)
    # Verify exactly the bytes that would be sent (a record appended meanwhile waits for the next run).
    local = _verify(raw, os.path.dirname(os.path.abspath(path)), read_ledger)
    if local.get("status") != "VERIFIED":
        return {"status": "LOCAL_NOT_VERIFIED", "reason": local.get("reason")}
    records = local["recordCount"]
    if manifest and manifest["totalSha256"] == _sha(raw):
        return {"status": "VERIFIED", "records": records, "bytes": len(raw)}
    if manifest and (len(raw) < manifest["totalBytes"] or _sha(raw[:manifest["totalBytes"]]) != manifest["totalSha256"]):
        # Not a clean extension (a shorter or different ledger): never overwrite the copy.
        return {"status": "CONFLICT", "records": records, "remoteRecords": manifest["records"]}
    # Check the unchanged chunk bound before any remote mutation. Retain only
    # digest/length descriptors; a second pass holds one outgoing piece.
    chunk_rows = [{"sha256": _sha(piece), "bytes": len(piece)} for piece in _iter_chunks(raw)]
    known = {row["sha256"] for row in (manifest or {}).get("chunks") or []}
    written = 0
    for piece, row in zip(_iter_chunks(raw), chunk_rows, strict=True):
        digest = _sha(piece)
        if digest != row["sha256"] or len(piece) != row["bytes"]:
            raise ValueError("event_memory_backup_chunk_plan_changed")
        if digest in known:
            continue
        existing, existing_version = remote.get(_chunk_path(digest))
        if existing is None:
            remote.put(_chunk_path(digest), piece, expected_version=None)
            written += 1
        elif existing != piece:
            raise ValueError("event_memory_backup_chunk_conflict")
    body = {"schemaVersion": SCHEMA, "chunks": chunk_rows,
            "totalBytes": len(raw), "totalSha256": _sha(raw), "records": records,
            "lastRecordHash": local["lastRecordHash"]}
    encoded = _encode(body)
    remote.put(MANIFEST, encoded, expected_version=version)
    if remote.get(MANIFEST)[0] != encoded:
        raise ValueError("event_memory_backup_readback_mismatch")
    return {"status": "UPLOADED", "records": records, "bytes": len(raw), "chunksWritten": written}


def _verification_summary(path: str, read_ledger: Callable[[str], Mapping[str, Any]]) -> Mapping[str, Any]:
    # Only the exact authoritative reader has a shared, equivalent streaming
    # verifier. Preserve injected-reader behavior and derive its scalars from
    # the validated records, never from caller-supplied summary fields.
    if read_ledger is _state_reader:
        return _stream_verifier(path)
    checked = read_ledger(path)
    rows = checked.get("records") or []
    return {"status": checked.get("status"), "reason": checked.get("reason"),
            "corruptLine": checked.get("corruptLine"), "recordCount": len(rows),
            "lastRecordHash": rows[-1].get("recordHash") if rows else None}


def _verify(raw: bytes, directory: str, read_ledger: Callable[[str], Mapping[str, Any]]) -> Mapping[str, Any]:
    fd, temporary = tempfile.mkstemp(prefix=".event-memory-check-", dir=directory)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(raw)
        return _verification_summary(temporary, read_ledger)
    finally:
        os.unlink(temporary)


def _restore(path: str, remote: Any, manifest: Mapping[str, Any],
             read_ledger: Callable[[str], Mapping[str, Any]]) -> Dict[str, Any]:
    parts = []
    for row in manifest["chunks"]:
        raw, _ = remote.get(_chunk_path(row["sha256"]))
        if raw is None or _sha(raw) != row["sha256"] or len(raw) != row["bytes"]:
            raise ValueError("event_memory_backup_chunk_invalid")
        parts.append(raw)
    whole = b"".join(parts)
    if _sha(whole) != manifest["totalSha256"]:
        raise ValueError("event_memory_backup_total_invalid")
    final = os.path.abspath(path)
    os.makedirs(os.path.dirname(final), exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".event-memory-restore-", dir=os.path.dirname(final))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(whole); handle.flush(); os.fsync(handle.fileno())
        checked = _verification_summary(temporary, read_ledger)
        if checked.get("status") != "VERIFIED" or checked["recordCount"] != manifest["records"]:
            raise ValueError("event_memory_backup_chain_invalid")
        if os.path.exists(final):
            raise ValueError("event_memory_backup_local_appeared")
        os.link(temporary, final)              # never replace a ledger written meanwhile
    finally:
        os.unlink(temporary)
    return {"status": "RESTORED", "records": manifest["records"], "bytes": len(whole)}
