"""Production bridge excludes retired dedicated feeds, even with old settings."""
import importlib.util
from datetime import datetime, timezone


def load(monkeypatch):
    monkeypatch.setenv('PUSH_SYMBOLS','JP.5803,US.NVDA')
    monkeypatch.setenv('PUSH_INTERVAL_SEC','15')
    monkeypatch.setenv('CAP_TEST_ENABLED','1')
    monkeypatch.setenv('JP_MOVER_SWEEP_ENABLED','1')
    spec=importlib.util.spec_from_file_location('shared_bridge','bridge/moomoo_push.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def test_shared_cycle_cannot_acquire_individuals_or_flow(monkeypatch):
    m=load(monkeypatch);calls=[];posted=[]
    monkeypatch.setattr(m,'shared_session_open',lambda:True)
    monkeypatch.setattr(m,'fetch_market_quotes',lambda qc,codes,**kw:(calls.append(codes) or [
        {'market':'US','symbol':'SPY','exchangeTs':'2026-09-18T15:00:00Z'},
        {'market':'US','symbol':'NVDA'}],False))
    class Response:
        ok=True
        def json(self):return {'accepted':1}
    monkeypatch.setattr(m,'_push_quotes',lambda rows:(posted.extend(rows),Response())[1])
    for name in ('fetch_flow','_fetch_jp_watchlist_codes','run_capability_test','sweep_jp_movers','sweep_us_movers'):
        monkeypatch.setattr(m,name,lambda *a,**kw:(_ for _ in ()).throw(AssertionError('retired call')))
    assert m.INTERVAL==300 and set(m.CODES)==set(m._REGIME_ETF_CODES)
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


def test_production_entry_point_uses_only_shared_cycle_and_health(monkeypatch):
    import pytest
    m=load(monkeypatch);events=[]
    class Context:
        def close(self):events.append('closed')
    monkeypatch.setattr(m,'TOKEN','test-only')
    monkeypatch.setattr(m,'OpenQuoteContext',lambda **kw:Context())
    monkeypatch.setattr(m,'shared_quote_cycle',lambda qc:events.append('shared'))
    monkeypatch.setattr(m,'send_heartbeat',lambda **kw:events.append(('health',kw)))
    def stop(_):raise KeyboardInterrupt()
    monkeypatch.setattr(m.time,'sleep',stop)
    for name in ('fetch_flow','_fetch_jp_watchlist_codes','run_capability_test','sweep_jp_movers','sweep_us_movers'):
        monkeypatch.setattr(m,name,lambda *a,**kw:(_ for _ in ()).throw(AssertionError('retired call')))
    with pytest.raises(KeyboardInterrupt):m.main()
    assert events==['shared',('health',{'disable_jp':True}),'closed']
