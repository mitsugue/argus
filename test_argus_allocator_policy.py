"""Allocator policy, bounded reclaim and resident inventory (v13.7.55).

The production evidence behind this unit: 1.85 GB of free-but-unreturned
glibc arena between mission ticks (docs/ops/allocator-reclaim.md).  These
tests pin the pure decision logic, the secret-free inventory contract, and
the scanner wiring — without touching a real allocator.
"""
import inspect
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
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


@pytest.fixture
def _backend_allocator_entry(monkeypatch):
    backend = str(Path(policy.__file__).with_name("scanner.py"))
    monkeypatch.setattr(sys.modules["__main__"], "__file__", backend, raising=False)
    monkeypatch.setattr(sys, "argv", [backend])
    monkeypatch.setattr(sys, "orig_argv", [sys.executable, "-B", "-u", backend])
    monkeypatch.setattr(policy, "python_allocator_name", lambda: "pymalloc")
    monkeypatch.delenv("PYTHONMALLOC", raising=False)
    return backend


def test_backend_allocator_observation_preserves_interpreter_args_and_environment(monkeypatch, _backend_allocator_entry):
    before = dict(os.environ)
    args, original_args = list(sys.argv), list(sys.orig_argv)
    monkeypatch.setattr(os, "execve", lambda *args: (_ for _ in ()).throw(AssertionError("must not exec")))
    assert policy._backend_allocator_observation() == {
        "status": "ALLOCATOR_PRESERVED", "allocatorName": "pymalloc"}
    assert dict(os.environ) == before
    assert sys.argv == args and sys.orig_argv == original_args


@pytest.mark.parametrize("configured", ["malloc", "pymalloc", "malloc_debug", "default"])
def test_backend_allocator_honours_explicit_allocator(monkeypatch, _backend_allocator_entry, configured):
    monkeypatch.setenv("PYTHONMALLOC", configured)
    monkeypatch.setattr(os, "execve", lambda *args: (_ for _ in ()).throw(AssertionError("must not exec")))
    assert policy._backend_allocator_observation()["status"] == "EXPLICIT_ALLOCATOR"


def test_backend_allocator_does_not_change_workers_imports_or_disabled_policy(monkeypatch, _backend_allocator_entry):
    monkeypatch.setattr(os, "execve", lambda *args: (_ for _ in ()).throw(AssertionError("must not exec")))
    with monkeypatch.context() as change:
        change.setattr(sys, "argv", [_backend_allocator_entry, "--worker"])
        assert policy._backend_allocator_observation()["status"] == "NOT_BACKEND_SERVER"
    with monkeypatch.context() as change:
        change.setattr(sys.modules["__main__"], "__file__", __file__)
        assert policy._backend_allocator_observation()["status"] == "NOT_BACKEND_SERVER"
    with monkeypatch.context() as change:
        change.setenv("ARGUS_MALLOC_MMAP_THRESHOLD_BYTES", "0")
        change.setattr(policy, "_backend_allocator_observation", lambda: (_ for _ in ()).throw(AssertionError("disabled")))
        assert policy.startup_policy()["status"] == "DISABLED"


def test_backend_allocator_repeated_observations_never_exec_or_expose_environment(monkeypatch, _backend_allocator_entry):
    calls = []
    def denied(*args):
        calls.append(True)
        raise PermissionError("private-exec-sentinel")
    monkeypatch.setattr(os, "execve", denied)
    first = policy._backend_allocator_observation()
    assert first == {"status": "ALLOCATOR_PRESERVED", "allocatorName": "pymalloc"}
    assert policy._backend_allocator_observation() == first
    assert calls == [] and "private-exec-sentinel" not in json.dumps(first)


@pytest.mark.parametrize("allocator,args,flags,expected_entries,expected_mode", [
    (None, [], [], 1, "pymalloc"),
    ("pymalloc", [], [], 1, "pymalloc"),
    ("malloc", [], [], 1, "malloc"),
    (None, ["--worker"], [], 1, "pymalloc"),
    (None, [], ["-E"], 1, "pymalloc"),
    (None, [], ["-X", "dev"], 1, "pymalloc_debug"),
])
def test_real_backend_allocator_keeps_interpreter_and_preserves_pid_flags_and_credentials(
        tmp_path, allocator, args, flags, expected_entries, expected_mode):
    if sys.platform != "linux" or sys.implementation.name != "cpython" or sys.version_info[:2] != (3, 12):
        pytest.skip("backend repair applies to Linux CPython3.12")
    shutil.copyfile(policy.__file__, tmp_path / "argus_allocator_policy.py")
    program = tmp_path / "scanner.py"
    program.write_text('''import json, os, sys
import argus_allocator_policy as policy
def _backend_exact_sha():
    return "a" * 40
def _semantic_app_version():
    return "1.2.3"
with open(os.environ["ALLOCATOR_TEST_TRACE"], "a") as stream:
    stream.write(json.dumps({"pid": os.getpid(), "allocator": policy.python_allocator_name()}) + "\\n")
report = policy.startup_policy()
print(json.dumps({"allocator": policy.python_allocator_name(), "bytecodeDisabled": sys.dont_write_bytecode,
    "unbuffered": sys.stdout.write_through, "credentialPreserved": os.environ.get("ALLOCATOR_TEST_CREDENTIAL") == "fixture-only",
    "restoreWouldStartNow": True, "bootstrap": report.get("pythonAllocator"),
    "buildSha": report.get("backendBuildSha"), "version": report.get("backendVersion")}))
''')
    env = dict(os.environ)
    env.pop("PYTHONMALLOC", None)
    env.pop("ARGUS_MALLOC_MMAP_THRESHOLD_BYTES", None)
    if allocator:
        env["PYTHONMALLOC"] = allocator
    env["ALLOCATOR_TEST_TRACE"] = str(tmp_path / "trace.jsonl")
    env["ALLOCATOR_TEST_CREDENTIAL"] = "fixture-only"
    result = subprocess.run([sys.executable, *flags, "-B", "-u", str(program), *args], env=env,
                            text=True, capture_output=True, check=True, timeout=15)
    output = json.loads(result.stdout)
    entries = [json.loads(line) for line in (tmp_path / "trace.jsonl").read_text().splitlines()]
    assert len(entries) == expected_entries
    assert len({entry["pid"] for entry in entries}) == 1
    assert output["allocator"] == expected_mode
    assert output["bytecodeDisabled"] and output["unbuffered"] and output["credentialPreserved"]
    assert output["restoreWouldStartNow"] is True
    if not args:
        assert output["buildSha"] == "a" * 40 and output["version"] == "1.2.3"
    else:
        assert output["buildSha"] is None and output["version"] is None
    assert "fixture-only" not in result.stdout


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

def test_builtin_graph_counts_shared_and_cyclic_objects_once_without_values():
    secret = "private-graph-sentinel-" * 5
    shared = [secret, 37.25]
    first = [shared, shared]
    first.append(first)
    second = [shared]
    graph = policy.retained_builtin_graph({"_A": first, "_B": second}, ["_A", "_B"])
    expected = sum(map(sys.getsizeof, (first, second, shared, secret, shared[1])))
    assert graph["uniqueVisitedShallowBytes"] == expected
    assert graph["uniqueObjectCount"] == 5
    assert graph["rows"][0]["sharedReferenceCount"] == 2
    assert graph["rows"][1]["newlyVisitedShallowBytes"] == sys.getsizeof(second)
    assert graph["wholeHeapMeasured"] is False
    assert secret not in json.dumps(graph)
    assert first[0] is first[1] is second[0] and first[-1] is first


def test_builtin_graph_never_calls_custom_hooks():
    class Trap(list):
        def __iter__(self):
            raise AssertionError("custom iteration")

        def __sizeof__(self):
            raise AssertionError("custom size")

        def __repr__(self):
            raise AssertionError("custom repr")
    graph = policy.retained_builtin_graph({"_A": [Trap()]}, ["_A"])
    assert graph["uniqueObjectCount"] == 1
    assert graph["rows"][0]["status"] == "OPAQUE_REFERENCES"
    assert graph["rows"][0]["opaqueReferenceCount"] == 1


@pytest.mark.parametrize("budget,value,status", [
    ("HEAP_ROOT_OBJECT_LIMIT", 3, "ROOT_OBJECT_LIMIT"),
    ("HEAP_OBJECT_LIMIT", 3, "OBJECT_LIMIT"),
    ("HEAP_EDGE_LIMIT", 3, "EDGE_LIMIT"),
    ("HEAP_DEPTH_LIMIT", 2, "DEPTH_LIMIT"),
])
def test_builtin_graph_budget_is_explicit_incomplete_evidence(monkeypatch, budget, value, status):
    monkeypatch.setattr(policy, budget, value)
    graph = policy.retained_builtin_graph({"_A": [[list(range(100))]]}, ["_A"])
    assert graph["rows"][0]["status"] == status
    assert graph["uniqueObjectCount"] <= policy.HEAP_OBJECT_LIMIT
    assert graph["visitedEdges"] <= policy.HEAP_EDGE_LIMIT
    assert graph["wholeHeapMeasured"] is False


def test_builtin_graph_time_budget_stops_before_visiting():
    clock = iter([0.0, 3.0, 4.0])
    graph = policy.retained_builtin_graph({"_A": [1]}, ["_A"], now=lambda: next(clock))
    assert graph["uniqueObjectCount"] == 0
    assert graph["rows"][0]["status"] == "TIME_LIMIT"


def test_builtin_graph_concurrent_dict_mutation_is_incomplete():
    root = {"key": []}
    calls = 0

    def clock():
        nonlocal calls
        calls += 1
        if calls == 4:
            root["added"] = []
        return 0.0
    graph = policy.retained_builtin_graph({"_A": root}, ["_A"], now=clock)
    assert graph["rows"][0]["status"] == "CONCURRENT_MUTATION"
    assert graph["currentHeapLowerBoundProved"] is False


def test_memory_coverage_preserves_native_mmaps_and_actual_cgroup_events(monkeypatch):
    memory = {"cgroup": {"memoryCurrentBytes": 100, "memoryMaxBytes": 2 * 1024**3,
                          "events": {"oom_kill": 2}},
              "allocatorMetrics": {"allocatedBytes": 7, "mmapBytes": 900}}
    monkeypatch.setattr(argus_memory_attribution, "memory_snapshot", lambda: memory)
    result = policy.resident_memory_coverage({"_A": [1]}, [{"name": "_A", "serializedBytes": 3}])
    assert result["before"] == result["after"] == memory
    assert result["builtinGraph"]["uniqueObjectCount"] == 2
    assert result["productionResourceAccepted"] is False


@pytest.mark.parametrize("current,maximum,running,reason", [
    (10, "max", False, "SKIPPED_UNKNOWN_MEMORY_LIMIT"),
    ("UNKNOWN", 1000, False, "SKIPPED_UNKNOWN_MEMORY_LIMIT"),
    (1000, 1001, False, "SKIPPED_LOW_HEADROOM"),
    (100, 2 * 1024**3, True, "SKIPPED_ACTIVE_WORK"),
])
def test_memory_coverage_skips_unsafe_graph_work(monkeypatch, current, maximum, running, reason):
    monkeypatch.setattr(argus_memory_attribution, "memory_snapshot", lambda: {
        "cgroup": {"memoryCurrentBytes": current, "memoryMaxBytes": maximum}})
    monkeypatch.setattr(policy, "retained_builtin_graph",
                        lambda *a: (_ for _ in ()).throw(AssertionError("must not walk")))
    result = policy.resident_memory_coverage({"_INTEL_COLLECT_RUN": {
        "status": "running" if running else "done"}}, [])
    assert result["builtinGraph"]["status"] == reason


def test_memory_coverage_concurrent_walk_is_skipped(monkeypatch):
    monkeypatch.setattr(argus_memory_attribution, "memory_snapshot", lambda: {
        "cgroup": {"memoryCurrentBytes": 0, "memoryMaxBytes": 2 * 1024**3}})
    with policy._HEAP_OBSERVATION_LOCK:
        assert policy.resident_memory_coverage({}, [])["builtinGraph"] == {"status": "SKIPPED_BUSY"}


def _synthetic_python_allocator_stats():
    rows = ["Small block threshold = 512, in 32 size classes."]
    for index in range(32):
        counts = "1 100 155" if index == 3 else "0 0 0"
        rows.append(f"{index} {(index + 1) * 16} {counts}")
    rows.extend([
        "# arenas allocated total = 3", "# arenas reclaimed = 2",
        "# arenas highwater mark = 3", "# arenas allocated current = 1",
        "1 arenas * 1048576 bytes/arena = 1,048,576",
        "# bytes in allocated blocks = 6,400",
        "# bytes in available blocks = 9,920",
        "63 unused pools * 16384 bytes = 1,032,192",
        "# bytes lost to pool headers = 48",
        "# bytes lost to quantization = 16",
        "# bytes lost to arena alignment = 0",
    ])
    return "\n".join(rows) + "\n"


def test_python_allocator_admits_consistent_class_and_arena_totals_only():
    result = policy._parse_python_allocator_stats(_synthetic_python_allocator_stats())
    assert result["allocatedSmallBlockBytes"] == 6400
    assert result["availableSmallBlockBytes"] == 9920
    assert result["unusedPoolBytes"] == 1032192
    assert result["arenaBytesCurrent"] == 1048576
    assert result["arenasCurrent"] == 1 and result["arenasReclaimed"] == 2
    assert len(result["sizeClasses"]) == 32
    assert result["scope"] == "cpython_pymalloc_reservations_not_rss"


@pytest.mark.parametrize("old,new", [
    ("# bytes in allocated blocks = 6,400", "# bytes in allocated blocks = 6,401"),
    ("# bytes lost to arena alignment = 0", "# bytes lost to arena alignment = 1"),
    ("# arenas allocated current = 1", "# arenas allocated current = 2"),
    ("# arenas allocated total = 3", "# arenas allocated total = 4"),
    ("63 unused pools", "62 unused pools"),
    ("1048576 bytes/arena", "2097152 bytes/arena"),
    ("31 512 0 0 0", "30 512 0 0 0"),
    ("31 512 0 0 0\n", ""),
    ("# arenas reclaimed = 2", "# arenas reclaimed = 2\n# arenas reclaimed = 2"),
])
def test_python_allocator_rejects_incomplete_duplicate_or_inconsistent_stats(old, new):
    with pytest.raises(ValueError):
        policy._parse_python_allocator_stats(_synthetic_python_allocator_stats().replace(old, new))


def test_python_allocator_unavailable_never_exposes_text_or_exception(monkeypatch):
    monkeypatch.setattr(policy, "_python_allocator_stats_text", lambda: "private-native-sentinel")
    result = policy.python_allocator_metrics()
    assert result["status"] == "UNAVAILABLE"
    assert "arenaBytesCurrent" not in result
    assert "private-native-sentinel" not in json.dumps(result)
    monkeypatch.setattr(policy, "_python_allocator_stats_text",
                        lambda: (_ for _ in ()).throw(OSError("private-native-sentinel")))
    assert policy.python_allocator_metrics()["status"] == "UNAVAILABLE"


@pytest.mark.parametrize("allocator", ["pymalloc", "malloc"])
def test_python_allocator_native_reader_leaves_descriptors_and_stderr_unchanged(allocator):
    import ctypes
    if (sys.implementation.name != "cpython" or sys.version_info[:2] != (3, 12)
            or not sys.platform.startswith("linux") or ctypes.sizeof(ctypes.c_void_p) != 8):
        pytest.skip("native reader deliberately restricted to Linux CPython 3.12 64-bit")
    # Other scanner tests leave background work in a suite worker. Observe
    # the reader's own persistent resources in a fresh process, keeping every
    # FD/stderr assertion and checking both native allocator modes explicitly.
    program = """
import os
import argus_allocator_policy as policy
allocator_name = policy.python_allocator_name()
assert allocator_name in {"pymalloc", "pymalloc_debug", "malloc", "malloc_debug"}
expected_status = "AVAILABLE" if allocator_name.startswith("pymalloc") else "UNAVAILABLE"
assert policy.python_allocator_metrics()["status"] == expected_status
before = len(os.listdir("/proc/self/fd"))
stderr_before = os.fstat(2)
for _ in range(8):
    result = policy.python_allocator_metrics()
    assert result["status"] == expected_status
    assert result["allocatorName"] == allocator_name
    if expected_status == "AVAILABLE":
        assert result["arenasHighwater"] >= result["arenasCurrent"]
    else:
        assert "arenaBytesCurrent" not in result
assert len(os.listdir("/proc/self/fd")) == before
stderr_after = os.fstat(2)
assert (stderr_before.st_dev, stderr_before.st_ino) == (stderr_after.st_dev, stderr_after.st_ino)
"""
    env = dict(os.environ)
    env["PYTHONMALLOC"] = allocator
    result = subprocess.run([sys.executable, "-B", "-c", program],
                            cwd=str(Path(policy.__file__).parent), env=env,
                            capture_output=True, text=True, check=True, timeout=15)
    assert result.stdout == result.stderr == ""


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
