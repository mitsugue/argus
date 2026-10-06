import base64
import io
import json
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

import pytest
from scripts import persist_backup_vault as vault


def payload(timestamp=1791288000):
    blob = json.dumps({'v': 1, 'salt': base64.b64encode(b's' * 16).decode(),
                       'iv': base64.b64encode(b'i' * 12).decode(),
                       'ct': base64.b64encode(b'c' * 32).decode(),
                       'exportedAt': '2026-10-06T14:00:00Z'})
    return json.dumps({'slots': {'a' * 64: {'ts': timestamp, 'blob': blob}}})


@pytest.mark.parametrize('initial', [(502, '<html>private-body</html>'), (200, ''), (200, '<html>private-body</html>')])
def test_temporary_invalid_response_retries_without_logging_body(initial, tmp_path):
    err = io.StringIO()
    with patch.object(vault, 'request_json', side_effect=[initial, (200, payload())]) as request, patch.object(vault.time, 'sleep'), redirect_stderr(err):
        slots = vault.fetch_slots('https://example.invalid', 'private-token')
    assert request.call_count == 2
    assert 'private-body' not in err.getvalue() and 'private-token' not in err.getvalue()
    assert vault.persist_slots(slots, tmp_path) == 1
    assert (tmp_path / ('a' * 64) / 'latest.json').read_text() == slots[0][2]


def test_exhausted_fetch_keeps_existing_backup_and_fails(tmp_path, monkeypatch):
    old = tmp_path / 'existing.json'; old.write_text('unchanged')
    monkeypatch.setenv('ARGUS_ADMIN_TOKEN', 'private-token')
    out, err = io.StringIO(), io.StringIO()
    with patch.object(vault, 'request_json', return_value=(502, 'private-body')) as request, patch.object(vault.time, 'sleep'), redirect_stdout(out), redirect_stderr(err):
        rc = vault.main(['--url', 'https://example.invalid', '--ledger-root', str(tmp_path)])
    assert rc == 1 and request.call_count == 3
    assert old.read_text() == 'unchanged' and list(tmp_path.iterdir()) == [old]
    assert 'http_502' in err.getvalue()
    assert 'private-token' not in out.getvalue() + err.getvalue()
    assert 'private-body' not in out.getvalue() + err.getvalue()


def test_auth_denial_does_not_retry_or_look_empty():
    with patch.object(vault, 'request_json', return_value=(401, '{}')) as request:
        with pytest.raises(vault.VaultFailure, match='http_401'):
            vault.fetch_slots('https://example.invalid', 'token')
    assert request.call_count == 1


@pytest.mark.parametrize('raw', ['{}', '{"slots":[]}', '{"slots":{"bad":{"blob":"private"}}}'])
def test_invalid_shape_is_failure_not_empty_backup(raw):
    with patch.object(vault, 'request_json', return_value=(200, raw)) as request:
        with pytest.raises(vault.VaultFailure):
            vault.fetch_slots('https://example.invalid', 'token')
    assert request.call_count == 1


def test_all_slots_validated_before_any_writes(tmp_path):
    value = json.loads(payload()); value['slots']['b' * 64] = {'ts': 10, 'blob': '{"owner":"private"}'}
    with pytest.raises(vault.VaultFailure, match='invalid_envelope'):
        vault.persist_slots(vault.validated_slots(json.dumps(value)), tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_empty_slots_and_missing_token_are_distinct(tmp_path):
    assert vault.persist_slots(vault.validated_slots('{"slots":{}}'), tmp_path) == 0
    with patch.object(vault, 'request_json') as request:
        with pytest.raises(vault.VaultFailure, match='missing_admin_token'):
            vault.fetch_slots('https://example.invalid', '')
    request.assert_not_called()


def test_same_timestamp_conflict_preserves_all_existing_bytes(tmp_path):
    slots = vault.validated_slots(payload()); vault.persist_slots(slots, tmp_path)
    before = {p.name: p.read_bytes() for p in tmp_path.rglob('*.json')}
    identity, stamp, blob = slots[0]
    with pytest.raises(vault.VaultFailure, match='existing_snapshot_conflict'):
        vault.persist_slots([(identity, stamp, blob + ' ')], tmp_path)
    assert before == {p.name: p.read_bytes() for p in tmp_path.rglob('*.json')}


def test_late_replay_does_not_regress_latest(tmp_path):
    newer = vault.validated_slots(payload()); vault.persist_slots(newer, tmp_path)
    latest = tmp_path / ('a' * 64) / 'latest.json'; before = latest.read_bytes()
    old = json.loads(payload(1791201600)); env = json.loads(old['slots']['a' * 64]['blob']); env['exportedAt'] = '2026-10-05T14:00:00Z'
    old['slots']['a' * 64]['blob'] = json.dumps(env)
    vault.persist_slots(vault.validated_slots(json.dumps(old)), tmp_path)
    assert latest.read_bytes() == before


def test_staged_helper_import_survives_ledger_branch_checkout(tmp_path):
    import os
    from pathlib import Path
    import shutil
    import subprocess
    import sys
    runtime = tmp_path / 'runtime' / 'scripts'; runtime.mkdir(parents=True)
    root = Path(__file__).parent
    for name in ('persist_backup_vault.py', 'workflow_http.py'):
        shutil.copyfile(root / 'scripts' / name, runtime / name)
    ledger = tmp_path / 'ledger'; ledger.mkdir()
    result = subprocess.run([sys.executable, str(runtime / 'persist_backup_vault.py'),
        '--url', 'https://example.invalid', '--ledger-root', 'ledger/vault'],
        cwd=ledger, env={**os.environ, 'PYTHONPATH': '', 'ARGUS_ADMIN_TOKEN': ''},
        capture_output=True, text=True)
    assert result.returncode == 1
    assert 'missing_admin_token' in result.stderr
    assert 'ModuleNotFoundError' not in result.stderr
