import copy
from concurrent.futures import ThreadPoolExecutor
import json
import threading
import time
import uuid
from flask import Flask
import pytest
import argus_owner_dialogue_api as api
import argus_owner_dialogue_store as store
from test_argus_owner_dialogue import market_brief, context, answer, AT


def identity(): return str(uuid.uuid4())


@pytest.mark.parametrize('corrected', [True, False])
def test_invalid_numeric_answer_gets_one_correction_with_fixed_evidence(corrected):
    c=context(); before=copy.deepcopy(c); calls=[]
    invalid=answer()
    invalid['reasons']={'textJa':'利益は999です。','kind':'INFERENCE',
        'evidenceIds':[c['facts'][0]['evidenceId']]}
    def generate(user, **kwargs):
        calls.append(user)
        kwargs['diagnostic'].update(returnedModel='test-primary',estUsd=.25)
        return answer() if corrected and len(calls)==2 else copy.deepcopy(invalid)
    result=api.generate_answer(c,generate)
    assert len(calls)==2 and c==before
    assert api.dialogue.generation_prompt(c)[0] in calls[1]
    assert 'unsupported_numeric_tokens' in calls[1]
    assert result['provider']['totalEstUsd']==.5
    assert len(result['provider']['attempts'])==2
    assert result['provider']['attempts'][0]['validation']['status']=='REJECTED'
    assert result['status']==('SUCCEEDED' if corrected else 'REJECTED')
    assert bool(result['answer']) is corrected


def test_unavailable_provider_does_not_create_a_correction_loop():
    calls=[]
    def generate(user, **kwargs):
        calls.append(user);kwargs['diagnostic']['errorCode']='insufficient_quota'
        return None
    result=api.generate_answer(context(),generate)
    assert result['status']=='UNAVAILABLE' and len(calls)==1


def test_owner_short_references_restore_before_validation_and_keep_saved_context():
    from argus_presentation_intent import dialogue_inventory
    c=context();before=copy.deepcopy(c)
    full=api.dialogue.reasoning_context(c);catalog=dialogue_inventory(c)
    short,short_catalog,restore,compact=api.dialogue.argus_explanation_contract.prompt_references(full,catalog)
    assert restore(short)==full and restore(short_catalog)==catalog
    assert len(json.dumps(short))+len(json.dumps(short_catalog))<len(json.dumps(full))+len(json.dumps(catalog))
    f=c['facts'][0];v=answer()
    v['reasons']={'textJa':f['text'],'kind':'INFERENCE','evidenceIds':[f['evidenceId']]}
    calls=[]
    def generate(user,**kwargs):
        calls.append(user)
        assert f['evidenceId'] not in user
        return compact(v)
    result=api.generate_answer(c,generate)
    assert result['status']=='SUCCEEDED' and len(calls)==1 and c==before
    assert result['answer']['sections']['reasons']['evidenceIds']==[f['evidenceId']]
    assert restore({'textJa':'ref-0'})=={'textJa':'ref-0'}


def test_owner_unknown_alias_never_becomes_an_accepted_reference():
    c=context();v=answer();v['reasons']={'textJa':'確認します。','kind':'INFERENCE','evidenceIds':['ref-999999']}
    calls=[]
    result=api.generate_answer(c,lambda *args,**kwargs:(calls.append(args[0]),copy.deepcopy(v))[1])
    assert len(calls)==2 and result['status']=='REJECTED'
    assert result['validation']['reason']=='unknown_evidence_reference'


@pytest.mark.parametrize('field', ['length', 'references'])
@pytest.mark.parametrize('corrected', [True, False])
def test_structural_correction_keeps_limits_and_one_retry(field, corrected):
    c=context(); before=copy.deepcopy(c); calls=[]
    invalid=answer()
    if field == 'length':
        invalid['next']['textJa']='次の変化を確認します。'*30
    else:
        invalid['next']['evidenceIds']=[c['facts'][0]['evidenceId']]*7
    def generate(user, **kwargs):
        calls.append(user); kwargs['diagnostic']['estUsd']=.1
        return answer() if corrected and len(calls)==2 else copy.deepcopy(invalid)
    result=api.generate_answer(c,generate)
    assert len(calls)==2 and c==before
    diagnostic=result['provider']['attempts'][0]['validation']
    assert diagnostic['reason']=='section_field_invalid' and diagnostic['section']=='next'
    assert diagnostic['fieldIssues']['textLimit']==240
    assert diagnostic['fieldIssues']['referenceLimit']==6
    assert 'fieldIssues' in calls[1] and '最大6件' in calls[1]
    assert result['status']==('SUCCEEDED' if corrected else 'REJECTED')
    assert bool(result['answer']) is corrected
    assert result['provider']['totalEstUsd']==.2


def test_store_append_read_and_restart_never_reexecutes(tmp_path):
    path=tmp_path/'owner.sqlite3'
    assert store.history(path,'boot')['items']==[] and not path.exists()
    store.initialize(path); first=identity(); c=context()
    assert store.submit(path,identity=first,input_hash='a',boot_id='boot',context=c)
    assert not store.submit(path,identity=first,input_hash='a',boot_id='boot',context=c)
    with pytest.raises(ValueError,match='conflict'):store.submit(path,identity=first,input_hash='b',boot_id='boot',context=c)
    assert store.read(path,first,'next')['status']=='INTERRUPTED'
    value={'status':'SUCCEEDED','answer':{'text':'保存した説明'},'completedAt':AT}
    store.complete(path,first,value);store.complete(path,first,value)
    with pytest.raises(ValueError,match='conflict'):store.complete(path,first,{**value,'status':'FAILED'})
    assert store.read(path,first,'next')['result']['answer']==value['answer']
    assert path.stat().st_mode&0o777==0o600


def test_single_inflight_claim_is_atomic(tmp_path):
    path=tmp_path/'owner.sqlite3'; store.initialize(path)
    def claim(_):
        try:return store.submit(path,identity=identity(),input_hash='a',boot_id='same',context=context())
        except ValueError as exc:return str(exc)
    with ThreadPoolExecutor(max_workers=5) as pool:results=list(pool.map(claim,range(5)))
    assert results.count(True)==1 and results.count('dialogue_busy')==4


def test_corrupt_or_symlinked_storage_rejected(tmp_path):
    path=tmp_path/'owner.sqlite3';store.initialize(path); rid=identity()
    store.submit(path,identity=rid,input_hash='a',boot_id='boot',context=context())
    db=store.connect(path);db.execute('UPDATE requests SET body=?', ('{}',));db.close()
    with pytest.raises(ValueError,match='integrity'):store.read(path,rid,'boot')
    link=tmp_path/'link';link.symlink_to(path)
    with pytest.raises(ValueError,match='regular_file'):store.initialize(link)


@pytest.fixture
def service(tmp_path):
    app=Flask(__name__);path=tmp_path/'owner.sqlite3'; entered=threading.Event();release=threading.Event();calls=[];brief=market_brief()
    def authorize(token):return (True,None,200) if token=='test-owner' else (False,{'error':'unauthorized'},401)
    def generate(user,**kw):
        calls.append(kw);entered.set();release.wait(5);return answer()
    api.register(app,authorize=authorize,storage_path=lambda:str(path),market_brief=lambda:brief,generate=generate,now=lambda:AT)
    yield app,path,entered,release,calls,brief
    release.set()


def payload(brief,**patch):return {'action':'ask','ownerToken':'test-owner','requestId':identity(),'baseContextId':brief['unifiedContext']['contextId'],'symbol':'5803','market':'JP','horizon':5,'question':'どう見ている？',**patch}


def test_route_auth_idempotence_nonblocking_reads_and_frozen_context(service):
    app,path,entered,release,calls,brief=service;client=app.test_client();body=payload(brief);before=copy.deepcopy(brief)
    assert client.post('/api/argus/owner-dialogue',json={**body,'ownerToken':'wrong'}).status_code==401
    assert not path.exists()
    first=client.post('/api/argus/owner-dialogue',json=body);assert first.status_code==202
    assert first.headers['Cache-Control']=='private, no-store' and entered.wait(2)
    repeated=client.post('/api/argus/owner-dialogue',json=body);assert repeated.status_code==200
    assert client.post('/api/argus/owner-dialogue',json={**body,'question':'変更'}).status_code==409
    assert client.post('/api/argus/owner-dialogue',json=payload(brief)).status_code==409
    rows=client.post('/api/argus/owner-dialogue',json={'action':'history','ownerToken':'test-owner'}).json['items']
    assert len(rows)==1 and rows[0]['status']=='RUNNING' and len(calls)==1
    release.set()
    for _ in range(100):
        got=client.post('/api/argus/owner-dialogue',json={'action':'status','ownerToken':'test-owner','requestId':body['requestId']}).json
        if got['status']!='RUNNING':break
        time.sleep(.01)
    assert got['status']=='SUCCEEDED' and got['result']['answer']['scope']=='OWNER_PRIVATE'
    assert got['context']['baseMarketContextId']==body['baseContextId'] and brief==before
    assert calls[0]['purpose']=='owner_dialogue' and calls[0]['max_out']==3000
    assert 'test-owner' not in path.read_bytes().decode('utf-8',errors='ignore')


def test_saved_subject_overview_advances_after_context_change_with_browser_closed(tmp_path):
    import argus_market_brief
    app=Flask(__name__);path=tmp_path/'owner.sqlite3';brief=[market_brief()];calls=[]
    def generate(user,**kw):calls.append(user);return answer()
    controls=api.register(app,authorize=lambda token:(True,None,200),storage_path=lambda:str(path),
        market_brief=lambda:brief[0],generate=generate,now=lambda:AT)
    client=app.test_client();body={'action':'overview','ownerToken':'test-owner',
        'baseContextId':brief[0]['unifiedContext']['contextId'],'symbol':'5803','market':'JP',
        'horizon':5,'owner':{'symbol':'5803','market':'JP','state':'HELD','quantity':100,
            'averageCost':5000,'purchaseReason':'需要を確認','holdingPeriod':'数か月','reportedAt':AT}}
    first=client.post('/api/argus/owner-dialogue',json=body).json
    for _ in range(100):
        saved=store.read(path,first['requestId'],controls['bootId'])
        if saved and saved['status']=='SUCCEEDED':break
        time.sleep(.01)
    changed=copy.deepcopy(brief[0]);changed['facts'][0]['text']='日経平均・1営業日先の参考値101。'
    changed['unifiedContext']=argus_market_brief.unified_context(changed);brief[0]=changed
    assert controls['refreshSubjectOverviews']()['status']=='STARTED'
    for _ in range(100):
        rows=store.history(path,controls['bootId'])['items']
        if len(rows)==2 and rows[0]['status']=='SUCCEEDED':break
        time.sleep(.01)
    assert len(rows)==2 and len(calls)==2
    latest=rows[0]
    assert latest['context']['baseMarketContextId']==changed['unifiedContext']['contextId']
    assert latest['context']['previousView']['requestId']==first['requestId']
    assert latest['context']['owner']['purchaseReason']=='需要を確認'
    assert controls['refreshSubjectOverviews']()['status']=='CURRENT'


def test_stale_context_and_injected_market_fields_never_call_ai(service):
    app,path,entered,release,calls,brief=service;client=app.test_client()
    assert client.post('/api/argus/owner-dialogue',json=payload(brief,baseContextId='a'*64)).status_code==409
    assert client.post('/api/argus/owner-dialogue',json=payload(brief,eps_input={'value':3000})).status_code==400
    assert not calls and not path.exists()
    assert client.post('/api/argus/owner-dialogue',data=b'x'*32769).status_code==413


def test_save_failure_retry_never_repeats_paid_request(service, monkeypatch):
    app,path,entered,release,calls,brief=service;client=app.test_client();body=payload(brief)
    original=store.complete
    monkeypatch.setattr(store,'complete',lambda *a,**kw:(_ for _ in ()).throw(OSError('disk unavailable')))
    assert client.post('/api/argus/owner-dialogue',json=body).status_code==202
    assert entered.wait(2);release.set()
    for _ in range(100):
        got=client.post('/api/argus/owner-dialogue',json={'action':'status','ownerToken':'test-owner','requestId':body['requestId']}).json
        if got['status']=='SAVE_FAILED':break
        time.sleep(.01)
    assert got['status']=='SAVE_FAILED' and got['result']['answer']
    monkeypatch.setattr(store,'complete',original)
    saved=client.post('/api/argus/owner-dialogue',json={'action':'save','ownerToken':'test-owner','requestId':body['requestId']}).json
    assert saved['status']=='SUCCEEDED' and len(calls)==1


def test_owner_sdk_has_one_bounded_attempt_and_usage(monkeypatch):
    import scanner
    from types import SimpleNamespace
    calls=[];recorded=[]
    def create(**kwargs):calls.append(kwargs);return SimpleNamespace(output_text='{}')
    client=SimpleNamespace(responses=SimpleNamespace(create=create))
    monkeypatch.setattr(scanner,'_ai_usage_provider_call',lambda provider,purpose,model,invoke,**kw:(recorded.append((provider,purpose,model)),invoke())[1])
    scanner._openai_prose_call(client,'test-primary','system','question',purpose='owner_dialogue')
    assert len(calls)==1 and calls[0]['max_output_tokens']==3000 and calls[0]['store'] is False
    assert recorded==[('openai','owner_dialogue','test-primary')]


def test_question_about_displayed_saved_edition_keeps_exact_inputs_and_no_current_fetch(tmp_path,monkeypatch):
    import argus_analysis_history as history
    from test_argus_analysis_history import brief as public_brief
    frozen=public_brief(); history_path=tmp_path/'market.sqlite'
    history.initialize(history_path)
    record=history.make_record(frozen,{'5':{'epsInput':3000}});history.append(history_path,record)
    original=history_path.read_bytes();current=market_brief();calls=[];done=threading.Event()
    def generate(user,**kw):calls.append(user);done.set();return None
    def forbidden(**kw):pytest.fail('frozen edition must not mix current materials or prices')
    app=Flask(__name__);path=tmp_path/'owner.sqlite'
    api.register(app,authorize=lambda token:(token=='test-owner',{'error':'unauthorized'},401),
        storage_path=lambda:str(path),market_brief=lambda:current,generate=generate,now=lambda:AT,
        market_reference=lambda rid:history.read_record(history_path,rid),
        subject_comparison=forbidden,subject_materials=forbidden)
    client=app.test_client();body=payload(frozen,symbol='N225',referenceRecordId=record['recordId'])
    assert client.post('/api/argus/owner-dialogue',json={**body,'ownerToken':'wrong'}).status_code==401
    assert not calls and not path.exists()
    result=client.post('/api/argus/owner-dialogue',json=body)
    assert result.status_code==202 and done.wait(2)
    context=result.json['context']
    assert context['baseMarketContextId']==frozen['unifiedContext']['contextId']
    assert context['baseMarketContextId']!=current['unifiedContext']['contextId']
    assert context['referenceEdition']=={'recordId':record['recordId'],'recordedAt':record['recordedAt'],'isCurrentMarketAnalysis':False}
    assert any(f['source']=='saved_market_edition' and record['recordedAt'] in f['text'] for f in context['facts'])
    assert frozen['unifiedContext']['facts'][0]['text'] in calls[0]
    assert history_path.read_bytes()==original
    assert client.post('/api/argus/owner-dialogue',json=body).status_code==200
    assert len(calls)==1


@pytest.mark.parametrize('fault',['missing','wrong_id','wrong_context','private','overview','wrong_subject','future'])
def test_saved_edition_reference_cannot_supply_or_substitute_unverified_context(tmp_path,fault):
    import argus_analysis_history as history
    from test_argus_analysis_history import brief as public_brief
    frozen=public_brief();record=history.make_record(frozen,{})
    body=payload(frozen,symbol='N225',referenceRecordId=record['recordId']);calls=[]
    selected=copy.deepcopy(record)
    if fault=='future':
        selected=history.make_record(public_brief('2026-09-14T00:00:00Z'),{})
        body.update(referenceRecordId=selected['recordId'],baseContextId=selected['brief']['unifiedContext']['contextId'])
    if fault=='missing':selected=None
    if fault=='wrong_id':body['referenceRecordId']='f'*64
    if fault=='wrong_context':body['baseContextId']='f'*64
    if fault=='private':selected['scope']='OWNER_PRIVATE'
    if fault=='overview':body['action']='overview'
    if fault=='wrong_subject':body['symbol']='5803'
    app=Flask(__name__);path=tmp_path/'owner.sqlite'
    api.register(app,authorize=lambda token:(True,None,200),storage_path=lambda:str(path),
        market_brief=market_brief,generate=lambda *a,**kw:calls.append(kw),now=lambda:AT,
        market_reference=lambda rid:selected)
    response=app.test_client().post('/api/argus/owner-dialogue',json=body)
    assert response.status_code in (400,409) and not calls and not path.exists()


def test_overview_reuse_tracks_relevant_inputs_and_keeps_saved_editions(tmp_path):
    import argus_market_brief
    import argus_owner_dialogue as dialogue
    path=tmp_path/'owner.sqlite3';brief=[market_brief()];calls=[];materials=[[]]
    clock=[AT];policy={'model':'test-primary','ruleVersion':'test-contract-v1'}
    def setup():
        app=Flask(__name__)
        controls=api.register(app,authorize=lambda token:(token=='test-owner',{'error':'unauthorized'},401),
            storage_path=lambda:str(path),market_brief=lambda:brief[0],
            generate=lambda user,**kw:(calls.append(user),answer())[1],now=lambda:clock[0],
            subject_materials=lambda **kw:copy.deepcopy(materials[0]),generation_policy=lambda:copy.deepcopy(policy))
        return app.test_client(),controls
    client,controls=setup()
    body={'action':'overview','ownerToken':'test-owner','baseContextId':brief[0]['unifiedContext']['contextId'],
        'symbol':'5803','market':'JP','horizon':5,
        'owner':{'symbol':'5803','market':'JP','state':'HELD','quantity':100,'reportedAt':AT}}
    def saved(value):
        for _ in range(100):
            row=store.read(path,value['requestId'],controls['bootId'])
            if row and row['status']!='RUNNING':return row
            time.sleep(.01)
        pytest.fail('overview worker did not complete')
    first=saved(client.post('/api/argus/owner-dialogue',json=body).json)
    before=copy.deepcopy(first)
    clock[0]='2026-09-13T00:10:00Z'
    # The common market changes only in another requested period.
    brief[0]['facts'][0]['text']='日経平均・1営業日先の参考値101。'
    brief[0]['unifiedContext']=argus_market_brief.unified_context(brief[0])
    body['baseContextId']=brief[0]['unifiedContext']['contextId']
    reused=client.post('/api/argus/owner-dialogue',json=body)
    assert reused.status_code==200 and len(calls)==1
    assert reused.json['requestId']==first['requestId']
    assert reused.json['overviewReuse']['checkedAt']==clock[0]
    assert reused.json['overviewReuse']['originalCompletedAt']==AT
    assert reused.json['context']==first['context'] and reused.json['result']==first['result']
    assert controls['refreshSubjectOverviews']()['status']=='CURRENT' and len(calls)==1
    # Restart preserves reuse without modifying the old saved record.
    client,controls=setup()
    assert client.post('/api/argus/owner-dialogue',json=body).json['requestId']==first['requestId']
    assert store.read(path,first['requestId'],controls['bootId'])['context']==before['context']
    assert len(calls)==1
    # A new company material must be collected even with an unchanged common ID.
    materials[0]=[dialogue.fact('企業の公式発表を確認中です。','company_material',kind='UNKNOWN')]
    assert controls['refreshSubjectOverviews']()['status']=='STARTED'
    rows=store.history(path,controls['bootId'])['items'];second=saved(rows[0])
    assert second['context']['baseMarketContextId']==body['baseContextId']
    assert second['context']['previousView']['requestId']==first['requestId'] and len(calls)==2
    assert client.post('/api/argus/owner-dialogue',json=body).json['requestId']==second['requestId']
    # A -> B -> A produces a new immutable edition, rather than relabelling old A.
    materials[0]=[]
    third=saved(client.post('/api/argus/owner-dialogue',json=body).json)
    assert third['requestId'] not in (first['requestId'],second['requestId']) and len(calls)==3
    assert third['context']['previousView']['requestId']==second['requestId']
    policy['model']='test-next-primary'
    fourth=saved(client.post('/api/argus/owner-dialogue',json=body).json)
    assert fourth['requestId']!=third['requestId'] and len(calls)==4
    policy['ruleVersion']='test-contract-v2'
    fifth=saved(client.post('/api/argus/owner-dialogue',json=body).json)
    assert fifth['requestId']!=fourth['requestId'] and len(calls)==5
    body['owner']['quantity']=200
    sixth=saved(client.post('/api/argus/owner-dialogue',json=body).json)
    assert sixth['context']['owner']['quantity']==200 and len(calls)==6
    clock[0]='2026-09-13T01:00:00Z'
    seventh=saved(client.post('/api/argus/owner-dialogue',json=body).json)
    assert seventh['requestId']!=sixth['requestId'] and len(calls)==7
    assert len(store.history(path,controls['bootId'])['items'])==7
    assert store.read(path,first['requestId'],controls['bootId'])['result']==before['result']
    assert client.post('/api/argus/owner-dialogue',json={**body,'ownerToken':'wrong'}).status_code==401
    assert len(calls)==7


@pytest.mark.parametrize('change', ['source_revision','source_time','missingness','chart','owner_report',
                                   'horizon','unknown_field','model','rule','hour'])
def test_overview_input_changes_invalidate_without_mutating_context(change):
    import argus_owner_dialogue as dialogue
    c=context();c['intent']='SUBJECT_OVERVIEW'
    c['contextId']=dialogue.digest({k:v for k,v in c.items() if k!='contextId'})
    original=copy.deepcopy(c);policy={'model':'test-primary','ruleVersion':'v1'}
    before=dialogue.overview_input_digest(c,policy)
    if change=='source_revision':c['facts'][0]['revision']='corrected'
    if change=='source_time':c['facts'][0]['acquiredAt']='2026-09-13T00:00:01Z'
    if change=='missingness':c['facts'][0]['verification']='UNAVAILABLE'
    if change=='chart':c['indexComparison']={'forecast':{'value':123}}
    if change=='owner_report':c['owner']={'reportedAt':'2026-09-12T00:00:00Z'}
    if change=='horizon':c['horizonSessions']=10
    if change=='unknown_field':c['newCondition']={'value':True}
    if change=='model':policy['model']='test-next'
    if change=='rule':policy['ruleVersion']='v2'
    if change=='hour':c['receivedAt']='2026-09-13T01:00:00Z'
    c['retrievalRecord']=dialogue.retrieval_record(c)
    c['contextId']=dialogue.digest({k:v for k,v in c.items() if k!='contextId'})
    snapshot=copy.deepcopy(c)
    assert dialogue.overview_input_digest(c,policy)!=before
    assert c==snapshot
    if change not in ('model','rule'):assert original['contextId']!=c['contextId']


def test_pending_overview_deduplicates_after_unrelated_market_change(tmp_path):
    import argus_market_brief
    brief=market_brief();path=tmp_path/'owner.sqlite';entered=threading.Event();release=threading.Event();calls=[]
    app=Flask(__name__)
    def generate(user,**kw):
        calls.append(user);entered.set();release.wait(3);return answer()
    controls=api.register(app,authorize=lambda token:(True,None,200),storage_path=lambda:str(path),
        market_brief=lambda:brief,generate=generate,now=lambda:AT,
        generation_policy=lambda:{'model':'test-primary','ruleVersion':'v1'})
    client=app.test_client();body={'action':'overview','ownerToken':'test-owner',
        'baseContextId':brief['unifiedContext']['contextId'],'symbol':'5803','market':'JP','horizon':5}
    try:
        first=client.post('/api/argus/owner-dialogue',json=body).json
        assert entered.wait(2)
        brief['facts'][0]['text']='他の期間の更新。'
        brief['unifiedContext']=argus_market_brief.unified_context(brief)
        body['baseContextId']=brief['unifiedContext']['contextId']
        second=client.post('/api/argus/owner-dialogue',json=body)
        assert second.status_code==200 and second.json['requestId']==first['requestId']
        assert second.json['overviewEvaluation']['baseMarketContextId']==body['baseContextId']
        assert second.json['status']=='RUNNING' and len(calls)==1
        assert len(store.history(path,controls['bootId'])['items'])==1
    finally:release.set()


def test_missing_generation_policy_rejects_reuse_without_provider_call(tmp_path):
    app=Flask(__name__);calls=[];brief=market_brief()
    api.register(app,authorize=lambda token:(True,None,200),storage_path=lambda:str(tmp_path/'owner.sqlite'),
        market_brief=lambda:brief,generate=lambda *a,**kw:calls.append(1),now=lambda:AT,
        generation_policy=lambda:{})
    response=app.test_client().post('/api/argus/owner-dialogue',json={'action':'overview',
        'baseContextId':brief['unifiedContext']['contextId'],'symbol':'5803','market':'JP','horizon':5})
    assert response.status_code==400 and not calls



def test_real_cached_price_comparison_reuses_clock_change_but_not_source_change(tmp_path):
    from datetime import timedelta
    from test_argus_owner_cached_inputs import inputs, AT as source_at
    import scanner
    import argus_owner_dialogue as dialogue
    import argus_market_brief
    brief,history,classification=inputs();clock=[source_at];calls=[];path=tmp_path/'owner.sqlite'
    brief['facts']=brief['unifiedContext']['facts']
    brief['unifiedContext']=argus_market_brief.unified_context(brief)
    def comparison(**kw):
        return dialogue.cached_subject_comparison(brief=kw['brief'],symbol=kw['symbol'],
            horizon=kw['horizon'],cutoff=kw['cutoff'],history=history,
            classification=classification,close_row=scanner._jp_internals_close_row)
    app=Flask(__name__)
    controls=api.register(app,authorize=lambda token:(True,None,200),storage_path=lambda:str(path),
        market_brief=lambda:brief,generate=lambda *a,**kw:(calls.append(1),answer())[1],
        now=lambda:clock[0],subject_comparison=comparison,
        generation_policy=lambda:{'model':'test-primary','ruleVersion':'v1'})
    client=app.test_client();body={'action':'overview','baseContextId':brief['unifiedContext']['contextId'],
        'symbol':'1234','market':'JP','horizon':5}
    first=client.post('/api/argus/owner-dialogue',json=body).json
    for _ in range(100):
        saved=store.read(path,first['requestId'],controls['bootId'])
        if saved['status']=='SUCCEEDED':break
        time.sleep(.01)
    assert saved['status']=='SUCCEEDED'
    frozen=copy.deepcopy(saved)
    assert any(f['source']=='subject_market_comparison' for f in saved['context']['facts'])
    clock[0]=(dialogue.instant(source_at)+timedelta(seconds=10)).isoformat()
    second=client.post('/api/argus/owner-dialogue',json=body)
    assert second.status_code==200 and second.json['requestId']==first['requestId']
    assert second.json['overviewReuse']['checkedAt']==clock[0] and len(calls)==1
    assert controls['refreshSubjectOverviews']()['status']=='CURRENT' and len(calls)==1
    brief['facts'][0]['text']='他の期間の更新です。'
    brief['unifiedContext']=argus_market_brief.unified_context(brief)
    body['baseContextId']=brief['unifiedContext']['contextId']
    assert client.post('/api/argus/owner-dialogue',json=body).json['requestId']==first['requestId']
    assert len(calls)==1
    # An actual source vintage update must not be dismissed as request time.
    history['acquiredAt']=clock[0]
    third=client.post('/api/argus/owner-dialogue',json=body)
    assert third.status_code==202 and third.json['requestId']!=first['requestId']
    assert store.read(path,first['requestId'],controls['bootId'])['context']==frozen['context']
    assert store.read(path,first['requestId'],controls['bootId'])['result']==frozen['result']
