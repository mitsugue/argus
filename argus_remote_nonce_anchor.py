"""Private, bounded monotonic nonce-anchor epochs.

The reservation lock remains a stable inode used only for ``flock``.  Anchor
authority lives beside it and can therefore be atomically replaced when an
epoch reaches its byte limit.  Each replacement carries the previous epoch's
terminal digest and absolute generation so a crash can select exactly one
newer, self-consistent authority without resetting a key-material counter.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import stat
import struct
import tempfile
from typing import Any, Callable, Dict, Mapping, Optional


V1_HEADER = b"argus-remote-recovery-nonce-anchor-v1\n"
V2_HEADER = b"argus-remote-recovery-nonce-anchor-v2\n"
RECORD_BYTES = 4172
PAYLOAD_BYTES = 4096
TRAILER_OFFSET = 4140
V2_META_BYTES = 8 + 8 + 32 + 32
V2_HEADER_BYTES = len(V2_HEADER) + V2_META_BYTES


class AnchorError(RuntimeError):
    pass


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":")).encode("utf-8")


def _digest(value: bytes) -> bytes:
    return hashlib.sha256(value).digest()


def _parse_record(encoded: bytes, *, previous_journal_hash: bytes,
                  expected_generation: int,
                  validate_counters: Callable[..., Dict[str, int]]) \
        -> Dict[str, Any]:
    if len(encoded) != RECORD_BYTES:
        raise AnchorError("recovery_nonce_lock_record_invalid")
    generation = struct.unpack(">Q", encoded[:8])[0]
    record_hash = encoded[8:40]
    payload_length = struct.unpack(">I", encoded[40:44])[0]
    if generation != expected_generation or payload_length <= 0 or \
            payload_length > PAYLOAD_BYTES or \
            any(encoded[44 + payload_length:TRAILER_OFFSET]):
        raise AnchorError("recovery_nonce_lock_record_invalid")
    try:
        payload = json.loads(
            encoded[44:44 + payload_length].decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise AnchorError("recovery_nonce_lock_record_invalid") from exc
    if not isinstance(payload, dict) or set(payload) != {
            "previousRecordHash", "keyMaterialCounters"}:
        raise AnchorError("recovery_nonce_lock_record_invalid")
    previous_record_hash = payload["previousRecordHash"]
    counters = validate_counters(
        payload["keyMaterialCounters"], allow_empty=(generation == 0))
    journal_hash = encoded[TRAILER_OFFSET:RECORD_BYTES]
    expected = _digest(previous_journal_hash + encoded[:TRAILER_OFFSET])
    if not hmac.compare_digest(journal_hash, expected):
        raise AnchorError("recovery_nonce_lock_record_invalid")
    return {
        "generation": generation,
        "recordHash": record_hash.hex(),
        "journalHash": journal_hash.hex(),
        "previousRecordHash": previous_record_hash,
        "counters": counters,
    }


def read(handle, *, maximum_bytes: int,
         validate_counters: Callable[..., Dict[str, int]]) \
        -> Optional[Dict[str, Any]]:
    """Read and validate a complete v1 or v2 anchor from ``handle``."""
    size = os.fstat(handle.fileno()).st_size
    if size == 0:
        return None
    if size > maximum_bytes:
        raise AnchorError("recovery_nonce_lock_size_invalid")
    handle.seek(0)
    marker = handle.read(max(len(V1_HEADER), len(V2_HEADER)))
    if marker.startswith(V1_HEADER):
        header_bytes = len(V1_HEADER)
        if size < header_bytes + RECORD_BYTES or \
                (size - header_bytes) % RECORD_BYTES:
            raise AnchorError("recovery_nonce_lock_size_invalid")
        count = (size - header_bytes) // RECORD_BYTES
        base_generation = 0
        epoch = 0
        previous_epoch_digest = bytes(32)
        epoch_base_hash = _digest(V1_HEADER)
    elif marker.startswith(V2_HEADER):
        header_bytes = V2_HEADER_BYTES
        if size < header_bytes + RECORD_BYTES or \
                (size - header_bytes) % RECORD_BYTES:
            raise AnchorError("recovery_nonce_lock_size_invalid")
        handle.seek(len(V2_HEADER))
        meta = handle.read(V2_META_BYTES)
        if len(meta) != V2_META_BYTES:
            raise AnchorError("recovery_nonce_lock_header_invalid")
        epoch, base_generation = struct.unpack(">QQ", meta[:16])
        previous_epoch_digest = meta[16:48]
        base_record_hash = meta[48:80]
        if epoch < 1 or previous_epoch_digest == bytes(32):
            raise AnchorError("recovery_nonce_lock_header_invalid")
        count = (size - header_bytes) // RECORD_BYTES
        if base_generation > (1 << 64) - count:
            raise AnchorError("recovery_nonce_lock_header_invalid")
        expected_base_hash = _digest(
            previous_epoch_digest + struct.pack(">QQ", epoch, base_generation))
        if not hmac.compare_digest(base_record_hash, expected_base_hash):
            raise AnchorError("recovery_nonce_lock_header_invalid")
        epoch_base_hash = _digest(V2_HEADER + meta)
    else:
        raise AnchorError("recovery_nonce_lock_header_invalid")

    handle.seek(header_bytes + (count - 1) * RECORD_BYTES)
    encoded = handle.read(RECORD_BYTES)
    if count == 1:
        previous_generation = None
        previous_journal_hash = epoch_base_hash
    else:
        handle.seek(header_bytes + (count - 2) * RECORD_BYTES)
        previous = handle.read(RECORD_BYTES)
        previous_generation = struct.unpack(">Q", previous[:8])[0]
        previous_journal_hash = previous[TRAILER_OFFSET:RECORD_BYTES]
    expected_generation = base_generation + count - 1
    result = _parse_record(
        encoded, previous_journal_hash=previous_journal_hash,
        expected_generation=expected_generation,
        validate_counters=validate_counters)
    if previous_generation is not None and \
            previous_generation + 1 != expected_generation:
        raise AnchorError("recovery_nonce_lock_record_invalid")
    result.update({
        "formatVersion": 1 if epoch == 0 else 2,
        "epoch": epoch,
        "baseGeneration": base_generation,
        "previousEpochDigest": previous_epoch_digest.hex(),
        "epochDigest": _digest(
            previous_epoch_digest + bytes.fromhex(result["journalHash"]) +
            struct.pack(">QQ", epoch, result["generation"])).hex(),
    })
    return result


def _record(history: Mapping[str, Any], previous_journal_hash: bytes) -> bytes:
    try:
        payload = _canonical({
            "previousRecordHash": history["previousRecordHash"],
            "keyMaterialCounters": history["keyMaterialCounters"],
        })
        if len(payload) > PAYLOAD_BYTES:
            raise AnchorError("recovery_nonce_lock_payload_oversized")
        prefix = (
            struct.pack(">Q", history["generation"]) +
            bytes.fromhex(history["recordHash"]) +
            struct.pack(">I", len(payload)) + payload +
            bytes(PAYLOAD_BYTES - len(payload)))
    except (KeyError, TypeError, ValueError) as exc:
        raise AnchorError("recovery_nonce_lock_payload_invalid") from exc
    return prefix + _digest(previous_journal_hash + prefix)


def _fsync_directory(directory: str) -> None:
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _atomic_epoch_replace(path: str, content: bytes) -> None:
    directory = os.path.dirname(os.path.abspath(path)) or "."
    descriptor, temporary = tempfile.mkstemp(
        prefix=".argus-nonce-anchor-", dir=directory)
    try:
        os.fchmod(descriptor, 0o600)
        offset = 0
        while offset < len(content):
            offset += os.write(descriptor, content[offset:])
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        os.replace(temporary, path)
        _fsync_directory(directory)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def replace_successor(path: str, current: Mapping[str, Any],
                      history: Mapping[str, Any], *, maximum_bytes: int,
                      validate_counters: Callable[..., Dict[str, int]]) \
        -> Dict[str, Any]:
    """Atomically install the first record of a successor anchor epoch."""
    if history["generation"] != current["generation"] + 1 or \
            history["previousRecordHash"] != current["recordHash"]:
        raise AnchorError("recovery_nonce_lock_sequence_invalid")
    epoch = current["epoch"] + 1
    previous_epoch_digest = bytes.fromhex(current["epochDigest"])
    identity = struct.pack(">QQ", epoch, history["generation"])
    base_record_hash = _digest(previous_epoch_digest + identity)
    meta = identity + previous_epoch_digest + base_record_hash
    header = V2_HEADER + meta
    content = header + _record(history, _digest(header))
    if len(content) > maximum_bytes:
        raise AnchorError("recovery_nonce_lock_capacity_invalid")
    _atomic_epoch_replace(path, content)
    with open(path, "r+b", buffering=0) as verified_handle:
        mode = stat.S_IMODE(os.fstat(verified_handle.fileno()).st_mode)
        if mode & 0o077:
            raise AnchorError("recovery_nonce_lock_permissions_invalid")
        verified = read(
            verified_handle, maximum_bytes=maximum_bytes,
            validate_counters=validate_counters)
    if verified is None or verified["generation"] != history["generation"] or \
            not hmac.compare_digest(
                verified["recordHash"], history["recordHash"]):
        raise AnchorError("recovery_nonce_lock_readback_failed")
    return verified


def append(handle, history: Mapping[str, Any], *, path: str,
           maximum_bytes: int,
           validate_counters: Callable[..., Dict[str, int]]) \
        -> Dict[str, Any]:
    """Append, or atomically begin a successor epoch before the hard cap."""
    current = read(
        handle, maximum_bytes=maximum_bytes,
        validate_counters=validate_counters)
    expected_generation = 0 if current is None else current["generation"] + 1
    if history["generation"] != expected_generation or (
            current is not None and history["previousRecordHash"] !=
            current["recordHash"]):
        raise AnchorError("recovery_nonce_lock_sequence_invalid")

    if current is None:
        header = V1_HEADER
        previous_journal_hash = _digest(header)
        handle.seek(0)
        handle.write(header)
        handle.write(_record(history, previous_journal_hash))
        handle.flush()
        os.fsync(handle.fileno())
    elif os.fstat(handle.fileno()).st_size + RECORD_BYTES <= maximum_bytes:
        handle.seek(0, os.SEEK_END)
        handle.write(_record(
            history, bytes.fromhex(current["journalHash"])))
        handle.flush()
        os.fsync(handle.fileno())
    else:
        return replace_successor(
            path, current, history, maximum_bytes=maximum_bytes,
            validate_counters=validate_counters)

    # Atomic replacement changes the inode, so reopen the data authority while
    # retaining the separate stable reservation lock at the caller.
    with open(path, "r+b", buffering=0) as verified_handle:
        mode = stat.S_IMODE(os.fstat(verified_handle.fileno()).st_mode)
        if mode & 0o077:
            raise AnchorError("recovery_nonce_lock_permissions_invalid")
        verified = read(
            verified_handle, maximum_bytes=maximum_bytes,
            validate_counters=validate_counters)
    if verified is None or verified["generation"] != history["generation"] or \
            not hmac.compare_digest(
                verified["recordHash"], history["recordHash"]):
        raise AnchorError("recovery_nonce_lock_readback_failed")
    return verified
