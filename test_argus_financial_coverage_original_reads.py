"""原本検証を保ったまま、同じSQLite読取中の重複I/Oだけを抑える。"""
from collections import Counter
import json
import sqlite3

import argus_earnings_history as history
from test_argus_earnings_history import AT, row, _previous_read_coverage


def count_original_reads(monkeypatch):
    calls = Counter()
    original = sqlite3.connect
    class Connection(sqlite3.Connection):
        def execute(self, query, parameters=()):
            if query.startswith('SELECT raw,sha256 FROM raw_sources WHERE id='):
                calls[parameters[0]] += 1
            return super().execute(query, parameters)
    def connect(*args, **kwargs):
        kwargs['factory'] = Connection
        return original(*args, **kwargs)
    monkeypatch.setattr(sqlite3, 'connect', connect)
    return calls


def test_one_original_shared_by_different_scope_receipts_is_read_once_per_call(tmp_path, monkeypatch):
    path = tmp_path/'shared.sqlite3'
    for i in range(8):
        members = [str(1000+i+j) for j in range(225)]
        history.retain(path, [], received_at=AT, member_codes=members,
                       query_date='2026-10-06', complete_scope=members)
    expected = _previous_read_coverage(path, cutoff=AT)
    before = path.read_bytes()
    calls = count_original_reads(monkeypatch)
    history.clear_verified_originals()
    assert json.dumps(history.read_coverage(path, cutoff=AT)) == json.dumps(expected)
    assert sum(calls.values()) == len(calls) == 1
    # 新しい呼出しの検証を、前回の原本保持で省略しない。
    history.clear_verified_originals()
    assert json.dumps(history.read_coverage(path, cutoff=AT)) == json.dumps(expected)
    assert sum(calls.values()) == 2
    assert path.read_bytes() == before


def test_bounded_originals_preserve_results_and_existing_integrity_checks(tmp_path, monkeypatch):
    import collections
    path = tmp_path/'shared.sqlite3'
    members = [str(1000+j) for j in range(225)]
    for i in range(18):
        history.retain(path, [{**row(), 'FOP':str(100+i)}],
                       received_at=f'2026-10-06T10:{i:02}:00Z', member_codes=members,
                       query_date='2026-10-06', complete_scope=members)
    cutoff = '2026-10-07T00:00:00Z'
    expected = _previous_read_coverage(path, cutoff=cutoff)
    original = collections.OrderedDict
    retained = []
    class Observed(original):
        def __setitem__(self, key, value):
            super().__setitem__(key, value)
            retained.append((len(self), sum(len(row[0]) for row in self.values())))
    monkeypatch.setattr(collections, 'OrderedDict', Observed)
    calls = count_original_reads(monkeypatch)
    history.clear_verified_originals()
    assert json.dumps(history.read_coverage(path, cutoff=cutoff)) == json.dumps(expected)
    assert len(calls) == 18
    assert retained and max(n for n,_ in retained) == 16
    assert all(n<=16 and size<=1024*1024 for n,size in retained)
    # 元原本の改変は、呼出しを跨いで再利用せず、既存どおり拒否する。
    history.clear_verified_originals()
    with sqlite3.connect(path) as db:
        db.execute("UPDATE raw_sources SET sha256=?", ('0'*64,))
    import pytest
    with pytest.raises(ValueError, match='integrity'):
        history.read_coverage(path, cutoff=cutoff)
