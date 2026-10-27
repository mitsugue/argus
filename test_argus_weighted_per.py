"""Synthetic manual references only; no official market values or network."""
from copy import deepcopy
from datetime import datetime, timezone
import json
from types import SimpleNamespace
import pytest
from flask import Flask
from werkzeug.security import generate_password_hash
import argus_owner_auth
import argus_weighted_per as per

ORIGIN = 'https://owner.example'


@pytest.fixture
def setup(tmp_path):
    app = Flask(__name__)
    auth = argus_owner_auth.install(app, {'ARGUS_OWNER_AUTH_REQUIRED': '1',
        'ARGUS_OWNER_AUTH_DB': str(tmp_path/'owner.sqlite3'), 'ARGUS_OWNER_AUTH_ORIGIN': ORIGIN,
        'ARGUS_OWNER_PASSWORD_HASH': generate_password_hash('synthetic-password', method='pbkdf2:sha256:1000')})
    app.extensions['argus_weighted_per_reference'] = lambda day: {'indexClose': 60000, 'estimateEps': 3000}
    client = app.test_client()
    token = client.post('/api/argus/owner-auth/password', json={'password': 'synthetic-password'}, headers={'Origin': ORIGIN}).json['token']
    return app, auth, client, {'Origin': ORIGIN, 'X-ARGUS-OWNER-SESSION': token}


def save(client, headers, **changes):
    body = {'revision': 0, 'operation': 'save', 'date': '2026-10-13', 'per': 20, 'confirmed': False} | changes
    return client.post('/api/argus/owner-auth/weighted-per', json=body, headers=headers)


def test_private_save_read_clear_and_no_raw_reference_in_responses(setup):
    app, auth, client, headers = setup
    assert client.get('/api/argus/owner-auth/weighted-per').status_code == 401
    assert save(client, headers).status_code == 200
    response = client.get('/api/argus/owner-auth/weighted-per', headers=headers)
    assert response.json['enabled'] and response.json['referenceDate'] == '2026-10-13'
    assert response.headers['Cache-Control'] == 'private, no-store'
    assert not {'per', 'ratio', 'estimateEps', 'indexClose'} & response.json.keys()
    with auth.reader() as conn:
        state = per.read(conn)
    assert state['reference']['ratio'] == 1
    assert save(client, headers).status_code == 409
    cleared = client.post('/api/argus/owner-auth/weighted-per', json={'revision': 1, 'operation': 'clear'}, headers=headers)
    assert cleared.status_code == 200 and not cleared.json['enabled']
    with auth.reader() as conn:
        assert per.read(conn)['reference'] is None


@pytest.mark.parametrize('changes', [{'per': 0}, {'per': -1}, {'per': True}, {'per': '20'}, {'date': '2026-10-17'}, {'date': '2099-01-01'}, {'date': '2026-10-12'}, {'date': 'bad'}])
def test_invalid_or_non_session_inputs_do_not_write(setup, changes):
    _, auth, client, headers = setup
    assert save(client, headers, **changes).status_code == 400
    with auth.reader() as conn:
        assert per.read(conn)['revision'] == 0


def test_origin_session_size_and_same_day_input_are_required(setup):
    app, auth, client, headers = setup
    assert save(client, headers | {'Origin': 'https://other.example'}).status_code == 403
    assert save(client, {'Origin': ORIGIN}).status_code == 401
    app.extensions['argus_weighted_per_reference'] = lambda day: None
    assert save(client, headers).json['error'] == 'same_day_estimate_unavailable'
    assert client.post('/api/argus/owner-auth/weighted-per', data='x'*2049, headers=headers | {'Content-Type': 'application/json'}).status_code == 400


def test_large_difference_requires_explicit_confirmation(setup):
    _, auth, client, headers = setup
    assert save(client, headers, per=30).json['error'] == 'confirmation_required'
    with auth.reader() as conn:
        assert per.read(conn)['revision'] == 0
    assert save(client, headers, per=30, confirmed=True).status_code == 200


def reference():
    return {'schemaVersion': per.SCHEMA, 'revision': 1, 'updatedAt': '2026-10-15T01:00:00Z', 'disabled': False,
        'reference': {'date': '2026-10-13', 'per': 25, 'indexClose': 60000, 'estimateEps': 3000, 'ratio': .8, 'receivedAt': '2026-10-15T01:00:00Z'}}


def test_future_receipt_never_enters_past_and_originals_are_unchanged():
    records = {day: {'eps': 3000, 'per': 20} for day in ['2026-10-13', '2026-10-14', '2026-10-15', '2026-10-16']}
    before = deepcopy(records)
    assert per.apply(records, reference(), '2026-10-15T00:59:59Z') == records
    result = per.apply(records, reference(), '2026-10-15T01:00:00Z')
    assert result['2026-10-13'] == records['2026-10-13'] and result['2026-10-14'] == records['2026-10-14']
    assert result['2026-10-15']['eps'] == 2400 and result['2026-10-15']['per'] == 25
    assert result['2026-10-15']['uncalibratedEps'] == 3000 and records == before


@pytest.mark.parametrize('stamp, expected', [('2026-10-16T07:29:59Z', '2026-10-09'), ('2026-10-16T07:30:00Z', '2026-10-16'), ('2026-10-18T01:00:00Z', '2026-10-16')])
def test_weekly_prompt_boundary(stamp, expected):
    assert per.weekly_due(per.instant(stamp)) == expected


def test_stale_warning_counts_official_sessions():
    assert per.status(reference(), per.instant('2026-11-02T01:00:00Z'))['stale']


class Remote:
    def __init__(self): self.raw = None; self.private = True; self.writes = 0
    def require_private(self):
        if not self.private: raise ValueError('private_required')
    def get(self, path):
        assert path == per.REMOTE_PATH
        return self.raw, self.writes if self.raw else None
    def put(self, path, raw, *, expected_version):
        assert path == per.REMOTE_PATH and expected_version == (self.writes if self.raw else None)
        self.raw = raw; self.writes += 1


def test_same_private_connection_restore_and_clear_tombstone(setup, tmp_path):
    _, auth, _, _ = setup
    with auth.db() as conn: per.write(conn, reference())
    remote = Remote()
    assert per.synchronize(auth, remote)['status'] == 'VERIFIED'
    assert remote.writes == 1
    with auth.db() as conn: conn.execute('DELETE FROM owner_weighted_per')
    assert per.synchronize(auth, remote)['status'] == 'RESTORED'
    with auth.db() as conn:
        state = per.read(conn)
        assert state == reference()
        cleared = state | {'revision': 2, 'reference': None, 'disabled': True, 'updatedAt': '2026-10-15T02:00:00Z'}
        per.write(conn, cleared)
    per.synchronize(auth, remote)
    assert json.loads(remote.raw)['reference'] is None
    assert per.synchronize(auth, remote)['status'] == 'VERIFIED'
    remote.private = False
    with pytest.raises(ValueError): per.synchronize(auth, remote)


def test_existing_owner_backup_preserves_calibration_without_sessions(setup, tmp_path):
    from scripts.owner_auth_backup import copy_database
    _, auth, _, _ = setup
    with auth.db() as conn: per.write(conn, reference())
    target = tmp_path/'restored.sqlite3'
    copy_database(auth.path, target, restore=True)
    restored = SimpleNamespace(path=str(target))
    import sqlite3
    conn = sqlite3.connect(restored.path); conn.row_factory = sqlite3.Row
    try:
        assert per.read(conn) == reference()
        assert conn.execute('SELECT count(*) FROM owner_sessions').fetchone()[0] == 0
    finally: conn.close()


def test_natural_projection_journal_keeps_both_values_and_restores(setup):
    _, auth, _, _ = setup
    with auth.db() as conn: per.write(conn, reference())
    rows = {'2026-10-15': {'eps': 3000, 'per': 20}, '2026-10-14': {'eps': 2900, 'per': 21}}
    per.record_estimates(auth, rows, '2026-10-15T02:00:00Z')
    per.record_estimates(auth, rows, '2026-10-15T02:01:00Z')
    with auth.reader() as conn:
        journal = per.projection_records(conn)
    assert len(journal) == 1
    value = json.loads(journal[0]['body'])
    assert value['originalEps'] == 3000 and value['calibratedEps'] == 2400
    remote = Remote(); per.synchronize(auth, remote)
    with auth.db() as conn: conn.execute('DELETE FROM owner_weighted_per_estimates')
    per.synchronize(auth, remote)
    with auth.reader() as conn: assert per.projection_records(conn) == journal


@pytest.mark.parametrize('bad', ['unknown_coverage', 'missing_earnings', 'wrong_basis', 'future_receipt', None])
def test_real_reference_boundary_requires_same_day_complete_known_estimate(bad):
    import ast
    from pathlib import Path
    import jp_market_level_map as levels
    import jp_market_engine as engine
    node = next(n for n in ast.parse(Path(__file__).with_name('scanner.py').read_text()).body
                if isinstance(n, ast.FunctionDef) and n.name == '_weighted_per_reference')
    row = {'date': '2026-10-13', 'eps': 3000, 'basis': levels.EPS_BASIS, 'recordedAt': '2026-10-13T08:00:00Z',
           'coverage': {'members': 225, 'missingMarketCap': 0, 'missingEarnings': 0, 'marketCapShareUsed': 1.0}}
    if bad == 'unknown_coverage': row.pop('coverage')
    elif bad == 'missing_earnings': row['coverage']['missingEarnings'] = 1
    elif bad == 'wrong_basis': row['basis'] = 'OTHER'
    elif bad == 'future_receipt': row['recordedAt'] = '2026-10-16T08:00:00Z'
    namespace = {'_level_map_admitted_eps': lambda: {'2026-10-13': row},
        '_nikkei_chart_rows': lambda: [], '_level_map_completed_bars': lambda rows, now: [{'date': '2026-10-13', 'close': 60000}],
        '_ai_now_iso': lambda: '2026-10-15T01:00:00Z', 'jp_market_level_map': levels, 'jp_market_engine': engine}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])), 'real-per-reference', 'exec'), namespace)
    result = namespace['_weighted_per_reference']('2026-10-13')
    assert result == ({'indexClose': 60000, 'estimateEps': 3000} if bad is None else None)


def test_official_inputs_are_kept_and_the_gap_is_watched(setup):
    # 2026-10-27 (owner): watch the estimate against the official value.
    _, auth, client, headers = setup
    first = save(client, headers)                                  # estimate PER 20 = official 20
    assert first.json['drift'] == {**first.json['drift'], 'inputs': 1, 'latestPct': 0.0, 'previousPct': None, 'warning': False}
    second = save(client, headers, revision=1, date='2026-10-14', per=21)   # official higher → estimated EPS +5%
    drift = second.json['drift']
    assert drift['inputs'] == 2 and drift['latestPct'] == 5.0 and drift['previousPct'] == 0.0
    assert drift['warning'] and drift['reason'] == 'LARGE_GAP'
    assert not {'per', 'ratio', 'estimateEps', 'indexClose'} & second.json.keys()
    assert client.get('/api/argus/owner-auth/weighted-per', headers=headers).json['drift']['latestPct'] == 5.0
    calm = per.drift([{'body': json.dumps({'date': d, 'ratio': r, 'receivedAt': d + 'T08:00:00+00:00'})}
                      for d, r in (('2026-10-13', 1 / 1.01), ('2026-10-20', 1 / 1.045))])
    assert calm['reason'] == 'LARGE_MOVE' and not per.drift([])['warning']
    # The history travels with the private backup and comes back after a loss.
    remote = Remote()
    per.synchronize(auth, remote)
    assert len(json.loads(remote.raw)['referenceHistory']) == 2
    with auth.db() as conn: conn.execute('DELETE FROM owner_weighted_per_history')
    per.synchronize(auth, remote)
    with auth.reader() as conn:
        assert len(per.history_records(conn)) == 2
