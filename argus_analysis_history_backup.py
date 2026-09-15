"""Content-addressed recovery of public analysis history in the existing private store.

A verified snapshot is merged by immutable record ID before a moving pointer is
advanced with compare-and-swap. Missing remote data and unavailable remote data
are distinct. No trading decisions, private portfolios or providers are accessed.
"""
import base64
from collections import deque
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile
import time

import argus_analysis_history as history

PREFIX = 'market-analysis/v1'
MAX_ARCHIVE_BYTES = 128 * 1024 * 1024
CHUNK_BYTES = 512 * 1024
MAX_SYNC_SECONDS = 180
SCHEMA = 'argus-public-analysis-backup-v1'


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(value).hexdigest()


def valid_digest(value):
    return isinstance(value, str) and len(value) == 64 and all(c in '0123456789abcdef' for c in value)


def _outcome(value):
    if not isinstance(value, dict): raise ValueError('history_outcome_invalid')
    body = dict(value); checksum = body.pop('resultDigest', None)
    if checksum != digest(encode(body)): raise ValueError('history_outcome_digest_invalid')
    identity = body.pop('resultId', None); body.pop('receivedAt', None)
    if identity != digest(encode(body)) or value.get('actionAuthority') is not False:
        raise ValueError('history_outcome_identity_invalid')
    if value.get('predictiveProbabilityVerified') is not False or not valid_digest(value.get('recordId')):
        raise ValueError('history_outcome_authority_invalid')
    history._instant(value['receivedAt'])
    return value


def _snapshot(path, directory):
    """Read one SQLite transaction into bounded, content-addressed chunks on disk."""
    archive = Path(directory) / 'archive.ndjson'
    conn = history._connect(path, True)
    counts = {'views': 0, 'outcomes': 0}; latest = None
    try:
        conn.execute('BEGIN')
        with archive.open('wb') as out:
            out.write(encode({'schemaVersion': SCHEMA}) + b'\n')
            for kind, table, validator in (('view', 'views', history.validate_record), ('outcome', 'outcomes', _outcome)):
                for (raw,) in conn.execute(f'SELECT body FROM {table} ORDER BY sequence'):
                    value = validator(json.loads(raw))
                    out.write(encode({'kind': kind, 'value': value}) + b'\n')
                    if out.tell() > MAX_ARCHIVE_BYTES: raise ValueError('history_archive_bound_exceeded')
                    counts[table] += 1
                    if kind == 'view': latest = value['recordId']
            out.flush(); os.fsync(out.fileno())
        latest_row = conn.execute('SELECT record_id FROM views ORDER BY julianday(recorded_at) DESC,sequence DESC LIMIT 1').fetchone()
        latest = latest_row[0] if latest_row else None
        conn.execute('COMMIT')
    finally: conn.close()
    chunks = []; archive_hash = hashlib.sha256(); total = 0
    with archive.open('rb') as source:
        while raw := source.read(CHUNK_BYTES):
            identity = digest(raw); archive_hash.update(raw); total += len(raw)
            (Path(directory) / identity).write_bytes(raw)
            chunks.append({'sha256': identity, 'bytes': len(raw)})
    body = {'schemaVersion': SCHEMA, 'scope': 'PUBLIC_MARKET', 'actionAuthority': False,
            'archiveSha256': archive_hash.hexdigest(), 'archiveBytes': total, 'chunks': chunks,
            'counts': counts, 'latestRecordId': latest}
    return body


def _manifest(raw):
    if len(raw) > 128 * 1024: raise ValueError('history_manifest_bound')
    value = json.loads(raw)
    if (value.get('schemaVersion') != SCHEMA or value.get('scope') != 'PUBLIC_MARKET'
            or value.get('actionAuthority') is not False or not valid_digest(value.get('archiveSha256'))):
        raise ValueError('history_manifest_invalid')
    chunks = value.get('chunks')
    if not isinstance(chunks, list) or not 1 <= len(chunks) <= MAX_ARCHIVE_BYTES // CHUNK_BYTES:
        raise ValueError('history_chunk_count_invalid')
    if any(not isinstance(p, dict) or not valid_digest(p.get('sha256')) or type(p.get('bytes')) is not int
           or not 1 <= p['bytes'] <= CHUNK_BYTES for p in chunks):
        raise ValueError('history_chunk_manifest_invalid')
    if sum(p['bytes'] for p in chunks) != value.get('archiveBytes'):
        raise ValueError('history_archive_size_invalid')
    return value


def _head(remote):
    raw, version = remote.get(PREFIX + '/head.json')
    if raw is None:
        if version is not None: raise ValueError('history_missing_head_version')
        return None, None
    value = json.loads(raw)
    if set(value) != {'schemaVersion', 'manifestSha256'} or value['schemaVersion'] != SCHEMA or not valid_digest(value['manifestSha256']):
        raise ValueError('history_head_invalid')
    manifest_raw, _ = remote.get(PREFIX + '/manifests/' + value['manifestSha256'] + '.json')
    if manifest_raw is None or digest(manifest_raw) != value['manifestSha256']:
        raise ValueError('history_remote_manifest_missing_or_corrupt')
    return _manifest(manifest_raw), version


def _restore(path, manifest, remote, directory):
    """Validate the whole remote snapshot before adding anything to the live file."""
    archive = Path(directory) / 'received.ndjson'; checksum = hashlib.sha256()
    chunks = manifest['chunks']
    reader = getattr(remote, 'read_chunks', None)
    reads = reader(chunks) if callable(reader) else (
        remote.get(PREFIX + '/chunks/' + chunk['sha256'] + '.bin')[0] for chunk in chunks)
    try:
        with archive.open('wb') as out:
            for chunk, raw in zip(chunks, reads, strict=True):
                if raw is None or len(raw) != chunk['bytes'] or digest(raw) != chunk['sha256']:
                    raise ValueError('history_remote_chunk_missing_or_corrupt')
                checksum.update(raw); out.write(raw)
    finally:
        close = getattr(reads, 'close', None)
        if callable(close): close()
    if checksum.hexdigest() != manifest['archiveSha256']:
        raise ValueError('history_remote_archive_digest_invalid')
    staging = Path(directory) / 'validated.sqlite3'; history.initialize(staging)
    counts = {'views': 0, 'outcomes': 0}; latest = None
    with archive.open('rb') as source:
        if json.loads(source.readline(1024)) != {'schemaVersion': SCHEMA}:
            raise ValueError('history_archive_header_invalid')
        while line := source.readline(history.MAX_RECORD_BYTES + 4096):
            if not line.endswith(b'\n'): raise ValueError('history_archive_row_bound')
            row = json.loads(line)
            if set(row) != {'kind', 'value'}: raise ValueError('history_archive_row_invalid')
            if row['kind'] == 'view':
                result = history.append(staging, row['value'])
                if not result['inserted']: raise ValueError('history_archive_duplicate_view')
                counts['views'] += 1; latest = result['recordId']
            elif row['kind'] == 'outcome':
                if history.append_outcomes(staging, [_outcome(row['value'])]) != 1:
                    raise ValueError('history_archive_duplicate_outcome')
                counts['outcomes'] += 1
            else: raise ValueError('history_archive_row_kind_invalid')
    last_view = history.read_record(staging)
    latest = last_view['recordId'] if last_view else None
    if counts != manifest['counts'] or latest != manifest['latestRecordId']:
        raise ValueError('history_archive_counts_invalid')
    history.initialize(path)
    conn = history._connect(path)
    try:
        conn.execute('ATTACH DATABASE ? AS recovered', (str(staging),))
        conn.execute('BEGIN IMMEDIATE')
        for table, column in (('views', 'record_id'), ('outcomes', 'result_id')):
            # Never replace a local immutable ID with a different remote body.
            conflicts = conn.execute(f'SELECT a.body,b.body FROM main.{table} a JOIN recovered.{table} b ON a.{column}=b.{column} WHERE a.body<>b.body').fetchall()
            if table == 'views' and conflicts: raise ValueError('history_recovery_identity_conflict')
            for a,b in conflicts:
                left,right = _outcome(json.loads(a)),_outcome(json.loads(b))
                if {k:v for k,v in left.items() if k not in ('receivedAt','resultDigest')} != {k:v for k,v in right.items() if k not in ('receivedAt','resultDigest')}:
                    raise ValueError('history_recovery_outcome_conflict')
            fields = 'record_id,recorded_at,body' if table == 'views' else 'result_id,record_id,body'
            conn.execute(f'INSERT INTO main.{table}({fields}) SELECT {fields} FROM recovered.{table} WHERE {column} NOT IN (SELECT {column} FROM main.{table}) ORDER BY sequence')
        conn.execute('COMMIT')
    except Exception:
        if conn.in_transaction: conn.execute('ROLLBACK')
        raise
    finally: conn.close()
    return counts


def _immutable(remote, path, raw):
    existing, version = remote.get(path)
    if existing is not None:
        if existing != raw: raise ValueError('history_remote_immutable_conflict')
        return
    remote.put(path, raw, expected_version=version)
    verified, _ = remote.get(path)
    if verified != raw: raise ValueError('history_remote_readback_mismatch')


def _publish_chunks(remote, chunks, directory):
    """Overlap independent existence reads; keep writes and readbacks serial."""
    reader = getattr(remote, 'read_chunks', None)
    if not callable(reader):
        for chunk in chunks:
            _immutable(remote, PREFIX + '/chunks/' + chunk['sha256'] + '.bin',
                       (Path(directory) / chunk['sha256']).read_bytes())
        return
    reads = reader(chunks)
    verified_chunks = set()
    try:
        for chunk, existing in zip(chunks, reads, strict=True):
            raw = (Path(directory) / chunk['sha256']).read_bytes()
            if len(raw) != chunk['bytes'] or digest(raw) != chunk['sha256']:
                raise ValueError('history_local_chunk_changed')
            path = PREFIX + '/chunks/' + chunk['sha256'] + '.bin'
            if chunk['sha256'] in verified_chunks:
                # A prefetched miss may precede this same object's first write.
                _immutable(remote, path, raw)
                continue
            if existing is not None:
                if existing != raw: raise ValueError('history_remote_immutable_conflict')
                verified_chunks.add(chunk['sha256'])
                continue
            remote.put(path, raw, expected_version=None)
            verified, _ = remote.get(path)
            if verified != raw: raise ValueError('history_remote_readback_mismatch')
            verified_chunks.add(chunk['sha256'])
    finally:
        close = getattr(reads, 'close', None)
        if callable(close): close()


def synchronize(path, remote, *, last_verified_head=None):
    """Restore/merge before publishing; concurrent writers cannot drop each other."""
    with tempfile.TemporaryDirectory(prefix='.analysis-recovery-', dir=Path(path).parent) as directory:
        manifest, version = _head(remote)
        restored = None
        if manifest and (version != last_verified_head or not Path(path).exists()):
            restored = _restore(path, manifest, remote, directory)
        history.initialize(path)
        local = _snapshot(path, directory)
        if manifest != local:
            _publish_chunks(remote, local['chunks'], directory)
            encoded = encode(local); identity = digest(encoded)
            _immutable(remote, PREFIX + '/manifests/' + identity + '.json', encoded)
            remote.put(PREFIX + '/head.json', encode({'schemaVersion': SCHEMA, 'manifestSha256': identity}),
                       expected_version=version)
        verified, head_version = _head(remote)
        if verified != local: raise ValueError('history_head_readback_changed')
        return {'status': 'VERIFIED', 'headVersion': head_version,
                'archiveSha256': local['archiveSha256'], 'counts': local['counts'],
                'latestRecordId': local['latestRecordId'], 'restoredCounts': restored,
                'storage': 'EXISTING_PRIVATE_REPOSITORY', 'actionAuthority': False}


class GitHubStore:
    """Bounded Contents API on the already configured authenticated connection."""
    write_message = 'Save immutable public market analysis recovery'
    def __init__(self, *, repo, headers, http, monotonic=None):
        if not isinstance(repo,str) or len(repo.split('/')) != 2 or any(not p or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-' for c in p) for p in repo.split('/')):
            raise ValueError('history_remote_repository_invalid')
        self.base = 'https://api.github.com/repos/' + repo + '/contents/'
        self.blobs = 'https://api.github.com/repos/' + repo + '/git/blobs/'
        self.headers = dict(headers); self.http = http
        self.monotonic = monotonic or time.monotonic
        self.deadline = self.monotonic() + MAX_SYNC_SECONDS

    def _check_deadline(self):
        remaining = self.deadline - self.monotonic()
        if remaining <= 0: raise TimeoutError('history_remote_deadline_exceeded')
        return remaining

    def _timeout(self):
        remaining = self._check_deadline()
        return min(5, remaining / 2), min(20, remaining / 2)

    def _read_json(self, url):
        response = self.http('GET', url, headers=self.headers, timeout=self._timeout(),
                             allow_redirects=False, stream=True)
        try:
            self._check_deadline()
            if response.status_code == 404: return None
            if response.status_code != 200: raise ValueError('history_remote_read_unavailable')
            parts = []; total = 0
            for part in response.iter_content(32768):
                self._check_deadline()
                total += len(part)
                if total > 1024 * 1024: raise ValueError('history_remote_response_bound')
                parts.append(part)
            value = json.loads(b''.join(parts))
            if not isinstance(value, dict): raise ValueError('history_remote_object_invalid')
            return value
        finally: response.close()

    @staticmethod
    def _content(value):
        if value.get('encoding') != 'base64' or not isinstance(value.get('content'),str) or len(value['content']) > 900000:
            raise ValueError('history_remote_content_bound')
        return base64.b64decode(value['content'].replace('\n',''), validate=True)

    @staticmethod
    def _matches_blob(raw, sha, size):
        return (len(raw) == size and len(raw) <= CHUNK_BYTES
                and hashlib.sha1(b'blob ' + str(len(raw)).encode('ascii') + b'\0' + raw).hexdigest() == sha)

    def get(self, path):
        value = self._read_json(self.base + path)
        if value is None: return None, None
        sha, size = value.get('sha'), value.get('size')
        if not isinstance(sha,str) or not re.fullmatch('[a-f0-9]{40}',sha) or type(size) is not int or not 0 <= size <= CHUNK_BYTES:
            raise ValueError('history_remote_object_invalid')
        raw = self._content(value)
        if not self._matches_blob(raw,sha,size):
            # Re-read the exact Git object. Never trim or normalize file bytes
            # to hide a damaged Contents response; both size and identity must match.
            blob = self._read_json(self.blobs + sha)
            if blob is None or blob.get('sha') != sha or blob.get('size') != size:
                raise ValueError('history_remote_blob_integrity_invalid')
            raw = self._content(blob)
            if not self._matches_blob(raw,sha,size):
                raise ValueError('history_remote_blob_integrity_invalid')
        return raw, sha

    def read_chunks(self, chunks):
        """Prefetch four independent reads; preserve order and all byte checks.

        Keep at most four chunk bodies in flight instead of queuing the entire
        archive. Writes and the final pointer compare-and-swap stay serial.
        Every request uses this operation's existing shared deadline.
        """
        def read(chunk):
            return self.get(PREFIX + '/chunks/' + chunk['sha256'] + '.bin')[0]
        pending = deque()
        remaining = iter(chunks)
        pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix='analysis-restore-read')
        try:
            for _ in range(4):
                chunk = next(remaining, None)
                if chunk is not None: pending.append(pool.submit(read, chunk))
            while pending:
                raw = pending.popleft().result()
                yield raw
                chunk = next(remaining, None)
                if chunk is not None: pending.append(pool.submit(read, chunk))
        finally:
            for task in pending: task.cancel()
            pool.shutdown(wait=True, cancel_futures=True)

    def put(self, path, raw, *, expected_version):
        if len(raw) > CHUNK_BYTES: raise ValueError('history_remote_write_bound')
        body = {'message': self.write_message,
                'content': base64.b64encode(raw).decode('ascii')}
        if expected_version is not None: body['sha'] = expected_version
        response = self.http('PUT', self.base + path, headers=self.headers, json=body, timeout=self._timeout(), allow_redirects=False)
        try:
            self._check_deadline()
            if response.status_code not in (200,201): raise ValueError('history_remote_write_conflict_or_unavailable')
        finally: response.close()
