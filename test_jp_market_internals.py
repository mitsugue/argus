from copy import deepcopy
from datetime import date,timedelta
import json
import pytest
import jp_market_internals as internal
import scanner

AT='2026-09-13T00:00:00Z'
DATES=[(date(2026,8,1)+timedelta(days=i)).isoformat() for i in range(42) if (date(2026,8,1)+timedelta(days=i)).weekday()<5]


def prices(symbol, end,kind='EQUITY'):
    return {'instrumentId':symbol,'instrumentKind':kind,'priceBasis':'CASH_INDEX_CLOSE' if kind=='INDEX' else 'JQUANTS_ADJUSTED_CLOSE',
        'receivedAt':AT,'source':'test daily prices','rows':[{'date':d,'close':end if d==DATES[-1] else 100,
        'closeAt':d+'T06:30:00Z','completed':True,'volume':1000,'adjusted':True} for d in DATES]}


def snapshot():
    p={'NIKKEI_225_INDEX':prices('NIKKEI_225_INDEX',90,'INDEX'),'1306':prices('1306',100,'ETF'),
       '1625':prices('1625',110,'ETF'),'1234':prices('1234',105)}
    m={'1234':{'sector17Code':'9','effectiveDate':DATES[-1],'receivedAt':AT,'source':'J-Quants V2 equities/master'}}
    return p,m


def build(p,m,symbols=None):return internal.build_snapshot(session_dates=DATES,cutoff=AT,prices=p,
    symbols=symbols or ['1234','2345'],classifications=m)


def test_index_sector_and_asset_use_same_dates_and_different_explained_returns():
    p,m=snapshot();result=build(p,m);five=result['periods']['5'];asset=five['assets'][0]
    sector=next(r for r in five['sectors'] if r['sector17Code']=='9')
    assert five['index']['returnPct']==pytest.approx(-10)
    assert sector['returnPct']==pytest.approx(10) and sector['relativeToBenchmarkPct']==pytest.approx(10)
    assert asset['returnPct']==pytest.approx(5)
    assert asset['relativeToSectorPct']==pytest.approx(-5) and asset['relativeToNikkeiPct']==pytest.approx(15)
    assert asset['startDate']==sector['startDate']==five['index']['startDate']
    assert five['sample']['isWholeMarket'] is False and five['sample']['counts']=={'advancers':1,'decliners':0,'unchanged':0,'available':1,'expected':2,'missing':1}
    assert five['indexContributions']['status']=='UNAVAILABLE' and five['directionScore'] is None
    assert result['actionAuthority'] is False and result['predictiveProbabilityVerified'] is False


def test_short_recovery_and_longer_decline_are_separate_and_snapshot_id_is_stable():
    p,m=snapshot();p['NIKKEI_225_INDEX']['rows'][-2]['close']=80
    first=build(p,m);second=internal.build_snapshot(session_dates=DATES,cutoff='2026-09-13T01:00:00Z',prices=p,symbols=['1234','2345'],classifications=m)
    assert first['periods']['1']['index']['returnPct']>0 and first['periods']['20']['index']['returnPct']<0
    assert first['evidenceId']==second['evidenceId']
    facts=internal.explanation_facts(first)
    assert len(facts)==4 and all('営業日' in f['text'] for f in facts)


@pytest.mark.parametrize('fault',['late','missing_session','unadjusted','no_trade','future_close','wrong_instrument','duplicate_session'])
def test_unusable_prices_never_fill_from_another_day_or_basis(fault):
    p,m=snapshot();r=p['1234']
    if fault=='late':r['receivedAt']='2026-09-14T00:00:00Z'
    elif fault=='missing_session':r['rows'].pop(-6)
    elif fault=='unadjusted':r['rows'][-1]['adjusted']=False
    elif fault=='no_trade':r['rows'][-1]['volume']=0
    elif fault=='future_close':r['rows'][-1]['closeAt']='2026-09-14T06:30:00Z'
    elif fault=='wrong_instrument':r['instrumentId']='9999'
    else:r['rows'].append(deepcopy(r['rows'][-1]))
    assert build(p,m)['periods']['5']['assets'][0]['status']=='UNAVAILABLE'


def test_future_industry_classification_is_not_used():
    p,m=snapshot();m['1234']['receivedAt']='2026-09-14T00:00:00Z'
    r=build(p,m)['periods']['5']['assets'][0]
    assert r['sector17Code'] is None and r['relativeToSectorPct'] is None and r['returnPct'] is not None


def test_market_breadth_requires_complete_received_vintage_and_discloses_basis():
    values={'advancers':6,'decliners':2,'unchanged':1,'unavailable':1,'eligibleCount':9,'totalUniverseCount':10}
    rows=[{'seriesId':'breadth.prime.'+k,'value':v,'periodEnd':'2026-09-11','observedAt':AT,
        'availableFrom':'2026-09-11T08:00:00Z','metadata':{'sourceObservationHash':'same-vintage','calculatedAt':AT,'methodVersion':'test'}} for k,v in values.items()]
    assert internal.breadth_from_ledger(rows[:-1],cutoff=AT)['status']=='UNAVAILABLE'
    assert internal.breadth_from_ledger(rows,cutoff='2026-09-12T00:00:00Z')['status']=='UNAVAILABLE'
    result=internal.breadth_from_ledger(rows,cutoff=AT)
    assert result['counts']==values and result['comparisonBasis']=='PREVIOUS_COMPARABLE_CLOSE'
    conflict=deepcopy(rows[0]);conflict['value']=7
    assert internal.breadth_from_ledger(rows+[conflict,rows[0]],cutoff=AT)['status']=='UNAVAILABLE'


def test_public_runtime_uses_cached_values_without_network_or_persistence(monkeypatch):
    def forbidden(*a,**kw):raise AssertionError('public read cannot fetch or save')
    monkeypatch.setattr(scanner.requests,'get',forbidden)
    monkeypatch.setattr(scanner,'_jp_internals_storage',forbidden)
    monkeypatch.setattr(scanner,'_ai_now_iso',lambda:AT)
    monkeypatch.setattr(scanner,'_JP_INTERNALS_CACHE',{'prices':{},'classifications':{},'restoreAttempted':False})
    result=scanner._jp_market_internals_cached()
    assert result['schemaVersion']==internal.SCHEMA and result['automaticAiCalls']==0


def test_received_cache_survives_restart_and_corruption_never_overwrites_memory(tmp_path,monkeypatch):
    p,m=snapshot();path=tmp_path/'cache.json'
    monkeypatch.setattr(scanner,'_jp_internals_path',lambda:str(path))
    cache={'prices':p,'classifications':m,'restoreAttempted':False}
    monkeypatch.setattr(scanner,'_JP_INTERNALS_CACHE',deepcopy(cache))
    scanner._jp_internals_storage()
    monkeypatch.setattr(scanner,'_JP_INTERNALS_CACHE',{'prices':{},'classifications':{},'restoreAttempted':False})
    scanner._jp_internals_storage(restore=True)
    assert scanner._JP_INTERNALS_CACHE['prices']==p
    assert path.stat().st_mode&0o777==0o600
    before=deepcopy(scanner._JP_INTERNALS_CACHE);value=json.loads(path.read_text());value['body']['prices']['1234']['rows'][-1]['close']=999
    path.write_text(json.dumps(value));scanner._JP_INTERNALS_CACHE['restoreAttempted']=False
    scanner._jp_internals_storage(restore=True)
    assert scanner._JP_INTERNALS_CACHE['prices']==before['prices']


def test_collector_records_actual_receipt_and_keeps_last_good_on_source_failure(monkeypatch):
    monkeypatch.setattr(scanner,'_JQUANTS_API_KEY','test-only')
    monkeypatch.setattr(scanner,'_JP_WATCHLIST',[{'symbol':'1234'}])
    monkeypatch.setattr(internal,'SECTORS',{'9':{'symbol':'1625','nameJa':'電機・精密'}})
    monkeypatch.setattr(scanner,'_jp_internals_path',lambda:None)
    monkeypatch.setattr(scanner,'_jq_master',lambda:[{'code4':'1234','sector17Code':'9','effectiveDate':DATES[-1],'receivedAt':AT}])
    monkeypatch.setattr(scanner,'_JP_INTERNALS_CACHE',{'prices':{},'classifications':{},'restoreAttempted':False})
    monkeypatch.setattr(scanner,'_JP_INTERNALS_ACQUISITION',{'status':'NOT_RUN'})
    stamp={'value':AT};monkeypatch.setattr(scanner,'_ai_now_iso',lambda:stamp['value'])
    failing={'value':False};calls=[]
    class Response:
        status_code=200
        def __init__(self,symbol):self.symbol=symbol
        def __enter__(self):return self
        def __exit__(self,*args):return None
        def iter_content(self,size):
            stamp['value']='2026-09-13T00:00:01Z'
            yield json.dumps({'data':[{'Code':self.symbol+'0','Date':DATES[-1],'AdjC':105,'Vo':1000}]}).encode()
    def get(*args,**kwargs):
        calls.append(kwargs['params']['code'])
        if failing['value']:raise OSError('temporary source outage')
        return Response(kwargs['params']['code'])
    monkeypatch.setattr(scanner.requests,'get',get)
    scanner._jp_internals_warm()
    assert len(calls)==3 and scanner._JP_INTERNALS_ACQUISITION['status']=='AVAILABLE'
    old=deepcopy(scanner._JP_INTERNALS_CACHE['prices'])
    assert old['1234']['receivedAt']=='2026-09-13T00:00:01Z'
    assert old['1625']['instrumentKind']=='ETF'
    failing['value']=True;scanner._JP_INTERNALS_ACQUISITION['lastAttemptMonotonic']=None
    scanner._jp_internals_warm()
    assert scanner._JP_INTERNALS_ACQUISITION['status']=='PARTIAL'
    assert scanner._JP_INTERNALS_CACHE['prices']==old
