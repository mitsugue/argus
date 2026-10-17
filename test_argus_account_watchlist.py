"""Synthetic two-device registration and recovery checks; no owner records."""
import uuid

import pytest
from flask import Flask
from werkzeug.security import generate_password_hash

from argus_owner_auth import install
from scripts.owner_auth_backup import copy_database

URL = '/api/argus/owner-auth/watchlist'
ORIGIN = 'https://owner.example'


def asset(identity='jp-1234', **extra):
    return dict(id=identity, symbol=identity.split('-')[-1], displayName='検査用銘柄',
                market='JP', assetType='jp_equity', source='jquants', enabled=True,
                sortOrder=0, createdAt=1, updatedAt=2, **extra)


@pytest.fixture
def account(tmp_path):
    app = Flask(__name__)
    env = dict(ARGUS_OWNER_AUTH_REQUIRED='1', ARGUS_OWNER_AUTH_DB=str(tmp_path / 'auth.db'),
               ARGUS_OWNER_AUTH_ORIGIN=ORIGIN,
               ARGUS_OWNER_PASSWORD_HASH=generate_password_hash('synthetic', method='pbkdf2:sha256:1000'),
               ARGUS_ADMIN_TOKEN='operator')
    auth = install(app, env)
    client = app.test_client()
    def login():
        token = client.post('/api/argus/owner-auth/password', json={'password': 'synthetic'},
                            headers={'Origin': ORIGIN}).json['token']
        return {'Origin': ORIGIN, 'X-ARGUS-OWNER-SESSION': token}
    return client, auth, login(), login(), env


def write(client, headers, revision, operations, batch=None):
    return client.post(URL, headers=headers, json=dict(revision=revision,
                       operations=operations, batchId=batch or str(uuid.uuid4())))


def test_shared_state_order_private_fields_and_restart(account):
    client, auth, first, second, env = account
    assert client.get(URL, headers=first).json['initialized'] is False
    one, two = asset(memo='合成のメモ', quantity=8, avgCost=100, futurePrivateExtension={'cash': 900}), asset('jp-5678')
    assert write(client, first, 0, [{'kind': 'import', 'asset': one}, {'kind': 'add', 'asset': two}]).status_code == 200
    saved = client.get(URL, headers=second).json
    assert saved['assets'] == [one, two]
    response = write(client, second, 1, [{'kind': 'update', 'id': two['id'], 'set': {'sortOrder': -1}, 'unset': []}])
    assert response.json['assets'][0]['id'] == two['id']
    restarted = Flask(__name__)
    install(restarted, env)
    assert restarted.test_client().get(URL, headers=first).json == client.get(URL, headers=second).json
    with auth.reader() as conn:
        assert conn.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'


def test_concurrent_fields_preserved_with_explicit_revision(account):
    client, auth, a, b, env = account
    write(client, a, 0, [{'kind': 'add', 'asset': asset()}])
    assert write(client, a, 1, [{'kind': 'update', 'id': 'jp-1234', 'set': {'memo': '端末1'}, 'unset': []}]).status_code == 200
    ops = [{'kind': 'update', 'id': 'jp-1234', 'set': {'sortOrder': -4}, 'unset': []}]
    assert write(client, b, 1, ops).status_code == 409
    revision = client.get(URL, headers=b).json['revision']
    result = write(client, b, revision, ops).json['assets'][0]
    assert result['memo'] == '端末1' and result['sortOrder'] == -4


def test_ack_loss_receipt_survives_later_changes(account):
    client, auth, a, b, env = account
    batch = str(uuid.uuid4())
    ops = [{'kind': 'add', 'asset': asset(memo='初回')}]
    write(client, a, 0, ops, batch)
    write(client, b, 1, [{'kind': 'update', 'id': 'jp-1234', 'set': {'memo': '次の編集'}, 'unset': []}])
    replay = write(client, a, 0, ops, batch)
    assert replay.status_code == 200
    assert replay.json['revision'] == 2 and replay.json['assets'][0]['memo'] == '次の編集'
    assert write(client, a, 2, [], batch).status_code == 409


def test_deletion_import_and_stale_update_never_resurrect(account):
    client, auth, a, b, env = account
    one = asset(memo='保存済み')
    write(client, a, 0, [{'kind': 'add', 'asset': one}])
    write(client, b, 1, [{'kind': 'remove', 'id': one['id']}])
    result = write(client, a, 2, [{'kind': 'import', 'asset': one},
        {'kind': 'update', 'id': one['id'], 'set': {'sortOrder': 9}, 'unset': []}]).json
    assert result['assets'] == [] and result['deleted'] == [one['id']]
    assert write(client, b, 3, [{'kind': 'add', 'asset': one}]).json['assets'] == [one]


def test_migration_preserves_current_and_archived_missing_fields(account):
    client, auth, a, b, env = account
    current = asset(memo='今のメモ')
    write(client, a, 0, [{'kind': 'add', 'asset': current}])
    result = write(client, b, 1, [{'kind': 'import', 'asset': asset(memo='古いメモ', quantity=7)}]).json['assets'][0]
    assert result['memo'] == '今のメモ' and result['quantity'] == 7


def test_session_required_even_with_admin_and_post_origin(account):
    client, auth, a, b, env = account
    assert client.get(URL).status_code == 401
    assert client.get(URL, headers={'X-ARGUS-ADMIN-TOKEN': 'operator'}).status_code == 401
    assert write(client, {**a, 'Origin': 'https://attacker.invalid'}, 0, []).status_code == 403
    response = client.get(URL, headers={**a, 'X-ARGUS-OWNER-NONCE': 'a' * 36})
    assert response.headers['X-ARGUS-OWNER-NONCE'] == 'a' * 36
    assert response.headers['Cache-Control'] == 'private, no-store'
    client.post('/api/argus/owner-auth/logout', headers=a, json={})
    assert client.get(URL, headers=a).status_code == 401


@pytest.mark.parametrize('operations', [None, [{'kind': 'order', 'symbol': '1234'}],
    [{'kind': 'add', 'asset': {**asset(), 'admin': True}}],
    [{'kind': 'update', 'id': 'jp-1234', 'set': {'symbol': '9999'}, 'unset': []}],
    [{'kind': 'remove', 'id': 3}], [{'kind': 'add', 'asset': {**asset(), 'quantity': -1}}]])
def test_reject_invalid_and_trading_operations(account, operations):
    client, auth, a, b, env = account
    assert write(client, a, 0, operations).status_code == 400
    assert client.get(URL, headers=a).json['revision'] == 0


def test_corruption_is_unavailable_not_empty(account):
    client, auth, a, b, env = account
    with auth.db() as conn:
        conn.execute("INSERT INTO owner_watchlist VALUES (1,1,'not-json')")
    assert client.get(URL, headers=a).status_code == 503


def test_backup_and_restore_preserve_registrations_without_reviving_auth(account, tmp_path):
    client, auth, a, b, env = account
    write(client, a, 0, [{'kind': 'add', 'asset': asset(memo='合成保存記録')}])
    target = tmp_path / 'restored.db'
    result = copy_database(auth.path, target, restore=True)
    assert result['sessionsInvalidated']
    restored = Flask(__name__)
    install(restored, {**env, 'ARGUS_OWNER_AUTH_DB': str(target)})
    restored_client = restored.test_client()
    assert restored_client.get(URL, headers=a).status_code == 401
    token = restored_client.post('/api/argus/owner-auth/password', headers={'Origin': ORIGIN}, json={'password': 'synthetic'}).json['token']
    assert restored_client.get(URL, headers={'X-ARGUS-OWNER-SESSION': token}).json['assets'][0]['memo'] == '合成保存記録'


def test_current_membership_projection_omits_archives_and_preserves_settings(account):
    from argus_account_watchlist import membership_snapshot
    client, auth, a, b, env = account
    legacy = {'members': [{'market': 'JP', 'symbol': '1234', 'ownerState': 'protected',
                          'downsideStrictness': 'strict', 'priority': 'high'},
                         {'market': 'JP', 'symbol': '9999'}]}
    assert membership_snapshot(auth, legacy) == legacy
    write(client, a, 0, [{'kind': 'add', 'asset': asset(quantity=4, avgCost=100, memo='私的な合成記録')},
                         {'kind': 'add', 'asset': {**asset('jp-5678'), 'enabled': False}}])
    projected = membership_snapshot(auth, legacy)
    assert [row['symbol'] for row in projected['members']] == ['1234']
    assert projected['members'][0]['ownerState'] == 'protected'
    assert projected['members'][0]['priority'] == 'high'
    for field in ('quantity', 'avgCost', 'memo'):
        assert field not in projected['members'][0]
    write(client, a, 1, [{'kind': 'remove', 'id': 'jp-1234'}])
    assert membership_snapshot(auth, legacy)['members'] == []


def test_scanner_universe_and_notifications_follow_shared_registration(account, monkeypatch):
    import scanner
    client, auth, a, b, env = account
    monkeypatch.setitem(scanner.app.extensions, 'argus_owner_auth', auth)
    monkeypatch.setattr(scanner, '_layer2b_store_configured', lambda: False)
    monkeypatch.setattr(scanner, '_OWNER_SYMS_CACHE', {'syms': None, 'ts': 0, 'status': 'unknown'})
    monkeypatch.setattr(scanner, '_OWNER_OVERVIEW_MEMBERSHIP', {'checkedAt': 0, 'members': None})
    write(client, a, 0, [{'kind': 'add', 'asset': asset()}])
    assert '1234' in scanner._owner_symbols_cached()
    assert [m['symbol'] for m in scanner._owner_overview_registered_subjects()] == ['1234']
    write(client, b, 1, [{'kind': 'remove', 'id': 'jp-1234'}, {'kind': 'add', 'asset': asset('jp-5678')}])
    assert set(scanner._owner_symbols_cached()) == {'5678'}, 'account revision bypasses old ten-minute cache'
    assert [m['symbol'] for m in scanner._layer2b_read_latest()['members']] == ['5678']
    assert [m['symbol'] for m in scanner._owner_overview_registered_subjects()] == ['5678']
