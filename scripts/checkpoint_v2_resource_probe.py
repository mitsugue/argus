#!/usr/bin/env python3
"""Production-shaped Checkpoint V2 write/restore resource probe."""
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


OBSERVED_SECTIONS_MIB = {
    "marketLedger": 59,
    "verifiedViewSnapshots": 26,
    "assetChartReports": 16,
    "chartIntelligence": 9,
    "marketReplay": 6,
    "todayIntelligence": 3,
}


def rss_bytes():
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(value if sys.platform == "darwin" else value * 1024)


def current_rss_bytes():
    status = pathlib.Path("/proc/self/status")
    if status.exists():
        for line in status.read_text().splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) * 1024
    return rss_bytes()


def snapshot(multiplier=1.0):
    result = {"schemaVersion": "argus-durable-v3"}
    for section, mib in OBSERVED_SECTIONS_MIB.items():
        blocks = max(1, int(mib * multiplier))
        result[section] = [
            {"block": index, "payload": chr(65 + index % 20) * (1024 * 1024 - 80)}
            for index in range(blocks)
        ]
    result.update({
        "missions": [{"missionId": f"m-{i}"} for i in range(120)],
        "missionWindows": [{"windowId": f"w-{i}"} for i in range(240)],
        "opsJournal": [{"sequence": i, "event": "verified"}
                       for i in range(400)],
        "opsJournalCompacted": [{"sequence": i} for i in range(40)],
        "remoteAck": {"maximumSequence": 400},
    })
    return result


def worker(mode, root, multiplier):
    before = rss_bytes()
    if mode == "write":
        value = snapshot(multiplier)
        result = v2.write_generation(
            root, value, source_generation="resource-probe")
        del value
    else:
        result = v2.restore_generation(root, include_archived=False)
        del result["snapshot"]
    gc.collect()
    print(json.dumps({"mode": mode, "peakRssBytes": rss_bytes(),
                      "baselineRssBytes": before,
                      "deltaRssBytes": rss_bytes() - before,
                      "verified": result["verified"]}, sort_keys=True))


def repeated_worker(root, multiplier, cycles):
    samples = [current_rss_bytes()]
    for index in range(cycles):
        value = snapshot(multiplier)
        v2.write_generation(root, value,
                            source_generation=f"reduced-{index}")
        del value
        restored = v2.restore_generation(root, include_archived=False)
        del restored["snapshot"], restored
        gc.collect()
        time.sleep(0.01)
        samples.append(current_rss_bytes())
    paths = list(pathlib.Path(root).iterdir())
    report = {
        "mode": "repeated", "cycles": cycles,
        "startingRssBytes": samples[0], "endingRssBytes": samples[-1],
        "retainedGrowthBytes": max(0, samples[-1] - samples[0]),
        "maximumCurrentRssBytes": max(samples), "peakRssBytes": rss_bytes(),
        "pendingGenerationCount": sum(
            path.name.startswith(".v2-pending-") for path in paths),
        "retainedGenerationCount": sum(
            path.name.startswith("v2-generation-") for path in paths),
        "samples": samples,
    }
    print(json.dumps(report, sort_keys=True))


def run_child(mode, root, multiplier):
    completed = subprocess.run(
        [sys.executable, __file__, "--worker", mode, "--root", root,
         "--multiplier", str(multiplier)],
        check=True, capture_output=True, text=True)
    return json.loads(completed.stdout.strip().splitlines()[-1])


def orchestrate(full_cycles, reduced_cycles, assert_bounds):
    results = []
    with tempfile.TemporaryDirectory(prefix="argus-checkpoint-v2-probe-") as root:
        for _ in range(full_cycles):
            results.append(run_child("write", root, 1.0))
            results.append(run_child("restore", root, 1.0))
        completed = subprocess.run(
            [sys.executable, __file__, "--worker", "repeated", "--root", root,
             "--multiplier", "0.05", "--reduced-cycles",
             str(reduced_cycles)], check=True, capture_output=True, text=True)
        repeated = json.loads(completed.stdout.strip().splitlines()[-1])
    maximum = max(row["peakRssBytes"] for row in results)
    maximum_delta = max(row["deltaRssBytes"] for row in results)
    report = {
        "schemaVersion": "argus-checkpoint-v2-resource-proof-v1",
        "fullCycles": full_cycles, "reducedCycles": reduced_cycles,
        "processRuns": len(results), "maximumPeakRssBytes": maximum,
        "maximumDeltaRssBytes": maximum_delta,
        "cgroupMemoryMax": pathlib.Path("/sys/fs/cgroup/memory.max").read_text().strip()
        if pathlib.Path("/sys/fs/cgroup/memory.max").exists() else None,
        "results": results, "repeated": repeated,
    }
    print(json.dumps(report, sort_keys=True))
    if assert_bounds:
        if report["cgroupMemoryMax"] not in (str(4 * 1024 ** 3),):
            raise SystemExit("expected_exact_4gib_cgroup")
        if maximum > 3 * 1024 ** 3 or maximum_delta > 512 * 1024 ** 2:
            raise SystemExit("checkpoint_v2_memory_bound_exceeded")
        if repeated["retainedGrowthBytes"] >= 128 * 1024 ** 2:
            raise SystemExit("checkpoint_v2_retained_growth_exceeded")
        if repeated["pendingGenerationCount"] or \
                repeated["retainedGenerationCount"] > v2.MAXIMUM_GENERATIONS:
            raise SystemExit("checkpoint_v2_generation_accumulation")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", choices=("write", "restore", "repeated"))
    parser.add_argument("--root")
    parser.add_argument("--multiplier", type=float, default=1.0)
    parser.add_argument("--full-cycles", type=int, default=3)
    parser.add_argument("--reduced-cycles", type=int, default=50)
    parser.add_argument("--assert-bounds", action="store_true")
    args = parser.parse_args()
    if args.worker == "repeated":
        repeated_worker(args.root, args.multiplier, args.reduced_cycles)
    elif args.worker:
        worker(args.worker, args.root, args.multiplier)
    else:
        orchestrate(args.full_cycles, args.reduced_cycles,
                    args.assert_bounds)


if __name__ == "__main__":
    main()
