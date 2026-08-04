#!/usr/bin/env python3
"""Exact/synthetic Checkpoint V2 Linux cgroup resource evidence."""
from __future__ import annotations

import argparse
import gc
import json
import os
import pathlib
import resource
import subprocess
import sys
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import argus_checkpoint_v2 as v2  # noqa: E402
import argus_tick_durability as durability  # noqa: E402


OBSERVED_SECTIONS_MIB = {
    "marketLedger": 59, "verifiedViewSnapshots": 26,
    "assetChartReports": 16, "chartIntelligence": 9,
    "marketReplay": 6, "todayIntelligence": 3,
}


def peak_rss_bytes():
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(value if sys.platform == "darwin" else value * 1024)


def current_rss_bytes():
    status = pathlib.Path("/proc/self/status")
    if status.exists():
        for line in status.read_text().splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) * 1024
    return peak_rss_bytes()


def cgroup_value(name):
    path = pathlib.Path("/sys/fs/cgroup") / name
    try:
        value = path.read_text().strip()
        return value if value == "max" else int(value)
    except (OSError, ValueError):
        return None


def synthetic_snapshot(multiplier=1.0):
    result = {"schemaVersion": "argus-durable-v3"}
    for section, mib in OBSERVED_SECTIONS_MIB.items():
        blocks = max(1, int(mib * multiplier))
        result[section] = [
            {"block": index,
             "payload": chr(65 + index % 20) * (1024 * 1024 - 80)}
            for index in range(blocks)]
    result.update({
        "missions": [{"missionId": f"m-{i}"} for i in range(120)],
        "missionWindows": [{"windowId": f"w-{i}"} for i in range(240)],
        "opsJournal": [{"sequence": i, "event": "verified"}
                       for i in range(400)],
        "opsJournalCompacted": [{"sequence": i} for i in range(40)],
        "remoteAck": {"maximumSequence": 400},
    })
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
            root, value, source_generation="resource-probe")
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
    }, sort_keys=True))


def repeated_worker(root, multiplier, cycles):
    samples = [current_rss_bytes()]
    for index in range(cycles):
        value = synthetic_snapshot(multiplier)
        v2.write_generation(root, value, source_generation=f"reduced-{index}")
        del value
        restored = v2.restore_generation(root, include_archived=False)
        del restored["snapshot"], restored
        gc.collect()
        time.sleep(0.01)
        samples.append(current_rss_bytes())
    paths = list(pathlib.Path(root).iterdir())
    print(json.dumps({
        "mode": "repeated", "cycles": cycles,
        "startingRssBytes": samples[0], "endingRssBytes": samples[-1],
        "retainedGrowthBytes": max(0, samples[-1] - samples[0]),
        "maximumCurrentRssBytes": max(samples),
        "peakRssBytes": peak_rss_bytes(),
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


def orchestrate(full_cycles, reduced_cycles, assert_bounds, source_json=None):
    results = []
    with tempfile.TemporaryDirectory(prefix="argus-checkpoint-v2-probe-") as root:
        cycles = 1 if source_json else full_cycles
        for _ in range(cycles):
            results.append(run_child("write", root, 1.0, source_json))
            results.append(run_child("restore", root, 1.0))
        results.append(run_child("wal", root, 1.0))
        completed = subprocess.run(
            [sys.executable, __file__, "--worker", "repeated", "--root", root,
             "--multiplier", "0.05", "--reduced-cycles",
             str(reduced_cycles)], check=True, capture_output=True, text=True)
        repeated = json.loads(completed.stdout.strip().splitlines()[-1])
    maximum = max(row["processPeakRssBytes"] for row in results)
    maximum_delta = max(row["processPeakDeltaBytes"] for row in results)
    report = {
        "schemaVersion": "argus-checkpoint-v2-resource-proof-v2",
        "datasetKind": ("exact_public_production_snapshot" if source_json
                        else "synthetic_observed_section_sizes"),
        "sameProductionShapedStateForWriteRestore": bool(source_json),
        "sourceJson": pathlib.Path(source_json).name if source_json else None,
        "fullCycles": (1 if source_json else full_cycles),
        "reducedCycles": reduced_cycles, "processRuns": len(results),
        "maximumPeakRssBytes": maximum,
        "maximumDeltaRssBytes": maximum_delta,
        "cgroupMemoryMax": cgroup_value("memory.max"),
        "cgroupMemoryCurrentAfterBytes": cgroup_value("memory.current"),
        "cgroupMemoryPeakBytes": cgroup_value("memory.peak"),
        "results": results, "repeated": repeated,
    }
    print(json.dumps(report, sort_keys=True))
    if assert_bounds:
        if str(report["cgroupMemoryMax"]) != str(4 * 1024 ** 3):
            raise SystemExit("expected_exact_4gib_cgroup")
        conservative_peak = max(
            int(report["cgroupMemoryPeakBytes"] or 0), maximum)
        if conservative_peak >= 4 * 1024 ** 3 or \
                maximum_delta > 512 * 1024 ** 2:
            raise SystemExit("checkpoint_v2_memory_bound_exceeded")
        if repeated["retainedGrowthBytes"] >= 128 * 1024 ** 2:
            raise SystemExit("checkpoint_v2_retained_growth_exceeded")
        if repeated["pendingGenerationCount"] or \
                repeated["retainedGenerationCount"] > v2.MAXIMUM_GENERATIONS:
            raise SystemExit("checkpoint_v2_generation_accumulation")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", choices=("write", "restore", "wal",
                                             "repeated"))
    parser.add_argument("--root")
    parser.add_argument("--source-json")
    parser.add_argument("--multiplier", type=float, default=1.0)
    parser.add_argument("--full-cycles", type=int, default=3)
    parser.add_argument("--reduced-cycles", type=int, default=50)
    parser.add_argument("--assert-bounds", action="store_true")
    args = parser.parse_args()
    if args.worker == "repeated":
        repeated_worker(args.root, args.multiplier, args.reduced_cycles)
    elif args.worker:
        worker(args.worker, args.root, args.multiplier, args.source_json)
    else:
        orchestrate(args.full_cycles, args.reduced_cycles,
                    args.assert_bounds, args.source_json)


if __name__ == "__main__":
    main()
