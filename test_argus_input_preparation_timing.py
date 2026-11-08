"""入力実行側と合流側を分け、時間と固定工程だけを残す。"""
from concurrent.futures import ThreadPoolExecutor
import json
import threading

import pytest
import scanner
from argus_input_preparation_timing import InputPreparationTiming, STAGES, projection
from scripts.run_intel_collect import private_runtime_record


@pytest.fixture
def timing(monkeypatch):
    clocks = {'wall': 0., 'cpu': 0.}
    value = InputPreparationTiming(clock=lambda: clocks['wall'], cpu=lambda: clocks['cpu'],
                                   stamp=lambda: '2026-11-07T01:00:00Z')
    monkeypatch.setattr(scanner, '_MARKET_INPUT_PREPARATION_TIMING', value)
    monkeypatch.setattr(scanner, '_SINGLE_FLIGHT', {})
    monkeypatch.setattr(scanner, '_SINGLE_FLIGHT_LOCK', threading.Lock())
    monkeypatch.setattr(scanner, '_INTEL_COLLECT_CONTEXT', threading.local())
    return value, clocks


def test_actual_bootstrap_without_collection_context_records_fixed_stages(timing, monkeypatch):
    value, clocks = timing
    result = {'sourceStatus': {'nikkei': 'saved'}}
    def core(*, warm):
        assert warm
        scanner._intel_collect_stage('pit_restore')
        clocks.update(wall=4., cpu=1.)
        scanner._intel_collect_stage('pit_research')
        clocks.update(wall=10., cpu=3.)
        return result
    monkeypatch.setattr(scanner, '_jp_market_engine_pit_inputs_impl', core)
    assert scanner._jp_market_engine_pit_inputs(warm=True) is result
    row = value.view()
    assert row['status'] == 'DONE'
    assert (row['elapsedSeconds'], row['cpuSeconds']) == (10., 3.)
    assert row['completedStages'] == [
        {'stage': 'pit_restore', 'elapsedSeconds': 4., 'cpuSeconds': 1.},
        {'stage': 'pit_research', 'elapsedSeconds': 6., 'cpuSeconds': 2.}]
    assert STAGES <= scanner._INTEL_COLLECT_STAGES


def test_joining_thread_cannot_replace_leader_stage_or_claim_its_cpu(timing, monkeypatch):
    value, clocks = timing
    entered, finish, joined = threading.Event(), threading.Event(), threading.Event()
    calls = []
    def core(*, warm):
        calls.append(warm)
        scanner._intel_collect_stage('pit_statements')
        entered.set()
        assert finish.wait(5)
        return {'result': 'saved'}
    monkeypatch.setattr(scanner, '_jp_market_engine_pit_inputs_impl', core)
    with ThreadPoolExecutor(2) as pool:
        leader = pool.submit(scanner._jp_market_engine_pit_inputs, warm=True)
        assert entered.wait(5)
        event = scanner._SINGLE_FLIGHT['internal:jp-market-input-warm']['event']
        wait = event.wait
        def signal_wait(timeout=None):
            scanner._intel_collect_stage('pit_research')
            joined.set()
            return wait(timeout)
        monkeypatch.setattr(event, 'wait', signal_wait)
        follower = pool.submit(scanner._jp_market_engine_pit_inputs, warm=True)
        try:
            assert joined.wait(5)
            clocks.update(wall=12., cpu=2.)
            row = value.view()
            assert row['stage'] == 'pit_statements'
            assert row['status'] == 'RUNNING' and row['cpuSeconds'] is None
            assert row['stageElapsedSeconds'] == 12.
        finally:
            finish.set()
        assert leader.result(5) is follower.result(5)
    assert calls == [True] and value.view()['sequence'] == 1
    assert value.view()['cpuSeconds'] == 2.


def test_public_read_and_busy_follower_never_start_measurement(timing, monkeypatch):
    value, _ = timing
    old = {'old': True}
    monkeypatch.setattr(scanner, '_jp_market_engine_pit_inputs_impl', lambda **_: old)
    assert scanner._jp_market_engine_pit_inputs() is old
    assert value.view()['status'] == 'NOT_STARTED'
    monkeypatch.setattr(scanner, '_single_flight', lambda *a, **k: (None, 'busy'))
    with pytest.raises(TimeoutError, match='market_input_warm_in_progress'):
        scanner._jp_market_engine_pit_inputs(warm=True)
    assert value.view()['sequence'] == 0


def test_failure_retains_stage_without_exception_text_and_next_run_is_fresh(timing, monkeypatch):
    value, clocks = timing
    failure = ValueError('owner-payload-must-not-escape')
    def core(*, warm):
        scanner._intel_collect_stage('pit_earnings')
        clocks.update(wall=5., cpu=1.)
        raise failure
    monkeypatch.setattr(scanner, '_jp_market_engine_pit_inputs_impl', core)
    with pytest.raises(ValueError) as caught:
        scanner._jp_market_engine_pit_inputs(warm=True)
    assert caught.value is failure
    assert value.view()['status'] == 'FAILED'
    assert value.view()['stage'] == 'pit_earnings'
    assert 'owner-payload' not in json.dumps(value.view())
    monkeypatch.setattr(scanner, '_jp_market_engine_pit_inputs_impl', lambda **_: {})
    scanner._jp_market_engine_pit_inputs(warm=True)
    assert value.view()['sequence'] == 2
    assert value.view()['completedStages'] == [] and value.view()['stage'] is None


def test_stages_are_bounded_and_returned_rows_cannot_mutate_internal_state(timing):
    value, clocks = timing
    def core():
        for n in range(100):
            clocks['wall'] = n
            value.stage('pit_research')
            value.stage('private-company')
            value.stage(['invalid'])
    value.run(core)
    row = value.view()
    assert len(row['completedStages']) == len(STAGES)
    assert row['droppedStageCount'] == 100 - len(STAGES)
    row['completedStages'][0]['stage'] = 'private-company'
    assert 'private-company' not in json.dumps(value.view())


def test_unavailable_thread_cpu_is_unknown_not_zero():
    def missing():
        raise OSError('not available')
    value = InputPreparationTiming(cpu=missing)
    value.run(lambda: value.stage('pit_restore'))
    assert value.view()['cpuSeconds'] is None
    assert value.view()['completedStages'][0]['cpuSeconds'] is None


def test_private_runtime_reprojects_and_retains_completed_window_without_payload(timing):
    value, clocks = timing
    value.run(lambda: value.stage('pit_research'))
    original = value.view()
    original.update(raw='private-body', token='private-key')
    original['completedStages'].append({'stage':'private-company','elapsedSeconds':1})
    row = private_runtime_record({'marketInputPreparation':original}, {})
    assert row['marketInputPreparation'] == value.view()
    history = private_runtime_record({'intelCollect':{'completedMemoryWindows':[row]}}, {})
    assert history['completedOrdinaryWindows'][0]['marketInputPreparation'] == value.view()
    assert all(token not in json.dumps(history) for token in
               ('private-body', 'private-key', 'private-company'))
    bad = projection({'status':'DONE','cpuSeconds':float('inf'),'elapsedSeconds':True,
        'stage':{},'startedAt':'no timezone','sequence':True,'completedStages':[{'stage':[]}]*100})
    assert bad['cpuSeconds'] is None and bad['elapsedSeconds'] is None
    assert bad['sequence'] is None and bad['startedAt'] is None and bad['stage'] is None
    assert bad['completedStages'] == []


def test_projection_is_only_on_existing_authenticated_admin_route(timing, monkeypatch):
    value, _ = timing
    value.run(lambda: value.stage('pit_backup'))
    monkeypatch.setattr(scanner, '_require_admin', lambda: (False, {'error':'admin_required'},401))
    with scanner.app.test_request_context('/api/argus/admin/memory-attribution'):
        response, status = scanner.api_argus_admin_memory_attribution()
        assert status == 401 and 'marketInputPreparation' not in response.get_json()
    # Check the real handler wiring without starting collection, AI or an external fetch.
    import inspect
    source = inspect.getsource(scanner.api_argus_admin_memory_attribution)
    assert 'payload["marketInputPreparation"] = _MARKET_INPUT_PREPARATION_TIMING.view()' in source


def test_flight_records_real_computed_and_joined_calls_without_changing_result(timing, monkeypatch):
    value, _ = timing
    entered, release, joined = threading.Event(), threading.Event(), threading.Event()
    calls = []
    result = {'sourceStatus': {'nikkei': 'saved'}}
    def core(*, warm):
        calls.append(warm)
        entered.set()
        assert release.wait(5)
        return result
    monkeypatch.setattr(scanner, '_jp_market_engine_pit_inputs_impl', core)
    with ThreadPoolExecutor(2) as pool:
        leader = pool.submit(scanner._jp_market_engine_pit_inputs, warm=True)
        assert entered.wait(5)
        event = scanner._SINGLE_FLIGHT['internal:jp-market-input-warm']['event']
        wait = event.wait
        def mark_join(timeout=None):
            joined.set()
            return wait(timeout)
        monkeypatch.setattr(event, 'wait', mark_join)
        follower = pool.submit(scanner._jp_market_engine_pit_inputs, warm=True)
        try:
            assert joined.wait(5)
            assert len(value.view()['flightCalls']) == 2
        finally:
            release.set()
        assert leader.result(5) is follower.result(5) is result
    rows = value.view()['flightCalls']
    assert sorted(row['mode'] for row in rows) == ['computed', 'joined']
    assert all(row['status'] == 'DONE' for row in rows)
    assert len({row['callSequence'] for row in rows}) == 2
    assert calls == [True]
    assert value.view()['sequence'] == 1


def test_busy_calls_do_not_cancel_leader_or_claim_computation(timing, monkeypatch):
    value, clocks = timing
    waits = []
    def busy(key, compute, *, wait_sec):
        waits.append(wait_sec)
        clocks['wall'] += 900
        return None, 'busy'
    monkeypatch.setattr(scanner, '_single_flight', busy)
    for _ in range(2):
        with pytest.raises(TimeoutError, match='market_input_warm_in_progress'):
            scanner._jp_market_engine_pit_inputs(warm=True)
    assert waits == [900., 900.]
    row = value.view()
    assert row['sequence'] == 0 and row['status'] == 'NOT_STARTED'
    assert [call['mode'] for call in row['flightCalls']] == ['busy', 'busy']
    assert [call['elapsedSeconds'] for call in row['flightCalls']] == [900., 900.]


def test_flight_failure_keeps_same_exception_and_no_dynamic_message(timing, monkeypatch):
    value, _ = timing
    error = ValueError('private-company-and-key-do-not-copy')
    def fail(**kwargs):
        raise error
    monkeypatch.setattr(scanner, '_jp_market_engine_pit_inputs_impl', fail)
    with pytest.raises(ValueError) as caught:
        scanner._jp_market_engine_pit_inputs(warm=True)
    assert caught.value is error
    row = value.view()['flightCalls'][-1]
    assert row['status'] == 'FAILED' and row['mode'] is None
    assert 'private-company' not in json.dumps(value.view())


def test_flight_projection_is_bounded_reprojects_and_preserves_legacy(timing, monkeypatch):
    value, _ = timing
    monkeypatch.setattr(scanner, '_jp_market_engine_pit_inputs_impl', lambda **_: {})
    for _ in range(8):
        scanner._jp_market_engine_pit_inputs(warm=True)
    row = value.view()
    assert len(row['flightCalls']) == 3 and row['droppedFlightCallCount'] == 5
    assert [call['callSequence'] for call in row['flightCalls']] == [6, 7, 8]
    row['flightCalls'][-1].update(mode='private-company', raw='private-body', elapsedSeconds=True)
    projected = private_runtime_record({'marketInputPreparation': row}, {})['marketInputPreparation']
    assert projected['flightCalls'][-1]['mode'] is None
    assert projected['flightCalls'][-1]['elapsedSeconds'] is None
    assert all(word not in json.dumps(projected) for word in ('private-company', 'private-body'))
    assert value.view()['flightCalls'][-1]['mode'] == 'computed'
    legacy = projection({'status': 'DONE', 'completedStages': []})
    assert legacy['flightCalls'] == [] and legacy['droppedFlightCallCount'] is None
    public_before = value.view()
    scanner._jp_market_engine_pit_inputs()
    assert value.view() == public_before


def test_flight_observer_does_not_retain_the_returned_payload():
    import gc
    import weakref
    class Payload:
        pass
    payload = Payload()
    pointer = weakref.ref(payload)
    value = InputPreparationTiming()
    returned = value.observe_flight(lambda compute: (compute(), 'computed'), lambda: payload)
    assert returned == (payload, 'computed')
    del returned, payload
    gc.collect()
    assert pointer() is None


def test_failed_flight_finish_observation_never_replaces_successful_result():
    stamps = []
    def stamp():
        stamps.append(1)
        if len(stamps) == 4:
            raise RuntimeError('private-clock-message')
        return '2026-11-08T01:00:00Z'
    value = InputPreparationTiming(stamp=stamp)
    result = object()
    assert value.observe_flight(lambda compute: (compute(), 'computed'), lambda: result) == (result, 'computed')
    assert 'private-clock-message' not in json.dumps(value.view())
    assert value.view()['flightCalls'][-1]['finishedAt'] is None
