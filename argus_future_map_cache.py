"""Persist read receipts in the existing local forecast cache, never remotely.

Forecast update time is not the reader's success time. A legacy cache retains
its forecast but cannot prove a read that occurred after midnight.
"""
from datetime import date, datetime
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
from zoneinfo import ZoneInfo

from argus_future_map import PUBLIC_SCHEMA

RECEIPT_KEY = "localReadReceipt"
MAX_BYTES = 256 * 1024
TRIGGERS = {"notification", "fallback_daily", "fallback_empty", "unspecified"}
JST = ZoneInfo("Asia/Tokyo")


def _encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _stamp(value, now):
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > 40:
        raise ValueError("future_map_cache_timestamp")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed > now:
        raise ValueError("future_map_cache_timestamp")
    return value


def load(path, *, now_iso):
    path = Path(path)
    if not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError("future_map_cache_regular_file")
    with path.open("rb") as stream:
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError("future_map_cache_bound")
    public = json.loads(raw)
    if not isinstance(public, dict) or public.get("schemaVersion") != PUBLIC_SCHEMA:
        raise ValueError("future_map_cache_schema")
    receipt = public.pop(RECEIPT_KEY, None)
    if not isinstance(receipt, dict):
        return public, {}
    try:
        now = datetime.fromisoformat(now_iso.replace("Z", "+00:00"))
        if now.tzinfo is None or receipt.get("documentDigest") != hashlib.sha256(_encode(public)).hexdigest():
            raise ValueError("future_map_cache_receipt_binding")
        read = _stamp(receipt.get("lastReadOkAt"), now)
        changed = _stamp(receipt.get("lastChangedAt"), now)
        trigger = receipt.get("lastTrigger")
        if trigger is not None and trigger not in TRIGGERS:
            raise ValueError("future_map_cache_trigger")
        result = {"lastReadOkAt": read, "lastChangedAt": changed, "lastTrigger": trigger}
        fallback = receipt.get("fallback")
        if fallback is not None:
            day = date.fromisoformat(fallback["day"])
            decision = fallback["decision"]
            if day > now.astimezone(JST).date() or decision not in ("read", "skipped_already_read"):
                raise ValueError("future_map_cache_fallback")
            if decision == "skipped_already_read" and (not read or datetime.fromisoformat(read.replace("Z", "+00:00")).astimezone(JST).date() < day):
                raise ValueError("future_map_cache_skip_without_read")
            result["fallback"] = {"day": day.isoformat(), "decision": decision}
        return public, result
    except (ValueError, TypeError, KeyError, AttributeError):
        # The forecast remains available; invalid receipts prove nothing.
        return public, {}


def store(path, public, *, last_read_ok_at, last_changed_at, last_trigger, fallback):
    path = Path(path)
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise ValueError("future_map_cache_regular_file")
    if RECEIPT_KEY in public:
        raise ValueError("future_map_cache_reserved_field")
    receipt = {"documentDigest": hashlib.sha256(_encode(public)).hexdigest(),
               "lastReadOkAt": last_read_ok_at, "lastChangedAt": last_changed_at,
               "lastTrigger": last_trigger, "fallback": fallback}
    encoded = _encode({**public, RECEIPT_KEY: receipt})
    if len(encoded) > MAX_BYTES:
        raise ValueError("future_map_cache_bound")
    fd, temporary = tempfile.mkstemp(prefix=".future-map-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
