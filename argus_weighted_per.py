"""Manual, owner-private calibration in the existing owner database.

The original estimates, morning records and scores are never rewritten.
No provider or AI request is made here. Only the latest manual reference is
retained locally; the existing private backup connection copies this state.
"""
from datetime import date, datetime, timedelta, timezone
import json
import math
import hashlib
from flask import current_app, jsonify, request
import argus_market_clock as clock

SCHEMA = 'owner-weighted-per-v1'
REMOTE_PATH = 'market-analysis/v1/level-map/owner-weighted-per.json'
JST = timezone(timedelta(hours=9))


def number(v):
    return type(v) in (int, float) and math.isfinite(v) and v > 0


def instant(v):
    value = datetime.fromisoformat(v.replace('Z', '+00:00'))
    if value.tzinfo is None:
        raise ValueError('invalid_time')
    return value


def prepare(auth):
    if auth.enabled:
        with auth.db() as conn:
            conn.execute('CREATE TABLE IF NOT EXISTS owner_weighted_per (id INTEGER PRIMARY KEY CHECK(id=1), body TEXT NOT NULL)')
            conn.execute('CREATE TABLE IF NOT EXISTS owner_weighted_per_estimates (id TEXT PRIMARY KEY, body TEXT NOT NULL)')
            conn.execute('CREATE TABLE IF NOT EXISTS owner_weighted_per_history (id TEXT PRIMARY KEY, body TEXT NOT NULL)')


# 2026-10-27 (owner): watch the gap between the estimate and the official value.
# Every saved official input is kept (append only) with the same-day estimate;
# the gap is the estimated EPS against the official EPS. A large gap or a large
# move since the previous input is flagged; nothing else is changed by it.
DRIFT_WARN_PCT = 5.0
DRIFT_MOVE_PCT = 3.0
HISTORY_LIMIT = 520


def _history_row(ref):
    value = {'date': ref['date'], 'per': ref['per'], 'indexClose': ref['indexClose'],
             'estimateEps': ref['estimateEps'], 'ratio': ref['ratio'], 'receivedAt': ref['receivedAt']}
    raw = json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)
    return hashlib.sha256(raw.encode()).hexdigest(), raw


def remember_reference(conn, ref):
    """Append one official input to the history (idempotent)."""
    if ref:
        conn.execute('INSERT OR IGNORE INTO owner_weighted_per_history VALUES(?,?)', _history_row(ref))


def history_records(conn):
    rows = []
    for row in conn.execute('SELECT id,body FROM owner_weighted_per_history ORDER BY id'):
        raw = row['body']; value = json.loads(raw)
        if (hashlib.sha256(raw.encode()).hexdigest() != row['id']
                or set(value) != {'date', 'per', 'indexClose', 'estimateEps', 'ratio', 'receivedAt'}
                or not all(number(value[k]) for k in ('per', 'indexClose', 'estimateEps', 'ratio'))):
            raise ValueError('calibration_history_invalid')
        date.fromisoformat(value['date']); instant(value['receivedAt'])
        rows.append({'id': row['id'], 'body': raw})
    return rows


def drift(history):
    """The estimated EPS against the official EPS at each input, latest last."""
    points = sorted((json.loads(r['body']) for r in history), key=lambda v: (v['date'], v['receivedAt']))
    gaps = [{'date': v['date'], 'gapPct': round((1 / v['ratio'] - 1) * 100, 2)} for v in points][-HISTORY_LIMIT:]
    if not gaps:
        return {'inputs': 0, 'latestPct': None, 'previousPct': None, 'warning': False, 'reason': None, 'recent': []}
    latest = gaps[-1]['gapPct']; previous = gaps[-2]['gapPct'] if len(gaps) > 1 else None
    reason = ('LARGE_GAP' if abs(latest) >= DRIFT_WARN_PCT else
              'LARGE_MOVE' if previous is not None and abs(latest - previous) >= DRIFT_MOVE_PCT else None)
    return {'inputs': len(gaps), 'latestPct': latest, 'previousPct': previous, 'latestDate': gaps[-1]['date'],
            'warning': reason is not None, 'reason': reason, 'recent': gaps[-8:]}


def validate(v):
    if not isinstance(v, dict) or set(v) != {'schemaVersion', 'revision', 'reference', 'updatedAt', 'disabled'}:
        raise ValueError('invalid_calibration')
    if v['schemaVersion'] != SCHEMA or type(v['revision']) is not int or v['revision'] < 0 or type(v['disabled']) is not bool:
        raise ValueError('invalid_calibration')
    if v['updatedAt'] is not None:
        instant(v['updatedAt'])
    r = v['reference']
    if r is not None:
        if (not isinstance(r, dict) or set(r) != {'date', 'per', 'indexClose', 'estimateEps', 'ratio', 'receivedAt'}
                or not all(number(r[k]) for k in ('per', 'indexClose', 'estimateEps', 'ratio'))
                or not math.isclose(r['ratio'], r['indexClose'] / r['per'] / r['estimateEps'], rel_tol=1e-12)):
            raise ValueError('invalid_reference')
        day = date.fromisoformat(r['date'])
        if day.isoformat() != r['date'] or not clock.is_trading_day(clock.JP_EQUITY, day) or r['receivedAt'] != v['updatedAt']:
            raise ValueError('invalid_reference_date')
        instant(r['receivedAt'])
    if v['disabled'] and r is not None:
        raise ValueError('disabled_reference_retained')
    return v


def read(conn):
    row = conn.execute('SELECT body FROM owner_weighted_per WHERE id=1').fetchone()
    return validate(json.loads(row['body'])) if row else {'schemaVersion': SCHEMA, 'revision': 0, 'reference': None, 'updatedAt': None, 'disabled': False}


def write(conn, state):
    validate(state)
    conn.execute('INSERT INTO owner_weighted_per VALUES(1,?) ON CONFLICT(id) DO UPDATE SET body=excluded.body',
                 (json.dumps(state, sort_keys=True, separators=(',', ':'), allow_nan=False),))


def latest_session(now):
    day = now.astimezone(JST).date()
    if now.astimezone(JST).hour < 16:
        day -= timedelta(days=1)
    for _ in range(15):
        if clock.is_trading_day(clock.JP_EQUITY, day):
            return day
        day -= timedelta(days=1)
    raise ValueError('calendar_unavailable')


def weekly_due(now):
    local = now.astimezone(JST)
    friday = local.date() + timedelta(days=4-local.weekday())
    while not clock.is_trading_day(clock.JP_EQUITY, friday):
        friday -= timedelta(days=1)
    if local < datetime.combine(friday, datetime.min.time(), JST) + timedelta(hours=16, minutes=30):
        friday -= timedelta(days=7)
        while not clock.is_trading_day(clock.JP_EQUITY, friday):
            friday -= timedelta(days=1)
    return friday.isoformat()


def status(state, now, history=None):
    ref = state['reference']
    age = 0
    if ref:
        day = date.fromisoformat(ref['date'])
        end = now.astimezone(JST).date()
        while day < end:
            day += timedelta(days=1)
            age += int(clock.is_trading_day(clock.JP_EQUITY, day))
    return {'revision': state['revision'], 'enabled': bool(ref), 'referenceDate': ref['date'] if ref else None,
            'appliedFromDate': max(ref['date'], instant(ref['receivedAt']).astimezone(JST).date().isoformat()) if ref else None,
            'receivedAt': ref['receivedAt'] if ref else None, 'stale': age > 10, 'ageSessions': age,
            'inputDue': not state['disabled'] and (not ref or ref['date'] < weekly_due(now)),
            'defaultDate': latest_session(now).isoformat(), 'dueDate': weekly_due(now),
            'automaticAcquisition': False, 'actionAuthority': False,
            **({'drift': drift(history)} if history is not None else {})}


def apply(records, state, cutoff):
    """Owner-only current display: no earlier dates, history or issued scores."""
    ref = state['reference']
    if not ref or instant(ref['receivedAt']) > instant(cutoff):
        return records
    out = {}
    starts = max(ref['date'], instant(ref['receivedAt']).astimezone(JST).date().isoformat())
    for day, row in records.items():
        if day < starts or not number(row.get('eps')):
            out[day] = row
        else:
            out[day] = {**row, 'eps': row['eps'] * ref['ratio'],
                        'per': row['per'] / ref['ratio'], 'uncalibratedEps': row['eps'],
                        'uncalibratedPer': row['per'], 'manualCalibration': True,
                        'calibrationReferenceDate': ref['date']}
    return out


def record_estimates(auth, records, cutoff):
    """Natural existing warm only: keep raw and calibrated numbers together."""
    with auth.db() as conn:
        state = read(conn)
        if not state['reference']:
            return
        remember_reference(conn, state['reference'])   # inputs saved before the history existed
        projected = apply(records, state, cutoff)
        for day, row in projected.items():
            if not row.get('manualCalibration') or day > instant(cutoff).astimezone(JST).date().isoformat():
                continue
            value = {'date': day, 'referenceRevision': state['revision'], 'originalEps': row['uncalibratedEps'],
                     'calibratedEps': row['eps'], 'originalPer': row['uncalibratedPer'], 'calibratedPer': row['per']}
            raw = json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)
            conn.execute('INSERT OR IGNORE INTO owner_weighted_per_estimates VALUES(?,?)', (hashlib.sha256(raw.encode()).hexdigest(), raw))


def projection_records(conn):
    rows = []
    for row in conn.execute('SELECT id,body FROM owner_weighted_per_estimates ORDER BY id'):
        raw = row['body']; value = json.loads(raw)
        if (hashlib.sha256(raw.encode()).hexdigest() != row['id'] or set(value) != {'date', 'referenceRevision', 'originalEps', 'calibratedEps', 'originalPer', 'calibratedPer'}
                or type(value['referenceRevision']) is not int or value['referenceRevision'] < 1
                or not all(number(value[k]) for k in ('originalEps', 'calibratedEps', 'originalPer', 'calibratedPer'))
                or not math.isclose(value['originalEps'] * value['originalPer'], value['calibratedEps'] * value['calibratedPer'], rel_tol=1e-12)):
            raise ValueError('calibration_projection_invalid')
        date.fromisoformat(value['date'])
        rows.append({'id': row['id'], 'body': raw})
    return rows


def action(auth):
    if not auth.enabled:
        return jsonify(error='owner_auth_disabled'), 503
    try:
        if not auth.session():
            return jsonify(error='owner_auth_required'), 401
        now = datetime.now(timezone.utc)
        if request.method == 'GET':
            with auth.reader() as conn:
                return jsonify(status(read(conn), now, history_records(conn)))
        if request.method != 'POST':
            return jsonify(error='not_found'), 404
        if request.headers.get('Origin') != auth.origin:
            return jsonify(error='origin_rejected'), 403
        if request.content_length is None or request.content_length > 2048 or not request.is_json:
            return jsonify(error='invalid_request'), 400
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or type(body.get('revision')) is not int:
            return jsonify(error='invalid_request'), 400
        with auth.db() as conn:
            state = read(conn)
            if body['revision'] != state['revision']:
                return jsonify(error='revision_conflict'), 409
            if body.get('operation') == 'clear' and set(body) == {'revision', 'operation'}:
                ref, disabled = None, True
            elif body.get('operation') == 'save' and set(body) == {'revision', 'operation', 'date', 'per', 'confirmed'}:
                day = date.fromisoformat(body['date'])
                if day.isoformat() != body['date'] or day > latest_session(now) or not clock.is_trading_day(clock.JP_EQUITY, day) or not number(body['per']):
                    raise ValueError('invalid_input')
                context = current_app.extensions['argus_weighted_per_reference'](body['date'])
                if not context or not all(number(context.get(k)) for k in ('indexClose', 'estimateEps')):
                    return jsonify(error='same_day_estimate_unavailable'), 409
                estimate_per = context['indexClose'] / context['estimateEps']
                if abs(body['per'] / estimate_per - 1) >= .15 and body['confirmed'] is not True:
                    return jsonify(error='confirmation_required'), 409
                ref = {'date': body['date'], 'per': body['per'], **context,
                       'ratio': context['indexClose'] / body['per'] / context['estimateEps'], 'receivedAt': now.isoformat()}
                disabled = False
            else:
                raise ValueError('invalid_request')
            updated = {'schemaVersion': SCHEMA, 'revision': state['revision'] + 1,
                       'reference': ref, 'updatedAt': now.isoformat(), 'disabled': disabled}
            write(conn, updated)
            remember_reference(conn, ref)
            history = history_records(conn)
        return jsonify(status(updated, now, history))
    except (ValueError, TypeError, KeyError, OverflowError):
        return jsonify(error='invalid_calibration_request'), 400
    except Exception:
        return jsonify(error='calibration_storage_unavailable'), 503


def synchronize(auth, remote):
    """One mutable state in the SAME private connection, bounded and CAS checked.

    Revision tombstones prevent an older remote value re-enabling a clear.
    Historic private repository versions remain recovery history.
    """
    remote.require_private()
    with auth.reader() as conn:
        local = read(conn)
        records = projection_records(conn)
        history = history_records(conn)
    raw, version = remote.get(REMOTE_PATH)
    if raw is not None and len(raw) > 512 * 1024:
        raise ValueError('calibration_backup_bound')
    saved_document = json.loads(raw) if raw is not None else None
    # v1 can lack the optional natural projection journal.
    saved_records = saved_document.get('projectionRecords', []) if saved_document else []
    saved = validate({k:v for k,v in saved_document.items() if k not in ('projectionRecords', 'referenceHistory')}) if saved_document else None
    saved_history = saved_document.get('referenceHistory', []) if saved_document else []
    if not isinstance(saved_history, list) or len(saved_history) > HISTORY_LIMIT * 2:
        raise ValueError('calibration_history_bound')
    if not isinstance(saved_records, list) or len(saved_records) > 10000:
        raise ValueError('calibration_projection_bound')
    # Validate every remote journal row before any live state is changed.
    import sqlite3
    staging = sqlite3.connect(':memory:'); staging.row_factory = sqlite3.Row
    try:
        staging.execute('CREATE TABLE owner_weighted_per_estimates (id TEXT PRIMARY KEY, body TEXT NOT NULL)')
        staging.execute('CREATE TABLE owner_weighted_per_history (id TEXT PRIMARY KEY, body TEXT NOT NULL)')
        for row in saved_history:
            if not isinstance(row, dict) or set(row) != {'id', 'body'} or not isinstance(row['body'], str) or len(row['body']) > 1024:
                raise ValueError('calibration_history_invalid')
            staging.execute('INSERT INTO owner_weighted_per_history VALUES(?,?)', (row['id'], row['body']))
        history_records(staging)
        for row in saved_records:
            if not isinstance(row, dict) or set(row) != {'id', 'body'} or not isinstance(row['body'], str) or len(row['body']) > 2048:
                raise ValueError('calibration_projection_invalid')
            staging.execute('INSERT INTO owner_weighted_per_estimates VALUES(?,?)', (row['id'], row['body']))
        projection_records(staging)
    finally:
        staging.close()
    if saved_history:
        with auth.db() as conn:
            for row in saved_history:
                conn.execute('INSERT OR IGNORE INTO owner_weighted_per_history VALUES(?,?)', (row['id'], row['body']))
        with auth.reader() as conn:
            history = history_records(conn)
    if saved_records:
        with auth.db() as conn:
            for row in saved_records:
                conn.execute('INSERT OR IGNORE INTO owner_weighted_per_estimates VALUES(?,?)', (row['id'], row['body']))
        with auth.reader() as conn:
            records = projection_records(conn)
    if saved and saved['revision'] > local['revision']:
        with auth.db() as conn:
            current = read(conn)
            if current != local:
                raise ValueError('calibration_changed_during_restore')
            write(conn, saved)
        return {'status': 'RESTORED', 'revision': saved['revision']}
    if saved and saved['revision'] == local['revision'] and saved != local:
        raise ValueError('calibration_revision_conflict')
    if local['revision'] and (local != saved or records != saved_records or history != saved_history):
        encoded = json.dumps({**local, 'projectionRecords': records, 'referenceHistory': history},
                             sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
        if len(encoded) > 512 * 1024:
            raise ValueError('calibration_backup_bound')
        remote.put(REMOTE_PATH, encoded, expected_version=version)
        if remote.get(REMOTE_PATH)[0] != encoded:
            raise ValueError('calibration_backup_readback_mismatch')
    return {'status': 'VERIFIED', 'revision': local['revision']}
