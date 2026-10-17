"""Owner-entered price adjustment factors for the Nikkei 225 contributions (2026-10-17)."""
import pytest
from flask import Flask
from werkzeug.security import generate_password_hash
import argus_owner_auth
import argus_index_factor_input as fi

ORIGIN = 'https://owner.example'
ROUTE = '/api/argus/owner-auth/index-factors'


@pytest.fixture
def setup(tmp_path):
    app = Flask(__name__)
    auth = argus_owner_auth.install(app, {'ARGUS_OWNER_AUTH_REQUIRED': '1',
        'ARGUS_OWNER_AUTH_DB': str(tmp_path/'owner.sqlite3'), 'ARGUS_OWNER_AUTH_ORIGIN': ORIGIN,
        'ARGUS_OWNER_PASSWORD_HASH': generate_password_hash('synthetic-password', method='pbkdf2:sha256:1000')})
    need = {'value': {'missingFactorCodes': ['1003'], 'mismatch': None, 'inputDue': True,
                      'names': {'1003': '合成丙'}, 'since': {'1003': '2026-10-01'}, 'factorsAsOf': '2026-09-30'}}
    changed = []
    app.extensions['argus_index_factor_needs'] = lambda: need['value']
    app.extensions['argus_index_factor_changed'] = lambda: changed.append(1)
    client = app.test_client()
    token = client.post('/api/argus/owner-auth/password', json={'password': 'synthetic-password'}, headers={'Origin': ORIGIN}).json['token']
    return auth, client, {'Origin': ORIGIN, 'X-ARGUS-OWNER-SESSION': token}, need, changed


def test_the_form_states_what_is_missing_and_saves_privately(setup):
    auth, client, headers, need, changed = setup
    assert client.get(ROUTE).status_code == 401
    status = client.get(ROUTE, headers=headers).json
    assert status['inputDue'] is True and status['missing'] == [{'code': '1003', 'nameJa': '合成丙', 'since': '2026-10-01'}]
    assert status['sourceUrl'] == 'https://indexes.nikkei.co.jp/nkave/index/profile?idx=nk225'
    assert status['automaticAcquisition'] is False
    saved = client.post(ROUTE, json={'revision': 0, 'operation': 'save', 'code': '1003', 'factor': 2.0,
                                     'effectiveFrom': '2026-10-01'}, headers=headers)
    assert saved.status_code == 200 and saved.json['revision'] == 1 and changed == [1]
    assert saved.json['entries'] == [{'code': '1003', 'factor': 2.0, 'effectiveFrom': '2026-10-01'}]
    with auth.reader() as conn:
        assert fi.overrides(conn) == [{'code': '1003', 'factor': 2.0, 'effectiveFrom': '2026-10-01'}]
    need['value'] = {'missingFactorCodes': [], 'mismatch': None, 'inputDue': False}
    assert client.get(ROUTE, headers=headers).json['inputDue'] is False      # the form disappears


def test_invalid_entries_and_stale_revisions_are_refused(setup):
    auth, client, headers, need, changed = setup
    def post(**body):
        return client.post(ROUTE, json={'revision': 0, 'operation': 'save', 'code': '1003', 'factor': 2.0,
                                        'effectiveFrom': '2026-10-01', **body}, headers=headers)
    assert post(factor=0.25).status_code == 400                # not on the 0.1 grid
    assert post(factor=-1).status_code == 400
    assert post(code='12').status_code == 400
    assert post(effectiveFrom='2026-10-04').status_code == 400  # a Sunday
    assert post(effectiveFrom='2999-01-04').status_code == 400  # the future
    assert post(revision=5).status_code == 409
    assert client.post(ROUTE, json={'revision': 0, 'operation': 'save', 'code': '1003', 'factor': 2.0,
                                    'effectiveFrom': '2026-10-01'}, headers={'X-ARGUS-OWNER-SESSION': headers['X-ARGUS-OWNER-SESSION']}).status_code == 403
    assert post().status_code == 200
    removed = client.post(ROUTE, json={'revision': 1, 'operation': 'remove', 'code': '1003', 'effectiveFrom': '2026-10-01'},
                          headers=headers)
    assert removed.status_code == 200 and removed.json['entries'] == []
