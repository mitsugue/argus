"""Normal ticks save a retained provider result without another provider call."""
import copy
import threading
import time
import pytest
from flask import Flask
import argus_owner_dialogue_api as api
import argus_owner_dialogue_store as store
from test_argus_owner_dialogue import market_brief, answer, AT


def prepared(tmp_path, monkeypatch, *, result='valid', readback_failure=False):
    path=tmp_path/'owner.sqlite';app=Flask(__name__);calls=[];writes=[];fail=[True]
    original_complete=store.complete;original_read=store.read
    def complete(*args,**kwargs):
        writes.append(copy.deepcopy(args[2]))
        if fail[0] and not readback_failure:raise OSError('synthetic local write failure')
        return original_complete(*args,**kwargs)
    def read(*args,**kwargs):
        if fail[0] and readback_failure and threading.current_thread().name=='owner-overview-refresh':
            raise OSError('synthetic readback failure')
        return original_read(*args,**kwargs)
    monkeypatch.setattr(store,'complete',complete);monkeypatch.setattr(store,'read',read)
    def generate(*args,**kwargs):
        calls.append(1)
        return answer() if result=='valid' else None
    controls=api.register(app,authorize=lambda token:(True,None,200),storage_path=lambda:str(path),
        market_brief=market_brief,generate=generate,now=lambda:AT,
        generation_policy=lambda:{'model':'test','ruleVersion':'v1'},
        registered_subjects=lambda:[{'market':'JP','symbol':'9999'}])
    assert controls['refreshSubjectOverviews']()['status']=='STARTED'
    item=store.history(path,controls['bootId'])['items'][0];identity=item['requestId']
    for _ in range(200):
        held=app.test_client().post('/api/argus/owner-dialogue',json={'action':'status','requestId':identity}).json
        if held['status']=='SAVE_FAILED':break
        time.sleep(.01)
    assert held['status']=='SAVE_FAILED' and len(calls)==1
    return path,controls,identity,held['result'],calls,writes,fail,app


@pytest.mark.parametrize('readback_failure',[False,True])
def test_next_normal_tick_preserves_original_paid_result(tmp_path,monkeypatch,readback_failure):
    path,controls,identity,paid,calls,writes,fail,app=prepared(tmp_path,monkeypatch,readback_failure=readback_failure)
    fail[0]=False
    controls['refreshSubjectOverviews']()
    actual=store.read(path,identity,controls['bootId'])
    assert actual['status']=='SUCCEEDED'
    assert {k:v for k,v in actual['result'].items() if k!='recordDigest'}==paid
    assert len(calls)==1 and writes[-1]==paid
    assert app.test_client().post('/api/argus/owner-dialogue',json={'action':'status','requestId':identity}).json['status']=='SUCCEEDED'
    assert controls['overviewStatus']()['pendingUnsavedResults']==0
    assert controls['overviewStatus']()['retainedPersistenceStatus']=='PERSISTED'


def test_persistent_write_failure_holds_paid_result_without_new_generation(tmp_path,monkeypatch):
    path,controls,identity,paid,calls,writes,fail,app=prepared(tmp_path,monkeypatch)
    for _ in range(3):
        assert controls['refreshSubjectOverviews']()['status']=='UNAVAILABLE'
        held=app.test_client().post('/api/argus/owner-dialogue',json={'action':'status','requestId':identity}).json
        assert held['status']=='SAVE_FAILED' and held['result']==paid
    assert len(calls)==1 and len(writes)==4
    assert controls['overviewStatus']()['pendingUnsavedResults']==1
    assert controls['overviewStatus']()['retainedPersistenceStatus']=='FAILED'
    fail[0]=False;controls['refreshSubjectOverviews']()
    assert store.read(path,identity,controls['bootId'])['status']=='SUCCEEDED' and len(calls)==1


def test_unavailable_result_is_saved_as_unavailable_not_success(tmp_path,monkeypatch):
    path,controls,identity,paid,calls,writes,fail,app=prepared(tmp_path,monkeypatch,result='unavailable')
    assert paid['status']=='UNAVAILABLE';fail[0]=False
    controls['refreshSubjectOverviews']()
    actual=store.read(path,identity,controls['bootId'])
    assert actual['status']=='UNAVAILABLE'
    assert {k:v for k,v in actual['result'].items() if k!='recordDigest'}==paid and len(calls)==1


def test_saved_only_view_does_not_flush_or_generate(tmp_path,monkeypatch):
    path,controls,identity,paid,calls,writes,fail,app=prepared(tmp_path,monkeypatch)
    response=app.test_client().post('/api/argus/owner-dialogue',json={
        'action':'overview','market':'JP','symbol':'9999','horizon':5}).json
    assert response['overviewRead']['mode']=='SAVED_ONLY'
    assert len(calls)==1 and len(writes)==1
    assert controls['overviewStatus']()['pendingUnsavedResults']==1


def test_retained_result_does_not_need_new_generation_admission(tmp_path,monkeypatch):
    path,controls,identity,paid,calls,writes,fail,app=prepared(tmp_path,monkeypatch)
    fail[0]=False
    # No new provider call or context rebuild is needed for this result.
    monkeypatch.setattr(api.dialogue,'build_context',lambda **kwargs:pytest.fail('retained save rebuilt context'))
    controls['refreshSubjectOverviews']()
    assert store.read(path,identity,controls['bootId'])['status']=='SUCCEEDED' and len(calls)==1


def test_closed_diagnostics_never_copy_retained_body_or_error_text():
    from argus_owner_recovery_diagnostics import subject_overviews
    result=subject_overviews({'pendingUnsavedResults':1,'retainedPersistenceStatus':'PERSISTED',
        'lastErrorCode':'completion_persistence_failed','lastValidationReason':'presentation_invalid',
        'result':'PRIVATE_SENTINEL','lastError':'PRIVATE_SENTINEL'})
    assert result['pendingUnsavedResults']==1 and result['retainedPersistenceStatus']=='PERSISTED'
    assert result['lastValidationReason']=='presentation_invalid'
    assert 'PRIVATE_SENTINEL' not in str(result)
    assert subject_overviews({'pendingUnsavedResults':True,'retainedPersistenceStatus':'PRIVATE_SENTINEL'})['pendingUnsavedResults'] is None


def test_existing_different_completion_is_never_overwritten(tmp_path,monkeypatch):
    path,controls,identity,paid,calls,writes,fail,app=prepared(tmp_path,monkeypatch)
    fail[0]=False
    existing={'status':'FAILED','completedAt':AT,'answer':None,'errorClass':'SyntheticOriginal'}
    store.complete(path,identity,existing)
    original=store.read(path,identity,controls['bootId'])['result']
    assert controls['refreshSubjectOverviews']()['status']=='UNAVAILABLE'
    assert store.read(path,identity,controls['bootId'])['result']==original
    held=app.test_client().post('/api/argus/owner-dialogue',json={'action':'status','requestId':identity}).json
    assert held['status']=='SAVE_FAILED' and held['result']==paid and len(calls)==1
