"""Remote analysis history v3 (2026-10-20): skeletons and parts kept once, append-only packs."""
import hashlib
import json
import sqlite3

import pytest

import argus_analysis_history as history
import argus_analysis_history_parts as v3
from test_argus_analysis_history import brief


class Remote:
    def __init__(self):
        self.files = {}; self.overwrites = 0; self.before_head = None

    def _check_deadline(self):
        return 100

    def get(self, path):
        raw = self.files.get(path)
        return (raw, hashlib.sha1(raw).hexdigest()) if raw is not None else (None, None)

    def put(self, path, raw, *, expected_version):
        if path.endswith('head.json') and self.before_head:
            self.before_head(); self.before_head = None
        current = self.files.get(path)
        if (hashlib.sha1(current).hexdigest() if current is not None else None) != expected_version:
            raise ValueError('history_remote_write_conflict_or_unavailable')
        if current is not None and not path.endswith('head.json'):
            self.overwrites += 1
        self.files[path] = bytes(raw)


STABLE = {'rows': [{'name': f'条件{i}', 'value': i * 1.5, 'note': '過去の局面との比較に使う値です。'} for i in range(60)]}


def calculations(day, value, cutoff):
    return {'5': {'comparison': {'schemaVersion': 'jp-market-comparison-v1', 'anchorDate': day,
                                 'actualAnchorPrice': 100, 'unit': 'ANCHOR_100',
                                 'forecast': {'horizonSessions': 5, 'line': [{'offsetSessions': 5, 'value': value}],
                                              'flatThresholdPct': 0.5, 'validationStatus': 'UNVALIDATED'}},
                  'marketFeatureSnapshot': dict(STABLE),
                  'marketInternals': {**STABLE, 'informationCutoff': cutoff}}}


def edition(at, value=101.0):
    return history.make_record(brief(at), calculations(at[:10], value, at))


def local_file(tmp_path, name, records):
    path = tmp_path / name
    history.initialize(path)
    for record in records:
        history.append(path, record)
    return path


def bodies(path):
    conn = sqlite3.connect(path)
    try:
        return (dict(conn.execute('SELECT record_id, body FROM views').fetchall()),
                dict(conn.execute('SELECT result_id, body FROM outcomes').fetchall()))
    finally:
        conn.close()


def test_split_and_assemble_keep_the_record_identity_and_move_read_times_out_of_parts():
    record = edition('2026-10-19T00:00:00Z')
    skeleton, parts = v3.split(record)
    internals = skeleton['calculations']['5']['marketInternals']
    assert set(internals) == {'$part', '$volatile'} and internals['$volatile'] == {'informationCutoff': '2026-10-19T00:00:00Z'}
    rebuilt = v3.assemble(skeleton, lambda identity: json.loads(parts[identity]))
    assert rebuilt == record
    later = edition('2026-10-19T03:00:00Z')
    _, later_parts = v3.split(later)
    # the snapshot and the internals differ only by their read time: both parts are shared
    assert skeleton['calculations']['5']['marketFeatureSnapshot']['$part'] in later_parts
    assert internals['$part'] in later_parts


def test_a_wrong_part_never_rebuilds_a_record():
    record = edition('2026-10-19T00:00:00Z')
    skeleton, parts = v3.split(record)
    identity = skeleton['calculations']['5']['marketFeatureSnapshot']['$part']
    wrong = dict(parts); wrong[identity] = v3._encode({'rows': []})
    with pytest.raises(ValueError):
        v3.assemble(skeleton, lambda key: json.loads(wrong[key]))


def test_migration_in_bounded_steps_is_append_only_and_restores_byte_identically(tmp_path):
    records = [edition(f'2026-10-{d:02d}T00:00:00Z', 100 + d) for d in range(1, 7)]
    local = local_file(tmp_path, 'local.sqlite3', records)
    remote = Remote(); calls = 0
    while True:
        calls += 1
        result = v3.synchronize(local, remote, max_views=2)
        if result['complete']:
            break
    assert calls == 3 and remote.overwrites == 0
    assert result['counts']['views'] == 6
    assert v3.synchronize(local, remote)['written'] == {'packs': 0, 'views': 0, 'outcomes': 0}
    fresh = tmp_path / 'fresh.sqlite3'
    restored = v3.synchronize(fresh, remote)
    assert restored['restoredCounts'] == {'views': 6, 'outcomes': 0}
    assert bodies(fresh) == bodies(local)


def test_unchanged_parts_cost_nothing_on_later_editions(tmp_path):
    local = local_file(tmp_path, 'local.sqlite3', [edition('2026-10-01T00:00:00Z')])
    remote = Remote()
    first = v3.synchronize(local, remote)['capacity']['originalBytes']
    history.append(local, edition('2026-10-01T03:00:00Z'))
    second = v3.synchronize(local, remote)['capacity']['originalBytes'] - first
    assert second < first / 2


def test_local_newer_editions_survive_a_restore_and_are_published(tmp_path):
    remote = Remote()
    v3.synchronize(local_file(tmp_path, 'a.sqlite3', [edition('2026-10-01T00:00:00Z')]), remote)
    other = local_file(tmp_path, 'b.sqlite3', [edition('2026-10-02T00:00:00Z')])
    result = v3.synchronize(other, remote)
    assert result['restoredCounts'] == {'views': 1, 'outcomes': 0}
    assert result['counts']['views'] == 2 and result['complete']


@pytest.mark.parametrize('damage', ['pack', 'missing_part'])
def test_damaged_remote_is_rejected_before_local_history_changes(tmp_path, damage):
    remote = Remote()
    v3.synchronize(local_file(tmp_path, 'a.sqlite3', [edition('2026-10-01T00:00:00Z')]), remote)
    pack = next(k for k in remote.files if '/packs/' in k)
    if damage == 'pack':
        remote.files[pack] = remote.files[pack][:-1] + bytes([remote.files[pack][-1] ^ 1])
    else:
        import zlib
        manifest, _, _ = v3._head(remote)
        entry = manifest['packs'][0]
        lines = [l for l in zlib.decompress(remote.files[pack]).split(b'\n')[:-1]
                 if json.loads(l)['kind'] != 'part']
        raw = b''.join(l + b'\n' for l in lines)
        remote.files[pack] = zlib.compress(raw, 6)
    other = local_file(tmp_path, 'b.sqlite3', [edition('2026-10-02T00:00:00Z')])
    before = bodies(other)
    with pytest.raises(ValueError):
        v3.synchronize(other, remote)
    assert bodies(other) == before


def test_a_concurrent_writer_is_never_overwritten(tmp_path):
    remote = Remote()
    v3.synchronize(local_file(tmp_path, 'a.sqlite3', [edition('2026-10-01T00:00:00Z')]), remote)
    head = remote.files[v3.PREFIX + '/head.json']
    local = local_file(tmp_path, 'b.sqlite3', [edition('2026-10-01T00:00:00Z'), edition('2026-10-02T00:00:00Z')])
    def other_writer():
        remote.files[v3.PREFIX + '/head.json'] = head + b' '
    remote.before_head = other_writer
    with pytest.raises(ValueError):
        v3.synchronize(local, remote)
    assert remote.files[v3.PREFIX + '/head.json'] == head + b' '


def test_capacity_warns_at_seventy_percent_of_either_bound(monkeypatch):
    manifest = {'storedBytes': 70, 'rawBytes': 10}
    monkeypatch.setattr(v3, 'MAX_STORED_BYTES', 100)
    assert v3.capacity(manifest)['warning'] is True
    assert v3.capacity({'storedBytes': 69, 'rawBytes': 10})['warning'] is False
    repo = v3.capacity(manifest, repository_bytes=int(v3.REPOSITORY_RECOMMENDED_BYTES * 0.7))
    assert repo['repositoryWarning'] is True and repo['repositoryShare'] == 0.7


def test_outcomes_are_kept_after_their_editions_and_restored(tmp_path):
    from test_argus_analysis_history import _issue
    local = tmp_path / 'local.sqlite3'; history.initialize(local)
    _issue(local, '2026-09-13T00:00:00Z', '2026-09-11', 102, [{'date': '2026-09-14', 'close': 98}], '2026-09-14T07:00:00Z')
    _issue(local, '2026-09-15T08:00:00Z', '2026-09-15', 103, [{'date': '2026-09-16', 'close': 104}], '2026-09-16T07:00:00Z')
    views, outcomes = bodies(local)
    assert outcomes
    remote = Remote()
    assert v3.synchronize(local, remote)['complete']
    fresh = tmp_path / 'fresh.sqlite3'
    assert v3.synchronize(fresh, remote)['restoredCounts'] == {'views': len(views), 'outcomes': len(outcomes)}
    assert bodies(fresh) == (views, outcomes)
