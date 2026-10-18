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


def test_production_diagnostics_never_publish_artifacts_or_print_contents():
    for name in ('runtime-diagnostics', 'render-deploy-diagnostics', 'breadth-freshness'):
        text = (ROOT / '.github/workflows' / f'{name}.yml').read_text()
        assert 'upload-artifact' not in text and 'GITHUB_STEP_SUMMARY' not in text, name
        assert 'private_diagnostics_store.py' in text and 'ARGUS_PRIVATE_LEDGER_TOKEN' in text, name


def test_scheduled_runs_keep_response_bodies_out_of_the_public_log():
    import re
    checks = {
        'caos-scan': ['echo "caos-collect: $RESP"', 'echo "osint-agents: $OS"', 'echo "missions-tick[$BATCH]: $MT"'],
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
