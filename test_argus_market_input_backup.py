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
    assert result['status']=='VERIFIED' and result['counts']=={'financial':2,'sector17':1,'observations':2,'coverageReceipts':0}
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
    monkeypatch.setattr(backup,'synchronize',lambda path,remote:calls.append(path) or {'status':'VERIFIED'})
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
