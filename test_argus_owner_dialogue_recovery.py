import threading
from flask import Flask
from argus_owner_dialogue_recovery import RecoveryWorker
import argus_owner_dialogue_api as api
import argus_owner_dialogue_backup as backup
from test_argus_owner_dialogue import AT, market_brief
from test_argus_owner_dialogue_api import payload
from test_argus_owner_dialogue_backup import Remote,keys,add


def test_recovery_worker_blocks_new_generation_until_initial_restore_and_reads_are_pure(tmp_path):
    remote=Remote();original=tmp_path/'original';add(original);backup.synchronize(original,remote,keys())
    path=tmp_path/'cold';r=RecoveryWorker(storage_path=lambda:path,configuration=lambda:(True,'config'),keys=keys,remote=lambda:remote,now=lambda:AT)
    assert r.status()['generationReady'] is False and not path.exists()
    assert r._lock.acquire(False);r._run()
    state=r.status();assert state['generationReady'] is True and state['restoredCounts']=={'requests':1,'completions':1}
    before=remote.puts[:]
    for _ in range(3):assert r.status()['status']=='VERIFIED'
    assert remote.puts==before
    remote.fail_read=True
    assert r._lock.acquire(False);r._run()
    assert r.status()['generationReady'] is True and r.status()['status']=='FAILED'
    r.configuration=lambda:(True,'different-config')
    assert r.status()['generationReady'] is False


def test_background_backup_does_not_block_status_or_launch_two_workers(tmp_path):
    entered=threading.Event();release=threading.Event()
    class SlowRemote(Remote):
        def assert_private(self):entered.set();release.wait(3)
    remote=SlowRemote();path=tmp_path/'local';add(path)
    r=RecoveryWorker(storage_path=lambda:path,configuration=lambda:(True,'config'),keys=keys,remote=lambda:remote,now=lambda:AT)
    r.tick();assert entered.wait(1)
    assert r.status()['status']=='RUNNING'
    r.tick(force=True);assert r.status()['pending'] is True
    release.set()
    assert r._lock.acquire(timeout=3);r._lock.release()
    assert r.status()['generationReady'] is True


def test_api_recovery_gate_does_not_call_ai_and_history_does_not_trigger_sync(tmp_path):
    app=Flask(__name__);brief=market_brief();calls=[];triggers=[];path=tmp_path/'cold'
    api.register(app,authorize=lambda t:(True,None,200),storage_path=lambda:path,market_brief=lambda:brief,
        generate=lambda *a,**kw:calls.append(1),now=lambda:AT,
        recovery_status=lambda:{'configured':True,'generationReady':False,'status':'NOT_RUN'},
        recovery_trigger=lambda **kw:triggers.append(kw))
    client=app.test_client()
    history=client.post('/api/argus/owner-dialogue',json={'action':'history'}).json
    assert history['remoteBackup']['generationReady'] is False and not triggers and not path.exists()
    result=client.post('/api/argus/owner-dialogue',json=payload(brief))
    assert result.status_code==503 and result.json['error']=='dialogue_recovery_pending'
    assert calls==[] and len(triggers)==1 and not path.exists()
