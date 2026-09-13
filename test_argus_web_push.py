import base64
import json
from datetime import datetime, timezone
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
import argus_web_push as push


def b64(value):return base64.urlsafe_b64encode(value).decode().rstrip('=')

def sub(endpoint='https://web.push.apple.com/Qtest'):
    private=ec.generate_private_key(ec.SECP256R1())
    return {'endpoint':endpoint,'keys':{'auth':b64(b'1234567890123456'),'p256dh':b64(private.public_key().public_bytes(serialization.Encoding.X962,serialization.PublicFormat.UncompressedPoint))}}

@pytest.fixture
def service(tmp_path):
    clock=[1800000000.0];sent=[]
    def sender(*args):sent.append(args);return 201
    env={'ARGUS_WEB_PUSH_PRIVATE_KEY':b64((7).to_bytes(32,'big')),'ARGUS_WEB_PUSH_CONTACT':'https://example.org'}
    value=push.PushService(path=lambda:str(tmp_path/'push.sqlite3'),config=lambda:push.configuration(env),now=lambda:clock[0],sender=sender)
    return value,clock,sent

def subscribe(value,**kwargs):
    return value.handle({'operation':'subscribe','subscription':sub(),'sq':True,'news':True,**kwargs})['subscriptionId']

def event(clock,**kwargs):
    return {'key':'event:week','kind':'sq','title':'SQの週です','body':'日程を確認','hash':'#notifications/sq/jp-monthly-sq-2026-10','due':clock[0],'expires':clock[0]+100,**kwargs}

@pytest.mark.parametrize('endpoint',['http://web.push.apple.com/p','https://web.push.apple.com.evil.test/p','https://127.0.0.1/p','https://web.push.apple.com:8443/p','https://user@web.push.apple.com/p','https://fcm.googleapis.com/p?url=http://localhost','https://updates.push.services.mozilla.com/p#q'])
def test_reject_non_service_endpoint(endpoint):
    with pytest.raises(ValueError):push.subscription(sub(endpoint))

def test_claim_survives_restart_and_does_not_claim_device_receipt(service):
    value,clock,sent=service;identity=subscribe(value);notice=event(clock)
    value.tick([notice]);assert len(sent)==1
    restarted=push.PushService(path=value.path,config=value.config,now=value.now,sender=value.sender)
    restarted.tick([notice]);assert len(sent)==1
    result=restarted.status(identity);assert result['deliveries'][0]['status']=='SERVICE_ACCEPTED'
    assert result['deliveries'][0]['display_at'] is None
    assert 'endpoint' not in json.dumps(result) and not result['remoteRecoveryVerified']

def test_preferences_and_no_news_backfill(service):
    value,clock,sent=service;subscribe(value,news=False)
    value.tick([event(clock,kind='news')]);assert not sent
    subscribe(value,news=True)
    value.tick([event(clock,kind='news',due=clock[0]-1)]);assert not sent
    value.tick([event(clock,kind='news')]);assert len(sent)==1

def test_queued_test_can_close_app_then_disable_cancels(service):
    value,clock,sent=service;identity=subscribe(value)
    value.handle({'operation':'test','subscriptionId':identity});value.tick([]);assert not sent
    with pytest.raises(ValueError):value.handle({'operation':'test','subscriptionId':identity})
    clock[0]+=61;value.tick([]);assert len(sent)==1
    clock[0]+=61;value.handle({'operation':'test','subscriptionId':identity})
    value.handle({'operation':'disable','subscriptionId':identity});clock[0]+=61;value.tick([]);assert len(sent)==1

def test_timeout_not_blindly_resent_and_expiration_disables(service):
    value,clock,sent=service;identity=subscribe(value)
    def timeout(*args):raise TimeoutError()
    value.sender=timeout;value.tick([event(clock)]);value.tick([event(clock)])
    assert value.status(identity)['deliveries'][0]['status']=='DELIVERY_UNKNOWN'
    value.sender=lambda *args:410;value.tick([event(clock,key='other')]);assert not value.status(identity)['enabled']

def test_receipt_cannot_update_other_subscription_or_unsent(service):
    value,clock,sent=service;one=subscribe(value);two=subscribe(value,subscription=sub('https://web.push.apple.com/other'))
    value.tick([event(clock)]);delivery=value.status(one)['deliveries'][0]['id']
    report={'deliveryId':delivery,'displayedAt':datetime.fromtimestamp(clock[0],timezone.utc).isoformat(),'openedAt':None}
    value.handle({'operation':'receipts','subscriptionId':two,'receipts':[report]})
    assert value.status(one)['deliveries'][0]['display_at'] is None
    value.handle({'operation':'receipts','subscriptionId':one,'receipts':[report]})
    assert value.status(one)['deliveries'][0]['display_at']==report['displayedAt']

def test_sql_failure_rolls_back_and_never_sends(service,monkeypatch):
    value,clock,sent=service;subscribe(value)
    def broken(*args):raise OSError()
    monkeypatch.setattr(value,'enqueue',broken)
    with pytest.raises(OSError):value.tick([event(clock)])
    assert not sent

def test_real_encryption_and_vapid_without_network(service,monkeypatch):
    value,clock,sent=service;captured=[]
    class Response:status_code=201;text='';headers={}
    def post(self,url,**kwargs):captured.append((url,kwargs));return Response()
    monkeypatch.setattr(push.NoRedirectSession,'post',post)
    config=value.config();payload={'deliveryId':'12345678-1234-1234-1234-123456789abc','title':'test'}
    assert push.deliver(sub(),payload,config,60)==201
    url,kwargs=captured[0];assert url.startswith('https://web.push.apple.com/')
    assert kwargs['headers']['content-encoding']=='aes128gcm'
    assert kwargs['headers']['authorization'].startswith('vapid ')
    assert b'title' not in kwargs['data']

def test_auth_before_notification_callbacks(tmp_path):
    from flask import Flask
    import argus_owner_dialogue_api as api
    calls=[]
    class Service:
        def handle(self,body):calls.append(body);return {'configured':False}
    app=Flask(__name__)
    api.register(app,authorize=lambda token:(False,{'error':'auth'},401),storage_path=lambda:None,market_brief=lambda:None,generate=lambda *a:None,now=lambda:'2026-09-13T00:00:00Z',push_service=Service())
    result=app.test_client().post('/api/argus/owner-dialogue',json={'action':'notifications','operation':'configuration'})
    assert result.status_code==401 and calls==[]

def test_official_calendar_independent_of_ai():
    import jp_market_events
    now=datetime(2026,10,8,0,tzinfo=timezone.utc)
    calendar=jp_market_events.published_sq_calendar(now=now)
    rows=push.proposals(calendar,[],now.timestamp())
    assert len(rows)==1 and rows[0]['kind']=='sq'
    assert rows[0]['hash']=='#notifications/sq/jp-monthly-sq-2026-10'
    assert rows[0]['key'].endswith(':PREVIOUS_SESSION')

def test_no_redirect_and_bounded_network(monkeypatch):
    import requests
    seen=[]
    class Session:
        trust_env=True
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def post(self,*args,**kwargs):seen.append((self.trust_env,kwargs));return object()
    monkeypatch.setattr(requests,'Session',Session)
    push.NoRedirectSession().post('https://web.push.apple.com/p',timeout=10000)
    assert seen==[(False,{'timeout':12,'allow_redirects':False})]

def test_disabling_category_cancels_already_queued_notice(service):
    value,clock,sent=service;data=sub();identity=subscribe(value,subscription=data)
    with value.db() as db:value.enqueue(db,identity,event(clock,key='news:one',due=clock[0]+5),clock[0])
    subscribe(value,subscription=data,news=False);clock[0]+=6;value.tick([])
    assert not sent and value.status(identity)['deliveries'][0]['status']=='CANCELLED'

def test_news_pending_ai_can_notify_but_backfill_cannot():
    now=datetime(2026,9,13,tzinfo=timezone.utc)
    record={'eventId':'ev-123','severity':'HIGH','sourceReceivedAt':now.isoformat(),'alertEligible':True,'analysisState':'AI_ANALYSIS_PENDING'}
    assert push.proposals({},[record],now.timestamp())[0]['hash']=='#notifications/news/ev-123'
    assert push.proposals({},[{**record,'backfill':True}],now.timestamp())==[]


def test_worker_reads_news_store_independently_of_brief(monkeypatch):
    import copy
    import scanner
    now = datetime.now(timezone.utc).isoformat()
    records = {'material': {'eventId': 'material', 'severity': 'CRITICAL',
               'alertEligible': True, 'sourceReceivedAt': now}}
    records.update({str(i): {'eventId': str(i), 'severity': 'INFO'} for i in range(15)})
    before = copy.deepcopy(records)
    monkeypatch.setitem(scanner._NEWS_INTEL, 'events', records)
    monkeypatch.setitem(scanner._NEWS_INTEL, 'order', list(records))
    monkeypatch.setattr(scanner, '_news_intel_ensure_loaded', lambda: None)
    monkeypatch.setattr(push, 'configuration', lambda env: {'configured': True})
    projected = []
    def project(record):
        projected.append(record['eventId'])
        if record['eventId'] == '0': raise ValueError('invalid record')
        return dict(record)
    monkeypatch.setattr(scanner.argus_news_intelligence, 'project_owner_event', project)
    def forbidden(): raise AssertionError('generated explanation must not drive notifications')
    monkeypatch.setattr(scanner, '_brief_news_events', forbidden)
    sent = []
    monkeypatch.setattr(scanner._WEB_PUSH, 'tick', lambda rows: sent.extend(rows))
    scanner._web_push_tick()
    assert any(row['hash'] == '#notifications/news/material' for row in sent)
    assert 'material' in projected and len(projected) == 16
    assert records == before
