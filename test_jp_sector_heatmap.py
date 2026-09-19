from datetime import datetime, timezone
import jp_sector_heatmap as h

NOW = datetime(2026, 9, 18, 1, 0, tzinfo=timezone.utc)
SECTORS = [{'symbol': '1631', 'nameJa': '銀行'}]

def data():
    q = {s: {'price': p, 'sourceTimestamp': '2026-09-18T00:50:00Z', 'source': 'test'}
         for s,p in [('1631', 110), ('1306', 102)]}
    history = {s: {'2026-09-17': 100, '2026-09-11': 90, '2026-08-21': 80} for s in q}
    return q, history

def test_same_session_returns_and_relative_strength_have_distinct_values():
    q,b=data(); result=h.project(q,b,SECTORS,now=NOW); r=result['rows'][0]
    assert r['periods']['1']['returnPct']==10
    assert r['periods']['1']['relativeToBenchmarkPct']==8
    assert not result['actionAuthority']
    assert result['isToday']

def test_previous_day_refetch_is_not_today_and_not_zero():
    q,b=data(); q['1631']['sourceTimestamp']='2026-09-17T06:30:00Z'
    r=h.project(q,b,SECTORS,now=NOW)['rows'][0]
    assert r['state']=='NOT_UPDATED'
    assert all(v['returnPct'] is None for v in r['periods'].values())

def test_future_or_delayed_quote_cannot_color_as_current():
    for stamp, state in [('2026-09-18T01:05:00Z','INVALID_TIME'),('2026-09-18T00:00:00Z','DELAYED')]:
        q,b=data();q['1631']['sourceTimestamp']=stamp
        r=h.project(q,b,SECTORS,now=NOW)['rows'][0]
        assert r['state']==state and r['periods']['1']['returnPct'] is None

def test_missing_anchor_and_benchmark_do_not_fabricate_returns():
    q,b=data(); del b['1631']['2026-09-11'];q.pop('1306')
    r=h.project(q,b,SECTORS,now=NOW)['rows'][0]
    assert r['periods']['5']['returnPct'] is None
    assert r['periods']['1']['returnPct']==10
    assert r['periods']['1']['relativeToBenchmarkPct'] is None

def test_weekend_keeps_last_session_label_separate_from_today():
    q,b=data();r=h.project(q,b,SECTORS,now=datetime(2026,9,19,1,tzinfo=timezone.utc))
    assert r['session']['session']=='WEEKEND_CLOSED'
    assert r['targetDate']=='2026-09-18' and not r['isToday']
