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
    'unifiedStatus', 'lastSuccessfulAiAt', 'sdaAuthority', 'noteJa', 'hasCritical')


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


def read_record(path, record_id=None):
    if record_id is not None and not re.fullmatch('[a-f0-9]{64}', str(record_id)):
        raise ValueError('invalid_analysis_record_id')
    conn = _connect(path, True)
    try:
        row = (conn.execute('SELECT record_id,body FROM views WHERE record_id=?', (record_id,)).fetchone()
               if record_id else conn.execute('SELECT record_id,body FROM views ORDER BY sequence DESC LIMIT 1').fetchone())
        if not row: return None
        record = validate_record(json.loads(row[1]))
        if record['recordId'] != row[0]: raise ValueError('analysis_index_integrity_mismatch')
        return record
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
