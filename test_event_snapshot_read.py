import io
import json
import urllib.error

import pytest

from scripts.event_snapshot_read import read_snapshot


def snapshot(active=None, log=None, **extra):
    active = [] if active is None else active
    return {'schemaVersion': 'event-store-v1', 'snapshotAt': '2026-10-29T08:00:00Z',
            'activeCount': len(active), 'active': active,
            'log': [] if log is None else log, **extra}


class Response:
    status = 200
    def __init__(self, body): self.body = body
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def read(self, size): return self.body


def test_transient_unavailability_then_valid_snapshot(tmp_path):
    calls = []
    def request(req, timeout):
        calls.append(req)
        if len(calls) < 3:
            raise urllib.error.HTTPError(req.full_url, 503, 'private', {}, None)
        return Response(json.dumps(snapshot([{}, {}], private='body')).encode())
    now = [0]
    result = read_snapshot(url='https://example.test', token='secret', output=tmp_path/'snap',
                           request=request, clock=lambda: now[0], sleep=lambda n: now.__setitem__(0, now[0]+n))
    assert result == {'status': 'done', 'activeCount': 2, 'logCount': 0, 'attempts': 3}
    assert json.loads((tmp_path/'snap').read_text())['activeCount'] == 2
    assert 'secret' not in json.dumps(result) and 'private' not in json.dumps(result)


def test_auth_rejection_does_not_retry_or_write(tmp_path):
    calls = []
    def request(req, timeout):
        calls.append(1)
        raise urllib.error.HTTPError(req.full_url, 401, 'secret', {}, None)
    result = read_snapshot(url='https://example.test', token='secret', output=tmp_path/'snap', request=request)
    assert result['errorClass'] == 'snapshot_rejected' and result['httpStatus'] == 401
    assert len(calls) == 1 and not (tmp_path/'snap').exists()


def test_log_only_snapshot_is_saved_and_revisions_restore_without_live_authority(tmp_path):
    from scripts.event_snapshot_read import stage_snapshot
    from argus_event_store import restore_state
    target = tmp_path / 'snap'
    event = {'eventId': 'synthetic-event', 'symbol': 'TEST', 'market': 'JP',
             'eventType': 'PRICE_MOVE', 'lifecycleState': 'EXPIRED',
             'sourceTimeValidated': True, 'dossier': {'revision': 2}}
    value = snapshot(log=[event])
    result = read_snapshot(url='https://example.test', token='secret', output=target,
                           request=lambda *a, **k: Response(json.dumps(value).encode()))
    assert result['activeCount'] == 0 and result['logCount'] == 1
    root = tmp_path / 'events'
    result = stage_snapshot(target, root, '2026-10-29')
    assert result['status'] == 'changed' and result['appendedRows'] == 1
    saved = json.loads((root / 'snapshot.json').read_text())
    assert saved == value
    active, log = restore_state(saved, 0, lambda _: None, lambda e: e['eventId'])
    assert active == {} and log[0]['dossier'] == {'revision': 2}
    assert log[0]['sourceTimeValidated'] is False and log[0]['restoredFromSnapshot'] is True


def test_timestamp_only_poll_and_repeated_rows_do_not_duplicate_history(tmp_path):
    from scripts.event_snapshot_read import stage_snapshot
    root, source = tmp_path / 'events', tmp_path / 'snap'
    event = {'eventId': 'synthetic-event', 'lifecycleState': 'ACTIVE', 'reasonJa': '合成'}
    source.write_text(json.dumps(snapshot([event], [event])))
    assert stage_snapshot(source, root, '2026-10-29')['appendedRows'] == 1
    old_snapshot = (root / 'snapshot.json').read_bytes()
    old_log = (root / 'log/2026-10-29.jsonl').read_bytes()
    source.write_text(json.dumps(snapshot([event], [event], snapshotAt='2026-10-29T08:15:00Z')))
    assert stage_snapshot(source, root, '2026-10-29')['status'] == 'unchanged'
    assert (root / 'snapshot.json').read_bytes() == old_snapshot
    assert (root / 'log/2026-10-29.jsonl').read_bytes() == old_log
    revised = {**event, 'lifecycleState': 'EXPIRED'}
    source.write_text(json.dumps(snapshot(log=[revised])))
    assert stage_snapshot(source, root, '2026-10-29')['appendedRows'] == 1
    assert (root / 'log/2026-10-29.jsonl').read_bytes().startswith(old_log)
    assert len((root / 'log/2026-10-29.jsonl').read_text().splitlines()) == 2
    # A dossier-only revision must survive even though the short daily row is unchanged.
    source.write_text(json.dumps(snapshot(log=[{**revised, 'dossier': {'revision': 3}}])))
    assert stage_snapshot(source, root, '2026-10-29')['status'] == 'changed'
    assert json.loads((root / 'snapshot.json').read_text())['log'][0]['dossier']['revision'] == 3
    assert len((root / 'log/2026-10-29.jsonl').read_text().splitlines()) == 2


@pytest.mark.parametrize('patch', [
    {'schemaVersion': 'other'}, {'activeCount': True}, {'activeCount': 1},
    {'active': [None], 'activeCount': 1}, {'log': None}, {'log': [{}] * 201},
    {'snapshotAt': None},
])
def test_invalid_snapshot_never_replaces_saved_bytes(tmp_path, patch):
    target = tmp_path / 'snap'
    target.write_text('prior')
    value = snapshot()
    value.update(patch)
    result = read_snapshot(url='https://example.test', token='secret', output=target,
                           request=lambda *a, **k: Response(json.dumps(value).encode()))
    assert result['errorClass'] == 'snapshot_invalid'
    assert target.read_text() == 'prior'


def test_empty_or_invalid_staging_preserves_originals(tmp_path):
    from scripts.event_snapshot_read import stage_snapshot
    source, root = tmp_path / 'snap', tmp_path / 'events'
    source.write_text(json.dumps(snapshot(log=[{'eventId': 'synthetic'}])))
    stage_snapshot(source, root, '2026-10-29')
    before = {p: p.read_bytes() for p in root.rglob('*') if p.is_file()}
    source.write_text(json.dumps(snapshot()))
    assert stage_snapshot(source, root, '2026-10-29')['status'] == 'empty'
    assert all(p.read_bytes() == b for p, b in before.items())
    source.write_text(json.dumps(snapshot(log=[{'eventId': 'new-synthetic'}])))
    with pytest.raises(ValueError):
        stage_snapshot(source, root, '../2026-10-29')
    (root / 'log/2026-10-29.jsonl').write_text('not-json\n')
    original = (root / 'snapshot.json').read_bytes()
    with pytest.raises(ValueError):
        stage_snapshot(source, root, '2026-10-29')
    assert (root / 'snapshot.json').read_bytes() == original


def test_workflow_uses_history_and_the_exact_validated_source():
    from pathlib import Path
    workflow = (Path(__file__).parent / '.github/workflows/event-ledger.yml').read_text()
    assert "if: env.STATE_ITEMS != '0'" in workflow
    assert "if: env.ACTIVE != '0'" not in workflow
    assert 'ref: ${{ github.sha }}' in workflow
    assert 'cp scripts/event_snapshot_read.py "$RUNNER_TEMP/event_snapshot_read.py"' in workflow
    assert 'python3 "$RUNNER_TEMP/event_snapshot_read.py" --stage' in workflow


def test_existing_day_bytes_without_final_newline_and_symlinks(tmp_path):
    from scripts.event_snapshot_read import stage_snapshot
    source, root = tmp_path / 'snap', tmp_path / 'events'
    root.mkdir()
    (root / 'log').mkdir()
    daily = root / 'log/2026-10-29.jsonl'
    daily.write_text('{"eventId":"previous"}')
    before = daily.read_bytes()
    source.write_text(json.dumps(snapshot(log=[{'eventId': 'synthetic'}])))
    stage_snapshot(source, root, '2026-10-29')
    assert daily.read_bytes().startswith(before + b'\n')
    assert len([json.loads(line) for line in daily.read_text().splitlines()]) == 2
    saved = (root / 'snapshot.json').read_bytes()
    other = tmp_path / 'other'
    other.write_bytes(saved)
    (root / 'snapshot.json').unlink()
    (root / 'snapshot.json').symlink_to(other)
    with pytest.raises(ValueError):
        stage_snapshot(source, root, '2026-10-29')
    assert other.read_bytes() == saved


def test_history_only_cli_exports_a_nonzero_save_gate(tmp_path, monkeypatch, capsys):
    import scripts.event_snapshot_read as reader
    monkeypatch.setattr('sys.argv', ['event_snapshot_read.py'])
    env_file = tmp_path / 'env'
    monkeypatch.setenv('GITHUB_ENV', str(env_file))
    monkeypatch.setenv('RUNNER_TEMP', str(tmp_path))
    monkeypatch.setattr(reader, 'read_snapshot', lambda **kw: {
        'status': 'done', 'activeCount': 0, 'logCount': 2, 'attempts': 1})
    assert reader.main() == 0
    assert env_file.read_text() == 'ACTIVE=0\nSTATE_ITEMS=2\n'
    assert json.loads(capsys.readouterr().out)['logCount'] == 2


def test_timeout_and_malformed_snapshot_do_not_overwrite(tmp_path):
    target = tmp_path/'snap'
    target.write_text('prior')
    now = [0]
    def unavailable(req, timeout): raise TimeoutError('secret')
    result = read_snapshot(url='https://example.test', token='secret', output=target, timeout=30,
                           request=unavailable, clock=lambda: now[0], sleep=lambda n: now.__setitem__(0, now[0]+n))
    assert result['errorClass'] == 'snapshot_timeout' and target.read_text() == 'prior'
    result = read_snapshot(url='https://example.test', token='secret', output=target,
                           request=lambda *a, **k: Response(b'{"activeCount":"2\\nEVIL=1"}'))
    assert result['errorClass'] == 'snapshot_invalid' and target.read_text() == 'prior'


def test_redirect_is_not_followed_and_never_retries(tmp_path):
    from scripts.event_snapshot_read import _NoRedirect
    handler = _NoRedirect()
    assert handler.redirect_request(None, None, 302, 'redirect', {}, 'https://other.example') is None
    calls = []
    def redirect(req, timeout):
        calls.append(1)
        raise urllib.error.HTTPError(req.full_url, 302, 'redirect', {}, None)
    result = read_snapshot(url='https://example.test', token='secret', output=tmp_path/'snap', request=redirect)
    assert result['errorClass'] == 'snapshot_rejected' and result['httpStatus'] == 302
    assert len(calls) == 1 and not (tmp_path/'snap').exists()
