"""Cold replay keeps the ordinary PIT results while avoiding repeated row hashing."""
from copy import deepcopy
import pytest
import jp_market_engine as engine
import jp_market_features as features
from test_jp_market_feature_pit_work import data


CUTOFFS = ['2026-07-01T23:59:59Z', '2026-08-01T23:59:59Z',
           '2026-08-20T23:59:59Z', '2026-09-01T23:59:59Z']


def ordinary_history(source, cutoffs, monkeypatch):
    original = features.build_market_features
    def ordinary(**kwargs):
        kwargs.pop('_price_replay', None)
        return original(**kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(features, 'build_market_features', ordinary)
        return features.build_feature_history(cutoffs=cutoffs, **source)


@pytest.mark.parametrize('case', ['normal', 'late', 'future', 'revision', 'malformed'])
def test_every_feature_condition_reference_revision_and_cache_identity_matches(case, monkeypatch):
    source = data(case)
    before = deepcopy(source)
    actual = features.build_feature_history(cutoffs=CUTOFFS, **source)
    assert actual == ordinary_history(source, CUTOFFS, monkeypatch)
    assert source == before
    assert actual['historicalVintageVerified'] is False
    assert actual['actionAuthority'] is False
    assert actual['automaticAiCalls'] == 0


def test_future_conflict_is_rejected_only_when_both_rows_are_visible(monkeypatch):
    source = data('normal')
    rows = source['price_series']['vix']
    rows.append({**rows[6], 'value': 123, 'knownAt': '2026-08-15T00:00:00Z'})
    early = CUTOFFS[:2]
    assert features.build_feature_history(cutoffs=early, **source) == ordinary_history(source, early, monkeypatch)
    for calculate in (lambda: features.build_feature_history(cutoffs=CUTOFFS, **source),
                      lambda: ordinary_history(source, CUTOFFS, monkeypatch)):
        with pytest.raises(ValueError, match='conflicting_row_revision'):
            calculate()


def test_conflicts_outside_each_cutoffs_existing_price_window_stay_excluded(monkeypatch):
    source = data('normal')
    rows = source['price_series']['nikkei']
    old = {**rows[0], 'date': '2020-01-01', 'availableFrom': '2020-01-01T07:00:00Z'}
    rows.extend([old, {**old, 'value': 999}])
    assert features.build_feature_history(cutoffs=CUTOFFS, **source) == ordinary_history(source, CUTOFFS, monkeypatch)


def test_ambiguous_series_on_the_same_day_is_not_silently_selected(monkeypatch):
    source = data('normal')
    row = source['price_series']['vix'][6]
    source['price_series']['vix'].append({**row, 'field': 'OHLCV_BAR', 'value': 55})
    for calculate in (lambda: features.build_feature_history(cutoffs=CUTOFFS, **source),
                      lambda: ordinary_history(source, CUTOFFS, monkeypatch)):
        with pytest.raises(ValueError, match='ambiguous_series_observation'):
            calculate()


def test_malformed_rows_and_explicit_correction_receipts_match_ordinary_selector(monkeypatch):
    source = data('normal')
    rows = source['price_series']['vix']
    for delta in ({'revision': -1}, {'revision': True}, {'revision': 1, 'knownAt': None},
                  {'knownAt': 'bad'}, {'date': '2026-02-30'}, {'date': '2027-01-01'},
                  {'field': 'volume'}, {'instrumentId': 'OTHER'}):
        rows.append({**rows[7], **delta})
    assert features.build_feature_history(cutoffs=CUTOFFS, **source) == ordinary_history(source, CUTOFFS, monkeypatch)


def test_price_results_and_a_new_history_never_share_mutable_source_metadata():
    source = data('normal')
    replay = features._PriceHistoryReplay(source['price_series'], CUTOFFS[-1])
    first = replay.history('vix', 'VIX', CUTOFFS[1])
    first[6]['metadata']['receipts'][0]['flags'].append(99)
    source['price_series']['vix'][6]['metadata']['receipts'][0]['flags'].append(88)
    second = replay.history('vix', 'VIX', CUTOFFS[-1])
    assert second[6]['metadata']['receipts'][0]['flags'] == [1, 2]
    fresh = features._PriceHistoryReplay(source['price_series'], CUTOFFS[-1])
    assert fresh.history('vix', 'VIX', CUTOFFS[-1])[6]['metadata']['receipts'][0]['flags'] == [1, 2, 88]
    with pytest.raises(ValueError, match='outside_scope'):
        replay.history('vix', 'VIX', '2027-01-01T00:00:00Z')


def test_cold_replay_hash_work_is_bounded_without_changing_any_output(monkeypatch):
    source = data('normal')
    old_hash = engine._sha256
    calls = []
    def counted(value):
        calls.append(None)
        return old_hash(value)
    monkeypatch.setattr(engine, '_sha256', counted)
    actual = features.build_feature_history(cutoffs=CUTOFFS, **source)
    reused_work = len(calls)
    calls.clear()
    expected = ordinary_history(source, CUTOFFS, monkeypatch)
    assert actual == expected
    assert reused_work < len(calls) * .75


def test_ordinary_single_cutoff_never_allocates_the_replay_cache(monkeypatch):
    def forbidden(*args):
        raise AssertionError('single-cutoff replay allocation')
    monkeypatch.setattr(features, '_PriceHistoryReplay', forbidden)
    result = features.build_feature_history(cutoffs=CUTOFFS[-1:], **data('normal'))
    assert result['calculationWork']['evaluatedCutoffs'] == 1


def test_mixed_revisions_receipts_and_date_windows_match_the_ordinary_path(monkeypatch):
    import random
    rng = random.Random(263)
    for _ in range(30):
        source = data('normal')
        rows = source['price_series']['vix']
        for _ in range(8):
            row = deepcopy(rng.choice(rows[:60]))
            row.update(rng.choice([
                {'revision': rng.choice([0, 1, 2]), 'knownAt': rng.choice(CUTOFFS), 'value': rng.randrange(10, 80)},
                {'revision': True}, {'date': 'bad'}, {'knownAt': 'bad'},
                {'date': '2027-01-01'}, {'field': 'volume'}, {'instrumentId': 'OTHER'},
                {'metadata': {'receipt': [rng.randrange(9)]}},
            ]))
            rows.insert(rng.randrange(len(rows) + 1), row)
        def outcome(calculate):
            try:
                return ('success', calculate())
            except ValueError as error:
                return ('rejected', str(error))
        assert outcome(lambda: features.build_feature_history(cutoffs=CUTOFFS, **source)) == outcome(
            lambda: ordinary_history(source, CUTOFFS, monkeypatch))
