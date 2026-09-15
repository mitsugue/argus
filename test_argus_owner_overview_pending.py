"""Background generations use the completed edition while public reads refresh."""
import copy
import time

from flask import Flask
import pytest

import argus_market_brief
import argus_owner_dialogue as dialogue
import argus_owner_dialogue_api as api
import argus_owner_dialogue_store as store
from test_argus_owner_dialogue import AT, answer, market_brief


def completed(path, controls, request_id):
    for _ in range(100):
        item = store.read(path, request_id, controls['bootId'])
        if item and item['status'] != 'RUNNING': return item
        time.sleep(.01)
    raise AssertionError('worker_did_not_finish')


@pytest.mark.parametrize('status', ['AWAITING_AI', 'UNAVAILABLE', 'INVALID_RESPONSE'])
def test_pending_market_edition_does_not_repeat_ai_but_company_changes_still_do(tmp_path, status):
    path=tmp_path/'owner.sqlite3'; current=[market_brief()];calls=[];materials=[[]]
    current[0].update(unifiedStatus='GENERATED', presentationStatus='GENERATED')
    app=Flask(__name__)
    controls=api.register(app,authorize=lambda token:(True,None,200),storage_path=lambda:str(path),
        market_brief=lambda:current[0],generate=lambda *args,**kw:(calls.append(1),answer())[1],
        now=lambda:AT,generation_policy=lambda:{'model':'test-primary','ruleVersion':'test-revision'},
        subject_materials=lambda **kw:copy.deepcopy(materials[0]))
    body={'action':'overview','ownerToken':'test-owner','baseContextId':current[0]['unifiedContext']['contextId'],
          'symbol':'5803','market':'JP','horizon':5}
    first=app.test_client().post('/api/argus/owner-dialogue',json=body).json
    saved=completed(path,controls,first['requestId']);assert saved['status']=='SUCCEEDED'
    retained=copy.deepcopy(current[0]);pending=copy.deepcopy(retained)
    pending['facts'].append(dialogue.fact('更新途中の市場情報です。','market_refresh',kind='UNKNOWN'))
    pending['unifiedContext']=argus_market_brief.unified_context(pending)
    pending.update(unifiedStatus=status, retainedPresentation=retained)
    current[0]=pending; untouched=copy.deepcopy(pending)
    assert controls['refreshSubjectOverviews']()['status']=='CURRENT'
    assert len(calls)==1 and current[0]==untouched
    assert store.read(path,first['requestId'],controls['bootId'])['context']==saved['context']
    materials[0]=[dialogue.fact('企業の新しい公式資料は確認中です。','company_material',kind='UNKNOWN')]
    assert controls['refreshSubjectOverviews']()['status']=='STARTED'
    latest=store.history(path,controls['bootId'])['items'][0]
    second=completed(path,controls,latest['requestId'])
    assert second['status']=='SUCCEEDED' and len(calls)==2
    assert second['context']['baseMarketContextId']==retained['unifiedContext']['contextId']
    assert any(f['source']=='company_material' for f in second['context']['facts'])
    current[0]=copy.deepcopy(pending);current[0].pop('retainedPresentation')
    current[0]['unifiedStatus']='GENERATED'
    assert controls['refreshSubjectOverviews']()['status']=='STARTED'
    latest=store.history(path,controls['bootId'])['items'][0]
    assert completed(path,controls,latest['requestId'])['status']=='SUCCEEDED' and len(calls)==3


def test_pending_without_completed_edition_does_not_start_background_ai(tmp_path):
    pending=market_brief();pending['unifiedStatus']='AWAITING_AI';calls=[]
    controls=api.register(Flask(__name__),authorize=lambda token:(True,None,200),
        storage_path=lambda:str(tmp_path/'owner.sqlite3'),market_brief=lambda:pending,
        generate=lambda *args,**kw:calls.append(1),now=lambda:AT)
    assert controls['refreshSubjectOverviews']()=={'status':'WAITING','started':0,'reason':'market_edition_pending'}
    assert calls==[] and not (tmp_path/'owner.sqlite3').exists()
