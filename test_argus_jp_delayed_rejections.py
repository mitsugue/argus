"""Fixed rejection classes with frozen235 price-admission parity; no provider I/O."""
import copy
from datetime import datetime, timezone
import json
import pytest
import argus_jp_delayed_quotes as q
from test_argus_jp_delayed_quotes import Response, payload, MEMBERS, NOW

FROZEN_235_PARSE = "def parse_quote(payload, symbol, received):\n    try:\n        if not _number(received) or received <= 0:\n            return None\n        result = payload['chart']['result']\n        if payload['chart'].get('error') or len(result) != 1:\n            return None\n        m = result[0]['meta']\n        price, traded = m.get('regularMarketPrice'), m.get('regularMarketTime')\n        if m.get('symbol') != symbol + '.T' or m.get('currency') != 'JPY':\n            return None\n        if not _number(price) or price <= 0 or not _number(traded) or not 0 < traded <= received:\n            return None\n        source = datetime.fromtimestamp(traded, JST)\n        receipt = datetime.fromtimestamp(received, JST)\n        # A prior day's stale meta is not an intraday quote or today's change.\n        if source.date() != receipt.date() or not 9 * 60 <= source.hour * 60 + source.minute <= 15 * 60 + 30:\n            return None\n        source_session = market_session(JP_EQUITY, source)\n        if not source_session['isTradingDay'] or (source_session['session'] not in ('MORNING_SESSION', 'AFTERNOON_SESSION')\n                and source.hour * 60 + source.minute not in (11 * 60 + 30, 15 * 60 + 30)):\n            return None\n        previous = m.get('chartPreviousClose')\n        previous = previous if _number(previous) and previous > 0 else None\n        iso = lambda n: datetime.fromtimestamp(n, timezone.utc).isoformat()\n        return {'symbol': symbol, 'price': price, 'previousClose': previous,\n            'changePct': (price / previous - 1) * 100 if previous else None,\n            'sourceTimestamp': iso(traded), 'receivedAt': iso(received),\n            'delaySeconds': int(received - traded), 'provider': 'YAHOO_DELAYED',\n            'realtime': False, 'actionAuthority': False}\n    except (KeyError, TypeError, ValueError, IndexError, OverflowError, OSError):\n        return None"

def test_price_admission_and_public_price_fields_match_frozen235():
    scope = dict(vars(q))
    exec(compile(FROZEN_235_PARSE, '<frozen235-quote-parser>', 'exec'), scope)
    legacy = scope['parse_quote']
    cases = [payload(), {}, {'chart': {'result': None}}, {'chart': {'result': []}},
        {'chart': {'result': [{'meta': None}]}}, {'chart': {'result': [], 'error': {'description': 'not retained'}}}]
    for field in ('regularMarketPrice','regularMarketTime','chartPreviousClose','currency','symbol'):
        for value in (None, True, False, 0, -1, 123.5, float('nan'), float('inf'), 'untrusted-private-text'):
            candidate=payload();candidate['chart']['result'][0]['meta'][field]=value
            cases.append(candidate)
    for minute in (0, 8*60+59, 9*60, 11*60+30, 11*60+31, 12*60+29, 12*60+30, 15*60+30, 15*60+31):
        at=datetime(2026,11,5,minute//60,minute%60,tzinfo=q.JST).timestamp()
        cases.append(payload(regularMarketTime=at))
    for value in cases:
        original=json.dumps(value,sort_keys=True)
        def outcome(fn):
            try:return ('returned',fn(copy.deepcopy(value),'1001',NOW))
            except Exception as error:return ('raised',type(error).__name__)
        assert outcome(legacy)==outcome(q.parse_quote)
        assert json.dumps(value,sort_keys=True)==original

@pytest.mark.parametrize('patch,reason', [
    ({'regularMarketPrice':0},'PRICE_INVALID'),
    ({'regularMarketPrice':float('nan')},'PRICE_INVALID'),
    ({'regularMarketTime':NOW+1},'SOURCE_TIME_INVALID'),
    ({'regularMarketTime':NOW-86400},'SOURCE_PREVIOUS_SESSION'),
    ({'regularMarketTime':datetime(2026,11,5,0,0,tzinfo=timezone.utc).timestamp()-1},'SOURCE_OUTSIDE_CASH_SESSION'),
    ({'symbol':'untrusted-private-text'},'SYMBOL_MISMATCH'),
    ({'currency':'USD'},'CURRENCY_MISMATCH'),
])
def test_fixed_rejection_never_contains_response_text(patch,reason):
    quote,error=q.parse_quote_with_reason(payload(**patch),'1001',NOW)
    assert quote is None and error==reason
    assert 'untrusted-private-text' not in error


def test_body_shape_and_receipt_reasons_are_fixed():
    assert q.parse_quote_with_reason({},'1001',NOW)==(None,'QUOTE_SHAPE_INVALID')
    assert q.parse_quote_with_reason(payload(),'1001',None)==(None,'INVALID_RECEIPT')
    assert q.parse_quote_with_reason({'chart':{'result':[]}},'1001',NOW)==(None,'RESULT_UNAVAILABLE')


def test_normal_read_has_one_request_and_no_raw_body_in_reason():
    response=Response(payload(currency='not-copied'))
    calls=[]
    def get(*args,**kwargs):calls.append(kwargs);return response
    quote,error=q._read(get,'1001',lambda:NOW,lambda:0,8)
    assert quote is None and error=='CURRENCY_MISMATCH' and response.closed
    assert len(calls)==1 and calls[0]['allow_redirects'] is False
    assert calls[0]['timeout']==(2,4)


def test_previous_session_preserves_prior_receipt_and_failure_interval():
    c=q.Collector();clock=[NOW];calls=[]
    def get(*args,**kwargs):
        calls.append(1)
        return Response(payload(regularMarketTime=NOW-1200 if len(calls)==1 else NOW-86400))
    c.tick(get,lambda:MEMBERS,epoch=lambda:clock[0])
    prior=c.document(['1001'],now=clock[0])['symbols']['1001']
    clock[0]+=61;c.tick(get,lambda:MEMBERS,epoch=lambda:clock[0])
    kept=c.document(['1001'],now=clock[0])['symbols']['1001']
    assert kept['price']==prior['price'] and kept['receivedAt']==prior['receivedAt']
    assert kept['sourceTimestamp']==prior['sourceTimestamp']
    assert kept['lastError']=='SOURCE_PREVIOUS_SESSION' and len(calls)==2
    clock[0]+=119;c.tick(get,lambda:MEMBERS,epoch=lambda:clock[0]);assert len(calls)==2
    clock[0]+=1;c.tick(get,lambda:MEMBERS,epoch=lambda:clock[0]);assert len(calls)==3
