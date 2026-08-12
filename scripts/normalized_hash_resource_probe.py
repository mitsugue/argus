#!/usr/bin/env python3
"""Fresh-process resource proof for normalized-state hashing.

This probe is local/CI only.  It creates deterministic production-shaped
stores, never contacts a provider or service, and exercises no durability or
runtime-control path.  The supervisor starts one fresh process per store/path
pair so the fallback and normalized fast path do not share allocator history.
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


def _worker_command(
        store_kind: str, mode: str, cycles: int,
        bars_per_record: int) -> list[str]:
    return [
        sys.executable, "-B", str(pathlib.Path(__file__).resolve()),
        "--worker-store", store_kind, "--worker-mode", mode,
        "--cycles", str(cycles),
        "--bars-per-record", str(bars_per_record),
    ]


def _run_worker(
        store_kind: str, mode: str, cycles: int,
        bars_per_record: int) -> Dict[str, Any]:
    environment = dict(os.environ)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PYTHONHASHSEED"] = "0"
    try:
        completed = subprocess.run(
            _worker_command(store_kind, mode, cycles, bars_per_record),
            cwd=str(ROOT), env=environment, capture_output=True, text=True,
            timeout=900, check=False)
    except subprocess.TimeoutExpired:
        return {
            "storeKind": store_kind, "pathMode": mode,
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
    workers = [
        _run_worker(
            store_kind, mode, cycles, bars_by_store[store_kind])
        for store_kind in STORE_KINDS for mode in PATH_MODES
    ]
    by_key = {
        (row.get("storeKind"), row.get("pathMode")): row
        for row in workers
    }
    comparisons = []
    digest_matches = 0
    expected_comparisons = cycles * len(STORE_KINDS)
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
        "containerImage", "sourceHeadSha", "executionSha",
    )
    asset_comparison = next(
        (row for row in comparisons if row.get("storeKind") == "asset"), {})
    asset_steady_reductions = asset_comparison.get(
        "steadyStateReductionBytes") or {}
    checks = {
        "fourFreshProcesses": (
            len(process_ids) == 4 and None not in process_ids and
            len(set(process_ids)) == 4 and
            all(row.get("freshProcess") is True for row in workers)),
        "allWorkersExitedNormally": all(
            row.get("returnCode") == 0 and
            row.get("abnormalExit") is False for row in workers),
        "allWorkerChecksPassed": all(row.get("passed") for row in workers),
        "digestParity100Percent": digest_matches == expected_comparisons,
        "sameProductionShapedStores": all(
            row.get("sameStoreShape") is True for row in comparisons),
        "productionCalibratedCanonicalInput": all(
            (row.get("checks") or {}).get(
                "productionCalibratedCanonicalInput") is True
            for row in workers),
        "normalizedFastPathUsed": all(
            row.get("candidateNormalizeCalls") == 0
            for row in comparisons),
        "fallbackPathUsed": all(
            row.get("fallbackNormalizeCalls") == cycles
            for row in comparisons),
        "wholeStateRepresentationReduced": all(
            value == 1 for value in representation_reduction),
        # ru_maxrss is a cumulative process-lifetime high-water mark.  It
        # remains safety telemetry, while the fixed-cycle paired median below
        # measures the long-lived RSS effect without address-layout aliasing.
        "steadyStateRssMateriallyReduced": all(
            _integer(value) is not None and
            value >= MINIMUM_MATERIAL_RSS_REDUCTION_BYTES
            for value in steady_rss_reductions),
        "steadyStatePssMateriallyReduced": all(
            _integer(value) is not None and
            value >= MINIMUM_MATERIAL_RSS_REDUCTION_BYTES
            for value in steady_pss_reductions),
        "steadyStateRssAnonMateriallyReduced": all(
            _integer(value) is not None and
            value >= MINIMUM_MATERIAL_RSS_REDUCTION_BYTES
            for value in steady_anon_reductions),
        "assetAllocatorRetentionMateriallyReduced": all(
            _integer(asset_steady_reductions.get(metric)) is not None and
            asset_steady_reductions.get(metric) >=
                MINIMUM_MATERIAL_RSS_REDUCTION_BYTES
            for metric in ("arenaBytes", "fordblksBytes")),
        "durationP50Reduced": all(
            isinstance(value, (int, float)) and value > 0
            for value in duration_p50_reductions),
        "plateauBelow128MiB": all(
            (row.get("checks") or {}).get("plateauBelow128MiB") is True
            for row in workers),
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
        "schemaVersion": "argus-normalized-hash-resource-proof-v2",
        "topology": "fresh_process_per_store_and_path",
        "environment": execution_environment,
        "cyclesPerWorker": cycles,
        "workerCount": len(workers),
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
            report = _worker(
                args.worker_store, args.worker_mode, args.cycles,
                max(1, int(worker_bars)))
        except Exception as exc:
            report = {
                "schemaVersion": "argus-normalized-hash-worker-v2",
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
