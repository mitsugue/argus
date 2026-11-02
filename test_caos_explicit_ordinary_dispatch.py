"""Execute the workflow's guards and payload without contacting any service."""
import ast
import json
import os
from pathlib import Path
import re
import subprocess

import pytest

from test_caos_workflow_recovery import _workflow_step_run


ROOT = Path(__file__).resolve().parent
PATH = '.github/workflows/caos-scan.yml'
TEXT = (ROOT / PATH).read_text()
BASE = '44df055770a12a6267583f97df4eceabd80bca98'


def job(text, name):
    body = text.split(f'\n  {name}:\n', 1)[1]
    boundary = re.search(r'\n  [a-z][a-z-]*:\n', body)
    return body[:boundary.start()] if boundary else body


def condition(name, *, event='workflow_dispatch', only='', actor='owner',
              cancelled=False, identity='success', verified='verified'):
    body = job(TEXT, name)
    match = re.search(r'^    if: ([^\n]+)\n', body, re.M)
    assert match
    expression = match.group(1)
    if expression == '>-':
        tail = body[match.end():]
        expression = ' '.join(re.findall(r'^      (.+)$', tail.split('    runs-on:', 1)[0], re.M))
    expression = expression.replace('always()', 'True').replace('cancelled()', repr(cancelled))
    expression = expression.replace('&&', ' and ').replace('||', ' or ')
    expression = re.sub(r'!(?!=)', ' not ', expression)
    values = {'github.event_name': event, 'inputs.only': only,
              'github.actor': actor, 'github.repository_owner': 'owner',
              'needs.backend-identity.result': identity,
              'needs.backend-identity.outputs.status': verified}
    for key in sorted(values, key=len, reverse=True):
        expression = expression.replace(key, repr(values[key]))
    tree = ast.parse(expression.strip(), mode='eval')
    allowed = (ast.Expression, ast.BoolOp, ast.And, ast.Or, ast.UnaryOp,
               ast.Not, ast.Compare, ast.Eq, ast.NotEq, ast.Constant, ast.Load)
    assert all(isinstance(node, allowed) for node in ast.walk(tree))
    return eval(compile(tree, '<workflow-guard>', 'eval'), {'__builtins__': {}}, {})


@pytest.mark.parametrize('name', ['mission-backup', 'caos-collection', 'durability-flush'])
@pytest.mark.parametrize('event,only,actor,expected', [
    ('workflow_dispatch', '', 'owner', False),
    ('workflow_dispatch', 'future_map', 'owner', False),
    ('workflow_dispatch', 'ordinary', 'owner', True),
    ('workflow_dispatch', 'ordinary', 'collaborator', False),
    ('workflow_dispatch', 'ORDINARY', 'owner', False),
    ('workflow_dispatch', 'ordinary ', 'owner', False),
    ('workflow_dispatch', 'ordinary', 'owner || true', False),
    ('schedule', '', 'scheduler', True),
    ('pull_request', 'ordinary', 'owner', False),
])
def test_actual_operational_guards_require_explicit_owner_or_existing_schedule(
        name, event, only, actor, expected):
    assert condition(name, event=event, only=only, actor=actor) is expected


@pytest.mark.parametrize('name', ['mission-backup', 'caos-collection'])
@pytest.mark.parametrize('identity,verified', [('failure', 'verified'), ('success', 'genuine_mismatch')])
def test_owner_dispatch_cannot_bypass_backend_identity(name, identity, verified):
    assert not condition(name, only='ordinary', identity=identity, verified=verified)


def test_cancelled_flush_stays_disabled_for_owner_and_schedule():
    assert not condition('durability-flush', only='ordinary', cancelled=True)
    assert not condition('durability-flush', event='schedule', actor='scheduler', cancelled=True)


def test_existing_cron_concurrency_and_operational_steps_are_unchanged():
    baseline = subprocess.check_output(['git', 'show', f'{BASE}:{PATH}'], cwd=ROOT, text=True)
    assert re.findall(r"^\s+- cron: '([^']+)'", TEXT, re.M) == ['7,37 * * * *']
    old_group = next(line for line in baseline.splitlines() if line.startswith('  group:'))
    assert old_group in TEXT
    assert set(re.findall(r'^  ([a-z][a-z-]*):$', TEXT, re.M)) == set(
        re.findall(r'^  ([a-z][a-z-]*):$', baseline, re.M))
    for name in ('backend-identity', 'caos-collection', 'durability-flush', 'future-map'):
        assert job(TEXT, name).split('    steps:\n', 1)[1] == job(baseline, name).split('    steps:\n', 1)[1]
    new_mission = job(TEXT, 'mission-backup').split('    steps:\n', 1)[1]
    new_mission = new_mission.replace(
        '          if [ "$GITHUB_EVENT_NAME" = "workflow_dispatch" ]; then\n'
        '            TRIGGER_SOURCE="manual"\n'
        '          fi\n', '')
    assert new_mission == job(baseline, 'mission-backup').split('    steps:\n', 1)[1]
    assert 'timeout-minutes: 7' in job(TEXT, 'mission-backup')
    assert 'for BATCH in 1 2 3; do' in job(TEXT, 'mission-backup')
    assert '--method POST --timeout 240' in job(TEXT, 'mission-backup')


@pytest.mark.parametrize('event,expected', [('schedule', 'github_schedule'), ('workflow_dispatch', 'manual')])
def test_actual_shell_payload_uses_manual_window_without_extra_authority(event, expected):
    script = _workflow_step_run(job(TEXT, 'mission-backup'), 'Scheduled backup mission tick')
    prefix = script.split('LAST_RESULT=', 1)[0]
    env = {**os.environ, 'ARGUS_ADMIN_TOKEN': 'synthetic-token',
           'EXPECTED_BACKEND_SHA': 'b' * 40, 'GITHUB_RUN_ID': '123', 'GITHUB_EVENT_NAME': event}
    result = subprocess.run(['bash', '-e', '-c', prefix + '\nprintf "%s" "$TICK_PAYLOAD"'],
                            cwd=ROOT, env=env, check=True, capture_output=True, text=True)
    payload = json.loads(result.stdout)
    assert payload == {'triggerSource': expected, 'expectedBuildSha': 'b' * 40, 'runId': '123'}
    assert 'synthetic-token' not in result.stdout + result.stderr


@pytest.mark.parametrize('event,ordinary,mission,mission_result,expected', [
    ('workflow_dispatch', 'false', 'failure', 'partial', 0),
    ('workflow_dispatch', 'true', 'failure', 'partial', 1),
    ('workflow_dispatch', 'true', 'success', 'caught_up', 0),
    ('workflow_dispatch', 'true', 'success', 'busy', 1),
    ('workflow_dispatch', 'true', 'success', 'expected_skip', 1),
    ('schedule', 'false', 'failure', 'partial', 1),
    ('schedule', 'false', 'success', 'busy', 0),
])
def test_actual_result_shell_does_not_mask_owner_run_failures(event, ordinary, mission, mission_result, expected):
    script = _workflow_step_run(job(TEXT, 'result'), 'Report independent control-plane results')
    values = {'github.event_name': event, 'needs.mission-backup.result': mission,
              'needs.mission-backup.outputs.missionResult || needs.mission-backup.result': mission_result,
              'needs.mission-backup.outputs.missionResult': mission_result,
              'needs.backend-identity.outputs.status || needs.backend-identity.result': 'verified',
              'needs.backend-identity.result': 'success', 'needs.caos-collection.result': 'success',
              'needs.caos-collection.outputs.caosResult || needs.caos-collection.result': 'success',
              'needs.durability-flush.result': 'success',
              'needs.durability-flush.outputs.durabilityResult || needs.durability-flush.result': 'verified',
              'needs.durability-flush.outputs.durabilityResult': 'verified'}
    script = re.sub(r'\$\{\{\s*(.*?)\s*\}\}', lambda m: values[m.group(1)], script)
    result = subprocess.run(['bash', '-e', '-c', script], cwd=ROOT,
                            env={**os.environ, 'ARGUS_OWNER_ORDINARY_DISPATCH': ordinary},
                            capture_output=True, text=True)
    assert result.returncode == expected
    if ordinary == 'true':
        assert 'expected_skip_manual_diagnostic' not in result.stdout
