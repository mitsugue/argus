#!/usr/bin/env python3
"""Exact/synthetic Checkpoint V2 Linux cgroup resource evidence."""
from __future__ import annotations

import argparse
import concurrent.futures
import gc
import hashlib
import json
import os
import pathlib
import resource
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import tracemalloc

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import argus_checkpoint_v2 as v2  # noqa: E402
import argus_tick_durability as durability  # noqa: E402


OBSERVED_SECTIONS_MIB = {
    "marketLedger": 59, "verifiedViewSnapshots": 26,
    "assetChartReports": 16, "chartIntelligence": 9,
    "marketReplay": 6, "todayIntelligence": 3,
}
PRODUCTION_SHAPED_SECTION_COUNT = 41
PRODUCTION_SHAPED_ROW_TARGET = 45_000
PRODUCTION_SHAPED_PAYLOAD_BYTES = 9_300


def peak_rss_bytes():
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(value if sys.platform == "darwin" else value * 1024)


def current_rss_bytes():
    status = pathlib.Path("/proc/self/status")
    if status.exists():
        for line in status.read_text().splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) * 1024
    if sys.platform == "darwin":
        try:
            return int(subprocess.check_output(
                ["ps", "-o", "rss=", "-p", str(os.getpid())],
                text=True).strip()) * 1024
        except (OSError, subprocess.SubprocessError, ValueError):
            pass
    return peak_rss_bytes()


def smaps_rollup_bytes():
    path = pathlib.Path("/proc/self/smaps_rollup")
    result = {}
    try:
        for line in path.read_text().splitlines():
            key, separator, remainder = line.partition(":")
            if separator and key in {
                    "Rss", "Pss", "Pss_Anon", "Pss_File", "Private_Clean",
                    "Private_Dirty", "Swap"}:
                result[f"{key}Bytes"] = int(remainder.split()[0]) * 1024
    except (FileNotFoundError, OSError, ValueError, IndexError):
        pass
    return result


def descriptor_count():
    for path in (pathlib.Path("/proc/self/fd"), pathlib.Path("/dev/fd")):
        try:
            return len(list(path.iterdir()))
        except OSError:
            continue
    return None


def mapping_counts():
    path = pathlib.Path("/proc/self/maps")
    result = {"mappingCount": None, "sqliteOrTempMappingCount": None}
    try:
        lines = path.read_text().splitlines()
    except (FileNotFoundError, OSError):
        return result
    result["mappingCount"] = len(lines)
    result["sqliteOrTempMappingCount"] = sum(
        "checkpoint-v2.sqlite" in line or ".v2-pending-" in line
        for line in lines)
    return result


def gc_resource_counts():
    connections = cursors = futures = 0
    for value in gc.get_objects():
        try:
            connections += isinstance(value, sqlite3.Connection)
            cursors += isinstance(value, sqlite3.Cursor)
            futures += isinstance(value, concurrent.futures.Future)
        except ReferenceError:
            continue
    return {
        "sqliteConnectionCount": connections,
        "sqliteCursorCount": cursors,
        "threadCount": threading.active_count(),
        "descriptorCount": descriptor_count(),
        "futureCount": futures,
        **mapping_counts(),
    }


def cgroup_value(name):
    path = pathlib.Path("/sys/fs/cgroup") / name
    try:
        value = path.read_text().strip()
        return value if value == "max" else int(value)
    except (OSError, ValueError):
        return None


def synthetic_snapshot(multiplier=1.0):
    # 15,000 dict items x three scalar leaves is approximately 45,000 rows.
    # Payload width gives a 133-140 MiB source while the named heavy sections
    # retain the proportions seen in production.  The remaining 34 bounded
    # sections make the top-level shape 41 sections including schemaVersion.
    item_total = max(41, int((PRODUCTION_SHAPED_ROW_TARGET // 3) *
                             multiplier))
    heavy_total = int(item_total * 0.84)
    observed_total = sum(OBSERVED_SECTIONS_MIB.values())
    section_counts = {
        section: max(1, int(heavy_total * mib / observed_total))
        for section, mib in OBSERVED_SECTIONS_MIB.items()
    }
    assigned = sum(section_counts.values())
    auxiliary_names = [f"resourceProbeSection{index:02d}"
                       for index in range(34)]
    remaining = max(len(auxiliary_names), item_total - assigned)
    for index, section in enumerate(auxiliary_names):
        section_counts[section] = (
            remaining // len(auxiliary_names) +
            (1 if index < remaining % len(auxiliary_names) else 0))
    result = {"schemaVersion": "argus-durable-v3"}
    global_index = 0
    for section, count in section_counts.items():
        result[section] = []
        for _ in range(count):
            global_index += 1
            result[section].append({
                "id": global_index,
                "group": section,
                "payload": chr(65 + global_index % 20) *
                PRODUCTION_SHAPED_PAYLOAD_BYTES,
            })
    assert len(result) == PRODUCTION_SHAPED_SECTION_COUNT
    return result


def item_counts(value, prefix="", depth=0):
    counts = {}
    if isinstance(value, dict):
        counts[prefix or "$root"] = len(value)
        if depth < 2:
            for key, child in value.items():
                if isinstance(child, (dict, list)):
                    child_prefix = f"{prefix}.{key}" if prefix else str(key)
                    counts.update(item_counts(child, child_prefix, depth + 1))
    elif isinstance(value, list):
        counts[prefix or "$root"] = len(value)
    return counts


def load_snapshot(source_json, multiplier):
    if source_json:
        with open(source_json, encoding="utf-8") as handle:
            return json.load(handle)
    return synthetic_snapshot(multiplier)


def worker(mode, root, multiplier, source_json=None,
           wal_target_bytes=631_910):
    peak_before = peak_rss_bytes()
    current_before = current_rss_bytes()
    cgroup_before = cgroup_value("memory.current")
    counts = None
    if mode == "write":
        value = load_snapshot(source_json, multiplier)
        counts = item_counts(value)
        result = v2.write_generation(
            root, value, source_generation="resource-probe",
            consume_snapshot=True)
        consumed = value == {}
        del value
    elif mode == "restore":
        result = v2.restore_generation(root, include_archived=False)
        del result["snapshot"]
    else:
        wal = pathlib.Path(root) / "resource-probe.wal"
        sequence = 0
        while not wal.exists() or wal.stat().st_size < wal_target_bytes:
            sequence += 1
            durability.append_wal(
                str(wal), sequence=sequence, kind="mission_transition",
                payload={"transitionId": f"t-{sequence}",
                         "payload": "w" * 4096}, job_id="resource-probe")
        result = durability.read_valid_wal(str(wal))
        counts = {"walRecords": len(result["records"])}
        result["verified"] = result["corruptCount"] == 0
    gc.collect()
    current_after = current_rss_bytes()
    peak_after = peak_rss_bytes()
    print(json.dumps({
        "mode": mode, "processTopology": "isolated_child_process",
        "measurementSource": "ru_maxrss_and_proc_self_status",
        "processRssBeforeBytes": current_before,
        "processPeakRssBeforeBytes": peak_before,
        "processPeakRssBytes": peak_after,
        "processRssAfterBytes": current_after,
        "processPeakDeltaBytes": max(0, peak_after - current_before),
        "cgroupMemoryCurrentBeforeBytes": cgroup_before,
        "cgroupMemoryCurrentAfterBytes": cgroup_value("memory.current"),
        "cgroupMemoryPeakBytes": cgroup_value("memory.peak"),
        "pageCacheIncludedInProcessRss": False,
        "pageCacheIncludedInCgroup": True,
        "pythonAllocatorHighWaterIncludedInRuMaxrss": True,
        "executionTemperature": "cold_isolated_process",
        "sourceStateFileBytes": (
            pathlib.Path(source_json).stat().st_size if source_json else None),
        "sqliteGenerationBytes": result.get("databaseBytes"),
        "walBytes": result.get("bytes") if mode == "wal" else None,
        "itemCounts": counts, "verified": result["verified"],
        "snapshotConsumed": consumed if mode == "write" else None,
    }, sort_keys=True))


def allocation_trace_worker(multiplier, source_json=None):
    """Trace one identical lifecycle without retaining observer state."""
    with tempfile.TemporaryDirectory(
            prefix="argus-checkpoint-v2-trace-") as root:
        tracemalloc.start()
        previous_trace = tracemalloc.take_snapshot()
        value = load_snapshot(source_json, multiplier)
        result = v2.write_generation(
            root, value, source_generation="allocation-trace",
            consume_snapshot=True)
        consumed = value == {}
        del value
        restored = v2.restore_generation(root, include_archived=False)
        restored_verified = bool(restored.get("verified"))
        del restored["snapshot"], restored
        gc.collect()
        v2._release_unused_allocator_memory(
            int(result.get("sourceSerializedBytes") or 0))
        traced_current, traced_peak = tracemalloc.get_traced_memory()
        current_trace = tracemalloc.take_snapshot()
        top_deltas = []
        for statistic in current_trace.compare_to(
                previous_trace, "traceback")[:5]:
            frame = statistic.traceback[0]
            top_deltas.append({
                "file": pathlib.Path(frame.filename).name,
                "line": frame.lineno,
                "sizeDeltaBytes": statistic.size_diff,
                "countDelta": statistic.count_diff,
            })
        print(json.dumps({
            "tracedCurrentBytes": traced_current,
            "tracedPeakBytes": traced_peak,
            "topAllocationTracebackDeltas": top_deltas,
            "writeVerified": bool(result.get("verified")),
            "restoreVerified": restored_verified,
            "snapshotConsumed": consumed,
        }, sort_keys=True))


def run_allocation_trace_child(multiplier, source_json=None):
    command = [sys.executable, __file__, "--worker", "allocation-trace",
               "--multiplier", str(multiplier)]
    if source_json:
        command.extend(["--source-json", source_json])
    completed = subprocess.run(
        command, check=True, capture_output=True, text=True)
    return json.loads(completed.stdout.strip().splitlines()[-1])


def repeated_worker(root, multiplier, cycles, source_json=None):
    root_path = pathlib.Path(root)
    root_path.mkdir(parents=True, exist_ok=True)
    legacy_checkpoint = root_path / "legacy-state.json"
    legacy_checkpoint.write_text("{}", encoding="utf-8")
    legacy_temp_paths = []
    for index in range(10):
        path = root_path / f"legacy-state.json.incident-{index}.v1338-tmp"
        path.write_bytes(f"incident-{index}".encode("ascii"))
        legacy_temp_paths.append(path)
    legacy_temp_hashes = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in legacy_temp_paths}
    gc.collect()
    baseline_resources = gc_resource_counts()
    samples = [None] * (cycles + 1)
    samples[0] = current_rss_bytes()
    traced_currents = []
    traced_peaks = []
    cycle_report_path = root_path / "resource-cycle-reports.ndjson"
    cycle_report_path.write_text("", encoding="utf-8")
    for index in range(cycles):
        trace_report = run_allocation_trace_child(multiplier, source_json)
        value = load_snapshot(source_json, multiplier)
        source_counts = item_counts(value)
        result = v2.write_generation(
            root, value, source_generation=f"retention-{index}",
            consume_snapshot=True,
            validation_context={
                "triggerSource": "resource_probe",
                "missionWindowId": f"retention-{index}",
                "natural": False,
                "formalSoakState": "not_started",
                "legacyCheckpointPath": str(legacy_checkpoint),
                "legacyTempDirectory": str(root_path),
            })
        consumed = value == {}
        del value
        restored = v2.restore_generation(root, include_archived=False)
        restored_verified = bool(restored.get("verified"))
        del restored["snapshot"], restored
        unreachable = gc.collect()
        # restore_generation is deliberately exercised here as an isolated
        # validation/read-back step.  Production Stage 1 does not retain that
        # reconstructed graph, so return its test-only allocator arenas before
        # measuring the production write lifecycle's steady-state RSS.
        readback_reclaim = v2._release_unused_allocator_memory(
            int(result.get("sourceSerializedBytes") or 0))
        traced_current = trace_report["tracedCurrentBytes"]
        traced_peak = trace_report["tracedPeakBytes"]
        top_deltas = trace_report["topAllocationTracebackDeltas"]
        traced_currents.append(traced_current)
        traced_peaks.append(traced_peak)
        gc.collect()
        v2._release_unused_allocator_memory(
            int(result.get("sourceSerializedBytes") or 0))
        time.sleep(0.01)
        rss = current_rss_bytes()
        samples[index + 1] = rss
        resources = gc_resource_counts()
        current_paths = list(root_path.iterdir())
        retained = sum(path.name.startswith("v2-generation-")
                       for path in current_paths)
        pending = sum(path.name.startswith(".v2-pending-")
                      for path in current_paths)
        manifest = json.loads((root_path / v2.MANIFEST_NAME).read_text())
        disk = shutil.disk_usage(root_path)
        cycle_report = {
            "cycle": index + 1,
            "writeVerified": bool(result.get("verified")),
            "restoreVerified": restored_verified,
            "snapshotConsumed": consumed,
            "processRssAfterBytes": rss,
            "processRssBeforeBytes": (
                result.get("resourceTelemetry") or {}).get(
                    "processRssBeforeBytes"),
            "processPeakRssBytes": peak_rss_bytes(),
            "tracedCurrentBytes": traced_current,
            "tracedPeakBytes": traced_peak,
            "topAllocationTracebackDeltas": top_deltas,
            "gcGenerationCounts": list(gc.get_count()),
            "gcUnreachableAfterRelease": unreachable,
            "sourceItemCounts": source_counts,
            "generationBytes": result.get("databaseBytes"),
            "rowCount": (result.get("resourceTelemetry") or {}).get(
                "rowCount"),
            "sectionCount": (result.get("resourceTelemetry") or {}).get(
                "sectionCount"),
            "durationMs": (result.get("resourceTelemetry") or {}).get(
                "durationMs"),
            "writerLockWaitMs": (result.get("resourceTelemetry") or {}).get(
                "writerLockWaitMs"),
            "diskFreeBytes": disk.free,
            "pendingGenerationCount": pending,
            "retainedGenerationCount": retained,
            "generationMetadataEntryCount": len(
                manifest.get("generationHistory") or []),
            "legacyTempBaselineCount": (
                result.get("resourceTelemetry") or {}).get(
                    "legacyTempBaselineCount"),
            "legacyTempAfterCount": (
                result.get("resourceTelemetry") or {}).get(
                    "legacyTempAfterCount"),
            "newLegacyTempCount": (
                result.get("resourceTelemetry") or {}).get(
                    "newLegacyTempCount"),
            "allocatorReclaim": (result.get("resourceTelemetry") or {}).get(
                "allocatorReclaim"),
            "readBackAllocatorReclaim": readback_reclaim,
            "cgroupMemoryCurrentAfterBytes": (
                result.get("resourceTelemetry") or {}).get(
                    "cgroupMemoryCurrentAfterBytes"),
            "cgroupMemoryPeakBytes": (
                result.get("resourceTelemetry") or {}).get(
                    "cgroupMemoryPeakBytes"),
            **resources,
            **smaps_rollup_bytes(),
        }
        with open(cycle_report_path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(cycle_report, sort_keys=True) + "\n")
        cycle_report = source_counts = current_paths = manifest = None
        result = resources = top_deltas = trace_report = None
    paths = list(pathlib.Path(root).iterdir())
    ending_resources = gc_resource_counts()
    steady_samples = samples[3:] if len(samples) > 3 else samples[1:]
    steady_growth = (steady_samples[-1] - steady_samples[0]
                     if len(steady_samples) > 1 else 0)
    strictly_monotonic = len(steady_samples) > 1 and all(
        later > earlier
        for earlier, later in zip(steady_samples, steady_samples[1:]))
    traced_current = traced_currents[-1] if traced_currents else 0
    traced_peak = max(traced_peaks, default=0)
    legacy_temp_hashes_after = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in legacy_temp_paths}
    cycle_reports = [json.loads(line) for line in
                     cycle_report_path.read_text(encoding="utf-8").splitlines()
                     if line]
    print(json.dumps({
        "mode": "repeated", "cycles": cycles,
        "executionTemperature": "production_shaped_long_lived_process",
        "datasetKind": ("exact_public_production_snapshot" if source_json
                        else "synthetic_observed_section_sizes"),
        "startingRssBytes": samples[0], "endingRssBytes": samples[-1],
        "retainedGrowthBytes": max(0, samples[-1] - samples[0]),
        "steadyStateSamples": steady_samples,
        "steadyStateGrowthBytes": steady_growth,
        "strictlyMonotonicSteadyState": strictly_monotonic,
        "maximumCurrentRssBytes": max(samples),
        "peakRssBytes": peak_rss_bytes(),
        "tracedCurrentBytes": traced_current,
        "tracedPeakBytes": traced_peak,
        "baselineResources": baseline_resources,
        "endingResources": ending_resources,
        "incidentTempCount": len(legacy_temp_paths),
        "incidentTempsImmutable": legacy_temp_hashes_after ==
        legacy_temp_hashes,
        "cycleReports": cycle_reports,
        "pendingGenerationCount": sum(
            path.name.startswith(".v2-pending-") for path in paths),
        "retainedGenerationCount": sum(
            path.name.startswith("v2-generation-") for path in paths),
        "samples": samples,
    }, sort_keys=True))


def run_child(mode, root, multiplier, source_json=None):
    command = [sys.executable, __file__, "--worker", mode, "--root", root,
               "--multiplier", str(multiplier)]
    if source_json:
        command.extend(["--source-json", source_json])
    completed = subprocess.run(
        command, check=True, capture_output=True, text=True)
    return json.loads(completed.stdout.strip().splitlines()[-1])


def orchestrate(full_cycles, retention_cycles, assert_bounds,
                source_json=None):
    results = []
    with tempfile.TemporaryDirectory(prefix="argus-checkpoint-v2-probe-") as root:
        cycles = 1 if source_json else full_cycles
        for _ in range(cycles):
            results.append(run_child("write", root, 1.0, source_json))
            results.append(run_child("restore", root, 1.0))
        results.append(run_child("wal", root, 1.0))
        completed = subprocess.run(
            [sys.executable, __file__, "--worker", "repeated", "--root", root,
             "--multiplier", "1.0", "--retention-cycles",
             str(retention_cycles)] + (
                 ["--source-json", source_json] if source_json else []),
            check=True, capture_output=True, text=True)
        repeated = json.loads(completed.stdout.strip().splitlines()[-1])
    maximum = max(row["processPeakRssBytes"] for row in results)
    maximum_delta = max(row["processPeakDeltaBytes"] for row in results)
    cgroup_memory_peak = cgroup_value("memory.peak")
    conservative_peak = max(
        int(cgroup_memory_peak or 0), maximum,
        int(repeated.get("peakRssBytes") or 0),
        max((int(row.get("cgroupMemoryPeakBytes") or 0)
             for row in repeated.get("cycleReports") or []), default=0))
    cgroup_memory_limit = 4 * 1024 ** 3
    acceptance_ceiling = 3 * 1024 ** 3
    report = {
        "schemaVersion": "argus-checkpoint-v2-resource-proof-v2",
        "datasetKind": ("exact_public_production_snapshot" if source_json
                        else "synthetic_observed_section_sizes"),
        "sameProductionShapedStateForWriteRestore": bool(source_json),
        "sourceJson": pathlib.Path(source_json).name if source_json else None,
        "fullCycles": (1 if source_json else full_cycles),
        "retentionCycles": retention_cycles, "processRuns": len(results),
        "maximumPeakRssBytes": maximum,
        "maximumDeltaRssBytes": maximum_delta,
        "cgroupMemoryMax": cgroup_value("memory.max"),
        "cgroupMemoryCurrentAfterBytes": cgroup_value("memory.current"),
        "cgroupMemoryPeakBytes": cgroup_memory_peak,
        "conservativePeakBytes": conservative_peak,
        "acceptanceCeilingBytes": acceptance_ceiling,
        "headroomTo4GiBBytes": cgroup_memory_limit - conservative_peak,
        "results": results, "repeated": repeated,
    }
    print(json.dumps(report, sort_keys=True))
    if assert_bounds:
        if str(report["cgroupMemoryMax"]) != str(cgroup_memory_limit):
            raise SystemExit("expected_exact_4gib_cgroup")
        if conservative_peak >= acceptance_ceiling:
            raise SystemExit("checkpoint_v2_memory_bound_exceeded")
        if repeated["steadyStateGrowthBytes"] >= 128 * 1024 ** 2:
            raise SystemExit("checkpoint_v2_steady_state_growth_exceeded")
        if repeated["strictlyMonotonicSteadyState"]:
            raise SystemExit("checkpoint_v2_strict_monotonic_rss_growth")
        if repeated["pendingGenerationCount"] or \
                repeated["retainedGenerationCount"] > v2.MAXIMUM_GENERATIONS:
            raise SystemExit("checkpoint_v2_generation_accumulation")
        if len(repeated["cycleReports"]) != retention_cycles or not all(
                row["writeVerified"] and row["restoreVerified"] and
                row["snapshotConsumed"] and
                row["pendingGenerationCount"] == 0 and
                row["retainedGenerationCount"] <= v2.MAXIMUM_GENERATIONS and
                row["generationMetadataEntryCount"] <=
                v2.MAXIMUM_GENERATIONS and
                row["newLegacyTempCount"] == 0 and
                row["diskFreeBytes"] >= 1024 ** 3
                for row in repeated["cycleReports"]):
            raise SystemExit("checkpoint_v2_repeated_verification_failed")
        if not source_json and not all(
                40_000 <= int(row["rowCount"] or 0) <= 50_000 and
                row["sectionCount"] == PRODUCTION_SHAPED_SECTION_COUNT and
                127 * 1024 ** 2 <= int(row["generationBytes"] or 0) <=
                160 * 1024 ** 2
                for row in repeated["cycleReports"]):
            raise SystemExit("checkpoint_v2_production_shape_mismatch")
        if not repeated["incidentTempsImmutable"]:
            raise SystemExit("checkpoint_v2_incident_temp_mutation")
        baseline = repeated["baselineResources"]
        ending = repeated["endingResources"]
        for field in ("sqliteConnectionCount", "sqliteCursorCount",
                      "threadCount", "descriptorCount", "futureCount",
                      "mappingCount", "sqliteOrTempMappingCount"):
            if baseline.get(field) is not None and ending.get(field) is not None \
                    and ending[field] > baseline[field]:
                raise SystemExit(f"checkpoint_v2_{field}_growth")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", choices=("write", "restore", "wal",
                                             "repeated", "allocation-trace"))
    parser.add_argument("--root")
    parser.add_argument("--source-json")
    parser.add_argument("--multiplier", type=float, default=1.0)
    parser.add_argument("--full-cycles", type=int, default=3)
    parser.add_argument("--retention-cycles", type=int, default=8)
    parser.add_argument("--assert-bounds", action="store_true")
    args = parser.parse_args()
    if args.worker == "repeated":
        repeated_worker(args.root, args.multiplier, args.retention_cycles,
                        args.source_json)
    elif args.worker == "allocation-trace":
        allocation_trace_worker(args.multiplier, args.source_json)
    elif args.worker:
        worker(args.worker, args.root, args.multiplier, args.source_json)
    else:
        orchestrate(args.full_cycles, args.retention_cycles,
                    args.assert_bounds, args.source_json)


if __name__ == "__main__":
    main()
