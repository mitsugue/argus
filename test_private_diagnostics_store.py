"""Diagnostics go to the owner's private repository, never a public artifact (2026-10-18)."""
import base64
import json
from pathlib import Path

import pytest

from scripts import private_diagnostics_store as store

ROOT = Path(__file__).resolve().parent


class Response:
    status = 201
    def __enter__(self): return self
    def __exit__(self, *a): return None


def test_files_go_to_the_private_repository_and_nothing_is_printed(tmp_path, capsys):
    (tmp_path / 'snapshot.json').write_text('{"threads":["SECRET_FRAME"]}')
    sent = []
    def opener(request, timeout):
        sent.append(request)
        return Response()
    assert store.store('runtime', '123', [tmp_path / 'snapshot.json'], 't' * 40, opener=opener) == 1
    request = sent[0]
    assert request.full_url == 'https://api.github.com/repos/mitsugue/argus-l2b-private/contents/diagnostics/runtime/123/snapshot.json'
    assert base64.b64decode(json.loads(request.data)['content']) == b'{"threads":["SECRET_FRAME"]}'
    assert 'SECRET_FRAME' not in capsys.readouterr().out


def test_bad_destinations_and_missing_token_are_refused(tmp_path):
    (tmp_path / 'a.json').write_text('{}')
    for kind, run in (('../x', '1'), ('runtime', 'abc'), ('', '1')):
        with pytest.raises(ValueError):
            store.destinations(kind, run, [tmp_path / 'a.json'])
    with pytest.raises(ValueError):
        store.store('runtime', '1', [tmp_path / 'a.json'], '')


def test_rerun_is_append_only_and_preserves_original_destination(tmp_path, capsys):
    path = tmp_path / 'snapshot.json'
    path.write_text('{"phase":"new-private-snapshot"}')
    original = 'https://api.github.com/repos/mitsugue/argus-l2b-private/contents/diagnostics/runtime/123/snapshot.json'
    remote = {original: b'original-snapshot'}

    def create_only(request, timeout):
        assert request.full_url not in remote
        body = json.loads(request.data)
        assert 'sha' not in body
        remote[request.full_url] = base64.b64decode(body['content'])
        return Response()

    assert store.store('runtime', '123', [path], 't' * 40, run_attempt=2, opener=create_only) == 1
    assert remote[original] == b'original-snapshot'
    assert remote[original.replace('/123/', '/123/attempt-2/')] == path.read_bytes()
    assert 'new-private-snapshot' not in capsys.readouterr().out


@pytest.mark.parametrize('attempt', [0, -1, True, 1.5, '01', '../2', '2/3', '', '1000000000'])
def test_invalid_attempt_is_refused_before_any_write(tmp_path, attempt):
    path = tmp_path / 'snapshot.json'
    path.write_text('{}')

    def forbidden(*args, **kwargs):
        pytest.fail('invalid destination reached the network')

    with pytest.raises(ValueError, match='invalid_diagnostics_attempt'):
        store.store('runtime', '123', [path], 't' * 40, run_attempt=attempt, opener=forbidden)


@pytest.mark.parametrize('attempt', ['1', '2'])
def test_cli_passes_the_attempt_without_printing_private_data(tmp_path, monkeypatch, capsys, attempt):
    path = tmp_path / 'snapshot.json'
    path.write_text('PRIVATE_SENTINEL')
    monkeypatch.setenv('PRIVATE_DIAGNOSTICS_TOKEN', 'fake-token')
    calls = []

    def capture(kind, run, files, token, *, run_attempt):
        calls.append((kind, run, files, token, run_attempt))
        return 1

    monkeypatch.setattr(store, 'store', capture)
    assert store.main(['--kind', 'runtime', '--run-id', '123', '--run-attempt', attempt, str(path)]) == 0
    assert calls == [('runtime', '123', [path], 'fake-token', int(attempt))]
    output = capsys.readouterr().out
    assert output == 'private diagnostics: stored 1 file(s)\n'
    assert 'PRIVATE_SENTINEL' not in output and 'fake-token' not in output


def test_observed_identity_is_closed_and_keeps_backend_distinct_from_workflow():
    from scripts.runtime_diagnostics_summary import observed_backend_identity
    health = {'buildSha': 'a' * 40, 'backendVersion': '1.2.3', 'status': 'ok',
              'ownerData': 'PRIVATE_SENTINEL'}
    identity = observed_backend_identity(health, dict(health), {'buildSha': 'a' * 40, 'ready': True},
                                         at='2026-11-01T14:00:00Z')
    assert identity['observedBackendSha'] == 'a' * 40
    assert identity['backendVersion'] == '1.2.3'
    assert identity['status'] == 'verified'
    assert 'PRIVATE_SENTINEL' not in json.dumps(identity)
    assert 'ownerData' not in identity


@pytest.mark.parametrize('patch', [
    {'buildSha': 'b' * 40}, {'buildSha': 'a' * 7}, {'buildSha': None},
    {'backendVersion': '1.2.4'}, {'backendVersion': None}, {'status': 'error'},
])
def test_identity_transition_or_malformed_probe_is_not_accepted(patch):
    from scripts.runtime_diagnostics_summary import observed_backend_identity
    health = {'buildSha': 'a' * 40, 'backendVersion': '1.2.3', 'status': 'ok'}
    with pytest.raises(ValueError, match='runtime_backend_identity_'):
        observed_backend_identity(health, {**health, **patch}, {'buildSha': 'a' * 40, 'ready': True},
                                  at='2026-11-01T14:00:00Z')


@pytest.mark.parametrize('ready', [{'buildSha': 'b' * 40, 'ready': True},
                                  {'buildSha': 'a' * 40, 'ready': False}])
def test_unready_or_different_ready_build_is_not_accepted(ready):
    from scripts.runtime_diagnostics_summary import observed_backend_identity
    health = {'buildSha': 'a' * 40, 'backendVersion': '1.2.3', 'status': 'ok'}
    with pytest.raises(ValueError, match='runtime_backend_identity_'):
        observed_backend_identity(health, health, ready, at='2026-11-01T14:00:00Z')


@pytest.mark.parametrize('at', ['not-a-date', '2026-11-01T14:00:00', None])
def test_identity_requires_an_explicit_timestamp(at):
    from scripts.runtime_diagnostics_summary import observed_backend_identity
    health = {'buildSha': 'a' * 40, 'backendVersion': '1.2.3', 'status': 'ok'}
    with pytest.raises(ValueError, match='runtime_backend_identity_'):
        observed_backend_identity(health, health, {'buildSha': 'a' * 40, 'ready': True}, at=at)


def test_production_diagnostics_never_publish_artifacts_or_print_contents():
    for name in ('runtime-diagnostics', 'render-deploy-diagnostics', 'breadth-freshness'):
        text = (ROOT / '.github/workflows' / f'{name}.yml').read_text()
        assert 'upload-artifact' not in text and 'GITHUB_STEP_SUMMARY' not in text, name
        assert 'private_diagnostics_store.py' in text and 'ARGUS_PRIVATE_LEDGER_TOKEN' in text, name
    runtime = (ROOT / '.github/workflows/runtime-diagnostics.yml').read_text()
    assert '--run-attempt "${{ github.run_attempt }}"' in runtime
    assert 'backend-identity.json' in runtime
    assert 'schedule:' not in runtime


def test_scheduled_runs_keep_response_bodies_out_of_the_public_log():
    import re
    checks = {
        'crypto-watch': ['echo "crypto-scan: $RESP"'],
        'prediction-ledger': ['echo "gate: $GATE"', 'echo "ai run: $SHORT"', 'provider diag: \\`${DIAG}'],
        'news-intake-ops': ['tee -a "$GITHUB_STEP_SUMMARY"', 'echo "reprocess: $RESP"'],
        'backend-warm-after-deploy': ['run_intel_collect.py --base "$BE" --timeout 900 || exit 1'],
        'macro-event-analysis': ['echo "generate: ${GEN:0:200}', 'echo "refresh-results: ${RES:0:200}"'],
    }
    for name, banned in checks.items():
        text = (ROOT / '.github/workflows' / f'{name}.yml').read_text()
        for line in banned:
            assert line not in text, (name, line)
        assert 'private_diagnostics_store.py' in text and 'stored privately' in text, name
