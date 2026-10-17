"""Public evidence reads remain responsive when another parser owns its lock."""
import _strptime
import threading
from datetime import datetime

import pytest

import argus_fastdate
import scanner


@pytest.mark.parametrize('market', ['JP', 'US', 'CRYPTO'])
@pytest.mark.parametrize('value', ['2026-09-11', '2026-01-09', '2024-02-29',
                                  '2026-02-29', '2026-13-01', '', None,
                                  '2026-09-11T15:30:00+09:00'])
def test_source_time_contract_matches_existing_parser(monkeypatch, market, value):
    actual = scanner._canonical_truth_iso(value, market, date_means_close=True)
    with monkeypatch.context() as old:
        old.setattr(argus_fastdate, 'strptime', datetime.strptime)
        expected = scanner._canonical_truth_iso(value, market, date_means_close=True)
    assert actual == expected


def test_daily_history_and_quote_reads_do_not_join_global_parser_lock():
    done = threading.Event()
    results, errors = {}, []

    def read():
        try:
            results['source'] = scanner._date_only_eod_source_truth(
                '2026-09-11', now_epoch=1789182000)
            results['bars'] = scanner._chart_rows_from_history(
                {'dates': ['2026-09-10', '2026-09-11'],
                 'closes': [63000, 64000], 'opens': [62500, 63500],
                 'highs': [63500, 64500], 'lows': [62000, 63000],
                 'volumes': [1000, 1200]}, market='JP', provider='jquants',
                known_at='2026-09-12T00:00:00Z', dataset_id='provider-revision')
            results['weekly'] = scanner._chart_weekly_rows(results['bars'])
        except BaseException as exc:
            errors.append(exc)
        finally:
            done.set()

    _strptime._cache_lock.acquire()
    worker = threading.Thread(target=read)
    try:
        worker.start()
        completed_while_locked = done.wait(2)
    finally:
        _strptime._cache_lock.release()
        worker.join(5)
    assert completed_while_locked, 'evidence read joined the process-wide parser lock'
    assert not errors
    assert results['source']['delayClass'] == 'EOD'
    assert results['source']['realtimeEvidence'] is False
    assert [row['close'] for row in results['bars']] == [63000, 64000]
    assert results['bars'][1]['observedAt'] == '2026-09-11T06:30:00.000000Z'
    assert results['bars'][1]['knownAt'] == '2026-09-12T00:00:00Z'


def test_retried_snapshot_requests_share_one_build(monkeypatch):
    started, release = threading.Event(), threading.Event()
    calls, results, errors = [], [], []
    monkeypatch.setattr(scanner, '_PREDICTION_SNAPSHOT_CACHE', {'data': None, 'expires': 0})
    payload = {'canonicalPredictionLedger': {'schemaVersion': 'argus-prediction-ledger-v2',
                                            'mode': 'forward_live', 'issuedDecisions': []}}

    def compute():
        calls.append(True)
        started.set()
        assert release.wait(5)
        return payload

    monkeypatch.setattr(scanner, 'get_prediction_snapshot', compute)

    def request():
        try:
            with scanner.app.test_client() as client:
                response = client.get('/api/argus/prediction-snapshot')
                results.append((response.status_code, response.get_json()))
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=request) for _ in range(4)]
    try:
        threads[0].start()
        assert started.wait(2)
        for thread in threads[1:]:
            thread.start()
    finally:
        release.set()
        for thread in threads:
            if thread.ident is not None:
                thread.join(5)
    assert not errors
    assert len(calls) == 1
    assert results == [(200, payload)] * 4
    assert scanner._PREDICTION_SNAPSHOT_CACHE['expires'] > scanner.time.time()
    assert not any(row['key'] == 'prediction-snapshot' for row in scanner._single_flight_status())


def test_failed_build_does_not_replace_prior_snapshot(monkeypatch):
    old = {'data': {'asOf': '2026-09-11T00:00:00Z'}, 'expires': 1}
    monkeypatch.setattr(scanner, '_PREDICTION_SNAPSHOT_CACHE', old.copy())
    def fail():
        raise ValueError('provider unavailable')
    monkeypatch.setattr(scanner, 'get_prediction_snapshot', fail)
    with pytest.raises(ValueError):
        scanner._prediction_snapshot_cached_build()
    assert scanner._PREDICTION_SNAPSHOT_CACHE == old


def test_completed_snapshot_gets_a_full_cache_window(monkeypatch):
    from types import SimpleNamespace
    clock = [100.0]
    monkeypatch.setattr(scanner, 'time', SimpleNamespace(time=lambda: clock[0]))
    monkeypatch.setattr(scanner, '_PREDICTION_SNAPSHOT_CACHE', {'data': None, 'expires': 0})
    calls = []
    def compute():
        calls.append(True)
        clock[0] = 220.0
        return {'asOf': '2026-09-12T03:00:00Z'}
    monkeypatch.setattr(scanner, 'get_prediction_snapshot', compute)
    first = scanner._prediction_snapshot_cached_build()
    clock[0] = 250.0
    assert scanner._prediction_snapshot_cached_build() == first
    assert len(calls) == 1
    assert scanner._PREDICTION_SNAPSHOT_CACHE['expires'] == 310.0
