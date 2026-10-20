"""2026-10-20 (owner): the local history keeps calculation parts once, without losing a byte."""
import json
import sqlite3
import tempfile
import zlib
from pathlib import Path

import pytest

import argus_analysis_history as history
import argus_analysis_history_backup as v1
import argus_analysis_history_compact as v2
import argus_analysis_history_local as local_form
import argus_analysis_history_parts as v3
from test_argus_analysis_history_parts import Remote, bodies, edition, local_file

NOW = '2026-10-20T15:00:00Z'


def history_file(tmp_path, name='local.sqlite3', days=6):
    return local_file(tmp_path, name, [edition(f'2026-10-{d:02d}T00:00:00Z', 100 + d) for d in range(1, days + 1)])


def originals(path):
    conn = sqlite3.connect(path)
    try:
        return dict(conn.execute('SELECT record_id, body FROM views').fetchall())
    finally:
        conn.close()


def test_migration_keeps_every_original_body_and_shares_parts(tmp_path):
    path = history_file(tmp_path)
    before = originals(path)
    result = history.migrate_to_parts(path, now_iso=NOW)
    assert result['migrated'] == 6 and result['failures'] == []
    status = history.form_status(path)
    assert status['migrated'] == 6 and status['remaining'] == 0 and status['userVersion'] == 2
    # the market snapshot and internals repeat across editions: fewer parts than editions x containers
    assert status['partCount'] < 6 * 2
    for record_id, body in before.items():
        assert history.read_full_body(path, 'views', 'record_id', record_id) == body
    stored = originals(path)
    assert all(stored[r] != before[r] for r in before)          # rows now hold skeletons
    assert history.read_record(path) == json.loads(before[history.read_record(path)['recordId']])
    page = history.read_page(path, limit=10)
    assert len(page['rows']) == 6
    assert history.verify_all_bodies(path) == {'checked': 6, 'mismatches': 0}


def test_brief_fields_stay_readable_by_sql(tmp_path):
    path = history_file(tmp_path, days=2)
    history.migrate_to_parts(path, now_iso=NOW)
    conn = sqlite3.connect(path)
    try:
        rows = conn.execute("SELECT json_extract(body,'$.brief.unifiedContext') IS NOT NULL FROM views").fetchall()
    finally:
        conn.close()
    assert rows and all(r[0] for r in rows)


def test_a_rebuild_mismatch_keeps_the_full_row(tmp_path, monkeypatch):
    path = history_file(tmp_path, days=2)
    before = originals(path)
    real = local_form.assemble
    monkeypatch.setattr(local_form, 'assemble', lambda s, p: {**real(s, p), 'extra': 1})
    result = history.migrate_to_parts(path, now_iso=NOW)
    assert result['migrated'] == 0 and len(result['failures']) == 2
    assert originals(path) == before and history.form_status(path)['userVersion'] == 1


def test_a_damaged_part_is_an_error_never_a_guess(tmp_path):
    path = history_file(tmp_path, days=2)
    history.migrate_to_parts(path, now_iso=NOW)
    conn = sqlite3.connect(path)
    identity = conn.execute('SELECT identity FROM view_parts LIMIT 1').fetchone()[0]
    conn.execute('UPDATE view_parts SET body=? WHERE identity=?', (zlib.compress(b'{"x":1}'), identity))
    conn.commit(); conn.close()
    errors = 0
    for record_id in originals(path):
        try:
            history.read_full_body(path, 'views', 'record_id', record_id)
        except ValueError:
            errors += 1
    assert errors >= 1
    assert history.verify_all_bodies(path)['mismatches'] == errors


def test_append_compares_against_the_original_body(tmp_path):
    record = edition('2026-10-01T00:00:00Z')
    path = local_file(tmp_path, 'local.sqlite3', [record])
    history.migrate_to_parts(path, now_iso=NOW)
    assert history.append(path, record)['inserted'] is False
    changed = json.loads(json.dumps(record)); changed['brief']['aiText']['nowJa'] = '別の文章'
    changed['recordId'] = record['recordId']
    with pytest.raises(ValueError):
        history.append(path, changed)


def test_the_way_back_restores_every_body_and_the_version(tmp_path):
    path = history_file(tmp_path)
    before = originals(path)
    history.migrate_to_parts(path, now_iso=NOW)
    assert history.restore_full_bodies(path, limit=100) == {'restored': 6, 'remaining': 0}
    assert originals(path) == before and history.form_status(path)['userVersion'] == 1


def test_remote_copies_are_identical_before_and_after(tmp_path):
    plain = history_file(tmp_path, 'plain.sqlite3')
    converted = history_file(tmp_path, 'converted.sqlite3')
    history.migrate_to_parts(converted, now_iso=NOW)
    a, b = Remote(), Remote()
    assert v3.synchronize(plain, a)['complete'] and v3.synchronize(converted, b)['complete']
    assert a.files == b.files                                   # v3: byte-identical remote
    fresh = tmp_path / 'fresh.sqlite3'
    v3.synchronize(fresh, b)
    assert bodies(fresh)[0] == {r: history.read_full_body(converted, 'views', 'record_id', r)
                                for r in originals(converted)}
    with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
        v1._snapshot(plain, d1); v1._snapshot(converted, d2)
        assert Path(d1, 'archive.ndjson').read_bytes() == Path(d2, 'archive.ndjson').read_bytes()


def test_restoring_remote_rows_does_not_conflict_with_converted_rows(tmp_path):
    path = history_file(tmp_path, days=3)
    staging = history_file(tmp_path, 'staging.sqlite3', days=4)    # the same three plus one more
    history.migrate_to_parts(path, now_iso=NOW)
    v1._merge_validated(path, staging)
    assert history.form_status(path)['views'] == 4
    assert history.verify_all_bodies(path)['mismatches'] == 0


def test_compaction_returns_space_after_conversion(tmp_path):
    path = history_file(tmp_path, days=12)
    history.migrate_to_parts(path, now_iso=NOW)
    sizes = history.compact_file(path)
    assert sizes['afterBytes'] < sizes['beforeBytes']
    assert history.verify_all_bodies(path) == {'checked': 12, 'mismatches': 0}


def test_split_refuses_a_record_that_already_holds_a_placeholder():
    record = edition('2026-10-01T00:00:00Z')
    record['calculations']['5']['comparison']['x'] = {'$part': 'a' * 64}
    with pytest.raises(ValueError):
        local_form.split(record)


def test_the_resident_step_converts_checks_all_and_compacts(tmp_path, monkeypatch):
    import scanner
    path = history_file(tmp_path, days=8)
    before = originals(path)
    monkeypatch.setattr(scanner, "_ANALYSIS_HISTORY_FORM", {"status": "NOT_RUN"})
    monkeypatch.setattr(scanner, "ANALYSIS_HISTORY_COMPACT_MIN_FREE_BYTES", 0)
    scanner._analysis_history_form_step(str(path))
    state = scanner._ANALYSIS_HISTORY_FORM
    assert state["status"] == "CONVERTED" and state["migrated"] == 8 and state["failureCount"] == 0
    assert state["verifiedAll"] == {"checked": 8, "mismatches": 0}
    assert state["compact"]["afterBytes"] <= state["compact"]["beforeBytes"]
    assert {r: history.read_full_body(path, 'views', 'record_id', r) for r in before} == before


def test_the_resident_step_only_runs_after_the_remote_holds_everything():
    import inspect
    import scanner
    source = inspect.getsource(scanner._market_brief_history_sync)
    assert source.index("if v3_complete:") < source.index("_analysis_history_form_step(path)")
