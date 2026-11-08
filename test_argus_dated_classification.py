"""Dated source selection, with synthetic HTTP and exact frozen periods."""
from copy import deepcopy
import json
import pytest
import argus_market_classification as source

DAY='2026-11-06'
AT='2026-11-08T13:36:00Z'

class Response:
    status_code=200
    def __init__(self,body):self.body=body
    def __enter__(self):return self
    def __exit__(self,*args):return None
    def iter_content(self,n):yield json.dumps(self.body).encode()


def rows(day=DAY):
    return [{'Date':day,'Code':'12340','S17':'9','S33':'3650'},
            {'Date':day,'Code':'285A0','S17':'9','S33':'3650'}]


def warm(cache,get,dates=(DAY,),clock=lambda:0):
    return source.warm(cache,dates,get=get,base='https://synthetic.test/v2',headers={'x-api-key':'synthetic'},
                       now_iso=lambda:AT,monotonic=clock,wall_time=lambda:10,deadline=150)


def test_dated_request_and_pagination_are_complete_before_publication():
    cache={'data':[{'effectiveDate':'2026-11-09'}],'expires':999};before=deepcopy(cache);calls=[]
    def get(url,**kw):
        calls.append(kw)
        assert kw['params']['date']==DAY and not kw['allow_redirects']
        if len(calls)==1:
            assert source.lookup(cache,'1234',DAY) is None
            return Response({'data':rows()[:1],'pagination_key':'next'})
        assert kw['params']['pagination_key']=='next'
        return Response({'data':rows()[1:]})
    status=warm(cache,get)
    assert status['status']=='AVAILABLE' and len(calls)==2
    assert cache['data']==before['data'] and cache['expires']==before['expires']
    meta=source.lookup(cache,'1234',DAY)
    assert meta['effectiveDate']==DAY and meta['receivedAt']==AT and meta['sector17Code']=='9'
    assert len(meta['sourceSnapshotSha256'])==64
    meta['effectiveDate']='2030-01-01'
    assert source.lookup(cache,'1234',DAY)['effectiveDate']==DAY
    assert source.lookup(cache,'1234','2026-11-09') is None
    assert warm(cache,lambda *a,**k:pytest.fail('fresh edition must reuse'))['status']=='AVAILABLE'


@pytest.mark.parametrize('fault',['future','older','duplicate','bad_code','bad_sector','empty','cycle','partial','http','oversize'])
def test_bad_edition_keeps_original_dated_and_current_caches(fault):
    cache={};warm(cache,lambda *a,**k:Response({'data':rows()}));before=deepcopy(cache)
    cache['comparisonByDate'][DAY]['expires']=0;before=deepcopy(cache)
    calls=[]
    def get(*a,**kw):
        calls.append(kw);r=rows()
        if fault=='future':r[0]['Date']='2026-11-09'
        if fault=='older':r[0]['Date']='2026-11-05'
        if fault=='duplicate':r.append(r[0])
        if fault=='bad_code':r[0]['Code']='PRIVATE_TEXT'
        if fault=='bad_sector':r[0]['S17']={'bad':'value'}
        if fault=='empty':r=[]
        body={'data':r}
        if fault in ('cycle','partial'):body['pagination_key']='same'
        response=Response(body)
        if fault=='http':response.status_code=403
        if fault=='oversize':response.iter_content=lambda n:iter([b'x'*(2*1024*1024+1)])
        return response
    result=warm(cache,get)
    assert result['status']=='PARTIAL' and cache==before
    assert len(calls)<=2 if fault!='partial' else len(calls)<=40
    assert source.lookup(cache,'1234',DAY)['receivedAt']==AT


def test_two_dates_bounded_and_readers_never_fetch():
    cache={};warm(cache,lambda *a,**k:Response({'data':rows(k['params']['date'])}),dates=('2026-11-05',DAY))
    assert len(cache['comparisonByDate'])==2
    warm(cache,lambda *a,**k:Response({'data':rows(k['params']['date'])}),dates=(DAY,'2026-11-09'))
    assert set(cache['comparisonByDate'])=={DAY,'2026-11-09'}
    assert source.lookup(cache,'1234',DAY)['effectiveDate']==DAY


def test_deadline_and_total_pages_cover_all_requested_dates():
    cache={};calls=[]
    def get(*a,**kw):calls.append(kw);return Response({'data':rows()})
    result=warm(cache,get,clock=lambda:151)
    assert result['status']=='PARTIAL' and calls==[] and not cache.get('comparisonByDate')
    with pytest.raises(ValueError):warm(cache,get,dates=(DAY,DAY,DAY))


def test_preferred_shares_do_not_replace_ordinary_classification():
    cache={};r=rows();r.append({'Date':DAY,'Code':'12341','S17':'1','S33':'0050'})
    warm(cache,lambda *a,**k:Response({'data':r}))
    assert source.lookup(cache,'1234',DAY)['sector17Code']=='9'


def test_unknown_sector_is_not_invented_and_invalid_token_is_not_completion():
    cache={};r=rows();r[0]['S17']=None
    assert warm(cache,lambda *a,**k:Response({'data':r}))['status']=='AVAILABLE'
    assert source.lookup(cache,'1234',DAY)['sector17Code']==''
    cache={}
    result=warm(cache,lambda *a,**k:Response({'data':rows(),'pagination_key':False}))
    assert result['status']=='PARTIAL' and not cache.get('comparisonByDate')


def test_frozen_public_period_chooses_its_own_classification_not_future_master():
    import jp_market_internals as internal
    from test_jp_market_internals import snapshot,build,AT as cutoff,DATES
    prices,meta=snapshot();future=deepcopy(meta)
    future['1234']['effectiveDate']='2026-09-14'
    old=build(prices,future,symbols=['1234'])
    assert old['periods']['5']['assets'][0]['relativeToSectorPct'] is None
    result=internal.build_snapshot(session_dates=DATES,cutoff=cutoff,prices=prices,
        symbols=['1234'],classifications=future,classification_editions={DATES[-1]:meta})
    assert result['classificationBasis']=='DATED_RECEIVED_MASTER'
    assert result['periods']['5']['assets'][0]['relativeToSectorPct']==pytest.approx(-5)
    meta['1234']['receivedAt']='2026-09-14T00:00:00Z'
    missing=internal.build_snapshot(session_dates=DATES,cutoff=cutoff,prices=prices,
        symbols=['1234'],classifications=future,classification_editions={DATES[-1]:meta})
    assert missing['periods']['5']['assets'][0]['relativeToSectorPct'] is None


def test_private_cached_reader_uses_frozen_date_without_provider_calls(monkeypatch):
    import scanner
    from test_argus_owner_cached_inputs import inputs,AT as cutoff
    brief,history,meta=inputs();day=meta['effectiveDate']
    dated={**meta,'sourceSnapshotSha256':'a'*64}
    cache={'data':[{'code4':'1234',**meta,'effectiveDate':'2026-09-14'}],
           'comparisonByDate':{day:{'rows':{'1234':dated}}}}
    monkeypatch.setattr(scanner,'_JQ_MASTER_CACHE',cache)
    monkeypatch.setattr(scanner,'_JQ_HISTORY_CACHE',{'1234':history})
    monkeypatch.setattr(scanner.requests,'get',lambda *a,**k:pytest.fail('reader must not fetch'))
    before=deepcopy((brief,cache,history))
    result=scanner._owner_dialogue_subject_comparison(brief=brief,symbol='1234',market='JP',horizon=5,cutoff=cutoff)
    assert result['relativeToSectorPct']==pytest.approx(-5)
    assert result['classification']['effectiveDate']==day and result['sectorEvidenceId']
    assert (brief,cache,history)==before


@pytest.mark.parametrize('retained,expected', [('2026-11-06',['2026-11-09','2026-11-06']),('2026-11-10',['2026-11-09']),('2026-11-08',['2026-11-09']),('2026-01-01',['2026-11-09'])])
def test_existing_collector_selects_closed_and_frozen_sessions_only(monkeypatch,retained,expected):
    from datetime import date
    import scanner
    seen=[];cache={'data':[{'effectiveDate':'2026-11-10'}]};before=deepcopy(cache)
    monkeypatch.setattr(scanner,'_JQ_MASTER_CACHE',cache)
    monkeypatch.setattr(scanner,'_JP_INTERNALS_ACQUISITION',{})
    monkeypatch.setattr(scanner,'_jp_market_internals_cached',lambda:{'asOfDate':'2026-11-09'})
    monkeypatch.setattr(scanner.argus_market_clock,'latest_completed_session_date',lambda *a:date(2026,11,9))
    monkeypatch.setattr(scanner,'_JP_INTERNALS_CACHE',{'classifications':{'1234':{'effectiveDate':retained}}})
    def capture(cache,days,**kwargs):
        seen.append((days,kwargs['deadline']));return {'status':'AVAILABLE','requestedDates':days}
    monkeypatch.setattr(source,'warm',capture)
    scanner._jp_classification_warm(123)
    assert seen==[(expected,123)] and cache==before


def test_postclose_price_publication_gap_selects_observed_session(monkeypatch):
    from datetime import date
    import scanner
    captured=[]
    monkeypatch.setattr(scanner,'_JQ_MASTER_CACHE',{})
    monkeypatch.setattr(scanner,'_JP_INTERNALS_ACQUISITION',{})
    monkeypatch.setattr(scanner.argus_market_clock,'latest_completed_session_date',lambda *a:date(2026,11,9))
    monkeypatch.setattr(scanner,'_jp_market_internals_cached',lambda:{'asOfDate':'2026-11-06'})
    monkeypatch.setattr(scanner,'_JP_INTERNALS_CACHE',{'classifications':{'1234':{'effectiveDate':'2026-11-06'}}})
    def capture(cache,days,**kw):captured.extend(days);return {'status':'AVAILABLE'}
    monkeypatch.setattr(source,'warm',capture)
    scanner._jp_classification_warm(123)
    assert captured==['2026-11-06']


def test_new_source_mode_never_uses_another_date_as_fallback():
    import jp_market_internals as internal
    from test_jp_market_internals import snapshot,AT as cutoff,DATES
    prices,meta=snapshot()
    exact=internal.build_snapshot(session_dates=DATES,cutoff=cutoff,prices=prices,
        symbols=['1234'],classifications=meta,classification_editions={})
    assert exact['periods']['5']['assets'][0]['relativeToSectorPct']==pytest.approx(-5)
    meta['1234']['effectiveDate']=DATES[-2]
    result=internal.build_snapshot(session_dates=DATES,cutoff=cutoff,prices=prices,
        symbols=['1234'],classifications=meta,classification_editions={})
    assert result['periods']['5']['assets'][0]['relativeToSectorPct'] is None
