import base64
import json
from datetime import datetime, timezone, timedelta
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
    return value.handle({'operation':'subscribe','subscription':sub(),'sq':True,'news':True,'ownerChanges':True,**kwargs})['subscriptionId']

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


def _move(clock, **kwargs):
    # The shape scanner._record_event stores (argus_events.make_envelope).
    stamp = datetime.fromtimestamp(clock[0], timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    return {'eventId': 'US:SOXL:PRICE_SPIKE:2026-10-23:20#' + stamp, 'eventType': 'PRICE_SPIKE',
            'severity': 4, 'symbol': 'SOXL', 'market': 'US', 'sourceTimeValidated': True,
            'observedAt': stamp, 'ingestAt': stamp,
            'reasonJa': '急騰 +8.24%(US_REGULAR閾値5%)', **kwargs}


def test_owner_change_is_opt_in_names_the_symbol_and_is_not_backfilled(service):
    value,clock,sent=service
    data=sub();identity=subscribe(value,subscription=data,ownerChanges=False)
    item=_move(clock,ownerState='held')
    rows=push.proposals({},[],clock[0],owner_events=[item])
    assert len(rows)==1 and rows[0]['kind']=='owner_changes'
    # The symbol's own screen, never the retired holdings landing.
    assert rows[0]['hash']=='#asset/SOXL'
    assert rows[0]['title']=='監視銘柄 SOXL 急騰 +8.2%'
    assert '保有' not in rows[0]['title']
    assert rows[0]['body'].endswith('時点の値動きです。') and len(rows[0]['body'])<=20
    value.tick(rows);assert not sent
    subscribe(value,subscription=data,ownerChanges=True);value.tick(rows);assert len(sent)==1
    payload=sent[0][1]
    assert payload['hash']=='#asset/SOXL' and payload['title']=='監視銘柄 SOXL 急騰 +8.2%'
    value.tick(rows);assert len(sent)==1   # one notice per event and severity
    old=_move(clock,eventId='US:SOXL:PRICE_SPIKE:old',
              ingestAt=datetime.fromtimestamp(clock[0]-3601,timezone.utc).isoformat())
    assert push.proposals({},[],clock[0],owner_events=[old])==[]


def test_jp_move_title_carries_code_and_company_name(service):
    _,clock,_=service
    item=_move(clock,eventId='JP:7203:PRICE_CRASH:2026-10-23:20#x',symbol='7203',market='JP',
               eventType='PRICE_CRASH',nameJa='トヨタ自動車',reasonJa='急落 -6.12%(JP_REGULAR閾値5%)')
    row=push.proposals({},[],clock[0],owner_events=[item])[0]
    assert row['title']=='監視銘柄 7203 トヨタ自動車 急落 -6.1%' and row['hash']=='#asset/7203'
    long=_move(clock,symbol='285A',market='JP',nameJa='とても長い会社名株式会社ホールディングス')
    assert push.proposals({},[],clock[0],owner_events=[long])[0]['title']=='監視銘柄 285A とても長い会社名株…'+' 急騰 +8.2%'
    stop=_move(clock,symbol='7203',market='JP',eventType='LIMIT_DOWN',nameJa='トヨタ自動車',
               reasonJa='ストップ安(S安)に到達 — 制限値幅±500円',severity=5)
    assert push.proposals({},[],clock[0],owner_events=[stop])[0]['title']=='監視銘柄 7203 トヨタ自動車 ストップ安'


def test_downside_incident_percent_and_signed_movers(service):
    _,clock,_=service
    crash=_move(clock,eventType='MOMENTUM_ACCELERATION',reasonJa='急加速下落 -2.4%/分(直近60秒・閾値2.5%/分)',
                downsideIncident={'changePct':-7.25})
    assert push.proposals({},[],clock[0],owner_events=[crash])[0]['title']=='監視銘柄 SOXL 急落 -7.2%'
    mover=_move(clock,eventType='MARKET_MOVER',reasonJa='SOXL 全市場急騰 +12.3%($40.1)')
    assert push.proposals({},[],clock[0],owner_events=[mover])[0]['title']=='監視銘柄 SOXL 急騰 +12.3%'


@pytest.mark.parametrize('change',[
    {'eventType':'VOLUME_ANOMALY','reasonJa':'出来高が平常の5.0倍(閾値3倍)'},
    {'eventType':'FLOW_REVERSAL','reasonJa':'大口資金が流入→流出に反転(40%→-40%)'},
    {'severity':3},
    {'sourceTimeValidated':False},
    {'symbol':'../settings'},
    {'symbol':'SOXL/x'},
    {'symbol':''},
    {'eventId':'bad id with spaces'},
])
def test_non_price_or_unsafe_moves_are_not_sent(service,change):
    _,clock,_=service
    assert push.proposals({},[],clock[0],owner_events=[_move(clock,**change)])==[]


def test_existing_subscription_schema_migrates_without_enabling_owner_changes(service):
    value,clock,sent=service
    path=value.path();import sqlite3
    with sqlite3.connect(path) as db:
        db.executescript('''CREATE TABLE subscriptions (
          id TEXT PRIMARY KEY, body TEXT NOT NULL, created REAL NOT NULL,
          enabled INTEGER NOT NULL, sq INTEGER NOT NULL, news INTEGER NOT NULL);
          CREATE TABLE deliveries (id TEXT PRIMARY KEY, subscription_id TEXT NOT NULL,
          event_key TEXT NOT NULL, payload TEXT NOT NULL, due REAL NOT NULL, expires REAL NOT NULL,
          status TEXT NOT NULL, attempted REAL, display_at TEXT, opened_at TEXT,
          UNIQUE(subscription_id,event_key));''')
    identity=subscribe(value,ownerChanges=False)
    assert value.status(identity)['ownerChanges'] is False


def test_reanalysis_does_not_refresh_old_or_unknown_intake():
    now=datetime(2026,9,13,tzinfo=timezone.utc)
    record={'eventId':'ev-old','severity':'HIGH','alertEligible':True,
            'processedAt':now.isoformat(),'staleness':'FRESH_BREAKING'}
    assert push.proposals({},[record],now.timestamp())==[]
    record['sourceReceivedAt']=(now-timedelta(days=2)).isoformat()
    assert push.proposals({},[record],now.timestamp())==[]
    record['sourceReceivedAt']=(now-timedelta(hours=2)).isoformat()
    assert len(push.proposals({},[record],now.timestamp()))==1


def _news(clock, **changes):
    stamp = datetime.fromtimestamp(clock[0], timezone.utc).isoformat()
    return {'eventId':'nie-policy', 'severity':'HIGH', 'alertEligible':True,
            'sourceReceivedAt':stamp, 'processedAt':stamp, 'sourceFamily':'NIKKEI',
            'headlineJa':'米中銀が政策金利を据え置き',
            'facts':['政策金利は据え置き', '声明は物価の高止まりを指摘'],
            'eventType':'RATES', 'sourceUrl':'https://example.org/news/policy',
            'confirmationState':'MARKET_CONFIRMATION_PENDING', **changes}


def test_news_notice_names_the_material_without_raw_mail_or_private_fields(service):
    value, clock, sent = service
    subscribe(value)
    record = _news(clock, rawBody='非公開の原メール本文', excerpt='有料記事の全文',
                  ownerSymbols=['PRIVATE'], ownerQuantity=987)
    value.tick(push.proposals({}, [record], clock[0]))
    payload = sent[0][1]
    assert payload['title'] == '米中銀が政策金利を据え置き'
    assert '物価の高止まり' in payload['body']
    assert '市場反応は未確認' in payload['body'] and '日経 ' in payload['body']
    assert payload['hash'] == '#notifications/news/nie-policy'
    text = json.dumps(payload, ensure_ascii=False)
    assert all(s not in text for s in ('非公開の原メール本文', '有料記事の全文', 'PRIVATE', '987'))
    assert 'sourceUrl' not in text and 'example.org' not in text


def test_different_news_has_different_content_and_identical_report_is_not_resent(service):
    value, clock, sent = service
    subscribe(value)
    original = _news(clock)
    value.tick(push.proposals({}, [original], clock[0]))
    # Same publisher, same URL, same complete facts: a repeated mail is not new.
    duplicate = _news(clock, eventId='nie-another-mail')
    value.tick(push.proposals({}, [duplicate], clock[0]))
    assert len(sent) == 1
    # An unchanged headline with a changed fact is a genuine separate report.
    followup = _news(clock, eventId='nie-followup', facts=['議長は追加利上げを排除せず'])
    value.tick(push.proposals({}, [followup], clock[0]))
    assert len(sent) == 2 and '追加利上げ' in sent[-1][1]['body']
    # A headline alone never proves that two reports are duplicates.
    no_url = _news(clock, eventId='nie-other-source', sourceUrl=None)
    value.tick(push.proposals({}, [no_url], clock[0]))
    assert len(sent) == 3


def test_news_rewrite_is_silent_and_severity_rise_explains_the_change(service):
    value, clock, sent = service
    subscribe(value)
    original = _news(clock)
    value.tick(push.proposals({}, [original], clock[0]))
    rewritten = {**original, 'revision':2, 'headlineJa':'米中銀、政策金利を据え置いた'}
    value.tick(push.proposals({}, [rewritten], clock[0]))
    assert len(sent) == 1
    escalated = {**rewritten, 'severity':'CRITICAL'}
    value.tick(push.proposals({}, [escalated], clock[0]))
    assert len(sent) == 2 and sent[-1][1]['title'].startswith('重要度上昇｜')
    restarted = push.PushService(path=value.path, config=value.config, now=value.now, sender=value.sender)
    restarted.tick(push.proposals({}, [original, escalated], clock[0]))
    assert len(sent) == 2


def test_measured_confirmation_after_an_hour_is_one_reasoned_update(service):
    value, clock, sent = service
    subscribe(value)
    original = _news(clock)
    value.tick(push.proposals({}, [original], clock[0]))
    clock[0] += 3700
    at = datetime.fromtimestamp(clock[0], timezone.utc).isoformat()
    confirmed = {**original, 'confirmationState':'MARKET_CONFIRMED',
                 'marketReaction':{'confirmed':True, 'measuredAfterNews':True, 'at':at}}
    value.tick(push.proposals({}, [confirmed], clock[0]))
    assert len(sent) == 2 and sent[-1][1]['title'].startswith('市場反応を確認｜')
    assert '市場反応を確認' in sent[-1][1]['body']
    value.tick(push.proposals({}, [confirmed], clock[0]))
    assert len(sent) == 2
    clock[0] += 3601
    assert push.proposals({}, [confirmed], clock[0]) == []


def test_legacy_generic_claims_are_not_replayed_by_notification_upgrade(service):
    value, clock, sent = service
    identity = subscribe(value)
    value.tick([event(clock, key='news:nie-policy:HIGH', kind='news')])
    assert len(sent) == 1
    record = _news(clock, confirmationState='MARKET_CONFIRMED',
        marketReaction={'confirmed':True, 'measuredAfterNews':True,
                        'at':datetime.fromtimestamp(clock[0], timezone.utc).isoformat()})
    value.tick(push.proposals({}, [record], clock[0]))
    assert len(sent) == 1  # Unknown old confirmation state must not trigger a replay.
    assert len(value.status(identity)['deliveries']) == 1


def test_only_unsent_generic_notice_gets_content_without_moving_its_schedule(service):
    value, clock, sent = service
    identity = subscribe(value)
    old = event(clock, key='news:nie-policy:HIGH', kind='news', due=clock[0]+10)
    value.tick([old])
    with value.db() as db:
        before = dict(db.execute('SELECT * FROM deliveries').fetchone())
    value.tick(push.proposals({}, [_news(clock)], clock[0]))
    assert not sent
    with value.db() as db:
        after = dict(db.execute('SELECT * FROM deliveries').fetchone())
    assert [before[k] for k in ('id','due','expires','status','attempted')] == [
        after[k] for k in ('id','due','expires','status','attempted')]
    assert json.loads(after['payload'])['title'] == '米中銀が政策金利を据え置き'
    clock[0] += 11
    value.tick([])
    assert len(sent) == 1 and len(value.status(identity)['deliveries']) == 1


def test_ambiguous_news_delivery_is_not_retried_with_new_wording(service):
    value, clock, sent = service
    identity = subscribe(value)
    def timeout(*args):
        raise TimeoutError()
    value.sender = timeout
    value.tick(push.proposals({}, [_news(clock)], clock[0]))
    value.sender = lambda *args: sent.append(args) or 201
    value.tick(push.proposals({}, [_news(clock, headlineJa='新しい言い回し')], clock[0]))
    assert not sent and value.status(identity)['deliveries'][0]['status'] == 'DELIVERY_UNKNOWN'


def test_news_text_is_bounded_and_pending_summary_never_copies_the_original(service):
    _, clock, _ = service
    row = push.proposals({}, [_news(clock, headlineJa='翻訳処理中', facts=[],
                        titleOriginal='PRIVATE ENGLISH MAIL')], clock[0])[0]
    assert row['title'] == '重要報道（要約待ち）'
    assert 'PRIVATE' not in json.dumps(row)
    row = push.proposals({}, [_news(clock, headlineJa='見出し\x00\u202e<b>内容</b>\n'+'長'*300,
                        facts=['短い要点\nhttps://example.org/private'])], clock[0])[0]
    assert '<b>' not in row['title'] and '\x00' not in row['title'] and '\u202e' not in row['title']
    assert len(row['title']) <= 140 and len(row['body']) <= 220
    assert 'https://' not in row['body']


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


def test_a_burst_of_news_never_pushes_a_stock_move_out():
    import argus_web_push as wp
    events = [{'kind': 'news', 'key': f'n{i}'} for i in range(30)] + [{'kind': 'owner_changes', 'key': 's1'}]
    picked = wp._per_kind(events)
    assert sum(e['kind'] == 'news' for e in picked) == 20 and picked[-1]['key'] == 's1'


def test_a_bull_and_bear_pair_sends_one_notice_per_index_move(service):
    # 2026-10-25 (owner): SOX and Nikkei 2x bull/bear are both registered; one move, one notice.
    value,clock,sent=service
    subscribe(value,ownerChanges=True)
    bear=_move(clock,eventId='US:SOXS:PRICE_CRASH:x',symbol='SOXS',eventType='PRICE_CRASH',
               reasonJa='急落 -8.10%(US_REGULAR閾値5%)')
    bull=_move(clock)
    rows=push.proposals({},[],clock[0],owner_events=[bear,bull])
    assert [r['hash'] for r in rows]==['#asset/SOXL']                 # the bull side is shown
    value.tick(rows);assert len(sent)==1
    later=push.proposals({},[],clock[0],owner_events=[bear])          # the bear arrives on its own later
    value.tick(later);assert len(sent)==1
    jp_bear=_move(clock,eventId='JP:1360:PRICE_SPIKE:x',symbol='1360',market='JP',nameJa='日経ベア2倍')
    jp_bull=_move(clock,eventId='JP:1570:PRICE_CRASH:x',symbol='1570',market='JP',eventType='PRICE_CRASH',
                  nameJa='日経レバ',reasonJa='急落 -6.00%(JP_REGULAR閾値5%)')
    rows=push.proposals({},[],clock[0],owner_events=[jp_bear,jp_bull])
    assert [r['hash'] for r in rows]==['#asset/1570'] and ':down:' in rows[0]['key']
    other=_move(clock,eventId='JP:7203:PRICE_SPIKE:x',symbol='7203',market='JP',nameJa='トヨタ自動車')
    assert len(push.proposals({},[],clock[0],owner_events=[other,jp_bull]))==2   # unrelated symbols stay separate
