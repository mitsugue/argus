"""Official disclosure reactions are tracked in-process (2026-10-19).

The only caller of the admin track route (ai-rejudge) became manual-only, and
590 of 600 stored disclosures stayed "classified" without any reaction."""
import inspect

import scanner


def _fresh(monkeypatch, *, started_ago=3600, last_ago=None):
    now = 100_000.0
    monkeypatch.setattr(scanner, "_INTEL_COLLECT_PROCESS_STARTED", now - started_ago)
    monkeypatch.setattr(scanner, "_OFFICIAL_TRACK_RESIDENT", {
        "lastMonotonic": None if last_ago is None else now - last_ago, "lastAt": None,
        "lastResult": None, "runs": 0})
    return now


def test_not_right_after_a_start_and_at_most_once_an_hour(monkeypatch):
    calls = []
    monkeypatch.setattr(scanner, "_official_events_track", lambda: calls.append(1) or {"status": "ok"})
    assert scanner._official_events_track_resident_tick(_fresh(monkeypatch, started_ago=300)) is None
    assert scanner._official_events_track_resident_tick(_fresh(monkeypatch, last_ago=59 * 60)) is None
    assert calls == []


def test_one_bounded_pass_records_its_counts(monkeypatch):
    now = _fresh(monkeypatch, last_ago=61 * 60)
    monkeypatch.setattr(scanner, "_official_events_track", lambda: {
        "status": "partial", "updated": 7, "processedCount": 100, "remainingCount": 490, "total": 600})
    assert scanner._official_events_track_resident_tick(now)["updated"] == 7
    state = scanner._OFFICIAL_TRACK_RESIDENT
    assert state["runs"] == 1 and state["lastMonotonic"] == now
    assert state["lastResult"] == {"status": "partial", "reason": None, "updated": 7,
                                   "processedCount": 100, "remainingCount": 490}
    assert scanner._official_events_track_resident_tick(now + 60) is None     # not again within the hour


def test_single_flight_with_the_admin_route_and_a_failure_stays_visible(monkeypatch):
    now = _fresh(monkeypatch)
    assert scanner._OFFICIAL_TRACK_LOCK.acquire(blocking=False)
    try:
        assert scanner._official_events_track_resident_tick(now) is None
    finally:
        scanner._OFFICIAL_TRACK_LOCK.release()
    def broken():
        raise RuntimeError("bars")
    monkeypatch.setattr(scanner, "_official_events_track", broken)
    assert scanner._official_events_track_resident_tick(now) is None
    assert scanner._OFFICIAL_TRACK_RESIDENT["lastResult"] == {"status": "failed", "errorClass": "RuntimeError"}
    assert scanner._OFFICIAL_TRACK_LOCK.acquire(blocking=False)           # released after the failure
    scanner._OFFICIAL_TRACK_LOCK.release()


def test_the_scheduler_starts_the_resident_tracking():
    source = inspect.getsource(scanner)
    assert 'target=_official_events_track_resident_tick' in source
    assert 'name="official-events-track"' in source
