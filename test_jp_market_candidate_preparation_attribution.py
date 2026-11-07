"""Fixed candidate rebuild observations do not alter admission or results."""
import copy
import hashlib
import json
from unittest.mock import patch

import pytest
import jp_market_price_paths as paths
import jp_market_analog_backtest as backtest
from test_jp_market_analog_cache_revisions import BARS, DAYS, CUTOFF, row


@pytest.fixture(autouse=True)
def fixed_study():
    with patch.object(backtest, 'walk_forward', return_value={'horizons': {}, 'method': 'synthetic-validation'}), \
         patch.object(backtest, 'weight_search', return_value={'status': 'INSUFFICIENT_DATA', 'adopted': False}):
        yield


def invoke(cache, **kwargs):
    return paths.cached_index_comparison(kwargs.pop('bars', BARS), cutoff=CUTOFF,
        session_dates=kwargs.pop('session_dates', DAYS), backtest_cache=cache, **kwargs)


def test_observation_keeps_original_full_result_and_both_keys():
    cache = {}
    result = invoke(cache, state_rows=[row('credit.loss_pct', -1)])
    assert hashlib.sha256(json.dumps(result, sort_keys=True, separators=(',', ':')).encode()).hexdigest() == \
        'af807f7cf6f4b4dda5165d31432a01e2511afb4f45d7603f0e2d016a310689db'
    assert cache['sealedCandidates']['key'] == 'e0b23c6ea80feccda9dcb8ade071e74bf5450d4c0bd2ef0c4b49e0da5d972802'
    assert cache['key'] == '37e01d9be240608af77978be47325bbc64dd8ad20d78378287bb6ce38fbfab25'
    assert 'candidatePreparation' not in json.dumps(result)
    first = cache['candidatePreparation']
    assert first['status'] == 'COLD' and first['changedInputs'] == [] and first['builtCandidates'] > 0
    assert first['elapsedSeconds'] >= 0 and first['cpuSeconds'] >= 0
    assert invoke(cache, state_rows=[row('credit.loss_pct', -1)]) == result
    assert cache['candidatePreparation']['status'] == 'REUSED'
    assert cache['candidatePreparation']['builtCandidates'] == 0


@pytest.mark.parametrize('group, argument', [('states', 'state_rows'), ('conditions', 'condition_rows'),
    ('reactions', 'reaction_rows'), ('research', 'research_reaction_rows')])
def test_same_count_change_names_only_fixed_input_groups(group, argument):
    series = 'credit.loss_pct' if group == 'states' else 'material.CPI.3'
    original = row(series, -1, eventType='CPI', eventId='synthetic:CPI', reactionWindowSessions=3)
    cache = {}
    invoke(cache, **{argument: [original]})
    changed = {**original, 'value': 2}
    result = invoke(cache, **{argument: [changed]})
    observation = cache['candidatePreparation']
    assert observation['status'] == 'REBUILT' and group in observation['changedInputs']
    assert result == invoke({}, **{argument: [changed]})
    assert set(observation) == {'status', 'changedInputs', 'builtCandidates', 'elapsedSeconds', 'cpuSeconds'}
    assert 'synthetic' not in json.dumps(observation)


def test_price_and_calendar_changes_remain_distinct():
    cache = {}; invoke(cache)
    bars = copy.deepcopy(BARS); bars[35]['close'] += 1
    invoke(cache, bars=bars)
    assert cache['candidatePreparation']['changedInputs'] == ['prices']
    invoke(cache, bars=bars, session_dates=[*DAYS, '2026-12-01'])
    assert cache['candidatePreparation']['changedInputs'] == ['calendar']


def test_old_generation_without_components_is_unknown_not_a_proved_reason():
    cache = {}; invoke(cache)
    del cache['sealedCandidates']['inputComponents']
    bars = copy.deepcopy(BARS); bars[35]['close'] += 1
    invoke(cache, bars=bars)
    assert cache['candidatePreparation']['status'] == 'UNKNOWN_BASELINE'
    assert cache['candidatePreparation']['changedInputs'] == []


def test_receipt_hash_change_is_observed_without_ignoring_originals():
    original = row('material.CPI.3', 1, sourceRowsHash='a'*64, sourceSha256='b'*64,
                   eventType='CPI', eventId='synthetic:CPI', reactionWindowSessions=3)
    cache = {}; before = invoke(cache, research_reaction_rows=[original])
    key = cache['key']
    changed = {**original, 'sourceRowsHash': 'c'*64, 'sourceSha256': 'd'*64}
    after = invoke(cache, research_reaction_rows=[changed])
    assert before == after and cache['key'] == key
    assert cache['candidatePreparation']['status'] == 'REBUILT'
    assert cache['candidatePreparation']['changedInputs'] == ['research']
    assert after == invoke({}, research_reaction_rows=[changed])


def test_observation_does_not_suppress_warm_revision_conflict():
    original = row('credit.loss_pct', -1)
    cache = {}; invoke(cache, state_rows=[original])
    with pytest.raises(ValueError, match='conflicting_row_revision'):
        invoke(cache, state_rows=[original, {**original, 'sourceSha256': 'e'*64}])


def test_only_component_digests_remain_in_existing_generation():
    cache = {}; invoke(cache)
    components = cache['sealedCandidates']['inputComponents']
    assert set(components) == {'prices', 'states', 'conditions', 'reactions', 'research', 'calendar', 'policy'}
    assert all(type(v) is str and len(v) == 64 for v in components.values())
    from argus_index_research_cache import calibration_record
    saved = calibration_record(cache, method='synthetic:method', at=CUTOFF)
    assert 'inputComponents' not in json.dumps(saved)
    assert 'candidatePreparation' not in json.dumps(saved)
