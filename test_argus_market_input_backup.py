import base64
import json
from pathlib import Path
import pytest
import argus_market_input_backup as backup
import argus_earnings_history as earnings
import jp_market_acquisition as sources
from test_argus_earnings_history import row,AT,LATER


def sector(**extra):
    return sources._json({'data':[dict(Date='2026-10-06',Code='16170',AdjC=100,**extra)]}).encode()


class Remote:
    base='https://api.github.com/repos/mitsugue/argus-l2b-private/contents/'
    def __init__(self,private=True):self.files={};self.writes=0;self.private=private
    def _read_json(self,url):return {'private':self.private}
    def get(self,key):return self.files.get(key),None
    def put(self,key,raw,expected_version):self.files[key]=raw;self.writes+=1


def originals(tmp_path):
    path=tmp_path/'source.sqlite3'
    earnings.retain(path,[row()],received_at=AT,member_codes=['1000'])
    earnings.retain(path,[{**row(),'FOP':'1230000000'}],received_at=LATER,member_codes=['1000'])
    backup.retain_sector(path,sector(),symbol='1617',received_at=AT)
    return path


def test_daily_limit_flags_and_provider_scalar_extensions_survive_private_readback(tmp_path):
    raw=sector(UL='0',LL='0',ExRT=1.0,MktCap=123000,
               MUL='0',MLL='0',MAdjC=99,AUL='0',ALL='0',AAdjVo=10)
    path=tmp_path/'source.sqlite3';remote=Remote()
    backup.retain_sector(path,raw,symbol='1617',received_at=AT)
    result=backup.synchronize(path,remote)
    assert result['status']=='VERIFIED' and result['counts']['sector17']==1
    manifest=json.loads(remote.files[backup.PREFIX+'/manifests/'+result['manifestSha256']+'.json'])
    content=b''.join(remote.files[backup.PREFIX+'/chunks/'+c['sha256']+'.bin'] for c in manifest['chunks'])
    entries=[json.loads(line) for line in content.splitlines()]
    assert [base64.b64decode(r['dataBase64']) for r in entries if r.get('kind')=='raw']==[raw]


@pytest.mark.parametrize('extra',[{'Unexpected':'do-not-export'},{'ExRT':{'owner':'excluded'}},
                                  {'MktCap':[123]}])
def test_extended_daily_schema_still_rejects_unknown_or_nested_values_before_export(tmp_path,extra):
    path=tmp_path/'source.sqlite3'
    with pytest.raises(ValueError,match='fields'):
        backup.retain_sector(path,sector(**extra),symbol='1617',received_at=AT)
    assert not path.exists()


def test_originals_and_corrections_retained_and_private_backup_reuses_immutable_chunks(tmp_path):
    path=originals(tmp_path);remote=Remote()
    result=backup.synchronize(path,remote)
    assert result['status']=='VERIFIED' and result['counts']=={'financial':2,'sector17':1,'observations':2,'coverageReceipts':0,'selectedVix':0,'selectedFeatures':0}
    manifest=json.loads(remote.files[backup.PREFIX+'/manifests/'+result['manifestSha256']+'.json'])
    content=b''.join(remote.files[backup.PREFIX+'/chunks/'+c['sha256']+'.bin'] for c in manifest['chunks'])
    entries=[json.loads(r) for r in content.splitlines()]
    raws=[base64.b64decode(r['dataBase64']) for r in entries if r.get('kind')=='raw']
    assert sector() in raws and len(raws)==3
    assert sorted(r['body']['receivedAt'] for r in entries if r.get('kind')=='observation')==[AT,LATER]
    writes=remote.writes
    assert backup.synchronize(path,remote)==result and remote.writes==writes


@pytest.mark.parametrize('private',[False,None])
def test_public_or_unproven_destination_rejected_before_export(tmp_path,private):
    remote=Remote(private)
    with pytest.raises(ValueError,match='visibility'):backup.synchronize(originals(tmp_path),remote)
    assert remote.writes==0


def test_other_destination_or_owner_fields_cannot_be_sent(tmp_path):
    path=originals(tmp_path);remote=Remote();remote.base=remote.base.replace('argus-l2b-private','another-repo')
    with pytest.raises(ValueError,match='destination'):backup.synchronize(path,remote)
    assert remote.writes==0
    with pytest.raises(ValueError,match='fields'):backup.retain_sector(path,sector(OwnerSecret='excluded'),symbol='1617',received_at=AT)
    with pytest.raises(ValueError,match='scope'):backup.retain_sector(path,sector(),symbol='1000',received_at=AT)


def test_corrupt_original_aborts_before_any_body_is_sent(tmp_path):
    path=originals(tmp_path);db=sources.connect(path)
    db.execute("UPDATE raw_sources SET raw=? WHERE url=?",(b'corrupt',earnings.URL));db.commit();db.close()
    remote=Remote()
    with pytest.raises(ValueError,match='integrity'):backup.synchronize(path,remote)
    assert remote.writes==0


def test_unrelated_owner_storage_is_not_backed_up(tmp_path):
    path=originals(tmp_path);db=sources.connect(path)
    db.execute('INSERT INTO raw_sources VALUES(?,?,?,?,?)',('excluded','https://example.invalid/owner','wrong',AT,b'owner-data'))
    db.commit();db.close()
    remote=Remote();assert backup.synchronize(path,remote)['counts']['financial']==2
    assert all(b'owner-data' not in r for r in remote.files.values())


def test_incomplete_pages_and_future_sector_rows_are_not_preserved_as_complete(tmp_path):
    path=tmp_path/'source.sqlite3'
    with pytest.raises(ValueError,match='schema'):
        backup.retain_sector(path,sources._json({'data':[],'pagination_key':'opaque'}).encode(),symbol='1617',received_at=AT)
    with pytest.raises(ValueError,match='future'):
        backup.retain_sector(path,sector(),symbol='1617',received_at='2026-10-05T01:00:00Z')
    assert not path.exists()


def test_altered_observation_cannot_be_exported_as_an_original(tmp_path):
    path=originals(tmp_path);db=sources.connect(path)
    db.execute("UPDATE observations SET body=replace(body,'1230000000','9990000000')")
    db.commit();db.close();remote=Remote()
    with pytest.raises(ValueError,match='observation_integrity'):backup.synchronize(path,remote)
    assert remote.writes==0


def test_schedule_reuses_existing_connection_bounded_and_not_inline(monkeypatch,tmp_path):
    import scanner
    calls=[];started=[]
    class Thread:
        def __init__(self,target,**kw):self.target=target
        def start(self):started.append(self.target)
    monkeypatch.setattr(scanner,'_JP_INPUT_BACKUP_STATUS',{'status':'NOT_RUN'})
    monkeypatch.setattr(scanner,'_cost_policy_durable_enabled',lambda:True)
    monkeypatch.setattr(scanner,'_DURABILITY_PATHS',{'root':str(tmp_path)})
    monkeypatch.setattr(scanner,'_level_map_remote',lambda:Remote())
    monkeypatch.setattr(scanner.threading,'Thread',Thread)
    monkeypatch.setattr(backup,'synchronize',lambda path,remote,**kw:calls.append(path) or {'status':'VERIFIED'})
    assert scanner._jp_market_inputs_backup_schedule() is True and calls==[]
    assert scanner._jp_market_inputs_backup_schedule() is False
    started[0]()
    assert calls==[str(tmp_path/'jp_market_source_history.sqlite3')]
    assert scanner._JP_INPUT_BACKUP_STATUS['status']=='VERIFIED'
    assert scanner._jp_market_inputs_backup_schedule() is False


def test_backup_deadline_prevents_outbound_body(monkeypatch,tmp_path):
    path=originals(tmp_path);remote=Remote(); ticks=iter([0,backup.MAX_SYNC_SECONDS])
    monkeypatch.setattr(backup.time,'monotonic',lambda:next(ticks))
    with pytest.raises(ValueError,match='deadline'): backup.synchronize(path,remote)
    assert remote.writes==0


def test_visibility_deadline_keeps_visibility_phase_and_never_starts_snapshot(monkeypatch,tmp_path):
    clock=[0.0];steps=[];remote=Remote()
    monkeypatch.setattr(backup.time,'monotonic',lambda:clock[0])
    def visibility(url):
        clock[0]=181.0
        return {'private':True}
    remote._read_json=visibility
    def forbidden(*args,**kwargs):raise AssertionError('snapshot after expired visibility')
    monkeypatch.setattr(backup,'snapshot',forbidden)
    with pytest.raises(ValueError,match='private_original_backup_deadline'):
        backup.synchronize(originals(tmp_path),remote,progress=steps.append)
    assert steps[-1]['phase']=='VISIBILITY'
    assert steps[-1]['elapsedSeconds']==steps[-1]['phaseElapsedSeconds']==181
    assert remote.writes==0 and not remote.files


@pytest.mark.parametrize('phase',[
    'SNAPSHOT_ORIGINALS','SNAPSHOT_OBSERVATIONS','SNAPSHOT_DATE_COVERAGE',
    'SNAPSHOT_COMPANY_COVERAGE','SNAPSHOT_SELECTED','SNAPSHOT_CHUNKS'])
def test_snapshot_checks_shared_deadline_in_each_stage(monkeypatch,tmp_path,phase):
    clock=[0.0];steps=[];remote=Remote()
    monkeypatch.setattr(backup.time,'monotonic',lambda:clock[0])
    def progress(step):
        steps.append(step)
        if step['phase']==phase:clock[0]=181.0
    with pytest.raises(ValueError,match='private_original_backup_deadline'):
        backup.synchronize(originals(tmp_path),remote,progress=progress)
    assert steps[-1]['phase']==phase and steps[-1]['elapsedSeconds']==181
    assert remote.writes==0 and not remote.files


def test_snapshot_deadline_checked_after_individual_original_validation(monkeypatch,tmp_path):
    path=originals(tmp_path);clock=[0.0];steps=[];remote=Remote();calls=[]
    validate=backup._validate_original
    def slow(url,raw):
        calls.append(1);validate(url,raw);clock[0]=181.0
    monkeypatch.setattr(backup.time,'monotonic',lambda:clock[0])
    monkeypatch.setattr(backup,'_validate_original',slow)
    with pytest.raises(ValueError,match='private_original_backup_deadline'):
        backup.synchronize(path,remote,progress=steps.append)
    assert calls==[1] and steps[-1]['phase']=='SNAPSHOT_ORIGINALS'
    assert remote.writes==0 and not remote.files


def test_existing_remote_read_cannot_complete_after_deadline(monkeypatch,tmp_path):
    path=originals(tmp_path);remote=Remote();backup.synchronize(path,remote)
    writes=remote.writes;clock=[0.0];steps=[];get=remote.get
    def late(key):
        result=get(key);clock[0]=181.0;return result
    remote.get=late
    monkeypatch.setattr(backup.time,'monotonic',lambda:clock[0])
    with pytest.raises(ValueError,match='private_original_backup_deadline'):
        backup.synchronize(path,remote,progress=steps.append)
    assert remote.writes==writes and steps[-1]['phase']=='CHUNK_READ'


def test_progress_separates_worker_cpu_from_wall_time(monkeypatch,tmp_path):
    clock=[0.0];cpu=[5.0];steps=[];remote=Remote()
    monkeypatch.setattr(backup.time,'monotonic',lambda:clock[0])
    monkeypatch.setattr(backup.time,'thread_time',lambda:cpu[0])
    def visibility(url):
        clock[0]=10.0;cpu[0]=5.5
        return {'private':True}
    remote._read_json=visibility
    backup.synchronize(originals(tmp_path),remote,progress=steps.append)
    after=next(s for s in steps if s['phase']=='SNAPSHOT')
    assert after['elapsedSeconds']==10 and after['phaseElapsedSeconds']==0
    assert after['workerCpuSeconds']==0.5
    assert after['phaseSeconds']=={'VISIBILITY':10.0,'SNAPSHOT':0.0}


@pytest.mark.parametrize('invalid',[True,-1,float('nan'),float('inf'),'secret',10000001,10**400])
def test_owner_timing_projection_rejects_invalid_or_free_text_values(invalid):
    view=backup.status_projection({'status':'FAILED','elapsedSeconds':invalid,
        'phaseElapsedSeconds':invalid,'workerCpuSeconds':invalid})
    assert view=={'status':'FAILED','workerActive':False}


def test_owner_timing_projection_keeps_only_finite_nonnegative_numbers():
    view=backup.status_projection({'status':'RUNNING','phase':'SNAPSHOT_OBSERVATIONS',
        'elapsedSeconds':15.5,'phaseElapsedSeconds':1,'workerCpuSeconds':2.25,'thread':'owner secret'})
    assert view=={'status':'RUNNING','workerActive':False,'phase':'SNAPSHOT_OBSERVATIONS',
        'elapsedSeconds':15.5,'phaseElapsedSeconds':1,'workerCpuSeconds':2.25}


def test_owner_phase_timing_projection_rejects_unknown_keys_and_values():
    view=backup.status_projection({'status':'FAILED','phaseSeconds':{
        'VISIBILITY':2.5,'owner secret':99,'SNAPSHOT':float('inf'),
        'SNAPSHOT_CHUNKS':True,'COMPLETE':10**400}})
    assert view=={'status':'FAILED','workerActive':False,'phaseSeconds':{'VISIBILITY':2.5}}


def test_progress_reports_only_protocol_scalars_and_preserves_archive(tmp_path):
    path=originals(tmp_path);plain=Remote();observed=Remote();steps=[]
    expected=backup.synchronize(path,plain)
    assert backup.synchronize(path,observed,progress=steps.append)==expected
    assert plain.files==observed.files
    # 2026-10-20: each section is its own chunk stream, so a small store has several chunks.
    chunks=sum(1 for key in plain.files if '/chunks/' in key)
    assert chunks>1
    assert [s['phase'] for s in steps]==[
        'VISIBILITY','SNAPSHOT','SNAPSHOT_ORIGINALS','SNAPSHOT_OBSERVATIONS',
        'SNAPSHOT_DATE_COVERAGE','SNAPSHOT_COMPANY_COVERAGE','SNAPSHOT_SELECTED','SNAPSHOT_CHUNKS',
        'SNAPSHOT_CHUNKS']+['CHUNK_READ','CHUNK_WRITE','CHUNK_READBACK','CHUNK_READBACK']*chunks+[
        'MANIFEST_READ','MANIFEST_WRITE','MANIFEST_READBACK','COMPLETE']
    assert set().union(*(set(s) for s in steps))=={
        'phase','counts','archiveBytes','chunksTotal','chunksProcessed',
        'elapsedSeconds','phaseElapsedSeconds','workerCpuSeconds','phaseSeconds'}
    assert all(s['elapsedSeconds']>=s['phaseElapsedSeconds']>=0 and s['workerCpuSeconds']>=0 for s in steps)
    assert not any(x in json.dumps(steps) for x in ['dataBase64','sourceResponseSha256','1230000000'])


def test_progress_delivery_error_cannot_bypass_or_break_admission(tmp_path):
    path=originals(tmp_path);expected=Remote();observed=Remote()
    result=backup.synchronize(path,expected)
    def broken(value):raise RuntimeError('synthetic owner secret')
    assert backup.synchronize(path,observed,progress=broken)==result
    assert observed.files==expected.files
    rejected=Remote(private=False)
    with pytest.raises(ValueError,match='visibility'):
        backup.synchronize(path,rejected,progress=broken)
    assert rejected.writes==0


def test_write_failure_keeps_exact_failed_phase_without_retry(tmp_path):
    class Failed(Remote):
        def put(self,*args,**kwargs):
            self.writes+=1
            raise ValueError('history_remote_write_conflict_or_unavailable')
    steps=[];remote=Failed()
    with pytest.raises(ValueError,match='write_conflict') as error:
        backup.synchronize(originals(tmp_path),remote,progress=steps.append)
    assert steps[-1]['phase']=='CHUNK_WRITE' and remote.writes==1
    assert set(steps[-1])=={'phase','elapsedSeconds','phaseElapsedSeconds','workerCpuSeconds','phaseSeconds'}
    assert backup.diagnostic_error(error.value)=='history_remote_write_conflict_or_unavailable'
    assert backup.diagnostic_error(ValueError('private_owner_secret'))=='UNCLASSIFIED'


def test_owner_projection_drops_unknown_payload_and_invalid_scalars():
    state={'status':'FAILED','phase':'CHUNK_WRITE','errorClass':'ValueError',
           'errorCategory':'history_remote_write_conflict_or_unavailable',
           'lastAttemptAt':AT,'verifiedAt':LATER,'finishedAt':'not a time',
           'counts':{'financial':2,'sector17':True,'owner':123},
           'chunksProcessed':True,'chunksTotal':2,'archiveBytes':-1,
           'manifestSha256':'a'*64,'raw':'owner secret','headers':{'Authorization':'secret'},
           'lastAttemptMonotonic':123.0}
    view=backup.status_projection(state,worker_active=True)
    assert view=={'status':'FAILED','phase':'CHUNK_WRITE','errorClass':'ValueError',
                 'errorCategory':'history_remote_write_conflict_or_unavailable',
                 'lastAttemptAt':AT,'lastVerifiedAt':LATER,'counts':{'financial':2},
                 'chunksTotal':2,'workerActive':True}
    assert backup.status_projection({'status':'owner secret','phase':'secret',
        'errorCategory':'private_owner_secret','errorClass':'secret'})=={
            'status':'UNKNOWN','workerActive':False}


def test_backup_diagnostic_is_owner_only_opt_in_and_never_runs_backup(monkeypatch):
    import scanner
    monkeypatch.setattr(scanner,'_ARGUS_ADMIN_TOKEN','synthetic-admin')
    monkeypatch.setattr(scanner,'_JP_INPUT_BACKUP_STATUS',{'status':'FAILED',
        'phase':'SNAPSHOT','errorClass':'ValueError','errorCategory':'private_observation_integrity',
        'raw':'synthetic owner secret'})
    def forbidden(*args,**kwargs):raise AssertionError('diagnostic initiated work')
    monkeypatch.setattr(scanner,'_jp_market_inputs_backup_schedule',forbidden)
    monkeypatch.setattr(scanner,'_level_map_remote',forbidden)
    monkeypatch.setattr(backup,'synchronize',forbidden)
    with scanner.app.test_client() as client:
        assert client.get('/api/argus/admin/memory-attribution?market-input-backup=1').status_code==401
        headers={'X-ARGUS-ADMIN-TOKEN':'synthetic-admin'}
        assert 'marketInputBackup' not in client.get('/api/argus/admin/memory-attribution',headers=headers).get_json()
        body=client.get('/api/argus/admin/memory-attribution?market-input-backup=1',headers=headers).get_json()
        assert body['marketInputBackup']['errorCategory']=='private_observation_integrity'
        assert 'synthetic owner secret' not in json.dumps(body)
        assert 'marketInputBackup' not in client.get('/readyz').get_json()


def test_sector_retention_failure_keeps_quotes_and_does_not_fetch_again(monkeypatch,tmp_path):
    import scanner
    import threading
    calls=[];retentions=[]
    class Response:
        status_code=200
        def __init__(self,symbol): self.symbol=symbol
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def iter_content(self,size):
            yield sources._json({'data':[{'Code':self.symbol+'0','Date':'2026-10-06','AdjC':100,'Vo':10}]}).encode()
    def get(url,**kwargs):
        calls.append(kwargs['params']['code']);return Response(calls[-1])
    def fail(*args,**kwargs):
        retentions.append(kwargs['symbol']);raise OSError('synthetic')
    monkeypatch.setattr(scanner,'_JP_INTERNALS_CACHE',{'prices':{},'classifications':{}})
    monkeypatch.setattr(scanner,'_JP_INTERNALS_ACQUISITION',{'status':'NOT_RUN'})
    monkeypatch.setattr(scanner,'_JP_INTERNALS_REFRESH_LOCK',threading.Lock())
    monkeypatch.setattr(scanner,'_JP_INPUT_BACKUP_STATUS',{'status':'NOT_RUN'})
    monkeypatch.setattr(scanner,'_JP_MARKET_ENGINE_MARKET_VIEW_MEMO',{'ts':1})
    monkeypatch.setattr(scanner,'_JP_WATCHLIST',[])
    monkeypatch.setattr(scanner.jp_market_internals,'SECTORS',{'synthetic':{'symbol':'1617'}})
    monkeypatch.setattr(scanner,'_jq_master',lambda:[])
    monkeypatch.setattr(scanner,'_JQUANTS_API_KEY','synthetic')
    monkeypatch.setattr(scanner,'_cost_policy_durable_enabled',lambda:True)
    monkeypatch.setattr(scanner,'_DURABILITY_PATHS',{'root':str(tmp_path)})
    monkeypatch.setattr(scanner,'_jp_internals_storage',lambda **kwargs:None)
    monkeypatch.setattr(scanner.requests,'get',get)
    monkeypatch.setattr(backup,'retain_sector',fail)
    scanner._jp_internals_warm()
    assert calls==['1306','1617'] and retentions==['1617']
    assert scanner._JP_INTERNALS_CACHE['prices']['1617']['rows'][0]['close']==100
    assert scanner._JP_INTERNALS_ACQUISITION['status']=='AVAILABLE'
    assert scanner._JP_INPUT_BACKUP_STATUS['sectorOriginalRetention']=='FAILED'


def test_company_receipts_survive_private_restore_and_identical_response_reuse(tmp_path):
    path=tmp_path/'source.sqlite3';remote=Remote()
    for at in (AT,LATER):
        earnings.retain(path,[row()],received_at=at,member_codes=['1000'],query_code='1000')
    earnings.retain(path,[],received_at=LATER,member_codes=['1001'],query_code='1001')
    result=backup.synchronize(path,remote)
    assert result['counts']['coverageReceipts']==3
    manifest=json.loads(remote.files[backup.PREFIX+'/manifests/'+result['manifestSha256']+'.json'])
    content=b''.join(remote.files[backup.PREFIX+'/chunks/'+c['sha256']+'.bin'] for c in manifest['chunks'])
    restored=tmp_path/'restored.sqlite3';db=sources.connect(restored)
    for entry in [json.loads(line) for line in content.splitlines()][1:]:
        if entry['kind']=='raw':
            db.execute('INSERT INTO raw_sources VALUES(?,?,?,?,?)',(entry['id'],entry['url'],entry['sha256'],entry['receivedAt'],base64.b64decode(entry['dataBase64'])))
        elif entry['kind']=='coverage':
            db.execute('INSERT INTO metadata VALUES(?,?)',(entry['key'],sources._json(entry['body'])))
    db.commit();db.close()
    assert earnings.completed_codes(restored,cutoff=LATER,member_codes=['1000','1001'])=={'1000','1001'}
    assert earnings.completed_codes(restored,cutoff=AT,member_codes=['1000','1001'])=={'1000'}


@pytest.mark.parametrize('change',[{'OwnerSecret':'excluded'},{'retainedRows':999},
                                   {'receivedAt':'2020-01-01T00:00:00Z'}])
def test_company_receipt_fields_counts_and_future_original_rejected_before_send(tmp_path,change):
    path=tmp_path/'source.sqlite3';remote=Remote()
    earnings.retain(path,[row()],received_at=AT,member_codes=['1000'],query_code='1000')
    db=sources.connect(path);key,raw=db.execute("SELECT key,value FROM metadata WHERE key LIKE 'financial-summary-code:%'").fetchone()
    body=json.loads(raw);body.pop('receiptSha256');body.update(change)
    body['receiptSha256']=backup._hash(sources._json(body).encode())
    db.execute('DELETE FROM metadata WHERE key=?',(key,))
    db.execute('INSERT INTO metadata VALUES(?,?)',('financial-summary-code:1000:revision:'+body['receiptSha256'],sources._json(body)))
    db.commit();db.close()
    with pytest.raises(ValueError,match='company_receipt'):
        backup.synchronize(path,remote)
    assert remote.writes==0


def _chunks(remote, result):
    manifest = json.loads(remote.files[backup.PREFIX + '/manifests/' + result['manifestSha256'] + '.json'])
    return [c['sha256'] for c in manifest['chunks']]


def test_a_new_original_reuploads_only_its_section_tail(tmp_path, monkeypatch):
    """2026-10-20: every snapshot re-uploaded all 86 chunks; originals were ordered by hash."""
    monkeypatch.setattr(backup, 'CHUNK_BYTES', 2048)
    path = tmp_path / 'source.sqlite3'
    for day in range(1, 40):
        raw = sources._json({'data': [dict(Date=f'2026-09-{day % 28 + 1:02d}', Code='16170', AdjC=100 + day,
                                           MktCap=123000 + day)] * 40}).encode()
        backup.retain_sector(path, raw, symbol='1617', received_at=f'2026-09-{day % 28 + 1:02d}T09:00:00+00:00')
    remote = Remote()
    first = _chunks(remote, backup.synchronize(path, remote))
    earnings.retain(path, [row()], received_at=AT, member_codes=['1000'])   # one new original
    second = _chunks(remote, backup.synchronize(path, remote))
    assert len(first) > 4
    assert len(set(second) - set(first)) <= 3          # the tail of the touched sections only


def test_first_receipts_and_selected_rows_are_kept_and_checked(tmp_path):
    path = originals(tmp_path)
    rows = [{'instrumentId': 'TOPIX', 'date': '2026-10-06', 'close': 3000.0, 'availableFrom': '2026-10-06T07:00:00Z',
             'sourceRef': 'jquants:topix'}]
    sources.retain_first_receipts(rows, path=path, source_id='topix', received_at='2026-10-06T08:00:00+00:00')
    remote = Remote()
    result = backup.synchronize(path, remote)
    assert result['counts']['selectedFeatures'] == 1
    content = b''.join(remote.files[backup.PREFIX + '/chunks/' + c + '.bin'] for c in _chunks(remote, result))
    entry = [json.loads(l) for l in content.splitlines() if b'selectedFeature' in l][0]
    assert entry['sourceId'] == 'topix' and entry['session'] == '2026-10-06' and entry['receivedAt']
    import sqlite3
    conn = sqlite3.connect(path); conn.execute("UPDATE selected_feature_inputs SET body=replace(body,'3000','3001')"); conn.commit(); conn.close()
    with pytest.raises(ValueError, match='private_selected_integrity'):
        backup.synchronize(path, Remote())
