"""Local recovery fault injection; this does not prove live remote delivery."""
import copy
from pathlib import Path

import pytest

import argus_analysis_history as history
import argus_analysis_history_backup as backup
from test_argus_analysis_history import brief


class Remote:
    def __init__(self): self.files = {}; self.puts = []; self.fail_read = False; self.before_head = None
    def get(self, path):
        if self.fail_read: raise OSError('remote unavailable')
        value = self.files.get(path)
        return (value, backup.digest(value)) if value is not None else (None,None)
    def put(self,path,raw,*,expected_version):
        if path.endswith('/head.json') and self.before_head:
            callback,self.before_head=self.before_head,None;callback()
        if self.get(path)[1] != expected_version: raise ValueError('compare_and_swap_conflict')
        self.puts.append(path);self.files[path]=raw


def add(path, stamp, eps):
    history.initialize(path)
    record=history.make_record(brief(stamp),{'5':{'epsInput':eps}})
    history.append(path,record);return record


def test_cold_restore_keeps_original_inputs_and_merges_local_newer_views(tmp_path):
    a=tmp_path/'one.sqlite';b=tmp_path/'two.sqlite';remote=Remote()
    old=add(a,'2026-09-12T00:00:00Z',3000)
    first=backup.synchronize(a,remote);assert first['counts']=={'views':1,'outcomes':0}
    newer=add(b,'2026-09-13T00:00:00Z',3100)
    merged=backup.synchronize(b,remote)
    assert merged['restoredCounts']=={'views':1,'outcomes':0} and merged['counts']['views']==2
    assert history.read_record(b)==newer
    assert history.read_record(b,old['recordId'])['calculations']['5']['epsInput']==3000
    cold=tmp_path/'cold.sqlite';restored=backup.synchronize(cold,remote)
    assert restored['counts']==merged['counts']
    assert history.read_record(cold)==newer
    before=len(remote.puts)
    backup.synchronize(cold,remote,last_verified_head=restored['headVersion'])
    assert len(remote.puts)==before


def test_remote_failure_cannot_be_treated_as_empty_or_rewrite_pointer(tmp_path):
    path=tmp_path/'history.sqlite';remote=Remote();record=add(path,'2026-09-12T00:00:00Z',3000)
    backup.synchronize(path,remote);before=copy.deepcopy(remote.files)
    add(path,'2026-09-13T00:00:00Z',3100);remote.fail_read=True
    with pytest.raises(OSError):backup.synchronize(path,remote)
    assert remote.files==before and history.read_record(path,record['recordId'])==record


def test_corrupt_snapshot_is_rejected_before_mutating_local_history(tmp_path):
    remote=Remote();source=tmp_path/'source.sqlite';add(source,'2026-09-12T00:00:00Z',3000)
    backup.synchronize(source,remote)
    chunk=next(path for path in remote.files if '/chunks/' in path);remote.files[chunk]=b'corrupt'
    target=tmp_path/'target.sqlite'
    with pytest.raises(ValueError,match='chunk'):backup.synchronize(target,remote)
    assert not target.exists()


def test_concurrent_pointer_change_fails_without_overwriting_remote_writer(tmp_path):
    remote=Remote();a=tmp_path/'a.sqlite';b=tmp_path/'b.sqlite'
    original=add(a,'2026-09-12T00:00:00Z',3000);backup.synchronize(a,remote)
    backup.synchronize(b,remote)
    one=add(a,'2026-09-13T00:00:00Z',3100);two=add(b,'2026-09-14T00:00:00Z',3200)
    remote.before_head=lambda:backup.synchronize(b,remote)
    with pytest.raises(ValueError,match='compare_and_swap'):backup.synchronize(a,remote)
    backup.synchronize(a,remote)
    cold=tmp_path/'cold.sqlite';backup.synchronize(cold,remote)
    assert {x['recordId'] for x in history.read_page(cold)['rows']}=={original['recordId'],one['recordId'],two['recordId']}


def test_later_results_and_corrections_survive_remote_restore(tmp_path):
    path=tmp_path/'history.sqlite';history.initialize(path);remote=Remote()
    record=history.make_record(brief('2026-09-13T00:00:00Z'),{'1':{'comparison':{
        'schemaVersion':'jp-market-comparison-v1','anchorDate':'2026-09-11','actualAnchorPrice':100,'unit':'ANCHOR_100',
        'forecast':{'horizonSessions':1,'line':[{'offsetSessions':1,'value':102}],'flatThresholdPct':1,'validationStatus':'UNVALIDATED'}}}})
    history.append(path,record)
    for close in (98,97):history.append_outcomes(path,history.outcome_candidates(record,[{'date':'2026-09-14','close':close}],received_at='2026-09-15T00:00:00Z'))
    backup.synchronize(path,remote);cold=tmp_path/'cold.sqlite';backup.synchronize(cold,remote)
    assert history.read_record(cold)==record
    assert history.read_outcomes(cold,record['recordId'])==history.read_outcomes(path,record['recordId'])


def test_large_snapshot_is_split_and_limits_never_truncate_history(tmp_path,monkeypatch):
    path=tmp_path/'history.sqlite';history.initialize(path);remote=Remote()
    record=history.make_record(brief(),{'5':{'observations':['sample-value']*70000}})
    history.append(path,record);result=backup.synchronize(path,remote)
    chunks=[raw for p,raw in remote.files.items() if '/chunks/' in p]
    assert len(chunks)>1 and max(map(len,chunks))<=backup.CHUNK_BYTES
    cold=tmp_path/'cold.sqlite';backup.synchronize(cold,remote)
    assert history.read_record(cold)==record
    before=copy.deepcopy(remote.files)
    monkeypatch.setattr(backup,'MAX_ARCHIVE_BYTES',100)
    with pytest.raises(ValueError):backup.synchronize(path,remote,last_verified_head=result['headVersion'])
    assert remote.files==before and history.read_record(path)==record


def test_restore_prefetch_is_bounded_ordered_and_closes_on_failure():
    import threading
    remote=backup.GitHubStore(repo='test-owner/test-private',headers={},http=None)
    gate=threading.Barrier(4,timeout=5)
    lock=threading.Lock();entered=[];active=[0];maximum=[0]
    def read(path):
        number=int(path.rsplit('/',1)[1].removesuffix('.bin'))
        with lock:
            entered.append(number);active[0]+=1;maximum[0]=max(maximum[0],active[0])
        try:
            if number<4:gate.wait()
            return str(number).encode(),None
        finally:
            with lock:active[0]-=1
    remote.get=read
    chunks=[{'sha256':str(n)} for n in range(10)]
    stream=remote.read_chunks(chunks)
    assert next(stream)==b'0'
    assert set(entered)==set(range(4)) and maximum[0]==4
    assert list(stream)==[str(n).encode() for n in range(1,10)]
    assert active[0]==0 and maximum[0]<=4
    called=[]
    def fail(path):
        called.append(path);raise TimeoutError('read deadline')
    remote.get=fail
    with pytest.raises(TimeoutError):list(remote.read_chunks(chunks))
    assert len(called)<=4


def test_prefetched_corrupt_chunk_never_changes_live_history(tmp_path):
    source=tmp_path/'source.sqlite';remote=Remote()
    add(source,'2026-09-12T00:00:00Z',3000);backup.synchronize(source,remote)
    target=tmp_path/'target.sqlite';original=add(target,'2026-09-13T00:00:00Z',3100)
    remote.read_chunks=lambda chunks:iter([b'corrupt']*len(chunks))
    before=copy.deepcopy(remote.files)
    with pytest.raises(ValueError,match='chunk'):backup.synchronize(target,remote)
    assert history.read_record(target)==original and remote.files==before


def test_existing_authenticated_transport_checks_readback_bounds_and_compare_and_swap():
    import base64,json
    calls=[]
    class Response:
        status_code=200
        def __init__(self,body):self.body=body;self.closed=False
        def iter_content(self,size):yield self.body
        def close(self):self.closed=True
    import hashlib
    sha=hashlib.sha1(b'blob 6\0record').hexdigest()
    response=Response(json.dumps({'sha':sha,'size':6,'encoding':'base64','content':base64.b64encode(b'record').decode()}).encode())
    def http(method,url,**kwargs):calls.append((method,url,kwargs));return response
    store=backup.GitHubStore(repo='test-owner/test-private',headers={'Authorization':'Bearer test-token'},http=http)
    assert store.get(backup.PREFIX+'/head.json')==(b'record',sha)
    assert calls[0][2]['stream'] is True and calls[0][2]['allow_redirects'] is False and response.closed
    store.put(backup.PREFIX+'/head.json',b'next',expected_version='b'*40)
    assert calls[-1][2]['json']['sha']=='b'*40
    response.body=b'x'*(1024*1024+1)
    with pytest.raises(ValueError,match='response_bound'):store.get(backup.PREFIX+'/head.json')


@pytest.mark.parametrize('damage', ['extra_byte','same_size_wrong_bytes'])
def test_contents_representation_recovers_from_exact_git_blob_without_trimming(damage):
    import base64,hashlib,json
    original=b'x'*backup.CHUNK_BYTES
    sha=hashlib.sha1(b'blob '+str(len(original)).encode()+b'\0'+original).hexdigest()
    damaged=original+b'!' if damage=='extra_byte' else original[:-1]+b'!'
    calls=[];responses=[]
    class Response:
        status_code=200
        def __init__(self,raw):
            self.body=json.dumps({'sha':sha,'size':len(original),'encoding':'base64','content':base64.b64encode(raw).decode()}).encode();self.closed=False
        def iter_content(self,size):
            for start in range(0,len(self.body),size):yield self.body[start:start+size]
        def close(self):self.closed=True
    def http(method,url,**kwargs):
        calls.append((method,url,kwargs));r=Response(original if '/git/blobs/' in url else damaged);responses.append(r);return r
    remote=backup.GitHubStore(repo='test-owner/test-private',headers={},http=http)
    result,version=remote.get(backup.PREFIX+'/chunks/'+backup.digest(original)+'.bin')
    assert result==original and version==sha and len(calls)==2
    assert calls[-1][1].endswith('/git/blobs/'+sha)
    assert all(row[0]=='GET' and row[2]['allow_redirects'] is False for row in calls)
    assert all(r.closed for r in responses)
    def corrupt_http(method,url,**kwargs):return Response(damaged)
    remote=backup.GitHubStore(repo='test-owner/test-private',headers={},http=corrupt_http)
    with pytest.raises(ValueError,match='blob_integrity_invalid'):
        remote.get(backup.PREFIX+'/chunks/'+backup.digest(original)+'.bin')


@pytest.mark.parametrize('kind', ['dialogue','vault'])
def test_private_transports_keep_their_own_deadline_and_can_read_and_write(kind):
    import base64,hashlib,json
    import argus_owner_dialogue_backup as dialogue
    import argus_owner_vault as vault
    clock=[100.0];calls=[];raw=b'bounded encrypted bytes'
    sha=hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()
    class Response:
        status_code=200
        def iter_content(self,n):yield json.dumps({'sha':sha,'size':len(raw),'encoding':'base64','content':base64.b64encode(raw).decode()}).encode()
        def close(self):pass
    def http(method,url,**kwargs):calls.append((method,kwargs));return Response()
    cls=dialogue.PrivateGitHubStore if kind=='dialogue' else vault.PrivateStore
    remote=cls(repo='owner/private',headers={},http=http,monotonic=lambda:clock[0])
    path=dialogue.PREFIX+'/head.json' if kind=='dialogue' else vault.PREFIX+'/'+'a'*64+'/catalog.json'
    clock[0]=150.0
    assert remote.get(path)==(raw,sha)
    with pytest.raises(ValueError,match='private_scope_required'):remote.put(path,raw,expected_version=sha)
    remote.private_verified=True
    remote.put(path,raw,expected_version=sha)
    assert calls[-1][0]=='PUT' and calls[-1][1]['json']['sha']==sha
    clock[0]=280.0
    before=len(calls)
    with pytest.raises(TimeoutError):remote.get(path)
    assert len(calls)==before


def test_worker_connection_and_public_status_do_not_expose_credentials(tmp_path,monkeypatch):
    import scanner
    path=tmp_path/'runtime.sqlite';add(path,'2026-09-12T00:00:00Z',3000)
    monkeypatch.setattr(scanner,'_market_brief_history_path',lambda:str(path))
    monkeypatch.setenv('ARGUS_LAYER2B_PRIVATE_REPO','test-owner/test-private')
    monkeypatch.setenv('ARGUS_LAYER2B_PRIVATE_TOKEN','test-token')
    remote=Remote()
    monkeypatch.setattr(backup,'GitHubStore',lambda **kwargs:remote)
    monkeypatch.setattr(scanner,'_MARKET_BRIEF_HISTORY_REMOTE',{'status':'NOT_RUN','headVersion':None})
    scanner._market_brief_history_sync()
    assert scanner._MARKET_BRIEF_HISTORY_REMOTE['status']=='VERIFIED'
    def forbidden(*args,**kwargs):raise AssertionError('public history must not synchronize')
    monkeypatch.setattr(scanner,'_market_brief_history_sync',forbidden)
    with scanner.app.test_request_context('/api/argus/market-brief?history=1'):
        result=scanner.api_argus_market_brief().get_json()
    assert result['remoteBackup']['counts']['views']==1 and result['remoteRecoveryVerified'] is False
    assert 'test-token' not in str(result) and 'headVersion' not in str(result)


def test_remote_deadline_prevents_more_network_and_preserves_local_history(tmp_path):
    path=tmp_path/'history.sqlite';record=add(path,'2026-09-12T00:00:00Z',3000)
    clock=[0.0];calls=[]
    def http(*args,**kwargs):calls.append(args);raise AssertionError('expired operation sent a request')
    remote=backup.GitHubStore(repo='test-owner/test-private',headers={},http=http,monotonic=lambda:clock[0])
    clock[0]=backup.MAX_SYNC_SECONDS
    with pytest.raises(TimeoutError,match='history_remote_deadline_exceeded'):
        backup.synchronize(path,remote)
    with pytest.raises(TimeoutError):remote.put(backup.PREFIX+'/head.json',b'new',expected_version=None)
    assert not calls and history.read_record(path)==record


def test_remote_stream_deadline_closes_response_and_request_timeout_shrinks():
    clock=[0.0];timeouts=[]
    class Response:
        status_code=200
        closed=False
        def iter_content(self,size):
            clock[0]=backup.MAX_SYNC_SECONDS+1
            yield b'late bytes'
        def close(self):self.closed=True
    response=Response()
    def http(*args,**kwargs):timeouts.append(kwargs['timeout']);return response
    remote=backup.GitHubStore(repo='test-owner/test-private',headers={},http=http,monotonic=lambda:clock[0])
    clock[0]=backup.MAX_SYNC_SECONDS-4
    with pytest.raises(TimeoutError):remote.get(backup.PREFIX+'/head.json')
    assert sum(timeouts[0])<=4 and response.closed
