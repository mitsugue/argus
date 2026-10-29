"""失敗時の入力を期限切れで失わず、公開せずに完全再結合できること。"""
import gzip
import hashlib
import json
import os
from pathlib import Path
import re

import pytest

from scripts import preserve_failed_checkpoint_source as preserve


def arguments():
    needs = {name: {'result': 'success'} for name in preserve.PROOF_JOBS | {'exact-public-state'}}
    needs['mapping-closure-32']['result'] = 'failure'
    return dict(run_id='12345', attempt='2', revision='a' * 40, needs=needs)


def test_private_chunks_restore_exact_original_bytes_and_attempt_identity(tmp_path, monkeypatch):
    source = tmp_path / 'source.json'
    original = json.dumps({'input': os.urandom(2000).hex(), 'text': '改訂前の入力'},
                          ensure_ascii=False, indent=2).encode() + b'\n'
    source.write_bytes(original)
    monkeypatch.setattr(preserve, 'CHUNK_BYTES', 256)
    files = preserve.prepare(source, tmp_path / 'output', **arguments())
    manifest = json.loads(next(p for p in files if p.suffix == '.json').read_text())
    packed = b''.join((tmp_path / 'output' / item['name']).read_bytes() for item in manifest['chunks'])
    assert len(manifest['chunks']) > 1
    assert all(hashlib.sha256((tmp_path / 'output' / item['name']).read_bytes()).hexdigest()
               == item['sha256'] for item in manifest['chunks'])
    assert hashlib.sha256(packed).hexdigest() == manifest['compressedSha256']
    assert gzip.decompress(packed) == original == source.read_bytes()
    assert manifest['sourceSha256'] == hashlib.sha256(original).hexdigest()
    assert manifest['sourceBytes'] == len(original)
    assert manifest['codeRevision'] == 'a' * 40 and manifest['attempt'] == '2'
    assert all(p.stat().st_mode & 0o777 == 0o600 for p in files)
    assert manifest['runtimeIdentity'].startswith('REQUIRES_ORIGINAL_JOB_LOGS')


@pytest.mark.parametrize('change', ['success', 'source_failure', 'bad_job', 'bad_revision', 'bad_run'])
def test_no_success_only_or_unidentified_input_is_stored(tmp_path, change):
    source = tmp_path / 'source.json'; source.write_text('{"input": 1}')
    args = arguments()
    if change == 'success': args['needs']['mapping-closure-32']['result'] = 'success'
    if change == 'source_failure': args['needs']['exact-public-state']['result'] = 'failure'
    if change == 'bad_job': args['needs']['mapping-closure-32']['result'] = 'unknown_private_text'
    if change == 'bad_revision': args['revision'] = 'main'
    if change == 'bad_run': args['run_id'] = '../123'
    with pytest.raises(ValueError): preserve.prepare(source, tmp_path / 'out', **args)
    assert not (tmp_path / 'out').exists()


@pytest.mark.parametrize('kind', ['symlink', 'too_large', 'empty_object', 'array', 'malformed'])
def test_invalid_or_unbounded_original_is_refused(tmp_path, monkeypatch, kind):
    source = tmp_path / 'source.json'; source.write_text('{"input": 1}')
    if kind == 'symlink':
        target = tmp_path / 'target.json'; source.rename(target); source.symlink_to(target)
    if kind == 'too_large': monkeypatch.setattr(preserve, 'SOURCE_LIMIT', 1)
    if kind == 'empty_object': source.write_text('{}')
    if kind == 'array': source.write_text('[1]')
    if kind == 'malformed': source.write_text('PRIVATE_INPUT_BROKEN')
    with pytest.raises(ValueError): preserve.prepare(source, tmp_path / 'out', **arguments())
    assert not (tmp_path / 'out').exists()


def test_private_store_failure_is_failure_without_input_in_public_log(tmp_path, monkeypatch, capsys):
    source = tmp_path / 'source.json'; source.write_text('{"PRIVATE_INPUT_MARKER": 1}')
    args = arguments()
    for key, value in {'GITHUB_RUN_ID': args['run_id'], 'GITHUB_RUN_ATTEMPT': args['attempt'],
            'GITHUB_SHA': args['revision'], 'CHECKPOINT_PROOF_RESULTS': json.dumps(args['needs']),
            'PRIVATE_DIAGNOSTICS_TOKEN': 'existing-test-credential'}.items(): monkeypatch.setenv(key, value)
    def fail(*args, **kwargs): raise ValueError('PRIVATE_INPUT_MARKER')
    monkeypatch.setattr(preserve, 'require_private_destination', lambda *args: None)
    monkeypatch.setattr(preserve.private_diagnostics_store, 'store', fail)
    assert preserve.main(['--source', str(source), '--output', str(tmp_path / 'out')]) == 1
    assert capsys.readouterr().out == 'private checkpoint source: preservation failed\n'


@pytest.mark.parametrize('private,name,accepted', [
    (True, 'mitsugue/argus-l2b-private', True),
    (False, 'mitsugue/argus-l2b-private', False),
    (True, 'other/private', False), (None, 'mitsugue/argus-l2b-private', False)])
def test_public_or_wrong_destination_is_never_admitted(private, name, accepted):
    class Response:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def read(self, limit): return json.dumps({'private': private, 'full_name': name}).encode()
    calls = []
    def opener(request, timeout): calls.append(request); return Response()
    if accepted: preserve.require_private_destination('existing-token', opener)
    else:
        with pytest.raises(ValueError): preserve.require_private_destination('existing-token', opener)
    assert calls[0].get_method() == 'GET'
    assert calls[0].full_url == 'https://api.github.com/repos/mitsugue/argus-l2b-private'
    assert preserve.NoRedirect().redirect_request(None, None, 302, '', {}, 'https://other') is None


def test_workflow_preserves_only_existing_failed_source_without_refetch_or_public_upload():
    workflow = (Path(__file__).parent / '.github/workflows/checkpoint-v2-gate.yml').read_text()
    text = workflow.split('\n  preserve-failed-exact-state:\n', 1)[1]
    dependencies = re.search(r'needs: \[([^]]+)\]', text).group(1)
    assert {name.strip() for name in dependencies.split(',')} == preserve.PROOF_JOBS | {'exact-public-state'}
    assert "needs.exact-public-state.result == 'success'" in text
    assert "contains(needs.*.result, 'failure')" in text
    assert 'actions/download-artifact@v5' in text and 'owner-artifact-envelope.mjs unseal' in text
    assert 'ARGUS_PRIVATE_LEDGER_TOKEN' in text and 'ARGUS_OWNER_ARTIFACT_KEY' in text
    assert 'upload-artifact' not in text and 'memory-snapshot' not in text and 'curl' not in text
