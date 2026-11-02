"""Cursor equivalence against the original full WAL reader and lifetime checks."""
import builtins
import hashlib
import json
import os
import weakref

import pytest

import argus_chart_intelligence as charts
import argus_tick_durability as wal


def legacy_full_reader(path, *, after_sequence=0):
    # Original full reader before extraction of the common decoder. Keep the
    # validation here independent of the new decoder/cursor implementation.
    records = []
    corrupt = 0
    maximum = int(after_sequence)
    try:
        with open(path, 'rb') as handle:
            lines = handle.readlines()
    except FileNotFoundError:
        lines = []
    for raw in lines:
        try:
            record = json.loads(raw.decode('utf-8'))
            sequence = int(record.get('sequence') or 0)
            if (not isinstance(record, dict) or
                    record.get('schemaVersion') != 'argus-mission-wal-v1' or
                    record.get('recordHash') != wal._record_hash(record) or
                    sequence <= 0):
                raise ValueError('invalid_wal_record')
            maximum = max(maximum, sequence)
            if sequence > int(after_sequence):
                records.append(record)
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
            corrupt += 1
    records.sort(key=lambda row: int(row['sequence']))
    return dict(records=records, corruptCount=corrupt,
                maximumSequence=maximum,
                bytes=os.path.getsize(path) if os.path.exists(path) else 0)


def encoded(sequence, *, corrupt_hash=False, schema='argus-mission-wal-v1'):
    row = dict(schemaVersion=schema, sequence=sequence,
               payload={'label': '合成データ', 'values': [1.25, None, True]},
               jobId='fixture-job', unknownField={'kept': True})
    row['recordHash'] = wal._record_hash(row)
    if corrupt_hash:
        row['recordHash'] = '0' * 64
    return json.dumps(row, ensure_ascii=False).encode() + b'\n'


@pytest.mark.parametrize('after', [0, 1, 3, 99, -5, True, '2'])
@pytest.mark.parametrize('tail', [b'', b'{"incomplete":', b'\xff\n'])
def test_cursor_and_default_reader_match_original_with_corruption(tmp_path, after, tail):
    path = tmp_path / 'transitions.wal'
    raw = (encoded(3) + encoded(1) + encoded(3) + encoded('2') +
           encoded(7, corrupt_hash=True) + encoded(0) +
           encoded(9, schema='unknown') + b'{}\n\n' + tail)
    path.write_bytes(raw)
    before = (hashlib.sha256(raw).hexdigest(), path.stat().st_mtime_ns)
    original = legacy_full_reader(str(path), after_sequence=after)
    assert wal.read_valid_wal(str(path), after_sequence=after) == original
    assert wal.read_valid_wal_cursor(str(path), after_sequence=after) == {
        'recordCount': len(original['records']),
        **{key: original[key] for key in ('corruptCount', 'maximumSequence', 'bytes')}}
    assert (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns) == before


def test_missing_and_empty_cursor_do_not_create_a_file(tmp_path):
    path = tmp_path / 'absent.wal'
    assert wal.read_valid_wal_cursor(str(path), after_sequence=12) == {
        'recordCount': 0, 'corruptCount': 0, 'maximumSequence': 12, 'bytes': 0}
    assert not path.exists()
    path.write_bytes(b'')
    assert wal.read_valid_wal_cursor(str(path)) == {
        'recordCount': 0, 'corruptCount': 0, 'maximumSequence': 0, 'bytes': 0}


@pytest.mark.parametrize('raw', [b'[]\n', b'null\n', b'"text"\n'])
def test_non_mapping_exception_semantics_remain_the_original(tmp_path, raw):
    path = tmp_path / 'non-mapping.wal'
    path.write_bytes(raw)
    for reader in (legacy_full_reader, wal.read_valid_wal, wal.read_valid_wal_cursor):
        with pytest.raises(AttributeError):
            reader(str(path))


def test_cursor_iterates_lines_and_never_calls_readlines(tmp_path, monkeypatch):
    path = tmp_path / 'streamed.wal'
    path.write_bytes(encoded(1) + encoded(2))

    class StreamOnly:
        def __init__(self, *args, **kwargs):
            self.handle = builtins.open(*args, **kwargs)
        def __enter__(self):
            return self
        def __exit__(self, *args):
            self.handle.close()
        def __iter__(self):
            return iter(self.handle)
        def fileno(self):
            return self.handle.fileno()
        def readline(self, size):
            return self.handle.readline(size)
        def readlines(self):
            pytest.fail('cursor retained raw WAL lines')

    monkeypatch.setattr(wal, 'open', StreamOnly, raising=False)
    assert wal.read_valid_wal_cursor(str(path))['recordCount'] == 2


def test_cursor_does_not_chase_rows_appended_after_its_captured_length(tmp_path, monkeypatch):
    path = tmp_path / 'growing.wal'
    first, second = encoded(1), encoded(2)
    path.write_bytes(first)

    class GrowingFile:
        def __init__(self, *args, **kwargs):
            self.handle = builtins.open(*args, **kwargs)
            self.appended = False
        def __enter__(self):
            return self
        def __exit__(self, *args):
            self.handle.close()
        def fileno(self):
            return self.handle.fileno()
        def readline(self, size):
            if not self.appended:
                with builtins.open(path, 'ab') as output:
                    output.write(second)
                self.appended = True
            return self.handle.readline(size)

    monkeypatch.setattr(wal, 'open', GrowingFile, raising=False)
    value = wal.read_valid_wal_cursor(str(path))
    assert value == {'recordCount': 1, 'corruptCount': 0,
                     'maximumSequence': 1, 'bytes': len(first + second)}
    assert path.read_bytes() == first + second


def test_cursor_rejects_nonregular_input_instead_of_reporting_an_empty_cursor(tmp_path, monkeypatch):
    path = tmp_path / 'fixture.wal'
    path.write_bytes(encoded(1))
    from types import SimpleNamespace
    import stat
    monkeypatch.setattr(wal, 'os', SimpleNamespace(
        fstat=lambda fd: SimpleNamespace(st_mode=stat.S_IFIFO, st_size=0)))
    with pytest.raises(ValueError, match='wal_cursor_requires_regular_file'):
        wal.read_valid_wal_cursor(str(path))


def test_cursor_releases_parsed_rows_without_gc_and_full_reader_retains_them(tmp_path, monkeypatch):
    path = tmp_path / 'lifetimes.wal'
    path.write_bytes(b''.join(encoded(i) for i in range(1, 65)))
    refs = []
    expect_bounded = True
    original_decode = wal._decode_valid_wal_record

    class TrackedRow(dict):
        pass

    def decode(raw):
        if expect_bounded:
            assert sum(ref() is not None for ref in refs) <= 1
        row, sequence = original_decode(raw)
        wrapped = TrackedRow(row)
        refs.append(weakref.ref(wrapped))
        return wrapped, sequence

    monkeypatch.setattr(wal, '_decode_valid_wal_record', decode)
    assert wal.read_valid_wal_cursor(str(path))['recordCount'] == 64
    assert all(ref() is None for ref in refs)
    refs.clear()
    expect_bounded = False
    full = wal.read_valid_wal(str(path))
    assert len(full['records']) == 64
    assert all(ref() is not None for ref in refs)
    del full
    assert all(ref() is None for ref in refs)


@pytest.mark.parametrize('reports', [
    [{'reportId': 'a', 'status': 'live'}, {'reportId': 'b', 'status': 'partial'}],
    [{}, {'reportId': None, 'status': None}],
    [{'reportId': '日本語', 'status': 'unknown'}],
])
def test_summary_preserves_exact_existing_consumer_values(reports):
    def consumer(rows):
        return {'reportId': rows[0].get('reportId'), 'status': rows[0].get('status'),
                'reportIds': [r.get('reportId') for r in rows],
                'statuses': [r.get('status') for r in rows]}
    projected = [charts.mission_report_scalars(r) for r in reports]
    assert consumer(projected) == consumer(reports)
    assert all(set(row) == {'reportId', 'status'} for row in projected)
    assert all(a is not b for a, b in zip(projected, reports))


def test_summary_does_not_retain_full_reports_or_payloads_without_gc():
    class Tracked(dict):
        pass
    refs, summaries = [], []
    for i in range(4):
        payload = Tracked(rows=[{'value': j} for j in range(100)])
        report = Tracked(reportId=str(i), status='live', payload=payload)
        refs.extend((weakref.ref(report), weakref.ref(payload)))
        summaries.append(charts.mission_report_scalars(report))
        del report, payload
    assert all(ref() is None for ref in refs)
    assert [r['reportId'] for r in summaries] == ['0', '1', '2', '3']


def test_summary_does_not_coerce_the_existing_get_values():
    marker = object()
    source = {'reportId': marker, 'status': False, 'payload': {'kept': True}}
    result = charts.mission_report_scalars(source)
    assert result == {'reportId': marker, 'status': False}
    assert source['payload'] == {'kept': True}
