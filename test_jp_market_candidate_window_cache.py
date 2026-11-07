"""Current-only receipts must not rebuild sealed historical candidates."""
import copy
from unittest.mock import patch

import pytest
import jp_market_analogs as analogs
import jp_market_analog_backtest as backtest
import jp_market_price_paths as paths
from test_jp_market_analog_cache_revisions import BARS, DAYS, CUTOFF, row


def reaction(day, value=1):
    return row('material.CPI.3', value, date=day, periodEnd=day,
               availableFrom=day+'T07:00:00Z', eventId='synthetic:'+day,
               eventType='CPI', reactionWindowSessions=3)


@pytest.mark.parametrize('group', ['state_rows', 'condition_rows', 'reaction_rows', 'research_reaction_rows'])
def test_new_receipts_after_last_candidate_keep_history_and_refresh_current(group):
    values = {'state_rows': row('credit.loss_pct', -1),
              'condition_rows': row('synthetic.condition', 1),
              'reaction_rows': reaction(DAYS[35]),
              'research_reaction_rows': reaction(DAYS[35])}
    initial = {group: [values[group]]}
    today = {**values[group], 'date': DAYS[-1], 'periodEnd': DAYS[-1],
             'availableFrom': DAYS[-1]+'T07:00:00Z', 'value': 2 if 'reaction' in group else -1}
    latest = {group: [values[group], today]}
    untouched = copy.deepcopy((BARS, initial, latest))
    cache = {}
    original = analogs.build_episode
    builds = []
    def counted(**kwargs):
        if kwargs['cutoff'] != CUTOFF:
            builds.append(kwargs['cutoff'])
        return original(**kwargs)
    with patch.object(backtest, 'walk_forward', return_value={'horizons':{}, 'method':'synthetic-validation'}), \
         patch.object(backtest, 'weight_search', return_value={'status':'INSUFFICIENT_DATA', 'adopted':False}), \
         patch.object(analogs, 'build_episode', counted):
        first = paths.cached_index_comparison(BARS, cutoff=CUTOFF, session_dates=DAYS, backtest_cache=cache, **initial)
        before = len(builds)
        after = paths.cached_index_comparison(BARS, cutoff=CUTOFF, session_dates=DAYS, backtest_cache=cache, **latest)
        assert len(builds) == before, 'current-only receipts rebuilt historical candidates'
        fresh = paths.cached_index_comparison(BARS, cutoff=CUTOFF, session_dates=DAYS, backtest_cache={}, **latest)
        assert after == fresh
        if group in ('condition_rows', 'reaction_rows', 'state_rows'):
            assert after['comparison']['marketEvidence']['current'] != first['comparison']['marketEvidence']['current']
    assert (BARS, initial, latest) == untouched


@pytest.mark.parametrize('receipt_delta, rebuild', [(0, True), (1, False)])
def test_last_candidate_receipt_boundary(receipt_delta, rebuild):
    from datetime import datetime, timedelta
    last_day = DAYS[len(BARS) - analogs.AnalogPolicy().lookback_sessions - 2]
    boundary = datetime.fromisoformat(last_day + 'T23:59:59+00:00')
    received = (boundary + timedelta(seconds=receipt_delta)).isoformat()
    material = {**reaction(last_day), 'knownAt': received}
    cache = {}
    with patch.object(backtest, 'walk_forward', return_value={'horizons': {}, 'method': 'synthetic-validation'}), \
         patch.object(backtest, 'weight_search', return_value={'status': 'INSUFFICIENT_DATA', 'adopted': False}):
        paths.cached_index_comparison(BARS, cutoff=CUTOFF, session_dates=DAYS, backtest_cache=cache)
        prior = cache['sealedCandidates']
        result = paths.cached_index_comparison(BARS, cutoff=CUTOFF, session_dates=DAYS,
                                              backtest_cache=cache, reaction_rows=[material])
        assert (cache['sealedCandidates'] is not prior) is rebuild
        assert result == paths.cached_index_comparison(BARS, cutoff=CUTOFF, session_dates=DAYS,
                                                       backtest_cache={}, reaction_rows=[material])


def test_research_enable_disable_and_calendar_advance_keep_fresh_parity():
    cache = {}
    last_position = len(BARS) - analogs.AnalogPolicy().lookback_sessions - 2
    material = reaction(DAYS[last_position])
    with patch.object(backtest, 'walk_forward', return_value={'horizons': {}, 'method': 'synthetic-validation'}), \
         patch.object(backtest, 'weight_search', return_value={'status': 'INSUFFICIENT_DATA', 'adopted': False}):
        for bars, research in [(BARS[:-1], []), (BARS[:-1], [material]),
                               (BARS, [material]), (BARS, [])]:
            kwargs = dict(cutoff=bars[-1]['date']+'T12:00:00Z', session_dates=DAYS,
                          research_reaction_rows=research)
            result = paths.cached_index_comparison(bars, backtest_cache=cache, **kwargs)
            assert result == paths.cached_index_comparison(bars, backtest_cache={}, **kwargs)
            if research and bars == BARS:
                assert any(episode['reactions'] for episode in cache['sealedCandidates']['candidatesWith'])


@pytest.mark.parametrize('knowledge', [{'knownAt': 'invalid'}, {'knownAt': None, 'availableFrom': None}])
def test_unknown_receipt_remains_conservative(knowledge):
    material = {**reaction(DAYS[35]), **knowledge}
    cache = {}
    with patch.object(backtest, 'walk_forward', return_value={'horizons': {}, 'method': 'synthetic-validation'}), \
         patch.object(backtest, 'weight_search', return_value={'status': 'INSUFFICIENT_DATA', 'adopted': False}):
        paths.cached_index_comparison(BARS, cutoff=CUTOFF, session_dates=DAYS,
                                      backtest_cache=cache, reaction_rows=[material])
        prior_key = cache['sealedCandidates']['key']
        corrected = {**material, 'value': 9}
        result = paths.cached_index_comparison(BARS, cutoff=CUTOFF, session_dates=DAYS,
                                              backtest_cache=cache, reaction_rows=[corrected])
        assert cache['sealedCandidates']['key'] != prior_key
        assert result == paths.cached_index_comparison(BARS, cutoff=CUTOFF, session_dates=DAYS,
                                                       backtest_cache={}, reaction_rows=[corrected])
