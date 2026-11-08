"""New overview generations require an accepted plan; archives stay readable."""
from copy import deepcopy
import pytest
import argus_owner_dialogue_api as api
import argus_owner_dialogue as dialogue
from argus_presentation_intent import dialogue_inventory
from test_argus_owner_dialogue import context,answer


def current():
    c=context();c['presentationRequired']=True
    c['contextId']=dialogue.digest({k:v for k,v in c.items() if k!='contextId'})
    return c


def planned(c):
    value=answer();catalog=dialogue_inventory(c)
    value['presentation']={'inventoryId':catalog['inventoryId'],'intentJa':'根拠と確認する条件を順に伝える',
        'elements':[{'id':row['id'],'purposeJa':'見立てと根拠を対応させる','placement':'lead' if row['id']=='view' else 'support',
                     'emphasis':'primary' if row['id']=='view' else 'normal'} for row in catalog['elements']]}
    return value


@pytest.mark.parametrize('corrected',[True,False])
def test_missing_plan_is_corrected_once_or_rejected(corrected):
    c=current();calls=[]
    def generate(user,**kwargs):
        calls.append(user)
        return planned(c) if corrected and len(calls)==2 else answer()
    r=api.generate_answer(c,generate)
    assert len(calls)==2
    assert r['provider']['attempts'][0]['validation']['reason']=='presentation_invalid'
    assert r['status']==('SUCCEEDED' if corrected else 'REJECTED')
    assert bool(r['answer']) is corrected
    if corrected:assert r['answer']['presentationStatus']=='GENERATED'


def test_invalid_plan_after_correction_is_never_saved_as_success():
    c=current();bad=planned(c);bad['presentation']['elements'].pop();calls=[]
    r=api.generate_answer(c,lambda *a,**k:(calls.append(a[0]),deepcopy(bad))[1])
    assert len(calls)==2 and r['status']=='REJECTED' and r['answer'] is None
    assert all(x['validation']['reason']=='presentation_invalid' for x in r['provider']['attempts'])


def test_legacy_answer_contract_remains_readable_without_a_plan():
    c=context();old=dialogue.validate_answer(answer(),c)
    assert old and old['presentationStatus']=='UNAVAILABLE'
    rebuilt=dialogue.validate_saved_answer(answer(),c,completed_at='2026-09-13T00:00:00Z')
    assert rebuilt==old


def test_actual_registered_generation_requires_plan_before_success(tmp_path):
    import time
    from flask import Flask
    import argus_owner_dialogue_store as store
    from test_argus_owner_dialogue import market_brief,AT
    controls=api.register(Flask(__name__),authorize=lambda token:(True,None,200),
        storage_path=lambda:str(tmp_path/'store'),market_brief=market_brief,
        generate=lambda *a,**k:answer(),now=lambda:AT,
        generation_policy=lambda:{'model':'test','ruleVersion':'v1','presentationRequired':True},
        registered_subjects=lambda:[{'market':'JP','symbol':'9999'}])
    assert controls['refreshSubjectOverviews']()['status']=='STARTED'
    for _ in range(200):
        item=store.history(tmp_path/'store',controls['bootId'])['items'][0]
        if item['status']!='RUNNING':break
        time.sleep(.01)
    assert item['context']['presentationRequired'] is True
    assert item['status']=='REJECTED' and item['result']['answer'] is None


def test_production_policy_requires_presentation_without_increasing_attempts(monkeypatch):
    import scanner
    monkeypatch.setattr(scanner,'_backend_exact_sha',lambda:'a'*40)
    p=scanner._owner_overview_generation_policy()
    assert p['presentationRequired'] is True
    assert p['maxValidationAttempts']==2 and p['maxOutputTokens']==3000


@pytest.mark.parametrize('kind',['missing','invalid'])
def test_saved_new_contract_never_normalizes_an_unaccepted_plan(kind):
    c=current();value=answer() if kind=='missing' else planned(c)
    if kind=='invalid':value['presentation']['elements'].pop()
    diagnostic={}
    assert dialogue.validate_saved_answer(value,c,completed_at='2026-11-08T14:00:00Z',diagnostic=diagnostic) is None
    assert diagnostic['reason']=='presentation_invalid'
