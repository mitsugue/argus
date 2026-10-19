"""Owner decisions of 2026-10-20 ("as recommended")."""
import inspect
from datetime import datetime

import pytz

import scanner

JST = pytz.timezone("Asia/Tokyo")


def test_official_disclosure_tracking_is_not_scheduled():
    source = inspect.getsource(scanner)
    assert "_official_events_track_resident_tick" not in source
    assert '@app.route("/api/argus/official-events/track", methods=["POST"])' in source   # manual run kept


def test_research_runs_once_a_tokyo_day_before_the_open(monkeypatch, tmp_path):
    monkeypatch.setattr(scanner, "_osint_daily_run_path", lambda: str(tmp_path / "osint_daily_run.json"))
    monkeypatch.setitem(scanner._OSINT_LAST, "dailyRunDate", None)
    at = lambda h: JST.localize(datetime(2026, 10, 21, h, 30))
    assert scanner._osint_daily_run_decision(at(4)) == (False, "outside_pre_open_window")
    assert scanner._osint_daily_run_decision(at(9)) == (False, "outside_pre_open_window")
    assert scanner._osint_daily_run_decision(at(6)) == (True, None)
    scanner._osint_daily_run_mark(at(6))
    assert scanner._osint_daily_run_decision(at(8)) == (False, "already_ran_today")
    # a restart forgets memory but not the durable day
    monkeypatch.setitem(scanner._OSINT_LAST, "dailyRunDate", None)
    assert scanner._osint_daily_run_decision(at(8)) == (False, "already_ran_today")
    assert scanner._osint_daily_run_decision(JST.localize(datetime(2026, 10, 22, 7, 0))) == (True, None)


def test_scheduled_research_call_outside_the_window_calls_no_ai(monkeypatch):
    monkeypatch.setattr(scanner, "_ARGUS_ADMIN_TOKEN", "test-admin")
    monkeypatch.setattr(scanner, "_scheduled_ai_skip", lambda *a: None)
    monkeypatch.setattr(scanner, "_osint_daily_run_decision", lambda now=None: (False, "outside_pre_open_window"))
    started = []
    monkeypatch.setattr(scanner, "_osint_agents_worker", lambda syms: started.append(syms))
    monkeypatch.setitem(scanner._OSINT_AGENT_QUEUE, "6965", {"symbol": "6965"})
    with scanner.app.test_client() as client:
        body = client.post("/api/argus/admin/osint/agents-run", json={},
                           headers={"X-ARGUS-ADMIN-TOKEN": "test-admin"}).get_json()
    assert body["status"] == "expected_skip" and body["reason"] == "outside_pre_open_window" and started == []
