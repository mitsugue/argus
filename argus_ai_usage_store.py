"""Durable append-only AI usage detail beneath the existing persistent root.

No provider invocation, monetary authorization, or public write path. The
runtime must pass a path within its already-verified persistent root. Read-only
calls never initialize a database or silently report an absent file as zero.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
import stat
from typing import Iterable, Mapping

from argus_ai_usage_receipt import validate_receipt, summarize
from argus_product_naming import require_allowed

VERSION = 1
MAX_BATCH = 1000
MAX_PAGE = 1000


def _regular(path: Path):
    if not stat.S_ISREG(path.lstat().st_mode) or path.is_symlink():
        raise ValueError("usage_store_requires_regular_file")


def _connect(path: Path, *, readonly=False):
    _regular(path)
    connection = sqlite3.connect(path.resolve().as_uri() + ("?mode=ro" if readonly else "?mode=rw"),
                                 uri=True, timeout=15, isolation_level=None)
    try:
        if connection.execute("PRAGMA user_version").fetchone()[0] != VERSION:
            raise ValueError("usage_store_schema_mismatch")
        connection.execute("PRAGMA foreign_keys=ON")
        if not readonly:
            connection.execute("PRAGMA synchronous=FULL")
        return connection
    except Exception:
        connection.close()
        raise


def initialize(path: str | Path):
    """Explicit write initialization; existing records are never reset."""
    path = Path(path)
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    except FileExistsError:
        connection = _connect(path, readonly=True)
        connection.close()
        return
    os.close(fd)
    connection = sqlite3.connect(path, isolation_level=None)
    try:
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("CREATE TABLE usage_receipts (sequence INTEGER PRIMARY KEY, call_id TEXT NOT NULL UNIQUE, digest TEXT NOT NULL, started_at TEXT NOT NULL, body TEXT NOT NULL)")
        connection.execute("CREATE INDEX usage_receipts_started ON usage_receipts(started_at)")
        connection.execute("PRAGMA user_version=1")
        connection.execute("COMMIT")
    finally:
        connection.close()
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def append(path: str | Path, receipts: Iterable[Mapping]):
    """Commit a bounded batch atomically, or retain all preceding state."""
    prepared = []
    for item in receipts:
        if len(prepared) >= MAX_BATCH:
            raise ValueError("usage_batch_too_large")
        row = validate_receipt(item)
        require_allowed(row)
        prepared.append(row)
    connection = _connect(Path(path))
    inserted = 0
    try:
        connection.execute("BEGIN IMMEDIATE")
        for row in prepared:
            existing = connection.execute("SELECT digest, body FROM usage_receipts WHERE call_id=?", (row['callId'],)).fetchone()
            body = json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
            if existing:
                if existing != (row['receiptDigest'], body):
                    raise ValueError("conflicting_usage_call_id")
                continue
            connection.execute("INSERT INTO usage_receipts(call_id,digest,started_at,body) VALUES(?,?,?,?)",
                               (row['callId'], row['receiptDigest'], row['startedAt'], body))
            inserted += 1
        connection.execute("COMMIT")
        return {"inserted": inserted, "duplicates": len(prepared) - inserted, "durable": True}
    except Exception:
        if connection.in_transaction:
            connection.execute("ROLLBACK")
        raise
    finally:
        connection.close()


def _validated_record(record):
    sequence, call_id, digest, started_at, body = record
    row = validate_receipt(json.loads(body))
    require_allowed(row)
    if (call_id, digest, started_at) != (row['callId'], row['receiptDigest'], row['startedAt']):
        raise ValueError("usage_store_index_integrity_mismatch")
    return {"sequence": sequence, "receipt": row}


def read_page(path: str | Path, *, after_sequence=0, through_sequence=None, limit=500):
    """Immutable upper watermark permits a stable paginated restore/export."""
    for value in (after_sequence, limit):
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("invalid_usage_cursor")
    if after_sequence < 0 or not 1 <= limit <= MAX_PAGE:
        raise ValueError("invalid_usage_cursor")
    if through_sequence is not None and (isinstance(through_sequence, bool) or
            not isinstance(through_sequence, int) or through_sequence < after_sequence):
        raise ValueError("invalid_usage_watermark")
    connection = _connect(Path(path), readonly=True)
    try:
        connection.execute("BEGIN")
        latest = connection.execute("SELECT COALESCE(MAX(sequence),0) FROM usage_receipts").fetchone()[0]
        watermark = latest if through_sequence is None else through_sequence
        if watermark > latest or after_sequence > watermark:
            raise ValueError("usage_watermark_unavailable")
        records = connection.execute("SELECT sequence,call_id,digest,started_at,body FROM usage_receipts WHERE sequence>? AND sequence<=? ORDER BY sequence LIMIT ?",
                                     (after_sequence, watermark, limit + 1)).fetchall()
        page = [_validated_record(record) for record in records[:limit]]
        return {"rows": page, "throughSequence": watermark, "hasMore": len(records) > limit,
                "nextAfterSequence": page[-1]['sequence'] if page else after_sequence,
                "source": "durable_usage_receipts", "readOnly": True}
    finally:
        connection.close()


def read_summary(path: str | Path):
    """Aggregate every committed receipt, independent of the display window."""
    connection = _connect(Path(path), readonly=True)
    try:
        connection.execute("BEGIN")
        cursor = connection.execute("SELECT sequence,call_id,digest,started_at,body FROM usage_receipts ORDER BY sequence")
        result = summarize(_validated_record(record)['receipt'] for record in cursor)
        count, first, last, watermark = connection.execute("SELECT COUNT(*), MIN(started_at), MAX(started_at), COALESCE(MAX(sequence),0) FROM usage_receipts").fetchone()
        return {**result, "coverage": "all_committed_receipts_in_this_store",
                "durableReceiptCount": count, "firstRecordedAt": first, "lastRecordedAt": last,
                "throughSequence": watermark, "historyBeforeFirstReceiptReconstructed": False,
                "displayWindowLimitApplied": False, "readOnly": True}
    finally:
        connection.close()
