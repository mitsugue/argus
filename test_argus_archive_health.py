"""Archive measurement must not rewrite sources or confuse window/batch bounds."""
import hashlib
import json
import sqlite3

import pytest

from argus_archive_health import read_archive_metadata
from argus_collection_health import build_collection_health


def test_measures_archive_beyond_analysis_window_without_reading_or_deleting_bodies(tmp_path, monkeypatch):
    path = tmp_path / "source.sqlite3"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE selected_vix_inputs(session TEXT, body TEXT)")
        conn.executemany("INSERT INTO selected_vix_inputs VALUES (?, ?)",
                         [(str(i), "PRIVATE_BODY") for i in range(3101)])
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    original = sqlite3.connect
    def protected_connection(*args, **kwargs):
        conn = original(*args, **kwargs)
        # Fail the query if any implementation attempts to select source bodies.
        conn.set_authorizer(lambda action, first, second, *rest:
                            sqlite3.SQLITE_DENY if action == sqlite3.SQLITE_READ and second == "body"
                            else sqlite3.SQLITE_OK)
        return conn
    monkeypatch.setattr(sqlite3, "connect", protected_connection)
    result = read_archive_metadata(path, kind="source_history")
    assert result["status"] == "measured"
    assert result["tables"]["selected_vix_inputs"] == {"status": "measured", "rows": 3101}
    assert result["tables"]["raw_sources"] == {"status": "not_created", "rows": None}
    assert result["databaseBytes"] == path.stat().st_size and result["walBytes"] == 0
    assert "PRIVATE_BODY" not in json.dumps(result) and str(path) not in json.dumps(result)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


def test_committed_wal_rows_are_counted_but_uncommitted_rows_are_not(tmp_path):
    path = tmp_path / "analysis.sqlite3"
    writer = sqlite3.connect(path)
    try:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("CREATE TABLE views(body TEXT)")
        writer.execute("INSERT INTO views VALUES ('PRIVATE_RECORD')")
        writer.commit()
        writer.execute("INSERT INTO views VALUES ('UNCOMMITTED_PRIVATE_RECORD')")
        result = read_archive_metadata(path, kind="analysis_history")
        assert result["status"] == "measured" and result["walBytes"] > 0
        assert result["tables"]["views"]["rows"] == 1
        assert "PRIVATE_RECORD" not in json.dumps(result)
    finally:
        writer.rollback()
        writer.close()


@pytest.mark.parametrize("state", ["not_configured", "missing", "corrupt", "directory", "symlink"])
def test_unknown_is_not_an_empty_healthy_archive_and_missing_is_not_created(tmp_path, state):
    path = tmp_path / "archive.sqlite3"
    if state == "corrupt": path.write_bytes(b"PRIVATE_INVALID_FILE")
    elif state == "directory": path.mkdir()
    elif state == "symlink": path.symlink_to(tmp_path / "missing-target")
    result = read_archive_metadata(None if state == "not_configured" else path, kind="analysis_history")
    assert result["status"] == (state if state in ("missing", "not_configured") else "unavailable")
    assert result["databaseBytes"] is None and result["walBytes"] is None
    assert all(t == {"status": "unknown", "rows": None} for t in result["tables"].values())
    if state == "missing": assert not path.exists()


def test_timed_out_measurement_is_unknown_with_no_partial_counts(tmp_path, monkeypatch):
    import argus_archive_health as module
    path = tmp_path / "analysis.sqlite3"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE views(body TEXT)")
    ticks = iter([1.0, 2.0])
    monkeypatch.setattr(module.time, "monotonic", lambda: next(ticks, 2.0))
    result = read_archive_metadata(path, kind="analysis_history")
    assert result["status"] == "unavailable"
    assert result["tables"]["views"]["rows"] is None


def test_only_closed_archive_scalars_can_reach_admin_diagnostics():
    sentinel = "PRIVATE_ARCHIVE_SENTINEL"
    raw = {"archives": {"analysis_history": {"status": "measured", "databaseBytes": 4096,
         "walBytes": 0, "path": sentinel, "tables": {"views": {"status": "measured", "rows": 2,
         "body": sentinel}, sentinel: {"rows": 999}}, "remote": sentinel}, sentinel: {"rows": 100}}}
    health = build_collection_health(raw, now_iso="2026-10-06T03:30:00+09:00")
    archive = health["archives"][0]
    assert sentinel not in json.dumps(health)
    assert archive["status"] == "measured" and archive["databaseBytes"] == 4096
    assert archive["tables"][0]["rows"] == 2
    assert archive["rowLimit"] is None and archive["storageQuotaBytes"] is None
    assert archive["automaticPruning"] is False and archive["remoteRecoveryMeasured"] is False
    poisoned = build_collection_health({"archives": {"analysis_history": {"status": "measured",
           "databaseBytes": True, "walBytes": -1, "tables": {"views": {"status": "measured", "rows": True}}}}},
           now_iso="2026-10-06T03:30:00+09:00")["archives"][0]
    assert poisoned["status"] == "unknown" and poisoned["tables"][0]["rows"] is None


def test_actual_admin_collector_uses_only_existing_local_archives(monkeypatch, tmp_path):
    import scanner
    paths = []
    monkeypatch.setattr(scanner, "_cost_policy_durable_enabled", lambda: True)
    monkeypatch.setattr(scanner, "_DURABILITY_PATHS", {"root": str(tmp_path)})
    def read(path, *, kind):
        paths.append((path, kind))
        return {"status": "missing"}
    monkeypatch.setattr("argus_archive_health.read_archive_metadata", read)
    health = build_collection_health(scanner._collection_health_inputs("2026-10-06T03:30:00+09:00"),
                                    now_iso="2026-10-06T03:30:00+09:00")
    assert {kind for _, kind in paths} == {"analysis_history", "source_history"}
    assert all(str(tmp_path) in path for path, _ in paths)
    assert all(a["status"] == "missing" for a in health["archives"])
    monkeypatch.setattr(scanner, "_collection_health_inputs", lambda *_: (_ for _ in ()).throw(AssertionError("admin only")))
    assert "archives" not in json.dumps(scanner._public_diagnostics_snapshot())
