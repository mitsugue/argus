"""Owner-authorized Web Push with durable event claims and explicit receipts.

The HTTP transport accepting a message is not evidence of device display.
Subscription endpoints never appear in API responses or logs.
"""
from __future__ import annotations
import base64
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
import re
import sqlite3
import threading
import uuid
from urllib.parse import urlsplit
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec


def decode(value, size):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]+={0,2}', value):
        raise ValueError('invalid_push_key')
    raw = base64.urlsafe_b64decode(value + '=' * (-len(value) % 4))
    if len(raw) != size: raise ValueError('invalid_push_key')
    return raw


def subscription(value):
    if not isinstance(value, dict) or set(value) - {'endpoint', 'keys', 'expirationTime'}:
        raise ValueError('invalid_subscription')
    endpoint = value.get('endpoint')
    if not isinstance(endpoint, str) or not 20 <= len(endpoint) <= 2048:
        raise ValueError('invalid_push_endpoint')
    parsed = urlsplit(endpoint)
    host = parsed.hostname or ''
    allowed = (host == 'web.push.apple.com' or bool(re.fullmatch(r'[a-z0-9-]+\.push\.apple\.com', host))
               or host in {'fcm.googleapis.com', 'updates.push.services.mozilla.com'})
    if (parsed.scheme != 'https' or not allowed or parsed.port not in (None, 443)
            or parsed.username or parsed.password or parsed.fragment or parsed.query
            or not parsed.path.startswith('/') or len(parsed.path) < 2):
        raise ValueError('unsupported_push_service')
    keys = value.get('keys')
    if not isinstance(keys, dict) or set(keys) != {'p256dh', 'auth'}: raise ValueError('invalid_push_key')
    ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), decode(keys['p256dh'], 65))
    decode(keys['auth'], 16)
    return {'endpoint': endpoint, 'keys': keys}


def configuration(env):
    private = env.get('ARGUS_WEB_PUSH_PRIVATE_KEY', '')
    subject = env.get('ARGUS_WEB_PUSH_CONTACT', '')
    if not private or not subject: return {'configured': False}
    try:
        raw = decode(private, 32)
        key = ec.derive_private_key(int.from_bytes(raw, 'big'), ec.SECP256R1())
        if not (re.fullmatch(r'mailto:[^\s@]+@[^\s@]+', subject) or
                (urlsplit(subject).scheme == 'https' and urlsplit(subject).hostname and not urlsplit(subject).path and not urlsplit(subject).query and not urlsplit(subject).fragment and not urlsplit(subject).username and not urlsplit(subject).port)):
            raise ValueError('invalid_contact')
        public = base64.urlsafe_b64encode(key.public_key().public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)).decode().rstrip('=')
        return {'configured': True, 'publicKey': public, 'privateKey': private, 'contact': subject}
    except Exception: return {'configured': False}


class NoRedirectSession:
    """pywebpush transport: fixed validated service, no redirect or proxy route."""
    def post(self, *args, **kwargs):
        import requests
        kwargs['allow_redirects'] = False
        kwargs['timeout'] = 12
        with requests.Session() as session:
            session.trust_env = False
            return session.post(*args, **kwargs)


def deliver(sub, payload, config, ttl):
    from pywebpush import webpush
    return webpush(subscription_info=subscription(sub), data=json.dumps(payload, ensure_ascii=False),
                   vapid_private_key=config['privateKey'], vapid_claims={'sub': config['contact']},
                   ttl=ttl, timeout=12, requests_session=NoRedirectSession(),
                   headers={'Urgency': 'normal', 'Topic': payload['deliveryId'].replace('-', '')}).status_code


class PushService:
    def __init__(self, *, path, config, now, sender=deliver):
        self.path, self.config, self.now, self.sender = path, config, now, sender
        self.lock = threading.Lock()

    @contextmanager
    def db(self):
        path = self.path()
        if not path: raise ValueError('push_storage_unavailable')
        os.makedirs(os.path.dirname(path), exist_ok=True)
        fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600); os.close(fd); os.chmod(path, 0o600)
        conn = sqlite3.connect(path, timeout=5)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute('PRAGMA synchronous=FULL')
            conn.executescript('''CREATE TABLE IF NOT EXISTS subscriptions (
              id TEXT PRIMARY KEY, body TEXT NOT NULL, created REAL NOT NULL,
              enabled INTEGER NOT NULL, sq INTEGER NOT NULL, news INTEGER NOT NULL);
              CREATE TABLE IF NOT EXISTS deliveries (
              id TEXT PRIMARY KEY, subscription_id TEXT NOT NULL, event_key TEXT NOT NULL,
              payload TEXT NOT NULL, due REAL NOT NULL, expires REAL NOT NULL,
              status TEXT NOT NULL, attempted REAL, display_at TEXT, opened_at TEXT,
              UNIQUE(subscription_id,event_key));''')
            yield conn
            conn.commit()
        finally: conn.close()

    def handle(self, body):
        allowed = {'action','ownerToken','operation','subscription','subscriptionId','sq','news','receipts'}
        if set(body) - allowed: raise ValueError('invalid_push_request')
        operation = body.get('operation')
        config = self.config()
        if operation == 'configuration':
            return {'configured': config['configured'], 'publicKey': config.get('publicKey'),
                    'remoteRecoveryVerified': False}
        if operation not in {'subscribe','status','disable','test','receipts'}:
            raise ValueError('invalid_push_operation')
        now = self.now()
        if operation == 'subscribe':
            if not config['configured']: raise ValueError('push_not_configured')
            sub = subscription(body.get('subscription'))
            if not isinstance(body.get('sq'), bool) or not isinstance(body.get('news'), bool):
                raise ValueError('invalid_push_preferences')
            identity = hashlib.sha256(sub['endpoint'].encode()).hexdigest()
            with self.db() as db:
                db.execute('BEGIN IMMEDIATE')
                if not db.execute('SELECT 1 FROM subscriptions WHERE id=?', (identity,)).fetchone() and db.execute(
                    'SELECT count(*) FROM subscriptions WHERE enabled=1').fetchone()[0] >= 10:
                    raise ValueError('push_device_limit')
                db.execute('INSERT INTO subscriptions VALUES(?,?,?,1,?,?) ON CONFLICT(id) DO UPDATE SET body=excluded.body, enabled=1,sq=excluded.sq,news=excluded.news,created=CASE WHEN subscriptions.enabled=0 OR (subscriptions.news=0 AND excluded.news=1) THEN excluded.created ELSE subscriptions.created END',
                           (identity, json.dumps(sub), now, int(body['sq']), int(body['news'])))
                db.execute("UPDATE deliveries SET status='CANCELLED' WHERE subscription_id=? AND status='QUEUED' AND ((?=0 AND event_key LIKE 'news:%') OR (?=0 AND event_key LIKE 'jp-monthly-sq-%'))",(identity,int(body['news']),int(body['sq'])))
            return self.status(identity)
        identity = body.get('subscriptionId')
        if not isinstance(identity, str) or not re.fullmatch('[a-f0-9]{64}', identity):
            raise ValueError('invalid_push_identity')
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            found = db.execute('SELECT * FROM subscriptions WHERE id=?', (identity,)).fetchone()
            if not found: raise ValueError('push_subscription_missing')
            if operation == 'disable':
                db.execute('UPDATE subscriptions SET enabled=0 WHERE id=?', (identity,))
                db.execute("UPDATE deliveries SET status='CANCELLED' WHERE subscription_id=? AND status='QUEUED'", (identity,))
            elif operation == 'test':
                if not found['enabled']: raise ValueError('push_subscription_disabled')
                recent = db.execute("SELECT 1 FROM deliveries WHERE subscription_id=? AND event_key LIKE 'test:%' AND due>?", (identity, now-60)).fetchone()
                if recent: raise ValueError('push_test_cooldown')
                self.enqueue(db, identity, {'key':'test:'+str(uuid.uuid4()), 'title':'ARGUSの通知確認',
                    'body':'通知が届いたらタップして、Settingsで受信状況を確認してください。',
                    'hash':'#settings', 'due':now+60, 'expires':now+660}, now)
            elif operation == 'receipts':
                receipts = body.get('receipts')
                if not isinstance(receipts, list) or len(receipts)>50: raise ValueError('invalid_push_receipts')
                for receipt in receipts:
                    if not isinstance(receipt, dict) or set(receipt) != {'deliveryId','displayedAt','openedAt'}:
                        raise ValueError('invalid_push_receipts')
                    times = []
                    for field in ('displayedAt','openedAt'):
                        value = receipt[field]
                        if value is not None:
                            if not isinstance(value,str) or len(value)>40: raise ValueError('invalid_push_receipts')
                            stamp = datetime.fromisoformat(value.replace('Z','+00:00'))
                            if stamp.tzinfo is None or stamp.timestamp()>now+300: raise ValueError('invalid_push_receipts')
                        times.append(value)
                    # Client-reported display/open, never promoted to physical acceptance.
                    db.execute('UPDATE deliveries SET display_at=coalesce(display_at,?),opened_at=coalesce(opened_at,?) WHERE id=? AND subscription_id=? AND attempted IS NOT NULL',
                               (*times, receipt['deliveryId'], identity))
        return self.status(identity)

    def status(self, identity):
        with self.db() as db:
            row = db.execute('SELECT enabled,sq,news FROM subscriptions WHERE id=?', (identity,)).fetchone()
            records = [dict(r) for r in db.execute('SELECT id,event_key,status,attempted,display_at,opened_at FROM deliveries WHERE subscription_id=? ORDER BY due DESC LIMIT 20', (identity,))]
        return {'subscriptionId': identity, 'enabled': bool(row['enabled']), 'sq': bool(row['sq']),
                'news': bool(row['news']), 'deliveries': records, 'remoteRecoveryVerified': False}

    def enqueue(self, db, identity, event, now):
        if not event['due'] <= event['expires'] or event['expires'] <= now: return
        delivery_id = str(uuid.uuid4())
        payload = {'schemaVersion':'argus-web-push-v1','deliveryId':delivery_id,
                   'title':event['title'][:100],'body':event['body'][:220],'hash':event['hash'],
                   'expiresAt':datetime.fromtimestamp(event['expires'],timezone.utc).isoformat()}
        db.execute('INSERT OR IGNORE INTO deliveries(id,subscription_id,event_key,payload,due,expires,status) VALUES(?,?,?,?,?,?,?)',
                   (delivery_id, identity, event['key'], json.dumps(payload,ensure_ascii=False), event['due'], event['expires'], 'QUEUED'))

    def tick(self, events):
        if not self.lock.acquire(blocking=False): return
        try:
            config = self.config()
            if not config['configured'] or not self.path(): return
            now = self.now()
            with self.db() as db:
                for sub in db.execute('SELECT * FROM subscriptions WHERE enabled=1').fetchall():
                    for event in events[:20]:
                        if event['kind'] not in {'sq','news'} or not sub[event['kind']]: continue
                        if event['kind']=='news' and event['due']<sub['created']: continue
                        self.enqueue(db,sub['id'],event,now)
                db.execute("UPDATE deliveries SET status='EXPIRED' WHERE status='QUEUED' AND expires<=?", (now,))
                # A process interrupted after claiming cannot prove non-delivery.
                db.execute("UPDATE deliveries SET status='DELIVERY_UNKNOWN' WHERE status='SENDING' AND attempted<?", (now-120,))
            for _ in range(4):
                with self.db() as db:
                    db.execute('BEGIN IMMEDIATE')
                    row = db.execute("SELECT d.*,s.body FROM deliveries d JOIN subscriptions s ON s.id=d.subscription_id WHERE s.enabled=1 AND d.status='QUEUED' AND d.due<=? AND d.expires>? ORDER BY d.due LIMIT 1", (now,now)).fetchone()
                    if not row: break
                    db.execute("UPDATE deliveries SET status='SENDING',attempted=? WHERE id=?", (now,row['id']))
                try:
                    code = self.sender(json.loads(row['body']),json.loads(row['payload']),config,max(1,int(row['expires']-self.now())))
                    status = 'SERVICE_ACCEPTED' if 200<=code<300 else 'SUBSCRIPTION_EXPIRED' if code in (404,410) else 'SERVICE_REJECTED'
                except Exception as exc:
                    response = getattr(exc,'response',None)
                    code = getattr(response,'status_code',None)
                    status = 'SUBSCRIPTION_EXPIRED' if code in (404,410) else 'SERVICE_REJECTED' if code else 'DELIVERY_UNKNOWN'
                with self.db() as db:
                    db.execute('UPDATE deliveries SET status=? WHERE id=?',(status,row['id']))
                    if status=='SUBSCRIPTION_EXPIRED': db.execute('UPDATE subscriptions SET enabled=0 WHERE id=?',(row['subscription_id'],))
        finally: self.lock.release()


def proposals(calendar, news, now):
    result = []
    for p in calendar.get('notificationProposals',[]):
        result.append({'key':p['deduplicationKey'],'kind':'sq','title':p['title'],
            'body':'清算に関係する日程です。SQだけで相場の方向は判断しません。日程と根拠を確認してください。',
            'hash':'#notifications/sq/'+p['eventId'],
            'due':datetime.fromisoformat(p['dueAt']).timestamp(),'expires':datetime.fromisoformat(p['expiresAt']).timestamp()})
    for item in news:
        if item.get('backfill') or item.get('staleness')=='STALE': continue
        if item.get('severity') not in ('HIGH','CRITICAL') or item.get('alertEligible') is not True: continue
        event_id = item.get('eventId'); received = item.get('processedAt') or item.get('sourceReceivedAt')
        if not isinstance(event_id,str) or not re.fullmatch(r'[A-Za-z0-9:_-]{1,150}',event_id): continue
        try:
            stamp = datetime.fromisoformat(received.replace('Z','+00:00'))
            source_stamp = datetime.fromisoformat(str(item.get('sourceReceivedAt')).replace('Z','+00:00'))
            if stamp.tzinfo is None or source_stamp.tzinfo is None: continue
            due = stamp.timestamp()
        except Exception: continue
        # Reanalysis does not turn a days-old intake into a new notification.
        if not 0<=now-source_stamp.timestamp()<=24*3600: continue
        if not 0<=now-due<=3600: continue
        # Public, rights-cleared product projection is the only input; no article text on lock screen.
        result.append({'key':'news:'+event_id+':'+item['severity'],'kind':'news',
            'title':'重大ニュースを確認してください','body':'市場に影響し得る新しい材料があります。記事と確認状況をARGUSで確認してください。',
            'hash':'#notifications/news/'+event_id,'due':due,'expires':due+3600})
    return result
