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
