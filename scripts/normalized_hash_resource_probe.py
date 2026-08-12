#!/usr/bin/env python3
"""Fresh-process resource proof for normalized-state hashing.

This probe is local/CI only.  It creates deterministic production-shaped
stores, never contacts a provider or service, and exercises no durability or
runtime-control path.  The supervisor starts one fresh process per store/path
pair so the fallback and normalized fast path do not share allocator history,
plus two asset-only allocation-trace processes that cannot perturb the four
OS-resource workers.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import pathlib
import platform
import resource
import subprocess
import sys
import time
from datetime import date, timedelta
from typing import Any, Callable, Dict, Iterable, Mapping


ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import argus_asset_chart_cache as asset_cache
import argus_memory_attribution as memory
import argus_verified_snapshot as verified_snapshot


MIB = 1024 * 1024
GIB = 1024 * MIB
MINIMUM_CYCLES = 32
PLATEAU_LIMIT_BYTES = 128 * MIB
LOGICAL_ACCEPTANCE_CEILING_BYTES = 3 * GIB
MINIMUM_MATERIAL_RSS_REDUCTION_BYTES = 1 * MIB
# Asset hashes eliminate one transient whole-state representation.  The
# allocator is free to release or retain that representation after the call,
# so its deterministic effect is the allocation high-water *during* the call,
# not the post-call RSS retained by glibc.  Keep the exact same materiality
# threshold; this is a measurement correction, not a relaxed gate.
MINIMUM_MATERIAL_ALLOCATION_REDUCTION_BYTES = \
    MINIMUM_MATERIAL_RSS_REDUCTION_BYTES
# Calibrated against the single authorized v13.4.11 production baseline:
# verified canonical/UTF-8 ~= 27.0/27.4 million bytes and asset ~=
# 14.9/15.2 million bytes.
# A shared 750-row fixture serialized to only ~2.2 MiB for either store and
# therefore was not production-shaped.  Keep the module-specific sizes
# explicit because the two durable stores have intentionally asymmetric
# schemas and hash material.
DEFAULT_VERIFIED_BARS_PER_RECORD = 9140
DEFAULT_ASSET_BARS_PER_RECORD = 5024
MINIMUM_PRODUCTION_CANONICAL_BYTES = {
    "verified": 27_000_000,
    "asset": 14_850_000,
}
MAXIMUM_CALIBRATION_OVERSHOOT_PERCENT = 1.0
STORE_KINDS = ("verified", "asset")
PATH_MODES = ("fallback", "normalized")
STEADY_STATE_METRICS = (
    "processRssBytes", "rssAnonBytes", "pssBytes", "arenaBytes",
    "uordblksBytes", "fordblksBytes",
)


def _integer(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) \
        else None


def _metric(value: Any) -> int | str:
    parsed = _integer(value)
    return parsed if parsed is not None else memory.UNKNOWN


def _difference(before: Any, after: Any) -> int | str:
    left = _integer(before)
    right = _integer(after)
    return right - left if left is not None and right is not None \
        else memory.UNKNOWN


def _maximum(values: Iterable[Any]) -> int | str:
    parsed = [value for value in values if _integer(value) is not None]
    return max(parsed) if parsed else memory.UNKNOWN


def _span(values: Iterable[Any]) -> int | str:
    parsed = [value for value in values if _integer(value) is not None]
    return max(parsed) - min(parsed) if parsed else memory.UNKNOWN


def _percentile(values: Iterable[float], percentile: float) -> float:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return 0.0
    index = max(0, min(
        len(ordered) - 1,
        int(math.ceil((percentile / 100.0) * len(ordered))) - 1,
    ))
    return round(ordered[index], 3)


def _integer_percentile(
        values: Iterable[Any], percentile: float) -> int | str:
    ordered = sorted(
        value for value in values if _integer(value) is not None)
    if not ordered:
        return memory.UNKNOWN
    index = max(0, min(
        len(ordered) - 1,
        int(math.ceil((percentile / 100.0) * len(ordered))) - 1,
    ))
    return ordered[index]


def _reduction(fallback: Any, candidate: Any) -> int | str:
    left = _integer(fallback)
    right = _integer(candidate)
    return left - right if left is not None and right is not None \
        else memory.UNKNOWN


def _steady_state_summary(
        baseline: Mapping[str, Any], rows: Iterable[Mapping[str, Any]],
        ) -> Dict[str, Any]:
    samples = list(rows)
    after_p50 = {
        metric: _integer_percentile(
            ((row.get("after") or {}).get(metric) for row in samples), 50)
        for metric in STEADY_STATE_METRICS
    }
    growth = {
        metric: _difference(baseline.get(metric), after_p50.get(metric))
        for metric in STEADY_STATE_METRICS
    }
    return {
        "sampleDefinition": "cycles_3_plus_after_nearest_rank_p50",
        "sampleCount": len(samples),
        "afterP50Bytes": after_p50,
        "growthFromBaselineBytes": growth,
    }


def _paired_steady_state_reduction(
        fallback_memory: Mapping[str, Any],
        candidate_memory: Mapping[str, Any], metric: str) -> int | str:
    fallback_baseline = fallback_memory.get("baseline") or {}
    candidate_baseline = candidate_memory.get("baseline") or {}
    fallback_rows = list(fallback_memory.get("cycles") or [])[2:]
    candidate_rows = list(candidate_memory.get("cycles") or [])[2:]
    if not fallback_rows or len(fallback_rows) != len(candidate_rows):
        return memory.UNKNOWN
    reductions = []
    for expected_cycle, (fallback_row, candidate_row) in enumerate(
            zip(fallback_rows, candidate_rows), start=3):
        if (
                fallback_row.get("cycle") != expected_cycle or
                candidate_row.get("cycle") != expected_cycle):
            return memory.UNKNOWN
        fallback_growth = _difference(
            fallback_baseline.get(metric),
            (fallback_row.get("after") or {}).get(metric))
        candidate_growth = _difference(
            candidate_baseline.get(metric),
            (candidate_row.get("after") or {}).get(metric))
        reduction = _reduction(fallback_growth, candidate_growth)
        if _integer(reduction) is None:
            return memory.UNKNOWN
        reductions.append(reduction)
    return _integer_percentile(reductions, 50)


def _paired_allocation_peak_reduction_summary(
        fallback_worker: Mapping[str, Any],
        candidate_worker: Mapping[str, Any]) -> Dict[str, Any]:
    unknown = {
        "sampleDefinition":
            "paired_cycles_3_plus_peak_increment_reduction",
        "sampleCount": 0,
        "minimum": memory.UNKNOWN,
        "p50": memory.UNKNOWN,
        "p95": memory.UNKNOWN,
        "maximum": memory.UNKNOWN,
        "span": memory.UNKNOWN,
    }
    fallback_rows = list(
        (fallback_worker.get("allocationTrace") or {}).get("cycles") or [])[2:]
    candidate_rows = list(
        (candidate_worker.get("allocationTrace") or {}).get("cycles") or [])[2:]
    if not fallback_rows or len(fallback_rows) != len(candidate_rows):
        return unknown
    reductions = []
    for expected_cycle, (fallback_row, candidate_row) in enumerate(
            zip(fallback_rows, candidate_rows), start=3):
        if (
                fallback_row.get("cycle") != expected_cycle or
                candidate_row.get("cycle") != expected_cycle):
            return unknown
        reduction = _reduction(
            fallback_row.get("peakIncrementBytes"),
            candidate_row.get("peakIncrementBytes"))
        if _integer(reduction) is None:
            return unknown
        reductions.append(reduction)
    return {
        "sampleDefinition":
            "paired_cycles_3_plus_peak_increment_reduction",
        "sampleCount": len(reductions),
        "minimum": min(reductions),
        "p50": _integer_percentile(reductions, 50),
        "p95": _integer_percentile(reductions, 95),
        "maximum": max(reductions),
        "span": _span(reductions),
    }


def _environment_fingerprint() -> Dict[str, Any]:
    libc_name, libc_version = platform.libc_ver()
    return {
        "pythonImplementation": platform.python_implementation(),
        "pythonVersion": platform.python_version(),
        "pythonBuild": sys.version.replace("\n", " "),
        "libcName": libc_name or memory.UNKNOWN,
        "libcVersion": libc_version or memory.UNKNOWN,
        "system": platform.system(),
        "machine": platform.machine(),
        "kernelRelease": platform.release(),
        "runnerImageOs": os.environ.get(
            "ARGUS_PROBE_RUNNER_IMAGE_OS", memory.UNKNOWN),
        "runnerImageVersion": os.environ.get(
            "ARGUS_PROBE_RUNNER_IMAGE_VERSION", memory.UNKNOWN),
        "containerImage": os.environ.get(
            "ARGUS_PROBE_CONTAINER_IMAGE", memory.UNKNOWN),
        "sourceHeadSha": os.environ.get(
            "ARGUS_PROBE_HEAD_SHA", memory.UNKNOWN),
        "executionSha": os.environ.get(
            "ARGUS_PROBE_EXECUTION_SHA", memory.UNKNOWN),
    }


def _peak_rss_bytes() -> int | str:
    try:
        peak = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        return peak if sys.platform == "darwin" else peak * 1024
    except (OSError, TypeError, ValueError, OverflowError):
        return memory.UNKNOWN


def _memory_events() -> Dict[str, int | str]:
    path = pathlib.Path("/sys/fs/cgroup/memory.events")
    output: Dict[str, int | str] = {
        "oom": memory.UNKNOWN,
        "oomKill": memory.UNKNOWN,
    }
    try:
        raw = path.read_text(encoding="utf-8")
    except (FileNotFoundError, PermissionError, OSError, UnicodeError):
        return output
    values: Dict[str, int] = {}
    for line in raw.splitlines():
        fields = line.split()
        if len(fields) != 2:
            continue
        try:
            values[fields[0]] = int(fields[1])
        except (TypeError, ValueError, OverflowError):
            continue
    output["oom"] = values.get("oom", memory.UNKNOWN)
    output["oomKill"] = values.get("oom_kill", memory.UNKNOWN)
    return output


def _snapshot() -> Dict[str, Any]:
    sample = memory.memory_snapshot(None)
    process = sample.get("process") if isinstance(sample, Mapping) else {}
    smaps = sample.get("smapsRollup") if isinstance(sample, Mapping) else {}
    allocator = sample.get("allocatorMetrics") \
        if isinstance(sample, Mapping) else {}
    cgroup = sample.get("cgroup") if isinstance(sample, Mapping) else {}
    if not isinstance(process, Mapping):
        process = {}
    if not isinstance(smaps, Mapping):
        smaps = {}
    if not isinstance(allocator, Mapping):
        allocator = {}
    if not isinstance(cgroup, Mapping):
        cgroup = {}
    return {
        "processRssBytes": _metric(process.get("vmRssBytes")),
        "processPeakRssBytes": _peak_rss_bytes(),
        "rssAnonBytes": _metric(process.get("rssAnonBytes")),
        "pssBytes": _metric(smaps.get("pssBytes")),
        "arenaBytes": _metric(allocator.get("arenaBytes")),
        "uordblksBytes": _metric(allocator.get("allocatedBytes")),
        "fordblksBytes": _metric(allocator.get("freeBytes")),
        "topReleasableBytes": _metric(
            allocator.get("topReleasableBytes")),
        "cgroupCurrentBytes": _metric(cgroup.get("memoryCurrentBytes")),
        "cgroupPeakBytes": _metric(cgroup.get("memoryPeakBytes")),
        "cgroupMaxBytes": cgroup.get("memoryMaxBytes", memory.UNKNOWN),
    }


def _bar_rows(count: int, seed: int) -> list[Dict[str, Any]]:
    start = date(2022, 1, 1)
    return [{
        "date": (start + timedelta(days=index)).isoformat(),
        "open": round(100.0 + seed + index / 100.0, 4),
        "high": round(101.0 + seed + index / 100.0, 4),
        "low": round(99.0 + seed + index / 100.0, 4),
        "close": round(100.5 + seed + index / 100.0, 4),
        "volume": seed * 100_000 + index,
        "availableFrom": (start + timedelta(days=index + 1)).isoformat(),
    } for index in range(count)]


def _verified_store(
        bars_per_record: int =
        DEFAULT_VERIFIED_BARS_PER_RECORD) -> Dict[str, Any]:
    store = verified_snapshot.empty_store()
    for index in range(verified_snapshot.MAX_CURRENT):
        label = f"LOCAL{index:02d}"
        dataset = f"dataset-{index:02d}"
        payload = {
            "schemaVersion": "chart-intelligence-phase2-v1",
            "methodVersion": "chart-intelligence-phase2-v1",
            "asOf": "2026-08-10T00:00:00Z",
            "symbol": label,
            "status": "complete",
            "source": "local-resource-proof",
            "automaticAiCalls": 0,
            "indicators": {
                "status": "complete",
                "bars": _bar_rows(bars_per_record, index),
            },
        }
        item = verified_snapshot.build_snapshot(
            payload=payload, kind="market-chart", instrument=label,
            horizon="5D", dataset_hash=dataset,
            method_version="resource-proof-v1",
            as_of="2026-08-10T00:00:00Z",
            generated_at="2026-08-10T00:01:00Z", quality="live",
            source_status={"chart": "complete"},
        )
        key = verified_snapshot.snapshot_key(
            "market-chart", label, "5D")
        store["current"][key] = item
    store["history"] = [{
        "key": f"history-{index:02d}",
        "snapshotId": f"local-history-{index:02d}",
        "replacedAt": "2026-08-09T00:00:00Z",
    } for index in range(verified_snapshot.MAX_HISTORY)]
    store["lastPublishedAt"] = "2026-08-10T00:01:00Z"
    return store


def _asset_store(
        bars_per_record: int =
        DEFAULT_ASSET_BARS_PER_RECORD) -> Dict[str, Any]:
    store = asset_cache.empty_store()
    for index in range(asset_cache.MAX_RECORDS):
        market = "JP" if index % 2 == 0 else "US"
        label = f"LOCAL{index:02d}"
        identity = asset_cache.identity_key(market, label, "daily")
        logical = f"{identity}:dataset-{index:02d}:resource-proof-v1"
        payload = {
            "schemaVersion": "chart-intelligence-phase2-v1",
            "methodVersion": "chart-intelligence-phase2-v1",
            "reportId": f"local-report-{index:02d}",
            "symbol": label,
            "market": market,
            "status": "complete",
            "periodEnd": "2026-08-10",
            "indicators": {
                "status": "complete",
                "bars": _bar_rows(bars_per_record, index),
            },
        }
        store["records"][logical] = {
            "schemaVersion": asset_cache.SCHEMA_VERSION,
            "logicalKey": logical,
            "identityKey": identity,
            "market": market,
            "symbol": label,
            "timeframe": "daily",
            "datasetHash": f"dataset-{index:02d}",
            "methodVersion": "resource-proof-v1",
            "publishedAt": "2026-08-10T00:01:00Z",
            "periodEnd": "2026-08-10",
            "payloadHash": asset_cache._hash(payload),
            "payload": payload,
        }
        store["current"][identity] = logical
    store["lastUpdatedAt"] = "2026-08-10T00:01:00Z"
    return store


def _module_and_store(
        store_kind: str, bars_per_record: int,
        ) -> tuple[Any, Dict[str, Any], Dict[str, int]]:
    if store_kind == "verified":
        module = verified_snapshot
        raw = _verified_store(bars_per_record)
        shape = {
            "currentCount": verified_snapshot.MAX_CURRENT,
            "historyCount": verified_snapshot.MAX_HISTORY,
            "recordCount": verified_snapshot.MAX_CURRENT,
            "barsPerRecord": bars_per_record,
        }
    elif store_kind == "asset":
        module = asset_cache
        raw = _asset_store(bars_per_record)
        shape = {
            "currentCount": asset_cache.MAX_RECORDS,
            "historyCount": 0,
            "recordCount": asset_cache.MAX_RECORDS,
            "barsPerRecord": bars_per_record,
        }
    else:
        raise ValueError("unsupported_store_kind")
    return module, module.normalize_store(raw), shape


def _worker(
        store_kind: str, mode: str, cycles: int,
        bars_per_record: int) -> Dict[str, Any]:
    cycles = max(MINIMUM_CYCLES, int(cycles))
    module, normalized, shape = _module_and_store(
        store_kind, bars_per_record)
    state_hash_normalized = getattr(module, "state_hash_normalized", None)
    if mode == "normalized" and not callable(state_hash_normalized):
        raise RuntimeError("normalized_hash_api_missing")
    hash_callback: Callable[[Any], str] = (
        state_hash_normalized if mode == "normalized" else module.state_hash)

    normalize_calls = 0
    original_normalize = module.normalize_store

    def counted_normalize(value: Any) -> Dict[str, Any]:
        nonlocal normalize_calls
        normalize_calls += 1
        return original_normalize(value)

    module.normalize_store = counted_normalize
    canonical_byte_counts: set[int] = set()
    canonical_character_counts: set[int] = set()

    def hash_observer(phase: str, metadata: Dict[str, Any]) -> None:
        if phase == "canonical_string_ready":
            value = _integer(metadata.get("canonicalCharacterCount"))
            if value is not None:
                canonical_character_counts.add(value)
        elif phase == "utf8_bytes_ready":
            value = _integer(metadata.get("canonicalByteCount"))
            if value is not None:
                canonical_byte_counts.add(value)

    events_before = _memory_events()
    baseline = _snapshot()
    rows = []
    digests = []
    try:
        for index in range(cycles):
            before = _snapshot()
            started = time.perf_counter_ns()
            digest = hash_callback(
                normalized, diagnostic_observer=hash_observer)
            duration_ms = (time.perf_counter_ns() - started) / 1_000_000.0
            after = _snapshot()
            digests.append(str(digest))
            rows.append({
                "cycle": index + 1,
                "durationMs": round(duration_ms, 3),
                "before": before,
                "after": after,
                "delta": {
                    key: _difference(before.get(key), after.get(key))
                    for key in (
                        "processRssBytes", "rssAnonBytes", "pssBytes",
                        "arenaBytes", "uordblksBytes", "fordblksBytes",
                        "topReleasableBytes", "cgroupCurrentBytes")
                },
            })
    finally:
        module.normalize_store = original_normalize
    final = _snapshot()
    events_after = _memory_events()
    durations = [row["durationMs"] for row in rows]
    steady = rows[2:] if len(rows) > 2 else rows
    rss_values = [row["after"]["processRssBytes"] for row in steady]
    pss_values = [row["after"]["pssBytes"] for row in steady]
    steady_state = _steady_state_summary(baseline, steady)
    conservative_peak = _maximum([
        baseline.get("processPeakRssBytes"),
        final.get("processPeakRssBytes"),
        *(row["after"].get("processRssBytes") for row in rows),
        *(row["after"].get("pssBytes") for row in rows),
        *(row["after"].get("cgroupCurrentBytes") for row in rows),
        *(row["after"].get("cgroupPeakBytes") for row in rows),
    ])
    oom_delta = _difference(events_before.get("oom"), events_after.get("oom"))
    oom_kill_delta = _difference(
        events_before.get("oomKill"), events_after.get("oomKill"))
    cgroup_observed = _integer(final.get("cgroupMaxBytes")) is not None
    normalized_fast = mode == "normalized" and normalize_calls == 0
    fallback_observed = mode == "fallback" and normalize_calls == cycles
    rss_plateau = _span(rss_values)
    pss_plateau = _span(pss_values)
    plateau_ok = all(
        value == memory.UNKNOWN or value < PLATEAU_LIMIT_BYTES
        for value in (rss_plateau, pss_plateau))
    logical_peak_ok = (
        conservative_peak == memory.UNKNOWN or
        conservative_peak < LOGICAL_ACCEPTANCE_CEILING_BYTES)
    canonical_bytes = (
        next(iter(canonical_byte_counts))
        if len(canonical_byte_counts) == 1 else memory.UNKNOWN)
    canonical_characters = (
        next(iter(canonical_character_counts))
        if len(canonical_character_counts) == 1 else memory.UNKNOWN)
    minimum_canonical_bytes = MINIMUM_PRODUCTION_CANONICAL_BYTES[store_kind]
    maximum_canonical_bytes = math.floor(
        minimum_canonical_bytes *
        (1.0 + MAXIMUM_CALIBRATION_OVERSHOOT_PERCENT / 100.0))
    calibrated_input = (
        _integer(canonical_bytes) is not None and
        minimum_canonical_bytes <= canonical_bytes <= maximum_canonical_bytes)
    shape.update({
        "canonicalCharacterCount": canonical_characters,
        "canonicalHashInputBytes": canonical_bytes,
        "minimumProductionCanonicalBytes": minimum_canonical_bytes,
        "maximumCalibratedCanonicalBytes": maximum_canonical_bytes,
    })
    checks = {
        "cyclesAtLeast32": len(rows) >= MINIMUM_CYCLES,
        "digestStable100Percent": len(set(digests)) == 1,
        "expectedPathObserved": normalized_fast or fallback_observed,
        "allocationTracerNotLoaded": "tracemalloc" not in sys.modules,
        "plateauBelow128MiB": plateau_ok,
        "logicalPeakBelow3GiB": logical_peak_ok,
        "productionCalibratedCanonicalInput": calibrated_input,
        "oomDeltaZero": (
            oom_delta == 0 if cgroup_observed
            else oom_delta in (0, memory.UNKNOWN)),
        "oomKillDeltaZero": (
            oom_kill_delta == 0 if cgroup_observed
            else oom_kill_delta in (0, memory.UNKNOWN)),
    }
    return {
        "schemaVersion": "argus-normalized-hash-worker-v2",
        "measurementProfile": "os_resource_uninstrumented",
        "freshProcess": True,
        "processId": os.getpid(),
        "environment": _environment_fingerprint(),
        "storeKind": store_kind,
        "pathMode": mode,
        "pathClassification": (
            "NORMALIZED_FAST_PATH" if mode == "normalized"
            else "NORMALIZING_FALLBACK"),
        "cycles": cycles,
        "storeShape": shape,
        "normalizeCallsDuringCycles": normalize_calls,
        "wholeStateRepresentationsPerCall": 1 if normalized_fast else 2,
        "digest": digests[-1] if digests else None,
        "digestStableCount": sum(
            value == digests[0] for value in digests) if digests else 0,
        "durationMs": {
            "total": round(sum(durations), 3),
            "minimum": round(min(durations), 3) if durations else 0,
            "p50": _percentile(durations, 50),
            "p95": _percentile(durations, 95),
            "maximum": round(max(durations), 3) if durations else 0,
        },
        "memory": {
            "baseline": baseline,
            "final": final,
            "rssPlateauSpanBytesCycles3Plus": rss_plateau,
            "pssPlateauSpanBytesCycles3Plus": pss_plateau,
            "steadyState": steady_state,
            "conservativePeakBytes": conservative_peak,
            "plateauLimitBytes": PLATEAU_LIMIT_BYTES,
            "logicalAcceptanceCeilingBytes":
                LOGICAL_ACCEPTANCE_CEILING_BYTES,
            "cgroupEventsBefore": events_before,
            "cgroupEventsAfter": events_after,
            "oomDelta": oom_delta,
            "oomKillDelta": oom_kill_delta,
            "cycles": rows,
        },
        "runtimeActions": {
            "allocatorTrimInvoked": False,
            "forcedCollectionInvoked": False,
            "restartInvoked": False,
        },
        "checks": checks,
        "passed": all(checks.values()),
    }


def _allocation_worker(
        store_kind: str, mode: str, cycles: int,
        bars_per_record: int) -> Dict[str, Any]:
    if store_kind != "asset":
        raise ValueError("allocation_trace_is_asset_only")
    cycles = max(MINIMUM_CYCLES, int(cycles))
    module, normalized, shape = _module_and_store(
        store_kind, bars_per_record)
    # Lazy import is deliberate: the four OS-resource workers never import or
    # initialize the tracer, preserving their startup/address-layout profile.
    import tracemalloc as allocation_tracer
    state_hash_normalized = getattr(module, "state_hash_normalized", None)
    if mode == "normalized" and not callable(state_hash_normalized):
        raise RuntimeError("normalized_hash_api_missing")
    hash_callback: Callable[[Any], str] = (
        state_hash_normalized if mode == "normalized" else module.state_hash)

    normalize_calls = 0
    original_normalize = module.normalize_store

    def counted_normalize(value: Any) -> Dict[str, Any]:
        nonlocal normalize_calls
        normalize_calls += 1
        return original_normalize(value)

    module.normalize_store = counted_normalize
    canonical_byte_counts: set[int] = set()
    canonical_character_counts: set[int] = set()

    def hash_observer(phase: str, metadata: Dict[str, Any]) -> None:
        if phase == "canonical_string_ready":
            value = _integer(metadata.get("canonicalCharacterCount"))
            if value is not None:
                canonical_character_counts.add(value)
        elif phase == "utf8_bytes_ready":
            value = _integer(metadata.get("canonicalByteCount"))
            if value is not None:
                canonical_byte_counts.add(value)

    events_before = _memory_events()
    baseline = _snapshot()
    rows = []
    digests = []
    tracing_started_fresh = not allocation_tracer.is_tracing()
    if not tracing_started_fresh:
        module.normalize_store = original_normalize
        raise RuntimeError("unexpected_active_allocation_tracer")
    allocation_tracer.start(1)
    try:
        for index in range(cycles):
            # reset_peak() makes the current traced allocation the local high
            # water, so subtracting current_before isolates this hash call's
            # transient allocation peak without depending on glibc retention.
            allocation_tracer.reset_peak()
            current_before, _ = allocation_tracer.get_traced_memory()
            started = time.perf_counter_ns()
            digest = hash_callback(
                normalized, diagnostic_observer=hash_observer)
            duration_ms = (time.perf_counter_ns() - started) / 1_000_000.0
            current_after, peak_after = allocation_tracer.get_traced_memory()
            digests.append(str(digest))
            rows.append({
                "cycle": index + 1,
                "durationMs": round(duration_ms, 3),
                "currentBeforeBytes": current_before,
                "currentAfterBytes": current_after,
                "currentDeltaBytes": current_after - current_before,
                "peakBytes": peak_after,
                "peakIncrementBytes": peak_after - current_before,
            })
    finally:
        module.normalize_store = original_normalize
        allocation_tracer.stop()
    tracing_stopped = not allocation_tracer.is_tracing()
    final = _snapshot()
    events_after = _memory_events()

    durations = [row["durationMs"] for row in rows]
    steady = rows[2:] if len(rows) > 2 else rows
    peak_increments = [row["peakIncrementBytes"] for row in steady]
    current_deltas = [row["currentDeltaBytes"] for row in steady]
    conservative_peak = _maximum([
        baseline.get("processPeakRssBytes"),
        final.get("processPeakRssBytes"),
        baseline.get("cgroupCurrentBytes"),
        final.get("cgroupCurrentBytes"),
        baseline.get("cgroupPeakBytes"),
        final.get("cgroupPeakBytes"),
    ])
    oom_delta = _difference(events_before.get("oom"), events_after.get("oom"))
    oom_kill_delta = _difference(
        events_before.get("oomKill"), events_after.get("oomKill"))
    cgroup_observed = _integer(final.get("cgroupMaxBytes")) is not None
    normalized_fast = mode == "normalized" and normalize_calls == 0
    fallback_observed = mode == "fallback" and normalize_calls == cycles
    logical_peak_ok = (
        conservative_peak == memory.UNKNOWN or
        conservative_peak < LOGICAL_ACCEPTANCE_CEILING_BYTES)
    canonical_bytes = (
        next(iter(canonical_byte_counts))
        if len(canonical_byte_counts) == 1 else memory.UNKNOWN)
    canonical_characters = (
        next(iter(canonical_character_counts))
        if len(canonical_character_counts) == 1 else memory.UNKNOWN)
    minimum_canonical_bytes = MINIMUM_PRODUCTION_CANONICAL_BYTES[store_kind]
    maximum_canonical_bytes = math.floor(
        minimum_canonical_bytes *
        (1.0 + MAXIMUM_CALIBRATION_OVERSHOOT_PERCENT / 100.0))
    calibrated_input = (
        _integer(canonical_bytes) is not None and
        minimum_canonical_bytes <= canonical_bytes <= maximum_canonical_bytes)
    shape.update({
        "canonicalCharacterCount": canonical_characters,
        "canonicalHashInputBytes": canonical_bytes,
        "minimumProductionCanonicalBytes": minimum_canonical_bytes,
        "maximumCalibratedCanonicalBytes": maximum_canonical_bytes,
    })
    allocation_samples_complete = (
        len(rows) == cycles and
        all(
            row.get("cycle") == expected_cycle and
            _integer(row.get("currentBeforeBytes")) is not None and
            _integer(row.get("currentAfterBytes")) is not None and
            _integer(row.get("currentDeltaBytes")) is not None and
            _integer(row.get("peakBytes")) is not None and
            _integer(row.get("peakIncrementBytes")) is not None and
            row.get("peakIncrementBytes") >= 0
            for expected_cycle, row in enumerate(rows, start=1)))
    checks = {
        "cyclesAtLeast32": len(rows) >= MINIMUM_CYCLES,
        "digestStable100Percent": len(set(digests)) == 1,
        "expectedPathObserved": normalized_fast or fallback_observed,
        "allocationTraceStartedFresh": tracing_started_fresh,
        "allocationTraceStopped": tracing_stopped,
        "allocationTraceSamplesComplete": allocation_samples_complete,
        "logicalPeakBelow3GiB": logical_peak_ok,
        "productionCalibratedCanonicalInput": calibrated_input,
        "oomDeltaZero": (
            oom_delta == 0 if cgroup_observed
            else oom_delta in (0, memory.UNKNOWN)),
        "oomKillDeltaZero": (
            oom_kill_delta == 0 if cgroup_observed
            else oom_kill_delta in (0, memory.UNKNOWN)),
    }
    return {
        "schemaVersion": "argus-normalized-hash-allocation-worker-v1",
        "measurementProfile": "python_allocation_peak",
        "freshProcess": True,
        "processId": os.getpid(),
        "environment": _environment_fingerprint(),
        "storeKind": store_kind,
        "pathMode": mode,
        "pathClassification": (
            "NORMALIZED_FAST_PATH" if mode == "normalized"
            else "NORMALIZING_FALLBACK"),
        "cycles": cycles,
        "storeShape": shape,
        "normalizeCallsDuringCycles": normalize_calls,
        "wholeStateRepresentationsPerCall": 1 if normalized_fast else 2,
        "digest": digests[-1] if digests else None,
        "digestStableCount": sum(
            value == digests[0] for value in digests) if digests else 0,
        "durationMs": {
            "total": round(sum(durations), 3),
            "minimum": round(min(durations), 3) if durations else 0,
            "p50": _percentile(durations, 50),
            "p95": _percentile(durations, 95),
            "maximum": round(max(durations), 3) if durations else 0,
        },
        "allocationTrace": {
            "tracer": "python_tracemalloc",
            "tracebackFrames": 1,
            "sampleDefinition":
                "cycles_3_plus_per_call_peak_increment_nearest_rank_p50",
            "sampleCount": len(steady),
            "peakIncrementBytes": {
                "minimum": min(peak_increments) if peak_increments else 0,
                "p50": _integer_percentile(peak_increments, 50),
                "p95": _integer_percentile(peak_increments, 95),
                "maximum": max(peak_increments) if peak_increments else 0,
                "span": _span(peak_increments),
            },
            "currentDeltaBytes": {
                "minimum": min(current_deltas) if current_deltas else 0,
                "p50": _integer_percentile(current_deltas, 50),
                "p95": _integer_percentile(current_deltas, 95),
                "maximum": max(current_deltas) if current_deltas else 0,
                "span": _span(current_deltas),
            },
            "cycles": rows,
        },
        "memory": {
            "baseline": baseline,
            "final": final,
            "conservativePeakBytes": conservative_peak,
            "logicalAcceptanceCeilingBytes":
                LOGICAL_ACCEPTANCE_CEILING_BYTES,
            "cgroupEventsBefore": events_before,
            "cgroupEventsAfter": events_after,
            "oomDelta": oom_delta,
            "oomKillDelta": oom_kill_delta,
        },
        "runtimeActions": {
            "allocatorTrimInvoked": False,
            "forcedCollectionInvoked": False,
            "restartInvoked": False,
        },
        "checks": checks,
        "passed": all(checks.values()),
    }


def _worker_command(
        store_kind: str, mode: str, cycles: int,
        bars_per_record: int, measurement_profile: str = "resource",
        ) -> list[str]:
    command = [
        sys.executable, "-B", str(pathlib.Path(__file__).resolve()),
        "--worker-store", store_kind, "--worker-mode", mode,
        "--worker-profile", measurement_profile,
        "--cycles", str(cycles),
        "--bars-per-record", str(bars_per_record),
    ]
    return command


def _run_worker(
        store_kind: str, mode: str, cycles: int,
        bars_per_record: int,
        measurement_profile: str = "resource") -> Dict[str, Any]:
    environment = dict(os.environ)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PYTHONHASHSEED"] = "0"
    try:
        completed = subprocess.run(
            _worker_command(
                store_kind, mode, cycles, bars_per_record,
                measurement_profile),
            cwd=str(ROOT), env=environment, capture_output=True, text=True,
            timeout=900, check=False)
    except subprocess.TimeoutExpired:
        return {
            "storeKind": store_kind, "pathMode": mode,
            "measurementProfile": measurement_profile,
            "returnCode": None, "signal": None,
            "timedOut": True, "outputValid": False,
            "stderrPresent": False, "passed": False,
        }
    try:
        report = json.loads(completed.stdout)
        output_valid = isinstance(report, dict)
    except (TypeError, ValueError, json.JSONDecodeError):
        report = {}
        output_valid = False
    report.update({
        "returnCode": completed.returncode,
        "signal": -completed.returncode if completed.returncode < 0 else None,
        "timedOut": False,
        "outputValid": output_valid,
        "stderrPresent": bool(completed.stderr.strip()),
        "abnormalExit": completed.returncode != 0,
    })
    report["passed"] = bool(
        report.get("passed") and output_valid and completed.returncode == 0)
    return report


def run(
        cycles: int = MINIMUM_CYCLES, *,
        verified_bars_per_record: int =
        DEFAULT_VERIFIED_BARS_PER_RECORD,
        asset_bars_per_record: int = DEFAULT_ASSET_BARS_PER_RECORD,
        require_cgroup_max_bytes: int = 0) -> Dict[str, Any]:
    cycles = max(MINIMUM_CYCLES, int(cycles))
    started = time.monotonic()
    bars_by_store = {
        "verified": max(1, int(verified_bars_per_record)),
        "asset": max(1, int(asset_bars_per_record)),
    }
    resource_workers = [
        _run_worker(
            store_kind, mode, cycles, bars_by_store[store_kind])
        for store_kind in STORE_KINDS for mode in PATH_MODES
    ]
    allocation_workers = [
        _run_worker(
            "asset", mode, cycles, bars_by_store["asset"],
            "allocation_peak")
        for mode in PATH_MODES
    ]
    workers = resource_workers + allocation_workers
    by_key = {
        (row.get("storeKind"), row.get("pathMode")): row
        for row in resource_workers
    }
    allocation_by_mode = {
        row.get("pathMode"): row for row in allocation_workers
    }
    comparisons = []
    digest_matches = 0
    expected_comparisons = cycles * (len(STORE_KINDS) + 1)
    representation_reduction = []
    process_peak_reductions = []
    steady_rss_reductions = []
    steady_pss_reductions = []
    steady_anon_reductions = []
    duration_p50_reductions = []
    for store_kind in STORE_KINDS:
        fallback = by_key.get((store_kind, "fallback"), {})
        candidate = by_key.get((store_kind, "normalized"), {})
        digest_equal = bool(
            fallback.get("digest") and
            fallback.get("digest") == candidate.get("digest"))
        matches = cycles if digest_equal else 0
        digest_matches += matches
        fallback_representations = fallback.get(
            "wholeStateRepresentationsPerCall")
        candidate_representations = candidate.get(
            "wholeStateRepresentationsPerCall")
        reduction = (
            fallback_representations - candidate_representations
            if _integer(fallback_representations) is not None and
            _integer(candidate_representations) is not None else
            memory.UNKNOWN)
        representation_reduction.append(reduction)
        fallback_memory = fallback.get("memory") or {}
        candidate_memory = candidate.get("memory") or {}
        fallback_final = fallback_memory.get("final") or {}
        candidate_final = candidate_memory.get("final") or {}
        fallback_process_peak = fallback_final.get("processPeakRssBytes")
        candidate_process_peak = candidate_final.get("processPeakRssBytes")
        process_peak_reduction = (
            fallback_process_peak - candidate_process_peak
            if _integer(fallback_process_peak) is not None and
            _integer(candidate_process_peak) is not None else
            memory.UNKNOWN)
        process_peak_reductions.append(process_peak_reduction)
        fallback_growth = (
            fallback_memory.get("steadyState") or {}).get(
                "growthFromBaselineBytes") or {}
        candidate_growth = (
            candidate_memory.get("steadyState") or {}).get(
                "growthFromBaselineBytes") or {}
        steady_reductions = {
            metric: _paired_steady_state_reduction(
                fallback_memory, candidate_memory, metric)
            for metric in STEADY_STATE_METRICS
        }
        steady_rss_reductions.append(
            steady_reductions["processRssBytes"])
        steady_pss_reductions.append(steady_reductions["pssBytes"])
        steady_anon_reductions.append(steady_reductions["rssAnonBytes"])
        fallback_p50 = (fallback.get("durationMs") or {}).get("p50")
        candidate_p50 = (candidate.get("durationMs") or {}).get("p50")
        duration_p50_reduction = (
            round(float(fallback_p50) - float(candidate_p50), 3)
            if isinstance(fallback_p50, (int, float)) and
            isinstance(candidate_p50, (int, float)) else memory.UNKNOWN)
        duration_p50_reductions.append(duration_p50_reduction)
        comparisons.append({
            "storeKind": store_kind,
            "cyclesCompared": cycles,
            "digestMatches": matches,
            "digestMatchPercent": round((matches / cycles) * 100, 3),
            "sameStoreShape": (
                fallback.get("storeShape") == candidate.get("storeShape")),
            "fallbackNormalizeCalls": fallback.get(
                "normalizeCallsDuringCycles"),
            "candidateNormalizeCalls": candidate.get(
                "normalizeCallsDuringCycles"),
            "fallbackRepresentationsPerCall": fallback_representations,
            "candidateRepresentationsPerCall": candidate_representations,
            "representationReductionPerCall": reduction,
            "fallbackProcessPeakRssBytes": fallback_process_peak,
            "candidateProcessPeakRssBytes": candidate_process_peak,
            "processPeakRssReductionBytes": process_peak_reduction,
            "steadyStateSampleDefinition":
                "paired_cycles_3_plus_growth_nearest_rank_p50",
            "fallbackSteadyStateGrowthBytes": fallback_growth,
            "candidateSteadyStateGrowthBytes": candidate_growth,
            "steadyStateReductionBytes": steady_reductions,
            "steadyStateRssReductionBytes":
                steady_reductions["processRssBytes"],
            "steadyStatePssReductionBytes": steady_reductions["pssBytes"],
            "steadyStateRssAnonReductionBytes":
                steady_reductions["rssAnonBytes"],
            "minimumMaterialRssReductionBytes":
                MINIMUM_MATERIAL_RSS_REDUCTION_BYTES,
            "fallbackDurationMs": fallback.get("durationMs"),
            "candidateDurationMs": candidate.get("durationMs"),
            "durationP50ReductionMs": duration_p50_reduction,
        })
    allocation_fallback = allocation_by_mode.get("fallback", {})
    allocation_candidate = allocation_by_mode.get("normalized", {})
    allocation_digest_equal = bool(
        allocation_fallback.get("digest") and
        allocation_fallback.get("digest") == allocation_candidate.get(
            "digest"))
    allocation_digest_matches = cycles if allocation_digest_equal else 0
    digest_matches += allocation_digest_matches
    asset_digests_across_profiles = (
        by_key.get(("asset", "fallback"), {}).get("digest"),
        by_key.get(("asset", "normalized"), {}).get("digest"),
        allocation_fallback.get("digest"),
        allocation_candidate.get("digest"),
    )
    same_asset_digest_across_profiles = (
        all(asset_digests_across_profiles) and
        len(set(asset_digests_across_profiles)) == 1)
    allocation_peak_reduction = _paired_allocation_peak_reduction_summary(
        allocation_fallback, allocation_candidate)
    allocation_fallback_p50 = (
        (allocation_fallback.get("allocationTrace") or {}).get(
            "peakIncrementBytes") or {}).get("p50")
    allocation_candidate_p50 = (
        (allocation_candidate.get("allocationTrace") or {}).get(
            "peakIncrementBytes") or {}).get("p50")
    allocation_duration_fallback_p50 = (
        allocation_fallback.get("durationMs") or {}).get("p50")
    allocation_duration_candidate_p50 = (
        allocation_candidate.get("durationMs") or {}).get("p50")
    allocation_duration_reduction = (
        round(
            float(allocation_duration_fallback_p50) -
            float(allocation_duration_candidate_p50), 3)
        if isinstance(allocation_duration_fallback_p50, (int, float)) and
        isinstance(allocation_duration_candidate_p50, (int, float))
        else memory.UNKNOWN)
    asset_comparison = next(
        (row for row in comparisons if row.get("storeKind") == "asset"), {})
    asset_comparison["allocationPeakProof"] = {
        "measurementProfile": "separate_fresh_python_tracemalloc_workers",
        "sampleDefinition":
            "paired_cycles_3_plus_peak_increment_nearest_rank_p50",
        "cyclesCompared": cycles,
        "digestMatches": allocation_digest_matches,
        "digestMatchPercent": round(
            (allocation_digest_matches / cycles) * 100, 3),
        "sameStoreShape": (
            allocation_fallback.get("storeShape") ==
            allocation_candidate.get("storeShape") ==
            by_key.get(("asset", "fallback"), {}).get("storeShape") ==
            by_key.get(("asset", "normalized"), {}).get("storeShape")),
        "fallbackNormalizeCalls": allocation_fallback.get(
            "normalizeCallsDuringCycles"),
        "candidateNormalizeCalls": allocation_candidate.get(
            "normalizeCallsDuringCycles"),
        "fallbackRepresentationsPerCall": allocation_fallback.get(
            "wholeStateRepresentationsPerCall"),
        "candidateRepresentationsPerCall": allocation_candidate.get(
            "wholeStateRepresentationsPerCall"),
        "fallbackPeakIncrementP50Bytes": allocation_fallback_p50,
        "candidatePeakIncrementP50Bytes": allocation_candidate_p50,
        "pairedPeakReductionBytes": allocation_peak_reduction,
        "minimumMaterialAllocationReductionBytes":
            MINIMUM_MATERIAL_ALLOCATION_REDUCTION_BYTES,
        "fallbackDurationMs": allocation_fallback.get("durationMs"),
        "candidateDurationMs": allocation_candidate.get("durationMs"),
        "durationP50ReductionMs": allocation_duration_reduction,
    }
    process_ids = [row.get("processId") for row in workers]
    cgroup_max_values = [
        ((row.get("memory") or {}).get("final") or {}).get(
            "cgroupMaxBytes") for row in workers
    ]
    required_resource_metrics = (
        "processRssBytes", "rssAnonBytes", "pssBytes", "arenaBytes",
        "uordblksBytes", "fordblksBytes", "topReleasableBytes",
        "cgroupCurrentBytes", "cgroupPeakBytes", "cgroupMaxBytes",
    )
    resource_telemetry_complete = all(
        all(
            _integer(sample.get(metric)) is not None
            for sample in (
                (row.get("memory") or {}).get("baseline") or {},
                (row.get("memory") or {}).get("final") or {},
                *(
                    cycle.get("after") or {}
                    for cycle in (row.get("memory") or {}).get("cycles") or []
                ),
            )
            for metric in required_resource_metrics
        )
        for row in workers
    )
    exact_cgroup = (
        not require_cgroup_max_bytes or all(
            value == require_cgroup_max_bytes for value in cgroup_max_values))
    no_oom = all(
        ((row.get("memory") or {}).get("oomDelta") == 0 and
         (row.get("memory") or {}).get("oomKillDelta") == 0)
        if require_cgroup_max_bytes else
        ((row.get("memory") or {}).get("oomDelta") in (0, memory.UNKNOWN) and
         (row.get("memory") or {}).get("oomKillDelta") in (0, memory.UNKNOWN))
        for row in workers)
    execution_environment = _environment_fingerprint()
    required_environment_fields = (
        "pythonImplementation", "pythonVersion", "pythonBuild", "libcName",
        "libcVersion", "system", "machine", "kernelRelease",
        "runnerImageOs", "runnerImageVersion", "containerImage",
        "sourceHeadSha", "executionSha",
    )
    verified_comparison = next(
        (row for row in comparisons if row.get("storeKind") == "verified"),
        {})
    asset_comparison = next(
        (row for row in comparisons if row.get("storeKind") == "asset"), {})
    verified_steady_reductions = verified_comparison.get(
        "steadyStateReductionBytes") or {}
    asset_steady_reductions = asset_comparison.get(
        "steadyStateReductionBytes") or {}
    allocation_peak_minimum = allocation_peak_reduction.get("minimum")
    allocation_peak_p50 = allocation_peak_reduction.get("p50")
    allocation_proof = asset_comparison.get("allocationPeakProof") or {}
    checks = {
        "sixFreshProcesses": (
            len(process_ids) == 6 and None not in process_ids and
            len(set(process_ids)) == 6 and
            all(row.get("freshProcess") is True for row in workers)),
        "fourUninstrumentedResourceProcesses": (
            len(resource_workers) == 4 and all(
                row.get("measurementProfile") ==
                    "os_resource_uninstrumented" and
                (row.get("checks") or {}).get(
                    "allocationTracerNotLoaded") is True
                for row in resource_workers)),
        "twoFreshAssetAllocationProcesses": (
            len(allocation_workers) == 2 and all(
                row.get("storeKind") == "asset" and
                row.get("measurementProfile") == "python_allocation_peak" and
                (row.get("checks") or {}).get(
                    "allocationTraceStartedFresh") is True and
                (row.get("checks") or {}).get(
                    "allocationTraceStopped") is True
                for row in allocation_workers)),
        "allWorkersExitedNormally": all(
            row.get("returnCode") == 0 and
            row.get("abnormalExit") is False for row in workers),
        "allWorkerChecksPassed": all(row.get("passed") for row in workers),
        "digestParity100Percent": digest_matches == expected_comparisons,
        "sameAssetDigestAcrossProfiles": same_asset_digest_across_profiles,
        "sameProductionShapedStores": (
            all(row.get("sameStoreShape") is True for row in comparisons) and
            allocation_proof.get("sameStoreShape") is True),
        "productionCalibratedCanonicalInput": all(
            (row.get("checks") or {}).get(
                "productionCalibratedCanonicalInput") is True
            for row in workers),
        "normalizedFastPathUsed": (
            all(row.get("candidateNormalizeCalls") == 0
                for row in comparisons) and
            allocation_proof.get("candidateNormalizeCalls") == 0),
        "fallbackPathUsed": (
            all(row.get("fallbackNormalizeCalls") == cycles
                for row in comparisons) and
            allocation_proof.get("fallbackNormalizeCalls") == cycles),
        "wholeStateRepresentationReduced": (
            all(value == 1 for value in representation_reduction) and
            allocation_proof.get("fallbackRepresentationsPerCall") == 2 and
            allocation_proof.get("candidateRepresentationsPerCall") == 1),
        # Verified retains a stable, architecture-meaningful RSS/PSS signal,
        # so its exact 1 MiB terminal gate remains.  Asset post-call RSS and
        # arena retention are allocator policy diagnostics; the separate
        # transient allocation workers gate the eliminated representation.
        "verifiedSteadyStateRssMateriallyReduced": (
            _integer(verified_steady_reductions.get("processRssBytes"))
                is not None and
            verified_steady_reductions.get("processRssBytes") >=
                MINIMUM_MATERIAL_RSS_REDUCTION_BYTES),
        "verifiedSteadyStatePssMateriallyReduced": (
            _integer(verified_steady_reductions.get("pssBytes")) is not None and
            verified_steady_reductions.get("pssBytes") >=
                MINIMUM_MATERIAL_RSS_REDUCTION_BYTES),
        "verifiedSteadyStateRssAnonMateriallyReduced": (
            _integer(verified_steady_reductions.get("rssAnonBytes"))
                is not None and
            verified_steady_reductions.get("rssAnonBytes") >=
                MINIMUM_MATERIAL_RSS_REDUCTION_BYTES),
        "assetAllocationPeakMinimumMateriallyReduced": (
            _integer(allocation_peak_minimum) is not None and
            allocation_peak_minimum >=
                MINIMUM_MATERIAL_ALLOCATION_REDUCTION_BYTES),
        "assetAllocationPeakP50MateriallyReduced": (
            _integer(allocation_peak_p50) is not None and
            allocation_peak_p50 >=
                MINIMUM_MATERIAL_ALLOCATION_REDUCTION_BYTES),
        "durationP50Reduced": all(
            isinstance(value, (int, float)) and value > 0
            for value in duration_p50_reductions),
        "assetAllocationTraceDurationP50Reduced": (
            isinstance(allocation_duration_reduction, (int, float)) and
            allocation_duration_reduction > 0),
        "plateauBelow128MiB": all(
            (row.get("checks") or {}).get("plateauBelow128MiB") is True
            for row in resource_workers),
        "logicalPeakBelow3GiB": all(
            (row.get("checks") or {}).get("logicalPeakBelow3GiB") is True
            for row in workers),
        "requiredResourceTelemetryObserved": (
            resource_telemetry_complete
            if require_cgroup_max_bytes else True),
        "exactCgroupLimit": exact_cgroup,
        "oomAndOomKillZero": no_oom,
        "noRuntimeControlActions": all(
            not any((row.get("runtimeActions") or {}).values())
            for row in workers),
        "singleExecutionEnvironment": all(
            row.get("environment") == execution_environment
            for row in workers),
        "environmentFingerprintComplete": all(
            execution_environment.get(field) not in (
                None, "", memory.UNKNOWN)
            for field in required_environment_fields),
    }
    return {
        "schemaVersion": "argus-normalized-hash-resource-proof-v3",
        "topology": (
            "four_uninstrumented_resource_workers_plus_two_fresh_"
            "asset_allocation_workers"),
        "environment": execution_environment,
        "cyclesPerWorker": cycles,
        "workerCount": len(workers),
        "resourceWorkerCount": len(resource_workers),
        "allocationWorkerCount": len(allocation_workers),
        "digestComparisons": expected_comparisons,
        "digestMatches": digest_matches,
        "digestMatchPercent": round(
            (digest_matches / expected_comparisons) * 100, 3),
        "resourceEnvelope": {
            "plateauLimitBytes": PLATEAU_LIMIT_BYTES,
            "logicalAcceptanceCeilingBytes":
                LOGICAL_ACCEPTANCE_CEILING_BYTES,
            "minimumMaterialRssReductionBytes":
                MINIMUM_MATERIAL_RSS_REDUCTION_BYTES,
            "minimumMaterialAllocationReductionBytes":
                MINIMUM_MATERIAL_ALLOCATION_REDUCTION_BYTES,
            "requiredCgroupMaxBytes": (
                require_cgroup_max_bytes or memory.NOT_APPLICABLE),
            "observedCgroupMaxBytes": cgroup_max_values,
            "productionCalibratedBarsPerRecord": bars_by_store,
        },
        "comparisons": comparisons,
        "workers": workers,
        "runtimeActions": {
            "allocatorTrimInvoked": False,
            "forcedCollectionInvoked": False,
            "restartInvoked": False,
        },
        "diagnostics": {
            "processPeakRssReductionBytes": process_peak_reductions,
            "processPeakRssMateriallyReduced": all(
                _integer(value) is not None and
                value >= MINIMUM_MATERIAL_RSS_REDUCTION_BYTES
                for value in process_peak_reductions),
            "processPeakRssRole":
                "safety_telemetry_not_terminal_effect_gate",
            "assetPostCallSteadyStateReductionBytes":
                asset_steady_reductions,
            "assetPostCallResourceRole":
                "allocator_retention_diagnostic_not_terminal_effect_gate",
            "assetAllocationPeakReductionBytes": allocation_peak_reduction,
        },
        "oomCount": 0 if no_oom else memory.UNKNOWN,
        "abnormalExitCount": sum(
            int(bool(row.get("abnormalExit"))) for row in workers),
        "elapsedMs": round((time.monotonic() - started) * 1000, 3),
        "checks": checks,
        "passed": all(checks.values()),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cycles", type=int, default=MINIMUM_CYCLES)
    parser.add_argument("--bars-per-record", type=int)
    parser.add_argument(
        "--verified-bars-per-record", type=int,
        default=DEFAULT_VERIFIED_BARS_PER_RECORD)
    parser.add_argument(
        "--asset-bars-per-record", type=int,
        default=DEFAULT_ASSET_BARS_PER_RECORD)
    parser.add_argument("--require-cgroup-max-bytes", type=int, default=0)
    parser.add_argument("--output")
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--worker-store", choices=STORE_KINDS)
    parser.add_argument("--worker-mode", choices=PATH_MODES)
    parser.add_argument(
        "--worker-profile", choices=("resource", "allocation_peak"),
        default="resource")
    args = parser.parse_args()
    if args.worker_store or args.worker_mode:
        if not (args.worker_store and args.worker_mode):
            return 2
        worker_bars = args.bars_per_record
        if worker_bars is None:
            worker_bars = (
                args.verified_bars_per_record
                if args.worker_store == "verified"
                else args.asset_bars_per_record)
        try:
            worker_callback = (
                _allocation_worker
                if args.worker_profile == "allocation_peak" else _worker)
            report = worker_callback(
                args.worker_store, args.worker_mode, args.cycles,
                max(1, int(worker_bars)))
        except Exception as exc:
            report = {
                "schemaVersion": (
                    "argus-normalized-hash-allocation-worker-v1"
                    if args.worker_profile == "allocation_peak"
                    else "argus-normalized-hash-worker-v2"),
                "measurementProfile": args.worker_profile,
                "freshProcess": True,
                "processId": os.getpid(),
                "storeKind": args.worker_store,
                "pathMode": args.worker_mode,
                "errorClass": type(exc).__name__,
                "passed": False,
            }
        print(json.dumps(report, separators=(",", ":"), sort_keys=True))
        return 0 if report.get("passed") else 1
    verified_bars = args.verified_bars_per_record
    asset_bars = args.asset_bars_per_record
    if args.bars_per_record is not None:
        verified_bars = args.bars_per_record
        asset_bars = args.bars_per_record
    report = run(
        args.cycles,
        verified_bars_per_record=max(1, int(verified_bars)),
        asset_bars_per_record=max(1, int(asset_bars)),
        require_cgroup_max_bytes=max(0, int(args.require_cgroup_max_bytes)))
    encoded = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    if not args.quiet:
        print(encoded)
    if args.output:
        pathlib.Path(args.output).write_text(
            encoded + "\n", encoding="utf-8")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
