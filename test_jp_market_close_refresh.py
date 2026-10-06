from copy import deepcopy
from datetime import datetime, timezone
import pytest
import jp_market_close_refresh as policy
import jp_market_chart_layers as layers
import jp_market_level_map as levels


def test_slots_are_bounded_holiday_aware_and_prices_do_not_wait_for_per():
    assert policy.due('2026-10-06T06:30:59Z', close_date='2026-10-05', eps_date='2026-10-05') is None
    first = policy.due('2026-10-06T06:31:00Z')
    assert first['price'] and not first['valuation']
    assert policy.due('2026-10-06T06:34:59Z', last_slot=first['slot']) is None
    assert policy.due('2026-10-06T06:35:00Z', last_slot=first['slot'])['price']
    assert policy.due('2026-10-06T07:05:00Z', close_date='2026-10-06') is None
    assert policy.due('2026-10-06T07:34:59Z', close_date='2026-10-06') is None
    later = policy.due('2026-10-06T07:35:00Z', close_date='2026-10-06')
    assert later['valuation'] and not later['price']
    assert policy.due('2026-10-06T07:35:00Z', last_slot=later['slot'], close_date='2026-10-06') is None
    assert policy.due('2026-10-06T08:05:00Z', close_date='2026-10-06')['valuation']
    assert policy.due('2026-10-06T07:05:00Z', close_date='2026-10-06', eps_date='2026-10-06') is None
    assert policy.due('2026-10-12T06:31:00Z', close_date='2026-10-09', eps_date='2026-10-09') is None
    assert policy.due('2026-10-10T06:31:00Z', close_date='2026-10-09', eps_date='2026-10-09') is None
    assert policy.due('2026-10-06T13:00:00Z', close_date='2026-10-06', eps_date='2026-10-06') is None


def test_close_projection_keeps_morning_record_and_dates_old_eps_until_ready():
    from datetime import date, timedelta
    rows = []
    day = date(2026, 8, 24)
    while day <= date(2026, 10, 6):
        if policy.clock.is_trading_day(policy.clock.JP_EQUITY, day):
            rows.append({'date': day.isoformat(), 'close': 70000, 'high': 71000, 'low': 69000,
                         'availableFrom': day.isoformat()+'T07:00:00Z'})
        day += timedelta(days=1)
    morning = levels.morning_map('2026-10-06', rows, {'2026-10-05':4000}, created_at='2026-10-06T00:00:00Z')
    original = deepcopy(morning)
    waiting = layers.snapshot(rows, {}, morning, [], now_iso='2026-10-06T07:00:01Z')
    shown = waiting['displayMap']
    assert shown['previousSession'] == '2026-10-06' and shown['epsDate'] == '2026-10-05'
    assert shown['valuationPending'] and shown['displayOnly'] and shown['per'] == 17.5
    new = {'2026-10-06': {'date':'2026-10-06','eps':4200,'per':70000/4200,'basis':levels.EPS_BASIS,
                          'recordedAt':'2026-10-06T09:05:00Z'}}
    ready = layers.snapshot(rows, new, morning, [], now_iso='2026-10-06T09:05:01Z')
    assert not ready['displayMap']['valuationPending'] and ready['displayMap']['eps'] == 4200
    assert ready['current']['eps'] == 4000 and morning == original
    before = layers.snapshot(rows, new, morning, [], now_iso='2026-10-06T07:00:01Z')
    assert before['displayMap']['eps'] == 4000  # future receipt excluded
    assert layers.snapshot(rows, new, morning, [], now_iso='2026-10-06T06:00:00Z')['displayMap'] is None
    # A newly saved next-morning map must not make today's closing display
    # claim it is tomorrow's morning or revert to the old closing label.
    tomorrow = levels.morning_map('2026-10-07', rows, {'2026-10-06':4200}, created_at='2026-10-06T09:05:00Z')
    assert layers.snapshot(rows, new, tomorrow, [], now_iso='2026-10-06T09:05:01Z')['displayMap']['asOf'] == '2026-10-06'
    offset = deepcopy(new)
    offset['2026-10-06']['recordedAt'] = '2026-10-06T18:05:00+09:00'
    assert layers.snapshot(rows, offset, morning, [], now_iso='2026-10-06T09:05:01Z')['displayMap']['eps'] == 4200


@pytest.mark.parametrize('reported_minute,price,now_hour,now_minute,accepted',[
    (30,70000,6,31,True),(29,70000,6,31,False),(30,69999,6,31,False),
    (30,70000,6,29,False),(None,70000,7,5,True),
])
def test_daily_bar_needs_final_source_metadata_before_conservative_cutoff(monkeypatch,
    reported_minute,price,now_hour,now_minute,accepted):
    import scanner
    now = datetime(2026,10,6,now_hour,now_minute,tzinfo=timezone.utc)
    class Clock(datetime):
        @classmethod
        def now(cls,tz=None): return now.astimezone(tz) if tz else now.replace(tzinfo=None)
    meta = {'gmtoffset':32400,'regularMarketPrice':price}
    if reported_minute is not None:
        meta['regularMarketTime'] = datetime(2026,10,6,6,reported_minute,tzinfo=timezone.utc).timestamp()
    body = {'chart':{'result':[{'meta':meta,
        'timestamp':[datetime(2026,10,6,0,tzinfo=timezone.utc).timestamp()],
        'indicators':{'quote':[{'open':[69000],'high':[71000],'low':[68000],
                               'close':[70000],'volume':[0]}]}}]}}
    class Response:
        status_code=200
        content=b'synthetic'
        def json(self): return body
        def close(self): pass
    monkeypatch.setattr(scanner,'datetime',Clock)
    monkeypatch.setattr(scanner.time,'time',lambda:now.timestamp())
    monkeypatch.setattr(scanner,'_ai_now_iso',lambda:now.isoformat().replace('+00:00','Z'))
    monkeypatch.setattr(scanner,'_JP_MARKET_ENGINE_INDEX_OHLCV_CACHE',{})
    monkeypatch.setattr(scanner.requests,'get',lambda *a,**kw:Response())
    rows = scanner._yahoo_index_ohlcv('^N225','NIKKEI_225_INDEX',fetch=True,available_hour_utc=7)
    assert bool(rows) is accepted
    if accepted and now_hour == 6:
        assert rows[0]['availableFrom'] == '2026-10-06T06:31:00Z'


def test_worker_is_one_slot_only_current_valuation_and_no_full_collection(monkeypatch):
    import scanner
    calls=[]
    rows=[{'date':'2026-10-06','close':70000,'high':71000,'low':69000,
           'availableFrom':'2026-10-06T06:31:00Z'}]
    monkeypatch.setattr(scanner,'_NIKKEI_CLOSE_REFRESH',{'lastSlot':None})
    monkeypatch.setattr(scanner,'_LEVEL_MAP',{'eps':{}})
    monkeypatch.setattr(scanner,'_ai_now_iso',lambda:'2026-10-06T07:35:00Z')
    monkeypatch.setattr(scanner,'_nikkei_chart_rows',lambda:rows)
    def warm(values,*,current_only):
        calls.append(current_only)
        scanner._LEVEL_MAP['eps']['2026-10-06']={'eps':4000}
    monkeypatch.setattr(scanner,'_level_map_warm',warm)
    monkeypatch.setattr(scanner.requests,'get',lambda *a,**kw:pytest.fail('no price/provider fetch here'))
    assert scanner._nikkei_close_refresh_tick()['status'] == 'AVAILABLE'
    assert scanner._nikkei_close_refresh_tick()['status'] == 'not_due'
    assert calls == [True]


def test_stored_comparison_receives_fresh_display_without_recalculating_it(monkeypatch):
    import scanner
    saved = {'comparison': {'asOf':'2026-10-05'}, 'researchCache': {'recordSha256':'a'*64},
             'levelMap': {'old':True}, 'automaticAiCalls':0, 'actionAuthority':False}
    original = deepcopy(saved)
    monkeypatch.setattr(scanner,'_index_research_read',lambda key:deepcopy(saved))
    shown = {'chart': {'points':[{'date':'2026-10-06','close':70000}]}}
    monkeypatch.setattr(scanner,'_level_map_public',lambda:shown)
    monkeypatch.setattr(scanner,'_jp_market_comparison_calculate',lambda *a:pytest.fail('no analog recalculation'))
    monkeypatch.setattr(scanner.requests,'get',lambda *a,**kw:pytest.fail('no GET acquisition'))
    reply = scanner._jp_market_comparison_cached(5)
    assert reply['levelMap'] == shown and reply['comparison']['asOf'] == '2026-10-05'
    assert reply['researchCache']['recordSha256'] == 'a'*64 and saved == original
    assert scanner._jp_market_comparison_cached(10)['levelMap'] == {'old':True}


def test_newer_cache_window_visible_before_slow_history_refresh(monkeypatch):
    import scanner
    def row(day,close):
        return {'instrumentId':'NIKKEI_225_INDEX','date':day,'open':close,'high':close+1,
                'low':close-1,'close':close,'volume':0,'availableFrom':day+'T07:00:00Z'}
    held={'data':[row('2026-10-05',69000)],'currentSourceAcquiredAt':'2026-10-06T06:00:00Z'}
    monkeypatch.setattr(scanner,'_N225_ANALOG_HISTORY',held)
    monkeypatch.setattr(scanner,'_JP_MARKET_ENGINE_INDEX_OHLCV_CACHE',{'^N225':{
        'data':[row('2026-10-06',70000)],'acquiredAt':'2026-10-06T07:00:00Z'}})
    assert scanner._nikkei_chart_rows()[-1]['close'] == 70000
    assert len(held['data']) == 1
    scanner._JP_MARKET_ENGINE_INDEX_OHLCV_CACHE['^N225']['acquiredAt']='2026-10-05T07:00:00Z'
    assert scanner._nikkei_chart_rows() == held['data']


def test_chart_survives_unavailable_analog_comparison(monkeypatch):
    import scanner
    monkeypatch.setattr(scanner, '_index_research_read', lambda key: None)
    shown = {'chart': {'points': [{'date': '2026-10-06', 'close': 70000}]}}
    monkeypatch.setattr(scanner, '_level_map_public', lambda: shown)
    monkeypatch.setattr(scanner.requests, 'get', lambda *a, **kw: pytest.fail('cached read only'))
    reply = scanner._jp_market_comparison_cached(5)
    assert reply['comparison'] is None
    assert reply['levelMap'] == shown


def test_missing_latest_closed_session_recovers_after_night_restart_and_holiday():
    late = policy.due('2026-10-06T13:28:00Z', close_date='2026-10-05', eps_date='2026-10-05')
    assert late['session'] == '2026-10-06' and late['price'] and late['valuation']
    assert policy.due('2026-10-06T13:29:00Z', last_slot=late['slot'], close_date='2026-10-05') is None
    early = policy.due('2026-10-06T16:05:00Z', close_date='2026-10-05', eps_date='2026-10-05')
    assert early['session'] == '2026-10-06'
    assert policy.due('2026-10-06T16:05:00Z', close_date='2026-10-06', eps_date='2026-10-06') is None
    holiday = policy.due('2026-10-12T01:05:00Z', close_date='2026-10-08', eps_date='2026-10-08')
    assert holiday['session'] == '2026-10-09'


def test_completed_bar_cutoff_compares_instants_not_timestamp_text(monkeypatch):
    import scanner
    row = {'date': '2026-10-06', 'close': 70000, 'high': 71000, 'low': 69000,
           'availableFrom': '2026-10-06T15:31:00+09:00'}
    now = '2026-10-06T06:31:01Z'
    assert scanner._level_map_completed_bars([row], now)[-1]['date'] == '2026-10-06'
    assert layers.snapshot([row], {}, None, [], now_iso=now)['points'][-1]['date'] == '2026-10-06'
    assert scanner._level_map_completed_bars([row], '2026-10-06T15:30:59+09:00') == []
    row['availableFrom'] = 'not-a-time'
    assert scanner._level_map_completed_bars([row], now) == []
