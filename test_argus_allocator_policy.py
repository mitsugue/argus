"""Allocator policy, bounded reclaim and resident inventory (v13.7.55).

The production evidence behind this unit: 1.85 GB of free-but-unreturned
glibc arena between mission ticks (docs/ops/allocator-reclaim.md).  These
tests pin the pure decision logic, the secret-free inventory contract, and
the scanner wiring — without touching a real allocator.
"""
import inspect
import json
import time
from collections import deque
from typing import Any

import pytest

import argus_allocator_policy as policy
import argus_checkpoint_v2
import argus_memory_attribution
import scanner


# ── startup policy ───────────────────────────────────────────────────────────

def test_startup_policy_applies_fixed_thresholds_on_linux_only():
    calls = []

    def mallopt(parameter, value):
        calls.append((parameter, value))
        return 1

    report = policy.startup_policy({}, platform="linux", mallopt=mallopt)
    assert report["status"] == "APPLIED"
    assert calls == [
        (policy.M_MMAP_THRESHOLD, policy.DEFAULT_MMAP_THRESHOLD_BYTES),
        (policy.M_TRIM_THRESHOLD, policy.DEFAULT_TRIM_THRESHOLD_BYTES),
        (policy.M_ARENA_MAX, policy.DEFAULT_ARENA_MAX),
    ]
    assert report["applied"] == {
        "mmapThresholdBytes": policy.DEFAULT_MMAP_THRESHOLD_BYTES,
        "trimThresholdBytes": policy.DEFAULT_TRIM_THRESHOLD_BYTES,
        "arenaMax": policy.DEFAULT_ARENA_MAX}
    untouched = []
    darwin = policy.startup_policy(
        {}, platform="darwin", mallopt=lambda *a: untouched.append(a) or 1)
    assert darwin["status"] == "UNSUPPORTED" and untouched == []


def test_startup_policy_honours_disable_and_reports_bad_overrides():
    calls = []
    disabled = policy.startup_policy(
        {"ARGUS_MALLOC_MMAP_THRESHOLD_BYTES": "0"}, platform="linux",
        mallopt=lambda *a: calls.append(a) or 1)
    assert disabled["status"] == "DISABLED" and calls == []
    report = policy.startup_policy(
        {"ARGUS_MALLOC_ARENA_MAX": "abc",
         "ARGUS_MALLOC_TRIM_THRESHOLD_BYTES": "1"},
        platform="linux", mallopt=lambda p, v: 1)
    assert report["overrideErrors"] == {
        "ARGUS_MALLOC_ARENA_MAX": "invalid",
        "ARGUS_MALLOC_TRIM_THRESHOLD_BYTES": "out_of_range"}
    assert report["applied"]["arenaMax"] == policy.DEFAULT_ARENA_MAX
    rejected = policy.startup_policy({}, platform="linux", mallopt=lambda p, v: 0)
    assert rejected["status"] == "REJECTED" and rejected["applied"] == {}


def test_startup_policy_never_raises_without_a_native_mallopt(monkeypatch):
    import ctypes
    monkeypatch.setattr(ctypes, "CDLL", lambda *a, **k: (_ for _ in ()).throw(OSError("no libc")))
    report = policy.startup_policy({}, platform="linux")
    assert report["status"] == "UNAVAILABLE" and report["errorClass"] == "OSError"


# ── reclaim decision ─────────────────────────────────────────────────────────

def _metrics(free):
    return {"status": "AVAILABLE", "freeBytes": free, "arenaBytes": free * 2}


def test_reclaim_decision_requires_idle_process_large_balance_and_interval():
    big = policy.RECLAIM_MINIMUM_FREE_BYTES + 1
    assert policy.reclaim_decision(
        _metrics(big), now_monotonic=1000.0, last_reclaim_monotonic=None,
        mission_active=True)["reason"] == "mission_tick_active"
    assert policy.reclaim_decision(
        "UNAVAILABLE", now_monotonic=1000.0, last_reclaim_monotonic=None,
        mission_active=False)["reason"] == "allocator_metrics_unavailable"
    assert policy.reclaim_decision(
        _metrics(1024), now_monotonic=1000.0, last_reclaim_monotonic=None,
        mission_active=False)["reason"] == "free_below_floor"
    ok = policy.reclaim_decision(
        _metrics(big), now_monotonic=1000.0, last_reclaim_monotonic=None,
        mission_active=False)
    assert ok == {"reclaim": True, "reason": "free_above_floor", "freeBytes": big}
    assert policy.reclaim_decision(
        _metrics(big), now_monotonic=1100.0, last_reclaim_monotonic=1000.0,
        mission_active=False)["reason"] == "interval_not_elapsed"
    assert policy.reclaim_decision(
        _metrics(big), now_monotonic=1000.0 + policy.RECLAIM_MINIMUM_INTERVAL_SECONDS,
        last_reclaim_monotonic=1000.0, mission_active=False)["reclaim"] is True


def test_forced_reclaim_skips_the_interval_but_keeps_a_half_floor():
    half = policy.RECLAIM_MINIMUM_FREE_BYTES // 2
    forced = policy.reclaim_decision(
        _metrics(half), now_monotonic=1001.0, last_reclaim_monotonic=1000.0,
        mission_active=False, force=True)
    assert forced["reclaim"] is True and forced["reason"] == "forced"
    assert policy.reclaim_decision(
        _metrics(half - 1), now_monotonic=1001.0, last_reclaim_monotonic=1000.0,
        mission_active=False, force=True)["reason"] == "free_below_floor"
    # Forcing never overrides an active mission tick.
    assert policy.reclaim_decision(
        _metrics(half * 4), now_monotonic=1001.0, last_reclaim_monotonic=None,
        mission_active=True, force=True)["reclaim"] is False


# ── resident inventory ───────────────────────────────────────────────────────

class _Mutating(dict):
    """A dict whose iteration raises like a concurrently mutated one."""

    def items(self):
        raise RuntimeError("dictionary changed size during iteration")


def test_resident_inventory_reports_sizes_largest_first_without_values():
    named = {
        "_SMALL": {"a": 1},
        "_BIG": {"rows": [{"secret": "ZZ-sentinel-value"}] * 200},
        "_DEQUE": deque([1, 2, 3]),
        "_OBJ": {"x": object()},
        "_MUTATING": _Mutating(a=1),
    }
    report = policy.resident_inventory(named)
    assert report["schemaVersion"] == policy.INVENTORY_SCHEMA_VERSION
    assert [row["name"] for row in report["rows"]][0] == "_BIG"
    by_name = {row["name"]: row for row in report["rows"]}
    assert by_name["_BIG"]["length"] == 1 and by_name["_BIG"]["status"] == "MEASURED"
    # Every element visited: the estimate tracks the real serialized size
    # (JSON-byte units, within a few percent for string-heavy rows).
    real = len(json.dumps(named["_BIG"], ensure_ascii=False, separators=(",", ":")))
    assert abs(by_name["_BIG"]["serializedBytes"] - real) / real < 0.15
    assert by_name["_DEQUE"]["type"] == "deque"
    assert by_name["_OBJ"]["status"] == "MEASURED"          # opaque leaf counted, never copied
    assert by_name["_MUTATING"]["status"] == "CONCURRENT_MUTATION"
    for row in report["rows"]:
        assert set(row) == {"name", "type", "length", "serializedBytes", "status"}
    assert "ZZ-sentinel-value" not in json.dumps(report)
    assert report["totalSerializedBytes"] >= by_name["_BIG"]["serializedBytes"]


def test_resident_inventory_samples_long_containers_and_stays_fast():
    rows = [{"id": i, "close": 100.0 + i, "date": "2026-09-28", "note": "x" * 40}
            for i in range(50_000)]
    huge = {"_LEDGER": {"observations": rows, "imports": list(range(3_000))},
            "_TINY": [1]}
    started = time.monotonic()
    report = policy.resident_inventory(huge, sample=256)
    elapsed = time.monotonic() - started
    ledger = {r["name"]: r for r in report["rows"]}["_LEDGER"]
    real = len(json.dumps(huge["_LEDGER"], separators=(",", ":")))
    assert ledger["status"] == "ESTIMATED"
    assert abs(ledger["serializedBytes"] - real) / real < 0.10
    assert elapsed < 1.0, elapsed                     # sampling, not a full walk
    # Time budget still guards the whole walk.
    clock = iter([0.0, 0.0, 100.0, 100.0, 100.0])
    timed = policy.resident_inventory(
        {"_A": [1], "_B": [2]}, total_time_budget_seconds=1.0,
        now=lambda: next(clock))
    assert "SKIPPED_TIME" in [r["status"] for r in timed["rows"]]
    assert policy.resident_inventory({}, limit=5)["rows"] == []


def test_resident_inventory_depth_is_bounded():
    nested: Any = "leaf"
    for _ in range(40):
        nested = [nested]
    report = policy.resident_inventory({"_DEEP": nested})
    assert report["rows"][0]["status"] == "MEASURED"
    assert 0 < report["rows"][0]["serializedBytes"] < 2_000


# ── scanner wiring ───────────────────────────────────────────────────────────

@pytest.fixture
def _reclaim_state():
    saved = dict(scanner._ALLOCATOR_RECLAIM_STATE)
    scanner._ALLOCATOR_RECLAIM_STATE.update({
        "count": 0, "lastAt": None, "lastMonotonic": None,
        "lastReason": None, "lastDecision": None, "last": None})
    try:
        yield scanner._ALLOCATOR_RECLAIM_STATE
    finally:
        scanner._ALLOCATOR_RECLAIM_STATE.clear()
        scanner._ALLOCATOR_RECLAIM_STATE.update(saved)


def test_scanner_reclaim_uses_the_checkpoint_v2_helper_and_records_scalars(
        monkeypatch, _reclaim_state):
    big = policy.RECLAIM_MINIMUM_FREE_BYTES * 2
    monkeypatch.setattr(argus_memory_attribution, "allocator_metrics",
                        lambda: _metrics(big))
    calls = []

    def fake_release(source_bytes):
        calls.append(source_bytes)
        return {"attempted": True, "supported": True,
                "rssBeforeBytes": 3_000, "rssAfterBytes": 1_000,
                "rssReleasedBytes": 2_000}
    monkeypatch.setattr(argus_checkpoint_v2, "_release_unused_allocator_memory",
                        fake_release)
    monkeypatch.setitem(scanner._MISSION_TICK_CONTEXT, "active", False)
    first = scanner._allocator_reclaim("scheduler", now_monotonic=5_000.0)
    assert first["status"] == "reclaimed" and calls == [big]
    assert first["rssReleasedBytes"] == 2_000
    assert _reclaim_state["count"] == 1 and _reclaim_state["lastReason"] == "scheduler"
    assert _reclaim_state["last"]["allocatorBefore"]["freeBytes"] == big
    # Rate limited within the window; forced by the checkpoint path.
    second = scanner._allocator_reclaim("scheduler", now_monotonic=5_060.0)
    assert second == {"status": "skipped", "reclaim": False,
                      "reason": "interval_not_elapsed", "freeBytes": big}
    third = scanner._allocator_reclaim("checkpoint_persist", force=True,
                                       now_monotonic=5_061.0)
    assert third["status"] == "reclaimed" and _reclaim_state["count"] == 2
    # Never during a mission tick, even when forced.
    monkeypatch.setitem(scanner._MISSION_TICK_CONTEXT, "active", True)
    held = scanner._allocator_reclaim("mission_tick", force=True,
                                      now_monotonic=9_000.0)
    assert held["reason"] == "mission_tick_active" and len(calls) == 2


def test_scanner_reclaim_never_raises(monkeypatch, _reclaim_state):
    monkeypatch.setattr(argus_memory_attribution, "allocator_metrics",
                        lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    assert scanner._allocator_reclaim("scheduler") == {
        "status": "error", "errorClass": "RuntimeError"}
    assert _reclaim_state["lastDecision"]["errorClass"] == "RuntimeError"


def test_owner_route_carries_reclaim_scalars_and_inventory_on_request(
        monkeypatch, _reclaim_state):
    monkeypatch.setattr(scanner, "_ARGUS_ADMIN_TOKEN", "tok")
    monkeypatch.setattr(scanner, "_INVENTORY_PROBE_STORE",
                        {"row": "ZZ-inventory-sentinel"}, raising=False)
    with scanner.app.test_client() as client:
        assert client.get(
            "/api/argus/admin/memory-attribution?inventory=1").status_code == 401
        plain = client.get("/api/argus/admin/memory-attribution",
                           headers={"X-ARGUS-ADMIN-TOKEN": "tok"}).get_json()
        full = client.get("/api/argus/admin/memory-attribution?inventory=1",
                          headers={"X-ARGUS-ADMIN-TOKEN": "tok"})
    assert plain["allocatorReclaim"]["schemaVersion"] == policy.SCHEMA_VERSION
    assert "residentInventory" not in plain
    body = full.get_json()
    inventory = body["residentInventory"]
    names = [row["name"] for row in inventory["rows"]]
    assert "_INVENTORY_PROBE_STORE" in [
        row["name"] for row in policy.resident_inventory(
            scanner._resident_inventory_candidates(), limit=10_000)["rows"]]
    assert all(name.startswith("_") and name.isupper() for name in names)
    text = full.get_data(as_text=True)
    assert "ZZ-inventory-sentinel" not in text and "tok" not in text.split('"name"')[0]
    for row in inventory["rows"]:
        assert set(row) == {"name", "type", "length", "serializedBytes", "status"}


def test_inventory_candidates_are_module_containers_only():
    candidates = scanner._resident_inventory_candidates()
    for name in ("_VERIFIED_VIEW_SNAPSHOTS", "_ASSET_CHART_REPORTS",
                 "_MARKET_LEDGER", "_JQ_HISTORY_CACHE", "_DECISION_EVIDENCE_CACHE"):
        assert name in candidates
    assert "_MEMORY_ATTRIBUTION" not in candidates      # recorder object
    assert "_ARGUS_ADMIN_TOKEN" not in candidates       # scalar secret
    assert all(isinstance(v, (dict, list, tuple, set, frozenset, deque))
               for v in candidates.values())


def test_wiring_points_and_no_direct_runtime_control_calls():
    for function in (scanner._allocator_reclaim, scanner._resident_inventory,
                     scanner._resident_inventory_candidates):
        source = inspect.getsource(function)
        assert "malloc_trim(" not in source and "gc.collect(" not in source
    scheduler = inspect.getsource(scanner.run_scheduler)
    assert 'name="allocator-reclaim"' in scheduler
    assert scheduler.index("jp-owner-quote-warm") < scheduler.index("allocator-reclaim")
    entry = inspect.getsource(scanner._run_backend_server)
    assert "argus_allocator_policy.startup_policy()" in entry
    assert entry.index("startup_policy()") < entry.index("_startup_bootstrap()")
    persist = inspect.getsource(scanner._osint_persist)
    assert '_allocator_reclaim("checkpoint_persist", force=True)' in persist
    tick = inspect.getsource(scanner.api_argus_admin_missions_tick)
    assert tick.index("_DURABLE_CHECKPOINT_LOCK.release()") < \
        tick.index('_allocator_reclaim("mission_tick", force=True)')
