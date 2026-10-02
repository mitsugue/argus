"""Opt-in owner authentication. Opaque browser sessions never grant admin rights.

No cookies or storage of bearer secrets in the browser are required. SQLite
transactions consume challenges and advance counters across worker processes.
"""
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import time
from contextlib import contextmanager
from urllib.parse import urlsplit

from flask import g, jsonify, request
from werkzeug.security import check_password_hash

PREFIX = '/api/argus/owner-auth'
# 24 hours: a reload or relaunch inside one app session keeps the owner signed in
# (owner request 2026-10-02); logout and revoke-all still end it at once.
TTL = 86400
MAX_BODY = 32768
# Stored sessions are bounded; the least recently used go first.
MAX_SESSIONS = 32
SEEN_RESOLUTION = 60


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


class OwnerAuth:
    def __init__(self, env):
        mode = env.get('ARGUS_OWNER_AUTH_REQUIRED', '0')
        if mode not in ('0', '1'):
            raise RuntimeError('owner_auth_mode_invalid')
        self.enabled = mode == '1'
        self.path = env.get('ARGUS_OWNER_AUTH_DB', '')
        self.origin = env.get('ARGUS_OWNER_AUTH_ORIGIN', '')
        self.password_hash = env.get('ARGUS_OWNER_PASSWORD_HASH', '')
        self.admin = env.get('ARGUS_ADMIN_TOKEN', '')
        if not self.enabled:
            return
        parsed = urlsplit(self.origin)
        if (parsed.scheme != 'https' or not parsed.hostname or parsed.username
                or parsed.password or parsed.path or parsed.query or parsed.fragment
                or parsed.port not in (None, 443)
                or not os.path.isabs(self.path)
                or not self.password_hash.startswith(('scrypt:', 'pbkdf2:sha256:'))):
            raise RuntimeError('owner_auth_configuration_invalid')
        # Pin the RP to the exact browser host, not a parent/public suffix.
        self.rp = parsed.hostname
        self.epoch = digest(self.origin + '\n' + self.password_hash)
        if os.path.islink(self.path):
            raise RuntimeError('owner_auth_database_symlink')
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        os.close(fd)
        os.chmod(self.path, 0o600)
        with self.db() as conn:
            conn.executescript('''
                CREATE TABLE IF NOT EXISTS owner_sessions (
                    digest TEXT PRIMARY KEY, expires REAL NOT NULL, epoch TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS owner_challenges (
                    id TEXT PRIMARY KEY, challenge TEXT NOT NULL, purpose TEXT NOT NULL,
                    session_digest TEXT NOT NULL, expires REAL NOT NULL, epoch TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS owner_passkeys (
                    id TEXT PRIMARY KEY, public_key BLOB NOT NULL, counter INTEGER NOT NULL,
                    created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS owner_rate (
                    id TEXT PRIMARY KEY, window REAL NOT NULL, count INTEGER NOT NULL);
            ''')
            # 2026-10-02: sessions carry their last use so the storage bound
            # evicts abandoned sessions first. With 24-hour sessions, evicting
            # by earliest expiry removed the owner's own long-lived login (and
            # pages still in use) whenever another device or the release
            # acceptance signed in a few dozen times. Existing rows are kept;
            # they count as used at migration time.
            columns = {row['name'] for row in conn.execute('PRAGMA table_info(owner_sessions)')}
            if 'last_seen' not in columns:
                conn.execute('ALTER TABLE owner_sessions ADD COLUMN last_seen REAL NOT NULL DEFAULT 0')
                conn.execute('UPDATE owner_sessions SET last_seen=?', (time.time(),))

    @contextmanager
    def db(self):
        conn = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute('PRAGMA synchronous=FULL')
            conn.execute('BEGIN IMMEDIATE')
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def token_digest(self):
        token = request.headers.get('X-ARGUS-OWNER-SESSION', '')
        return digest(token) if 32 <= len(token) <= 128 else ''

    def session(self):
        now = time.time()
        with self.db() as conn:
            row = conn.execute('SELECT expires, last_seen FROM owner_sessions WHERE digest=? AND epoch=?',
                               (self.token_digest(), self.epoch)).fetchone()
            valid = bool(row and row['expires'] > now)
            # Record use at most once a minute; it only orders eviction.
            if valid and now - row['last_seen'] >= SEEN_RESOLUTION:
                conn.execute('UPDATE owner_sessions SET last_seen=? WHERE digest=?', (now, self.token_digest()))
        if valid:
            g.owner_session_verified = True
        return valid

    def issue(self, conn):
        now = time.time()
        conn.execute('DELETE FROM owner_sessions WHERE expires<=? OR epoch<>?', (now, self.epoch))
        # Bound storage, including repeated successful logins.
        conn.execute('DELETE FROM owner_sessions WHERE digest IN '
                     '(SELECT digest FROM owner_sessions ORDER BY last_seen DESC, expires DESC '
                     'LIMIT -1 OFFSET ?)', (MAX_SESSIONS - 1,))
        token = secrets.token_urlsafe(32)
        conn.execute('INSERT INTO owner_sessions (digest, expires, epoch, last_seen) VALUES (?,?,?,?)',
                     (digest(token), now + TTL, self.epoch, now))
        return {'token': token, 'expiresAt': int((now + TTL) * 1000)}

    def rate(self, purpose):
        # One persistent owner-wide limit: spoofed forwarding headers cannot
        # create new buckets; all processes share the same reservation.
        now = time.time()
        with self.db() as conn:
            row = conn.execute('SELECT * FROM owner_rate WHERE id=?', (purpose,)).fetchone()
            count = row['count'] if row and now - row['window'] < 60 else 0
            start = row['window'] if count else now
            if count >= 10:
                return False
            conn.execute('INSERT OR REPLACE INTO owner_rate VALUES (?,?,?)', (purpose, start, count + 1))
        return True

    def options(self, purpose):
        from webauthn import generate_registration_options, generate_authentication_options, options_to_json
        from webauthn.helpers import base64url_to_bytes, bytes_to_base64url
        from webauthn.helpers.structs import (AuthenticatorSelectionCriteria, PublicKeyCredentialDescriptor,
                                             ResidentKeyRequirement, UserVerificationRequirement)
        with self.db() as conn:
            now = time.time()
            conn.execute('DELETE FROM owner_challenges WHERE expires<=? OR epoch<>?', (now, self.epoch))
            rows = conn.execute('SELECT id FROM owner_passkeys').fetchall()
            if purpose == 'register' and len(rows) >= 16:
                raise ValueError('passkey_limit')
            if purpose == 'login' and not rows:
                raise ValueError('no_passkeys')
            credentials = [PublicKeyCredentialDescriptor(id=base64url_to_bytes(r['id'])) for r in rows]
            challenge = secrets.token_bytes(32)
            ident = secrets.token_urlsafe(32)
            if purpose == 'register':
                options = generate_registration_options(
                    rp_id=self.rp, rp_name='ARGUS', user_id=b'argus-owner-v1',
                    user_name='owner', user_display_name='ARGUS owner', challenge=challenge,
                    exclude_credentials=credentials,
                    authenticator_selection=AuthenticatorSelectionCriteria(
                        resident_key=ResidentKeyRequirement.REQUIRED,
                        user_verification=UserVerificationRequirement.REQUIRED))
            else:
                options = generate_authentication_options(
                    rp_id=self.rp, challenge=challenge, allow_credentials=credentials,
                    user_verification=UserVerificationRequirement.REQUIRED)
            conn.execute('INSERT INTO owner_challenges VALUES (?,?,?,?,?,?)',
                         (ident, bytes_to_base64url(challenge), purpose,
                          self.token_digest() if purpose == 'register' else '', now + 300, self.epoch))
        return {'challengeId': ident, 'publicKey': json.loads(options_to_json(options))}

    def verify(self, purpose, body):
        from webauthn import verify_registration_response, verify_authentication_response
        from webauthn.helpers import base64url_to_bytes, bytes_to_base64url
        # Commit consumption even on an invalid signature. Challenges are one-use.
        with self.db() as conn:
            row = conn.execute('SELECT * FROM owner_challenges WHERE id=?', (body.get('challengeId', ''),)).fetchone()
            if row:
                conn.execute('DELETE FROM owner_challenges WHERE id=?', (row['id'],))
        if (not row or row['expires'] <= time.time() or row['epoch'] != self.epoch
                or row['purpose'] != purpose or purpose == 'register'
                and row['session_digest'] != self.token_digest()):
            raise ValueError('invalid_challenge')
        credential = body.get('credential')
        if not isinstance(credential, dict):
            raise ValueError('invalid_credential')
        if purpose == 'login' and credential.get('response', {}).get('userHandle') not in (
                None, bytes_to_base64url(b'argus-owner-v1')):
            raise ValueError('invalid_user_handle')
        common = dict(credential=credential, expected_challenge=base64url_to_bytes(row['challenge']),
                      expected_rp_id=self.rp, expected_origin=self.origin, require_user_verification=True)
        with self.db() as conn:
            if purpose == 'register':
                session = conn.execute('SELECT expires FROM owner_sessions WHERE digest=? AND epoch=?',
                                       (self.token_digest(), self.epoch)).fetchone()
                if not session or session['expires'] <= time.time():
                    raise ValueError('session_expired')
                if conn.execute('SELECT count(*) FROM owner_passkeys').fetchone()[0] >= 16:
                    raise ValueError('passkey_limit')
                result = verify_registration_response(**common)
                conn.execute('INSERT INTO owner_passkeys VALUES (?,?,?,?)',
                             (bytes_to_base64url(result.credential_id), result.credential_public_key,
                              result.sign_count, time.time()))
                return {'registered': True}
            key = conn.execute('SELECT * FROM owner_passkeys WHERE id=?', (credential.get('id'),)).fetchone()
            if not key:
                raise ValueError('unknown_passkey')
            result = verify_authentication_response(
                **common, credential_public_key=key['public_key'], credential_current_sign_count=key['counter'])
            conn.execute('UPDATE owner_passkeys SET counter=? WHERE id=?', (result.new_sign_count, key['id']))
            return self.issue(conn)


def install(app, env=None):
    auth = OwnerAuth(dict(os.environ if env is None else env))
    app.extensions['argus_owner_auth'] = auth

    @app.before_request
    def owner_boundary():
        # Authentication must be available without starting market restoration,
        # news/provider threads, or any other later application middleware.
        if request.endpoint == 'owner_action':
            if request.method == 'OPTIONS':
                return app.make_default_options_response()
            return owner_action(request.view_args['action'])
        if not auth.enabled:
            return None
        if request.method == 'OPTIONS' or request.path in ('/healthz', '/readyz'):
            return None
        # Retain existing operational credentials and every downstream check.
        admin = request.headers.get('X-ARGUS-ADMIN-TOKEN', '')
        if auth.admin and hmac.compare_digest(admin.encode(), auth.admin.encode()):
            return None
        try:
            if auth.session():
                return None
        except sqlite3.Error:
            return jsonify(error='owner_auth_unavailable'), 503
        return jsonify(error='owner_auth_required'), 401

    @app.after_request
    def private_responses(response):
        if auth.enabled and request.path not in ('/healthz', '/readyz'):
            response.headers['Cache-Control'] = 'private, no-store'
            nonce = request.headers.get('X-ARGUS-OWNER-NONCE', '')
            if getattr(g, 'owner_session_verified', False) and len(nonce) == 36:
                response.headers['X-ARGUS-OWNER-NONCE'] = nonce
                response.headers['Access-Control-Expose-Headers'] = ', '.join(filter(None, [
                    response.headers.get('Access-Control-Expose-Headers'), 'X-ARGUS-OWNER-NONCE']))
            response.headers['Vary'] = ', '.join(filter(None, [response.headers.get('Vary'), 'X-ARGUS-OWNER-SESSION']))
        return response

    @app.route(PREFIX + '/<action>', methods=['GET', 'POST'])
    def owner_action(action):
        if not auth.enabled:
            return jsonify(error='owner_auth_disabled'), 503
        if request.method == 'GET' and action == 'session':
            try:
                if auth.session():
                    return jsonify(authenticated=True)
            except sqlite3.Error:
                return jsonify(error='owner_auth_unavailable'), 503
            return jsonify(error='owner_auth_required'), 401
        if request.method != 'POST' or action not in (
                'password', 'logout', 'revoke-all', 'register-options', 'register-verify',
                'login-options', 'login-verify'):
            return jsonify(error='not_found'), 404
        if request.headers.get('Origin') != auth.origin:
            return jsonify(error='origin_rejected'), 403
        if request.content_length is None or request.content_length > MAX_BODY:
            return jsonify(error='body_limit'), 413
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return jsonify(error='invalid_request'), 400
        try:
            if action not in ('password', 'login-options', 'login-verify') and not auth.session():
                return jsonify(error='owner_auth_required'), 401
            if action == 'logout':
                with auth.db() as conn:
                    conn.execute('DELETE FROM owner_sessions WHERE digest=?', (auth.token_digest(),))
                return jsonify(loggedOut=True)
            if not auth.rate(action):
                return jsonify(error='try_later'), 429
            if action in ('password', 'revoke-all'):
                password = body.get('password')
                if not isinstance(password, str) or len(password) > 1024 or not check_password_hash(auth.password_hash, password):
                    return jsonify(error='authentication_failed'), 401
                with auth.db() as conn:
                    if action == 'revoke-all':
                        conn.execute('DELETE FROM owner_sessions')
                        conn.execute('DELETE FROM owner_challenges')
                        conn.execute('DELETE FROM owner_passkeys')
                        return jsonify(revoked=True)
                    return jsonify(auth.issue(conn))
            purpose = 'register' if action.startswith('register') else 'login'
            return jsonify(auth.options(purpose) if action.endswith('options') else auth.verify(purpose, body))
        except sqlite3.Error:
            return jsonify(error='owner_auth_unavailable'), 503
        except Exception:
            return jsonify(error='authentication_failed'), 401
    return auth
