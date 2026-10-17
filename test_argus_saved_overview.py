"""Saved viewing is free of provider work; durable registration drives updates."""
import copy
import time
from flask import Flask
import argus_owner_dialogue_api as api
import argus_owner_dialogue_store as store
from test_argus_owner_dialogue import market_brief, answer, AT


def service(tmp_path):
    path = tmp_path / 'owner.sqlite3'
    members = [{'market':'JP', 'symbol':'5803', 'enabled':True}]
    brief = market_brief()
    calls = []
    materials = []
    def setup():
        app = Flask(__name__)
        controls = api.register(app, authorize=lambda token:(token=='owner', {'error':'unauthorized'},401),
            storage_path=lambda:str(path), market_brief=lambda:brief,
            generate=lambda user, **kw:(calls.append(user),answer())[1], now=lambda:AT,
            generation_policy=lambda:{'model':'test','ruleVersion':'v1'},
            subject_materials=lambda **kw:(materials.append(kw),[])[1],
            registered_subjects=lambda:copy.deepcopy(members))
        return app.test_client(), controls
    client, controls = setup()
    body = {'action':'overview','ownerToken':'owner','symbol':'5803','market':'JP','horizon':5,
            'baseContextId':brief['unifiedContext']['contextId']}
    return path, members, calls, materials, setup, client, controls, body


def wait(path, controls):
    for _ in range(100):
        items = store.history(path, controls['bootId'])['items']
        if items and items[0]['status']!='RUNNING': return items[0]
        time.sleep(.01)
    raise AssertionError('worker did not complete')


def test_view_never_generates_and_first_registration_generates_without_browser(tmp_path):
    path, members, calls, materials, setup, client, controls, body = service(tmp_path)
    for _ in range(3):
        response = client.post('/api/argus/owner-dialogue',json=body)
        assert response.status_code==200 and response.json['status']=='WAITING'
    assert not calls and not materials and not path.exists()
    assert controls['refreshSubjectOverviews']()['status']=='STARTED'
    saved=wait(path,controls)
    assert saved['status']=='SUCCEEDED' and len(calls)==1
    before=copy.deepcopy(saved)
    for _ in range(3):
        response=client.post('/api/argus/owner-dialogue',json={**body,'baseContextId':'new-market'})
        assert response.status_code==200 and response.json['requestId']==saved['requestId']
        assert response.json['overviewRead']['mode']=='SAVED_ONLY'
    assert len(calls)==1 and len(materials)==1
    client,controls=setup()
    assert client.post('/api/argus/owner-dialogue',json=body).json['requestId']==saved['requestId']
    assert controls['refreshSubjectOverviews']()['status']=='CURRENT'
    assert len(calls)==1
    assert store.read(path,saved['requestId'],controls['bootId'])['result']==before['result']
    assert client.post('/api/argus/owner-dialogue',json={**body,'ownerToken':'wrong'}).status_code==401
    assert client.post('/api/argus/owner-dialogue',json={**body,'horizon':999}).status_code==400
    assert len(calls)==1


def test_removal_stops_refresh_but_keeps_history(tmp_path):
    path,members,calls,materials,setup,client,controls,body=service(tmp_path)
    controls['refreshSubjectOverviews']();saved=wait(path,controls)
    members.clear();materials.clear()
    assert controls['refreshSubjectOverviews']()['status']=='CURRENT'
    assert not materials and len(calls)==1
    assert client.post('/api/argus/owner-dialogue',json=body).json['requestId']==saved['requestId']
    assert store.read(path,saved['requestId'],controls['bootId'])['result']==saved['result']


def test_missing_membership_does_not_generate_from_archived_subjects(tmp_path):
    path,members,calls,materials,setup,client,controls,body=service(tmp_path)
    app=Flask(__name__)
    controls=api.register(app,authorize=lambda token:(True,{},200),storage_path=lambda:str(path),
        market_brief=market_brief,generate=lambda *a,**kw:calls.append(a),now=lambda:AT,
        generation_policy=lambda:{'model':'test','ruleVersion':'v1'},registered_subjects=lambda:None)
    assert controls['refreshSubjectOverviews']()['reason']=='membership_unavailable'
    assert not calls


def test_failed_first_subject_does_not_starve_later_registration(tmp_path):
    path=tmp_path/'owner.sqlite3';calls=[]
    app=Flask(__name__)
    controls=api.register(app,authorize=lambda token:(True,{},200),storage_path=lambda:str(path),
        market_brief=market_brief,generate=lambda *a,**kw:(calls.append(a),None)[1],now=lambda:AT,
        generation_policy=lambda:{'model':'test','ruleVersion':'v1'},
        registered_subjects=lambda:[{'symbol':'5803','market':'JP'},{'symbol':'5804','market':'JP'}])
    assert controls['refreshSubjectOverviews']()['status']=='STARTED'
    first=wait(path,controls)
    assert first['status']=='UNAVAILABLE'
    assert controls['refreshSubjectOverviews']()['status']=='STARTED'
    second=wait(path,controls)
    assert first['context']['subject'] != second['context']['subject'] and len(calls)==2
    assert controls['refreshSubjectOverviews']()['status']=='UNAVAILABLE'
    assert len(calls)==2
