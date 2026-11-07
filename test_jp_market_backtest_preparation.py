"""Prepared per-episode work preserves exact distances and held-out results."""
import copy
import hashlib
import json
import math
import random
from datetime import date, timedelta

import pytest
import jp_market_analog_backtest as backtest
from jp_market_analogs import AnalogPolicy, FEATURE_DEFINITIONS, INSTRUMENT, _edit_distance, _order_pattern, build_episode


def matrix_distance(left, right):
    previous = list(range(len(right) + 1))
    for i, token in enumerate(left, 1):
        current = [i]
        for j, other in enumerate(right, 1):
            current.append(min(current[-1] + 1, previous[j] + 1, previous[j - 1] + (token != other)))
        previous = current
    return previous[-1] / max(len(left), len(right), 1)


@pytest.mark.parametrize('mutable', [False, True])
def test_prepared_orders_equal_independent_matrix_and_keep_inputs(mutable):
    randomizer = random.Random(271)
    for size in (0, 1, 5, 20, 65, 120, 131):
        for other_size in (0, 1, 9, 70, 125):
            left = [('condition', randomizer.randrange(5)) for _ in range(size)]
            right = [('condition', randomizer.randrange(5)) for _ in range(other_size)]
            if mutable:
                left, right = [list(t) for t in left], [list(t) for t in right]
            patterns = (_order_pattern(left), _order_pattern(right))
            original = copy.deepcopy((left, right, patterns))
            assert _edit_distance(left, right, left_pattern=patterns[0], right_pattern=patterns[1]) == matrix_distance(left, right)
            assert (left, right, patterns) == original


def study_inputs():
    days = [(date(2023, 11, 1) + timedelta(days=i)).isoformat() for i in range(120)]
    closes = {day: 30000 * (1 + .05 * math.sin(i / 7)) for i, day in enumerate(days)}
    policy = AnalogPolicy(lookback_sessions=5, minimum_separation_sessions=6, maximum_distance=2)
    candidates = []
    all_states = []
    for i in range(5, 100):
        day = days[i]
        states = [dict(instrumentId=INSTRUMENT, seriesId=key, value=math.sin(i / (j + 3)),
                       unit=definition[0], date=day, availableFrom=day+'T07:00:00Z')
                  for j, (key, definition) in enumerate(FEATURE_DEFINITIONS.items()) if (i+j) % 3]
        all_states.extend(states)
        conditions = [dict(instrumentId=INSTRUMENT, seriesId='synthetic.condition', value=1,
                           unit='DIRECTION', date=days[k], availableFrom=days[k]+'T07:00:00Z')
                      for k in range(i-5, i+1) if k % 3 == 0]
        reactions = ([dict(instrumentId=INSTRUMENT, seriesId='material.CPI.1', value=math.sin(i),
                           unit='PERCENT', date=day, availableFrom=day+'T07:00:00Z', eventId='synthetic:'+day,
                           eventType='CPI', reactionWindowSessions=1)] if i % 2 else [])
        rows = [dict(instrumentId=INSTRUMENT, field='OHLCV_BAR', date=days[k], close=closes[days[k]],
                     availableFrom=days[k]+'T07:00:00Z') for k in range(i-5, i+1)]
        candidates.append(build_episode(cutoff=day+'T23:59:59Z', bars=rows, state_rows=states,
                                        condition_rows=conditions, reaction_rows=reactions, policy=policy))
        assert candidates[-1]['status'] == 'AVAILABLE'
    return candidates, closes, days, dict(policy=policy, state_rows=all_states, minimum_prior=10, step=2, maximum_evaluations=30)


def test_complete_studies_match_preparation_free_reference():
    candidates, closes, days, options = study_inputs()
    original = copy.deepcopy((candidates, closes, days, options))
    results = {
        'walk': backtest.walk_forward(candidates, closes, days, **options),
        'search': backtest.weight_search(candidates, closes, days, **options),
        'mixedGrid': backtest.weight_search(candidates, closes, days, **options,
            grid=((), (('priceShape', 1.), ('marketState', 2.), ('conditionOrder', 0.)),
                  (('priceShape', 1.), ('marketState', .5), ('materialReaction', 2.))))}
    assert (candidates, closes, days, options) == original
    assert results['walk']['evaluatedDates'] == 30
    assert results['walk']['actionAuthority'] is False
    for key, value in results.items():
        assert value.get('predictiveProbabilities') is None
        encoded = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()
        assert hashlib.sha256(encoded).hexdigest() == REFERENCE_HASHES[key]


def test_each_order_is_prepared_once_per_study_and_not_kept_between_calls(monkeypatch):
    candidates, closes, days, options = study_inputs()
    prepared = []
    original = backtest._order_pattern

    def record(order):
        prepared.append(tuple(order))
        return original(order)

    monkeypatch.setattr(backtest, '_order_pattern', record)
    backtest.walk_forward(candidates, closes, days, **options)
    assert len(prepared) == len(candidates)
    backtest.weight_search(candidates, closes, days, **options)
    assert len(prepared) == 2 * len(candidates)
    changed = copy.deepcopy(candidates)
    changed[-1]['conditions'].append({'date': days[99], 'condition': 'synthetic.changed', 'direction': -1})
    backtest.walk_forward(changed, closes, days, **options)
    assert len(prepared) == 3 * len(candidates)
    assert prepared[-1] != prepared[len(candidates) - 1]


# Full records, all horizon metrics, train/confirmation/held-out partitions,
# adopted weights and missing-component behavior from the pre-change engine.
REFERENCE_HASHES = {'walk': '58403f2e2181f3893c74b517f70b95ecb0770a5c719ad46195bb9f34ad5a7d49', 'search': '7de0d865aadee761c9c08c76ec4f833047fb5ba9bfd5ec05ee4cd73c578ed25c', 'mixedGrid': 'ae5b8b90d5bef0c9dc92cb8da59e380393ae38631af8847c69c425877f07d146'}
