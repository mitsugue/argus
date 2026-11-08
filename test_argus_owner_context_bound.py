"""Keep all current/prior evidence within the unchanged private context bound."""
import copy
import json
import uuid
import pytest
import argus_owner_dialogue as dialogue
import argus_owner_dialogue_backup as backup
import argus_owner_dialogue_store as store
from test_argus_owner_dialogue import AT, answer, market_brief
from test_argus_owner_dialogue_backup import Remote, keys


def large_brief():
    brief = market_brief()
    public = brief['unifiedContext']
    public['facts'] = [dialogue.fact('資料' + chr(65+i) + '。' + '確認した市場資料です。' * 75,
        'market_context', kind='UNKNOWN') for i in range(18)]
    public['fiscalEnvironment'] = {'id':'fiscal-synthetic', 'status':'AVAILABLE',
        'cases':{'baseline':{'detail':'保存した財政計算です。' * 500}}, 'actionAuthority':False}
    public['contextId'] = dialogue.digest({k:v for k,v in public.items() if k!='contextId'})
    return brief


def build(brief, **kwargs):
    result=dialogue.build_context(brief=brief,symbol='9999',market='JP',horizon=5,
        question='市場と登録銘柄の説明',received_at=AT,watchlist_only=True,
        owner={'symbol':'9999','market':'JP','state':'WATCHING'},**kwargs)
    result['intent']='SUBJECT_OVERVIEW'
    result['contextId']=dialogue.digest({k:v for k,v in result.items() if k!='contextId'})
    return result


def permitted_prior(context):
    return [row for row in context['facts'] if row.get('source')!='owner_report'
        and row.get('evidenceKind')!='OWNER_REPORTED']


def test_first_registration_keeps_all_facts_and_binds_existing_fiscal_reference():
    brief=large_brief();before=copy.deepcopy(brief)
    result=build(brief)
    assert brief==before
    assert all(row in result['facts'] for row in brief['unifiedContext']['facts'])
    assert 'fiscalEnvironment' not in result
    assert result['fiscalEnvironmentReference']['sourceContentSha256']==dialogue.digest(brief['unifiedContext']['fiscalEnvironment'])
    assert result['baseMarketContextId']==brief['unifiedContext']['contextId']
    assert len(json.dumps(result,ensure_ascii=False).encode())<=65536
    assert result['actionAuthority'] is False


def test_followup_references_only_identical_prior_bodies_and_preserves_prompt_and_archive(tmp_path):
    brief=large_brief();old=build(brief);previous=copy.deepcopy(old)
    result=build(brief,previous=old)
    assert old==previous
    assert result['previousFactEncoding']=='EXACT_CURRENT_FACT_REFERENCES_V1'
    assert dialogue.previous_facts(result)==permitted_prior(old)
    assert len(json.dumps(result,ensure_ascii=False).encode())<=65536
    assert result['retrievalRecord']['omittedEvidenceCount']==0
    selected=dialogue.reasoning_context(result)
    assert selected['facts']==result['facts'] and selected['previousFacts']==[]
    assert selected['previousSharedEvidenceIds']==[f['evidenceId'] for f in permitted_prior(old)]
    assert dialogue.overview_input_digest(result,{'model':'test','ruleVersion':'v1'})==dialogue.overview_input_digest(old,{'model':'test','ruleVersion':'v1'})
    validated=dialogue.validate_answer(answer(),result)
    assert validated is not None
    path=tmp_path/'original';store.initialize(path);identity=str(uuid.uuid4())
    store.submit(path,identity=identity,input_hash='a'*64,boot_id='old',context=result)
    store.complete(path,identity,{'status':'SUCCEEDED','answer':validated,'completedAt':AT})
    remote=Remote();backup.synchronize(path,remote,keys());cold=tmp_path/'cold'
    backup.synchronize(cold,remote,keys())
    assert store.read(cold,identity,'new')['context']==result
    assert backup.snapshot(cold)[0]==backup.snapshot(path)[0]


def test_changed_prior_evidence_keeps_its_complete_body_and_order():
    brief=large_brief();old=build(brief)
    old['facts'][0]['text']='前回だけの反対材料です。'
    old['contextId']=dialogue.digest({k:v for k,v in old.items() if k!='contextId'})
    current=build(brief,previous=old)
    assert dialogue.previous_facts(current)==permitted_prior(old)
    assert current['previousFacts'][0]==old['facts'][0]
    assert old['facts'][0] in dialogue.reasoning_context(current)['previousFacts']


@pytest.mark.parametrize('fault',['hash','missing','duplicate','codec'])
def test_invalid_stored_references_are_rejected_before_backup(fault,tmp_path):
    brief=large_brief();c=build(brief,previous=build(brief))
    if fault=='hash':c['previousFactsSha256']='0'*64
    if fault=='missing':c['previousFacts'][0]['sameAsCurrentFact']='missing'
    if fault=='duplicate':c['facts'].append(copy.deepcopy(c['facts'][0]))
    if fault=='codec':c['previousFactEncoding']='UNKNOWN'
    c['contextId']=dialogue.digest({k:v for k,v in c.items() if k!='contextId'})
    raw=store.sealed({'requestId':str(uuid.uuid4()),'inputHash':'a'*64,'bootId':'old','context':c})
    with pytest.raises(ValueError,match='previous_fact_reference'):backup._request(raw)


def test_distinct_overflow_still_fails_instead_of_dropping_facts():
    brief=large_brief();brief['unifiedContext']['facts']*=3
    brief['unifiedContext']['contextId']=dialogue.digest({k:v for k,v in brief['unifiedContext'].items() if k!='contextId'})
    with pytest.raises(ValueError,match='private_context_size_bound'):build(brief)


def test_nonwatchlist_fiscal_hypothesis_context_keeps_existing_full_reference():
    brief=market_brief();brief['unifiedContext']['fiscalEnvironment']={'id':'old-reference','cases':{}}
    brief['unifiedContext']['contextId']=dialogue.digest({k:v for k,v in brief['unifiedContext'].items() if k!='contextId'})
    c=dialogue.build_context(brief=brief,symbol='N225',market='JP',horizon=5,question='財政の仮定',received_at=AT)
    assert c['fiscalEnvironment']['id']=='old-reference' and 'fiscalEnvironmentReference' not in c


def test_reference_packing_distinguishes_json_booleans_and_numbers():
    brief=large_brief()
    brief['unifiedContext']['facts'][0]['sampleFlag']=False
    brief['unifiedContext']['contextId']=dialogue.digest({k:v for k,v in brief['unifiedContext'].items() if k!='contextId'})
    old=build(brief)
    old['facts'][0]['sampleFlag']=0
    old['contextId']=dialogue.digest({k:v for k,v in old.items() if k!='contextId'})
    current=build(brief,previous=old)
    assert current['previousFacts'][0]==old['facts'][0]
    assert old['facts'][0] in dialogue.reasoning_context(current)['previousFacts']


def test_context_encoding_does_not_create_new_generation_inputs():
    brief=market_brief();old=build(brief)
    c=build(brief,previous=old)
    positions={r['evidenceId']:i for i,r in enumerate(c['facts'])}
    c['previousFacts']=[{'sameAsCurrentFact':positions[r['evidenceId']]}
        for r in permitted_prior(old)]
    c['previousFactEncoding']='EXACT_CURRENT_FACT_REFERENCES_V1'
    c['previousFactsSha256']=dialogue.digest(permitted_prior(old))
    c['retrievalRecord']=dialogue.retrieval_record(c)
    c['contextId']=dialogue.digest({k:v for k,v in c.items() if k!='contextId'})
    assert dialogue.overview_input_digest(c,{'model':'test','ruleVersion':'v1'})==dialogue.overview_input_digest(old,{'model':'test','ruleVersion':'v1'})


def test_complete_saved_selection_ids_and_previous_view_fit_without_raising_bound():
    brief=large_brief();old=build(brief);c=build(brief,previous=old)
    full=dialogue.expanded_retrieval_record(c['retrievalRecord'],c)
    assert full['selection']['previousSharedWithCurrent']==[f['evidenceId'] for f in permitted_prior(old)]
    assert full['omittedEvidenceCount']==0
    c['previousView']={'sections':{key:{'textJa':'前回の説明を保存します。'*30,
        'kind':'UNKNOWN','evidenceIds':[]} for key in ('view','reasons','changes','impact','next','invalidation')}}
    c['contextId']=dialogue.digest({k:v for k,v in c.items() if k!='contextId'})
    assert len(json.dumps(dialogue.bounded_context(c),ensure_ascii=False).encode())<=65536


def test_corrupt_encoded_selection_is_not_accepted_in_archive():
    brief=large_brief();c=build(brief,previous=build(brief))
    c['retrievalRecord']['selection']['mandatoryCurrent'][0]=9999
    c['contextId']=dialogue.digest({k:v for k,v in c.items() if k!='contextId'})
    raw=store.sealed({'requestId':str(uuid.uuid4()),'inputHash':'a'*64,'bootId':'old','context':c})
    with pytest.raises(ValueError,match='dialogue_backup_context_invalid'):backup._request(raw)


def test_registered_overview_status_is_cached_counts_not_new_work(tmp_path):
    import time
    from flask import Flask
    import argus_owner_dialogue_api as api
    calls=[];members=[{'market':'JP','symbol':'9999'}]
    controls=api.register(Flask(__name__),authorize=lambda token:(True,None,200),
        storage_path=lambda:str(tmp_path/'store'),market_brief=large_brief,
        generate=lambda *a,**kw:(calls.append(1),answer())[1],now=lambda:AT,
        generation_policy=lambda:{'model':'test','ruleVersion':'v1'},registered_subjects=lambda:members)
    assert controls['overviewStatus']()['status']=='NOT_RUN'
    assert controls['refreshSubjectOverviews']()['status']=='STARTED'
    for _ in range(200):
        item=store.history(tmp_path/'store',controls['bootId'])['items'][0]
        if item['status']!='RUNNING':break
        time.sleep(.01)
    assert item['status']=='SUCCEEDED'
    assert controls['refreshSubjectOverviews']()['status']=='CURRENT'
    observed=controls['overviewStatus']()
    assert observed['registeredSubjects']==observed['savedSubjects']==observed['currentPolicySubjects']==1
    assert observed['missingSubjects']==0
    assert all(controls['overviewStatus']()==observed for _ in range(3))
    assert calls==[1] and '9999' not in json.dumps(observed)


def test_private_runtime_overview_projection_excludes_identifiers_and_error_text():
    from scripts.run_intel_collect import private_runtime_record
    value={'ownerSubjectOverviews':{'status':'CURRENT','registeredSubjects':32,
        'savedSubjects':15,'currentPolicySubjects':8,'missingSubjects':17,
        'lastErrorCode':'private-sentinel','symbol':'private-sentinel','lastCheckedAt':'private-sentinel',
        'jpComparisonBoundSubjects':False}}
    projected=private_runtime_record(value,{})['ownerSubjectOverviews']
    assert projected['registeredSubjects']==32 and projected['missingSubjects']==17
    assert projected['lastErrorCode']=='OTHER' and projected['jpComparisonBoundSubjects'] is None
    assert 'private-sentinel' not in json.dumps(projected)
