from copy import deepcopy
from datetime import date, timedelta
from test_argus_web_push import service
import hashlib
import json

import argus_market_ledger as ledger
import argus_jp_fiscal_sources as sources
import argus_jp_fiscal_runtime as runtime

AT='2026-09-16T07:00:00Z'


def calendar():
    start=date(2026,9,1)
    return [{'Date':(start+timedelta(days=i)).isoformat(),
        'HolDiv':'0' if (start+timedelta(days=i)).weekday()>=5 else '1'} for i in range(30)]


class Reply:
    status_code=200
    headers={'ETag':'"edition-a"'}
    def __init__(self,content):self.content=content
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def iter_content(self,size):yield self.content


def fixture(monkeypatch):
    table=deepcopy(sources.reviewed_table()); pdf=b'%PDF-fixture-annual-table'
    table['sourceSha256']=hashlib.sha256(pdf).hexdigest()
    monkeypatch.setattr(sources,'reviewed_table',lambda:deepcopy(table))
    csv=('国債金利情報\n基準日,10年,20年,30年,40年\n'+'\n'.join(
        f'R8.9.{day},{1+i/10:.3f},{2+i/10:.3f},{3+i/10:.3f},{4+i/10:.3f}'
        for i,day in enumerate((8,9,10,11,14,15)))).encode('cp932')
    bodies={runtime.CAO_INDEX:('<a href="'+table['sourceUrl']+'">資料</a>').encode(),
        table['sourceUrl']:pdf,sources.JGB_URL:csv}
    bodies[sources.boj_fx_url(AT)] = json.dumps({'STATUS':200,'NEXTPOSITION':None,'RESULTSET':[{
        'SERIES_CODE':'FXERD04','UNIT':'Yen per U.S. Dollar','FREQUENCY':'DAILY',
        'VALUES':{'SURVEY_DATES':[20260908,20260909,20260910,20260911,20260914,20260915],
                  'VALUES':[150.0]*6}}]}).encode()
    import argus_jgb_auction as auctions
    from test_argus_jgb_auction import result_raw
    days = {10:1,20:2,30:3,40:4}
    rows = []
    for tenor,day in days.items():
        rows.append('<tr><td>9月'+str(day)+'日（火）</td><td>'+str(tenor)+'年利付国債</td>'
            '<td></td><td></td><td><a href="nyusatsu/resul202609'+f'{day:02d}'+'.htm">結果</a></td><td></td></tr>')
        bodies[auctions.ROOT+'nyusatsu/resul202609'+f'{day:02d}'+'.htm'] = result_raw(tenor).replace(
            '令和8年10月6日'.encode(),f'令和8年9月{day}日'.encode())
    bodies[auctions.ROOT+'2608.htm'] = '<h1>入札カレンダー：令和8年8月</h1>'.encode()
    bodies[auctions.ROOT+'2609.htm'] = ('<h1>入札カレンダー：令和8年9月</h1><table>'+''.join(rows)+'</table>').encode()
    real_refresh = runtime.refresh
    def fixture_refresh(*args, **kwargs):
        kwargs.setdefault('clock', lambda: kwargs['now_iso'])
        return real_refresh(*args, **kwargs)
    monkeypatch.setattr(runtime, 'refresh', fixture_refresh)
    calls=[]
    def get(url,**kwargs):
        calls.append((url,kwargs)); assert kwargs['allow_redirects'] is False
        return Reply(bodies[url])
    return get,calls,bodies,table


def test_official_publication_clock_uses_following_business_day():
    assert runtime.expected_session(calendar(),'2026-09-16T00:29:00Z')=='2026-09-14'
    assert runtime.expected_session(calendar(),'2026-09-16T00:30:00Z')=='2026-09-15'
    assert runtime.expected_session(calendar(),'2026-09-20T07:00:00Z')=='2026-09-17'
    holidays=calendar()
    next(r for r in holidays if r['Date']=='2026-09-16')['HolDiv']='0'
    assert runtime.expected_session(holidays,AT)=='2026-09-14'


def test_real_ledger_registry_roundtrip_daily_reuse_and_revision_gate(monkeypatch):
    get,calls,bodies,table=fixture(monkeypatch)
    original=ledger.empty_state(); legacy_hash=ledger.state_hash(original)
    initial=runtime.refresh(original,now_iso=AT,calendar=calendar(),get=get)
    assert initial['status']=='AVAILABLE' and initial['requests']==len(calls)==10
    assert 'fiscalMonitor' not in original and ledger.state_hash(original)==legacy_hash
    saved=ledger.normalize_state(json.loads(json.dumps(initial['state'])))
    monitor=saved['fiscalMonitor']
    assert monitor['reportStatus']=='AVAILABLE'
    assert monitor['report']['cases']['baseline']['fiscal']['values']['spreadPoints']==1.8
    assert ledger.state_hash(saved)!=legacy_hash
    assert ledger.effective_observations(saved,AT)==[]
    repeat=runtime.refresh(saved,now_iso='2026-09-16T08:00:00Z',calendar=calendar(),get=get)
    assert repeat['status']=='NOT_DUE' and repeat['requests']==0 and len(calls)==10
    # Same document URL with changed bytes is a revision, not a trusted new table.
    bodies[table['sourceUrl']]=b'%PDF-unreviewed-change'
    revised=runtime.refresh(saved,now_iso='2026-09-17T07:01:00Z',calendar=calendar(),get=get)
    m=revised['state']['fiscalMonitor']
    assert m['fiscalAcquisitionStatus']=='UNREVIEWED_SOURCE_REVISION'
    assert revised['state']['observations']==saved['observations']
    assert all(v['previousWarningRetained'] and v['notificationCandidate'] is None for v in m['report']['cases'].values())
    restored=ledger.merge_restored_state(saved,revised['state'])
    assert restored['fiscalMonitor']==m


def test_new_publication_becomes_due_before_24_hours(monkeypatch):
    get,calls,_,_=fixture(monkeypatch)
    first=runtime.refresh(ledger.empty_state(),now_iso='2026-09-16T00:20:00Z',calendar=calendar(),get=get)
    later=runtime.refresh(first['state'],now_iso='2026-09-16T00:40:00Z',calendar=calendar(),get=get)
    assert later['changed'] and later['state']['fiscalMonitor']['expectedMarketSession']=='2026-09-15'


def test_failure_preserves_observations_warning_and_retry_backoff(monkeypatch):
    get,_,_,_=fixture(monkeypatch)
    first=runtime.refresh(ledger.empty_state(),now_iso=AT,calendar=calendar(),get=get)
    def fail(*args,**kwargs):raise TimeoutError('fixture_timeout')
    failed=runtime.refresh(first['state'],now_iso='2026-09-17T07:00:01Z',calendar=calendar(),get=fail)
    m=failed['state']['fiscalMonitor']
    assert failed['status']=='INCOMPLETE' and m['marketAcquisitionStatus']=='FAILED'
    assert failed['state']['observations']==first['state']['observations']
    assert all(v['previousWarningRetained'] for v in m['report']['cases'].values())
    assert runtime.refresh(failed['state'],now_iso='2026-09-17T07:30:00Z',calendar=calendar(),get=fail)['requests']==0


def test_unknown_calendar_retains_prior_report_without_current_acceptance(monkeypatch):
    get,_,_,_=fixture(monkeypatch)
    first=runtime.refresh(ledger.empty_state(),now_iso=AT,calendar=calendar(),get=get)
    missing=runtime.refresh(first['state'],now_iso='2026-09-17T07:00:01Z',calendar=[],get=get)
    assert missing['state']['fiscalMonitor']['reportStatus']=='CALENDAR_UNAVAILABLE'
    assert missing['state']['fiscalMonitor']['report']==first['state']['fiscalMonitor']['report']


def test_public_and_llm_projection_use_saved_numbers_and_same_evidence(monkeypatch):
    get,_,_,_=fixture(monkeypatch)
    result=runtime.refresh(ledger.empty_state(),now_iso=AT,calendar=calendar(),get=get)
    state=result['state']; before=deepcopy(state)
    public=runtime.public_document(state)
    facts=runtime.explanation_facts(public)
    assert len(facts)==4 and public['selectedCase'] is None
    assert '見通し' in facts[0]['text'] and '-3.09' in facts[0]['text']
    assert all(f['verification']=='UNCONFIRMED' for f in facts)
    assert public['automaticAiCalls']==public['fetchesDuringRead']==0
    assert public['notificationDelivery']=='EXISTING_WEB_PUSH_NEWS_SETTING'
    assert state==before
    assert runtime.explanation_facts(runtime.public_document(ledger.empty_state()))==[]


def test_ledger_slice_and_llm_context_preserve_case_scope_without_receipt_churn(monkeypatch):
    get,_,_,_=fixture(monkeypatch)
    stored=runtime.refresh(ledger.empty_state(),now_iso=AT,calendar=calendar(),get=get)['state']
    stored['observations'].append({'seriesId':'unrelated.series','id':'separate','privateValue':'excluded'})
    sliced=runtime.ledger_slice(stored)
    assert all(row['seriesId']!='unrelated.series' for row in sliced['observations'])
    assert sliced['fiscalMonitor']==stored['fiscalMonitor']
    public=runtime.public_document(sliced)
    before=runtime.context_reference(public)
    assert len(before['cases'])==3 and before['selectedCase'] is None
    assert before['cases']['baseline']['currentReasons'] is not None
    assert before['interpretation']['marketYieldIsEffectiveGovernmentRate'] is False
    public['sourceVerifiedAt']='2026-09-17T07:00:00Z'
    public['calculatedAt']='2026-09-17T07:00:00Z'
    assert runtime.context_reference(public)==before
    assert len(json.dumps(before,ensure_ascii=False).encode())<32_000
    for fact in runtime.explanation_facts(public):
        provenance=fact['provenance']
        assert provenance['scope']=='published_metadata_snapshot'
        assert {'publishedAt','receivedAt','observedAt','revision','url','sourceLabel'} <= set(provenance)
        assert provenance['publishedAt'] is None


def test_existing_collector_merges_and_retries_save_without_duplicate_fetch(monkeypatch):
    import scanner
    from datetime import datetime
    import threading
    get,calls,_,_=fixture(monkeypatch)
    seed=ledger.empty_state()
    seed['observations']=[{'id':'unrelated-row','seriesId':'unrelated.series','periodEnd':'2026-09-15'}]
    monkeypatch.setattr(scanner,'_MARKET_LEDGER',seed)
    monkeypatch.setattr(scanner,'_JP_FISCAL_REFRESH_LOCK',threading.Lock())
    monkeypatch.setattr(scanner,'_JP_FISCAL_REFRESH_STATE',{'pendingPersistence':False})
    monkeypatch.setattr(scanner,'_DURABLE_CHECKPOINT_LOCK',threading.RLock())
    monkeypatch.setattr(scanner,'_ai_now_iso',lambda:AT)
    monkeypatch.setattr(scanner.requests,'get',get)
    monkeypatch.setattr(scanner,'_journal',lambda *a,**k:None)
    class Clock:
        @staticmethod
        def now(tz):return datetime.fromisoformat(AT.replace('Z','+00:00')).astimezone(tz)
    monkeypatch.setattr(scanner,'datetime',Clock)
    work=[]
    class Thread:
        def __init__(self,*,target,**kwargs):self.target=target
        def start(self):work.append(self.target)
    monkeypatch.setattr(scanner.threading,'Thread',Thread)
    checkpoints=iter([{'verified':True,'readBackVerified':False},
                      {'verified':True,'readBackVerified':True}])
    monkeypatch.setattr(scanner,'_osint_persist',lambda:next(checkpoints))
    assert scanner._jp_fiscal_environment_warm()=={'status':'ACCEPTED','completed':False}
    assert scanner._jp_fiscal_environment_warm()['status']=='ALREADY_RUNNING'
    assert len(calls)==0
    work.pop()()
    assert len(calls)==10
    assert any(row['id']=='unrelated-row' for row in scanner._MARKET_LEDGER['observations'])
    assert scanner._JP_FISCAL_REFRESH_STATE['persistenceStatus']=='UNVERIFIED'
    # A failed read-back is retried through the same checkpoint without refetch.
    scanner._jp_fiscal_environment_warm(); work.pop()()
    assert len(calls)==10
    assert scanner._JP_FISCAL_REFRESH_STATE['persistenceStatus']=='VERIFIED'
    assert not scanner._JP_FISCAL_REFRESH_STATE['pendingPersistence']
    with scanner.app.test_request_context('/api/argus/jp-fiscal-environment'):
        document=scanner.api_argus_jp_fiscal_environment().get_json()
    assert document['id']==scanner._JP_FISCAL_REFRESH_STATE['verifiedReportId']
    assert document['fetchesDuringRead']==0 and len(calls)==10
    scanner._jp_fiscal_environment_warm(); work.pop()()
    assert scanner._JP_FISCAL_REFRESH_STATE['status']=='NOT_DUE' and len(calls)==10


def test_unified_context_and_existing_history_hold_same_fiscal_snapshot(monkeypatch,tmp_path):
    import argus_market_brief as brief
    import argus_analysis_history as history
    get,_,_,_=fixture(monkeypatch)
    state=runtime.refresh(ledger.empty_state(),now_iso=AT,calendar=calendar(),get=get)['state']
    public=runtime.public_document(state)
    item=brief.compose_brief(now_iso=AT)
    item['fiscalEnvironment']=runtime.context_reference(public)
    item['facts'].extend(runtime.explanation_facts(public))
    context=brief.unified_context(item)
    assert context['fiscalEnvironment']==item['fiscalEnvironment']
    ref=next(row['evidenceId'] for row in context['facts'] if row['source']=='jp_fiscal_environment')
    response={key:{'textJa':'金利と財政収支の変化を分けて確認します。',
        'evidenceIds':[ref],'kind':'INFERENCE'} for key in brief.UNIFIED_SECTIONS}
    for key in ('changes','impact'):
        response[key]={'textJa':'未確認です。','evidenceIds':[],'kind':'UNKNOWN'}
    item.update(unifiedContext=context,unifiedSummary=brief.validate_unified_ai(response,context),
        unifiedStatus='GENERATED',aiDiagnostics={'completedAt':AT})
    record=history.make_record(item,{})
    path=tmp_path/'history.sqlite3';history.initialize(path);history.append(path,record)
    item['fiscalEnvironment']['cases']['baseline']['fiscal']['values']['growthPct']=999
    restored=history.read_record(path,record['recordId'])
    assert restored['brief']['fiscalEnvironment']['cases']['baseline']['fiscal']['values']['growthPct']==3.0
    assert restored['brief']['unifiedContext']['fiscalEnvironment']['id']==public['id']


def test_owner_dialogue_preserves_same_fiscal_reference_and_scope(monkeypatch):
    import argus_market_brief as brief
    import argus_owner_dialogue as dialogue
    get,_,_,_=fixture(monkeypatch)
    state=runtime.refresh(ledger.empty_state(),now_iso=AT,calendar=calendar(),get=get)['state']
    document=runtime.public_document(state)
    market={'facts':runtime.explanation_facts(document),
        'fiscalEnvironment':runtime.context_reference(document)}
    market['unifiedContext']=brief.unified_context(market)
    before=deepcopy(market)
    for symbol in ('N225','7203'):
        context=dialogue.build_context(brief=market,symbol=symbol,market='JP',horizon=5,
            question='金利の変化をどう考える？',received_at=AT)
        reference=context['fiscalEnvironment']
        assert reference['id']==document['id']
        assert reference['cases']==market['fiscalEnvironment']['cases']
        assert reference['applicability']=='JAPAN_MACRO_CONTEXT_ONLY'
        assert dialogue.reasoning_context(context)['fiscalEnvironment']==reference
        assert not context['officialPredictionMutation'] and not reference['actionAuthority']
    us=dialogue.build_context(brief=market,symbol='SPY',market='US',horizon=5,
        question='金利の影響は？',received_at=AT)
    assert 'fiscalEnvironment' not in us
    assert market==before


def test_fiscal_push_packet_survives_poll_restore_and_failed_source(monkeypatch):
    from argus_jp_fiscal_monitor import instant
    get,_,_,_=fixture(monkeypatch)
    initial=runtime.refresh(ledger.empty_state(),now_iso=AT,calendar=calendar(),get=get)['state']
    packet=initial['fiscalMonitor']['notification']
    assert len(packet['cases'])==3
    now=instant(AT).timestamp()
    proposals=runtime.notification_proposals(initial,now=now)
    assert len(proposals)==1 and proposals[0]['key'].startswith('news:fiscal:')
    restored=ledger.normalize_state(json.loads(json.dumps(initial)))
    assert runtime.notification_proposals(restored,now=now+180)==proposals
    repeat=runtime.refresh(restored,now_iso='2026-09-16T08:00:00Z',calendar=calendar(),get=get)['state']
    assert repeat['fiscalMonitor']['notification']==packet
    def fail(*a,**k):raise TimeoutError()
    failed=runtime.refresh(restored,now_iso='2026-09-17T07:00:01Z',calendar=calendar(),get=fail)['state']
    assert failed['fiscalMonitor']['notification']==packet
    assert runtime.notification_proposals(failed,now=now+86401)==[]
    assert runtime.notification_proposals(initial,now=now-1)==[]


def test_fiscal_push_reuses_opt_in_and_durable_unique_delivery(service,monkeypatch):
    from test_argus_web_push import subscribe, sub
    from argus_jp_fiscal_monitor import instant
    value,clock,sent=service
    get,_,_,_=fixture(monkeypatch)
    state=runtime.refresh(ledger.empty_state(),now_iso=AT,calendar=calendar(),get=get)['state']
    clock[0]=instant(AT).timestamp()
    identity=subscribe(value,news=False)
    events=runtime.notification_proposals(state,now=clock[0])
    value.tick(events);assert not sent
    subscribe(value,news=True)
    value.tick(events);value.tick(events)
    assert len(sent)==1
    assert value.status(identity)['deliveries'][0]['status']=='SERVICE_ACCEPTED'
    assert value.status(identity)['deliveries'][0]['display_at'] is None
    # Opening the existing durable service again must not resend this event.
    import argus_web_push
    reloaded=argus_web_push.PushService(path=value.path,config=value.config,now=value.now,sender=value.sender)
    reloaded.tick(events);assert len(sent)==1



def test_fx_connection_survives_checkpoint_and_failed_or_late_update(monkeypatch):
    get, calls, bodies, _ = fixture(monkeypatch)
    first = runtime.refresh(ledger.empty_state(), now_iso=AT, calendar=calendar(), get=get)
    stored = ledger.normalize_state(json.loads(json.dumps(first['state'])))
    assert stored['fiscalMonitor']['fxAcquisitionStatus'] == 'AVAILABLE'
    view = stored['fiscalMonitor']['report']['cases']['baseline']['market']['series']['fx.usdjpy']
    assert view['status'] == 'AVAILABLE' and view['latestValue'] == 150.
    original = deepcopy(stored['observations'])
    def broken_fx(url, **kwargs):
        if url.startswith(sources.BOJ_FX_SOURCE): raise TimeoutError('fixture_fx')
        return get(url, **kwargs)
    failure = runtime.refresh(stored, now_iso='2026-09-17T07:00:01Z', calendar=calendar(), get=broken_fx)
    monitor = failure['state']['fiscalMonitor']
    assert monitor['fxAcquisitionStatus'] == 'FAILED' and monitor['acquisitionStatus'] == 'INCOMPLETE'
    assert failure['state']['observations'] == original
    assert all(case['previousWarningRetained'] for case in monitor['report']['cases'].values())
    delayed = runtime.refresh(stored, now_iso='2026-09-17T07:00:01Z', calendar=calendar(), get=get)
    monitor = delayed['state']['fiscalMonitor']
    assert monitor['fxAcquisitionStatus'] == 'UPDATE_WAIT'
    assert monitor['fxLatestSession'] == '2026-09-15'
    assert monitor['report']['cases']['baseline']['market']['groups']['FX']['status'] == 'UPDATE_DUE'
    assert all(case['previousWarningRetained'] for case in monitor['report']['cases'].values())


def test_fx_projection_reports_its_acquisition_and_own_source(monkeypatch):
    get,_,_,_=fixture(monkeypatch)
    state=runtime.refresh(ledger.empty_state(),now_iso=AT,calendar=calendar(),get=get)['state']
    doc=runtime.public_document(state)
    assert doc['fxAcquisitionStatus']=='AVAILABLE' and doc['lastFxSuccessAt']==AT
    doc['market']['adverseGroups']=['JGB','FX']
    facts=runtime.explanation_facts(doc)
    fx=next(f for f in facts if f['provenance']['eventId'].endswith(':FX'))
    jgb=next(f for f in facts if f['provenance']['eventId'].endswith(':JGB'))
    assert fx['provenance']['url']==sources.BOJ_FX_SOURCE
    assert '17時' in fx['provenance']['sourceLabel']
    assert jgb['provenance']['url']==sources.JGB_URL
    assert runtime.context_reference(doc)['fxAcquisitionStatus']=='AVAILABLE'


def test_auction_receipt_is_completion_not_start_and_read_uses_saved_snapshot(monkeypatch):
    from datetime import datetime, timedelta
    import argus_jgb_auction as auctions
    get, calls, _, _ = fixture(monkeypatch)
    start = datetime.fromisoformat(AT.replace('Z','+00:00'))
    ticks = iter((start+timedelta(seconds=i)).isoformat() for i in range(1,8))
    result = runtime.refresh(ledger.empty_state(), now_iso=AT, calendar=calendar(), get=get, clock=lambda:next(ticks))
    state = ledger.normalize_state(json.loads(json.dumps(result['state'])))
    saved = auctions.saved_rows(state, as_of=state['fiscalMonitor']['updatedAt'])
    assert len(saved) == 4
    assert [row['knownAt'] for row in saved] == [(start+timedelta(seconds=i)).isoformat() for i in range(3,7)]
    assert auctions.saved_rows(state, as_of=AT) == []
    before = deepcopy(state); count = len(calls)
    document = runtime.public_document(state)
    reference = runtime.context_reference(document)
    assert reference['auctions'] == document['auctions'] == state['fiscalMonitor']['auctionReport']
    assert state == before and len(calls) == count
    assert reference['market'].get('auctionStatus') is None
    assert document['market']['warningLevel'] == state['fiscalMonitor']['report']['cases']['baseline']['market']['warningLevel']
    assert document['auctions']['predictivePerformance'] == 'UNVALIDATED'
    assert not document['auctions']['actionAuthority']


def test_pending_auction_retries_hourly_keeps_prior_result_and_does_not_guess(monkeypatch):
    import argus_jgb_auction as auctions
    get, calls, bodies, _ = fixture(monkeypatch)
    first = runtime.refresh(ledger.empty_state(), now_iso=AT, calendar=calendar(), get=get)['state']
    bodies[auctions.ROOT+'2609.htm'] += ('<table><tr><td>9月16日（水）</td><td>10年利付国債</td>'
        '<td></td><td></td><td>入札結果</td><td></td></tr></table>').encode()
    pending = runtime.refresh(first, now_iso='2026-09-17T07:00:01Z', calendar=calendar(), get=get)
    m = pending['state']['fiscalMonitor']
    assert m['auctionAcquisitionStatus'] == 'UPDATE_WAIT'
    view = m['auctionReport']['series']['10']
    assert view['status'] == 'UPDATE_WAIT' and view['latestResult']['sessionDate'] == '2026-09-01'
    assert not any(url.endswith('resul20260916.htm') for url, _ in calls)
    assert runtime.refresh(pending['state'], now_iso='2026-09-17T07:30:01Z', calendar=calendar(), get=get)['requests'] == 0
    retry = runtime.refresh(pending['state'], now_iso='2026-09-17T08:00:01Z', calendar=calendar(), get=get)
    assert retry['requests'] == 9
    assert retry['state']['observations'] == pending['state']['observations']


def test_auction_failure_is_separate_from_fiscal_warning_and_shared_restore(monkeypatch):
    import argus_jgb_auction as auctions
    get, _, _, _ = fixture(monkeypatch)
    initial = runtime.refresh(ledger.empty_state(), now_iso=AT, calendar=calendar(), get=get)['state']
    def broken(url, **kwargs):
        if url.startswith(auctions.ROOT): raise TimeoutError('synthetic')
        return get(url, **kwargs)
    failed = runtime.refresh(initial, now_iso='2026-09-16T08:01:00Z', calendar=calendar(), get=broken)
    # Not due on a healthy day; make the existing official publication become due next day.
    assert failed['status'] == 'NOT_DUE'
    comparable = runtime.refresh(initial, now_iso='2026-09-17T07:01:00Z', calendar=calendar(), get=get)['state']
    failed = runtime.refresh(initial, now_iso='2026-09-17T07:01:00Z', calendar=calendar(), get=broken)['state']
    restored = ledger.merge_restored_state(initial, failed)
    assert restored['fiscalMonitor']['auctionAcquisitionStatus'] == 'FAILED'
    assert len(auctions.saved_rows(restored, as_of='2026-09-17T07:01:00Z')) == 4
    for case, row in restored['fiscalMonitor']['report']['cases'].items():
        assert row['currentReasons'] == comparable['fiscalMonitor']['report']['cases'][case]['currentReasons']
        assert row['fiscal']['values'] == comparable['fiscalMonitor']['report']['cases'][case]['fiscal']['values']
        assert row['warningLevel'] == comparable['fiscalMonitor']['report']['cases'][case]['warningLevel']
        assert row['releaseConditions'] == comparable['fiscalMonitor']['report']['cases'][case]['releaseConditions']
    assert restored['fiscalMonitor']['notification'] == initial['fiscalMonitor']['notification']
