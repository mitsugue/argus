"""The original binding is unchanged when adjacent observations share a receipt."""
import json
import sqlite3
import pytest
import argus_market_input_backup as backup
import argus_earnings_history as earnings
import jp_market_acquisition as sources
from test_argus_earnings_history import row, AT, LATER


def trace_original_queries(monkeypatch):
    calls=[];connect=sqlite3.connect
    def instrumented(*args,**kwargs):
        db=connect(*args,**kwargs)
        db.set_trace_callback(lambda query:calls.append(query)
            if query.startswith('SELECT raw,sha256,received_at FROM raw_sources WHERE id=') else None)
        return db
    monkeypatch.setattr(backup.sqlite3,'connect',instrumented)
    return calls


def retain_many(path, received, *, count=32, forecast='1230000000'):
    rows=[{**row(),'Code':f'{1000+i:04d}','FOP':forecast} for i in range(count)]
    earnings.retain(path,rows,received_at=received,member_codes=[r['Code'] for r in rows])


def test_one_source_query_for_many_adjacent_observations(monkeypatch,tmp_path):
    path=tmp_path/'source.sqlite3';retain_many(path,AT)
    calls=trace_original_queries(monkeypatch)
    manifest=backup.snapshot(path,tmp_path)
    assert manifest['counts']['observations']==32
    assert len(calls)==1
    entries=[json.loads(line) for line in (tmp_path/'inputs.ndjson').read_bytes().splitlines()]
    original=next(r for r in entries if r.get('kind')=='raw')
    assert len([r for r in entries if r.get('kind')=='observation' and r['rawId']==original['id']])==32


def test_cache_changes_on_source_revision_and_never_crosses_exports(monkeypatch,tmp_path):
    path=tmp_path/'source.sqlite3';retain_many(path,AT);retain_many(path,LATER,forecast='4560000000')
    calls=trace_original_queries(monkeypatch)
    first=backup.snapshot(path,tmp_path)
    assert first['counts']['observations']==64 and len(calls)==2
    first_bytes=(tmp_path/'inputs.ndjson').read_bytes()
    second=backup.snapshot(path,tmp_path)
    assert first==second and len(calls)==4 and (tmp_path/'inputs.ndjson').read_bytes()==first_bytes


@pytest.mark.parametrize('alteration',['forecast','received','raw-binding','last-row'])
def test_reused_original_still_rejects_changed_observation(tmp_path,alteration):
    path=tmp_path/'source.sqlite3';retain_many(path,AT)
    db=sources.connect(path)
    seq,body=db.execute('SELECT seq,body FROM observations ORDER BY seq DESC LIMIT 1').fetchone();value=json.loads(body)
    if alteration in ('forecast','last-row'):value['summary']['FOP']='9990000000'
    elif alteration=='received':value['receivedAt']=LATER
    else:value['rawId']='not-the-received-original'
    db.execute('UPDATE observations SET body=? WHERE seq=?',(sources._json(value),seq));db.commit();db.close()
    with pytest.raises(ValueError,match='private_observation_integrity'):
        backup.snapshot(path,tmp_path)


def test_original_reuse_keeps_budget_checks_between_observations(tmp_path):
    path=tmp_path/'source.sqlite3';retain_many(path,AT)
    phases=[];observations=[0]
    def budget():
        if phases and phases[-1]=='SNAPSHOT_OBSERVATIONS':
            observations[0]+=1
            if observations[0]==9:raise ValueError('private_original_backup_deadline')
    with pytest.raises(ValueError,match='private_original_backup_deadline'):
        backup.snapshot(path,tmp_path,check_budget=budget,progress=phases.append)
    assert phases[-1]=='SNAPSHOT_OBSERVATIONS' and observations[0]==9
