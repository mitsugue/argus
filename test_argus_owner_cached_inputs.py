"""Runtime provenance and private cached prices, using explicit test inputs."""
from copy import deepcopy
import hashlib
import json
import pytest
import scanner
import argus_owner_dialogue as dialogue
import jp_market_internals as internal
from test_jp_market_internals import snapshot, build, AT, DATES
from test_argus_owner_dialogue import market_brief


@pytest.mark.parametrize('fraction,expected',[('100000','AVAILABLE'),('300000','UNAVAILABLE')])
def test_fractional_receipt_uses_actual_cutoff_not_truncated_seconds(monkeypatch,fraction,expected):
    from datetime import datetime,timezone
    class Clock(datetime):
        @classmethod
        def now(cls,tz=None):return cls(2026,9,13,0,0,0,200000,tzinfo=timezone.utc)
    monkeypatch.setattr(scanner,'datetime',Clock)
    monkeypatch.setattr(scanner,'_ai_now_iso',lambda:'2026-09-13T00:00:00Z')
    monkeypatch.setattr(scanner,'_JP_MARKET_ENGINE_INDEX_OHLCV_CACHE',{'^N225':{
        'acquiredAt':f'2026-09-13T00:00:00.{fraction}+00:00','sourceResponseSha256':'a'*64,
        'data':[{'date':day,'close':100.0} for day in DATES]}})
    row=scanner._jp_market_internals_cached()['periods']['5']['index']
    assert row['status']==expected
    if expected=='AVAILABLE':assert row['sourceResponseSha256']=='a'*64
    else:assert row['reason']=='received_after_cutoff'


def inputs():
    prices, classifications=snapshot()
    saved=build(prices,classifications,symbols=['2345'])
    brief=market_brief()
    brief['calculationSnapshots']={'5':{'marketInternals':saved}}
    brief['unifiedContext']['facts']+=internal.explanation_facts(saved)
    brief['unifiedContext']['contextId']=dialogue.digest({k:v for k,v in brief['unifiedContext'].items() if k!='contextId'})
    data={'dates':list(reversed(DATES)), 'closes':[105]+[100]*(len(DATES)-1),
          'volumes':[1000]*len(DATES),'adjusted':[True]*len(DATES)}
    history={'instrumentId':'1234','sourceIdentityVerified':True,'sourceComplete':True,
        'acquiredAt':AT,'data':data,'sourceSnapshotSha256':dialogue.digest(data)}
    return brief,history,classifications['1234']


def calc(brief,history,meta):
    return dialogue.cached_subject_comparison(brief=brief,symbol='1234',horizon=5,cutoff=AT,
        history=history,classification=meta,close_row=scanner._jp_internals_close_row)


def test_private_symbol_uses_frozen_market_period_and_never_changes_public_sample():
    brief,history,meta=inputs(); before=deepcopy((brief,history,meta))
    row=calc(brief,history,meta)
    assert row['returnPct']==pytest.approx(5)
    assert row['relativeToNikkeiPct']==pytest.approx(15)
    assert row['relativeToSectorPct']==pytest.approx(-5)
    assert row['sourceResponseSha256'] is None and row['sourceSnapshotSha256']==history['sourceSnapshotSha256']
    result=dialogue.build_context(brief=brief,symbol='1234',market='JP',horizon=5,
        received_at=AT,question='市場との違いは？',subject_comparison=row)
    fact=next(f for f in result['facts'] if f['source']=='subject_market_comparison')
    assert fact['marketInput']['comparisonScope']=='OWNER_PRIVATE'
    assert '日経平均比+15.00' in fact['text'] and (brief,history,meta)==before


@pytest.mark.parametrize('fault',['identity','hash','future','unadjusted','duplicate','partial','empty'])
def test_unverified_or_mismatched_cached_inputs_stay_missing(fault):
    brief,history,meta=inputs()
    if fault=='identity':history['sourceIdentityVerified']=False
    if fault=='hash':history['sourceSnapshotSha256']='f'*64
    if fault=='future':history['acquiredAt']='2026-09-14T00:00:00Z'
    if fault=='partial':history['sourceComplete']=False
    if fault=='empty':history['data']={}
    if fault=='unadjusted':history['data']['adjusted'][0]=False
    if fault=='duplicate':
        for key in history['data']:history['data'][key].append(history['data'][key][0])
    if fault in ('unadjusted','duplicate','empty'):history['sourceSnapshotSha256']=dialogue.digest(history['data'])
    assert calc(brief,history,meta)['status']=='UNAVAILABLE'


def test_missing_classification_keeps_price_comparison_and_provenance_changes_identity():
    brief,history,meta=inputs()
    first=calc(brief,history,{})
    assert first['status']=='AVAILABLE' and first['relativeToSectorPct'] is None
    history['acquiredAt']='2026-09-12T23:00:00Z'
    second=calc(brief,history,{})
    assert first['returnPct']==second['returnPct'] and first['evidenceId']!=second['evidenceId']


def test_runtime_private_resolver_is_cached_only(monkeypatch):
    brief,history,meta=inputs()
    monkeypatch.setattr(scanner,'_JQ_HISTORY_CACHE',{'1234':history})
    monkeypatch.setattr(scanner,'_JQ_MASTER_CACHE',{'data':[{'code':'1234',**meta}]})
    monkeypatch.setattr(scanner.requests,'get',lambda *a,**kw:pytest.fail('no request allowed'))
    result=scanner._owner_dialogue_subject_comparison(brief=brief,symbol='1234',market='JP',horizon=5,cutoff=AT)
    assert result['status']=='AVAILABLE' and result['relativeToSectorPct']==pytest.approx(-5)
    assert scanner._owner_dialogue_subject_comparison(brief=brief,symbol='AAPL',market='US',horizon=5,cutoff=AT) is None


def test_index_raw_response_hash_and_last_good_provenance_survive_failed_refresh(monkeypatch):
    body={'chart':{'result':[{'meta':{'gmtoffset':32400},'timestamp':[1789084800],
        'indicators':{'quote':[{'open':[64000],'high':[64500],'low':[63000],'close':[64011.34],'volume':[0]}]}}]}}
    raw=json.dumps(body).encode();closed=[]
    class Response:
        status_code=200
        content=raw
        def json(self):return body
        def close(self):closed.append(True)
    monkeypatch.setattr(scanner,'_JP_MARKET_ENGINE_INDEX_OHLCV_CACHE',{})
    monkeypatch.setattr(scanner.requests,'get',lambda *a,**kw:Response())
    rows=scanner._yahoo_index_ohlcv('^N225','NIKKEI_225_INDEX',fetch=True,available_hour_utc=7)
    cache=scanner._JP_MARKET_ENGINE_INDEX_OHLCV_CACHE['^N225']
    assert rows and cache['sourceResponseSha256']==hashlib.sha256(raw).hexdigest() and closed
    acquired=cache['acquiredAt'];cache['expires']=0
    monkeypatch.setattr(scanner.requests,'get',lambda *a,**kw:(_ for _ in ()).throw(OSError('offline')))
    assert scanner._yahoo_index_ohlcv('^N225','NIKKEI_225_INDEX',fetch=True,available_hour_utc=7)==rows
    assert cache['acquiredAt']==acquired and cache['sourceResponseSha256']==hashlib.sha256(raw).hexdigest()
    assert cache['lastFetchStatus']=='FAILED'


@pytest.mark.parametrize('fault',[None,'wrong_code','conflicting_revision','nonfinite'])
def test_history_adds_provenance_without_changing_existing_price_selection(monkeypatch,fault):
    rows=[{'Date':d,'Code':'12340','C':100,'AdjC':101,'Vo':1000} for d in reversed(DATES)]
    if fault=='wrong_code':rows[0]['Code']='99990'
    if fault=='conflicting_revision':rows.append({**rows[0],'AdjC':200})
    if fault=='nonfinite':rows[0]['AdjC']=float('nan')
    class Response:
        def raise_for_status(self):pass
        def json(self):return {'data':rows}
    monkeypatch.setattr(scanner,'_JQ_HISTORY_CACHE',{})
    monkeypatch.setattr(scanner,'_JQUANTS_API_KEY','test-key')
    monkeypatch.setattr(scanner.requests,'get',lambda *a,**kw:Response())
    result=scanner._jq_price_history('1234')
    cache=scanner._JQ_HISTORY_CACHE['1234']
    assert result['dates']==list(reversed(DATES)) and cache['sourceComplete'] is True
    if fault=='nonfinite':assert cache['sourceSnapshotSha256'] is None
    else:
        assert result['closes']==[101.0]*len(DATES)
        assert cache['sourceSnapshotSha256']==dialogue.digest(result)
        assert cache['sourceIdentityVerified'] is (fault is None)
