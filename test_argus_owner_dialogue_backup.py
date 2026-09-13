"""Encrypted local fault injection; remote production acceptance remains separate."""
import copy
import json
import uuid
import pytest
from cryptography.exceptions import InvalidTag
import argus_owner_dialogue_backup as backup
import argus_owner_dialogue_store as store
import argus_owner_dialogue as dialogue
from test_argus_owner_dialogue import context,answer,AT
from test_argus_analysis_history_backup import Remote as BaseRemote

class Remote(BaseRemote):
    def assert_private(self):pass


def keys(key=b'a'*32,key_id='test-key'):
    return {'status':'configured','current':{'keyId':key_id,'key':key},'previous':None}


def add(path,*,pending=False):
    store.initialize(path);identity=str(uuid.uuid4());c=context()
    store.submit(path,identity=identity,input_hash='a'*64,boot_id='old-boot',context=c)
    if not pending:store.complete(path,identity,{'status':'SUCCEEDED','answer':dialogue.validate_answer(answer(),c),'completedAt':AT})
    return identity


def test_encrypted_cold_restore_preserves_history_and_never_resumes_ai(tmp_path):
    path=tmp_path/'local';remote=Remote();one=add(path);two=add(path,pending=True)
    result=backup.synchronize(path,remote,keys())
    assert result['counts']=={'requests':2,'completions':1}
    assert all(one.encode() not in raw and two.encode() not in raw and '質問'.encode() not in raw and '市場'.encode() not in raw for raw in remote.files.values())
    cold=tmp_path/'cold';restored=backup.synchronize(cold,remote,keys())
    assert store.read(cold,one,'new-boot')['result']==store.read(path,one,'old-boot')['result']
    assert store.read(cold,two,'new-boot')['status']=='INTERRUPTED'
    assert restored['restoredCounts']==result['counts'] and restored['remoteRecoveryVerified'] is False
    before=copy.deepcopy(remote.files)
    backup.synchronize(cold,remote,keys(),previous=restored)
    assert remote.files==before and cold.stat().st_mode&0o777==0o600


def test_local_newer_request_merges_without_overwriting_remote_old_request(tmp_path):
    remote=Remote();path=tmp_path/'first';one=add(path);backup.synchronize(path,remote,keys())
    path2=tmp_path/'second';two=add(path2);result=backup.synchronize(path2,remote,keys())
    assert result['counts']['requests']==2
    assert store.read(path2,one,'new') and store.read(path2,two,'new')
    cold=tmp_path/'third';backup.synchronize(cold,remote,keys())
    assert len(store.history(cold,'new')['items'])==2


def test_wrong_key_or_corrupt_chunk_does_not_create_or_change_local_data(tmp_path):
    path=tmp_path/'first';remote=Remote();add(path);backup.synchronize(path,remote,keys())
    cold=tmp_path/'cold'
    with pytest.raises(InvalidTag):backup.synchronize(cold,remote,keys(b'b'*32))
    assert not cold.exists()
    chunk=next(p for p in remote.files if '/chunks/' in p);remote.files[chunk]=remote.files[chunk][:-1]+b'x'
    with pytest.raises((ValueError,InvalidTag)):backup.synchronize(cold,remote,keys())
    assert not cold.exists()


def test_key_rotation_reads_previous_and_reencrypts_current(tmp_path):
    path=tmp_path/'first';remote=Remote();identity=add(path);old=keys();backup.synchronize(path,remote,old)
    rotated=keys(b'b'*32,'new-key');rotated['previous']=old['current']
    fresh=tmp_path/'fresh';result=backup.synchronize(fresh,remote,rotated)
    assert result['keyId']=='new-key' and store.read(fresh,identity,'new')['status']=='SUCCEEDED'
    final=tmp_path/'final';backup.synchronize(final,remote,keys(b'b'*32,'new-key'))
    assert store.read(final,identity,'new')['status']=='SUCCEEDED'


def test_cas_failure_keeps_concurrent_remote_changes_and_local_history(tmp_path):
    path=tmp_path/'first';remote=Remote();one=add(path);backup.synchronize(path,remote,keys());two=add(path)
    original=remote.put
    def put(name,raw,*,expected_version):
        if name.endswith('/head.json'):raise ValueError('compare_and_swap_conflict')
        return original(name,raw,expected_version=expected_version)
    remote.put=put;head=remote.files[backup.PREFIX+'/head.json']
    with pytest.raises(ValueError,match='compare_and_swap'):backup.synchronize(path,remote,keys())
    assert remote.files[backup.PREFIX+'/head.json']==head
    assert store.read(path,one,'new') and store.read(path,two,'new')


def test_unavailable_remote_is_not_empty_and_bound_never_truncates(tmp_path,monkeypatch):
    path=tmp_path/'first';remote=Remote();one=add(path);backup.synchronize(path,remote,keys());before=copy.deepcopy(remote.files)
    remote.fail_read=True
    with pytest.raises(OSError):backup.synchronize(path,remote,keys())
    remote.fail_read=False;monkeypatch.setattr(backup,'MAX_ARCHIVE_BYTES',100)
    with pytest.raises(ValueError):backup.synchronize(path,remote,keys())
    assert remote.files==before and store.read(path,one,'new')


def test_entire_archive_is_validated_before_merging_any_row(tmp_path):
    path=tmp_path/'first';add(path);raw,_=backup.snapshot(path)
    cold=tmp_path/'cold'
    with pytest.raises(ValueError):backup.restore(cold,raw+b'{"kind":"unknown","value":{}}\n')
    assert not cold.exists()


def test_private_repo_verified_before_any_upload(tmp_path):
    class Response:
        status_code=200
        def iter_content(self,n):yield json.dumps({'private':False,'full_name':'owner/repo'}).encode()
        def close(self):pass
    calls=[]
    def http(method,url,**kw):calls.append(method);return Response()
    remote=backup.PrivateGitHubStore(repo='owner/repo',headers={},http=http);path=tmp_path/'first';add(path)
    with pytest.raises(ValueError,match='private_repo_required'):backup.synchronize(path,remote,keys())
    assert calls==['GET']


def test_chunking_and_immutable_conflict_preserve_live_rows(tmp_path,monkeypatch):
    monkeypatch.setattr(backup,'CHUNK_BYTES',1024)
    remote=Remote();a=tmp_path/'a';one=add(a);backup.synchronize(a,remote,keys())
    assert len([p for p in remote.files if '/chunks/' in p])>1
    b=tmp_path/'b';backup.synchronize(b,remote,keys())
    with store.connect(b) as db:
        row=db.execute('SELECT body FROM requests WHERE request_id=?',(one,)).fetchone()
        value=store.decode(row[0]);value.pop('recordDigest');value['bootId']='altered-boot'
        db.execute('UPDATE requests SET body=?,boot_id=? WHERE request_id=?',(store.sealed(value),'altered-boot',one))
    second=add(a);backup.synchronize(a,remote,keys());before=b.read_bytes()
    with pytest.raises(ValueError,match='immutable_conflict'):backup.synchronize(b,remote,keys())
    assert b.read_bytes()==before and store.read(b,second,'new') is None
