"""Bounded official-source acquisition for the existing market feature engine.

Raw responses and changed observations are append-only. A download made today
is never evidence that a revised historical value was known in the past.
"""
from __future__ import annotations

import bisect
import csv
from datetime import date, datetime, timedelta, timezone
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
METHOD = 'official-market-acquisition-v2-scheduled-availability'
# Conservative availability of an ORIGINAL observation (revision 0) from its
# publisher's schedule: the calendar day after the observation date, 00:00Z
# (09:00 JST). MoF posts the day's JGB curve that evening; Cboe posts the VIX
# close after the US session. Until 2026-09-30 every imported history row
# was dated available from its download, so no past comparison cutoff could
# see it and ten years of official history contributed nothing to the
# analog selection. Corrections keep their actual receipt time. This is the
# same rule the two-market credit CSV already uses; it is not vintage proof.
SCHEDULED_AVAILABILITY_DAYS = {'vix_ohlc': 1, 'jp_yield_curve': 1}
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


def history_rows(db, source_id):
    """Return the append-only observation stream used by PIT calculations."""
    values = db.execute(
        'SELECT body FROM observations WHERE source_id=? ORDER BY seq',
        (source_id,)).fetchall()
    if len(values) > 3000:
        raise ValueError('source_feature_history_maintenance_required')
    return [json.loads(value[0]) for value in values]


def verify_raw(db):
    for raw_id, url, digest, received_at, raw in db.execute('SELECT * FROM raw_sources'):
        if (len(raw) > MAX_BYTES or hashlib.sha256(raw).hexdigest() != digest
                or hashlib.sha256((url + ':' + digest).encode()).hexdigest() != raw_id):
            raise ValueError('source_raw_integrity')
        # The durable SQLite file is shared by bounded acquisition adapters.
        # Verify every raw record's generic content identity, but only parse and
        # normalize the MOF/Cboe records owned by this adapter.  Treating a valid
        # J-Quants record as corruption prevents the official yield/VIX cache
        # from restoring after the margin adapter has appended its own receipt.
        if url not in SOURCES:
            continue
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


def scheduled_availability(source_id, day):
    """00:00Z of the scheduled calendar day after the observation date."""
    lag = SCHEDULED_AVAILABILITY_DAYS[source_id]
    return (date.fromisoformat(day) + timedelta(days=lag)).isoformat() + 'T00:00:00Z'


def feature_rows(rows, source_id):
    """Feature inputs from the append-only stream.

    An original observation (revision 0) is dated available from its
    publisher's schedule, never later than its receipt; the receipt stays on
    the row as receivedAt. A correction is available from its receipt only.
    The raw store is not rewritten: this is a read-side rule.
    """
    result = []
    if len(rows) > 3000:
        raise ValueError('source_feature_history_maintenance_required')
    for item in rows:
        value = item['values'].get('close' if source_id == 'vix_ohlc' else '10')
        if value is None:
            continue
        row = {k: v for k, v in item.items() if k != 'values'} | {
            'instrumentId': 'VIX' if source_id == 'vix_ohlc' else 'JP10Y',
            'seriesId': 'close' if source_id == 'vix_ohlc' else 'yield_pct', 'value': value,
            'close': value, 'receivedAt': item['knownAt']}
        if item.get('revision', 0) == 0:
            scheduled = scheduled_availability(source_id, item['date'])
            if _time(scheduled) < _time(item['knownAt']):
                row.update(knownAt=scheduled, availableFrom=scheduled,
                           availabilityBasis='SCHEDULED_PUBLICATION')
        result.append(row)
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
            histories = {key: history_rows(db, key) for key in groups}
            self.rows = {key: feature_rows(histories[key], key) for key in groups}
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


def merge_feature_sources(existing, official, *, path=None, received_at=None):
    """Fill absent sessions without replacing existing provider vintages.

    One provider per date avoids representing different providers as revisions
    of the same observation. Raw official rows remain in their separate store.
    """
    dates = {r.get('date') for r in existing}
    candidates = sorted([{**row, 'seriesId': 'close'} for row in existing] +
                        [row for row in official if row['date'] not in dates], key=lambda r: r['date'])[-3000:]
    if not path:
        return candidates
    _time(received_at)
    db = connect(path)
    try:
        # Persist provider selection: a date falling out of Yahoo's rolling
        # response must not switch provider and invalidate the historical prefix.
        db.execute("""CREATE TABLE IF NOT EXISTS selected_vix_inputs(
            seq INTEGER PRIMARY KEY, session TEXT NOT NULL, body TEXT NOT NULL,
            sha256 TEXT NOT NULL, received_at TEXT NOT NULL)""")
        saved = {}
        for session, body, digest in db.execute("""SELECT session,body,sha256 FROM selected_vix_inputs
                WHERE seq IN (SELECT max(seq) FROM selected_vix_inputs GROUP BY session)"""):
            if hashlib.sha256(body.encode()).hexdigest() != digest:
                raise ValueError('selected_source_integrity')
            row = json.loads(body)
            if row.get('date') != session:
                raise ValueError('selected_source_date')
            saved[session] = row
        changes = []
        for row in candidates:
            old = saved.get(row['date'])
            if old:
                if old.get('sourceRef') != row.get('sourceRef'):
                    continue  # Keep the originally selected provider for this date.
                fields = ('open', 'high', 'low', 'close', 'value', 'volume', 'unit')
                if all(old.get(k) == row.get(k) for k in fields):
                    continue
                previous_receipt = old.get('receivedAt') or (
                    old.get('knownAt') if old.get('availabilityBasis') in
                    ('RECEIVED_CORRECTION', 'PROVISIONAL_SESSION_UPDATE') else None)
                if previous_receipt and _time(received_at) <= _time(previous_receipt):
                    raise ValueError('selected_source_revision_time_order')
                if _time(received_at) < _time(old['availableFrom']):
                    # The session is still inside its conservative availability
                    # bound (Yahoo bars are dated available from the next day
                    # 00:00Z), so an intraday value moving is the session being
                    # formed, not a revision of a published observation. Record
                    # the receipt and keep the bound: point-in-time cutoffs
                    # before it never see this row. Until 2026-09-30 this raised
                    # from the VIX extended session (07:15Z) until midnight, so
                    # the feature history failed for sixteen hours every US
                    # trading day.
                    row = {**row, 'knownAt': received_at, 'availableFrom': old['availableFrom'],
                           'receivedAt': received_at,
                           'publishedAt': None, 'historicalVintageVerified': False,
                           'availabilityBasis': 'PROVISIONAL_SESSION_UPDATE'}
                else:
                    row = {**row, 'knownAt': received_at, 'availableFrom': received_at,
                           'receivedAt': received_at,
                           'publishedAt': None, 'historicalVintageVerified': False,
                           'availabilityBasis': 'RECEIVED_CORRECTION'}
            saved[row['date']] = row
            changes.append(row)
        # The candidate window above is already bounded to the newest 3000
        # sessions; the selection record must be bounded the same way, or the
        # day it holds 3000 sessions the next session raises here forever.
        # That is what happened on 2026-09-28: the store was seeded full on
        # 2026-09-20, and the feature history reported FAILED from the first
        # new session on. Sessions older than the window leave the returned
        # selection; their rows stay in the table as the record of which
        # provider was chosen, and the raw official rows keep their own store.
        if len(saved) > 3000:
            for day in sorted(saved)[:-3000]:
                del saved[day]
        with db:
            for row in changes:
                encoded = _json(row)
                db.execute('INSERT INTO selected_vix_inputs(session,body,sha256,received_at) VALUES(?,?,?,?)',
                           (row['date'], encoded, hashlib.sha256(encoded.encode()).hexdigest(), received_at))
        return [_scheduled_selection(saved[day]) for day in sorted(saved)]
    finally:
        db.close()


def _scheduled_selection(row):
    """Read-side availability of a stored VIX selection (2026-10-04).

    The selection table was seeded on 2026-09-20, before the scheduled
    availability rule (2026-09-30), so its official Cboe rows still carry
    their receipt (2026-09-19) as knownAt. An unchanged stored row is returned
    as stored, so every session from 2016 to 2024 was invisible to every past
    cutoff and the VIX features and D06 had history only from late 2024.
    An original observation is known from the next calendar day 00:00Z (the
    rule of both providers); the receipt stays as receivedAt. Corrections and
    in-session updates keep their own times. The table is not rewritten.
    """
    if (int(row.get('revision', 0) or 0) != 0
            or row.get('availabilityBasis') in ('RECEIVED_CORRECTION', 'PROVISIONAL_SESSION_UPDATE')):
        return row
    scheduled = scheduled_availability('vix_ohlc', row['date'])
    stamps = [row[key] for key in ('publishedAt', 'availableFrom', 'knownAt') if row.get(key)]
    if not stamps or max(_time(stamp) for stamp in stamps) <= _time(scheduled):
        return row
    return {**row, 'knownAt': scheduled, 'availableFrom': scheduled, 'publishedAt': None,
            'receivedAt': row.get('receivedAt') or row.get('knownAt') or row.get('availableFrom'),
            'availabilityBasis': 'SCHEDULED_PUBLICATION'}


# Feature series whose provider re-sends unchanged observations with a new
# receipt and drops its oldest session every day (2026-10-02): the J-Quants
# TOPIX window (receivedAt and the whole-response digest on every row), FRED
# US 10y (the newest 2,600 observations) and Yahoo USD/JPY (a ten-year range).
STABLE_FEATURE_SOURCES = frozenset({'topix', 'us10y', 'usdjpy'})
# Fields that record a receipt, not the observation. Every other field is
# compared, so a changed value, availability or source is still a change.
RECEIPT_FIELDS = frozenset({'receivedAt', 'sourceResponseSha256', 'rawId'})
STABLE_FEATURE_MAX_SESSIONS = 3000


def retain_first_receipts(rows, *, path, source_id, received_at,
                          maximum=STABLE_FEATURE_MAX_SESSIONS):
    """Keep each session's first receipt and the series' fixed origin.

    A re-sent identical observation keeps the row first selected (its own
    receipt and response digest), so the feature history does not see a
    changed input. Sessions that left the provider's rolling window stay in
    the selection, so its origin does not move every day; the newest
    `maximum` sessions are returned. A row whose observation fields changed
    replaces the selection as before; one not yet available at this receipt
    (a session still forming) is returned but not recorded. A cold provider
    cache returns the recorded selection. Raw provider rows are not stored.
    Returns the rows unchanged when there is no durable path.
    """
    if source_id not in STABLE_FEATURE_SOURCES:
        raise ValueError('stable_feature_source_unknown')
    rows = list(rows or [])
    if not path:
        return rows
    receipt = _time(received_at)
    observation = lambda row: {k: v for k, v in row.items() if k not in RECEIPT_FIELDS}
    db = connect(path)
    try:
        db.execute("""CREATE TABLE IF NOT EXISTS selected_feature_inputs(
            seq INTEGER PRIMARY KEY, source_id TEXT NOT NULL, session TEXT NOT NULL,
            body TEXT NOT NULL, sha256 TEXT NOT NULL, received_at TEXT NOT NULL)""")
        saved = {}
        for session, body, digest in db.execute("""SELECT session,body,sha256 FROM selected_feature_inputs
                WHERE seq IN (SELECT max(seq) FROM selected_feature_inputs WHERE source_id=?
                              GROUP BY session)""", (source_id,)):
            if hashlib.sha256(body.encode()).hexdigest() != digest:
                raise ValueError('selected_source_integrity')
            row = json.loads(body)
            if row.get('date') != session:
                raise ValueError('selected_source_date')
            saved[session] = row
        changes, forming = [], {}
        for row in rows:
            session = row.get('date') if isinstance(row, dict) else None
            if not isinstance(session, str) or len(session) != 10:
                raise ValueError('stable_feature_row_date')
            old = saved.get(session)
            if old is not None and observation(old) == observation(row):
                continue  # the same observation re-sent: keep its first receipt
            available = row.get('availableFrom')
            if not available or _time(available) > receipt:
                forming[session] = row
                continue
            saved[session] = row
            changes.append(row)
        with db:
            for row in changes:
                encoded = _json(row)
                db.execute('INSERT INTO selected_feature_inputs(source_id,session,body,sha256,received_at) '
                           'VALUES(?,?,?,?,?)', (source_id, row['date'], encoded,
                                                 hashlib.sha256(encoded.encode()).hexdigest(), received_at))
        merged = {**saved, **forming}
        return [merged[day] for day in sorted(merged)][-maximum:]
    finally:
        db.close()


def apply_scheduled_availability(rows, *, lag_days, source_label):
    """Read-side rule for provider rows whose only stamp is their receipt.

    An original observation (revision 0 or none) becomes available `lag_days`
    after its period end at 00:00Z when that is earlier than its receipt; the
    receipt stays as receivedAt and the raw rows are untouched. Corrections
    (revision >= 1) keep their receipt. Used for the weekly JPX margin
    balances of 1570 (published on the second business day after the Friday;
    six days is conservative). Not vintage proof.
    """
    if isinstance(lag_days, bool) or not isinstance(lag_days, int) or not 0 <= lag_days <= 14:
        raise ValueError('scheduled_lag_bound')
    result = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        period = str(row.get('periodEnd') or row.get('date') or '')[:10]
        known = row.get('knownAt') or row.get('availableFrom')
        if len(period) != 10 or not known or int(row.get('revision', 0) or 0) != 0:
            result.append(row); continue
        try:
            scheduled = (date.fromisoformat(period) + timedelta(days=lag_days)).isoformat() + 'T00:00:00Z'
            if _time(scheduled) < _time(str(known)):
                row = {**row, 'knownAt': scheduled, 'availableFrom': scheduled,
                       'receivedAt': row.get('receivedAt') or known,
                       'availabilityBasis': 'SCHEDULED_PUBLICATION',
                       'availabilityRule': source_label}
        except ValueError:
            pass
        result.append(row)
    return result


def enforce_session_publication(rows, *, sessions, sessions_after, utc_time, source_label):
    """Never let a weekly row be known before its publication session.

    The publication day of a weekly JPX series is counted in actual TSE
    sessions after the period end, so holidays push it later (the week ending
    2026-09-18 could not be read before Monday 09-28). `sessions` are the dates
    of real trading sessions; past their end the count continues on weekdays.
    Any publishedAt/availableFrom/knownAt earlier than that instant is raised
    to it; later ones are untouched. Read-side only (look-ahead audit
    2026-10-02).
    """
    if isinstance(sessions_after, bool) or not isinstance(sessions_after, int) or not 1 <= sessions_after <= 10:
        raise ValueError('session_publication_bound')
    # Keep the existing source-specific call contract so every consumer uses
    # the same cutover, including callers that still supply the older bound.
    # Other weekly series retain their own publication rule.
    if source_label == 'jpx-two-market-third-session':
        rows = list(rows)
        if any(isinstance(row, dict) and
               str(row.get('periodEnd') or row.get('date') or '')[:10] >= '2026-09-25'
               for row in rows):
            return enforce_two_market_publication(rows, sessions=sessions)
    days = sorted({str(day)[:10] for day in sessions if len(str(day)) >= 10})
    result = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        period = str(row.get('periodEnd') or row.get('date') or '')[:10]
        try:
            end = date.fromisoformat(period)
        except ValueError:
            result.append(row); continue
        later = days[bisect.bisect_right(days, period):]
        if len(later) >= sessions_after:
            floor_day = date.fromisoformat(later[sessions_after - 1])
        else:
            floor_day = date.fromisoformat(later[-1]) if later else end
            for _ in range(sessions_after - len(later)):
                floor_day += timedelta(days=1)
                while floor_day.weekday() >= 5:
                    floor_day += timedelta(days=1)
        floor = floor_day.isoformat() + 'T' + utc_time + 'Z'
        raised = {}
        for key in ('publishedAt', 'availableFrom', 'knownAt'):
            try:
                if row.get(key) and _time(str(row[key])) < _time(floor):
                    raised[key] = floor
            except ValueError:
                pass   # malformed stamps stay as they are; the reader rejects them
        if raised:
            row = {**row, **raised, 'availabilityFloor': source_label}
        result.append(row)
    return result


def enforce_two_market_publication(rows, *, sessions):
    """Respect the JPX rule change from the week ending 2026-09-25.

    Earlier inputs keep the existing conservative third-session bound. New
    weekly workbooks use the second actual TSE session at 16:00 JST, including
    holidays beyond the cached price window. This is an availability bound,
    not evidence of a historical publication or receipt. Later receipts stay
    later; raw records and publication stamps are never rewritten here.
    """
    import argus_market_clock as clock
    out = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        period = str(row.get('periodEnd') or row.get('date') or '')[:10]
        try:
            end = date.fromisoformat(period)
        except ValueError:
            out.append(row); continue
        if period < '2026-09-25':
            out.extend(enforce_session_publication(
                [row], sessions=sessions, sessions_after=3, utc_time='06:00:00',
                source_label='jpx-two-market-third-session'))
            continue
        day, count = end, 0
        try:
            for _ in range(14):
                day += timedelta(days=1)
                if clock.canonical_trading_day(clock.JP_EQUITY, day):
                    count += 1
                    if count == 2:
                        break
        except clock.CalendarUnavailableError:
            raise ValueError('two_market_publication_calendar_unavailable') from None
        if count != 2:
            raise ValueError('two_market_publication_calendar_invalid')
        floor = day.isoformat() + 'T07:00:00Z'
        raised = {}
        for key in ('availableFrom', 'knownAt'):
            try:
                if row.get(key) and _time(str(row[key])) < _time(floor):
                    raised[key] = floor
            except ValueError:
                pass  # Invalid stamps stay invalid for the existing reader.
        if raised:
            row = {**row, **raised, 'availabilityFloor': 'jpx-two-market-second-session-16jst'}
        out.append(row)
    return out
