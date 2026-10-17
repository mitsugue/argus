import base64,json,time
from copy import deepcopy
import pytest
import argus_owner_vault as vault

class MemoryRemote:
    def __init__(self):self.values={};self.private=True;self.calls=[];self.conflict=None
    def assert_private(self):
        if not self.private:raise ValueError('vault_private_repository_required')
    def get(self,path):
        self.calls.append(('get',path));raw=self.values.get(path)
        return (raw,vault.transport.digest(raw)[:40]) if raw is not None else (None,None)
    def put(self,path,raw,expected_version):
        self.calls.append(('put',path));_,version=self.get(path)
        if self.conflict and path.endswith('catalog.json'):
            other=self.conflict;self.conflict=None
            self.values[path]=vault.transport.encode({'schemaVersion':'argus-owner-vault-catalog-v2','snapshots':[other]})
            raise ValueError('history_remote_write_conflict_or_unavailable')
        if version!=expected_version:raise ValueError('history_remote_write_conflict_or_unavailable')
        self.values[path]=raw

def envelope(size=1200000):
    return json.dumps({'v':1,'salt':base64.b64encode(b'x'*16).decode(),'iv':base64.b64encode(b'y'*12).decode(),
        'ct':base64.b64encode(b'z'*size).decode(),'exportedAt':'2026-09-13T01:20:00Z'},separators=(',',':')).encode()

VID='a'*64

def test_large_envelope_chunks_and_cold_readback():
    remote=MemoryRemote();raw=envelope();identity=vault.publish(remote,VID,raw,time.time())
    assert len(raw)>1265164 and len(raw)>1024*1024
    assert vault.read_snapshot(remote,VID,identity)==raw
    assert all(len(v)<=512*1024 for v in remote.values.values())
    assert len(vault.catalog(remote,VID)[0])==1
    previous=deepcopy(remote.values);vault.publish(remote,VID,raw,time.time())
    assert previous==remote.values

def test_concurrent_catalog_writers_preserve_prior_snapshot():
    remote=MemoryRemote();raw=envelope(32)
    other={'snapshotId':'b'*64,'bytes':1000,'savedAt':1,'exportedAt':'2026-01-01T00:00:00Z'}
    remote.conflict=other;identity=vault.publish(remote,VID,raw,2)
    assert {r['snapshotId'] for r in vault.catalog(remote,VID)[0]}=={identity,'b'*64}

def test_failed_readback_never_advances_catalog():
    remote=MemoryRemote();normal=remote.get
    def get(path):
        raw,version=normal(path)
        return (b'corrupt',version) if '/chunks/' in path and raw is not None else (raw,version)
    remote.get=get
    with pytest.raises(ValueError):vault.publish(remote,VID,envelope(32),1)
    assert not any(p.endswith('catalog.json') for p in remote.values)

def test_private_repository_required_before_any_write():
    remote=MemoryRemote();remote.private=False
    with pytest.raises(ValueError):vault.publish(remote,VID,envelope(32),1)
    assert not remote.values and not remote.calls

@pytest.fixture
def service(tmp_path):
    remote=MemoryRemote();value=vault.VaultService(path=lambda:str(tmp_path/'upload.sqlite3'),remote=lambda:remote)
    return value,remote

def upload(service,raw):
    value,_=service;identity=vault.transport.digest(raw);args={'vaultId':VID,'snapshotId':identity}
    value.handle({'operation':'begin','bytes':len(raw),**args})
    for index,start in enumerate(range(0,len(raw),vault.UPLOAD_CHUNK)):
        value.handle({'operation':'chunk','part':index,'data':raw[start:start+vault.UPLOAD_CHUNK].decode(),**args})
    return args

def test_upload_resume_and_restarted_backend_read_without_old_db(service,tmp_path):
    value,remote=service;raw=envelope(40000);args=upload(service,raw)
    result=value.handle({'operation':'status',**args});assert result['state']=='UPLOADING' and len(result['parts'])>1
    value._publish(VID,args['snapshotId']);status=value.handle({'operation':'status',**args})
    assert status['state']=='VERIFIED' and not status['decryptionVerified']
    cold=vault.VaultService(path=lambda:str(tmp_path/'fresh.sqlite3'),remote=lambda:remote)
    assert cold.handle({'operation':'read',**args})['blob'].encode()==raw
    assert cold.handle({'operation':'list','vaultId':VID})['snapshots'][0]['snapshotId']==args['snapshotId']

def test_missing_and_conflicting_chunks_cannot_commit(service):
    value,_=service;raw=envelope(40000);identity=vault.transport.digest(raw);args={'vaultId':VID,'snapshotId':identity}
    value.handle({'operation':'begin','bytes':len(raw),**args})
    with pytest.raises(ValueError,match='incomplete'):value.handle({'operation':'commit',**args})
    assert value.handle({'operation':'status',**args})['state']=='UPLOADING'
    upload(service,raw)
    with pytest.raises(ValueError,match='conflict'):value.handle({'operation':'chunk','part':0,'data':'a'*16000,**args})

def test_truncated_or_plaintext_envelope_rejected():
    for raw in [b'{}',b'x'*100,json.dumps({'v':1,'salt':'','iv':'','ct':'','exportedAt':'today'}).encode()]:
        with pytest.raises((ValueError,KeyError)):vault.envelope(raw)

def test_api_authorization_and_body_bound_before_vault(tmp_path):
    from flask import Flask
    import argus_owner_dialogue_api as api
    calls=[]
    class Service:
        def handle(self,body):calls.append(body);return {'snapshots':[]}
    app=Flask(__name__)
    api.register(app,authorize=lambda token:(True,None,200) if token=='owner' else(False,{'error':'auth'},401),
        storage_path=lambda:None,market_brief=lambda:None,generate=lambda *a:None,now=lambda:'2026-09-13T00:00:00Z',vault_service=Service())
    client=app.test_client()
    assert client.post('/api/argus/owner-dialogue',json={'action':'vault','operation':'list','vaultId':VID}).status_code==401
    assert not calls
    assert client.post('/api/argus/owner-dialogue',data='x'*32769).status_code==413
    assert client.post('/api/argus/owner-dialogue',json={'action':'vault','operation':'list','vaultId':VID,'ownerToken':'owner'}).status_code==200
    assert len(calls)==1

def test_private_transport_refuses_public_metadata_before_upload():
    class Response:
        status_code=200
        def iter_content(self,n):yield b'{"private":false,"full_name":"owner/storage"}'
        def close(self):pass
    calls=[]
    def http(method,url,**kwargs):calls.append(method);return Response()
    remote=vault.PrivateStore(repo='owner/storage',headers={},http=http)
    with pytest.raises(ValueError,match='private_repository_required'):vault.publish(remote,VID,envelope(32),1)
    assert calls==['GET']
    with pytest.raises(ValueError,match='scope'):remote.put('outside/file',b'cipher',expected_version=None)

def test_completed_old_snapshot_remains_after_new_snapshot(service):
    value,remote=service;old=envelope(32);new=envelope(64)
    first=vault.publish(remote,VID,old,1);second=vault.publish(remote,VID,new,2)
    assert len(vault.catalog(remote,VID)[0])==2
    assert vault.read_snapshot(remote,VID,first)==old
    assert vault.read_snapshot(remote,VID,second)==new
