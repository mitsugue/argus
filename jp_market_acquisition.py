"""Bounded official-source acquisition for the existing market feature engine.

Raw responses and changed observations are append-only. A download made today
is never evidence that a revised historical value was known in the past.
"""
from __future__ import annotations

import csv
from datetime import date, datetime, timezone
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import threading
import time

MOF_HISTORY = 'https://www.mof.go.jp/jgbs/reference/interest_rate/data/jgbcm_all.csv'
MOF_CURRENT = 'https://www.mof.go.jp/jgbs/reference/interest_rate/jgbcm.csv'
VIX_HISTORY = 'https://cdn-api.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv'
SOURCES = {MOF_HISTORY: 'jp_yield_curve', MOF_CURRENT: 'jp_yield_curve', VIX_HISTORY: 'vix_ohlc'}
START = '2015-09-01'
MAX_BYTES = 2 * 1024 * 1024
METHOD = 'official-market-acquisition-v1'
ACQUISITION_SPEC = 'acquisition-map-20260920:b22a4a50965a045ac3e1385b75857732adb017dd0e993b56658d0b157c870bbd'


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(',', ':'))


def _time(value):
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('source_timezone_required')
    return result


def _number(value):
    number = float(value)
    if not math.isfinite(number):
        raise ValueError('source_nonfinite_value')
    return number


def _mof_date(value):
    match = re.fullmatch(r'([SHR])(\d+)\.(\d+)\.(\d+)', value)
    if not match:
        raise ValueError('source_era_date')
    era, year, month, day = match.groups()
    result = date({'S': 1925, 'H': 1988, 'R': 2018}[era] + int(year), int(month), int(day))
    bounds = {'S': ('1926-12-25', '1989-01-07'), 'H': ('1989-01-08', '2019-04-30'),
              'R': ('2019-05-01', '9999-12-31')}
    if not bounds[era][0] <= result.isoformat() <= bounds[era][1]:
        raise ValueError('source_era_boundary')
    return result.isoformat()


def parse(raw, *, url, received_at):
    if url not in SOURCES or not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_BYTES:
        raise ValueError('source_response_bound_or_identity')
    receipt = _time(received_at)
    if url == VIX_HISTORY:
        reader = csv.DictReader(io.StringIO(raw.decode('utf-8-sig')))
        if reader.fieldnames != ['DATE', 'OPEN', 'HIGH', 'LOW', 'CLOSE']:
            raise ValueError('source_vix_columns')
        entries = []
        for row in reader:
            day = datetime.strptime(row['DATE'], '%m/%d/%Y').date().isoformat()
            if day < START:
                continue  # Keep original bytes, but validate only the declared import window.
            values = {key.lower(): _number(row[key]) for key in ('OPEN', 'HIGH', 'LOW', 'CLOSE')}
            if (min(values.values()) <= 0 or values['low'] > min(values['open'], values['close'])
                    or values['high'] < max(values['open'], values['close'])
                    or values['high'] < values['low']):
                raise ValueError('source_vix_ohlc_order')
            entries.append({'date': day, 'values': values, 'unit': 'INDEX_POINTS'})
    else:
        lines = raw.decode('cp932').splitlines()
        if len(lines) < 3 or '国債金利情報' not in lines[0] or '%' not in lines[0]:
            raise ValueError('source_mof_definition')
        reader = csv.DictReader(io.StringIO('\n'.join(lines[1:])))
        expected = ['基準日'] + [str(n) + '年' for n in (*range(1, 11), 15, 20, 25, 30, 40)]
        if reader.fieldnames != expected:
            raise ValueError('source_mof_columns')
        entries = []
        for row in reader:
            if (not row['基準日'] or row['基準日'].startswith('※最新のcsvデータがダウンロードできない場合')) and all(
                    row.get(key) == '' for key in expected[1:]):
                continue  # Official blank/footer records contain no observation.
            values = {key[:-1]: None if row[key].strip() in ('', '-') else _number(row[key])
                      for key in expected[1:]}
            entries.append({'date': _mof_date(row['基準日']), 'values': values, 'unit': 'PERCENT'})
    if not entries or len(entries) > 20000 or len({r['date'] for r in entries}) != len(entries):
        raise ValueError('source_empty_or_duplicate_dates')
    if any(date.fromisoformat(r['date']) > receipt.date() for r in entries):
        raise ValueError('source_future_observation')
    selected = sorted([r for r in entries if r['date'] >= START], key=lambda r: r['date'])
    if not selected:
        raise ValueError('source_empty_import_window')
    return selected


def connect(path):
    path = Path(path)
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise ValueError('source_store_regular_file_required')
    # O_EXCL keeps new files private before SQLite opens them; existing stores
    # retain their permissions and contents.
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(fd)
    except FileExistsError:
        pass
    db = sqlite3.connect(path, timeout=10)
    db.execute('PRAGMA synchronous=FULL')
    db.executescript('''CREATE TABLE IF NOT EXISTS raw_sources(
        id TEXT PRIMARY KEY, url TEXT NOT NULL, sha256 TEXT NOT NULL,
        received_at TEXT NOT NULL, raw BLOB NOT NULL);
        CREATE TABLE IF NOT EXISTS observations(
        seq INTEGER PRIMARY KEY, source_id TEXT NOT NULL, session TEXT NOT NULL,
        raw_id TEXT NOT NULL REFERENCES raw_sources(id), body TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS source_session ON observations(source_id,session,seq);
        CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);''')
    return db


def ingest(db, raw, *, url, received_at):
    rows = parse(raw, url=url, received_at=received_at)
    digest = hashlib.sha256(raw).hexdigest()
    raw_id = hashlib.sha256((url + ':' + digest).encode()).hexdigest()
    previous = {r['date']: r for r in latest_rows(db, SOURCES[url])}
    count = 0
    with db:
        db.execute('INSERT OR IGNORE INTO raw_sources VALUES(?,?,?,?,?)',
                   (raw_id, url, digest, received_at, raw))
        for item in rows:
            old = previous.get(item['date'])
            if old and all(old[k] == item[k] for k in ('values', 'unit')):
                continue
            if old and _time(received_at) <= _time(old['knownAt']):
                raise ValueError('source_revision_time_order')
            body = {**item, 'sourceRef': url, 'sourceResponseSha256': digest,
                    'knownAt': received_at, 'availableFrom': received_at,
                    'publishedAt': None, 'availabilityBasis': 'UNKNOWN',
                    'historicalVintageVerified': False, 'observationFrequency': 'DAILY',
                    'definitionId': 'CBOE_VIX_INDEX_OHLC' if url == VIX_HISTORY else 'MOF_JGB_CONSTANT_MATURITY_PERCENT',
                    'rightsReference': 'PUBLIC_SOURCE_PERSONAL_ANALYSIS_NOT_REDISTRIBUTION',
                    'observationStatus': 'OBSERVED', 'isImputed': False,
                    'revision': old['revision'] + 1 if old else 0, 'rawId': raw_id,
                    'supersedesRawId': old['rawId'] if old else None}
            db.execute('INSERT INTO observations(source_id,session,raw_id,body) VALUES(?,?,?,?)',
                       (SOURCES[url], item['date'], raw_id, _json(body)))
            count += 1
    return {'rawId': raw_id, 'sha256': digest, 'changedObservations': count,
            'sourceRows': len(rows), 'sourceFirstDate': rows[0]['date'] if rows else None,
            'sourceLastDate': rows[-1]['date'] if rows else None}


def latest_rows(db, source_id):
    values = db.execute('''SELECT o.body FROM observations o JOIN
        (SELECT session,max(seq) seq FROM observations WHERE source_id=? GROUP BY session) x
        ON o.seq=x.seq ORDER BY o.session''', (source_id,)).fetchall()
    if len(values) > 4000:
        raise ValueError('source_retained_observation_bound')
    return [json.loads(value[0]) for value in values]


def verify_raw(db):
    for raw_id, url, digest, received_at, raw in db.execute('SELECT * FROM raw_sources'):
        if (url not in SOURCES or len(raw) > MAX_BYTES or hashlib.sha256(raw).hexdigest() != digest
                or hashlib.sha256((url + ':' + digest).encode()).hexdigest() != raw_id):
            raise ValueError('source_raw_integrity')
        parsed = {r['date']: r for r in parse(raw, url=url, received_at=received_at)}
        for source_id, session, encoded in db.execute(
                'SELECT source_id,session,body FROM observations WHERE raw_id=?', (raw_id,)):
            row = json.loads(encoded)
            expected = parsed.get(session)
            if (expected is None or source_id != SOURCES[url] or
                    any(row.get(k) != expected[k] for k in ('date', 'values', 'unit')) or
                    row.get('rawId') != raw_id or row.get('sourceRef') != url or
                    row.get('sourceResponseSha256') != digest or row.get('publishedAt') is not None or
                    row.get('historicalVintageVerified') is not False or
                    row.get('availableFrom') != row.get('knownAt') or
                    _time(row['knownAt']) < _time(received_at)):
                raise ValueError('source_normalized_integrity')


def feature_rows(rows, source_id):
    result = []
    for item in rows[-3000:]:
        value = item['values'].get('close' if source_id == 'vix_ohlc' else '10')
        if value is None:
            continue
        result.append({k: v for k, v in item.items() if k != 'values'} | {
            'instrumentId': 'VIX' if source_id == 'vix_ohlc' else 'JP10Y',
            'seriesId': 'close' if source_id == 'vix_ohlc' else 'yield_pct', 'value': value,
            'close': value})
    return result


class SourceCache:
    """Only background warm performs IO. No paid API or AI is called."""
    def __init__(self):
        self.rows = {}; self.status = {'status': 'NOT_ACQUIRED'}
        self.lock = threading.Lock(); self.next_attempt = 0; self.restored_path = None

    def snapshot(self):
        return json.loads(_json(self.status))

    def warm(self, path, *, get, now=lambda: datetime.now(timezone.utc).isoformat()):
        if not path or not self.lock.acquire(blocking=False):
            return
        db = None
        try:
            if time.monotonic() < self.next_attempt:
                return
            self.next_attempt = time.monotonic() + 3600
            db = connect(path)
            if self.restored_path != str(path):
                verify_raw(db); self.restored_path = str(path)
            at = now()
            previous = db.execute("SELECT value FROM metadata WHERE key='dailyAttempt'").fetchone()
            urls = []
            if not db.execute('SELECT 1 FROM raw_sources WHERE url=?', (MOF_HISTORY,)).fetchone():
                urls.append(MOF_HISTORY)
            if not db.execute('SELECT 1 FROM raw_sources WHERE url=?', (VIX_HISTORY,)).fetchone():
                urls.append(VIX_HISTORY)
            # The provider schedules publication around 09:30 JST on the next
            # business day. Never consume today's one refresh before that.
            if _time(at).astimezone(timezone.utc).hour >= 1 and (not previous or previous[0] != at[:10]):
                urls.append(MOF_CURRENT)
                with db:
                    db.execute("INSERT OR REPLACE INTO metadata VALUES('dailyAttempt',?)", (at[:10],))
            errors = {}; receipts = []
            for url in urls:
                try:
                    # A denied source is not retried during this warm or via a
                    # different endpoint. Bootstrap attempts are daily-bounded.
                    attempt_key = 'attempt:' + url
                    prior = db.execute('SELECT value FROM metadata WHERE key=?', (attempt_key,)).fetchone()
                    if prior and prior[0] == at[:10]:
                        continue
                    with db:
                        db.execute('INSERT OR REPLACE INTO metadata VALUES(?,?)', (attempt_key, at[:10]))
                    deadline = time.monotonic() + 25
                    with get(url, timeout=(5, 15), stream=True, allow_redirects=False) as response:
                        if response.status_code != 200:
                            raise ValueError('source_http_' + str(response.status_code))
                        chunks = []; size = 0
                        for chunk in response.iter_content(16384):
                            size += len(chunk)
                            if size > MAX_BYTES or time.monotonic() > deadline:
                                raise ValueError('source_response_bound_or_deadline')
                            chunks.append(chunk)
                    receipts.append(ingest(db, b''.join(chunks), url=url, received_at=now()))
                except Exception as exc:
                    errors[url] = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
            groups = {key: latest_rows(db, key) for key in sorted(set(SOURCES.values()))}
            self.rows = {key: feature_rows(rows, key) for key, rows in groups.items()}
            coverage = {key: {'observations': len(rows), 'firstDate': rows[0]['date'] if rows else None,
                             'lastDate': rows[-1]['date'] if rows else None,
                             'nativeFrequency': 'DAILY', 'originalVintageVerified': False,
                             'latestRawId': rows[-1]['rawId'] if rows else None,
                             'lastKnownAt': rows[-1]['knownAt'] if rows else None,
                             'expectedCalendarCoverageVerified': False}
                        for key, rows in groups.items()}
            self.status = {'status': 'PARTIAL' if errors or not all(groups.values()) else 'AVAILABLE',
                           'method': METHOD, 'acquisitionSpecId': ACQUISITION_SPEC,
                           'sources': coverage, 'errors': errors,
                           'lastCheckedAt': at, 'requestsThisRefresh': len(receipts) + len(errors),
                           'persistenceStatus': 'LOCAL_DURABLE', 'rawIntegrity': 'VERIFIED',
                           'historicalVintageVerified': False, 'full10yAllIndicatorsComplete': False,
                           'automaticAiCalls': 0, 'actionAuthority': False,
                           'vixUpdates': 'EXISTING_YAHOO_CACHE_AFTER_INITIAL_OFFICIAL_IMPORT'}
        except Exception as exc:
            self.status = {**self.status, 'status': 'FAILED', 'errorClass': type(exc).__name__}
        finally:
            if db is not None: db.close()
            self.lock.release()


def merge_feature_sources(existing, official):
    """Fill absent sessions without replacing existing provider vintages.

    One provider per date avoids representing different providers as revisions
    of the same observation. Raw official rows remain in their separate store.
    """
    dates = {r.get('date') for r in existing}
    return sorted([{**row, 'seriesId': 'close'} for row in existing] +
                  [row for row in official if row['date'] not in dates], key=lambda r: r['date'])[-3000:]
