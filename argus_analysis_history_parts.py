"""Remote analysis history v3: skeletons and content-addressed parts (2026-10-20).

The v2 transport re-uploaded its last group on every synchronisation and kept
every edition whole, although most of an edition repeats the one before it
(measured on the latest 32 editions: 960 KB each, 171 KB compressed; with
parts kept once, 233 KB and 48 KB). Its compressed bound (128 MiB) would have
stopped the private backup in mid-November 2026.

Records, their identities and their validation are unchanged. Only the remote
form differs: each edition is split into a skeleton and parts (the large
top-level values of the brief, of its unified context and of each horizon's
calculations). A part's identity is the hash of its canonical body; the
volatile timestamp keys of a part stay in the skeleton, so a part whose only
change is a read time is still kept once. New parts and skeletons are written
as append-only compressed packs; a pack is never rewritten. Restore rebuilds
every edition from its parts and accepts it only when the rebuilt record has
its original identity.

The private repository is the existing one; nothing here reads owner data.
"""
from concurrent.futures import ThreadPoolExecutor
from collections import deque
import copy
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import zlib

import argus_analysis_history as history
import argus_analysis_history_backup as legacy

PREFIX = 'market-analysis/v3'
SCHEMA = 'argus-public-analysis-backup-v3'
SEGMENT_SCHEMA = 'argus-public-analysis-backup-v3-segment'
SIDECAR_SCHEMA = 'argus-public-analysis-backup-v3-local-index'
PACK_BYTES = legacy.CHUNK_BYTES            # one remote object, as v1/v2 chunks
PACK_RAW_TARGET = 2 * 1024 * 1024
PACK_RAW_BYTES = 16 * 1024 * 1024          # expansion bound of one pack
PART_MIN_BYTES = 2048
VOLATILE_KEYS = frozenset({'informationCutoff', 'createdAt', 'lastAttemptAt', 'asOf',
                           'generatedAt', 'composedAt', 'measuredAt', 'checkedAt'})
MAX_STORED_BYTES = 512 * 1024 * 1024
MAX_RAW_BYTES = 4 * 1024 * 1024 * 1024
WARNING_SHARE = 0.7
#: GitHub's recommended maximum on-disk repository size (docs, 2026-10-20).
REPOSITORY_RECOMMENDED_BYTES = 10 * 1024 * 1024 * 1024
SEGMENT_PACKS = 1000
MAX_PACKS_PER_SYNC = 24
#: One call reads at most this many editions (about 1 MB each) for a first migration.
MAX_VIEWS_PER_SYNC = 48
MAX_MANIFEST_BYTES = legacy.CHUNK_BYTES


def _encode(value):
    return legacy.encode(value)


def _digest(raw):
    return legacy.digest(raw)


def _placeholder(value):
    return (isinstance(value, dict) and '$part' in value and set(value) <= {'$part', '$volatile'}
            and legacy.valid_digest(value['$part'])
            and isinstance(value.get('$volatile', {}), dict))


def _containers(record):
    brief = record.get('brief')
    if isinstance(brief, dict):
        yield brief, frozenset({'unifiedContext'})
        if isinstance(brief.get('unifiedContext'), dict):
            yield brief['unifiedContext'], frozenset()
    calculations = record.get('calculations')
    if isinstance(calculations, dict):
        for key in sorted(calculations):
            if isinstance(calculations[key], dict):
                yield calculations[key], frozenset()


def split(record):
    """(skeleton, {partId: canonical bytes}) for one validated record."""
    skeleton = copy.deepcopy(record)
    parts = {}
    for container, keep in _containers(skeleton):
        for key in sorted(container):
            value = container[key]
            if key in keep or _placeholder(value):
                if _placeholder(value):
                    raise ValueError('history_v3_reserved_placeholder')
                continue
            if len(_encode(value)) < PART_MIN_BYTES:
                continue
            volatile = {}
            if isinstance(value, dict):
                volatile = {k: value[k] for k in value if k in VOLATILE_KEYS}
                value = {k: value[k] for k in value if k not in VOLATILE_KEYS}
            raw = _encode(value)
            identity = _digest(raw)
            parts[identity] = raw
            container[key] = {'$part': identity, **({'$volatile': volatile} if volatile else {})}
    return skeleton, parts


def assemble(skeleton, part_body):
    """Rebuild one record; it must validate and keep its original identity."""
    record = copy.deepcopy(skeleton)
    for container, _ in _containers(record):
        for key in list(container):
            value = container[key]
            if not _placeholder(value):
                continue
            body = part_body(value['$part'])
            volatile = value.get('$volatile') or {}
            if volatile:
                if not isinstance(body, dict) or set(body) & set(volatile) or not set(volatile) <= VOLATILE_KEYS:
                    raise ValueError('history_v3_volatile_invalid')
                body = {**body, **volatile}
            container[key] = body
    rebuilt = history.validate_record(record)
    if rebuilt['recordId'] != skeleton.get('recordId') or rebuilt != record:
        raise ValueError('history_v3_record_identity_mismatch')
    return rebuilt


# ── packs ──────────────────────────────────────────────────────────────────
def _pack_bytes(lines):
    raw = b''.join(lines)
    return raw, zlib.compress(raw, 6)


def build_packs(lines):
    """Compressed packs of at most PACK_BYTES each, in line order."""
    packs, batch, size = [], [], 0

    def emit(group):
        raw, packed = _pack_bytes(group)
        if len(packed) > PACK_BYTES:
            if len(group) == 1:
                raise ValueError('history_v3_entry_bound')
            middle = len(group) // 2
            emit(group[:middle]); emit(group[middle:])
            return
        packs.append({'raw': raw, 'packed': packed})

    for line in lines:
        batch.append(line); size += len(line)
        if size >= PACK_RAW_TARGET:
            emit(batch); batch, size = [], 0
    if batch:
        emit(batch)
    return packs


def read_pack(raw_packed, entry):
    """Verified lines of one pack."""
    if raw_packed is None or len(raw_packed) != entry['bytes'] or _digest(raw_packed) != entry['sha256']:
        raise ValueError('history_v3_pack_integrity')
    decoder = zlib.decompressobj()
    raw = decoder.decompress(raw_packed, entry['rawBytes'] + 1)
    if (len(raw) != entry['rawBytes'] or decoder.unconsumed_tail or not decoder.eof
            or decoder.unused_data or _digest(raw) != entry['rawSha256']):
        raise ValueError('history_v3_pack_expansion')
    lines = raw.split(b'\n')
    if lines[-1] != b'':
        raise ValueError('history_v3_pack_line')
    out = []
    for line in lines[:-1]:
        value = json.loads(line)
        if _encode(value) != line or not isinstance(value, dict):
            raise ValueError('history_v3_pack_encoding')
        out.append(value)
    return out


def _entry_counts(values):
    counts = {'views': 0, 'outcomes': 0, 'parts': 0}
    for value in values:
        kind = value.get('kind')
        if kind == 'view': counts['views'] += 1
        elif kind == 'outcome': counts['outcomes'] += 1
        elif kind == 'part': counts['parts'] += 1
        else: raise ValueError('history_v3_entry_kind')
    return counts


# ── manifest ───────────────────────────────────────────────────────────────
def _valid_pack_entry(entry):
    return (isinstance(entry, dict) and legacy.valid_digest(entry.get('sha256'))
            and legacy.valid_digest(entry.get('rawSha256'))
            and type(entry.get('bytes')) is int and 1 <= entry['bytes'] <= PACK_BYTES
            and type(entry.get('rawBytes')) is int and 1 <= entry['rawBytes'] <= PACK_RAW_BYTES
            and all(type(entry.get(k)) is int and entry[k] >= 0 for k in ('views', 'outcomes', 'parts')))


def manifest_from(raw):
    if raw is None or len(raw) > MAX_MANIFEST_BYTES:
        raise ValueError('history_v3_manifest_bound')
    value = json.loads(raw)
    if (not isinstance(value, dict) or value.get('schemaVersion') != SCHEMA
            or value.get('scope') != 'PUBLIC_MARKET' or value.get('actionAuthority') is not False
            or value.get('codec') != 'zlib'):
        raise ValueError('history_v3_manifest_invalid')
    if not isinstance(value.get('segments'), list) or not isinstance(value.get('packs'), list) \
            or len(value['packs']) > SEGMENT_PACKS or not all(_valid_pack_entry(p) for p in value['packs']):
        raise ValueError('history_v3_manifest_packs')
    for segment in value['segments']:
        if (not isinstance(segment, dict) or not legacy.valid_digest(segment.get('sha256'))
                or type(segment.get('packs')) is not int or not 1 <= segment['packs'] <= SEGMENT_PACKS
                or type(segment.get('storedBytes')) is not int or type(segment.get('rawBytes')) is not int):
            raise ValueError('history_v3_manifest_segment')
    stored = sum(s['storedBytes'] for s in value['segments']) + sum(p['bytes'] for p in value['packs'])
    raw_total = sum(s['rawBytes'] for s in value['segments']) + sum(p['rawBytes'] for p in value['packs'])
    if stored != value.get('storedBytes') or raw_total != value.get('rawBytes') \
            or stored > MAX_STORED_BYTES or raw_total > MAX_RAW_BYTES:
        raise ValueError('history_v3_manifest_totals')
    counts = value.get('counts')
    if not isinstance(counts, dict) or set(counts) != {'views', 'outcomes', 'parts'} \
            or not all(type(v) is int and v >= 0 for v in counts.values()):
        raise ValueError('history_v3_manifest_counts')
    latest = value.get('latestRecordId')
    if (counts['views'] and not legacy.valid_digest(latest)) or (not counts['views'] and latest is not None):
        raise ValueError('history_v3_manifest_latest')
    return value


def _head(remote):
    raw, version = remote.get(PREFIX + '/head.json')
    if raw is None:
        if version is not None: raise ValueError('history_v3_head_version')
        return None, None, None
    if len(raw) > 1024: raise ValueError('history_v3_head_bound')
    head = json.loads(raw)
    if set(head) != {'schemaVersion', 'manifestSha256'} or head['schemaVersion'] != SCHEMA \
            or not legacy.valid_digest(head['manifestSha256']):
        raise ValueError('history_v3_head_invalid')
    raw, _ = remote.get(PREFIX + '/manifests/' + head['manifestSha256'] + '.json')
    if raw is None or _digest(raw) != head['manifestSha256']:
        raise ValueError('history_v3_manifest_digest')
    return manifest_from(raw), version, head['manifestSha256']


def _segment(remote, entry):
    raw, _ = remote.get(PREFIX + '/segments/' + entry['sha256'] + '.json')
    if raw is None or _digest(raw) != entry['sha256'] or len(raw) > MAX_MANIFEST_BYTES:
        raise ValueError('history_v3_segment_integrity')
    value = json.loads(raw)
    if (not isinstance(value, dict) or value.get('schemaVersion') != SEGMENT_SCHEMA
            or not isinstance(value.get('packs'), list) or len(value['packs']) != entry['packs']
            or not all(_valid_pack_entry(p) for p in value['packs'])
            or sum(p['bytes'] for p in value['packs']) != entry['storedBytes']
            or sum(p['rawBytes'] for p in value['packs']) != entry['rawBytes']):
        raise ValueError('history_v3_segment_invalid')
    return value['packs']


def _all_packs(remote, manifest):
    packs = []
    for entry in manifest['segments']:
        packs.extend(_segment(remote, entry))
    return packs + list(manifest['packs'])


def _read_packs(remote, packs):
    """Verified entries of each pack, in order, with four reads in flight."""
    def read(entry):
        return remote.get(PREFIX + '/packs/' + entry['sha256'] + '.bin')[0]
    pending, remaining = deque(), iter(packs)
    pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix='analysis-v3-read')
    try:
        for _ in range(4):
            entry = next(remaining, None)
            if entry is not None: pending.append((entry, pool.submit(read, entry)))
        while pending:
            entry, task = pending.popleft()
            values = read_pack(task.result(), entry)
            if _entry_counts(values) != {k: entry[k] for k in ('views', 'outcomes', 'parts')}:
                raise ValueError('history_v3_pack_counts')
            yield values
            nxt = next(remaining, None)
            if nxt is not None: pending.append((nxt, pool.submit(read, nxt)))
    finally:
        for _, task in pending: task.cancel()
        pool.shutdown(wait=True, cancel_futures=True)


# ── local index (sidecar) ──────────────────────────────────────────────────
def _sidecar_path(path):
    return str(path) + '.v3-index.json'


def _sidecar_load(path, manifest_sha):
    location = _sidecar_path(path)
    try:
        if not os.path.isfile(path) or os.path.islink(location):
            return None
        with open(location, 'rb') as handle:
            value = json.loads(handle.read(64 * 1024 * 1024))
        if (not isinstance(value, dict) or value.get('schemaVersion') != SIDECAR_SCHEMA
                or value.get('manifestSha256') != manifest_sha):
            return None
        return {k: set(value[k]) for k in ('views', 'outcomes', 'parts')}
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _sidecar_save(path, manifest_sha, index):
    location = Path(_sidecar_path(path))
    body = json.dumps({'schemaVersion': SIDECAR_SCHEMA, 'manifestSha256': manifest_sha,
                       **{k: sorted(index[k]) for k in ('views', 'outcomes', 'parts')}},
                      separators=(',', ':')).encode()
    fd, temporary = tempfile.mkstemp(prefix='.analysis-v3-index-', dir=location.parent)
    try:
        with os.fdopen(fd, 'wb') as handle:
            handle.write(body); handle.flush(); os.fsync(handle.fileno())
        os.replace(temporary, location)
    except Exception:
        try: os.unlink(temporary)
        except OSError: pass
        raise


# ── restore ────────────────────────────────────────────────────────────────
def scan(path, remote, manifest, directory, *, restore):
    """The remote ids, and (restore=True) every remote record merged into the
    local file after each one rebuilt with its original identity."""
    index = {'views': set(), 'outcomes': set(), 'parts': set()}
    work = Path(tempfile.mkdtemp(prefix='scan-', dir=directory))
    staging = work / 'validated.sqlite3'
    partdb = sqlite3.connect(work / 'parts.sqlite3', isolation_level=None)
    partdb.execute('CREATE TABLE parts(id TEXT PRIMARY KEY, body BLOB NOT NULL)')
    pending_outcomes = []
    latest = None
    if restore:
        history.initialize(staging)
    try:
        def body_of(identity):
            row = partdb.execute('SELECT body FROM parts WHERE id=?', (identity,)).fetchone()
            if row is None: raise ValueError('history_v3_part_missing')
            return json.loads(row[0])
        for values in _read_packs(remote, _all_packs(remote, manifest)):
            remote._check_deadline()
            for value in values:
                kind = value['kind']
                if kind == 'part':
                    raw = _encode(value.get('body'))
                    if _digest(raw) != value.get('partId'): raise ValueError('history_v3_part_identity')
                    if restore:
                        partdb.execute('INSERT OR IGNORE INTO parts VALUES(?,?)', (value['partId'], raw))
                    index['parts'].add(value['partId'])
                elif kind == 'view':
                    skeleton = value.get('skeleton')
                    if not isinstance(skeleton, dict) or skeleton.get('recordId') != value.get('recordId'):
                        raise ValueError('history_v3_view_invalid')
                    for container, _ in _containers(skeleton):
                        for item in container.values():
                            if _placeholder(item) and item['$part'] not in index['parts']:
                                raise ValueError('history_v3_part_missing')
                    if restore:
                        if not history.append(staging, assemble(skeleton, body_of))['inserted']:
                            raise ValueError('history_v3_duplicate_view')
                    if value['recordId'] in index['views']: raise ValueError('history_v3_duplicate_view')
                    index['views'].add(value['recordId']); latest = value['recordId']
                else:
                    outcome = legacy._outcome(value.get('value'))
                    if outcome['resultId'] in index['outcomes']: raise ValueError('history_v3_duplicate_outcome')
                    index['outcomes'].add(outcome['resultId'])
                    if restore: pending_outcomes.append(outcome)
        if restore:
            for start in range(0, len(pending_outcomes), 400):
                if history.append_outcomes(staging, pending_outcomes[start:start + 400]) != len(pending_outcomes[start:start + 400]):
                    raise ValueError('history_v3_duplicate_outcome')
    finally:
        partdb.close()
    counts = {k: len(v) for k, v in index.items()}
    if counts != manifest['counts'] or latest != manifest['latestRecordId']:
        raise ValueError('history_v3_counts_invalid')
    if restore:
        legacy._merge_validated(path, staging)
    return index


def _local_ids(path):
    conn = history._connect(path, True)
    try:
        views = [r[0] for r in conn.execute('SELECT record_id FROM views ORDER BY sequence')]
        outcomes = [r[0] for r in conn.execute('SELECT result_id FROM outcomes ORDER BY sequence')]
        return views, outcomes
    finally: conn.close()


def _local_bodies(path, table, column, ids):
    conn = history._connect(path, True)
    try:
        for identity in ids:
            row = conn.execute(f'SELECT body FROM {table} WHERE {column}=?', (identity,)).fetchone()
            if row is None: raise ValueError('history_v3_local_row_missing')
            yield json.loads(row[0])
    finally: conn.close()


# ── publish ────────────────────────────────────────────────────────────────
def _lines_for(path, new_views, new_outcomes, seen_parts):
    lines, added_parts = [], set()
    for record in _local_bodies(path, 'views', 'record_id', new_views):
        record = history.validate_record(record)
        skeleton, parts = split(record)
        for identity, raw in parts.items():
            if identity in seen_parts or identity in added_parts:
                continue
            lines.append(_encode({'kind': 'part', 'partId': identity, 'body': json.loads(raw)}) + b'\n')
            added_parts.add(identity)
        lines.append(_encode({'kind': 'view', 'recordId': record['recordId'], 'skeleton': skeleton}) + b'\n')
    for outcome in _local_bodies(path, 'outcomes', 'result_id', new_outcomes):
        lines.append(_encode({'kind': 'outcome', 'value': legacy._outcome(outcome)}) + b'\n')
    return lines


def capacity(manifest, repository_bytes=None):
    stored = manifest['storedBytes'] if manifest else 0
    raw = manifest['rawBytes'] if manifest else 0
    share = max(stored / MAX_STORED_BYTES, raw / MAX_RAW_BYTES)
    repo_share = (repository_bytes / REPOSITORY_RECOMMENDED_BYTES) if isinstance(repository_bytes, int) else None
    return {'storedBytes': stored, 'storedLimitBytes': MAX_STORED_BYTES, 'originalBytes': raw,
            'originalLimitBytes': MAX_RAW_BYTES, 'share': round(share, 4),
            'warning': share >= WARNING_SHARE,
            'repositoryBytes': repository_bytes, 'repositoryRecommendedBytes': REPOSITORY_RECOMMENDED_BYTES,
            'repositoryShare': round(repo_share, 4) if repo_share is not None else None,
            'repositoryWarning': bool(repo_share is not None and repo_share >= WARNING_SHARE)}


def synchronize(path, remote, *, max_packs=MAX_PACKS_PER_SYNC, max_views=MAX_VIEWS_PER_SYNC,
                repository_bytes=None):
    """Restore what the local file lacks, then append new records as new packs.

    `complete` is True when, after this call, the remote holds every local
    record; a long first migration takes several calls of at most `max_packs`.
    """
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.analysis-v3-', dir=Path(path).parent) as directory:
        manifest, version, manifest_sha = _head(remote)
        restored = None
        index = {'views': set(), 'outcomes': set(), 'parts': set()}
        if manifest is not None:
            index = _sidecar_load(path, manifest_sha) if Path(path).exists() else None
            local_views, local_outcomes = (_local_ids(path) if Path(path).exists() else ([], []))
            if index is None or not (index['views'] <= set(local_views) and index['outcomes'] <= set(local_outcomes)):
                index = scan(path, remote, manifest, directory, restore=False)
                if not (index['views'] <= set(local_views) and index['outcomes'] <= set(local_outcomes)):
                    index = scan(path, remote, manifest, directory, restore=True)
                    restored = {k: len(index[k]) for k in ('views', 'outcomes')}
                _sidecar_save(path, manifest_sha, index)
        history.initialize(path)
        local_views, local_outcomes = _local_ids(path)
        new_views = [i for i in local_views if i not in index['views']]
        new_outcomes = [i for i in local_outcomes if i not in index['outcomes']]
        written = {'packs': 0, 'views': 0, 'outcomes': 0}
        if new_views or new_outcomes:
            # Bound one call: the views are taken in local order, a batch at a time.
            batch_views = new_views[:max(1, max_views)]
            batch_outcomes = new_outcomes if len(batch_views) == len(new_views) else []
            lines = _lines_for(path, batch_views, batch_outcomes, index['parts'])
            packs = build_packs(lines)[:max_packs]
            published_lines = sum(len(p['raw'].split(b'\n')) - 1 for p in packs)
            lines = lines[:published_lines]
            entries = []
            for pack in packs:
                values = [json.loads(line) for line in pack['raw'].split(b'\n')[:-1]]
                entry = {'sha256': _digest(pack['packed']), 'bytes': len(pack['packed']),
                         'rawBytes': len(pack['raw']), 'rawSha256': _digest(pack['raw']), **_entry_counts(values)}
                legacy._immutable(remote, PREFIX + '/packs/' + entry['sha256'] + '.bin', pack['packed'])
                entries.append(entry)
                for value in values:
                    if value['kind'] == 'part': index['parts'].add(value['partId'])
                    elif value['kind'] == 'view': index['views'].add(value['recordId']); written['views'] += 1
                    else: index['outcomes'].add(value['value']['resultId']); written['outcomes'] += 1
            written['packs'] = len(entries)
            base = manifest or {'schemaVersion': SCHEMA, 'scope': 'PUBLIC_MARKET', 'actionAuthority': False,
                                'codec': 'zlib', 'segments': [], 'packs': [],
                                'counts': {'views': 0, 'outcomes': 0, 'parts': 0},
                                'storedBytes': 0, 'rawBytes': 0, 'latestRecordId': None}
            segments, tail = list(base['segments']), list(base['packs']) + entries
            while len(tail) > SEGMENT_PACKS:
                sealed, tail = tail[:SEGMENT_PACKS], tail[SEGMENT_PACKS:]
                raw = _encode({'schemaVersion': SEGMENT_SCHEMA, 'packs': sealed})
                identity = _digest(raw)
                legacy._immutable(remote, PREFIX + '/segments/' + identity + '.json', raw)
                segments.append({'sha256': identity, 'packs': len(sealed),
                                 'storedBytes': sum(p['bytes'] for p in sealed),
                                 'rawBytes': sum(p['rawBytes'] for p in sealed)})
            latest = base['latestRecordId']
            for value in (json.loads(line) for line in lines):
                if value['kind'] == 'view': latest = value['recordId']
            body = {'schemaVersion': SCHEMA, 'scope': 'PUBLIC_MARKET', 'actionAuthority': False, 'codec': 'zlib',
                    'segments': segments, 'packs': tail,
                    'counts': {k: len(index[k]) for k in ('views', 'outcomes', 'parts')},
                    'storedBytes': sum(s['storedBytes'] for s in segments) + sum(p['bytes'] for p in tail),
                    'rawBytes': sum(s['rawBytes'] for s in segments) + sum(p['rawBytes'] for p in tail),
                    'latestRecordId': latest}
            raw = _encode(body)
            manifest = manifest_from(raw)
            manifest_sha = _digest(raw)
            legacy._immutable(remote, PREFIX + '/manifests/' + manifest_sha + '.json', raw)
            remote.put(PREFIX + '/head.json', _encode({'schemaVersion': SCHEMA, 'manifestSha256': manifest_sha}),
                       expected_version=version)
            verified, version, verified_sha = _head(remote)
            if verified_sha != manifest_sha:
                raise ValueError('history_v3_head_readback_changed')
            _sidecar_save(path, manifest_sha, index)
        complete = all(i in index['views'] for i in local_views) and all(i in index['outcomes'] for i in local_outcomes)
        return {'status': 'VERIFIED', 'formatVersion': 3, 'headVersion': version,
                'manifestSha256': manifest_sha, 'complete': complete,
                'counts': manifest['counts'] if manifest else {'views': 0, 'outcomes': 0, 'parts': 0},
                'latestRecordId': manifest['latestRecordId'] if manifest else None,
                'written': written, 'restoredCounts': restored,
                'capacity': capacity(manifest, repository_bytes),
                'storage': 'EXISTING_PRIVATE_REPOSITORY', 'actionAuthority': False}
