"""Process-resident collection cadence (2026-10-19): the 30-minute collection starts in-process."""
import time

import scanner


def _fresh(monkeypatch, *, started_ago, last_ago=None, running=False):
    now = 100_000.0
    monkeypatch.setattr(scanner, "_INTEL_COLLECT_PROCESS_STARTED", now - started_ago)
    monkeypatch.setattr(scanner, "_INTEL_COLLECT_RUN", {"status": "running", "runId": "x"} if running else {})
    monkeypatch.setattr(scanner, "_INTEL_COLLECT_LAST", {
        "finishedMonotonic": None if last_ago is None else now - last_ago, "finishedAt": None,
        "status": None, "trigger": None, "residentStarted": 0})
    return now


def test_not_during_the_first_ten_minutes_after_a_start(monkeypatch):
    now = _fresh(monkeypatch, started_ago=300)
    assert scanner._intel_collect_resident_tick(now) is None


def test_not_while_a_collection_runs_or_within_thirty_minutes(monkeypatch):
    now = _fresh(monkeypatch, started_ago=3600, running=True)
    assert scanner._intel_collect_resident_tick(now) is None
    now = _fresh(monkeypatch, started_ago=3600, last_ago=29 * 60)
    assert scanner._intel_collect_resident_tick(now) is None


def test_starts_one_tracked_collection_when_due_and_records_its_end(monkeypatch):
    now = _fresh(monkeypatch, started_ago=3600, last_ago=31 * 60)
    calls = []
    monkeypatch.setattr(scanner, "_collect_institutional_intel_and_warm", lambda: calls.append(1) or {"ok": True})
    assert scanner._intel_collect_resident_tick(now) is True
    for _ in range(100):
        if scanner._INTEL_COLLECT_RUN.get("status") != "running":
            break
        time.sleep(0.02)
    assert calls == [1] and scanner._INTEL_COLLECT_RUN["status"] == "done"
    assert scanner._INTEL_COLLECT_LAST["trigger"] == "resident" and scanner._INTEL_COLLECT_LAST["residentStarted"] == 1
    assert scanner._INTEL_COLLECT_RUN["runId"].startswith("resident-")
    # Just finished: the next tick waits another 30 minutes.
    assert scanner._intel_collect_resident_tick(time.monotonic()) is None


def test_an_external_request_also_counts_as_the_last_collection(monkeypatch):
    _fresh(monkeypatch, started_ago=3600, last_ago=None)
    monkeypatch.setattr(scanner, "_collect_institutional_intel_and_warm", lambda: {"ok": True})
    scanner._intel_collect_tracked("external-run-1")
    for _ in range(100):
        if scanner._INTEL_COLLECT_RUN.get("status") != "running":
            break
        time.sleep(0.02)
    assert scanner._INTEL_COLLECT_LAST["trigger"] == "request"
    assert scanner._intel_collect_resident_tick(time.monotonic()) is None


def test_the_scheduler_starts_the_resident_tick():
    source = open("scanner.py", encoding="utf-8").read()
    assert 'target=_intel_collect_resident_tick, daemon=True, name="intel-collect-resident"' in source
