"""Closed completion history preserves old current-observation behavior."""
import copy
import json

import pytest

from scripts.run_intel_collect import private_runtime_record
from test_run_intel_collect import runtime_fixture


def completed(index):
    body = runtime_fixture()
    start = f'2026-11-01T00:0{index}:00Z'
    finish = f'2026-11-01T00:0{index + 1}:00Z'
    body['intelCollect']['currentRun'].update(startedAt=start, finishedAt=finish)
    body['indexResearch'].update(lastStartedAt=f'2026-11-01T00:0{index}:20Z',
                                 lastCompletedAt=f'2026-11-01T00:0{index}:50Z')
    return private_runtime_record(body, body['intelCollect']['currentRun'])


def test_three_closed_completions_do_not_relabel_unrelated_latest_research():
    raw = runtime_fixture()
    raw['indexResearch']['lastCompletedAt'] = '2026-11-01T01:00:00Z'
    original = private_runtime_record(raw, raw['intelCollect']['currentRun'])
    rows = [completed(i) for i in range(4)]
    raw['intelCollect']['completedMemoryWindows'] = rows
    before = copy.deepcopy(raw)
    value = private_runtime_record(raw, raw['intelCollect']['currentRun'])
    history = value.pop('completedOrdinaryWindows')
    assert value == original
    assert value['researchWindowWithinExpectedCollection'] is False
    assert len(history) == 3
    assert [r['observedCollection']['startedAt'] for r in history] == [
        r['observedCollection']['startedAt'] for r in rows[1:]]
    assert all(r['collectionTimingBoundsMatch'] is True for r in history)
    assert all(r['researchWindowWithinExpectedCollection'] is True for r in history)
    assert all('completedOrdinaryWindows' not in r for r in history)
    history[0]['observedCollection']['status'] = 'changed'
    assert raw == before


def test_history_is_closed_and_recomputes_claimed_pass_flags():
    raw = runtime_fixture()
    row = completed(0)
    row.update(secret='forbidden-sentinel', collectionTimingBoundsMatch=True,
               researchWindowWithinExpectedCollection=True,
               completedOrdinaryWindows=[{'secret': 'forbidden-sentinel'}])
    row['expectedCollection']['finishedAt'] = '2026-11-01T00:00:10Z'
    row['research']['outcomes']['private-source'] = {'body': 'forbidden-sentinel'}
    row['memoryObservation'].update(secret='forbidden-sentinel',
                                    processInstanceId='forbidden-sentinel', pid=True)
    row['memoryObservation']['process']['owner'] = 'forbidden-sentinel'
    row['memoryObservation']['cgroup']['events']['oom_kill'] = True
    raw['intelCollect']['completedMemoryWindows'] = [row]
    value = private_runtime_record(raw, raw['intelCollect']['currentRun'])
    exported = value['completedOrdinaryWindows'][0]
    assert exported['collectionTimingBoundsMatch'] is False
    assert exported['researchWindowWithinExpectedCollection'] is False
    assert exported['memoryObservation']['processInstanceId'] is None
    assert exported['memoryObservation']['pid'] is None
    assert exported['memoryObservation']['cgroup']['events']['oom_kill'] is None
    assert 'forbidden-sentinel' not in json.dumps(value)


@pytest.mark.parametrize('history', [None, {}, 'unknown', [], [{}], [{'schemaVersion': 'unknown'}]])
def test_absent_or_invalid_history_leaves_existing_projection_unchanged(history):
    raw = runtime_fixture()
    expected = raw['intelCollect']['currentRun']
    original = private_runtime_record(raw, expected)
    raw['intelCollect']['completedMemoryWindows'] = history
    assert private_runtime_record(raw, expected) == original


def test_failed_completion_is_exported_without_becoming_a_success():
    raw = runtime_fixture()
    row = completed(0)
    row['observedCollection']['status'] = 'failed'
    row['memoryObservation']['process']['vmHwmBytes'] = 2**40
    raw['intelCollect']['completedMemoryWindows'] = [row]
    value = private_runtime_record(raw, raw['intelCollect']['currentRun'])
    exported = value['completedOrdinaryWindows'][0]
    assert exported['observedCollection']['status'] == 'failed'
    assert exported['memoryObservation']['process']['vmHwmBytes'] == 2**40
