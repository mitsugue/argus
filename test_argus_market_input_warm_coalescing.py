"""起動と収集の同じ入力更新を共有し、公開読取と次の更新を妨げない。"""
import ast
from concurrent.futures import ThreadPoolExecutor
import hashlib
from pathlib import Path
import threading

import pytest
import scanner

KEY = 'internal:jp-market-input-warm'


@pytest.fixture(autouse=True)
def isolated_flights(monkeypatch):
    monkeypatch.setattr(scanner, '_SINGLE_FLIGHT', {})
    monkeypatch.setattr(scanner, '_SINGLE_FLIGHT_LOCK', threading.Lock())


def join_started(monkeypatch):
    """合流側が実際に同じ実行の待機へ入った時点を同期する。"""
    entered = threading.Event()
    event = scanner._SINGLE_FLIGHT[KEY]['event']
    original = event.wait

    def wait(timeout=None):
        entered.set()
        return original(timeout)

    monkeypatch.setattr(event, 'wait', wait)
    return entered


def test_bootstrap_and_collection_share_one_input_fetch_and_calculation(monkeypatch):
    started, release = threading.Event(), threading.Event()
    calls = []
    saved = {'sourceStatus': {'credit': 'csv_ledger'},
             'nikkeiRows': [{'date': '2026-10-30', 'close': 100, 'availableFrom': '2026-10-30T07:00:00Z'}]}

    def core(*, warm=False):
        calls.append(warm)
        started.set()
        assert release.wait(5)
        return saved

    monkeypatch.setattr(scanner, '_jp_market_engine_pit_inputs_impl', core)
    with ThreadPoolExecutor(max_workers=2) as pool:
        leader = pool.submit(scanner._jp_market_engine_pit_inputs, warm=True)
        assert started.wait(5)
        joined = join_started(monkeypatch)
        follower = pool.submit(scanner._jp_market_engine_pit_inputs, warm=True)
        try:
            assert joined.wait(5)
            assert calls == [True]
        finally:
            release.set()
        assert leader.result(timeout=5) is saved
        assert follower.result(timeout=5) is saved
    assert calls == [True]
    assert scanner._single_flight_status() == []


def test_cached_public_read_does_not_wait_or_fetch_when_background_is_running(monkeypatch):
    started, release = threading.Event(), threading.Event()
    calls = []
    old = {'sourceStatus': {'nikkei': 'cold_cache'}, 'originalTime': '2026-10-30T07:00:00Z'}

    def core(*, warm=False):
        calls.append(warm)
        if warm:
            started.set()
            assert release.wait(5)
            return {'completed': True}
        return old

    monkeypatch.setattr(scanner, '_jp_market_engine_pit_inputs_impl', core)
    with ThreadPoolExecutor(max_workers=2) as pool:
        active = pool.submit(scanner._jp_market_engine_pit_inputs, warm=True)
        assert started.wait(5)
        try:
            assert pool.submit(scanner._jp_market_engine_pit_inputs).result(timeout=1) is old
            assert calls == [True, False]
        finally:
            release.set()
        active.result(timeout=5)


def test_completed_warm_is_not_reused_by_the_next_collection(monkeypatch):
    calls = []

    def core(*, warm=False):
        calls.append(warm)
        return {'edition': len(calls)}

    monkeypatch.setattr(scanner, '_jp_market_engine_pit_inputs_impl', core)
    assert scanner._jp_market_engine_pit_inputs(warm=True) == {'edition': 1}
    assert scanner._jp_market_engine_pit_inputs(warm=True) == {'edition': 2}
    assert calls == [True, True]


def test_leader_failure_reaches_joiner_without_retry_and_releases_flight(monkeypatch):
    started, release = threading.Event(), threading.Event()
    calls = []

    def failed(*, warm=False):
        calls.append(warm)
        started.set()
        assert release.wait(5)
        raise ValueError('fixed_input_failure')

    monkeypatch.setattr(scanner, '_jp_market_engine_pit_inputs_impl', failed)
    with ThreadPoolExecutor(max_workers=2) as pool:
        leader = pool.submit(scanner._jp_market_engine_pit_inputs, warm=True)
        assert started.wait(5)
        joined = join_started(monkeypatch)
        follower = pool.submit(scanner._jp_market_engine_pit_inputs, warm=True)
        try:
            assert joined.wait(5)
        finally:
            release.set()
        for result in (leader, follower):
            with pytest.raises(ValueError, match='^fixed_input_failure$'):
                result.result(timeout=5)
    assert calls == [True]
    assert scanner._single_flight_status() == []
    monkeypatch.setattr(scanner, '_jp_market_engine_pit_inputs_impl', lambda **_: {'recovered': True})
    assert scanner._jp_market_engine_pit_inputs(warm=True) == {'recovered': True}


def test_actual_input_preparation_body_and_existing_public_wait_limit_are_unchanged():
    tree = ast.parse(Path(scanner.__file__).read_text())
    core = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                and n.name == '_jp_market_engine_pit_inputs_impl')
    core.name = '_jp_market_engine_pit_inputs'
    assert hashlib.sha256(ast.dump(core).encode()).hexdigest() == (
        'a0e28a6334bace0cb7a8d1e3451954802e96261bcda8a3ce2c00f8e753d5d58a')
    assert scanner._SINGLE_FLIGHT_WAIT_SEC == 45.0
    workflow = Path(scanner.__file__).parent / '.github/workflows/backend-warm-after-deploy.yml'
    assert 'scripts/run_intel_collect.py --base "$BE" --timeout 900' in workflow.read_text()


def test_join_timeout_is_bounded_and_never_starts_another_fetch(monkeypatch):
    def forbidden(**kwargs):
        pytest.fail('time-out started duplicate input work')

    def busy(key, compute, *, wait_sec):
        assert key == KEY and wait_sec == 900.0
        return None, 'busy'

    monkeypatch.setattr(scanner, '_jp_market_engine_pit_inputs_impl', forbidden)
    monkeypatch.setattr(scanner, '_single_flight', busy)
    with pytest.raises(TimeoutError, match='^market_input_warm_in_progress$'):
        scanner._jp_market_engine_pit_inputs(warm=True)
