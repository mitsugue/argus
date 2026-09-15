"""Transport acceptance: original records, failure atomicity and append stability."""
import copy
import json
from pathlib import Path

import pytest

import argus_analysis_history as history
import argus_analysis_history_backup as backup
import argus_analysis_history_compact as compact
import test_argus_analysis_history_backup as original


@pytest.mark.parametrize('case', [
    'test_cold_restore_keeps_original_inputs_and_merges_local_newer_views',
    'test_remote_failure_cannot_be_treated_as_empty_or_rewrite_pointer',
    'test_corrupt_snapshot_is_rejected_before_mutating_local_history',
    'test_concurrent_pointer_change_fails_without_overwriting_remote_writer',
    'test_later_results_and_corrections_survive_remote_restore',
])
def test_existing_history_contract_on_compact_transport(tmp_path, monkeypatch, case):
    monkeypatch.setattr(original.Remote, 'history_format_version', 2, raising=False)
    getattr(original, case)(tmp_path)


def test_v1_migration_keeps_original_archive_and_cold_restores(tmp_path):
    remote = original.Remote(); source = tmp_path/'source.sqlite'
    old = original.add(source, '2026-09-12T00:00:00Z', 3000)
    backup.synchronize_v1(source, remote)
    originals = copy.deepcopy(remote.files)
    target = tmp_path/'target.sqlite'
    newer = original.add(target, '2026-09-13T00:00:00Z', 3100)
    remote.history_format_version = 2
    result = backup.synchronize(target, remote)
    assert result['migratedFromV1'] and result['counts']['views'] == 2
    assert all(remote.files[path] == raw for path, raw in originals.items())
    cold = tmp_path/'cold.sqlite'; backup.synchronize(cold, remote)
    assert history.read_record(cold, old['recordId']) == old
    assert history.read_record(cold, newer['recordId']) == newer


def test_late_v1_writer_is_merged_without_losing_v2_records(tmp_path):
    remote = original.Remote(); old = tmp_path/'old.sqlite'; new = tmp_path/'new.sqlite'
    one = original.add(old, '2026-09-12T00:00:00Z', 3000)
    backup.synchronize_v1(old, remote)
    two = original.add(new, '2026-09-13T00:00:00Z', 3100)
    remote.history_format_version = 2
    first = backup.synchronize(new, remote)
    three = original.add(old, '2026-09-14T00:00:00Z', 3200)
    backup.synchronize_v1(old, remote)
    result = backup.synchronize(new, remote, last_verified_head=first['headVersion'])
    assert result['migratedFromV1'] and result['counts']['views'] == 3
    for row in (one, two, three): assert history.read_record(new, row['recordId']) == row


def test_v1_writer_during_v2_head_commit_is_not_reported_verified(tmp_path):
    remote = original.Remote(); old = tmp_path/'old.sqlite'; new = tmp_path/'new.sqlite'
    original.add(old, '2026-09-12T00:00:00Z', 3000); backup.synchronize_v1(old, remote)
    original.add(new, '2026-09-13T00:00:00Z', 3100); remote.history_format_version = 2
    def late():
        original.add(old, '2026-09-14T00:00:00Z', 3200)
        backup.synchronize_v1(old, remote)
    remote.before_head = late
    with pytest.raises(ValueError, match='legacy_writer_changed'): backup.synchronize(new, remote)
    assert backup.synchronize(new, remote)['counts']['views'] == 3


def test_completed_groups_reused_on_append_and_original_bytes_preserved(tmp_path):
    remote = original.Remote(); remote.history_format_version = 2
    source = tmp_path/'source.sqlite'
    from datetime import datetime, timedelta, timezone
    base = datetime(2026, 8, 1, tzinfo=timezone.utc)
    for n in range(34): original.add(source, (base+timedelta(days=n)).isoformat(), 3000+n)
    first = backup.synchronize(source, remote)
    manifest, _ = compact._head(compact.Remote(remote))
    complete = manifest['groups'][0]
    before = len(remote.puts)
    original.add(source, (base+timedelta(days=34)).isoformat(), 3034)
    second = backup.synchronize(source, remote, last_verified_head=first['headVersion'])
    after, _ = compact._head(compact.Remote(remote))
    assert after['groups'][0] == complete
    assert not any(c['sha256'] in path for c in complete['chunks'] for path in remote.puts[before:])
    assert second['storedBytes'] < second['originalBytes']
    cold = tmp_path/'cold.sqlite'; backup.synchronize(cold, remote)
    assert history.read_page(cold, limit=50)['rows'] == history.read_page(source, limit=50)['rows']


@pytest.mark.parametrize('fault', ['expansion', 'trailing', 'count', 'digest'])
def test_malicious_compressed_group_never_creates_live_database(tmp_path, fault):
    import zlib
    remote = original.Remote(); remote.history_format_version = 2
    source = tmp_path/'source.sqlite'; original.add(source, '2026-09-12T00:00:00Z', 3000)
    backup.synchronize(source, remote)
    wrapped = compact.Remote(remote); manifest, _ = compact._head(wrapped)
    group = manifest['groups'][0]
    if fault == 'expansion':
        group['rawBytes'] = 1; manifest['rawBytes'] = 1
    elif fault == 'trailing':
        chunk = group['chunks'][-1]
        path = compact.PREFIX+'/chunks/'+chunk['sha256']+'.bin'
        raw = remote.files[path] + zlib.compress(b'extra')
        identity = backup.digest(raw)
        remote.files[compact.PREFIX+'/chunks/'+identity+'.bin'] = raw
        manifest['storedBytes'] += len(raw)-chunk['bytes']
        chunk.update(sha256=identity, bytes=len(raw))
    elif fault == 'count':
        group['count'] += 1; manifest['counts']['views'] += 1
    else: group['rawSha256'] = '0'*64
    raw = backup.encode(manifest); identity = backup.digest(raw)
    remote.files[compact.PREFIX+'/manifests/'+identity+'.json'] = raw
    remote.files[compact.PREFIX+'/head.json'] = backup.encode({'schemaVersion':compact.SCHEMA,'manifestSha256':identity})
    target = tmp_path/'cold.sqlite'
    with pytest.raises(ValueError): backup.synchronize(target, remote)
    assert not target.exists()


def test_original_or_compressed_bound_fails_without_publishing_partial_history(tmp_path, monkeypatch):
    remote = original.Remote(); remote.history_format_version = 2
    source = tmp_path/'source.sqlite'; original.add(source, '2026-09-12T00:00:00Z', 3000)
    backup.synchronize(source, remote); before = copy.deepcopy(remote.files)
    original.add(source, '2026-09-13T00:00:00Z', 3100)
    monkeypatch.setattr(compact, 'MAX_RAW_BYTES', 1)
    with pytest.raises(ValueError, match='bound'): backup.synchronize(source, remote)
    assert remote.files == before


def test_compressed_transport_keeps_wire_bound_for_larger_original_history(tmp_path, monkeypatch):
    from test_argus_analysis_history import brief
    remote = original.Remote(); remote.history_format_version = 2
    source = tmp_path/'source.sqlite'; history.initialize(source)
    record = history.make_record(brief(), {'5': {'observations': ['repeated-value'] * 10000}})
    history.append(source, record)
    monkeypatch.setattr(backup, 'MAX_ARCHIVE_BYTES', 65536)
    with pytest.raises(ValueError, match='bound'): backup.synchronize_v1(source, remote)
    result = backup.synchronize(source, remote)
    assert result['originalBytes'] > 65536 > result['storedBytes']
    cold = tmp_path/'cold.sqlite'; backup.synchronize(cold, remote)
    assert history.read_record(cold) == record


def test_incompressible_record_splits_at_existing_transport_bound(tmp_path):
    import random
    from test_argus_analysis_history import brief
    remote = original.Remote(); remote.history_format_version = 2
    source = tmp_path/'source.sqlite'; history.initialize(source)
    record = history.make_record(brief(), {'5': {'input': random.Random(7).randbytes(600000).hex()}})
    history.append(source, record); backup.synchronize(source, remote)
    chunks = [v for k,v in remote.files.items() if '/chunks/' in k]
    assert len(chunks) > 1 and max(map(len, chunks)) <= backup.CHUNK_BYTES
    cold = tmp_path/'cold.sqlite'; backup.synchronize(cold, remote)
    assert history.read_record(cold) == record


def test_shared_deadline_stops_compression_before_any_publication(tmp_path):
    remote = original.Remote(); remote.history_format_version = 2
    source = tmp_path/'source.sqlite'; original.add(source, '2026-09-12T00:00:00Z', 3000)
    def expired(): raise TimeoutError('shared_deadline')
    remote._check_deadline = expired
    with pytest.raises(TimeoutError): backup.synchronize(source, remote)
    assert remote.files == {}
