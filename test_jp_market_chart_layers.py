from datetime import date, timedelta
import json
import pytest

import jp_market_chart_layers as chart
import jp_market_level_map as levels


def bar(day, close):
    return {'date': day, 'close': close, 'high': close * 1.01, 'low': close * .99}


def test_previous_session_eps_no_future_fill_or_current_unclosed_bar():
    rows = [bar('2026-10-01', 68957), bar('2026-10-02', 68309.46), bar('2026-10-05', 70000)]
    eps = {'2026-10-01': {'eps': 3900}, '2026-10-02': {'eps': 3932.61}, '2026-10-05': {'eps': 4000}}
    morning = {'morningOf': '2026-10-05', 'eps': 3932.61, 'epsDate': '2026-10-02', 'previousClose': 68309.46,
               'previousSession': '2026-10-02', 'atr14': 1235.05}
    result = chart.snapshot(rows, eps, morning, [], now_iso='2026-10-05T00:01:00Z')
    assert result['points'] == [dict(date='2026-10-01', close=68957, eps=None, epsDate=None),
                                dict(date='2026-10-02', close=68309.46, eps=3900, epsDate='2026-10-01')]
    assert result['current']['eps'] == 3932.61
    for multiple in (16, 17, 18, 19):
        assert result['current']['eps'] * multiple == pytest.approx(morning['eps'] * multiple)
    for row in result['nearest']:
        expected = levels.reach(row['side'], abs(row['price'] - morning['previousClose']) / morning['atr14'])
        assert row['reachedWithin10SessionsPct'] == expected['reachedWithin10SessionsPct']
    assert result['actionAuthority'] is False and result['automaticAiCalls'] == 0


def test_current_bar_available_time_and_completed_pivot_confirmation():
    rows = [bar('2026-09-28', 65000), bar('2026-09-29', 68000), bar('2026-10-01', 68957), bar('2026-10-02', 68309)]
    result = chart.snapshot(rows, {}, None, [], now_iso='2026-10-05T00:00:00Z')
    assert result['pending']['kind'] == 'TOP'
    assert result['pending']['confirmPrice'] == 66198.72
    rows.append({**bar('2026-10-05', 66100), 'availableFrom': '2026-10-05T07:00:00Z'})
    before = chart.snapshot(rows, {}, None, [], now_iso='2026-10-05T06:00:00Z')
    after = chart.snapshot(rows, {}, None, [], now_iso='2026-10-05T07:01:00Z')
    assert before['pending']['kind'] == 'TOP'
    assert after['pending']['kind'] == 'BOTTOM'
    assert after['pivots'][-1]['date'] == '2026-10-01'
    assert after['pivots'][-1]['price'] == 68957
    assert after['pivots'][-1]['confirmedOn'] == '2026-10-05'


def test_candidates_only_materialized_open_and_holiday_deadline():
    record = {'recordId': 'c1', 'candidate': 'R1', 'entryDate': '2026-10-05', 'target': {'nikkei': 65575},
              'stop': {'nikkei': 68995}, 'result': {'outcome': 'open'}, 'deadline': {'bd20': None}}
    result = chart.snapshot([bar('2026-10-02', 68309)], {}, None,
                            [record, {**record, 'result': {'outcome': 'reached'}}, {'result': {'outcome': 'open'}}], now_iso='2026-10-05T01:00:00Z')
    assert len(result['candidates']) == 1
    assert result['candidates'][0]['end'] == '2026-11-02'  # 10/12は休場
    assert result['candidates'][0]['target'] == 65575


def test_small_payload_no_constituents_and_missing_eps_stays_missing():
    first = date(2020, 1, 1)
    rows = [bar((first + timedelta(days=i)).isoformat(), 60000 + i) for i in range(2500)]
    result = chart.snapshot(rows, {}, None, [], now_iso='2026-10-05T00:00:00Z')
    assert len(result['points']) <= 185
    assert all(p['eps'] is None for p in result['points'])
    assert len(json.dumps(result)) < 35000


def test_moving_candidate_uses_current_eps_without_changing_saved_record():
    record = {'recordId': 'c1', 'candidate': 'S3', 'entryDate': '2026-10-01',
              'target': {'kind': 'PER_LINE', 'multiple': 18, 'nikkei': 69000},
              'stop': {'nikkei': 64000}, 'result': {'outcome': 'open'}}
    morning = {'morningOf': '2026-10-05', 'eps': 3932.61, 'epsDate': '2026-10-02',
               'previousClose': 68309, 'previousSession': '2026-10-02', 'atr14': 1235}
    result = chart.snapshot([bar('2026-10-02', 68309)], {}, morning, [record], now_iso='2026-10-05T01:00:00Z')
    assert result['candidates'][0]['target'] == 70786.98
    assert result['candidates'][0]['movingTarget'] is True
    assert record['target']['nikkei'] == 69000


def test_missing_price_session_does_not_turn_older_eps_into_previous_session():
    result = chart.snapshot([bar('2026-10-01', 68957), bar('2026-10-05', 69000)],
                            {'2026-10-01': {'eps': 3900}}, None, [], now_iso='2026-10-06T00:00:00Z')
    assert result['points'][-1]['eps'] is None
