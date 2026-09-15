"""Lossless, append-stable transport for the existing public history database.

Original records and SQLite schemas stay unchanged. The v1 remote archive is
read before the first v2 publication and remains available; no files are deleted.
"""
from pathlib import Path
import json
import re
import tempfile
import zlib

import argus_analysis_history as history
import argus_analysis_history_backup as legacy

PREFIX = 'market-analysis/v2'
SCHEMA = 'argus-public-analysis-backup-v2'
GROUP_RECORDS = 32
MAX_GROUP_BYTES = GROUP_RECORDS * (history.MAX_RECORD_BYTES + 4096)
MAX_RAW_BYTES = 1024 * 1024 * 1024
MAX_GROUPS = 512
MAX_MANIFEST_BYTES = legacy.CHUNK_BYTES


class Remote:
    """Reuse the authenticated connection, deadline, readback and four readers."""
    def __init__(self, remote): self.remote = remote
    def _path(self, path):
        if not path.startswith(legacy.PREFIX + '/'):
            raise ValueError('compact_history_path_invalid')
        return PREFIX + path[len(legacy.PREFIX):]
    def get(self, path): return self.remote.get(self._path(path))
    def put(self, path, raw, *, expected_version):
        return self.remote.put(self._path(path), raw, expected_version=expected_version)
    def read_chunks(self, chunks):
        return legacy.GitHubStore.read_chunks(self, chunks)
    def _check_deadline(self):
        check = getattr(self.remote, '_check_deadline', None)
        if callable(check): check()


def _manifest(raw):
    if len(raw) > MAX_MANIFEST_BYTES: raise ValueError('compact_history_manifest_bound')
    value = json.loads(raw)
    if (not isinstance(value, dict) or value.get('schemaVersion') != SCHEMA
            or value.get('scope') != 'PUBLIC_MARKET' or value.get('actionAuthority') is not False
            or value.get('codec') != 'zlib' or value.get('groupRecords') != GROUP_RECORDS):
        raise ValueError('compact_history_manifest_invalid')
    groups = value.get('groups')
    if not isinstance(groups, list) or len(groups) > MAX_GROUPS:
        raise ValueError('compact_history_group_bound')
    counts = {'views': 0, 'outcomes': 0}; raw_bytes = 0; stored_bytes = 0
    past_views = False
    for group in groups:
        kind = group.get('kind') if isinstance(group, dict) else None
        if kind not in counts or (past_views and kind == 'views'):
            raise ValueError('compact_history_group_order')
        past_views |= kind == 'outcomes'
        if (type(group.get('count')) is not int or not 1 <= group['count'] <= GROUP_RECORDS
                or type(group.get('rawBytes')) is not int or not 1 <= group['rawBytes'] <= MAX_GROUP_BYTES
                or not legacy.valid_digest(group.get('rawSha256'))):
            raise ValueError('compact_history_group_invalid')
        chunks = group.get('chunks')
        if not isinstance(chunks, list) or not 1 <= len(chunks) <= MAX_GROUP_BYTES // legacy.CHUNK_BYTES + 2:
            raise ValueError('compact_history_chunk_bound')
        for chunk in chunks:
            if (not isinstance(chunk, dict) or not legacy.valid_digest(chunk.get('sha256'))
                    or type(chunk.get('bytes')) is not int or not 1 <= chunk['bytes'] <= legacy.CHUNK_BYTES):
                raise ValueError('compact_history_chunk_invalid')
            stored_bytes += chunk['bytes']
        raw_bytes += group['rawBytes']; counts[kind] += group['count']
    if (raw_bytes != value.get('rawBytes') or stored_bytes != value.get('storedBytes')
            or counts != value.get('counts') or raw_bytes > MAX_RAW_BYTES
            or stored_bytes > legacy.MAX_ARCHIVE_BYTES):
        raise ValueError('compact_history_total_bound')
    latest = value.get('latestRecordId')
    if (counts['views'] and not legacy.valid_digest(latest)) or (not counts['views'] and latest is not None):
        raise ValueError('compact_history_latest_invalid')
    legacy_head = value.get('legacyHeadVersion')
    if legacy_head is not None and not re.fullmatch(r'(?:[a-f0-9]{40}|[a-f0-9]{64})', str(legacy_head)):
        raise ValueError('compact_history_legacy_head_invalid')
    return value


def _head(remote):
    raw, version = remote.get(legacy.PREFIX + '/head.json')
    if raw is None:
        if version is not None: raise ValueError('compact_history_missing_head_version')
        return None, None
    if len(raw) > 1024: raise ValueError('compact_history_head_bound')
    head = json.loads(raw)
    if (set(head) != {'schemaVersion', 'manifestSha256'} or head['schemaVersion'] != SCHEMA
            or not legacy.valid_digest(head['manifestSha256'])):
        raise ValueError('compact_history_head_invalid')
    raw, _ = remote.get(legacy.PREFIX + '/manifests/' + head['manifestSha256'] + '.json')
    if raw is None or legacy.digest(raw) != head['manifestSha256']:
        raise ValueError('compact_history_manifest_digest')
    return _manifest(raw), version


def _snapshot(path, directory, *, check_deadline=lambda: None):
    """Stable groups per table keep completed groups unchanged on append."""
    import hashlib
    groups = []; counts = {'views': 0, 'outcomes': 0}; raw_total = stored_total = 0
    conn = history._connect(path, True)
    try:
        conn.execute('BEGIN')
        for table, validator in (('views', history.validate_record), ('outcomes', legacy._outcome)):
            cursor = conn.execute(f'SELECT body FROM {table} ORDER BY sequence')
            while rows := cursor.fetchmany(GROUP_RECORDS):
                check_deadline()
                packed_path = Path(directory) / 'group.zlib'
                compressor = zlib.compressobj(6); checksum = hashlib.sha256(); size = 0
                with packed_path.open('wb') as output:
                    for (body,) in rows:
                        check_deadline()
                        if len(body.encode()) > history.MAX_RECORD_BYTES + 4096:
                            raise ValueError('compact_history_record_bound')
                        raw = legacy.encode(validator(json.loads(body))) + b'\n'
                        checksum.update(raw); size += len(raw)
                        output.write(compressor.compress(raw))
                    output.write(compressor.flush())
                chunks = []
                with packed_path.open('rb') as source:
                    while raw := source.read(legacy.CHUNK_BYTES):
                        identity = legacy.digest(raw)
                        (Path(directory) / identity).write_bytes(raw)
                        chunks.append({'sha256': identity, 'bytes': len(raw)})
                        stored_total += len(raw)
                raw_total += size; counts[table] += len(rows)
                groups.append({'kind': table, 'count': len(rows), 'rawBytes': size,
                    'rawSha256': checksum.hexdigest(), 'chunks': chunks})
                if (len(groups) > MAX_GROUPS or raw_total > MAX_RAW_BYTES
                        or stored_total > legacy.MAX_ARCHIVE_BYTES):
                    raise ValueError('compact_history_total_bound')
        row = conn.execute('SELECT record_id FROM views ORDER BY julianday(recorded_at) DESC,sequence DESC LIMIT 1').fetchone()
        conn.execute('COMMIT')
    finally: conn.close()
    body = {'schemaVersion': SCHEMA, 'scope': 'PUBLIC_MARKET', 'actionAuthority': False,
        'codec': 'zlib', 'groupRecords': GROUP_RECORDS, 'groups': groups,
        'rawBytes': raw_total, 'storedBytes': stored_total, 'counts': counts,
        'latestRecordId': row[0] if row else None, 'legacyHeadVersion': None}
    return _manifest(legacy.encode(body))


def _restore(path, manifest, remote, directory):
    """Validate every compressed group and original record before live merge."""
    import hashlib
    staging = Path(directory) / 'compact-validated.sqlite3'; history.initialize(staging)
    counts = {'views': 0, 'outcomes': 0}
    for group in manifest['groups']:
        remote._check_deadline()
        expanded = Path(directory) / 'group.ndjson'
        decoder = zlib.decompressobj(); checksum = hashlib.sha256(); size = 0
        reads = remote.read_chunks(group['chunks'])
        try:
            with expanded.open('wb') as output:
                for chunk, raw in zip(group['chunks'], reads, strict=True):
                    if raw is None or len(raw) != chunk['bytes'] or legacy.digest(raw) != chunk['sha256']:
                        raise ValueError('compact_history_chunk_integrity')
                    # max_length also bounds an attacker-controlled compression ratio.
                    decoded = decoder.decompress(raw, group['rawBytes'] - size + 1)
                    size += len(decoded)
                    if size > group['rawBytes'] or decoder.unconsumed_tail:
                        raise ValueError('compact_history_expansion_bound')
                    checksum.update(decoded); output.write(decoded)
                if (not decoder.eof or decoder.unused_data or size != group['rawBytes']
                        or checksum.hexdigest() != group['rawSha256']):
                    raise ValueError('compact_history_group_integrity')
        finally: reads.close()
        count = 0
        with expanded.open('rb') as source:
            while raw := source.readline(history.MAX_RECORD_BYTES + 4096):
                remote._check_deadline()
                if not raw.endswith(b'\n'): raise ValueError('compact_history_record_bound')
                value = json.loads(raw)
                if legacy.encode(value) + b'\n' != raw: raise ValueError('compact_history_record_encoding')
                if group['kind'] == 'views':
                    if not history.append(staging, value)['inserted']:
                        raise ValueError('compact_history_duplicate_view')
                elif history.append_outcomes(staging, [legacy._outcome(value)]) != 1:
                    raise ValueError('compact_history_duplicate_outcome')
                count += 1
        if count != group['count']: raise ValueError('compact_history_group_count')
        counts[group['kind']] += count
    latest = history.read_record(staging)
    if (counts != manifest['counts'] or (latest['recordId'] if latest else None) != manifest['latestRecordId']):
        raise ValueError('compact_history_counts_invalid')
    remote._check_deadline()
    legacy._merge_validated(path, staging)
    return counts


def synchronize(path, connection, *, last_verified_head=None):
    remote = Remote(connection)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.analysis-compact-', dir=Path(path).parent) as directory:
        manifest, version = _head(remote); restored = None; migrated = False
        if manifest is not None and (version != last_verified_head or not Path(path).exists()):
            restored = _restore(path, manifest, remote, directory)
        # During compatibility, a late v1 writer remains visible. No v1 files or
        # pointer are replaced, and new v2 records are never lost on re-import.
        old, old_version = legacy._head(connection)
        if old and (manifest is None or manifest.get('legacyHeadVersion') != old_version):
            old_counts = legacy._restore(path, old, connection, directory)
            restored = restored or old_counts
            migrated = True
        history.initialize(path)
        local = _snapshot(path, directory, check_deadline=remote._check_deadline)
        local['legacyHeadVersion'] = old_version
        if local != manifest:
            chunks = [chunk for group in local['groups'] for chunk in group['chunks']]
            legacy._publish_chunks(remote, chunks, directory)
            raw = legacy.encode(local); identity = legacy.digest(raw)
            legacy._immutable(remote, legacy.PREFIX + '/manifests/' + identity + '.json', raw)
            if connection.get(legacy.PREFIX + '/head.json')[1] != old_version:
                raise ValueError('compact_history_legacy_writer_changed')
            remote.put(legacy.PREFIX + '/head.json', legacy.encode({'schemaVersion': SCHEMA,
                'manifestSha256': identity}), expected_version=version)
        verified, head = _head(remote)
        if verified != local: raise ValueError('compact_history_head_readback_changed')
        if connection.get(legacy.PREFIX + '/head.json')[1] != old_version:
            raise ValueError('compact_history_legacy_writer_changed')
        return {'status': 'VERIFIED', 'headVersion': head, 'formatVersion': 2,
            'archiveSha256': legacy.digest(legacy.encode(local)), 'counts': local['counts'],
            'latestRecordId': local['latestRecordId'], 'restoredCounts': restored,
            'storedBytes': local['storedBytes'], 'originalBytes': local['rawBytes'],
            'migratedFromV1': migrated, 'storage': 'EXISTING_PRIVATE_REPOSITORY',
            'actionAuthority': False}
