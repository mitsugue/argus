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


def test_export_runtime_works_after_switching_away_from_source_checkout(history, tmp_path):
    import json
    import os
    from pathlib import Path
    import shutil
    import subprocess
    import sys
    runtime = tmp_path.parent / (tmp_path.name + '-runtime')
    (runtime / 'scripts').mkdir(parents=True)
    repo = Path(__file__).resolve().parent
    for path in ['argus_calibration.py', 'argus_decision_ledger.py',
                 'argus_market_data_truth.py', 'argus_market_clock.py',
                 'argus_event_prediction_results.py',
                 'scripts/run_prediction_ledger.py', 'scripts/export_event_prediction_results.py']:
        shutil.copyfile(repo / path, runtime / path)
    target = runtime / 'lookup.json'
    run = subprocess.run([sys.executable, str(runtime / 'scripts/export_event_prediction_results.py'),
        '--ledger-root', str(tmp_path), '--output', str(target), '--source-commit', '1' * 40],
        cwd=tmp_path, env={**os.environ, 'PYTHONPATH': str(runtime), 'PYTHONDONTWRITEBYTECODE': '1'},
        capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    assert json.loads(target.read_text())['pairs'] == [history[1]]


@pytest.fixture
def related_source(tmp_path):
    import json
    import argus_causal_event_memory as cem
    from scripts.export_event_prediction_results import export
    from test_argus_causal_event_memory import build_event, news, ledger_state
    from test_argus_owner_dialogue import AT
    initial = build_event(news(event_id='linked-inflation-event', event_type='INFLATION'))
    _, state = ledger_state(tmp_path / 'events', initial)
    memory = cem.reasoning_retrieval(state, family='INFLATION_RATES', as_of=AT)
    event = memory['records'][0]
    prediction, snapshot = _prediction(action='WAIT')
    prediction = _reseal_prediction(prediction, evidence_refs=[
        'causal-event:' + event['eventId'], 'causal-hypothesis:' + event['causalHypotheses'][0]['hypothesisId']])
    root = tmp_path / 'canonical'
    _run(_snapshot(as_of=ISSUED, decisions=[prediction], market_snapshot=snapshot), root, 'issue')
    _run(_snapshot(as_of=RUN_AT, outcomes=[_outcome_bar()]), root, 'observed')
    target = tmp_path / 'lookup.json'
    export(root, target, source_commit='1' * 40)
    return memory, json.loads(target.read_text())


def test_related_result_selection_keeps_subject_and_original_metric(related_source):
    from test_argus_owner_dialogue import AT
    memory, source = related_source
    saved = copy.deepcopy(source)
    linked = results.related_result_context(memory, source, as_of=AT, market='US', symbol='AAPL')
    assert len(linked['records']) == 1
    assert linked['records'][0]['metrics'] == source['pairs'][0]['outcome']['metrics']
    assert linked['records'][0]['forecastHorizon'] == source['pairs'][0]['prediction']['forecastHorizon']
    assert linked['causalAttributionVerified'] is False
    assert results.related_result_context(memory, source, as_of=AT, market='JP', symbol='N225')['records'] == []
    assert source == saved
    source['pairs'][0]['outcome']['metrics'][0]['value'] = 12345
    with pytest.raises(ValueError, match='canonical_pair_invalid'):
        results.related_result_context(memory, source, as_of=AT, market='US', symbol='AAPL')


def test_archived_event_results_remain_readable_without_regeneration(related_source, tmp_path):
    import json
    from flask import Flask
    import argus_owner_dialogue as dialogue
    import argus_owner_dialogue_api as api
    import argus_owner_dialogue_store as store
    from test_argus_owner_dialogue import AT, market_brief
    from test_argus_owner_dialogue_api import identity
    memory, source = related_source
    snapshot = {'eventId':'calendar-inflation', 'eventCode':'CPI', 'title':'CPI',
        'state':'UPCOMING', 'relatedMemory':memory,
        'predictionResultSource':{'status':'AVAILABLE','data':source,'readAt':AT}}
    saved = dialogue.build_context(brief=market_brief(), symbol='AAPL', market='US', horizon=1,
        question='What changed?', received_at=AT, focus_event_id='calendar-inflation',
        event_snapshot=snapshot)
    path = tmp_path/'owner.sqlite3'
    request_id = identity()
    store.initialize(path)
    store.submit(path, identity=request_id, input_hash=dialogue.digest(saved), boot_id='old-boot', context=saved)
    store.complete(path, request_id, {'status':'UNAVAILABLE', 'answer':None, 'completedAt':AT})
    def forbidden(*args, **kwargs):
        raise AssertionError('archived read invoked generation or source lookup')
    app = Flask(__name__)
    api.register(app, authorize=lambda token:(True,None,200), storage_path=lambda:str(path),
        market_brief=forbidden, generate=forbidden, now=lambda:AT,
        event_snapshot=forbidden, event_history=forbidden, prediction_result_source=forbidden)
    client = app.test_client()
    for _ in range(2):
        response = client.post('/api/argus/owner-dialogue',json={'action':'history','ownerToken':'test-owner'})
        assert response.status_code == 200
        assert response.json['items'][0]['context'] == saved
    linked = saved['eventFocus']['snapshot']['relatedPredictionResults']
    assert linked['records'][0]['status'] == 'OBSERVED'
    assert linked['records'][0]['metrics'] == source['pairs'][0]['outcome']['metrics']


def test_optional_results_cannot_displace_current_material_at_context_bound(related_source):
    import json
    import argus_owner_dialogue as dialogue
    from test_argus_owner_dialogue import AT, market_brief
    memory, source = related_source
    snapshot = {'eventId':'calendar-inflation', 'eventCode':'CPI', 'title':'CPI', 'state':'UPCOMING',
        'relatedMemory':memory, 'predictionResultSource':{'status':'AVAILABLE','data':source,'readAt':AT}}
    def build(padding):
        material = dialogue.fact('x' * padding, 'current_material')
        return dialogue.build_context(brief=market_brief(), symbol='AAPL', market='US', horizon=1,
            question='What changed?', received_at=AT, focus_event_id='calendar-inflation',
            event_snapshot=snapshot, material_facts=[material])
    small = build(1)
    assert small['eventFocus']['snapshot']['relatedPredictionResults']['status'] == 'AVAILABLE'
    size = len(json.dumps(small, ensure_ascii=False).encode())
    padding = 65536 - size + 101
    large = build(padding)
    assert large['eventFocus']['snapshot']['relatedPredictionResults']['reason'] == 'CONTEXT_BYTE_BOUND'
    assert any(row['source'] == 'current_material' and row['text'] == 'x' * padding for row in large['facts'])
    assert large['eventFocus']['snapshot']['relatedMemory']['status'] == 'AVAILABLE'
    assert len(json.dumps(large, ensure_ascii=False).encode()) <= 65536
