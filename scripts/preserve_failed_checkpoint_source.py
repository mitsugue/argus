"""失敗した既存検査の正確な入力を、既存の非公開診断保存へ渡す。"""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile

from scripts import private_diagnostics_store

SOURCE_LIMIT = 128 * 1024 * 1024
CHUNK_BYTES = 7 * 1024 * 1024
PROOF_JOBS = frozenset(('linux-4gib-cgroup', 'mapping-attribution',
    'mapping-syscall-trace', 'mapping-closure-32', 'isolated-writer-closure-32'))


def prepare(source, output, *, run_id, attempt, revision, needs):
    """原入力は変更せず、圧縮した不変片と再結合用の検証情報だけを作る。"""
    source, output = Path(source), Path(output)
    if (not re.fullmatch(r'[0-9]{1,20}', run_id or '')
            or not re.fullmatch(r'[0-9]{1,6}', attempt or '')
            or not re.fullmatch(r'[0-9a-f]{40}', revision or '')):
        raise ValueError('checkpoint_identity_invalid')
    if (not isinstance(needs, dict) or set(needs) != PROOF_JOBS | {'exact-public-state'}
            or any(not isinstance(row, dict) or row.get('result') not in
                   ('success', 'failure', 'cancelled', 'skipped') for row in needs.values())
            or needs['exact-public-state'].get('result') != 'success'
            or not any(needs[name].get('result') == 'failure' for name in PROOF_JOBS)):
        raise ValueError('failed_checkpoint_proof_required')
    if source.is_symlink() or not source.is_file() or not 0 < source.stat().st_size <= SOURCE_LIMIT:
        raise ValueError('checkpoint_source_bound')
    with source.open(encoding='utf-8') as handle:
        value = json.load(handle)
    if not isinstance(value, dict) or not value:
        raise ValueError('checkpoint_source_object_required')
    del value
    output.mkdir(mode=0o700, parents=False, exist_ok=False)
    raw_digest, compressed_digest = hashlib.sha256(), hashlib.sha256()
    raw_bytes = 0
    # 一時圧縮ファイルは非公開転送用の生成物。元入力には書き込まない。
    with tempfile.TemporaryFile() as compressed:
        with gzip.GzipFile(fileobj=compressed, mode='wb', filename='', mtime=0) as packed:
            with source.open('rb') as handle:
                while data := handle.read(1024 * 1024):
                    raw_bytes += len(data)
                    if raw_bytes > SOURCE_LIMIT:
                        raise ValueError('checkpoint_source_bound')
                    raw_digest.update(data)
                    packed.write(data)
        compressed.seek(0)
        chunks = []
        while data := compressed.read(CHUNK_BYTES):
            if len(chunks) >= private_diagnostics_store.MAX_FILES - 1:
                raise ValueError('checkpoint_chunk_bound')
            name = f'attempt-{attempt}-source.json.gz.part{len(chunks):03d}'
            path = output / name
            path.write_bytes(data)
            path.chmod(0o600)
            compressed_digest.update(data)
            chunks.append({'name': name, 'bytes': len(data),
                           'sha256': hashlib.sha256(data).hexdigest()})
    manifest = {'schemaVersion': 'argus-failed-checkpoint-source-v1',
        'runId': run_id, 'attempt': attempt, 'codeRevision': revision,
        'sourceBytes': raw_bytes, 'sourceSha256': raw_digest.hexdigest(),
        'compression': 'gzip', 'compressedSha256': compressed_digest.hexdigest(),
        'chunks': chunks,
        'jobResults': {name: needs[name]['result'] for name in sorted(needs)},
        'runtimeIdentity': 'REQUIRES_ORIGINAL_JOB_LOGS_NOT_INFERRED_FROM_THIS_READER',
        'additionalProductionReads': 0, 'sourceModified': False}
    path = output / f'attempt-{attempt}-source-manifest.json'
    path.write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True,
                               separators=(',', ':')), encoding='utf-8')
    path.chmod(0o600)
    files = sorted(output.iterdir())
    private_diagnostics_store.destinations('checkpoint-failed-source', run_id, files)
    return files


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args(argv)
    try:
        files = prepare(args.source, args.output, run_id=os.environ.get('GITHUB_RUN_ID', ''),
            attempt=os.environ.get('GITHUB_RUN_ATTEMPT', ''),
            revision=os.environ.get('GITHUB_SHA', ''),
            needs=json.loads(os.environ.get('CHECKPOINT_PROOF_RESULTS', '{}')))
        count = private_diagnostics_store.store('checkpoint-failed-source',
            os.environ['GITHUB_RUN_ID'], files,
            os.environ.get('PRIVATE_DIAGNOSTICS_TOKEN', ''))
    except (ValueError, OSError, KeyError):
        # 元入力・応答・パス・例外本文を公開ログへ出さない。
        print('private checkpoint source: preservation failed')
        return 1
    print(f'private checkpoint source: stored {count} file(s)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
