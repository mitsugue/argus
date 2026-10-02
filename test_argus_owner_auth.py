import base64
import hashlib
import json
import time

import cbor2
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import hashes
from flask import Flask
from werkzeug.security import generate_password_hash

import argus_owner_auth as module

ORIGIN = 'https://owner.example'
PASSWORD = 'local-test-only-password'


def b64(value):
    return base64.urlsafe_b64encode(value).decode().rstrip('=')


@pytest.fixture
def setup(tmp_path):
    app = Flask(__name__)
    env = {'ARGUS_OWNER_AUTH_REQUIRED': '1', 'ARGUS_OWNER_AUTH_DB': str(tmp_path / 'auth.db'),
           'ARGUS_OWNER_AUTH_ORIGIN': ORIGIN, 'ARGUS_OWNER_PASSWORD_HASH': generate_password_hash(PASSWORD, method='pbkdf2:sha256:1000'),
           'ARGUS_ADMIN_TOKEN': 'test-admin'}
    auth = module.install(app, env)
    app.add_url_rule('/api/argus/data', 'data', lambda: {'secret': 'fixture-private-value'})
    app.add_url_rule('/healthz', 'health', lambda: {'ok': True})
    app.add_url_rule('/', 'root', lambda: 'private-legacy-page')
    # An owner session must not replace an operational credential.
    from flask import request
    app.add_url_rule('/api/argus/admin/test', 'admin', lambda: ({'ok': True} if
                     request.headers.get('X-ARGUS-ADMIN-TOKEN') == 'test-admin' else ({'error': 'admin'}, 401)))
    return app.test_client(), auth, env


def post(client, action, body=None, token='', origin=ORIGIN):
    return client.post(module.PREFIX + '/' + action, json={} if body is None else body,
                       headers={'Origin': origin, 'X-ARGUS-OWNER-SESSION': token})


def login(client):
    response = post(client, 'password', {'password': PASSWORD})
    assert response.status_code == 200
    return response.json['token']


def registration(client, token):
    start = post(client, 'register-options', token=token).json
    private = ec.generate_private_key(ec.SECP256R1())
    public = private.public_key().public_numbers()
    credential_id = b'test-key-id'
    cose = cbor2.dumps({1: 2, 3: -7, -1: 1, -2: public.x.to_bytes(32, 'big'), -3: public.y.to_bytes(32, 'big')})
    auth_data = hashlib.sha256(b'owner.example').digest() + b'\x45' + bytes(4) + bytes(16) + len(credential_id).to_bytes(2, 'big') + credential_id + cose
    client_data = json.dumps({'type': 'webauthn.create', 'challenge': start['publicKey']['challenge'], 'origin': ORIGIN}).encode()
    credential = {'id': b64(credential_id), 'rawId': b64(credential_id), 'type': 'public-key',
                  'response': {'clientDataJSON': b64(client_data),
                               'attestationObject': b64(cbor2.dumps({'fmt': 'none', 'attStmt': {}, 'authData': auth_data}))}}
    return start, credential, private


def enroll(client, token):
    start, credential, private = registration(client, token)
    result = post(client, 'register-verify', {'challengeId': start['challengeId'], 'credential': credential}, token)
    assert result.status_code == 200, result.json
    return credential['id'], private


def assertion(client, keyid, private, count=1, origin=ORIGIN, flags=b'\x05'):
    start = post(client, 'login-options').json
    cd = json.dumps({'type': 'webauthn.get', 'challenge': start['publicKey']['challenge'], 'origin': origin}).encode()
    ad = hashlib.sha256(b'owner.example').digest() + flags + count.to_bytes(4, 'big')
    sig = private.sign(ad + hashlib.sha256(cd).digest(), ec.ECDSA(hashes.SHA256()))
    return {'challengeId': start['challengeId'], 'credential': {'id': keyid, 'rawId': keyid, 'type': 'public-key',
            'response': {'clientDataJSON': b64(cd), 'authenticatorData': b64(ad), 'signature': b64(sig), 'userHandle': b64(b'argus-owner-v1')}}}


def test_login_direct_access_logout(setup):
    client, auth, _ = setup
    assert client.get('/').status_code == 401
    assert client.get('/api/argus/data').status_code == 401
    assert client.get('/healthz').status_code == 200
    token = login(client)
    response = client.get('/api/argus/data', headers={'X-ARGUS-OWNER-SESSION': token})
    assert response.json == {'secret': 'fixture-private-value'}
    assert response.headers['Cache-Control'] == 'private, no-store'
    assert 'Set-Cookie' not in response.headers
    assert post(client, 'logout', token=token).status_code == 200
    assert client.get('/api/argus/data', headers={'X-ARGUS-OWNER-SESSION': token}).status_code == 401
    with auth.db() as conn:
        assert conn.execute('SELECT count(*) FROM owner_sessions').fetchone()[0] == 0


def test_actual_passkey_roundtrip_and_replay(setup):
    client, _, _ = setup
    keyid, private = enroll(client, login(client))
    payload = assertion(client, keyid, private)
    response = post(client, 'login-verify', payload)
    assert response.status_code == 200, response.json
    assert post(client, 'login-verify', payload).status_code == 401
    assert client.get('/api/argus/data', headers={'X-ARGUS-OWNER-SESSION': response.json['token']}).status_code == 200
    assert post(client, 'login-verify', assertion(client, keyid, private, count=1)).status_code == 401


@pytest.mark.parametrize('kind', ['origin', 'uv', 'signature', 'challenge', 'credential'])
def test_passkey_rejects_cryptographic_failures(setup, kind):
    client, _, _ = setup
    keyid, private = enroll(client, login(client))
    payload = assertion(client, keyid, private, origin='https://other.example' if kind == 'origin' else ORIGIN,
                        flags=b'\x01' if kind == 'uv' else b'\x05')
    if kind == 'signature': payload['credential']['response']['signature'] = b64(b'invalid')
    if kind == 'challenge': payload['challengeId'] = 'unknown'
    if kind == 'credential': payload['credential']['id'] = b64(b'unknown')
    assert post(client, 'login-verify', payload).status_code == 401


def test_registration_bound_to_session_and_one_use(setup):
    client, _, _ = setup
    first, second = login(client), login(client)
    start, credential, _ = registration(client, first)
    payload = {'challengeId': start['challengeId'], 'credential': credential}
    assert post(client, 'register-verify', payload, second).status_code == 401
    assert post(client, 'register-verify', payload, first).status_code == 401
    assert post(client, 'register-options').status_code == 401


def test_revocation_password_recovery_preserves_other_data(setup):
    client, auth, _ = setup
    token = login(client)
    enroll(client, token)
    assert post(client, 'revoke-all', {'password': 'wrong'}, token).status_code == 401
    assert post(client, 'revoke-all', {'password': PASSWORD}, token).status_code == 200
    with auth.db() as conn:
        for table in ('owner_sessions', 'owner_passkeys', 'owner_challenges'):
            assert conn.execute('SELECT count(*) FROM ' + table).fetchone()[0] == 0
    assert login(client)


def test_restart_and_password_rotation(setup):
    client, auth, env = setup
    token = login(client)
    second = module.OwnerAuth(env)
    with client.application.test_request_context(headers={'X-ARGUS-OWNER-SESSION': token}):
        assert second.session()
        rotated = module.OwnerAuth({**env, 'ARGUS_OWNER_PASSWORD_HASH': generate_password_hash('new', method='pbkdf2:sha256:1000')})
        assert not rotated.session()
    with auth.db() as conn:
        assert conn.execute('SELECT digest FROM owner_sessions').fetchone()[0] != token


def test_expiry_and_db_failure_fail_closed(setup):
    client, auth, _ = setup
    token = login(client)
    with auth.db() as conn:
        conn.execute('UPDATE owner_sessions SET expires=0')
    assert client.get('/api/argus/data', headers={'X-ARGUS-OWNER-SESSION': token}).status_code == 401
    auth.path += '/missing.db'
    assert client.get('/api/argus/data').status_code == 503


def test_admin_kept_separate_and_origin_body_limits(setup):
    client, _, _ = setup
    token = login(client)
    assert client.get('/api/argus/admin/test', headers={'X-ARGUS-OWNER-SESSION': token}).status_code == 401
    assert client.get('/api/argus/admin/test', headers={'X-ARGUS-ADMIN-TOKEN': 'test-admin'}).status_code == 200
    assert post(client, 'password', {'password': PASSWORD}, origin='https://evil.example').status_code == 403
    assert post(client, 'password', {'password': 'x' * 40000}).status_code == 413
    assert client.options('/api/argus/data').status_code == 200


def test_rate_persists_across_instances(setup):
    client, _, env = setup
    for _ in range(10): assert post(client, 'password', {'password': 'wrong'}).status_code == 401
    assert post(client, 'password', {'password': PASSWORD}).status_code == 429
    assert not module.OwnerAuth(env).rate('password')


@pytest.mark.parametrize('update', [{'ARGUS_OWNER_AUTH_ORIGIN': 'http://owner.example'},
    {'ARGUS_OWNER_AUTH_ORIGIN': ORIGIN + '/path'}, {'ARGUS_OWNER_AUTH_DB': 'relative.db'},
    {'ARGUS_OWNER_PASSWORD_HASH': ''}])
def test_bad_configuration_refuses_start(setup, update):
    _, _, env = setup
    with pytest.raises(RuntimeError): module.OwnerAuth({**env, **update})


def test_disabled_does_not_create_storage(tmp_path):
    app = Flask(__name__)
    module.install(app, {})
    app.add_url_rule('/', 'root', lambda: 'legacy')
    assert app.test_client().get('/').data == b'legacy'
    assert list(tmp_path.iterdir()) == []


def test_private_backup_and_restore_revokes_sessions(setup, tmp_path):
    from scripts.owner_auth_backup import copy_database
    client, auth, _ = setup
    token = login(client)
    enroll(client, token)
    backup, restored = tmp_path / 'backup.db', tmp_path / 'restored.db'
    assert copy_database(auth.path, backup)['passkeys'] == 1
    assert copy_database(backup, restored, restore=True)['sessionsInvalidated']
    with pytest.raises(ValueError): copy_database(auth.path, backup)
    import sqlite3
    with sqlite3.connect(restored) as conn:
        assert conn.execute('SELECT count(*) FROM owner_sessions').fetchone()[0] == 0
        assert conn.execute('SELECT count(*) FROM owner_challenges').fetchone()[0] == 0
        assert conn.execute('SELECT count(*) FROM owner_passkeys').fetchone()[0] == 0
    with sqlite3.connect(backup) as conn:
        assert conn.execute('SELECT count(*) FROM owner_passkeys').fetchone()[0] == 1
    assert restored.stat().st_mode & 0o777 == 0o600
    with auth.db() as conn:
        assert conn.execute('SELECT count(*) FROM owner_sessions').fetchone()[0] == 1


def test_expired_challenge_and_user_handle(setup):
    client, auth, _ = setup
    keyid, private = enroll(client, login(client))
    payload = assertion(client, keyid, private)
    with auth.db() as conn:
        conn.execute('UPDATE owner_challenges SET expires=0')
    assert post(client, 'login-verify', payload).status_code == 401
    payload = assertion(client, keyid, private)
    payload['credential']['response']['userHandle'] = b64(b'other-owner')
    assert post(client, 'login-verify', payload).status_code == 401


def test_nonce_attests_live_session_not_public_or_denied_response(setup):
    client, _, _ = setup
    token = login(client)
    nonce = '12345678-1234-1234-1234-123456789012'
    headers = {'X-ARGUS-OWNER-SESSION': token, 'X-ARGUS-OWNER-NONCE': nonce}
    response = client.get('/api/argus/data', headers=headers)
    assert response.headers['X-ARGUS-OWNER-NONCE'] == nonce
    assert 'X-ARGUS-OWNER-NONCE' in response.headers['Access-Control-Expose-Headers']
    assert client.get(module.PREFIX + '/session', headers=headers).headers['X-ARGUS-OWNER-NONCE'] == nonce
    assert 'X-ARGUS-OWNER-NONCE' not in client.get('/api/argus/data', headers={'X-ARGUS-OWNER-NONCE': nonce}).headers


def test_cors_preflight_retains_owner_headers(setup):
    from flask_cors import CORS
    client, _, _ = setup
    CORS(client.application, resources={r'/api/argus/*': {'origins': [ORIGIN]}})
    response = client.options('/api/argus/data', headers={'Origin': ORIGIN,
        'Access-Control-Request-Method': 'GET',
        'Access-Control-Request-Headers': 'X-ARGUS-OWNER-SESSION, X-ARGUS-OWNER-NONCE'})
    assert response.headers['Access-Control-Allow-Origin'] == ORIGIN
    assert 'X-ARGUS-OWNER-SESSION' in response.headers['Access-Control-Allow-Headers']
    assert 'X-ARGUS-OWNER-NONCE' in response.headers['Access-Control-Allow-Headers']


def test_login_does_not_start_later_market_middleware(setup):
    client, _, _ = setup
    @client.application.before_request
    def forbidden_market_bootstrap():
        raise AssertionError('authentication must not start market work')
    assert login(client)
    assert post(client, 'login-options').status_code == 401
    assert client.options(module.PREFIX + '/password').status_code == 200
    assert client.get('/api/argus/data').status_code == 401


def test_owner_session_lasts_one_app_session_of_up_to_twelve_hours():
    # Owner request 2026-10-02: a reload or relaunch keeps the login; the
    # frontend bounds it to the same build and rejects anything longer.
    import argus_owner_auth
    assert argus_owner_auth.TTL == 86400


def test_storage_bound_evicts_abandoned_sessions_before_the_one_in_use(setup):
    # 2026-10-02: with 24-hour sessions, evicting by earliest expiry removed the
    # owner's own login whenever a few dozen newer logins were issued.
    import time as clock
    client, auth, _ = setup
    owner = login(client)
    now = clock.time()
    with auth.db() as conn:
        conn.execute('UPDATE owner_sessions SET last_seen=?', (now - 7200,))
        for index in range(40):   # newer logins that were never used again
            conn.execute('INSERT INTO owner_sessions (digest, expires, epoch, last_seen) VALUES (?,?,?,?)',
                         (f'abandoned-{index}', now + module.TTL + index, auth.epoch, now - 3600 - index))
    assert client.get('/api/argus/data', headers={'X-ARGUS-OWNER-SESSION': owner}).status_code == 200
    login(client)
    assert client.get('/api/argus/data', headers={'X-ARGUS-OWNER-SESSION': owner}).status_code == 200
    with auth.db() as conn:
        assert conn.execute('SELECT count(*) FROM owner_sessions').fetchone()[0] == module.MAX_SESSIONS


def test_existing_sessions_survive_the_last_use_migration(tmp_path):
    import sqlite3
    path = tmp_path / 'legacy.db'
    env = {'ARGUS_OWNER_AUTH_REQUIRED': '1', 'ARGUS_OWNER_AUTH_DB': str(path), 'ARGUS_OWNER_AUTH_ORIGIN': ORIGIN,
           'ARGUS_OWNER_PASSWORD_HASH': generate_password_hash(PASSWORD, method='pbkdf2:sha256:1000')}
    token = 'x' * 43
    epoch = module.digest(ORIGIN + '\n' + env['ARGUS_OWNER_PASSWORD_HASH'])
    with sqlite3.connect(path) as conn:
        conn.execute('CREATE TABLE owner_sessions (digest TEXT PRIMARY KEY, expires REAL NOT NULL, epoch TEXT NOT NULL)')
        conn.execute('INSERT INTO owner_sessions VALUES (?,?,?)', (module.digest(token), 4e9, epoch))
    auth = module.OwnerAuth(env)
    with Flask(__name__).test_request_context(headers={'X-ARGUS-OWNER-SESSION': token}):
        assert auth.session()
    with auth.db() as conn:
        assert conn.execute('SELECT last_seen FROM owner_sessions').fetchone()[0] > 0
