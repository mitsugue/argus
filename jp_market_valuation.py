"""Index-based valuation vintages from a reviewed local export; no historical
availability inference.

The EPS is derived from the same-session close/PER, never a separately
published EPS. 2026-11-21 (owner): the direct read of Nikkei's daily summary
page was removed. The page answers 403 to every non-browser request, and the
current valuation comes from the J-Quants/weight-table lanes in scanner.py
(_level_map_current_valuation and the index valuation proxy). SOURCE remains
only as the identity of the page an export row claims to come from.
"""
from __future__ import annotations

from datetime import date, datetime
import csv
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import stat
import tempfile

from jp_market_price_paths import VALUATION_BASIS

SOURCE = "https://indexes.nikkei.co.jp/nkave/archives/summary/"


def _instant(value):
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('valuation_timezone_required')
    return parsed


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def _validate(row):
    if (not isinstance(row, dict) or row.get('sourceRef') != SOURCE
            or row.get('basis') != VALUATION_BASIS or row.get('instrumentId') != 'NIKKEI_225_INDEX'
            or row.get('currency') != 'JPY' or row.get('publishedAt') is not None
            or row.get('publicationStatus') != 'UNKNOWN'
            or row.get('epsKind') != 'DERIVED_FROM_INDEX_CLOSE_AND_INDEX_BASED_PER'
            or row.get('historicalVintageVerified') is not False
            or not re.fullmatch('[a-f0-9]{64}', str(row.get('sourceResponseSha256', '')))):
        raise ValueError('valuation_stored_schema')
    session = date.fromisoformat(row['date']).isoformat()
    if row['availableFrom'] != row['knownAt'] or _instant(row['knownAt']) < _instant(session+'T06:30:00Z'):
        raise ValueError('valuation_stored_time')
    if any(type(row[k]) not in (float, int) or not math.isfinite(row[k]) or row[k] <= 0
           for k in ('indexClose', 'per')):
        raise ValueError('valuation_stored_values')
    return row


def parse_export(raw: bytes, *, received_at: str):
    """Reviewable local export path into the SAME valuation vintage store.

    The file hash proves what was imported, not the supplier's original page.
    Claimed publication timestamps do not grant historical-vintage authority.
    """
    if not isinstance(raw, bytes) or not 0 < len(raw) <= 2 * 1024 * 1024:
        raise ValueError('valuation_export_bound')
    _instant(received_at)
    reader = csv.DictReader(io.StringIO(raw.decode('utf-8-sig')))
    required = {'date', 'nikkei_close', 'index_per', 'per_basis', 'source_url', 'source_sha256'}
    if not required <= set(reader.fieldnames or ()):
        raise ValueError('valuation_export_columns')
    rows = []; dates = set(); digest = hashlib.sha256(raw).hexdigest()
    for item in reader:
        day = date.fromisoformat(item['date']).isoformat()
        if day in dates or len(rows) >= 4000:
            raise ValueError('valuation_export_duplicate_or_bound')
        dates.add(day)
        if item['per_basis'] != 'INDEX_WEIGHT_BASIS':
            raise ValueError('valuation_export_wrong_per_basis')
        url = item['source_url']
        if url != SOURCE and not re.fullmatch(
                r'https://indexes\.nikkei\.co\.jp/nkave/archives/summary/?\?dt=' + day.replace('-', ''), url):
            raise ValueError('valuation_export_source_identity')
        if not re.fullmatch('[a-f0-9]{64}', item['source_sha256']):
            raise ValueError('valuation_export_claimed_hash')
        row = {'instrumentId': 'NIKKEI_225_INDEX', 'basis': VALUATION_BASIS,
               'currency': 'JPY', 'date': day, 'indexClose': float(item['nikkei_close']),
               'per': float(item['index_per']), 'knownAt': received_at, 'availableFrom': received_at,
               'publishedAt': None, 'publicationStatus': 'UNKNOWN', 'sourceRef': SOURCE,
               'sourceResponseSha256': digest, 'sourceExportSha256': digest,
               'claimedOriginalSha256': item['source_sha256'], 'originalHashVerified': False,
               'inputKind': 'REVIEWED_LOCAL_EXPORT', 'originalSourceUrl': url,
               'precisionNote': 'EPS_DERIVED_FROM_ROUNDED_INDEX_PER',
               'epsKind': 'DERIVED_FROM_INDEX_CLOSE_AND_INDEX_BASED_PER',
               'historicalVintageVerified': False}
        rows.append(_validate(row))
    if not rows:
        raise ValueError('valuation_export_empty')
    return sorted(rows, key=lambda r: r['date'])


def _connect(path, *, readonly=False):
    path = Path(path)
    if path.is_symlink() or not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError('valuation_regular_file_required')
    conn = sqlite3.connect(path.resolve().as_uri()+('?mode=ro' if readonly else '?mode=rw'),
                           uri=True, timeout=10, isolation_level=None)
    if conn.execute('PRAGMA user_version').fetchone()[0] != 1:
        conn.close(); raise ValueError('valuation_store_schema')
    if not readonly: conn.execute('PRAGMA synchronous=FULL')
    return conn


def initialize(path):
    path = Path(path)
    if path.exists() or path.is_symlink():
        _connect(path, readonly=True).close(); return
    fd, temporary = tempfile.mkstemp(prefix='.index-valuation-', dir=path.parent); os.close(fd)
    try:
        conn = sqlite3.connect(temporary)
        try:
            conn.executescript('''PRAGMA synchronous=FULL; BEGIN IMMEDIATE;
                CREATE TABLE vintages(sequence INTEGER PRIMARY KEY, id TEXT UNIQUE NOT NULL,
                  session TEXT NOT NULL, known_at TEXT NOT NULL, body TEXT NOT NULL);
                PRAGMA user_version=1; COMMIT;''')
        finally: conn.close()
        with open(temporary, 'rb') as handle: os.fsync(handle.fileno())
        try: os.link(temporary, path, follow_symlinks=False)
        except FileExistsError: _connect(path, readonly=True).close()
        directory = os.open(path.parent, os.O_RDONLY)
        try: os.fsync(directory)
        finally: os.close(directory)
    finally: os.unlink(temporary)


def latest(path, cutoff):
    conn = _connect(path, readonly=True)
    try:
        rows = conn.execute('SELECT id,body FROM vintages WHERE julianday(known_at)<=julianday(?) '
                            'ORDER BY session DESC,julianday(known_at) DESC,sequence DESC LIMIT 1', (cutoff,)).fetchone()
        if not rows: return None
        if hashlib.sha256(rows[1].encode()).hexdigest() != rows[0]:
            raise ValueError('valuation_vintage_integrity')
        row = _validate(json.loads(rows[1]))
        if _instant(row['knownAt']) > _instant(cutoff): return None
        return row
    finally: conn.close()


def append(path, row):
    row = _validate(row); conn = _connect(path)
    try:
        conn.execute('BEGIN IMMEDIATE')
        previous = conn.execute('SELECT id,body FROM vintages WHERE session=? '
                                'ORDER BY sequence DESC LIMIT 1', (row['date'],)).fetchone()
        if previous:
            if hashlib.sha256(previous[1].encode()).hexdigest() != previous[0]:
                raise ValueError('valuation_vintage_integrity')
            old = _validate(json.loads(previous[1]))
            if any(old[k] != row[k] for k in ('date', 'per', 'indexClose')):
                if _instant(row['knownAt']) <= _instant(old['knownAt']):
                    raise ValueError('valuation_revision_time_order')
            else:
                conn.execute('COMMIT'); return old
        body = _json(row); digest = hashlib.sha256(body.encode()).hexdigest()
        conn.execute('INSERT INTO vintages(id,session,known_at,body) VALUES(?,?,?,?)',
                     (digest, row['date'], row['knownAt'], body))
        conn.execute('COMMIT'); return row
    except Exception:
        if conn.in_transaction: conn.execute('ROLLBACK')
        raise
    finally: conn.close()
