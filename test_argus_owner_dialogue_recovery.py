import threading
from flask import Flask
from argus_owner_dialogue_recovery import RecoveryWorker
import argus_owner_dialogue_api as api
import argus_owner_dialogue_backup as backup
from test_argus_owner_dialogue import AT, market_brief
from test_argus_owner_dialogue_api import payload
from test_argus_owner_dialogue_backup import Remote,keys,add,saved_unknown_edition


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
    result=client.post('/api/argus/owner-dialogue',json={k:v for k,v in payload(brief, action='overview').items() if k not in ('requestId','question')})
    assert result.status_code==503 and result.json['error']=='dialogue_recovery_pending'
    assert calls==[] and len(triggers)==1 and not path.exists()


def test_old_unknown_edition_opens_recovery_gate_without_resuming_pending_ai(tmp_path):
    import uuid
    import argus_owner_dialogue_store as store
    original = tmp_path/'old'; store.initialize(original)
    c, result = saved_unknown_edition(); identity = str(uuid.uuid4())
    store.submit(original, identity=identity, input_hash='a'*64, boot_id='old', context=c)
    store.complete(original, identity, result)
    pending = add(original, pending=True)
    before = store.read(original, identity, 'old')['result']
    remote = Remote(); backup.synchronize(original, remote, keys())
    cold = tmp_path/'cold'
    worker = RecoveryWorker(storage_path=lambda:cold,
        configuration=lambda:(True,'config'), keys=keys, remote=lambda:remote, now=lambda:AT)
    assert worker.status()['generationReady'] is False
    assert worker._lock.acquire(False); worker._run()
    assert worker.status()['generationReady'] is True
    assert worker.status()['restoredCounts'] == {'requests':2, 'completions':1}
    assert store.read(cold, identity, 'new')['result'] == before
    assert store.read(cold, pending, 'new')['status'] == 'INTERRUPTED'
    calls = []; triggers = []; app = Flask(__name__)
    api.register(app, authorize=lambda t:(True,None,200), storage_path=lambda:cold,
        market_brief=market_brief, generate=lambda *a,**k:calls.append(1), now=lambda:AT,
        recovery_status=worker.status, recovery_trigger=lambda **k:triggers.append(k))
    puts = list(remote.puts)
    response = app.test_client().post('/api/argus/owner-dialogue',json={'action':'history'})
    assert response.status_code == 200
    assert response.json['remoteBackup']['generationReady'] is True
    assert not calls and not triggers and remote.puts == puts


def test_failed_local_snapshot_keeps_generation_blocked_and_reports_no_saved_text(tmp_path):
    import uuid
    import json
    import argus_owner_dialogue_store as store
    path = tmp_path/'local';store.initialize(path)
    c, result = saved_unknown_edition()
    result['answer']['sections']['reasons']['textJa'] = ' ' + result['answer']['sections']['reasons']['textJa']
    identity = str(uuid.uuid4())
    store.submit(path, identity=identity, input_hash='a'*64, boot_id='old', context=c)
    store.complete(path, identity, result)
    before = path.read_bytes();remote = Remote()
    worker = RecoveryWorker(storage_path=lambda:path,configuration=lambda:(True,'config'),
        keys=keys,remote=lambda:remote,now=lambda:AT)
    assert worker._lock.acquire(False);worker._run()
    state = worker.status()
    assert state['generationReady'] is False and state['restoredThisBoot'] is False
    assert state['status'] == 'FAILED' and state['errorClass'] == 'ValueError'
    assert state['failure']['phase'] == 'local_records'
    assert state['failure']['code'] == 'dialogue_backup_answer_invalid'
    assert state['failure']['answer']['sectionFields'] == {'reasons': ['textJa']}
    assert identity not in json.dumps(state)
    assert result['answer']['sections']['reasons']['textJa'] not in json.dumps(state)
    assert path.read_bytes() == before and not remote.puts


def test_remote_rejection_is_distinct_from_local_snapshot_and_does_not_restore_rows(tmp_path):
    import json
    import argus_owner_dialogue_store as store
    path = tmp_path/'source';add(path)
    raw, _ = backup.snapshot(path)
    rows = [json.loads(line) for line in raw.splitlines()]
    saved = rows[-1]['value']
    saved['answer']['sections']['reasons']['textJa'] = ' ' + saved['answer']['sections']['reasons']['textJa']
    saved.pop('recordDigest')
    rows[-1]['value'] = json.loads(store.sealed(saved))
    raw = b''.join(backup.transport.encode(row) + b'\n' for row in rows)
    cipher = backup._encrypt(raw, keys()['current']);remote = Remote()
    identity = backup.transport.digest(cipher)
    remote.files[backup.PREFIX+'/chunks/'+identity+'.bin'] = cipher
    remote.files[backup.PREFIX+'/head.json'] = backup.transport.encode({
        'schemaVersion': backup.SCHEMA, 'cipherBytes': len(cipher), 'cipherSha256': identity,
        'chunks': [{'sha256': identity, 'bytes': len(cipher)}]})
    cold = tmp_path/'cold'
    worker = RecoveryWorker(storage_path=lambda:cold,configuration=lambda:(True,'config'),
        keys=keys,remote=lambda:remote,now=lambda:AT)
    assert worker._lock.acquire(False);worker._run()
    state = worker.status()
    assert state['status'] == 'FAILED' and state['generationReady'] is False
    assert state['failure']['phase'] == 'remote_records'
    assert state['failure']['code'] == 'dialogue_backup_answer_invalid'
    assert state['failure']['answer']['sectionFields'] == {'reasons': ['textJa']}
    assert not cold.exists() and not remote.puts
