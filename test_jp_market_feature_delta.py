"""Append-only replay parity; no probability or vintage promotion."""
from copy import deepcopy
from unittest.mock import patch
from datetime import date, timedelta
import jp_market_features as features


def prices(n):
    return [{'instrumentId':'VIX', 'field':'close',
             'date':str(date(2026,1,1)+timedelta(days=i)),
             'availableFrom':str(date(2026,1,1)+timedelta(days=i))+'T07:00:00Z',
             'value':20+i*.1} for i in range(n)]


def cutoffs(n):
    return [str(date(2026,1,1)+timedelta(days=i))+'T23:59:59Z' for i in range(n)]


def saved(rows, at):
    return {**features.build_feature_history(cutoffs=at, price_series={'vix':rows}),
            'status':'AVAILABLE'}


def assert_parity(actual, full):
    for key in ('features','conditions','latest','firstCutoff','lastCutoff','cutoffCount',
                'evaluatedCutoffs','sourceManifest','historicalVintageVerified',
                'actionAuthority','automaticAiCalls'):
        assert actual[key] == full[key], key


def test_append_evaluates_only_new_cutoffs_with_exact_numerical_parity():
    old = saved(prices(60), cutoffs(60)); archive = deepcopy(old)
    with patch.object(features,'build_market_features',wraps=features.build_market_features) as compute:
        new = features.build_feature_history(cutoffs=cutoffs(62),previous_history=old,
                                              price_series={'vix':prices(62)})
        assert compute.call_count == 2
    assert new['calculationWork'] == {'reusedCutoffs':60,'evaluatedCutoffs':2}
    assert_parity(new,saved(prices(62),cutoffs(62)))
    assert old == archive


def test_intraday_endpoint_is_removed_without_changing_revisions_or_provenance():
    old = saved(prices(60), cutoffs(59)+['2026-03-01T12:00:00Z'])
    new = features.build_feature_history(cutoffs=cutoffs(61),previous_history=old,
                                          price_series={'vix':prices(61)})
    assert new['calculationWork']['reusedCutoffs'] == 59
    assert_parity(new,saved(prices(61),cutoffs(61)))


def test_changed_removed_reordered_or_backfilled_sources_force_full_replay():
    old = saved(prices(60), cutoffs(60))
    corrected=prices(61); corrected[3]['value']=99
    backfilled=prices(60)+[{**prices(60)[3],'availableFrom':'2026-03-03T07:00:00Z','revision':1}]
    for rows in (corrected,prices(59),list(reversed(prices(61))),backfilled):
        new = features.build_feature_history(cutoffs=cutoffs(62),previous_history=old,
                                              price_series={'vix':rows})
        assert new['calculationWork']['reusedCutoffs'] == 0
        assert_parity(new,saved(rows,cutoffs(62)))


def test_no_new_data_updates_freshness_without_replaying_history():
    old = saved(prices(60),cutoffs(60))
    new=features.build_feature_history(cutoffs=cutoffs(70),previous_history=old,
                                      price_series={'vix':prices(60)})
    assert new['calculationWork']['reusedCutoffs']==60
    assert_parity(new,saved(prices(60),cutoffs(70)))


def test_legacy_cache_without_manifest_is_preserved_and_recomputed():
    old=saved(prices(60),cutoffs(60)); del old['sourceManifest']
    original=deepcopy(old)
    new=features.build_feature_history(cutoffs=cutoffs(61),previous_history=old,
                                      price_series={'vix':prices(61)})
    assert new['calculationWork']['reusedCutoffs']==0
    assert old==original


def test_identical_repeat_reuses_endpoint_without_any_calculation():
    rows, at = prices(60), cutoffs(60)
    old = saved(rows, at); archived = deepcopy(old)
    with patch.object(features, 'build_market_features', side_effect=AssertionError('duplicate replay')):
        new = features.build_feature_history(cutoffs=at, previous_history=old,
            price_series={'vix': rows})
    assert new['calculationWork'] == {'reusedCutoffs': 60, 'evaluatedCutoffs': 0}
    assert_parity(new, old)
    new['latest']['missingFeatures'].clear()
    assert old == archived


def test_late_correction_preserves_past_and_recalculates_only_after_receipt():
    rows = prices(60); at = cutoffs(60)
    old = saved(rows, at); archived = deepcopy(old)
    correction = {**rows[3], 'value': 45, 'revision': 1,
                  'knownAt': '2026-03-03T07:00:00Z'}
    changed = rows + [correction]
    with patch.object(features, 'build_market_features', wraps=features.build_market_features) as compute:
        new = features.build_feature_history(cutoffs=cutoffs(65), previous_history=old,
            price_series={'vix': changed})
        assert compute.call_count == 5
    assert new['calculationWork'] == {'reusedCutoffs': 60, 'evaluatedCutoffs': 5}
    assert_parity(new, saved(changed, cutoffs(65)))
    assert old == archived
    # The original observation remains present; the correction is only knowable in March.
    assert changed[3]['value'] != correction['value']
    assert all(r['knownAt'] >= correction['knownAt'] for r in new['features']
        if r.get('availableFrom') == '2026-03-03T07:00:00+00:00')


def test_future_backfill_at_same_cutoff_does_not_trigger_replay():
    rows = prices(60); at = cutoffs(60); old = saved(rows, at)
    new_rows = rows + [{**rows[3], 'value': 45, 'revision': 1,
                       'knownAt': '2026-03-03T07:00:00Z'}]
    with patch.object(features, 'build_market_features', side_effect=AssertionError('future-only input')):
        new = features.build_feature_history(cutoffs=at, previous_history=old,
            price_series={'vix': new_rows})
    assert new['calculationWork']['evaluatedCutoffs'] == 0
    assert_parity(new, saved(new_rows, at))


def test_shortened_cutoff_request_computes_its_own_endpoint_once():
    old = saved(prices(60), cutoffs(60))
    with patch.object(features, 'build_market_features', wraps=features.build_market_features) as compute:
        new = features.build_feature_history(cutoffs=cutoffs(50), previous_history=old,
            price_series={'vix': prices(60)})
        assert compute.call_count == 1
    assert new['calculationWork'] == {'reusedCutoffs': 49, 'evaluatedCutoffs': 1}
    assert_parity(new, saved(prices(60), cutoffs(50)))


def test_backdated_correction_and_changed_prefix_still_replay_and_explain_why():
    old = saved(prices(60), cutoffs(60))
    changed = prices(60) + [{**prices(60)[3], 'value': 45, 'revision': 1,
        'knownAt': '2026-02-01T07:00:00Z'}]
    result = features.build_feature_history(cutoffs=cutoffs(65), previous_history=old,
        price_series={'vix': changed})
    assert result['calculationWork']['reusedCutoffs'] == 0
    assert result['reuseDecision'] == {'reason': 'append_can_affect_prior_cutoff', 'source': 'price_series:vix'}
    changed = prices(65); changed[2]['value'] += 1
    result = features.build_feature_history(cutoffs=cutoffs(65), previous_history=old,
        price_series={'vix': changed})
    assert result['reuseDecision'] == {'reason': 'source_prefix_changed', 'source': 'price_series:vix'}
    assert_parity(result, saved(changed, cutoffs(65)))
