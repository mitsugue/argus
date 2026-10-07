"""Immutable public market explanations and calculation inputs on persistent storage.

This store has no provider, order or portfolio access. Read paths cannot create
or repair files. Results append separately and never rewrite an issued view.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import tempfile
from datetime import datetime

from argus_product_naming import require_allowed

SCHEMA = 'argus-market-analysis-record-v1'
MAX_RECORD_BYTES = 2 * 1024 * 1024
BRIEF_FIELDS = ('schemaVersion', 'generatedAt', 'facts', 'chips', 'now', 'why', 'next',
    'aiText', 'aiModel', 'aiDiagnostics', 'unifiedContext', 'unifiedSummary',
    'unifiedStatus', 'lastSuccessfulAiAt', 'sdaAuthority', 'noteJa', 'hasCritical',
    'presentationCatalog', 'presentationPlan', 'presentationStatus', 'numericalResearch',
    'fiscalEnvironment')


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def _instant(value):
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('analysis_time_requires_timezone')
    return parsed


def make_record(brief, calculations):
    if brief.get('unifiedStatus') != 'GENERATED' or brief.get('sdaAuthority') is not False:
        raise ValueError('accepted_non_authoritative_explanation_required')
    context, summary = brief['unifiedContext'], brief['unifiedSummary']
    if context.get('ownerContextAvailable') is not False or summary.get('ownerContextAvailable') is not False:
        raise ValueError('public_history_cannot_contain_owner_context')
    if summary['contextId'] != context['contextId'] or summary.get('actionAuthority') is not False:
        raise ValueError('matching_non_authoritative_context_required')
    recorded_at = brief['aiDiagnostics']['completedAt']
    _instant(recorded_at)
    if (not isinstance(calculations, dict) or set(calculations) - {'1', '5', '10', '20'}
            or any(not isinstance(value, dict) for value in calculations.values())):
        raise ValueError('known_calculation_horizons_required')
    body = {'schemaVersion': SCHEMA, 'recordedAt': recorded_at, 'scope': 'PUBLIC_MARKET',
            'brief': {k: brief[k] for k in BRIEF_FIELDS if k in brief},
            'calculations': calculations, 'actionAuthority': False,
            'inputSnapshotDigest': hashlib.sha256(_json({'context': context, 'calculations': calculations}).encode()).hexdigest()}
    require_allowed(body)
    encoded = _json(body).encode()
    if len(encoded) > MAX_RECORD_BYTES:
        raise ValueError('analysis_record_bound_exceeded')
    return {'recordId': hashlib.sha256(encoded).hexdigest(), **json.loads(encoded)}


def validate_record(value):
    if not isinstance(value, dict) or value.get('schemaVersion') != SCHEMA:
        raise ValueError('analysis_schema_invalid')
    rebuilt = make_record(value['brief'], value['calculations'])
    if rebuilt != value:
        raise ValueError('analysis_record_integrity_mismatch')
    return rebuilt


def _connect(path, readonly=False):
    path = Path(path)
    if path.is_symlink() or not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError('analysis_history_regular_file_required')
    conn = sqlite3.connect(path.resolve().as_uri() + ('?mode=ro' if readonly else '?mode=rw'),
                           uri=True, timeout=15, isolation_level=None)
    if conn.execute('PRAGMA user_version').fetchone()[0] != 1:
        conn.close(); raise ValueError('analysis_history_schema_invalid')
    if not readonly:
        conn.execute('PRAGMA synchronous=FULL')
        conn.execute('PRAGMA foreign_keys=ON')
    return conn


def initialize(path):
    path = Path(path)
    if path.exists() or path.is_symlink():
        _connect(path, True).close(); return
    fd, temporary = tempfile.mkstemp(prefix='.analysis-history-', dir=path.parent)
    os.close(fd)
    try:
        conn = sqlite3.connect(temporary, isolation_level=None)
        try:
            conn.executescript('''PRAGMA synchronous=FULL;
                BEGIN IMMEDIATE;
                CREATE TABLE views(sequence INTEGER PRIMARY KEY, record_id TEXT NOT NULL UNIQUE,
                  recorded_at TEXT NOT NULL, body TEXT NOT NULL);
                CREATE TABLE outcomes(sequence INTEGER PRIMARY KEY, result_id TEXT NOT NULL UNIQUE,
                  record_id TEXT NOT NULL REFERENCES views(record_id), body TEXT NOT NULL);
                PRAGMA user_version=1; COMMIT;''')
        finally: conn.close()
        with open(temporary, 'rb') as handle: os.fsync(handle.fileno())
        try: os.link(temporary, path, follow_symlinks=False)
        except FileExistsError: _connect(path, True).close()
        directory = os.open(path.parent, os.O_RDONLY)
        try: os.fsync(directory)
        finally: os.close(directory)
    finally: os.unlink(temporary)


def append(path, record):
    record = validate_record(record); body = _json(record)
    conn = _connect(path)
    try:
        conn.execute('BEGIN IMMEDIATE')
        existing = conn.execute('SELECT body FROM views WHERE record_id=?', (record['recordId'],)).fetchone()
        if existing and existing[0] != body: raise ValueError('conflicting_analysis_record_id')
        if not existing:
            conn.execute('INSERT INTO views(record_id,recorded_at,body) VALUES(?,?,?)',
                         (record['recordId'], record['recordedAt'], body))
        conn.execute('COMMIT')
        return {'recordId': record['recordId'], 'inserted': not bool(existing), 'status': 'LOCAL_DURABLE'}
    except Exception:
        if conn.in_transaction: conn.execute('ROLLBACK')
        raise
    finally: conn.close()


def read_record(path, record_id=None, *, presentation_only=False):
    if record_id is not None and not re.fullmatch('[a-f0-9]{64}', str(record_id)):
        raise ValueError('invalid_analysis_record_id')
    conn = _connect(path, True)
    try:
        row = (conn.execute('SELECT record_id,body FROM views WHERE record_id=?', (record_id,)).fetchone()
               if record_id else conn.execute('SELECT record_id,body FROM views '
                   + ("WHERE json_extract(body,'$.brief.presentationStatus')='GENERATED' " if presentation_only else '')
                   + 'ORDER BY julianday(recorded_at) DESC,sequence DESC LIMIT 1').fetchone())
        if not row: return None
        record = validate_record(json.loads(row[1]))
        if record['recordId'] != row[0]: raise ValueError('analysis_index_integrity_mismatch')
        return record
    finally: conn.close()


def summary(path):
    """Row counts and the latest view id without reading any record body."""
    conn = _connect(path, True)
    try:
        views = conn.execute('SELECT COUNT(*) FROM views').fetchone()[0]
        outcomes = conn.execute('SELECT COUNT(*) FROM outcomes').fetchone()[0]
        latest = conn.execute('SELECT record_id FROM views ORDER BY julianday(recorded_at) DESC,sequence DESC LIMIT 1').fetchone()
        return {'counts': {'views': int(views), 'outcomes': int(outcomes)},
                'latestRecordId': latest[0] if latest else None}
    finally: conn.close()


def read_page_index(path, *, before_sequence=None, limit=20):
    """Sequence and record id only, newest first; no body leaves the database."""
    if type(limit) is not int or not 1 <= limit <= 100 or (before_sequence is not None and
            (type(before_sequence) is not int or before_sequence < 1)):
        raise ValueError('invalid_analysis_history_cursor')
    conn = _connect(path, True)
    try:
        rows = conn.execute('SELECT sequence,record_id FROM views WHERE sequence<? ORDER BY sequence DESC LIMIT ?',
                            (before_sequence if before_sequence is not None else 9223372036854775807, limit + 1)).fetchall()
        entries = [{'sequence': seq, 'recordId': identity} for seq, identity in rows[:limit]]
        return {'rows': entries, 'hasMore': len(rows) > limit,
                'nextBeforeSequence': entries[-1]['sequence'] if entries else None}
    finally: conn.close()


def read_page(path, *, before_sequence=None, limit=20):
    if type(limit) is not int or not 1 <= limit <= 100 or (before_sequence is not None and
            (type(before_sequence) is not int or before_sequence < 1)):
        raise ValueError('invalid_analysis_history_cursor')
    conn = _connect(path, True)
    try:
        rows = conn.execute('SELECT sequence,record_id,body FROM views WHERE sequence<? ORDER BY sequence DESC LIMIT ?',
                            (before_sequence if before_sequence is not None else 9223372036854775807, limit + 1)).fetchall()
        entries = []
        for seq, identity, body in rows[:limit]:
            record = validate_record(json.loads(body))
            if record['recordId'] != identity: raise ValueError('analysis_index_integrity_mismatch')
            entries.append({'sequence': seq, 'recordId': identity, 'recordedAt': record['recordedAt'],
                'inputSnapshotDigest': record['inputSnapshotDigest'],
                'contextId': record['brief']['unifiedContext']['contextId'],
                'sections': record['brief']['unifiedSummary']['sections'],
                'requestedModel': record['brief']['aiDiagnostics'].get('requestedModel'),
                'returnedModel': record['brief']['aiDiagnostics'].get('returnedModel'),
                'calculationHorizons': sorted(record['calculations'])})
        return {'status': 'AVAILABLE', 'scope': 'PUBLIC_MARKET', 'rows': entries,
                'hasMore': len(rows) > limit, 'nextBeforeSequence': entries[-1]['sequence'] if entries else None,
                'storage': 'PERSISTENT_ROOT_SQLITE', 'remoteRecoveryVerified': False,
                'readOnly': True, 'actionAuthority': False}
    finally: conn.close()


def outcome_candidates(record, price_rows, *, received_at):
    """Compare saved N225 paths with later completed cash-index sessions only."""
    from datetime import date, timedelta
    import math
    import argus_market_clock as clock
    record = validate_record(record)
    received = _instant(received_at)
    issued = _instant(record['recordedAt'])
    if received < issued: return []
    outcomes = []
    for key, calculation in record['calculations'].items():
        chart = calculation.get('comparison') or {}
        forecast = chart.get('forecast') or {}
        if chart.get('schemaVersion') != 'jp-market-comparison-v1' or forecast.get('horizonSessions') != int(key):
            continue
        target = date.fromisoformat(chart['anchorDate']); remaining = int(key)
        try:
            while remaining:
                target += timedelta(days=1)
                if clock.canonical_trading_day(clock.JP_EQUITY, target): remaining -= 1
        except clock.CalendarUnavailableError:
            continue
        close_at = clock.market_session_bounds(clock.JP_EQUITY, target)['regularCloseUtc']
        if not close_at or _instant(close_at) <= issued or _instant(close_at) > received:
            continue
        matched = [row for row in price_rows if row.get('date') == target.isoformat()]
        if len(matched) != 1: continue
        price = matched[0].get('close')
        anchor = chart.get('actualAnchorPrice')
        if not all(type(v) in (int,float) and math.isfinite(v) and v > 0 for v in (price,anchor)):
            continue
        last = [p for p in forecast.get('line',[]) if p.get('offsetSessions') == int(key)]
        if len(last) != 1 or chart.get('unit') not in ('ANCHOR_100','JPY_INDEX_POINTS'): continue
        predicted = last[0]['value'] * anchor / 100 if chart['unit'] == 'ANCHOR_100' else last[0]['value']
        if type(predicted) not in (int,float) or not math.isfinite(predicted) or predicted <= 0: continue
        threshold = forecast.get('flatThresholdPct')
        if type(threshold) not in (int,float) or not math.isfinite(threshold) or threshold < 0: continue
        compared_actual = price / anchor * 100 if chart['unit'] == 'ANCHOR_100' else price
        change = (price / anchor - 1) * 100
        body = {'schemaVersion':'argus-analysis-outcome-v1','recordId':record['recordId'],
            'instrumentId':'NIKKEI_225_INDEX','horizonSessions':int(key),'targetDate':target.isoformat(),
            'actualClose':price,'actualChangePct':change,
            'forecastValue':last[0]['value'],'actualComparisonValue':compared_actual,'comparisonUnit':chart['unit'],
            'absoluteErrorPct':abs(predicted-price)/price*100,
            'flatThresholdPct':threshold,'actualClass':'up' if change>threshold else 'down' if change < -threshold else 'flat',
            'source':'Yahoo Finance cash index daily close','sourceCloseAt':close_at,
            'engineValidationStatus':forecast.get('validationStatus'),'predictiveProbabilityVerified':False,
            'actionAuthority':False}
        identity = hashlib.sha256(_json(body).encode()).hexdigest()
        body.update(resultId=identity,receivedAt=received_at)
        body['resultDigest'] = hashlib.sha256(_json(body).encode()).hexdigest()
        outcomes.append(body)
    return outcomes


def append_outcomes(path, values):
    values = list(values)
    if len(values)>400: raise ValueError('analysis_outcome_batch_bound')
    conn=_connect(path)
    try:
        conn.execute('BEGIN IMMEDIATE'); inserted=0
        for row in values:
            body=dict(row);digest=body.pop('resultDigest')
            if hashlib.sha256(_json(body).encode()).hexdigest()!=digest: raise ValueError('analysis_outcome_integrity')
            require_allowed(row)
            previous=conn.execute('SELECT body FROM outcomes WHERE result_id=?',(row['resultId'],)).fetchone()
            if previous:
                prior=json.loads(previous[0])
                if {k:v for k,v in prior.items() if k not in ('receivedAt','resultDigest')} != {k:v for k,v in row.items() if k not in ('receivedAt','resultDigest')}:
                    raise ValueError('analysis_outcome_identity_conflict')
                continue
            conn.execute('INSERT INTO outcomes(result_id,record_id,body) VALUES(?,?,?)',(row['resultId'],row['recordId'],_json(row)));inserted+=1
        conn.execute('COMMIT'); return inserted
    except Exception:
        if conn.in_transaction:conn.execute('ROLLBACK')
        raise
    finally:conn.close()


def read_outcomes(path, record_id):
    conn=_connect(path,True)
    try:
        values=[]
        for (body,) in conn.execute('SELECT body FROM outcomes WHERE record_id=? ORDER BY sequence',(record_id,)):
            row=json.loads(body);check=dict(row);digest=check.pop('resultDigest')
            if hashlib.sha256(_json(check).encode()).hexdigest()!=digest:raise ValueError('analysis_outcome_integrity')
            values.append(row)
        return values
    finally:conn.close()


TRACK_RECORD_MINIMUM = 20


def _wilson_lower(hits, total, z=1.959963984540054):
    import math
    if total <= 0: return None
    p = hits / total; centre = p + z * z / (2 * total)
    margin = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total))
    return (centre - margin) / (1 + z * z / total)


def track_record(path):
    """Direction record of the Nikkei paths this product actually issued.

    One forecast per (horizon, anchor session): the earliest view issued before
    the first session of its horizon opened, so no counted forecast saw any of
    the move it is scored on. The latest appended result for that view is used
    (a corrected close replaces the first reading). Frequencies of past issued
    forecasts, never a probability for the next one.
    """
    from datetime import date, timedelta
    import argus_market_clock as clock
    conn = _connect(path, True)
    try:
        rows = conn.execute('SELECT o.body, v.recorded_at FROM outcomes o JOIN views v ON o.record_id=v.record_id '
                            'ORDER BY julianday(v.recorded_at), v.sequence, o.sequence').fetchall()
    finally: conn.close()
    chosen = {}
    for body, recorded_at in rows:
        row = json.loads(body)
        horizon, target = row.get('horizonSessions'), row.get('targetDate')
        if horizon not in (1, 5, 10, 20) or not isinstance(target, str): continue
        key = (horizon, target)
        if key in chosen and chosen[key]['recordId'] != row['recordId']: continue
        first = date.fromisoformat(target); remaining = horizon - 1
        try:
            while remaining:
                first -= timedelta(days=1)
                if clock.canonical_trading_day(clock.JP_EQUITY, first): remaining -= 1
            opened = clock.market_session_bounds(clock.JP_EQUITY, first)['regularOpenUtc']
        except clock.CalendarUnavailableError:
            continue
        if not opened or _instant(recorded_at) >= _instant(opened): continue
        chosen[key] = row
    horizons = {}
    for horizon in (1, 5, 10, 20):
        hits = up = down = directional = 0; dates = []
        for (h, target), row in sorted(chosen.items()):
            if h != horizon: continue
            threshold, value = row['flatThresholdPct'], row['forecastValue']
            if row['comparisonUnit'] == 'ANCHOR_100':
                predicted_change = value - 100
            else:
                anchor = row['actualClose'] / (1 + row['actualChangePct'] / 100)
                predicted_change = (value / anchor - 1) * 100
            predicted = 'up' if predicted_change > threshold else 'down' if predicted_change < -threshold else 'flat'
            dates.append(target)
            if predicted == 'flat': continue
            directional += 1; hits += row['actualClass'] == predicted
            up += row['actualClass'] == 'up'; down += row['actualClass'] == 'down'
        rate = hits / directional if directional else None
        naive = max(up, down) / directional if directional else None
        lower = _wilson_lower(hits, directional)
        status = ('INSUFFICIENT_SAMPLE' if directional < TRACK_RECORD_MINIMUM
                  else 'ABOVE_BASELINE' if lower is not None and lower > naive else 'NOT_ABOVE_BASELINE')
        horizons[str(horizon)] = {'horizonSessions': horizon, 'scoredForecasts': len(dates),
            'directionalForecasts': directional, 'hits': hits, 'hitRate': rate,
            'hitRateWilsonLower95': lower, 'naiveMajorityRate': naive, 'status': status,
            'firstTargetDate': dates[0] if dates else None, 'lastTargetDate': dates[-1] if dates else None}
    return {'schemaVersion': 'argus-forecast-track-record-v1', 'instrumentId': 'NIKKEI_225_INDEX',
            'minimumDirectionalForecasts': TRACK_RECORD_MINIMUM, 'horizons': horizons,
            'predictiveProbabilities': None, 'actionAuthority': False}


# --- Nikkei morning level map (2026-10-04) ---------------------------------------
# Two append-only tables in the same file: the daily ARGUS EPS estimate and the
# map fixed before each open. The first body stored for a date is kept; a later
# different body for the same date is refused and reported, never written. The
# views/outcomes tables and their remote backup are not changed: these tables
# are local-durable only until the backup carries them (documented).
_LEVEL_MAP_TABLES = '''CREATE TABLE IF NOT EXISTS level_map_eps(session TEXT PRIMARY KEY,
      recorded_at TEXT NOT NULL, body TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS level_map_mornings(morning_of TEXT PRIMARY KEY, record_id TEXT NOT NULL UNIQUE,
      created_at TEXT NOT NULL, body TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS candidate_records(record_key TEXT PRIMARY KEY, record_id TEXT NOT NULL UNIQUE,
      recorded_at TEXT NOT NULL, body TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS future_map_versions(record_id TEXT PRIMARY KEY,
      recorded_at TEXT NOT NULL, body TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS future_map_outcomes(outcome_id TEXT PRIMARY KEY,
      record_id TEXT NOT NULL REFERENCES future_map_versions(record_id),
      recorded_at TEXT NOT NULL, body TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS level_map_eps_corrections(correction_id TEXT PRIMARY KEY,
      session TEXT NOT NULL, recorded_at TEXT NOT NULL, original_sha256 TEXT NOT NULL, body TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS level_map_morning_corrections(correction_id TEXT PRIMARY KEY,
      morning_of TEXT NOT NULL, created_at TEXT NOT NULL, original_sha256 TEXT NOT NULL, body TEXT NOT NULL);'''


def _append_once(path, table, key_column, key, values):
    conn = _connect(path)
    try:
        conn.executescript(_LEVEL_MAP_TABLES)
        conn.execute('BEGIN IMMEDIATE')
        existing = conn.execute(f'SELECT body FROM {table} WHERE {key_column}=?', (key,)).fetchone()
        body = values[-1]
        if existing:
            conn.execute('COMMIT')
            return {'inserted': False, 'conflict': existing[0] != body}
        marks = ','.join('?' * len(values))
        conn.execute(f'INSERT INTO {table} VALUES({marks})', values)
        conn.execute('COMMIT')
        return {'inserted': True, 'conflict': False}
    except Exception:
        if conn.in_transaction: conn.execute('ROLLBACK')
        raise
    finally: conn.close()


def append_level_map_eps(path, record):
    session = str(record.get('date') or '')
    datetime.fromisoformat(session)
    return _append_once(path, 'level_map_eps', 'session', session,
                        (session, str(record.get('recordedAt') or ''), _json(record)))


def append_level_map_eps_correction(path, record):
    """Append a complete replacement for a known partial input, keep its original.

    This never changes a morning map or a valid first estimate. The receipt
    ordering and original digest are part of the immutable correction.
    """
    import jp_market_level_map as levels
    session = str(record.get('date') or '')
    datetime.fromisoformat(session)
    received = _instant(str(record.get('recordedAt') or ''))
    if record.get('basis') != levels.EPS_BASIS or not levels.estimate_input_usable(record, strict=True):
        raise ValueError('level_map_eps_complete_correction_required')
    conn = _connect(path)
    try:
        conn.executescript(_LEVEL_MAP_TABLES);conn.execute('BEGIN IMMEDIATE')
        old = conn.execute('SELECT body FROM level_map_eps WHERE session=?',(session,)).fetchone()
        if old is None or levels.estimate_input_usable(json.loads(old[0])):
            raise ValueError('level_map_eps_incomplete_original_required')
        original = json.loads(old[0])
        if original.get('basis') != record.get('basis') or received <= _instant(original['recordedAt']):
            raise ValueError('level_map_eps_correction_receipt_order')
        digest = hashlib.sha256(old[0].encode()).hexdigest();body = _json(record)
        identity = hashlib.sha256(_json([session,digest,record]).encode()).hexdigest()
        inserted = conn.execute('INSERT OR IGNORE INTO level_map_eps_corrections VALUES(?,?,?,?,?)',
            (identity,session,record['recordedAt'],digest,body)).rowcount
        conn.execute('COMMIT')
        return {'inserted':bool(inserted),'conflict':False,'correctionId':identity}
    except Exception:
        if conn.in_transaction:conn.execute('ROLLBACK')
        raise
    finally:conn.close()


def append_level_map_morning_correction(path, record):
    """Correct only a known partial future morning, before its market open."""
    import jp_market_level_map as levels
    day=str(record.get('morningOf') or '');datetime.fromisoformat(day)
    created=_instant(str(record.get('createdAt') or ''))
    if (not str(record.get('recordId') or '').startswith('lm-')
            or not levels.estimate_input_usable({'coverage':record.get('epsCoverage')},strict=True)
            or created >= _instant(day+'T00:00:00Z')):
        raise ValueError('level_map_complete_preopen_correction_required')
    conn=_connect(path)
    try:
        conn.executescript(_LEVEL_MAP_TABLES);conn.execute('BEGIN IMMEDIATE')
        old=conn.execute('SELECT body FROM level_map_mornings WHERE morning_of=?',(day,)).fetchone()
        if old is None or levels.morning_input_usable(json.loads(old[0])):
            raise ValueError('level_map_incomplete_original_required')
        original=json.loads(old[0])
        if (original.get('epsBasis')!=record.get('epsBasis')
                or created <= _instant(original['createdAt'])):
            raise ValueError('level_map_correction_receipt_order')
        digest=hashlib.sha256(old[0].encode()).hexdigest();body=_json(record)
        identity=hashlib.sha256(_json([day,digest,record]).encode()).hexdigest()
        inserted=conn.execute('INSERT OR IGNORE INTO level_map_morning_corrections VALUES(?,?,?,?,?)',
            (identity,day,record['createdAt'],digest,body)).rowcount
        conn.execute('COMMIT')
        return {'inserted':bool(inserted),'conflict':False,'correctionId':identity}
    except Exception:
        if conn.in_transaction:conn.execute('ROLLBACK')
        raise
    finally:conn.close()


def read_level_map_eps_originals(path, *, morning=False):
    conn = _connect(path, True)
    try:
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        table,column=('level_map_mornings','morning_of') if morning else ('level_map_eps','session')
        correction_table='level_map_morning_corrections' if morning else 'level_map_eps_corrections'
        originals = {r[0]:json.loads(r[1]) for r in conn.execute(f'SELECT {column},body FROM {table} ORDER BY {column}')} if table in names else {}
        corrections = [{'correctionId':r[0],'date':r[1],'recordedAt':r[2],'originalSha256':r[3],'record':json.loads(r[4])}
            for r in conn.execute(f'SELECT * FROM {correction_table} ORDER BY {column},'+('created_at' if morning else 'recorded_at')+',correction_id')] if correction_table in names else []
        return originals,corrections
    finally:conn.close()


def append_level_map(path, record):
    morning = str(record.get('morningOf') or '')
    datetime.fromisoformat(morning)
    if not str(record.get('recordId') or '').startswith('lm-'):
        raise ValueError('level_map_record_id_required')
    return _append_once(path, 'level_map_mornings', 'morning_of', morning,
                        (morning, record['recordId'], str(record.get('createdAt') or ''), _json(record)))


def read_level_map_state(path):
    """Every stored estimate (by session) and every stored morning map, oldest first."""
    conn = _connect(path, True)
    try:
        names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        eps = {}
        if 'level_map_eps' in names:
            eps = {row[0]: json.loads(row[1]) for row in conn.execute(
                'SELECT session, body FROM level_map_eps ORDER BY session')}
        if 'level_map_eps_corrections' in names:
            for session,body in sorted(conn.execute('SELECT session,body FROM level_map_eps_corrections'),key=lambda row:_instant(json.loads(row[1])['recordedAt'])):
                eps[session]=json.loads(body)
        mornings = []
        if 'level_map_mornings' in names:
            mornings = [json.loads(row[0]) for row in conn.execute(
                'SELECT body FROM level_map_mornings ORDER BY morning_of')]
        if 'level_map_morning_corrections' in names:
            corrected={m['morningOf']:m for m in mornings}
            for body, in sorted(conn.execute('SELECT body FROM level_map_morning_corrections'),key=lambda row:_instant(json.loads(row[0])['createdAt'])):
                row=json.loads(body);corrected[row['morningOf']]=row
            mornings=[corrected[day] for day in sorted(corrected)]
        return {'eps': eps, 'mornings': mornings}
    finally: conn.close()


# Pre-registered candidate signals (2026-10-04): one record per candidate and
# signal day, first body kept, same file and same rules as the level map.
def append_candidate_record(path, record):
    candidate, day = str(record.get('candidate') or ''), str(record.get('signalDate') or '')
    datetime.fromisoformat(day)
    if not candidate or not str(record.get('recordId') or '').startswith('cr-'):
        raise ValueError('candidate_record_identity_required')
    return _append_once(path, 'candidate_records', 'record_key', f'{candidate}:{day}',
                        (f'{candidate}:{day}', record['recordId'], str(record.get('recordedAt') or ''), _json(record)))


def read_candidate_records(path):
    conn = _connect(path, True)
    try:
        names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if 'candidate_records' not in names:
            return []
        return [json.loads(row[0]) for row in conn.execute('SELECT body FROM candidate_records ORDER BY record_key')]
    finally: conn.close()


def _validate_future_map_version(record):
    from argus_future_map_scoring import registration
    if registration(record['row'], received_at=record['recordedAt']) != record:
        raise ValueError('future_map_registration_integrity')
    require_allowed(record)


def append_future_map_version(path, record):
    _validate_future_map_version(record)
    return _append_once(path, 'future_map_versions', 'record_id', record['recordId'],
                        (record['recordId'], record['recordedAt'], _json(record)))


def _validate_future_map_outcome(outcome):
    from argus_future_map_scoring import digest, instant, METHOD
    instant(outcome['scoredAt'])
    body = {key: value for key, value in outcome.items() if key not in ('scoredAt', 'outcomeId')}
    if (outcome.get('schemaVersion') != METHOD or outcome.get('status') != 'SCORED'
            or outcome.get('result') not in ('reached', 'missed')
            or outcome.get('actionAuthority') is not False
            or outcome.get('turningPointValidated') is not False
            or outcome.get('probability') is not None
            or outcome.get('outcomeId') != 'fmo-' + digest(body)):
        raise ValueError('future_map_outcome_integrity')
    require_allowed(outcome)


def append_future_map_outcome(path, outcome):
    _validate_future_map_outcome(outcome)
    return _append_once(path, 'future_map_outcomes', 'outcome_id', outcome['outcomeId'],
                        (outcome['outcomeId'], outcome['recordId'], outcome['scoredAt'], _json(outcome)))


def read_future_map_state(path):
    conn = _connect(path, True)
    try:
        names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        versions = ([json.loads(row[0]) for row in conn.execute(
            'SELECT body FROM future_map_versions ORDER BY recorded_at, rowid')]
            if 'future_map_versions' in names else [])
        outcomes = ([json.loads(row[0]) for row in conn.execute(
            'SELECT body FROM future_map_outcomes ORDER BY rowid')]
            if 'future_map_outcomes' in names else [])
        for record in versions:
            _validate_future_map_version(record)
        ids = {record['recordId'] for record in versions}
        for outcome in outcomes:
            _validate_future_map_outcome(outcome)
            if outcome['recordId'] not in ids:
                raise ValueError('future_map_outcome_registration_missing')
        return {'versions': versions, 'outcomes': outcomes}
    finally: conn.close()
