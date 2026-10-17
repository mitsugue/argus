"""One heavy background tick at a time (v13.7.59).

2026-09-28 production attribution (run 36449052354): every run of every heavy
operation overlapped another — residency_ai_tick 446 MiB, jp_owner_quote_warm
415 MiB, missions/tick 326 MiB, zero exclusive runs, 58 instrumented
operations active at the maximum — so the process peak is their sum rather
than the largest one. These ticks are self-throttled and idempotent, so
skipping a slot is free and overlapping is what costs the peak.
"""
import inspect
import threading
import time

import pytest

import scanner


@pytest.fixture(autouse=True)
def _reset_heavy_tick_state():
    saved = dict(scanner._HEAVY_TICK_STATE)
    scanner._HEAVY_TICK_STATE.clear()
    scanner._HEAVY_TICK_STATE.update({
        "running": None, "startedAt": None, "ranCount": 0,
        "skippedCount": 0, "lastSkipped": None, "skippedByName": {}})
    try:
        yield
    finally:
        scanner._HEAVY_TICK_STATE.clear()
        scanner._HEAVY_TICK_STATE.update(saved)
        if scanner._HEAVY_TICK_LOCK.locked():       # pragma: no cover - safety
            scanner._HEAVY_TICK_LOCK.release()


def test_a_five_minute_tick_waits_for_the_slot_instead_of_starving(monkeypatch):
    """The JP owner warm is spawned beside the AI tick every five minutes.

    Losing that race must not cost it the whole window: it keeps the owner's
    Watchlist prices current, so it waits for the slot.
    """
    monkeypatch.setitem(scanner._MISSION_TICK_CONTEXT, "active", False)
    monkeypatch.setitem(scanner._HEAVY_TICK_WAIT_SECONDS, "jp_owner_quote_warm", 5.0)
    order = []
    entered = threading.Event()

    def first():
        entered.set()
        time.sleep(0.3)
        order.append("ai")

    thread = threading.Thread(
        target=scanner._heavy_tick, args=("residency_ai_tick", first))
    thread.start()
    assert entered.wait(5)
    scanner._heavy_tick("jp_owner_quote_warm", lambda: order.append("warm"))
    thread.join(5)
    assert order == ["ai", "warm"]
    assert scanner._HEAVY_TICK_STATE["ranCount"] == 2
    assert scanner._HEAVY_TICK_STATE["skippedCount"] == 0


def test_a_waiting_tick_yields_to_a_mission_tick_that_started_meanwhile(monkeypatch):
    monkeypatch.setitem(scanner._MISSION_TICK_CONTEXT, "active", False)
    monkeypatch.setitem(scanner._HEAVY_TICK_WAIT_SECONDS, "jp_owner_quote_warm", 5.0)
    entered = threading.Event()
    ran = []

    def first():
        entered.set()
        time.sleep(0.3)
        scanner._MISSION_TICK_CONTEXT["active"] = True

    thread = threading.Thread(
        target=scanner._heavy_tick, args=("residency_ai_tick", first))
    thread.start()
    assert entered.wait(5)
    result = scanner._heavy_tick("jp_owner_quote_warm", lambda: ran.append("warm"))
    thread.join(5)
    assert result == {"status": "skipped", "reason": "mission_tick_active"}
    assert ran == []
    assert scanner._HEAVY_TICK_LOCK.locked() is False


def test_a_thirty_second_tick_is_skipped_while_one_runs(monkeypatch):
    monkeypatch.setitem(scanner._MISSION_TICK_CONTEXT, "active", False)
    entered = threading.Event()
    release = threading.Event()
    ran = []

    def slow():
        entered.set()
        assert release.wait(5)
        ran.append("slow")
        return {"status": "ok"}

    thread = threading.Thread(
        target=scanner._heavy_tick, args=("residency_ai_tick", slow))
    thread.start()
    assert entered.wait(5)
    # The lock is held: the second tick reports the holder and does no work.
    second = scanner._heavy_tick(
        "nikkei_close_refresh",
        lambda: ran.append("second") or {"status": "ok"})
    assert second == {"status": "skipped", "reason": "heavy_tick_busy",
                      "running": "residency_ai_tick"}
    release.set()
    thread.join(5)
    assert ran == ["slow"]
    assert scanner._HEAVY_TICK_STATE["ranCount"] == 1
    assert scanner._HEAVY_TICK_STATE["skippedCount"] == 1
    assert scanner._HEAVY_TICK_STATE["skippedByName"] == {"nikkei_close_refresh": 1}
    assert scanner._HEAVY_TICK_STATE["running"] is None
    assert scanner._HEAVY_TICK_LOCK.locked() is False


def test_no_heavy_tick_runs_while_a_mission_tick_owns_the_process(monkeypatch):
    monkeypatch.setitem(scanner._MISSION_TICK_CONTEXT, "active", True)
    ran = []
    result = scanner._heavy_tick("residency_ai_tick", lambda: ran.append("x"))
    assert result == {"status": "skipped", "reason": "mission_tick_active"}
    assert ran == []
    assert scanner._HEAVY_TICK_STATE["lastSkipped"]["reason"] == "mission_tick_active"
    assert scanner._HEAVY_TICK_LOCK.locked() is False


def test_the_slot_is_released_when_a_tick_raises(monkeypatch):
    monkeypatch.setitem(scanner._MISSION_TICK_CONTEXT, "active", False)

    def boom():
        raise RuntimeError("tick failed")

    with pytest.raises(RuntimeError):
        scanner._heavy_tick("residency_ai_tick", boom)
    assert scanner._HEAVY_TICK_LOCK.locked() is False
    assert scanner._HEAVY_TICK_STATE["running"] is None
    # The next tick still gets the slot.
    assert scanner._heavy_tick("market_brief_worker_tick", lambda: "ok") == "ok"


def test_heavy_ticks_are_measured_exactly_as_before(monkeypatch):
    monkeypatch.setitem(scanner._MISSION_TICK_CONTEXT, "active", False)
    seen = []
    monkeypatch.setattr(scanner, "_memory_operation_run",
                        lambda kind, name, fn, *a, **k: seen.append((kind, name)) or fn())
    scanner._heavy_tick("residency_ai_tick", lambda: "ok")
    assert seen == [("scheduler", "residency_ai_tick")]


def test_waiting_ticks_and_their_bounds():
    assert set(scanner._HEAVY_TICK_WAIT_SECONDS) == {
        "residency_ai_tick", "jp_owner_quote_warm",
        "market_brief_worker_tick", "jp_sector_heatmap_tick"}
    assert all(0 < value <= 300 for value in scanner._HEAVY_TICK_WAIT_SECONDS.values())
    # Thirty-second ticks wait less than their spawn period: no waiter piles up.
    for name in ("market_brief_worker_tick", "jp_sector_heatmap_tick"):
        assert scanner._HEAVY_TICK_WAIT_SECONDS[name] < 30
    assert "nikkei_close_refresh" not in scanner._HEAVY_TICK_WAIT_SECONDS


def test_the_brief_worker_is_not_starved_by_a_short_tick_spawned_first(monkeypatch):
    """2026-10-15 production: 206 of 206 brief attempts lost the race.

    The tick spawned first held the slot for a few milliseconds, the brief
    worker spawned right after found it busy and skipped, every thirty seconds.
    """
    monkeypatch.setitem(scanner._MISSION_TICK_CONTEXT, "active", False)
    monkeypatch.setitem(scanner._HEAVY_TICK_WAIT_SECONDS, "market_brief_worker_tick", 2.0)
    monkeypatch.setitem(scanner._HEAVY_TICK_WAIT_SECONDS, "jp_sector_heatmap_tick", 2.0)
    order = []
    entered = threading.Event()

    def short():
        entered.set()
        time.sleep(0.05)
        order.append("first")

    thread = threading.Thread(target=scanner._heavy_tick, args=("residency_ai_tick", short))
    thread.start()
    assert entered.wait(5)
    sector = threading.Thread(target=scanner._heavy_tick,
                              args=("jp_sector_heatmap_tick", lambda: order.append("sector")))
    sector.start()
    scanner._heavy_tick("market_brief_worker_tick", lambda: order.append("brief"))
    thread.join(5); sector.join(5)
    assert sorted(order[1:]) == ["brief", "sector"] and order[0] == "first"
    assert scanner._HEAVY_TICK_STATE["skippedCount"] == 0
    assert scanner._HEAVY_TICK_STATE["ranCount"] == 3


def test_a_waiting_thirty_second_tick_still_skips_behind_a_long_holder(monkeypatch):
    monkeypatch.setitem(scanner._MISSION_TICK_CONTEXT, "active", False)
    monkeypatch.setitem(scanner._HEAVY_TICK_WAIT_SECONDS, "market_brief_worker_tick", 0.1)
    entered = threading.Event(); release = threading.Event(); ran = []

    def slow():
        entered.set(); assert release.wait(5)

    thread = threading.Thread(target=scanner._heavy_tick, args=("residency_ai_tick", slow))
    thread.start()
    assert entered.wait(5)
    result = scanner._heavy_tick("market_brief_worker_tick", lambda: ran.append("brief"))
    release.set(); thread.join(5)
    assert result["reason"] == "heavy_tick_busy" and ran == []
    assert scanner._HEAVY_TICK_LOCK.locked() is False


def test_the_close_refresh_takes_the_slot_only_when_due(monkeypatch):
    monkeypatch.setitem(scanner._MISSION_TICK_CONTEXT, "active", False)
    monkeypatch.setattr(scanner, "_nikkei_close_refresh_plan", lambda: None)
    monkeypatch.setattr(scanner, "_heavy_tick",
                        lambda *a, **k: pytest.fail("a not-due check must not take the slot"))
    assert scanner._nikkei_close_refresh_dispatch() == {"status": "not_due"}
    taken = []
    monkeypatch.setattr(scanner, "_nikkei_close_refresh_plan", lambda: {"slot": "x"})
    monkeypatch.setattr(scanner, "_heavy_tick", lambda name, fn: taken.append((name, fn)) or "ran")
    assert scanner._nikkei_close_refresh_dispatch() == "ran"
    assert taken == [("nikkei_close_refresh", scanner._nikkei_close_refresh_tick)]


def test_scheduler_routes_every_heavy_tick_through_the_slot():
    source = inspect.getsource(scanner.run_scheduler)
    for name in ("residency_ai_tick", "jp_owner_quote_warm",
                 "market_brief_worker_tick", "jp_sector_heatmap_tick"):
        assert f'"{name}"' in source, name
    # The close refresh checks its slot first, then takes the heavy slot.
    assert "target=_nikkei_close_refresh_dispatch" in source
    assert "_nikkei_close_refresh_tick" not in source
    # No heavy tick is spawned directly any more.
    for direct in ("target=_residency_ai_tick", "target=_jp_owner_quote_warm_tick",
                   "target=_market_brief_worker_tick", "target=_jp_sector_heatmap_tick"):
        assert direct not in source, direct
    # Web push and the owner overview stay outside the slot: they are small
    # and time sensitive.
    assert "target=_web_push_tick" in source
    assert "target=_owner_overview_tick" in source


def test_owner_diagnostics_expose_the_heavy_tick_counters(monkeypatch):
    monkeypatch.setattr(scanner, "_ARGUS_ADMIN_TOKEN", "tok")
    with scanner.app.test_client() as client:
        body = client.get("/api/argus/admin/memory-attribution",
                          headers={"X-ARGUS-ADMIN-TOKEN": "tok"}).get_json()
    assert set(body["heavyTicks"]) == {
        "running", "startedAt", "ranCount", "skippedCount", "lastSkipped",
        "skippedByName"}


def test_mission_phase_seconds_are_kept_between_the_existing_boundaries(monkeypatch):
    """2026-10-16 (remaining item 2): the mission tick took 383-455 s; the M1-M17
    boundaries keep the seconds since the previous one (IDs and seconds only)."""
    monkeypatch.setattr(scanner, "_ARGUS_ADMIN_TOKEN", "tok")
    monkeypatch.setitem(scanner._MISSION_PHASE_TIMING, "phases", {})
    monkeypatch.setattr(scanner, "_mission_tick_context_active", lambda: True)
    clock = iter([100.0, 101.5, 104.0, 104.25])
    monkeypatch.setattr(scanner.time, "monotonic", lambda: next(clock))
    scanner._mission_phase_timing_start()
    scanner._memory_attribution_path_capture("M1", "window_history_and_begin_complete")
    scanner._memory_attribution_path_capture("M2", "calendar_complete")
    scanner._memory_attribution_path_capture("M2", "calendar_complete")
    phases = scanner._MISSION_PHASE_TIMING["phases"]
    assert phases["M1"] == {"lastSeconds": 1.5, "maxSeconds": 1.5, "count": 1}
    assert phases["M2"] == {"lastSeconds": 0.25, "maxSeconds": 2.5, "count": 2}
    monkeypatch.setattr(scanner.time, "monotonic", lambda: 200.0)
    with scanner.app.test_client() as client:
        body = client.get("/api/argus/admin/memory-attribution",
                          headers={"X-ARGUS-ADMIN-TOKEN": "tok"}).get_json()
    assert body["missionPhaseSeconds"]["M2"]["maxSeconds"] == 2.5
    assert set(body["missionPhaseSeconds"]["M1"]) == {"lastSeconds", "maxSeconds", "count"}


def test_phase_seconds_are_not_kept_outside_a_mission_tick(monkeypatch):
    monkeypatch.setitem(scanner._MISSION_PHASE_TIMING, "phases", {})
    monkeypatch.setitem(scanner._MISSION_PHASE_TIMING, "last", None)
    scanner._memory_attribution_path_capture("M1", "window_history_and_begin_complete")
    assert scanner._MISSION_PHASE_TIMING["phases"] == {}



def test_a_save_outside_the_mission_tick_is_not_a_mission_phase(monkeypatch):
    """The checkpoint boundary M21 is crossed by every save; outside the
    mission tick the gap since the last tick must not become a phase."""
    monkeypatch.setitem(scanner._MISSION_PHASE_TIMING, "phases", {})
    monkeypatch.setitem(scanner._MISSION_PHASE_TIMING, "last", 1.0)
    monkeypatch.setattr(scanner, "_mission_tick_context_active", lambda: False)
    scanner._memory_attribution_path_capture("M21", "checkpoint_lock_acquired")
    assert scanner._MISSION_PHASE_TIMING["phases"] == {}


def test_checkpoint_saves_keep_wait_save_and_caller(monkeypatch):
    monkeypatch.setattr(scanner, "_ARGUS_ADMIN_TOKEN", "tok")
    stats = {"count": 0, "waitSeconds": 0.0, "saveSeconds": 0.0, "maxWaitSeconds": 0.0,
             "maxSaveSeconds": 0.0, "lastSaveSeconds": None, "callers": {}}
    monkeypatch.setattr(scanner, "_CHECKPOINT_PERSIST_STATS", stats)
    monkeypatch.setattr(scanner, "_osint_persist_locked", lambda: {"verified": True})
    monkeypatch.setattr(scanner, "_recovery_phase_a_finalize_checkpoint", lambda result: None)
    monkeypatch.setattr(scanner, "_allocator_reclaim", lambda *a, **k: None)
    monkeypatch.setattr(scanner, "_detach_market_stores", lambda *a, **k: None)

    def a_named_caller():
        return scanner._osint_persist()

    assert a_named_caller() == {"verified": True}
    assert stats["count"] == 1 and stats["lastSaveSeconds"] is not None
    assert stats["callers"] == {"a_named_caller": {"count": 1, "saveSeconds": stats["saveSeconds"]}}
    for index in range(30):
        scanner._checkpoint_persist_record(f"caller_{index}", 0.5, 2.0)
    assert len(stats["callers"]) == 20 and stats["count"] == 31
    assert stats["maxWaitSeconds"] == 0.5 and stats["maxSaveSeconds"] >= 2.0
    with scanner.app.test_client() as client:
        body = client.get("/api/argus/admin/memory-attribution",
                          headers={"X-ARGUS-ADMIN-TOKEN": "tok"}).get_json()
    assert body["checkpointPersist"]["count"] == 31
