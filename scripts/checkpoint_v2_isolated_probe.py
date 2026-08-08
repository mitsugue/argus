#!/usr/bin/env python3
"""32-cycle long-lived-parent proof for the fresh-process V2 writer."""
from __future__ import annotations

import argparse
import concurrent.futures
import gc
import json
import os
import pathlib
import sqlite3
import subprocess
import sys
import tempfile
import threading
from typing import Optional

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import argus_checkpoint_v2 as v2  # noqa: E402
import argus_checkpoint_v2_isolated as isolated  # noqa: E402
import argus_persistent_storage as storage  # noqa: E402
import argus_tick_durability as durability  # noqa: E402
from scripts.checkpoint_v2_resource_probe import (  # noqa: E402
    PRODUCTION_SHAPED_ROW_TARGET,
    load_snapshot,
)


WAL_DELTA_PER_CYCLE = 17
SYNTHETIC_WAL_BASE = 5000


def _runtime_counts() -> dict:
    gc.collect()
    connections = cursors = futures = 0
    for value in gc.get_objects():
        try:
            connections += isinstance(value, sqlite3.Connection)
            cursors += isinstance(value, sqlite3.Cursor)
            futures += isinstance(value, concurrent.futures.Future)
        except ReferenceError:
            continue
    return {
        "connections": connections, "cursors": cursors,
        "futures": futures, "fds": isolated._fd_count(),
        "threads": threading.active_count(),
    }


def prepare_fixture(root: str, source_json: Optional[str], cycle: int) -> dict:
    """Build one real compacted nonzero WAL/source pair in a short process."""
    persistent = pathlib.Path(root).resolve()
    persistent.mkdir(parents=True, exist_ok=True)
    source_path = persistent / "legacy.json"
    wal_path = persistent / "wal.jsonl"
    source = load_snapshot(source_json, 1.0)
    durability_state = source.get("missionTickDurability")
    if not isinstance(durability_state, dict):
        if source_json:
            raise SystemExit("fixture_source_wal_cursor_not_exact")
        durability_state = {}
        source["missionTickDurability"] = durability_state
    original = durability_state.get("walAppliedSequence")
    if original is None and not source_json:
        original = 0
    if isinstance(original, bool) or not isinstance(original, int) or original < 0:
        raise SystemExit("fixture_source_wal_cursor_not_exact")
    base = original if original > 0 else SYNTHETIC_WAL_BASE
    target = base + int(cycle) * WAL_DELTA_PER_CYCLE
    lower = target - WAL_DELTA_PER_CYCLE
    durability_state["walAppliedSequence"] = target
    legacy = storage.write_checkpoint(
        str(source_path), source, temp_directory=str(persistent))
    del source
    gc.collect()
    wal_path.unlink(missing_ok=True)
    # Seed the compacted anchor, append a real contiguous target interval,
    # then use the production compactor.  The final live WAL contains
    # lower+1..target plus the narrowly permitted checkpoint receipt.
    for sequence in range(lower, target + 1):
        durability.append_wal(
            str(wal_path), sequence=sequence, kind="fixture_noop",
            payload={"fixture": "isolated-resource-proof",
                     "sequence": sequence},
            job_id=f"isolated-proof-{cycle:02d}",
            mission_window_id=f"mw-isolated-proof-{cycle:02d}",
            build_sha="a" * 40)
    compaction = durability.compact_verified_wal(
        str(wal_path), included_sequence=lower,
        receipt={
            "jobId": f"isolated-proof-{cycle:02d}",
            "snapshotHash": legacy["snapshotHash"],
            "includedWalSequence": lower,
            "buildSha": "a" * 40,
            "missionWindowId": f"mw-isolated-proof-{cycle:02d}",
        })
    receipt = {**legacy, "snapshotBytes": legacy["bytes"],
               "includedWalSequence": target, "walCompaction": compaction}
    validated = isolated._validate_wal_contract(
        wal_path, lower=lower, upper=target)
    return {
        "fixtureProcessId": os.getpid(), "sourcePath": str(source_path),
        "walPath": str(wal_path), "receipt": receipt,
        "originalSourceCursor": original, "lowerSequence": lower,
        "targetSequence": target, "walValidation": validated,
    }


def _prepare_fixture_subprocess(root: pathlib.Path,
                                source_json: Optional[str], cycle: int) -> dict:
    command = [sys.executable, "-B", str(pathlib.Path(__file__).resolve()),
               "--prepare-fixture-root", str(root),
               "--fixture-cycle", str(cycle)]
    if source_json:
        command.extend(["--source-json", source_json])
    completed = subprocess.run(
        command, check=True, capture_output=True, text=True)
    return json.loads(completed.stdout.strip())


def run(source_json: Optional[str], cycles: int, assert_proof: bool) -> dict:
    with tempfile.TemporaryDirectory(
            prefix="argus-v2-isolated-proof-") as temporary:
        persistent = pathlib.Path(temporary)
        gc.collect()
        parent_pid = os.getpid()
        baseline_resources = _runtime_counts()
        rows = []
        child_pids = []
        for index in range(cycles):
            fixture = _prepare_fixture_subprocess(
                persistent, source_json, index + 1)
            source_path = pathlib.Path(fixture["sourcePath"])
            wal_path = pathlib.Path(fixture["walPath"])
            receipt = fixture["receipt"]
            result = isolated.launch_isolated_generation(
                str(persistent / "v2"), source_path=str(source_path),
                legacy_checkpoint=receipt, wal_path=str(wal_path),
                wal_upper_sequence=fixture["targetSequence"],
                backend_build_sha="a" * 40,
                backend_boot_id="isolated-proof-boot",
                mission_window_id=f"mw-isolated-proof-{index:02d}",
                trigger_source="ec2_systemd", timeout_seconds=900)
            telemetry = result["resourceTelemetry"]
            budget = v2.disk_budget_status(str(persistent / "v2"))
            current_resources = _runtime_counts()
            staging_count = len(list(
                (persistent / "v2").glob(f"{isolated.JOB_PREFIX}*")))
            pending_count = len(list(
                (persistent / "v2").glob(".v2-pending-*")))
            child_pids.append(result["validation"]["childProcessId"])
            rows.append({
                "cycle": index + 1, "parentPid": parent_pid,
                "fixtureProcessId": fixture["fixtureProcessId"],
                "originalSourceCursor": fixture["originalSourceCursor"],
                "childPid": result["validation"]["childProcessId"],
                "verified": result["verified"],
                "generationId": result["generationId"],
                "generationBytes": result["databaseBytes"],
                "rowCount": telemetry.get("generationRowCount"),
                "sectionCount": telemetry.get("generationSectionCount"),
                "walLowerSequence": result["validation"].get(
                    "walLowerSequence"),
                "walTargetSequence": result["validation"].get(
                    "walTargetSequence"),
                "walReconstructedSequence": result["validation"].get(
                    "walReconstructedSequence"),
                "walHashVerified": result["validation"].get(
                    "walHashVerified"),
                "walFramingVerified": result["validation"].get(
                    "walFramingVerified"),
                "manifestPromoted": result["validation"].get(
                    "manifestPromoted"),
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
                "parentConnectionCount": current_resources["connections"],
                "parentCursorCount": current_resources["cursors"],
                "parentFutureCount": current_resources["futures"],
                "childPeakRssBytes": telemetry.get("childPeakRssBytes"),
                "childDurationMs": telemetry.get("childDurationMs"),
                "childExitCode": telemetry.get("childExitCode"),
                "cgroupMemoryCurrentBytes": telemetry.get(
                    "cgroupMemoryAfterBytes"),
                "cgroupMemoryPeakBytes": telemetry.get(
                    "cgroupMemoryPeakBytes"),
                "cgroupMemoryLifetimePeakBytes": telemetry.get(
                    "cgroupMemoryLifetimePeakBytes"),
                "pendingGenerationCount": max(
                    budget["pendingGenerationCount"], pending_count),
                "retainedGenerationCount": budget[
                    "retainedGenerationCount"],
                "stagingOrphanCount": staging_count,
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
            "distinctFixtureProcessCount": len(set(
                row["fixtureProcessId"] for row in rows)),
            "parentNeverLoadedGenerationSource": True,
            "allVerified": all(row["verified"] for row in rows),
            "allWalExact": all(
                row["walTargetSequence"] == row["walReconstructedSequence"]
                and row["walHashVerified"] is True
                and row["walFramingVerified"] is True for row in rows),
            "walStartSequence": rows[0]["walTargetSequence"],
            "walFinalSequence": rows[-1]["walTargetSequence"],
            "originalSourceCursor": rows[0]["originalSourceCursor"],
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
            "cgroupLifetimePeakBytes": max(
                int(row["cgroupMemoryLifetimePeakBytes"] or 0)
                for row in rows),
            "fdGrowth": ((_runtime_counts()["fds"] or 0) -
                         (baseline_resources["fds"] or 0)
                         if baseline_resources["fds"] is not None else None),
            "threadGrowth": (_runtime_counts()["threads"] -
                             baseline_resources["threads"]),
            "connectionGrowth": (_runtime_counts()["connections"] -
                                 baseline_resources["connections"]),
            "cursorGrowth": (_runtime_counts()["cursors"] -
                             baseline_resources["cursors"]),
            "futureGrowth": (_runtime_counts()["futures"] -
                             baseline_resources["futures"]),
            "zombieFree": zombie_free,
            "pendingMaximum": max(row["pendingGenerationCount"] for row in rows),
            "retainedMaximum": max(row["retainedGenerationCount"] for row in rows),
            "orphanMaximum": max(row["stagingOrphanCount"] for row in rows),
            "diskFreeMinimumBytes": min(row["diskFreeBytes"] for row in rows),
            "cyclesEvidence": rows,
        }
        if assert_proof:
            failures = []
            if cycles < 32 or not report["allVerified"]:
                failures.append("isolated_32_cycles_unverified")
            if not report["allWalExact"] or report["walStartSequence"] <= 0:
                failures.append("isolated_nonzero_wal_contract_failed")
            if report["distinctChildProcessCount"] != cycles or not report[
                    "parentPidUnchanged"]:
                failures.append("isolated_process_topology_failed")
            if report["pendingMaximum"] != 0 or report["retainedMaximum"] > 4:
                failures.append("isolated_generation_retention_failed")
            if report["parentRssCycles3To32GrowthBytes"] > 128 * 1024 ** 2:
                failures.append("isolated_parent_rss_plateau_failed")
            if report["cgroupMemoryMax"] != 4 * 1024 ** 3 or report[
                    "cgroupLifetimePeakBytes"] >= 3 * 1024 ** 3:
                failures.append("isolated_cgroup_resource_gate_failed")
            if report["diskFreeMinimumBytes"] < 1024 ** 3:
                failures.append("isolated_disk_reserve_failed")
            if report["fdGrowth"] not in (None, 0) or report[
                    "threadGrowth"] != 0 or report["connectionGrowth"] != 0 or \
                    report["cursorGrowth"] != 0 or report["futureGrowth"] != 0 or \
                    not report["zombieFree"] or report["orphanMaximum"] != 0:
                failures.append("isolated_parent_resource_leak")
            if not (
                    127 * 1024 ** 2 <= report["generationBytesMinimum"] <=
                    report["generationBytesMaximum"] <= 160 * 1024 ** 2):
                failures.append("isolated_production_shape_failed")
            if not all(
                    40_000 <= int(row["rowCount"] or 0) <= 50_000 and
                    35 <= int(row["sectionCount"] or 0) <= 55 and
                    row["manifestPromoted"] is True
                    for row in rows):
                failures.append("isolated_production_shape_failed")
            if failures:
                raise SystemExit(failures[0])
        return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-json")
    parser.add_argument("--cycles", type=int, default=32)
    parser.add_argument("--assert-proof", action="store_true")
    parser.add_argument("--prepare-fixture-root")
    parser.add_argument("--fixture-cycle", type=int)
    args = parser.parse_args()
    if args.prepare_fixture_root:
        if args.fixture_cycle is None or args.fixture_cycle <= 0:
            raise SystemExit("fixture_cycle_required")
        result = prepare_fixture(
            args.prepare_fixture_root, args.source_json, args.fixture_cycle)
    else:
        result = run(args.source_json, args.cycles, args.assert_proof)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
