"""No-analog reason and the recent-years yardstick for the Japan 10-year yield (2026-10-19)."""
from dataclasses import replace

import pytest

import jp_market_analog_backtest as backtest
import jp_market_analogs as analogs
from jp_market_price_paths import cached_index_comparison
from test_jp_market_analog_backtest import sessions, bars


def rows(field, values_by_day):
    unit = analogs.FEATURE_DEFINITIONS[field][0]
    return [{'instrumentId': analogs.INSTRUMENT, 'seriesId': field, 'date': d, 'value': v, 'unit': unit,
             'availableFrom': d + 'T09:00:00Z'} for d, v in values_by_day]


def test_recent_window_measures_only_the_listed_field_over_recent_years():
    days = sessions(2400, start='2016-10-03')
    pinned = [(d, 0.01 if i % 2 else -0.01) for i, d in enumerate(days) if d < '2023-10-19']
    moving = [(d, 0.1 if i % 2 else -0.1) for i, d in enumerate(days) if d >= '2023-10-19']
    data = rows('rate.jp10y_change5', pinned + moving) + rows('vix.level', [(d, 15 + i % 5) for i, d in enumerate(days)])
    full = analogs.robust_feature_scales(data)
    recent = analogs.robust_feature_scales(data, windows=analogs.recent_scale_windows('2026-10-19'))
    assert recent['rate.jp10y_change5']['scale'] > 5 * full['rate.jp10y_change5']['scale']
    assert recent['vix.level'] == full['vix.level']
    assert analogs.recent_scale_windows('2024-02-29') == {'rate.jp10y_change5': '2021-02-28'}


def comparison(days_count=700, **kw):
    days = sessions(days_count)
    closes, value, seed = [], 30000.0, 5
    for _ in days:
        seed = (seed * 1103515245 + 12345) % 2**31
        value *= 1 + ((seed / 2**31) - 0.5) * 0.02
        closes.append(round(value, 2))
    return days, cached_index_comparison(bars(days, closes), cutoff=days[-1] + 'T08:00:00Z', session_dates=days,
                                         horizon_sessions=5, **kw)


def test_no_close_window_names_the_closest_and_why():
    days, doc = comparison(policy=analogs.AnalogPolicy(maximum_distance=0.001))
    c = doc['comparison']
    assert c['candidates'] == [] and c['forecast']['line'] == []
    e = c['noAnalogExplanation']
    assert e['distance'] > 0.001 and e['anchorDate'] < days[-1]
    assert e['textJa'].startswith('今週は過去10年に似た局面がありません') and '主な違い' in e['textJa']
    _, normal = comparison()
    assert 'noAnalogExplanation' not in normal['comparison']


def test_ranking_policy_changes_only_scales_and_weights():
    days = sessions(80)
    closes = [30000 + 10 * i for i in range(80)]
    policy = analogs.AnalogPolicy()
    episodes = [analogs.build_episode(cutoff=d + 'T23:59:59Z', bars=bars(days[:i + 1], closes[:i + 1]), policy=policy)
                for i, d in enumerate(days) if i >= policy.lookback_sessions]
    current, candidates = episodes[-1], episodes[:-30]
    rescaled = replace(policy, state_scales=(('rate.jp10y_change5', 0.5),))
    base = analogs.select_episodes(current, candidates, session_dates=days, policy=policy)
    again = analogs.select_episodes(current, candidates, session_dates=days, policy=policy, ranking_policy=rescaled)
    assert base['selectionId'] != again['selectionId'] or base['policy'] == again['policy']
    with pytest.raises(ValueError, match='ranking_policy'):
        analogs.select_episodes(current, candidates, session_dates=days, policy=policy,
                                ranking_policy=replace(policy, maximum_distance=5))


def test_recent_yardstick_is_reported_and_used_only_when_adopted(monkeypatch):
    cache = {}
    _, doc = comparison(backtest_cache=cache)
    y = doc['comparison']['forecast']['yardstickResearch']
    assert y['adopted'] is cache['yardstickResearch']['adopted'] and y['recentScaleYears'] == {'rate.jp10y_change5': 3}
    calls = []
    original = backtest.walk_forward
    def spy(*a, **kw):
        calls.append(kw.get('recent_years'))
        return original(*a, **kw)
    monkeypatch.setattr(backtest, 'walk_forward', spy)
    monkeypatch.setattr(backtest, 'compare_material_reactions', lambda a, b: {'adopted': True, 'reason': 'forced'})
    seen = []
    real = analogs.select_episodes
    monkeypatch.setattr(analogs, 'select_episodes', lambda *a, **kw: seen.append(kw.get('ranking_policy')) or real(*a, **kw))
    _, forced = comparison(backtest_cache={})
    assert {'rate.jp10y_change5': 3} in calls and None in calls
    assert forced['comparison']['forecast']['yardstickResearch']['adopted'] is True
    assert seen and seen[-1] is not None



def test_reason_names_the_market_series_when_market_state_differs_most(monkeypatch):
    # Production on 2026-10-19: the closest week differed most in the market
    # state (Japan 10-year yield, NT ratio), so the reason names the series.
    real = analogs.select_episodes
    def no_candidates(*a, **kw):
        result = real(*a, **kw)
        return {**result, "selected": [], "admittedCount": 0, "closestRejected": {
            "anchorDate": "2019-05-06", "distance": 1.02,
            "componentDistances": {"priceShape": 0.4, "marketState": 1.6, "conditionOrder": None},
            "largestDifferences": [{"feature": "rate.jp10y_change5"}, {"feature": "nt.ratio_change5"},
                                   {"feature": "vix.level"}]}}
    monkeypatch.setattr(analogs, "select_episodes", no_candidates)
    _, doc = comparison()
    assert doc['comparison']['noAnalogExplanation']['textJa'].endswith(
        '主な違い：日本10年金利の変化幅・NT倍率の変化率。')
