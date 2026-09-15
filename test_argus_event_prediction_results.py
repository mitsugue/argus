import copy

import pytest

import argus_event_prediction_results as results
import argus_decision_ledger as ledger
from test_run_prediction_ledger import (
    _prediction, _reseal_prediction, _snapshot, _run, _read, _outcome_bar,
    ISSUED, RUN_AT,
)


EVENT = {'eventId': 'test-economic-event', 'firstSeenAt': '2026-08-10T19:00:00Z',
         'causalHypotheses': [{'hypothesisId': 'test-rates-hypothesis'}]}


@pytest.fixture
def history(tmp_path):
    prediction, snapshot = _prediction(action='WAIT')
    prediction = _reseal_prediction(prediction, evidence_refs=[
        'causal-event:test-economic-event', 'causal-hypothesis:test-rates-hypothesis'])
    _run(_snapshot(as_of=ISSUED, decisions=[prediction], market_snapshot=snapshot),
         tmp_path, 'issue')
    missing = _run(_snapshot(as_of=RUN_AT, outcomes=[]), tmp_path, 'missing')
    missing = _read(tmp_path / missing['segmentPath'])['outcomeResolutions'][0]
    later = '2026-08-12T20:10:00Z'
    observed = _run(_snapshot(as_of=later, outcomes=[_outcome_bar()]), tmp_path, 'observed')
    observed = _read(tmp_path / observed['segmentPath'])['outcomeResolutions'][0]
    assert missing['status'] == 'UNSCORABLE' and observed['status'] == 'OBSERVED'
    return [{'prediction': prediction, 'outcome': row} for row in (missing, observed)]


def select(history, **kwargs):
    return results.select_event_results(EVENT, history, as_of=kwargs.pop('as_of',
        '2026-08-13T00:00:00Z'), market=kwargs.pop('market', 'US'),
        symbol=kwargs.pop('symbol', 'AAPL'), **kwargs)


def test_later_result_preserves_unscorable_history_and_canonical_metrics(history):
    original = copy.deepcopy(history)
    before = select(history, as_of=RUN_AT)
    assert before['records'][0]['status'] == 'UNSCORABLE'
    assert before['records'][0]['missingReasons'] == ['exact_target_session_truth_missing']
    assert before['excludedFutureCount'] == 1
    after = select(history)
    row = after['records'][0]
    assert row['status'] == 'OBSERVED' and row['sequence'] == 2
    assert row['metrics'] == history[1]['outcome']['metrics']
    assert row['truthRef'] == history[1]['outcome']['truthRef']
    assert row['previousOutcomeId'] == history[0]['outcome']['id']
    assert after['supersededCount'] == 1
    assert row['causalAttributionVerified'] is False
    assert row['actionAuthority'] is False
    assert row['predictiveProbabilityVerified'] is False
    assert row['relation'] == 'EVENT_REFERENCED_WHEN_PREDICTION_ISSUED'
    assert history == original


@pytest.mark.parametrize('market,symbol', [('JP', 'AAPL'), ('US', 'SPY'), ('JP', 'N225')])
def test_other_instrument_cannot_substitute_for_current_subject(history, market, symbol):
    view = select(history, market=market, symbol=symbol)
    assert view['records'] == []
    assert view['status'] == 'NOT_RECORDED_IN_SEARCH_SCOPE'
    assert view['historyComplete'] is False


def test_missing_original_event_or_hypothesis_reference_is_not_inferred(history):
    for key, value in [('eventId', 'another-event'),
                       ('causalHypotheses', [{'hypothesisId': 'another-hypothesis'}])]:
        event = {**EVENT, key: value}
        assert results.select_event_results(event, history,
            as_of='2026-08-13T00:00:00Z', market='US', symbol='AAPL')['records'] == []


def test_mutated_future_result_is_not_silently_filtered(history):
    history[1]['outcome']['recordedAt'] = '2099-01-01T00:00:00Z'
    with pytest.raises(ValueError, match='canonical_pair_invalid'):
        select(history, as_of=RUN_AT)


def test_mismatched_pair_and_predating_reference_fail_closed(history):
    bad = copy.deepcopy(history)
    bad[0]['prediction'] = _reseal_prediction(bad[0]['prediction'], evidence_refs=[])
    with pytest.raises(ValueError, match='canonical_pair_invalid'):
        select(bad)
    with pytest.raises(ValueError, match='reference_predates_event'):
        results.select_event_results({**EVENT, 'firstSeenAt': '2026-08-11T00:00:00Z'},
            history, as_of='2026-08-13T00:00:00Z', market='US', symbol='AAPL')


def test_subject_mismatch_rejected_even_when_resealed(history):
    outcome = copy.deepcopy(history[1]['outcome'])
    body = {k: v for k, v in outcome.items() if k not in ('id', 'integrityHash')}
    body['symbol'] = 'SPY'
    outcome = ledger._v2_seal(body, 'or')
    with pytest.raises(ValueError, match='subject_mismatch'):
        results.project_result(history[1]['prediction'], outcome,
                               as_of='2026-08-13T00:00:00Z')


def test_duplicate_and_order_do_not_change_selected_result(history):
    a = select(history)
    b = select(list(reversed(history)))
    assert a == b
    assert select(history + history)['records'] == a['records']


def test_bounds_and_timezone_are_enforced(history):
    with pytest.raises(ValueError, match='pair_bound'):
        select([history[0]] * (results.MAX_PAIRS + 1))
    with pytest.raises(ValueError, match='limit_invalid'):
        select(history, limit=0)
    with pytest.raises(ValueError, match='timezone_required'):
        select(history, as_of='2026-08-13T00:00:00')


def test_bounded_loader_reads_original_from_its_committed_segment(history, tmp_path):
    original = copy.deepcopy(history)
    loaded = results.load_recent_pairs(tmp_path)
    assert loaded['pairs'] == [history[1]]
    assert loaded['sourceSegmentCount'] == 2
    assert loaded['outcomeCount'] == loaded['selectedPairCount'] == 1
    assert loaded['scope'] == 'LATEST_COMMITTED_SEGMENT_OUTCOMES'
    assert loaded['historyComplete'] is False
    assert loaded['actionAuthority'] is False
    assert loaded['omissions'] == {}
    assert select(loaded['pairs'])['records'] == select(history)['records']
    assert history == original


def test_bounded_loader_reports_omitted_sources_and_never_invents_results(history, tmp_path, monkeypatch):
    monkeypatch.setattr(results, 'MAX_SOURCE_SEGMENTS', 1)
    loaded = results.load_recent_pairs(tmp_path)
    assert loaded['pairs'] == []
    assert loaded['omissions'] == {'SOURCE_SEGMENT_BOUND': 1}
    monkeypatch.setattr(results, 'MAX_SOURCE_SEGMENTS', 8)
    monkeypatch.setattr(results, 'MAX_PAIR_BYTES', 2)
    loaded = results.load_recent_pairs(tmp_path)
    assert loaded['pairs'] == []
    assert loaded['omissions'] == {'PAIR_BYTE_BOUND': 1}


def test_bounded_loader_rejects_changed_original_and_mismatched_manifest(history, tmp_path):
    import json
    from scripts import run_prediction_ledger as runner
    head = _read(tmp_path / 'commit-head.json')
    manifest_path = tmp_path / head['manifest']['path']
    manifest = _read(manifest_path)
    original = manifest_path.read_bytes()
    manifest['generation'] += 1
    manifest.pop('digest')
    manifest_path.write_bytes(runner._canonical_bytes(runner._sealed_document(manifest)) + b'\n')
    with pytest.raises(ValueError, match='commit_manifest_mismatch'):
        results.load_recent_pairs(tmp_path)
    manifest_path.write_bytes(original)
    index = _read(tmp_path / manifest['index']['path'])
    identity = next(row for row in index['identities'] if row['id'] == history[1]['prediction']['id'])
    path = tmp_path / identity['sourceSegment']
    value = json.loads(path.read_text())
    value['issuedDecisions'][0]['forecastValue'] = 'altered'
    path.write_bytes(runner._canonical_bytes(value) + b'\n')
    with pytest.raises(runner.LedgerRunError, match='digest'):
        results.load_recent_pairs(tmp_path)


def test_bounded_loader_limits_bytes_and_rejects_symlink(history, tmp_path, monkeypatch):
    monkeypatch.setattr(results, 'MAX_SOURCE_BYTES', 8)
    with pytest.raises(ValueError, match='source_byte_bound'):
        results.load_recent_pairs(tmp_path)
    monkeypatch.setattr(results, 'MAX_SOURCE_BYTES', 48 * 1024 * 1024)
    head = tmp_path / 'commit-head.json'; moved = tmp_path / 'saved-head.json'
    head.rename(moved); head.symlink_to(moved)
    with pytest.raises(OSError):
        results.load_recent_pairs(tmp_path)


def test_derived_export_preserves_canonical_files_and_is_repeatable(history, tmp_path):
    from scripts.export_event_prediction_results import export
    original = {p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob('*.json')}
    target = tmp_path.parent / (tmp_path.name + '-lookup.json')
    first = export(tmp_path, target, source_commit='1' * 40)
    raw = target.read_bytes()
    assert export(tmp_path, target, source_commit='1' * 40) == first
    assert target.read_bytes() == raw
    assert first['sourceCommit'] == '1' * 40 and first['rebuildable'] is True
    assert all((tmp_path / path).read_bytes() == body for path, body in original.items())
    with pytest.raises(ValueError, match='must_not_replace_canonical'):
        export(tmp_path, tmp_path / 'commit-head.json', source_commit='1' * 40)
