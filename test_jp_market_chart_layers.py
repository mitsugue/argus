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


def test_valuation_history_uses_same_basis_and_excludes_future_and_invalid_records():
    records = {
        '2026-10-01': {'date': '2026-10-01', 'basis': levels.EPS_BASIS, 'per': 16},
        '2026-10-02': {'date': '2026-10-02', 'basis': levels.EPS_BASIS, 'per': 20},
        '2026-10-05': {'date': '2026-10-05', 'basis': levels.EPS_BASIS, 'per': 90},
        '2026-09-30': {'date': '2026-09-30', 'basis': 'INDEX_WEIGHTED', 'per': 100},
        '2026-09-29': {'date': '2026-09-29', 'basis': levels.EPS_BASIS, 'per': float('nan')},
        '2026-09-28': {'date': '2026-09-27', 'basis': levels.EPS_BASIS, 'per': 40},
    }
    summary = chart.valuation_history(records, {'epsDate': '2026-10-02', 'eps': 4000, 'previousClose': 68001}, [bar(d, 68000) for d in records if d <= '2026-10-02' and d >= '2026-10-01'])
    assert summary['count'] == 2 and summary['median'] == 18
    assert summary['upperMultiple'] == 18 and summary['atOrAboveUpper'] == 1
    assert summary['minimum'] == 16 and summary['maximum'] == 20
    assert summary['sufficient'] is False and summary['actionAuthority'] is False
    assert summary['retrospective'] is True and summary['missingSessions'] == 0


def test_valuation_history_reports_gaps_and_never_claims_sparse_history_complete():
    first = date(2025, 1, 6)
    dates = [(first + timedelta(days=i)) for i in range(400)]
    dates = [d.isoformat() for d in dates if chart.clock.is_trading_day(chart.clock.JP_EQUITY, d)]
    records = {d: {'date': d, 'basis': levels.EPS_BASIS, 'per': 17} for d in dates[::3]}
    summary = chart.valuation_history(records, {'epsDate': dates[-1], 'eps': 4000, 'previousClose': 68001}, [bar(d, 68000) for d in dates])
    assert summary['count'] >= 60 and summary['missingSessions'] > summary['count']
    assert summary['sufficient'] is False
    assert chart.valuation_history(records, None, []) is None


def test_close_reprices_nearest_distance_stats_without_rewriting_morning_or_candidate():
    from copy import deepcopy
    rows = [bar((date(2026, 8, 24) + timedelta(days=i)).isoformat(), 68000 + i * 10)
            for i in range(43) if (date(2026, 8, 24) + timedelta(days=i)).weekday() < 5]
    eps = {'2026-10-05': {'date': '2026-10-05', 'basis': levels.EPS_BASIS,
                          'eps': 4000, 'per': 17.08, 'recordedAt': '2026-10-05T08:00:00Z'}}
    morning = levels.morning_map('2026-10-06', rows, {'2026-10-05': 4000}, eps_records=eps, created_at='2026-10-05T10:00:00Z')
    saved = deepcopy(morning)
    candidate = {'recordId': 'c1', 'candidate': 'S3', 'entryDate': '2026-10-06',
                 'target': {'kind': 'PER_LINE', 'multiple': 18, 'nikkei': 72000},
                 'stop': {'nikkei': 64000}, 'result': {'outcome': 'open'}}
    rows.append({**bar('2026-10-06', 71500), 'availableFrom': '2026-10-06T06:31:00Z'})
    result = chart.snapshot(rows, eps, morning, [candidate], now_iso='2026-10-06T06:32:00Z')
    shown = result['displayMap']
    assert shown['previousClose'] == 71500 and shown['valuationPending']
    up = next(r for r in result['nearest'] if r['side'] == 'UP')
    expected = levels.reach('UP', abs(72000 - 71500) / shown['atr14'])
    assert up['reachedWithin10SessionsPct'] == expected['reachedWithin10SessionsPct']
    assert up['sessionsMedian'] == expected['sessionsMedian']
    assert up['distancePct'] == pytest.approx((72000/71500-1)*100, abs=.001)
    assert up['distanceAtr'] == pytest.approx(500/shown['atr14'], abs=.001)
    eps['2026-10-06'] = {'date': '2026-10-06', 'basis': levels.EPS_BASIS,
                          'eps': 4200, 'per': 71500/4200, 'recordedAt': '2026-10-06T07:35:00Z'}
    refreshed = chart.snapshot(rows, eps, morning, [candidate], now_iso='2026-10-06T07:36:00Z')
    assert refreshed['displayMap']['eps'] == 4200 and not refreshed['displayMap']['valuationPending']
    assert next(r for r in refreshed['nearest'] if r['side'] == 'UP')['price'] == 75600
    assert refreshed['candidates'][0]['target'] == 72000
    assert morning == saved and candidate['target']['nikkei'] == 72000


def test_evening_display_history_remains_available_with_next_morning_record():
    rows = [bar((date(2026, 8, 24) + timedelta(days=i)).isoformat(), 68000 + i * 10)
            for i in range(43) if (date(2026, 8, 24) + timedelta(days=i)).weekday() < 5]
    rows.append({**bar('2026-10-06', 70000), 'availableFrom': '2026-10-06T06:31:00Z'})
    eps = {'2026-10-06': {'date': '2026-10-06', 'basis': levels.EPS_BASIS,
                          'eps': 4000, 'per': 17.5, 'recordedAt': '2026-10-06T07:35:00Z'}}
    tomorrow = levels.morning_map('2026-10-07', rows, {'2026-10-06': 4000}, eps_records=eps, created_at='2026-10-06T08:00:00Z')
    result = chart.snapshot(rows, eps, tomorrow, [], now_iso='2026-10-06T09:00:00Z')
    assert result['current'] is None
    assert result['displayMap']['asOf'] == '2026-10-06'
    assert result['valuationHistory']['lastDate'] == '2026-10-06'
    assert result['valuationHistory']['count'] == 1


def test_known_partial_eps_is_excluded_from_display_history_and_prior_lines():
    from copy import deepcopy
    rows=[bar((date(2026,8,24)+timedelta(days=i)).isoformat(),68000+i*10)
          for i in range(43) if (date(2026,8,24)+timedelta(days=i)).weekday()<5]
    complete={'date':'2026-10-05','eps':4000,'per':17,'basis':levels.EPS_BASIS,
              'recordedAt':'2026-10-05T08:00:00Z','coverage':{'members':225,'missingMarketCap':0}}
    morning=levels.morning_map('2026-10-06',rows,{'2026-10-05':4000},
                              eps_records={'2026-10-05':complete},created_at='2026-10-05T09:00:00Z')
    rows.append({**bar('2026-10-06',70000),'availableFrom':'2026-10-06T06:31:00Z'})
    partial={**complete,'date':'2026-10-06','eps':4549,'per':15.4,
             'recordedAt':'2026-10-06T06:51:00Z','coverage':{'members':225,'missingMarketCap':200}}
    eps={'2026-10-05':complete,'2026-10-06':partial}
    saved=deepcopy(morning)
    result=chart.snapshot(rows,eps,morning,[],now_iso='2026-10-06T08:00:00Z')
    assert result['displayMap']['previousClose']==70000
    assert result['displayMap']['eps']==4000 and result['displayMap']['valuationPending']
    assert result['valuationHistory']['count']==1 and result['valuationHistory']['lastDate']=='2026-10-05'
    rows.append(bar('2026-10-07',70100))
    bad_morning={**morning,'morningOf':'2026-10-07','eps':4549,'epsCoverage':partial['coverage']}
    after=chart.snapshot(rows,eps,bad_morning,[],now_iso='2026-10-08T00:00:00Z')
    assert after['points'][-1]['eps'] is None
    assert after['current'] is None and after['displayMap'] is None and after['nearest']==[]
    assert morning==saved and eps['2026-10-06']==partial
