"""Production bridge excludes retired dedicated feeds, even with old settings."""
import importlib.util
from datetime import datetime, timezone


def load(monkeypatch):
    monkeypatch.setenv('PUSH_SYMBOLS','JP.5803,US.NVDA')
    monkeypatch.setenv('PUSH_INTERVAL_SEC','15')
    monkeypatch.setenv('CAP_TEST_ENABLED','1')
    monkeypatch.setenv('JP_MOVER_SWEEP_ENABLED','1')
    import sys, types
    monkeypatch.setitem(sys.modules, 'moomoo', types.SimpleNamespace(OpenQuoteContext=None, RET_OK=0))
    spec=importlib.util.spec_from_file_location('shared_bridge','bridge/moomoo_push.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def test_shared_cycle_ignores_old_individual_settings_and_keeps_flow_retired(monkeypatch):
    m=load(monkeypatch);calls=[];posted=[]
    monkeypatch.setattr(m,'shared_session_open',lambda:True)
    monkeypatch.setattr(m,'registered_us_codes',lambda:list(m._REGIME_ETF_CODES))
    monkeypatch.setattr(m,'fetch_market_quotes',lambda qc,codes,**kw:(calls.append(codes) or [
        {'market':'US','symbol':'SPY','exchangeTs':'2026-09-18T15:00:00Z'},
        {'market':'US','symbol':'NVDA'}],False))
    class Response:
        ok=True
        def json(self):return {'accepted':1}
    monkeypatch.setattr(m,'_push_quotes',lambda rows:(posted.extend(rows),Response())[1])
    for name in ('fetch_flow','_fetch_jp_watchlist_codes','run_capability_test','sweep_jp_movers','sweep_us_movers'):
        monkeypatch.setattr(m,name,lambda *a,**kw:(_ for _ in ()).throw(AssertionError('retired call')))
    assert m.INTERVAL==30 and set(m.CODES)==set(m._REGIME_ETF_CODES)
    assert m.shared_quote_cycle(object())==1
    assert calls==[{'JP':[],'US':m._REGIME_ETF_CODES}]
    assert posted==[{'market':'US','symbol':'SPY','exchangeTs':'2026-09-18T15:00:00Z'}]
    monkeypatch.setattr(m,'shared_session_open',lambda:False)
    assert m.shared_quote_cycle(object())==0 and len(calls)==1


def test_shared_session_uses_dst_holidays_and_early_close(monkeypatch):
    m=load(monkeypatch)
    def open_at(value):return m.shared_session_open(datetime.fromisoformat(value).replace(tzinfo=timezone.utc))
    assert open_at('2026-09-18T14:00:00')
    assert not open_at('2026-09-19T14:00:00')
    assert not open_at('2026-09-07T14:00:00')
    assert not open_at('2026-11-27T18:30:00')
    assert not open_at('2026-12-01T14:00:00')
    assert open_at('2026-12-01T15:00:00')


def test_health_continues_when_opend_worker_is_stuck(monkeypatch):
    import pytest
    m=load(monkeypatch);events=[];ticks=iter([0,301,602])
    class StuckWorker:
        def __init__(self, **kw): pass
        def start(self): events.append('worker')
        def is_alive(self): return True
    monkeypatch.setattr(m,'TOKEN','test-only')
    monkeypatch.setattr(m,'OpenQuoteContext',object)
    monkeypatch.setattr(m,'shared_session_open',lambda:True)
    monkeypatch.setattr(m,'Thread',StuckWorker)
    monkeypatch.setattr(m.time,'monotonic',lambda:next(ticks))
    monkeypatch.setattr(m,'send_heartbeat',lambda **kw:events.append('health') or 200)
    def stop(_):
        if events.count('health')==3: raise KeyboardInterrupt()
    monkeypatch.setattr(m.time,'sleep',stop)
    with pytest.raises(KeyboardInterrupt):m.main()
    assert events==['health','worker','health','health']


def test_closed_session_never_initializes_opend(monkeypatch):
    import pytest
    m=load(monkeypatch);events=[]
    monkeypatch.setattr(m,'TOKEN','test-only')
    monkeypatch.setattr(m,'OpenQuoteContext',lambda **kw:events.append('unexpected'))
    monkeypatch.setattr(m,'shared_session_open',lambda:False)
    monkeypatch.setattr(m,'send_heartbeat',lambda **kw:events.append('health') or 200)
    monkeypatch.setattr(m.time,'sleep',lambda _:(_ for _ in ()).throw(KeyboardInterrupt()))
    with pytest.raises(KeyboardInterrupt):m.main()
    assert events==['health']


def test_quote_worker_releases_context_on_failure(monkeypatch):
    m=load(monkeypatch);events=[]
    class Context:
        def close(self):events.append('closed')
    monkeypatch.setattr(m,'OpenQuoteContext',lambda **kw:Context())
    monkeypatch.setattr(m,'shared_quote_cycle',lambda qc:(_ for _ in ()).throw(RuntimeError()))
    m._shared_quote_worker()
    assert events==['closed']


def test_registered_price_cycle_accepts_only_confirmed_names_and_preserves_source_time(monkeypatch):
    m = load(monkeypatch); posted = []; calls = []
    monkeypatch.setattr(m, 'shared_session_open', lambda: True)
    monkeypatch.setattr(m, 'registered_us_codes', lambda: m._REGIME_ETF_CODES + ['US.NVDA'])
    rows = [{'market': 'US', 'symbol': 'NVDA', 'price': 123.4,
             'exchangeTs': '2026-10-07T14:00:00Z'},
            {'market': 'US', 'symbol': 'NOTREGISTERED', 'price': 99},
            {'market': 'JP', 'symbol': '1001', 'price': 1000}]
    def fetch(qc, codes, **kwargs):
        calls.append((codes, kwargs)); return rows, False
    monkeypatch.setattr(m, 'fetch_market_quotes', fetch)
    class Response:
        ok = True
        def json(self): return {'accepted': 1}
    monkeypatch.setattr(m, '_push_quotes', lambda data: (posted.extend(data), Response())[1])
    monkeypatch.setattr(m, 'record_push_result', lambda data, accepted: None)
    assert m.shared_quote_cycle(object()) == 1
    assert posted == rows[:1]
    assert calls[0][0]['JP'] == [] and calls[0][1]['disable_jp'] is True
    assert 'US.NVDA' in calls[0][0]['US']


def test_registered_list_is_private_bounded_removed_and_fail_closed(monkeypatch):
    m = load(monkeypatch); requests = []; body = {'scope': 'registered', 'codes': ['US.NVDA', 'JP.1001', 'US.!!']}
    class Response:
        ok = True
        def json(self): return body
    def get(url, **kwargs):
        requests.append((url, kwargs)); return Response()
    monkeypatch.setattr(m.requests, 'get', get)
    monkeypatch.setattr(m, 'TOKEN', 'test-only')
    assert m.registered_us_codes() == m._REGIME_ETF_CODES + ['US.NVDA']
    assert requests[0][1]['params'] == {'scope': 'registered'}
    assert requests[0][1]['headers'] == {'X-ARGUS-ADMIN-TOKEN': 'test-only'}
    body['codes'] = []
    assert m.registered_us_codes() == m._REGIME_ETF_CODES
    body['codes'] = [f'US.A{i}' for i in range(100)]
    assert len(m.registered_us_codes()) == 32
    body['scope'] = 'broad'
    assert m.registered_us_codes() == m._REGIME_ETF_CODES
    monkeypatch.setattr(m.requests, 'get', lambda *a, **kw: (_ for _ in ()).throw(RuntimeError()))
    assert m.registered_us_codes() == m._REGIME_ETF_CODES


def test_zero_acceptance_never_claims_price_push_success(monkeypatch):
    m = load(monkeypatch)
    monkeypatch.setattr(m, 'shared_session_open', lambda: True)
    monkeypatch.setattr(m, 'registered_us_codes', lambda: m._REGIME_ETF_CODES)
    monkeypatch.setattr(m, 'fetch_market_quotes', lambda *a, **kw: ([{'market': 'US', 'symbol': 'SPY'}], False))
    class Response:
        ok = True
        def json(self): return {'accepted': 0}
    monkeypatch.setattr(m, '_push_quotes', lambda rows: Response())
    monkeypatch.setattr(m, 'record_push_result', lambda *a: (_ for _ in ()).throw(AssertionError('not received')))
    assert m.shared_quote_cycle(object()) == 0


def test_invalid_snapshot_row_never_discards_other_registered_prices(monkeypatch):
    m = load(monkeypatch)
    class Frame:
        def iterrows(self):
            return enumerate([
                {'code': 'US.AAPL', 'last_price': 120, 'prev_close_price': 119, 'volume': 1000},
                {'code': 'US.TEST', 'last_price': float('nan'), 'volume': float('nan')},
                {'code': 'US.MU', 'last_price': 110, 'prev_close_price': float('nan'), 'volume': float('nan')},
                {'code': 'US.BAD', 'last_price': float('inf'), 'volume': 1000}])
    rows = m.rows_from_snapshot(Frame())
    assert [r['symbol'] for r in rows] == ['AAPL', 'MU']
    assert rows[0]['volume'] == 1000 and rows[0]['changeAbs'] == 1
    assert rows[1]['volume'] == 0 and rows[1]['changePct'] == 0
    import json
    json.dumps(rows, allow_nan=False)
