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


def test_a_second_heavy_tick_is_skipped_while_one_runs(monkeypatch):
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
        "jp_owner_quote_warm",
        lambda: ran.append("second") or {"status": "ok"})
    assert second == {"status": "skipped", "reason": "heavy_tick_busy",
                      "running": "residency_ai_tick"}
    release.set()
    thread.join(5)
    assert ran == ["slow"]
    assert scanner._HEAVY_TICK_STATE["ranCount"] == 1
    assert scanner._HEAVY_TICK_STATE["skippedCount"] == 1
    assert scanner._HEAVY_TICK_STATE["skippedByName"] == {"jp_owner_quote_warm": 1}
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
    assert scanner._heavy_tick("jp_owner_quote_warm", lambda: "ok") == "ok"


def test_heavy_ticks_are_measured_exactly_as_before(monkeypatch):
    monkeypatch.setitem(scanner._MISSION_TICK_CONTEXT, "active", False)
    seen = []
    monkeypatch.setattr(scanner, "_memory_operation_run",
                        lambda kind, name, fn, *a, **k: seen.append((kind, name)) or fn())
    scanner._heavy_tick("residency_ai_tick", lambda: "ok")
    assert seen == [("scheduler", "residency_ai_tick")]


def test_scheduler_routes_every_heavy_tick_through_the_slot():
    source = inspect.getsource(scanner.run_scheduler)
    for name in ("residency_ai_tick", "jp_owner_quote_warm",
                 "market_brief_worker_tick", "jp_sector_heatmap_tick"):
        assert f'"{name}"' in source, name
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
