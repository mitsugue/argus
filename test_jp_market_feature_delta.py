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
