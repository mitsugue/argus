"""Actual runtime consumers keep replay intact and record real completions only."""
from argus_input_preparation_timing import InputPreparationTiming
import ast
import copy
import hashlib
import json
from pathlib import Path
import re
import threading
import time
from types import SimpleNamespace

import pytest

import argus_tick_durability as wal
from scripts.run_intel_collect import private_runtime_record
from test_run_intel_collect import runtime_fixture


SOURCE = Path(__file__).with_name('scanner.py').read_text()
FROZEN_FULL_READERS = {
    "_restore_mission_wal": "250cfa59d657343ee3020115b8580318955eba215cf5743c6c26815a2a3959de",
    "_rollback_remote_recovery_wal_floor": "b61cbfb657b8d061e875112ed2f3b91d379a9f0bac1500fce05d442ae6c2ecf9",
    "_seed_remote_recovery_wal_floor": "ae36ee9fd26d2dcf3ab22fb861150370bae651c72e91576d5b184c6329771bbf"
}
FROZEN_FULL_READER_CALL_COUNT = 6
FROZEN_PUBLIC_SNAPSHOT_READER = 'a7750b8c610057ab963c8ae0dae5fea179b1419b272e245b24dace011eda532b'
CURSOR_CALLERS = {'_checkpoint_wal_result', '_osint_persist_locked', 'api_argus_admin_missions_tick'}


def function_node(source, name):
    start = source.index('\ndef ' + name + '(') + 1
    following = re.search(r'(?m)^(?:def |@)', source[start + 4:])
    end = start + 4 + following.start() if following else len(source)
    return next(n for n in ast.parse(source[start:end]).body
                if isinstance(n, ast.FunctionDef) and n.name == name)


def fingerprint(node):
    return hashlib.sha256(ast.dump(node, include_attributes=False).encode()).hexdigest()


def functions(*names, extra=None):
    ns = {'copy': copy, 'threading': threading, 'time': time,
          'argus_tick_durability': wal}
    ns.update(extra or {})
    nodes = [function_node(SOURCE, name) for name in names]
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])),
                 '<actual-runtime-functions>', 'exec'), ns)
    return ns


def test_only_three_metadata_consumers_change_and_full_replay_readers_stay_identical():
    assert SOURCE.count('argus_tick_durability.read_valid_wal_cursor(') == 3
    assert SOURCE.count('argus_tick_durability.read_valid_wal(') == FROZEN_FULL_READER_CALL_COUNT
    for name in CURSOR_CALLERS:
        node = function_node(SOURCE, name)
        calls = [n for n in ast.walk(node) if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Attribute) and n.func.attr == 'read_valid_wal_cursor']
        assert len(calls) == 1
        assert len(calls[0].args) == 1 and calls[0].keywords == []
        assert isinstance(calls[0].args[0], ast.Name)
        assert calls[0].args[0].id == ('wal_path' if name == '_checkpoint_wal_result'
                                       else '_MISSION_WAL_FILE')
        assert not any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                       and n.func.attr == 'read_valid_wal' for n in ast.walk(node))
    for name, expected in FROZEN_FULL_READERS.items():
        assert fingerprint(function_node(SOURCE, name)) == expected
    assert fingerprint(function_node(SOURCE, '_verified_market_snapshot')) == FROZEN_PUBLIC_SNAPSHOT_READER


def test_deferred_compaction_uses_validated_scalars_without_replay_or_file_changes(tmp_path, monkeypatch):
    path = tmp_path / 'mission.wal'
    for i in (1, 2):
        wal.append_wal(str(path), sequence=i, kind='fixture', payload={'n': i}, job_id='fixture')
    with path.open('ab') as handle:
        handle.write(b'{incomplete')
    expected = wal.read_valid_wal(str(path))
    before = path.read_bytes()
    monkeypatch.setattr(wal, 'read_valid_wal', lambda *a, **k: pytest.fail('metadata requested full rows'))
    fn = functions('_checkpoint_wal_result')['_checkpoint_wal_result']
    value = fn({'verifiedAt': '2026-07-23T06:00:00Z', 'snapshotHash': 'a' * 64},
               wal_path=str(path), included_sequence=2, allow_wal_compaction=False,
               compaction_sequence=None, job_id='fixture', build_sha='b' * 40,
               mission_window_id='fixture-window')
    assert value == {'deferred': True, 'reason': 'remote_receipt_not_verified',
                     'compactedThrough': 0, 'remainingRecords': len(expected['records']),
                     'receiptSequence': 2, 'bytes': expected['bytes']}
    assert path.read_bytes() == before


def test_actual_compaction_still_uses_original_receipt_and_fence(monkeypatch):
    calls = []
    monkeypatch.setattr(wal, 'read_valid_wal_cursor', lambda *a, **k: pytest.fail('compaction used cursor'))
    monkeypatch.setattr(wal, 'compact_verified_wal', lambda *a, **k: calls.append((a, k)) or {'ok': True})
    fn = functions('_checkpoint_wal_result')['_checkpoint_wal_result']
    assert fn({'verifiedAt': '2026-07-23T06:00:00Z', 'snapshotHash': 'a' * 64},
              wal_path='fixture.wal', included_sequence=9, allow_wal_compaction=True,
              compaction_sequence=7, job_id='fixture', build_sha='b' * 40,
              mission_window_id='fixture-window') == {'ok': True}
    assert calls == [(('fixture.wal',), {'included_sequence': 7, 'receipt': {
        'jobId': 'fixture', 'verifiedAt': '2026-07-23T06:00:00Z', 'snapshotHash': 'a' * 64,
        'includedWalSequence': 7, 'buildSha': 'b' * 40, 'missionWindowId': 'fixture-window'}})]


def runtime_namespace():
    body = runtime_fixture()
    body['allocatorReclaim'] = {'startupPolicy': {'backendBuildSha': 'a' * 40,
        'backendVersion': '1.2.3', 'pythonAllocator': {'allocatorName': 'pymalloc'}}}
    body['startupRss'] = {'beforeRestoreMib': 1, 'afterRestoreMib': 2}
    body['operationAttribution'] = {
        'processIdentity': {'instanceId': 'b' * 32, 'pid': 123},
        'startupRestore': {'state': 'ready', 'outcome': 'restored', 'integrityStatus': 'ok'},
        'currentMemory': {'capturedAt': '2026-11-01T00:01:00Z',
            'process': {'vmRssBytes': 900, 'vmHwmBytes': 1000},
            'cgroup': {'memoryMaxBytes': 2147483648,
                       'events': {'oom': 0, 'oom_kill': 0, 'oom_group_kill': 0}},
            'smapsRollup': {'swapBytes': 0}}}
    targets = []
    class DeferredThread:
        def __init__(self, *, target, **kwargs):
            self.target = target
        def start(self):
            targets.append(self.target)
    ns = functions('_intel_collect_completed_memory_observation',
                   '_intel_collect_record_completion', '_intel_collect_tracked', extra={
        'threading': SimpleNamespace(Thread=DeferredThread),
        '_MARKET_INPUT_PREPARATION_TIMING': InputPreparationTiming(),
        '_INDEX_RESEARCH_STATUS': body['indexResearch'],
        '_MEMORY_OPERATIONS': SimpleNamespace(view=lambda: copy.deepcopy(body['operationAttribution'])),
        '_ALLOCATOR_RECLAIM_STATE': body['allocatorReclaim'], '_STARTUP_RSS': body['startupRss'],
        '_INTEL_COLLECT_LAST': {}, '_INTEL_COLLECT_RUN': {},
        '_INTEL_COLLECT_LOCK': threading.RLock(), '_INTEL_COLLECT_CONTEXT': threading.local(),
        '_collect_institutional_intel_and_warm': lambda: {'secret': 'private-result-sentinel'}})
    return ns, body, targets


def test_history_is_bounded_and_records_only_actual_terminal_work():
    ns, body, targets = runtime_namespace()
    for i in range(4):
        start, finish = f'2026-11-01T00:0{i}:00Z', f'2026-11-01T00:0{i+1}:00Z'
        stamps = iter((start, finish))
        ns['_ai_now_iso'] = lambda: next(stamps)
        body['indexResearch'].update(lastStartedAt=f'2026-11-01T00:0{i}:20Z',
                                     lastCompletedAt=f'2026-11-01T00:0{i}:50Z')
        body['operationAttribution']['currentMemory']['capturedAt'] = finish
        record, code = ns['_intel_collect_tracked'](f'fixture-{i}')
        assert record['status'] == 'running' and code == 202
        assert len(ns['_INTEL_COLLECT_LAST'].get('completedMemoryWindows', [])) == min(i, 3)
        joined, _ = ns['_intel_collect_tracked']('another-request')
        assert joined['startedAt'] == start
        targets.pop()()
        history = ns['_INTEL_COLLECT_LAST']['completedMemoryWindows']
        assert len(history) == min(i + 1, 3)
        assert history[-1]['observedCollection']['status'] == 'done'
        assert history[-1]['observedCollection']['finishedAt'] == finish
        assert history[-1]['memoryObservation']['capturedAt'] == finish
        assert history[-1]['researchWindowWithinExpectedCollection'] is True
        assert 'private-result-sentinel' not in json.dumps(history)
    assert [r['observedCollection']['startedAt'] for r in history] == [
        f'2026-11-01T00:0{i}:00Z' for i in (1, 2, 3)]
    before = copy.deepcopy(history)
    ns['_intel_collect_tracked']('fixture-3', status_only=True)
    assert history == before
    body['operationAttribution']['currentMemory']['process']['vmHwmBytes'] = 99999
    assert history == before


def test_observation_failure_is_unknown_and_does_not_change_successful_collection():
    ns, body, targets = runtime_namespace()
    ns['_ai_now_iso'] = lambda: '2026-11-01T00:01:00Z'
    def fail():
        raise ValueError('private-result-sentinel')
    ns['_MEMORY_OPERATIONS'] = SimpleNamespace(view=fail)
    ns['_intel_collect_tracked']('fixture-request')
    targets.pop()()
    assert ns['_INTEL_COLLECT_RUN']['status'] == 'done'
    [row] = ns['_INTEL_COLLECT_LAST']['completedMemoryWindows']
    assert row == {'schemaVersion': 'argus-collect-private-runtime-v1',
                   'available': False, 'captureErrorClass': 'ValueError'}
    assert 'private-result-sentinel' not in json.dumps(row)


def test_nonterminal_state_cannot_create_an_observation():
    ns, _, _ = runtime_namespace()
    ns['_intel_collect_record_completion']({'status': 'running'})
    assert 'completedMemoryWindows' not in ns['_INTEL_COLLECT_LAST']


def test_thread_start_failure_remains_failed_and_has_no_successful_observation():
    ns, _, _ = runtime_namespace()
    ns['_ai_now_iso'] = lambda: '2026-11-01T00:01:00Z'
    class BrokenThread:
        def __init__(self, **kwargs):
            pass
        def start(self):
            raise RuntimeError('private-result-sentinel')
    ns['threading'] = SimpleNamespace(Thread=BrokenThread)
    record, _ = ns['_intel_collect_tracked']('fixture-request')
    assert record['status'] == 'failed' and record['errorClass'] == 'RuntimeError'
    [row] = ns['_INTEL_COLLECT_LAST']['completedMemoryWindows']
    assert row['observedCollection']['status'] == 'failed'
    assert 'private-result-sentinel' not in json.dumps(row)


def test_collection_exception_is_preserved_as_a_failed_completion():
    ns, _, targets = runtime_namespace()
    ns['_ai_now_iso'] = lambda: '2026-11-01T00:01:00Z'
    def fail():
        raise ValueError('private-result-sentinel')
    ns['_collect_institutional_intel_and_warm'] = fail
    ns['_intel_collect_tracked']('fixture-request')
    targets.pop()()
    assert ns['_INTEL_COLLECT_RUN']['status'] == 'failed'
    assert ns['_INTEL_COLLECT_RUN']['errorClass'] == 'ValueError'
    [row] = ns['_INTEL_COLLECT_LAST']['completedMemoryWindows']
    assert row['observedCollection']['status'] == 'failed'
    assert 'private-result-sentinel' not in json.dumps(row)
