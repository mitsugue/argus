"""Owner-entered Nikkei 225 price adjustment factors (2026-10-17).

The contributions use factors recovered from the owner's month-end weight
table. A member that joined after that table, or whose factor changed since
(a split, a review), is entered here by hand from Nikkei's published list.
The entry form appears only while such a member exists or the latest day does
not add up; it disappears once the numbers reconcile. No automatic download.
Stored in the existing owner database, never in a public place.
"""
from datetime import date, datetime, timezone
import json
import math
import re
from flask import current_app, jsonify, request
import argus_market_clock as clock

SCHEMA = 'owner-index-factors-v1'
SOURCE_URL = 'https://indexes.nikkei.co.jp/nkave/index/profile?idx=nk225'
MAX_ENTRIES = 60
_CODE = re.compile(r'^[0-9][0-9A-Z]{3}$')


def prepare(auth):
    if auth.enabled:
        with auth.db() as conn:
            conn.execute('CREATE TABLE IF NOT EXISTS owner_index_factors (id INTEGER PRIMARY KEY CHECK(id=1), body TEXT NOT NULL)')


def factor_value(v):
    """Published factors are positive and on a 0.1 grid (e.g. 0.1, 1.0, 24.0)."""
    return (type(v) in (int, float) and math.isfinite(v) and 0 < v <= 1000
            and abs(round(v * 10) - v * 10) < 1e-9)


def _entry(row):
    if (not isinstance(row, dict) or set(row) != {'code', 'factor', 'effectiveFrom', 'receivedAt'}
            or not isinstance(row['code'], str) or not _CODE.match(row['code']) or not factor_value(row['factor'])):
        raise ValueError('invalid_entry')
    day = date.fromisoformat(row['effectiveFrom'])
    if day.isoformat() != row['effectiveFrom']:
        raise ValueError('invalid_entry_date')
    datetime.fromisoformat(row['receivedAt'].replace('Z', '+00:00'))
    return row


def validate(v):
    if (not isinstance(v, dict) or set(v) != {'schemaVersion', 'revision', 'entries', 'updatedAt'}
            or v['schemaVersion'] != SCHEMA or type(v['revision']) is not int or v['revision'] < 0
            or not isinstance(v['entries'], list) or len(v['entries']) > MAX_ENTRIES):
        raise ValueError('invalid_factor_state')
    keys = [(_entry(row)['code'], row['effectiveFrom']) for row in v['entries']]
    if len(keys) != len(set(keys)):
        raise ValueError('duplicate_factor_entry')
    return v


def read(conn):
    row = conn.execute('SELECT body FROM owner_index_factors WHERE id=1').fetchone()
    return validate(json.loads(row['body'])) if row else {'schemaVersion': SCHEMA, 'revision': 0, 'entries': [], 'updatedAt': None}


def write(conn, state):
    validate(state)
    conn.execute('INSERT INTO owner_index_factors VALUES(1,?) ON CONFLICT(id) DO UPDATE SET body=excluded.body',
                 (json.dumps(state, sort_keys=True, separators=(',', ':'), allow_nan=False),))


def overrides(conn):
    """The entries the calculation reads: code, factor and the day it applies from."""
    return [{k: row[k] for k in ('code', 'factor', 'effectiveFrom')} for row in read(conn)['entries']]


def status(state, need):
    need = need or {}
    names = need.get('names') or {}
    since = need.get('since') or {}
    missing = [{'code': c, 'nameJa': names.get(c), 'since': since.get(c)} for c in need.get('missingFactorCodes') or []]
    return {'revision': state['revision'], 'inputDue': bool(need.get('inputDue')),
            'missing': missing, 'mismatch': need.get('mismatch'), 'factorsAsOf': need.get('factorsAsOf'),
            'entries': [{k: row[k] for k in ('code', 'factor', 'effectiveFrom')} for row in state['entries']],
            'sourceUrl': SOURCE_URL, 'automaticAcquisition': False, 'actionAuthority': False}


def _need():
    provider = current_app.extensions.get('argus_index_factor_needs')
    try:
        return provider() if provider else {}
    except Exception:
        return {}


def action(auth):
    if not auth.enabled:
        return jsonify(error='owner_auth_disabled'), 503
    try:
        if not auth.session():
            return jsonify(error='owner_auth_required'), 401
        now = datetime.now(timezone.utc)
        if request.method == 'GET':
            with auth.reader() as conn:
                state = read(conn)
            return jsonify(status(state, _need()))
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
            entries = [dict(row) for row in state['entries']]
            if body.get('operation') == 'save' and set(body) == {'revision', 'operation', 'code', 'factor', 'effectiveFrom'}:
                code = str(body['code']).strip().upper()
                day = date.fromisoformat(body['effectiveFrom'])
                if (not _CODE.match(code) or not factor_value(body['factor']) or day.isoformat() != body['effectiveFrom']
                        or day > now.date() or not clock.is_trading_day(clock.JP_EQUITY, day)):
                    raise ValueError('invalid_input')
                entries = [row for row in entries if (row['code'], row['effectiveFrom']) != (code, body['effectiveFrom'])]
                entries.append({'code': code, 'factor': float(body['factor']), 'effectiveFrom': body['effectiveFrom'],
                                'receivedAt': now.isoformat()})
                entries = sorted(entries, key=lambda r: (r['effectiveFrom'], r['code']))[-MAX_ENTRIES:]
            elif body.get('operation') == 'remove' and set(body) == {'revision', 'operation', 'code', 'effectiveFrom'}:
                entries = [row for row in entries if (row['code'], row['effectiveFrom']) != (body['code'], body['effectiveFrom'])]
            else:
                raise ValueError('invalid_request')
            updated = {'schemaVersion': SCHEMA, 'revision': state['revision'] + 1, 'entries': entries,
                       'updatedAt': now.isoformat()}
            write(conn, updated)
        refresh = current_app.extensions.get('argus_index_factor_changed')
        if refresh:
            try:
                refresh()
            except Exception:
                pass
        return jsonify(status(updated, _need()))
    except (ValueError, TypeError, KeyError, OverflowError):
        return jsonify(error='invalid_factor_request'), 400
    except Exception:
        return jsonify(error='factor_storage_unavailable'), 503
