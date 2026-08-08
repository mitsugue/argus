#!/usr/bin/env python3
"""32-cycle long-lived-parent proof for the fresh-process V2 writer."""
from __future__ import annotations

import argparse
import gc
import json
import os
import pathlib
import shutil
import sys
import tempfile
from typing import Optional

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import argus_checkpoint_v2 as v2  # noqa: E402
import argus_checkpoint_v2_isolated as isolated  # noqa: E402
import argus_persistent_storage as storage  # noqa: E402
from scripts.checkpoint_v2_resource_probe import (  # noqa: E402
    PRODUCTION_SHAPED_ROW_TARGET,
    load_snapshot,
)


def run(source_json: Optional[str], cycles: int, assert_proof: bool) -> dict:
    with tempfile.TemporaryDirectory(
            prefix="argus-v2-isolated-proof-") as temporary:
        persistent = pathlib.Path(temporary)
        source_path = persistent / "legacy.json"
        source = load_snapshot(source_json, 1.0)
        legacy = storage.write_checkpoint(
            str(source_path), source, temp_directory=str(persistent))
        del source
        gc.collect()
        receipt = {**legacy, "snapshotBytes": legacy["bytes"],
                   "includedWalSequence": 0,
                   "walCompaction": {"compactedThrough": 0}}
        parent_pid = os.getpid()
        baseline_fds = isolated._fd_count()
        baseline_threads = isolated._thread_count()
        rows = []
        child_pids = []
        for index in range(cycles):
            result = isolated.launch_isolated_generation(
                str(persistent / "v2"), source_path=str(source_path),
                legacy_checkpoint=receipt, wal_path=str(persistent / "wal"),
                wal_upper_sequence=0, backend_build_sha="a" * 40,
                backend_boot_id="isolated-proof-boot",
                mission_window_id=f"mw-isolated-proof-{index:02d}",
                trigger_source="ec2_systemd", timeout_seconds=900)
            telemetry = result["resourceTelemetry"]
            budget = v2.disk_budget_status(str(persistent / "v2"))
            child_pids.append(result["validation"]["childProcessId"])
            rows.append({
                "cycle": index + 1, "parentPid": parent_pid,
                "childPid": result["validation"]["childProcessId"],
                "verified": result["verified"],
                "generationBytes": result["databaseBytes"],
                "rowCount": telemetry.get("generationRowCount"),
                "sectionCount": telemetry.get("generationSectionCount"),
                "parentRssBeforeBytes": telemetry.get(
                    "processRssBeforeBytes"),
                "parentRssDuringBytes": telemetry.get(
                    "processRssPeakBytes"),
                "parentRssAfterBytes": telemetry.get(
                    "processRssAfterBytes"),
                "parentQuietRssBytes": telemetry.get(
                    "parentQuietRssBytes"),
                "parentPssBeforeBytes": telemetry.get(
                    "parentPssBeforeBytes"),
                "parentPssAfterBytes": telemetry.get("parentPssAfterBytes"),
                "parentFdBefore": telemetry.get("parentFdBefore"),
                "parentFdAfter": telemetry.get("parentFdAfter"),
                "parentThreadBefore": telemetry.get("parentThreadBefore"),
                "parentThreadAfter": telemetry.get("parentThreadAfter"),
                "childPeakRssBytes": telemetry.get("childPeakRssBytes"),
                "childDurationMs": telemetry.get("childDurationMs"),
                "childExitCode": telemetry.get("childExitCode"),
                "cgroupMemoryCurrentBytes": telemetry.get(
                    "cgroupMemoryAfterBytes"),
                "cgroupMemoryPeakBytes": telemetry.get(
                    "cgroupMemoryPeakBytes"),
                "pendingGenerationCount": budget[
                    "pendingGenerationCount"],
                "retainedGenerationCount": budget[
                    "retainedGenerationCount"],
                "diskFreeBytes": budget["freeBytes"],
            })
        rss = [int(row["parentRssAfterBytes"]) for row in rows[2:]
               if row["parentRssAfterBytes"] is not None]
        zombie_free = True
        try:
            child, _ = os.waitpid(-1, os.WNOHANG)
            zombie_free = child == 0
        except ChildProcessError:
            zombie_free = True
        report = {
            "schemaVersion": "argus-checkpoint-v2-isolated-32-cycle-proof-v1",
            "writerMode": isolated.WRITER_MODE,
            "cycles": cycles, "parentPid": parent_pid,
            "parentPidUnchanged": os.getpid() == parent_pid,
            "distinctChildProcessCount": len(set(child_pids)),
            "allVerified": all(row["verified"] for row in rows),
            "generationBytesMinimum": min(row["generationBytes"] for row in rows),
            "generationBytesMaximum": max(row["generationBytes"] for row in rows),
            "rowCountTarget": PRODUCTION_SHAPED_ROW_TARGET,
            "parentRssCycles3To32GrowthBytes": (
                max(rss) - min(rss) if len(rss) > 1 else 0),
            "childPeakMaximumBytes": max(
                int(row["childPeakRssBytes"] or 0) for row in rows),
            "cgroupMemoryMax": isolated.v2._read_int(
                ("/sys/fs/cgroup/memory.max",)),
            "cgroupPeakMaximumBytes": max(
                int(row["cgroupMemoryPeakBytes"] or 0) for row in rows),
            "fdGrowth": ((isolated._fd_count() or 0) - (baseline_fds or 0)
                         if baseline_fds is not None else None),
            "threadGrowth": isolated._thread_count() - baseline_threads,
            "zombieFree": zombie_free,
            "pendingMaximum": max(row["pendingGenerationCount"] for row in rows),
            "retainedMaximum": max(row["retainedGenerationCount"] for row in rows),
            "diskFreeMinimumBytes": min(row["diskFreeBytes"] for row in rows),
            "cyclesEvidence": rows,
        }
        if assert_proof:
            failures = []
            if cycles < 32 or not report["allVerified"]:
                failures.append("isolated_32_cycles_unverified")
            if report["distinctChildProcessCount"] != cycles or not report[
                    "parentPidUnchanged"]:
                failures.append("isolated_process_topology_failed")
            if report["pendingMaximum"] != 0 or report["retainedMaximum"] > 4:
                failures.append("isolated_generation_retention_failed")
            if report["parentRssCycles3To32GrowthBytes"] > 128 * 1024 ** 2:
                failures.append("isolated_parent_rss_plateau_failed")
            if report["cgroupMemoryMax"] != 4 * 1024 ** 3 or report[
                    "cgroupPeakMaximumBytes"] >= 3 * 1024 ** 3:
                failures.append("isolated_cgroup_resource_gate_failed")
            if report["diskFreeMinimumBytes"] < 1024 ** 3:
                failures.append("isolated_disk_reserve_failed")
            if report["fdGrowth"] not in (None, 0) or report[
                    "threadGrowth"] != 0 or not report["zombieFree"]:
                failures.append("isolated_parent_resource_leak")
            if not (
                    127 * 1024 ** 2 <= report["generationBytesMinimum"] <=
                    report["generationBytesMaximum"] <= 160 * 1024 ** 2):
                failures.append("isolated_production_shape_failed")
            if failures:
                raise SystemExit(failures[0])
        return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-json")
    parser.add_argument("--cycles", type=int, default=32)
    parser.add_argument("--assert-proof", action="store_true")
    args = parser.parse_args()
    print(json.dumps(run(args.source_json, args.cycles, args.assert_proof),
                     sort_keys=True))


if __name__ == "__main__":
    main()
