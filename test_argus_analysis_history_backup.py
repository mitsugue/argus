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


def test_existing_authenticated_transport_checks_readback_bounds_and_compare_and_swap():
    import base64,json
    calls=[]
    class Response:
        status_code=200
        def __init__(self,body):self.body=body;self.closed=False
        def iter_content(self,size):yield self.body
        def close(self):self.closed=True
    response=Response(json.dumps({'sha':'a'*40,'encoding':'base64','content':base64.b64encode(b'record').decode()}).encode())
    def http(method,url,**kwargs):calls.append((method,url,kwargs));return response
    store=backup.GitHubStore(repo='test-owner/test-private',headers={'Authorization':'Bearer test-token'},http=http)
    assert store.get(backup.PREFIX+'/head.json')==(b'record','a'*40)
    assert calls[0][2]['stream'] is True and calls[0][2]['allow_redirects'] is False and response.closed
    store.put(backup.PREFIX+'/head.json',b'next',expected_version='b'*40)
    assert calls[-1][2]['json']['sha']=='b'*40
    response.body=b'x'*(1024*1024+1)
    with pytest.raises(ValueError,match='response_bound'):store.get(backup.PREFIX+'/head.json')


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
