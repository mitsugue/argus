"""Admit unchanged authenticated bytes once, including across cold recovery."""
import copy
import json
import sqlite3
import uuid
import pytest
import argus_owner_dialogue_backup as backup
import argus_owner_dialogue_segments as segments
import argus_owner_dialogue_store as store
from test_argus_owner_dialogue_backup import keys,add
from test_argus_owner_dialogue_segments import large,rows_digest


def instrument(monkeypatch):
    original=backup._completion;calls=[]
    def checked(*args,**kwargs):
        calls.append(1)
        return original(*args,**kwargs)
    monkeypatch.setattr(backup,'_completion',checked)
    return calls


def test_cold_recovery_admits_all_rows_once_before_reusing_exact_bytes(tmp_path,monkeypatch):
    path,remote=large(tmp_path,monkeypatch);backup.synchronize(path,remote,keys())
    calls=instrument(monkeypatch);cold=tmp_path/'cold';result=backup.synchronize(cold,remote,keys())
    assert len(calls)==12
    assert rows_digest(cold)==rows_digest(path) and result['restoredCounts']==result['counts']
    storage=result['archiveStorage']
    assert storage['reusedValidatedPartCount']==storage['parts'] and storage['newlyValidatedPartCount']==0


def test_warm_append_validates_changed_tail_and_keeps_all_old_parts(tmp_path,monkeypatch):
    path,remote=large(tmp_path,monkeypatch);state=backup.synchronize(path,remote,keys());before=copy.deepcopy(remote.files)
    add(path);calls=instrument(monkeypatch);result=backup.synchronize(path,remote,keys(),previous=state)
    assert 1<=len(calls)<13 and result['counts']['requests']==13
    storage=result['archiveStorage'];assert storage['reusedValidatedPartCount']>0 and storage['newlyValidatedPartCount']>0
    assert storage['reusedValidatedPartCount']+storage['newlyValidatedPartCount']==storage['parts']
    assert all(remote.files[name]==raw for name,raw in before.items() if '/chunks/' in name)


def test_duplicate_admission_cannot_exhaust_the_existing_180_second_budget(tmp_path,monkeypatch):
    path,remote=large(tmp_path,monkeypatch);backup.synchronize(path,remote,keys());calls=instrument(monkeypatch)
    # Controlled per-admission cost, without sleeps or a new production clock.
    def deadline():
        if len(calls)*10>=180:raise TimeoutError('dialogue_backup_deadline')
    remote._check_deadline=deadline
    result=backup.synchronize(tmp_path/'cold',remote,keys())
    assert result['status']=='VERIFIED' and len(calls)==12


def test_changed_old_bytes_cannot_borrow_authenticated_semantic_admission(tmp_path,monkeypatch):
    path,remote=large(tmp_path,monkeypatch);state=backup.synchronize(path,remote,keys());head=remote.files[backup.PREFIX+'/head.json']
    with sqlite3.connect(path) as db:
        identity,raw=db.execute('SELECT request_id,body FROM completions LIMIT 1').fetchone()
        value=store.decode(raw);value.pop('recordDigest')
        value['answer']['sections']['reasons']['textJa']='根拠のない987654321円です。'
        db.execute('UPDATE completions SET body=? WHERE request_id=?',(store.sealed(value),identity))
    before=rows_digest(path)
    with pytest.raises(ValueError,match='answer_invalid'):backup.synchronize(path,remote,keys(),previous=state)
    assert remote.files[backup.PREFIX+'/head.json']==head and rows_digest(path)==before


@pytest.mark.parametrize('fault',['hash','counts','status'])
def test_head_version_alone_does_not_authorize_cached_admission(tmp_path,monkeypatch,fault):
    path,remote=large(tmp_path,monkeypatch);state=backup.synchronize(path,remote,keys());called=[];original=segments._restore
    def restored(*args,**kwargs):called.append(1);return original(*args,**kwargs)
    monkeypatch.setattr(segments,'_restore',restored)
    incomplete=copy.deepcopy(state)
    if fault=='hash':incomplete['archiveSha256']='f'*64
    if fault=='counts':incomplete['counts']['requests']+=1
    if fault=='status':incomplete['status']='FAILED'
    backup.synchronize(path,remote,keys(),previous=incomplete)
    assert len(called)==1


def test_sql_row_identity_is_checked_even_for_previously_validated_body(tmp_path,monkeypatch):
    path,remote=large(tmp_path,monkeypatch);state=backup.synchronize(path,remote,keys());head=remote.files[backup.PREFIX+'/head.json']
    with sqlite3.connect(path) as db:
        old=db.execute('SELECT request_id FROM requests LIMIT 1').fetchone()[0];new=str(uuid.uuid4())
        db.execute('UPDATE requests SET request_id=? WHERE request_id=?',(new,old))
        db.execute('UPDATE completions SET request_id=? WHERE request_id=?',(new,old))
    with pytest.raises(ValueError,match='row_identity'):backup.synchronize(path,remote,keys(),previous=state)
    assert remote.files[backup.PREFIX+'/head.json']==head


def test_closed_diagnostics_include_only_bounded_admission_counts():
    from argus_owner_recovery_diagnostics import status
    value={'status':'VERIFIED','archiveStorage':{'mode':'SEGMENTED_ENCRYPTED_V2',
        'reusedValidatedPartCount':4,'newlyValidatedPartCount':1,'privateText':'never-output'}}
    out=status(value)['archiveStorage']
    assert out['reusedValidatedPartCount']==4 and out['newlyValidatedPartCount']==1
    assert 'never-output' not in json.dumps(out)
    value['archiveStorage'].update(reusedValidatedPartCount=True,newlyValidatedPartCount=1001)
    out=status(value)['archiveStorage']
    assert out['reusedValidatedPartCount'] is None and out['newlyValidatedPartCount'] is None
