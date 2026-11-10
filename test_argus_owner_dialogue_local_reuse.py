"""2026-11-10: a new boot reads only the remote parts the persistent local DB lacks."""
import copy
import shutil

import pytest
import argus_owner_dialogue_backup as backup
from test_argus_owner_dialogue_backup import keys, add
from test_argus_owner_dialogue_segments import large, rows_digest


def counting(remote):
    reads = []
    original = remote.get
    def get(path):
        if '/chunks/' in path:
            reads.append(path)
        return original(path)
    remote.get = get
    return reads


def test_new_boot_with_identical_local_db_reads_no_remote_part(tmp_path, monkeypatch):
    path, remote = large(tmp_path, monkeypatch)
    backup.synchronize(path, remote, keys())
    before = rows_digest(path); files = copy.deepcopy(remote.files)
    reads = counting(remote)
    result = backup.synchronize(path, remote, keys())   # no previous: a new boot
    assert reads == [] and result['status'] == 'VERIFIED'
    assert rows_digest(path) == before and remote.files == files


def test_new_boot_with_newer_local_records_reads_only_the_changed_tail(tmp_path, monkeypatch):
    path, remote = large(tmp_path, monkeypatch)
    backup.synchronize(path, remote, keys())
    head, _ = backup._head(remote, keys())
    add(path); before = rows_digest(path); existing = set(remote.files)
    reads = counting(remote)
    result = backup.synchronize(path, remote, keys())
    tail = {backup.PREFIX + '/chunks/' + c['sha256'] + '.bin' for c in head['segments'][-1]['chunks']}
    # Reads of chunks that did not exist yet are the existing write-once check
    # before an upload, not restore reads.
    assert {r for r in reads if r in existing} <= tail and len(head['segments']) > 1
    assert result['counts']['requests'] == 13 and rows_digest(path) == before
    cold = tmp_path / 'cold'; backup.synchronize(cold, remote, keys())
    assert rows_digest(cold) == before


def test_rows_missing_locally_are_still_restored_from_remote(tmp_path, monkeypatch):
    path, remote = large(tmp_path, monkeypatch)
    backup.synchronize(path, remote, keys()); full = rows_digest(path)
    partial = tmp_path / 'partial'; add(partial)          # a different, smaller local DB
    result = backup.synchronize(partial, remote, keys())
    assert result['restoredCounts'] == {'requests': 12, 'completions': 12}
    assert rows_digest(partial)['requests'][0] == 13


def test_corrupt_remote_part_that_local_lacks_still_stops_before_merge(tmp_path, monkeypatch):
    path, remote = large(tmp_path, monkeypatch)
    backup.synchronize(path, remote, keys())
    head, _ = backup._head(remote, keys())
    name = backup.PREFIX + '/chunks/' + head['segments'][-1]['chunks'][-1]['sha256'] + '.bin'
    remote.files[name] = remote.files[name][:-1] + bytes([remote.files[name][-1] ^ 1])
    other = tmp_path / 'other'; add(other); before = rows_digest(other)
    with pytest.raises(ValueError, match='chunk_corrupt'):
        backup.synchronize(other, remote, keys())
    assert rows_digest(other) == before
