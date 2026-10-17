"""Run the shared Node transport contract against the actual synthetic Flask server."""
import os
from pathlib import Path
import shutil
import subprocess
import sys


def test_owner_reader_transport_and_real_boundary():
    node = shutil.which('node')
    assert node, 'Node is required for the owner reader contract'
    repo = Path(__file__).resolve().parent
    result = subprocess.run([
        node, '--test', 'web/scripts/owner-auth-reader.test.mjs',
        'web/scripts/owner-auth-reader.integration.test.mjs',
    ], cwd=str(repo), env=dict(os.environ, ARGUS_TEST_PYTHON=sys.executable),
       capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr


def test_cli_auth_failure_has_bounded_failed_evidence(tmp_path):
    import json
    repo = Path(__file__).resolve().parent
    trigger = tmp_path / 'synthetic-trigger.json'
    trigger.write_text(json.dumps({'producerTriggerId': 'synthetic-trigger'}))
    for command in ('trigger-business', 'verify-business'):
        out = tmp_path / (command + '.json')
        result = subprocess.run([
            shutil.which('node'), 'web/scripts/release-state-machine.mjs', command,
            '--contract', 'release/v13-snapshot-readiness-contract.json',
            '--base-url', 'https://backend.example', '--expected-sha', 'a' * 40,
            '--trigger-id', 'synthetic-trigger', '--trigger-artifact', str(trigger),
            '--out', str(out),
        ], cwd=str(repo), env=dict(os.environ, ARGUS_ACCEPTANCE_OWNER_AUTH='invalid',
                                  ARGUS_ACCEPTANCE_OWNER_PASSWORD='synthetic-never-log-this'),
           capture_output=True, text=True, timeout=10)
        assert result.returncode != 0
        value = json.loads(out.read_text())
        assert value['status'] == 'failed'
        assert value['producerTriggerId'] == 'synthetic-trigger'
        assert value['reason'] == 'owner_reader:configuration'
        assert 'synthetic-never-log-this' not in out.read_text() + result.stdout + result.stderr
