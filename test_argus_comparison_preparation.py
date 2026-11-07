"""Observe raw group drift while the original engine and calibration stay exact."""
import copy
import hashlib
import json
from pathlib import Path
from unittest.mock import patch
import weakref

import pytest
import argus_comparison_preparation as observation
import jp_market_price_paths as paths
import jp_market_analog_backtest as backtest
from test_jp_market_analog_cache_revisions import BARS, DAYS, CUTOFF, row


@pytest.fixture(autouse=True)
def fixed_study():
    with patch.object(backtest, 'walk_forward', return_value={'horizons': {}, 'method': 'synthetic-validation'}), \
         patch.object(backtest, 'weight_search', return_value={'status': 'INSUFFICIENT_DATA', 'adopted': False}):
        yield


def invoke(cache, **kwargs):
    bars = kwargs.pop('bars', BARS); sessions = kwargs.pop('session_dates', DAYS)
    groups = {'prices': bars, 'calendar': sessions, **{key: kwargs.get(arg, ()) for key, arg in
              [('states', 'state_rows'), ('conditions', 'condition_rows'),
               ('reactions', 'reaction_rows'), ('research', 'research_reaction_rows')]}}
    before = observation.begin(cache, groups)
    result = paths.cached_index_comparison(bars, cutoff=CUTOFF, session_dates=sessions,
                                          backtest_cache=cache, **kwargs)
    observation.finish(cache, before)
    return result


def test_original_full_result_candidate_key_and_study_key_stay_exact():
    cache = {}; result = invoke(cache, state_rows=[row('credit.loss_pct', -1)])
    assert hashlib.sha256(json.dumps(result, sort_keys=True, separators=(',', ':')).encode()).hexdigest() == \
        'af807f7cf6f4b4dda5165d31432a01e2511afb4f45d7603f0e2d016a310689db'
    assert cache['sealedCandidates']['key'] == 'e0b23c6ea80feccda9dcb8ade071e74bf5450d4c0bd2ef0c4b49e0da5d972802'
    assert cache['key'] == '37e01d9be240608af77978be47325bbc64dd8ad20d78378287bb6ce38fbfab25'
    assert cache['candidatePreparation']['status'] == 'COLD'
    assert cache['candidatePreparation']['changedInputs'] == []
    assert invoke(cache, state_rows=[row('credit.loss_pct', -1)]) == result
    assert cache['candidatePreparation'] == {'status': 'REUSED', 'changedInputs': [], 'builtCandidates': 0}
    assert 'candidatePreparation' not in json.dumps(result)


@pytest.mark.parametrize('group, argument', [('states', 'state_rows'), ('conditions', 'condition_rows'),
    ('reactions', 'reaction_rows'), ('research', 'research_reaction_rows')])
def test_same_count_change_and_cold_parity(group, argument):
    original = row('credit.loss_pct' if group == 'states' else 'material.CPI.3', -1,
                   eventId='synthetic:CPI', eventType='CPI', reactionWindowSessions=3)
    cache = {}; invoke(cache, **{argument: [original]})
    updated = {**original, 'value': 2}
    result = invoke(cache, **{argument: [updated]})
    assert cache['candidatePreparation']['status'] == 'REBUILT'
    assert cache['candidatePreparation']['changedInputs'] == [group]
    assert result == invoke({}, **{argument: [updated]})


def test_price_and_calendar_drift_are_separate():
    cache = {}; invoke(cache)
    bars = copy.deepcopy(BARS); bars[35]['close'] += 1
    invoke(cache, bars=bars)
    assert cache['candidatePreparation']['changedInputs'] == ['prices']
    invoke(cache, bars=bars, session_dates=[*DAYS, '2026-12-01'])
    assert cache['candidatePreparation']['changedInputs'] == ['calendar']


def test_receipt_hash_refresh_still_rebuilds_original_candidates():
    original = row('material.CPI.3', 1, sourceRowsHash='a'*64, sourceSha256='b'*64,
                   eventId='synthetic:CPI', eventType='CPI', reactionWindowSessions=3)
    cache = {}; before = invoke(cache, research_reaction_rows=[original]); key = cache['key']
    after = invoke(cache, research_reaction_rows=[{**original, 'sourceRowsHash': 'c'*64}])
    assert before == after and cache['key'] == key
    assert cache['candidatePreparation']['status'] == 'REBUILT'
    assert cache['candidatePreparation']['changedInputs'] == ['research']


def test_future_input_drift_is_not_reported_as_rebuild_cause():
    cache = {}; invoke(cache)
    future = row('material.CPI.3', 1, availableFrom='2027-01-01T00:00:00Z')
    invoke(cache, research_reaction_rows=[future])
    # Enabling the optional research lane is a real policy change.
    invoke(cache, research_reaction_rows=[{**future, 'value': 9}])
    assert cache['candidatePreparation']['status'] == 'REUSED'
    assert cache['candidatePreparation']['changedInputs'] == ['research']


def test_failure_does_not_leave_previous_success_observation():
    value = row('credit.loss_pct', -1); cache = {}; invoke(cache, state_rows=[value])
    with pytest.raises(ValueError, match='conflicting_row_revision'):
        invoke(cache, state_rows=[value, {**value, 'value': -2}])
    assert 'candidatePreparation' not in cache


def test_observer_never_owns_raw_inputs_or_prior_candidate_graph():
    class Rows(list):
        pass
    values = Rows(BARS); ref = weakref.ref(values)
    groups = {k: [] for k in observation.GROUPS}; groups['prices'] = values
    cache = {'sealedCandidates': {'key': 'a'*64, 'candidates': []}}
    before = observation.begin(cache, groups)
    del groups, values
    assert ref() is None
    assert all(len(v) == 64 for v in before['inputs'].values())
    del cache['sealedCandidates']
    assert observation.finish(cache, before)['status'] == 'NOT_EVALUABLE'


@pytest.mark.parametrize('bad', [float('nan'), object()])
def test_unhashable_observation_is_not_a_false_hit(bad):
    cache = {'sealedCandidates': {'key': 'a'*64, 'candidates': []}}
    groups = {k: [] for k in observation.GROUPS}; groups['states'] = [bad]
    before = observation.begin(cache, groups)
    assert observation.finish(cache, before) == {'status': 'NOT_EVALUABLE', 'changedInputs': [], 'builtCandidates': None}


def test_diagnostics_are_not_persisted_calibration_and_method_sources_are_unchanged():
    import argus_index_research_cache as saved
    cache = {}; invoke(cache)
    record = saved.calibration_record(cache, method='synthetic:method', at=CUTOFF)
    assert 'preparationInputDigests' not in json.dumps(record)
    assert 'candidatePreparation' not in json.dumps(record)
    # Exact original numerical source, so diagnostic deployment does not
    # invalidate a stored study merely by changing a source digest.
    assert hashlib.sha1(b'blob '+str(len(Path(paths.__file__).read_bytes())).encode()+b'\0'+
                        Path(paths.__file__).read_bytes()).hexdigest() == '6873c0d0787b1febdd4623ecbe44c9739e34dfeb'
