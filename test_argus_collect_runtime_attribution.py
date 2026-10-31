"""Normal collection timing is private, bounded, and observes existing work only."""
import json
import threading
import time
from copy import deepcopy

import pytest
import scanner
from scripts.run_intel_collect import STAGES, private_timing_record

AT = '2026-01-02T00:00:00Z'
PREVIOUS = '2026-01-01T23:00:00Z'


def test_default_private_timing_remains_v1_and_excludes_context():
    body = {'status': 'done', 'startedAt': AT, 'finishedAt': AT,
            'previousFinishedAt': PREVIOUS, 'trigger': 'resident', 'stageStartedAt': AT,
            'stage': 'pit_backup', 'stageElapsedSeconds': .125,
            'completedStages': [{'stage': 'news_feeds', 'elapsedSeconds': 1.25}],
            'result': {'owner': 'private-result-marker'}, 'runId': 'private-run-marker'}
    old = private_timing_record(body)
    assert old == {'schemaVersion': 'argus-collect-timing-v1', 'available': True,
                   'status': 'done', 'startedAt': AT, 'finishedAt': AT,
                   'stage': 'pit_backup', 'stageElapsedSeconds': .125,
                   'completedStages': [{'stage': 'news_feeds', 'elapsedSeconds': 1.25}]}
    current = private_timing_record(body, include_run_context=True)
    assert current['schemaVersion'] == 'argus-collect-timing-v2'
    assert current['trigger'] == 'resident' and current['previousFinishedAt'] == PREVIOUS
    assert set(current) == set(old) | {'trigger', 'previousFinishedAt', 'stageStartedAt'}
    assert current['stageStartedAt'] == AT
    assert 'private-' not in json.dumps(current)


def test_run_context_rejects_untrusted_values_and_bounds_stages():
    body = {'status': 'not-a-status', 'previousFinishedAt': 'private-marker',
            'trigger': ['private-marker'], 'stageStartedAt': 'private-marker', 'stageElapsedSeconds': float('inf'),
            'completedStages': [{'stage': 'news_feeds', 'elapsedSeconds': 1.0}] * (len(STAGES) + 20)}
    value = private_timing_record(body, include_run_context=True)
    assert value['status'] is None and value['trigger'] is None
    assert value['previousFinishedAt'] is None and value['stageElapsedSeconds'] is None
    assert value['stageStartedAt'] is None
    assert len(value['completedStages']) == len(STAGES)
    assert 'private-marker' not in json.dumps(value)
    assert STAGES == scanner._INTEL_COLLECT_STAGES


def test_owner_current_run_get_is_private_redacted_and_read_only(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('diagnostic GET started work or wrote state')
    current = {'runId': 'private-run-marker', 'status': 'done', 'trigger': 'resident',
               'startedAt': AT, 'finishedAt': AT, 'previousFinishedAt': PREVIOUS,
               'result': {'owner': 'private-result-marker'},
               'completedStages': [{'stage': 'pit_research', 'elapsedSeconds': 2.5}]}
    previous = {'finishedAt': AT, 'status': 'done', 'trigger': 'resident', 'residentStarted': 2}
    monkeypatch.setattr(scanner, '_ARGUS_ADMIN_TOKEN', 'synthetic-token')
    monkeypatch.setattr(scanner, '_INTEL_COLLECT_RUN', current)
    monkeypatch.setattr(scanner, '_INTEL_COLLECT_LAST', previous)
    monkeypatch.setattr(scanner, '_JP_ANALOG_BACKTEST_CACHE', {})
    for name in ('_collect_institutional_intel_and_warm', '_index_research_warm', '_osint_persist'):
        monkeypatch.setattr(scanner, name, forbidden)
    monkeypatch.setattr(scanner.requests, 'get', forbidden)
    monkeypatch.setattr(scanner.requests, 'post', forbidden)
    before = deepcopy((current, previous))
    with scanner.app.test_client() as client:
        assert client.get('/api/argus/admin/memory-attribution').status_code == 401
        response = client.get('/api/argus/admin/memory-attribution',
                              headers={'X-ARGUS-ADMIN-TOKEN': 'synthetic-token'})
    assert response.status_code == 200
    view = response.json['intelCollect']['currentRun']
    assert view['startedAt'] == AT and view['previousFinishedAt'] == PREVIOUS
    assert view['trigger'] == 'resident' and view['completedStages'][0]['elapsedSeconds'] == 2.5
    assert 'private-run-marker' not in response.get_data(as_text=True)
    assert 'private-result-marker' not in response.get_data(as_text=True)
    assert (current, previous) == before and scanner._JP_ANALOG_BACKTEST_CACHE == {}


def test_join_keeps_resident_trigger_and_previous_finish(monkeypatch):
    entered, release = threading.Event(), threading.Event()
    calls = []
    monkeypatch.setattr(scanner, '_INTEL_COLLECT_RUN', {})
    monkeypatch.setattr(scanner, '_INTEL_COLLECT_LAST', {'finishedAt': PREVIOUS, 'trigger': 'request'})
    monkeypatch.setattr(scanner, '_ai_now_iso', lambda: AT)
    def work():
        calls.append(1); entered.set()
        assert release.wait(3)
        return {'stored': 0}
    monkeypatch.setattr(scanner, '_collect_institutional_intel_and_warm', work)
    try:
        first, _ = scanner._intel_collect_tracked('synthetic-a', trigger='resident')
        assert entered.wait(2)
        joined, _ = scanner._intel_collect_tracked('synthetic-b', trigger='request')
        assert first['runId'] == joined['runId'] == 'synthetic-a'
        assert joined['trigger'] == 'resident' and joined['previousFinishedAt'] == PREVIOUS
        assert scanner._INTEL_COLLECT_LAST['finishedAt'] == PREVIOUS and len(calls) == 1
    finally:
        release.set()
    deadline = time.monotonic() + 2
    while scanner._INTEL_COLLECT_LAST.get('finishedAt') != AT and time.monotonic() < deadline:
        time.sleep(.01)
    assert scanner._INTEL_COLLECT_LAST['finishedAt'] == AT
    assert scanner._INTEL_COLLECT_RUN['previousFinishedAt'] == PREVIOUS
    assert scanner._INTEL_COLLECT_LAST['trigger'] == 'resident'


def research_host(monkeypatch, *, restored=False, failed=False):
    monkeypatch.setattr(scanner, '_INDEX_RESEARCH_LOCK', threading.Lock())
    monkeypatch.setattr(scanner, '_INDEX_RESEARCH_STATUS', {})
    monkeypatch.setattr(scanner, '_INDEX_RESEARCH_REPORTS', {})
    monkeypatch.setattr(scanner, '_index_research_path', lambda: None)
    monkeypatch.setattr(scanner, '_index_research_restore', lambda: None)
    monkeypatch.setattr(scanner, '_ai_now_iso', lambda: AT)
    monkeypatch.setattr(scanner.argus_product_naming, 'require_allowed', lambda value: None)
    monkeypatch.setattr(scanner.argus_index_research_cache, 'comparison_retention_reason', lambda *a, **k: None)
    state = {'key': 'private-calibration-key', 'result': {}} if restored else {}
    monkeypatch.setattr(scanner, '_JP_ANALOG_BACKTEST_CACHE', state)
    calls = []
    def chart(index, interval):
        return {'status': 'available', 'index': index, 'symbol': index, 'timeframe': interval}
    def comparison(horizon):
        assert scanner._INDEX_RESEARCH_STATUS['currentTarget'] == f'comparison:N225:{horizon}'
        if failed:
            raise ValueError('synthetic_calculation_failure')
        if not state.get('key'):
            calls.append(horizon)
            state.update(key='private-calibration-key', result={})
        return {'status': 'available', 'comparison': {'horizonSessions': horizon}, 'actionAuthority': False}
    monkeypatch.setattr(scanner, '_index_chart_calculate', chart)
    monkeypatch.setattr(scanner, '_jp_market_comparison_calculate', comparison)
    return calls


def test_research_timing_distinguishes_calculated_and_reused_without_payload_changes(monkeypatch):
    calls = research_host(monkeypatch)
    scanner._index_research_warm()
    outcomes = scanner._INDEX_RESEARCH_STATUS['outcomes']
    assert calls == [1]
    assert outcomes['comparison:N225:1']['calibrationStatus'] == 'CALCULATED'
    assert all(outcomes[f'comparison:N225:{h}']['calibrationStatus'] == 'REUSED' for h in (5, 10, 20))
    assert all(row['elapsedSeconds'] >= 0 and row['cpuSeconds'] >= 0 for row in outcomes.values())
    assert scanner._INDEX_RESEARCH_STATUS['lastStartedAt'] == AT
    assert scanner._INDEX_RESEARCH_STATUS['currentTarget'] is None
    assert 'private-calibration-key' not in json.dumps(outcomes)
    reports = deepcopy(scanner._INDEX_RESEARCH_REPORTS)
    assert 'calibrationStatus' not in json.dumps(reports)
    scanner._INDEX_RESEARCH_STATUS['lastAttemptMonotonic'] = -1e20
    scanner._index_research_warm()
    assert scanner._INDEX_RESEARCH_REPORTS == reports and calls == [1]


def test_restored_calibration_is_observed_as_reused(monkeypatch):
    calls = research_host(monkeypatch, restored=True)
    scanner._index_research_warm()
    assert calls == []
    assert all(row['calibrationStatus'] == 'REUSED' for key, row in
               scanner._INDEX_RESEARCH_STATUS['outcomes'].items() if key.startswith('comparison:'))


def test_failed_study_is_not_reported_as_a_cache_hit(monkeypatch):
    calls = research_host(monkeypatch, restored=True, failed=True)
    scanner._index_research_warm()
    assert calls == [] and scanner._INDEX_RESEARCH_STATUS['status'] == 'PARTIAL'
    for key, row in scanner._INDEX_RESEARCH_STATUS['outcomes'].items():
        if key.startswith('comparison:'):
            assert row['status'] == 'exception' and row['calibrationStatus'] == 'NOT_EVALUABLE'
            assert row['elapsedSeconds'] >= 0 and row['cpuSeconds'] >= 0
