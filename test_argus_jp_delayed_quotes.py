"""Display backup admission, pacing and actual cache-only route boundary."""
import ast
from datetime import datetime, timezone
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import argus_jp_delayed_quotes as q

NOW = datetime(2026, 11, 5, 1, 0, tzinfo=timezone.utc).timestamp()
MEMBERS = [{'market': 'JP', 'symbol': '1001', 'enabled': True}]

def payload(symbol='1001', **patch):
    return {'chart': {'result': [{'meta': {'symbol': symbol+'.T', 'currency': 'JPY',
        'regularMarketPrice': 123.5, 'chartPreviousClose': 120, 'regularMarketTime': NOW-1200, **patch}}]}}

class Response:
    def __init__(self, value=None, status=200): self.value=value or payload(); self.status_code=status; self.closed=False
    def iter_content(self, **kwargs): yield json.dumps(self.value).encode()
    def close(self): self.closed=True

def test_strict_membership_only_not_public_hints():
    assert q.symbols_from_members(MEMBERS + [{'market':'US','symbol':'1002'},
        {'market':'JP','symbol':'1003','enabled':False}, {'market':'JP','symbol':'^N225'},
        {'market':'JP','symbol':'1001.T'}]) == ('1001',)
    assert len(q.symbols_from_members([{'market':'JP','symbol':str(1000+i)} for i in range(60)])) == 50
    with pytest.raises(ValueError): q.symbols_from_members(None)

@pytest.mark.parametrize('patch', [{'regularMarketPrice':float('nan')}, {'regularMarketPrice':0},
    {'regularMarketPrice':True}, {'regularMarketTime':NOW+1}, {'regularMarketTime':NOW-86400},
    {'regularMarketTime':float('inf')}, {'symbol':'1002.T'}, {'currency':'USD'},
    {'regularMarketTime':datetime(2026,11,5,3,1,tzinfo=timezone.utc).timestamp()}])
def test_reject_wrong_future_old_and_invalid_quotes(patch):
    assert q.parse_quote(payload(**patch), '1001', NOW) is None


def test_actual_receipt_and_source_separate_and_failure_preserves_original_times():
    c=q.Collector(); responses=[]; clock=[NOW]
    def get(*a,**k):
        assert k['allow_redirects'] is False and k['stream'] is True
        r=Response();responses.append(r);clock[0]+=1;return r
    c.tick(get, lambda:MEMBERS, epoch=lambda:clock[0])
    original=c.document(['1001'],now=clock[0])['symbols']['1001']
    assert original['delaySeconds']==1201 and original['actionAuthority'] is False
    clock[0]+=61
    failed=Response(status=503)
    c.tick(lambda *a,**k:failed, lambda:MEMBERS, epoch=lambda:clock[0])
    kept=c.document(['1001'],now=clock[0])['symbols']['1001']
    assert kept['receivedAt']==original['receivedAt'] and kept['sourceTimestamp']==original['sourceTimestamp']
    assert kept['lastError']=='HTTP_503' and all(r.closed for r in responses) and failed.closed
    assert c.document(['9999'],now=clock[0])['symbols']=={}
    calls=[]
    c.tick(lambda *a,**k:calls.append(a),lambda:MEMBERS,epoch=lambda:clock[0]+119)
    assert calls==[]


def test_fresh_tachibana_skips_backup_and_membership_removal_discards_prices():
    c=q.Collector();calls=[]
    def get(*a,**k):calls.append(a);return Response()
    c.tick(get,lambda:MEMBERS,{'1001'},epoch=lambda:NOW)
    assert calls==[]
    c.tick(get,lambda:MEMBERS,epoch=lambda:NOW)
    assert len(calls)==1
    c.tick(get,lambda:[],epoch=lambda:NOW+61)
    assert c.document(['1001'],now=NOW+61)['symbols']=={}


def test_429_pauses_all_and_no_more_than_four_inflight():
    c=q.Collector();calls=[]
    members=[{'market':'JP','symbol':str(1000+i)} for i in range(50)]
    def get(*a,**k):calls.append(a);return Response(status=429)
    c.tick(get,lambda:members,epoch=lambda:NOW)
    assert 1<=len(calls)<=4
    n=len(calls)
    c.tick(get,lambda:members,epoch=lambda:NOW+599)
    assert len(calls)==n

@pytest.mark.parametrize('stamp', ['2026-11-03T01:00:00+00:00','2026-11-05T03:00:00+00:00',
    '2026-11-07T01:00:00+00:00','2026-11-05T06:31:00+00:00'])
def test_no_holiday_lunch_weekend_afterhours_fetch(stamp):
    c=q.Collector()
    def no():raise AssertionError('membership not even read outside session')
    c.tick(no,no,epoch=lambda:datetime.fromisoformat(stamp).timestamp())


def test_loop_and_route_connection_cannot_alter_internal_price_or_fetch_in_get(monkeypatch):
    import argus_index_live
    source=Path('scanner.py').read_text();tree=ast.parse(source)
    route=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='api_argus_japan_watchlist')
    route.decorator_list=[]
    calls=[];base={'stocks':[{'symbol':'1001','price':100.0}],'status':'delayed'}
    def cached(*a,**k):
        assert k=={'allow_provider_fetch':False,'record_requested_symbols':False};return base
    env={'request':SimpleNamespace(args={'symbols':'1001'}),'get_japan_watchlist_snapshot':cached,
        '_note_jp_warm_hints':lambda s:None,'_with_cap_truth':lambda s,*a:s,
        '_sanitize_symbols':lambda s,*a:s,'_JP_SYM_RE':None,'_JP_DYN_MAX':50,'jsonify':lambda s:s}
    monkeypatch.setattr(q.collector,'document',lambda syms:calls.append(syms) or {'symbols':{'1001':{'price':123.5}}})
    exec(compile(ast.Module(body=[route],type_ignores=[]),'<real-route>','exec'),env)
    out=env['api_argus_japan_watchlist']()
    assert out['stocks'][0]['price']==100.0 and out['japaneseDelayed']['symbols']['1001']['price']==123.5
    assert 'japaneseDelayed' not in base and calls==[['1001']]
    # Single existing daemon owns the callback; the new module cannot start a timer.
    assert 'registered_tick=_jp_delayed_price_tick' in source
    assert 'Thread(target=' not in Path(q.__file__).read_text()


def test_index_records_http_and_shape_distinctly_and_success_clears(monkeypatch):
    import argus_index_live as live
    monkeypatch.setattr(live,'_state',{'quote':None,'error':None,'thread':None})
    class Broken:
        status_code=429
        def close(self):pass
    live.refresh_once(lambda *a,**k:Broken(),now_epoch=NOW)
    assert live.current_quote_safe()['lastErrorCode']=='HTTP_429'
    class Shape(Broken):
        status_code=200
        def json(self):return {}
    live.refresh_once(lambda *a,**k:Shape(),now_epoch=NOW+1)
    state=live.current_quote_safe()
    assert state['lastErrorCode']=='INVALID_QUOTE' and state['lastAttemptAt'].startswith('2026-11-05')


def test_late_body_completion_cannot_be_adopted_as_on_time():
    clock=[0]
    class Slow(Response):
        def iter_content(self, **kwargs):
            yield json.dumps(self.value).encode()
            clock[0]=9
    response=Slow()
    quote,error=q._read(lambda *a,**k:response,'1001',lambda:NOW,lambda:clock[0],8)
    assert quote is None and error=='TIME_BUDGET' and response.closed


def test_invalid_broker_price_does_not_suppress_the_backup():
    now=datetime.fromtimestamp(NOW,timezone.utc)
    stamp=now.isoformat()
    row={'provider':'TACHIBANA','freshness':'FRESH','marketStatus':'OPEN',
         'sourceTimestamp':stamp,'receivedAt':stamp,'sourceTimestampPrecision':'SECOND','price':123}
    doc={'enabled':True,'displayApproved':True,'mode':'DISPLAY','symbols':{'1001':row}}
    assert q.fresh_broker_symbols(doc,now)=={'1001'}
    for price in (None,0,float('nan'),True):
        assert q.fresh_broker_symbols({**doc,'symbols':{'1001':{**row,'price':price}}},now)==set()
