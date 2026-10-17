"""2026-10-03: the mission queue stayed at "processed 0, remaining 7" because the
stages before it used the whole batch deadline, and the daily short history was
fetched again after every restart because it was never written to durable state."""
import os
import tempfile
import time
from unittest import mock

import scanner
import argus_scheduler


def _run_tick(*, ledger_seconds, short_rows):
    saved = {"missions": list(scanner._MISSIONS), "windows": list(scanner._MISSION_WINDOWS),
             "forecasts": list(scanner._FORECAST_LEDGER), "outcomes": list(scanner._OUTCOME_LEDGER),
             "batch": dict(scanner._MISSION_BATCH_STATE), "token": scanner._ARGUS_ADMIN_TOKEN,
             "wal": scanner._MISSION_WAL_FILE, "lease": scanner._MISSION_LEASE_FILE,
             "persistState": dict(scanner._OSINT_PERSIST_STATE), "startup": dict(scanner._STARTUP),
             "short": list(scanner._TODAY_INTELLIGENCE.get("shortSellingHistory") or []),
             "shortCache": dict(scanner._JP_DAILY_SHORT_CACHE)}
    with tempfile.TemporaryDirectory() as directory:
        try:
            scanner._MISSIONS[:] = []; scanner._MISSION_WINDOWS[:] = []
            scanner._FORECAST_LEDGER[:] = []; scanner._OUTCOME_LEDGER[:] = []
            scanner._MISSION_BATCH_STATE.update({"cursor": 0, "remainingCount": 0, "walAppliedSequence": 0})
            scanner._OSINT_PERSIST_STATE["restored"] = True
            scanner._STARTUP.update({"state": "ready", "restoreOutcome": "test_mode"})
            scanner._ARGUS_ADMIN_TOKEN = "test-admin"
            scanner._MISSION_WAL_FILE = os.path.join(directory, "wal")
            scanner._MISSION_LEASE_FILE = os.path.join(directory, "lease")
            scanner._TODAY_INTELLIGENCE["shortSellingHistory"] = []
            scanner._JP_DAILY_SHORT_CACHE.update(rows=None, expires=0.0, status="live", errorClass=None)
            now = scanner._ai_now_iso()
            for number in range(3):
                scanner._MISSIONS.append(argus_scheduler.mission(
                    mission_type="daily_learning", market="ALL", session_date=now[:10],
                    scheduled_for=now, symbol=f"S{number}"))
            checkpoint = {"verified": True, "snapshotBytes": 1234, "serializationMs": 2,
                          "includedWalSequence": 1, "walCompaction": {"bytes": 120, "receiptSequence": 2}}
            def slow_ledger(*args, **kwargs):
                time.sleep(ledger_seconds)
                return {"changed": False}
            fetches = []
            def short_history(cached_only=False):
                fetches.append(cached_only)
                return list(short_rows)
            with mock.patch.dict(os.environ, {"ARGUS_MISSION_BATCH_MAX_EVENTS": "3",
                                              "ARGUS_OUTCOME_BATCH_MAX_EVENTS": "3",
                                              "ARGUS_MISSION_BATCH_MAX_SECONDS": "5"}, clear=False), \
                    mock.patch.object(scanner.argus_scheduler, "generate_daily_missions", return_value=[]), \
                    mock.patch.object(scanner.argus_scheduler, "generate_periodic_missions", return_value=[]), \
                    mock.patch.object(scanner.argus_scheduler, "detect_missed", return_value=[]), \
                    mock.patch.object(scanner, "_market_calendar_states",
                                      return_value={"JP": {"isTradingDay": False}, "US": {"isTradingDay": False}}), \
                    mock.patch.object(scanner, "_market_ledger_tick", side_effect=slow_ledger), \
                    mock.patch.object(scanner, "_precompute_verified_market_view",
                                      return_value=({"reportId": "r", "status": "ok"}, {"status": "verified"})), \
                    mock.patch.object(scanner, "_jp_daily_short_history", side_effect=short_history), \
                    mock.patch.object(scanner, "_osint_persist", return_value=checkpoint):
                response = scanner.app.test_client().post(
                    "/api/argus/admin/missions/tick", headers={"X-ARGUS-ADMIN-TOKEN": "test-admin"},
                    json={"triggerSource": "manual", "runId": "starvation-test"})
            durable = list(scanner._TODAY_INTELLIGENCE.get("shortSellingHistory") or [])
            return response.get_json(), fetches, durable
        finally:
            scanner._MISSIONS[:] = saved["missions"]; scanner._MISSION_WINDOWS[:] = saved["windows"]
            scanner._FORECAST_LEDGER[:] = saved["forecasts"]; scanner._OUTCOME_LEDGER[:] = saved["outcomes"]
            scanner._MISSION_BATCH_STATE.clear(); scanner._MISSION_BATCH_STATE.update(saved["batch"])
            scanner._ARGUS_ADMIN_TOKEN = saved["token"]
            scanner._MISSION_WAL_FILE = saved["wal"]; scanner._MISSION_LEASE_FILE = saved["lease"]
            scanner._OSINT_PERSIST_STATE.clear(); scanner._OSINT_PERSIST_STATE.update(saved["persistState"])
            scanner._STARTUP.clear(); scanner._STARTUP.update(saved["startup"])
            scanner._TODAY_INTELLIGENCE["shortSellingHistory"] = saved["short"]
            scanner._JP_DAILY_SHORT_CACHE.clear(); scanner._JP_DAILY_SHORT_CACHE.update(saved["shortCache"])


ROWS = [{"date": f"2026-09-{day:02d}", "shortRatio": 40.0 + day / 10, "revision": 1} for day in range(1, 11)]


def test_missions_run_even_when_earlier_stages_used_the_whole_batch_deadline():
    body, _, _ = _run_tick(ledger_seconds=6, short_rows=[])       # 6 s > the 5 s batch budget
    assert body["processedMissionCount"] == 3, body
    assert body["result"] == "caught_up"
    assert scanner._MISSION_LOOP_MIN_SECONDS == 20


def test_fetched_short_history_becomes_durable_so_a_restart_does_not_fetch_again():
    body, fetches, durable = _run_tick(ledger_seconds=0, short_rows=ROWS)
    assert fetches == [False]                       # empty durable state: one seed fetch
    assert [row["date"] for row in durable] == [row["date"] for row in ROWS]
    assert body["ok"] is True


def test_without_the_guaranteed_minimum_the_same_tick_claims_nothing(monkeypatch):
    """The condition before the fix, kept as the discriminating case."""
    monkeypatch.setattr(scanner, "_MISSION_LOOP_MIN_SECONDS", 0)
    body, _, _ = _run_tick(ledger_seconds=6, short_rows=[])
    assert body["processedMissionCount"] == 0 and body["result"] == "partial", body
