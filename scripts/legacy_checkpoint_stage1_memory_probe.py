#!/usr/bin/env python3
"""Long-lived legacy checkpoint + isolated Stage-1 writer RSS proof.

The public source is held as the authoritative in-process state.  Every cycle
runs in a fresh request-shaped thread, constructs an independent legacy
snapshot, seals and atomically verifies it, releases both temporary owners,
and launches the real isolated V2 writer.  Artifacts contain only aggregate
resource and integrity measurements.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import pathlib
import threading
import time
from typing import Any, Dict

ROOT = pathlib.Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0, str(ROOT))

import argus_checkpoint_v2 as v2  # noqa: E402
import argus_checkpoint_v2_isolated as isolated  # noqa: E402
import argus_persistent_storage as storage  # noqa: E402
import argus_tick_durability as durability  # noqa: E402
from scripts.checkpoint_v2_resource_probe import (  # noqa: E402
    cgroup_value, current_rss_bytes, smaps_rollup_bytes)

MINIMUM_CYCLES = 32
WARMUP_CYCLES = 2
PLATEAU_CYCLES = 6
RSS_GROWTH_LIMIT = 128 * 1024 ** 2
PLATEAU_SPAN_LIMIT = 64 * 1024 ** 2
CGROUP_PEAK_LIMIT = 3 * 1024 ** 3


def _fd_count():
    try:
        return len(list(pathlib.Path("/proc/self/fd").iterdir()))
    except OSError:
        return None


def _thread_count():
    try:
        return len(list(pathlib.Path("/proc/self/task").iterdir()))
    except OSError:
        return threading.active_count()


def _band(values):
    return {
        "first": values[0], "last": values[-1],
        "minimum": min(values), "maximum": max(values),
        "growth": values[-1] - values[0],
        "span": max(values) - min(values),
        "strictlyMonotonic": len(values) > 1 and all(
            right > left for left, right in zip(values, values[1:])),
    }


def _one_cycle(index: int, *, authoritative: Dict[str, Any], root: pathlib.Path,
               candidate: bool, holder: Dict[str, Any]) -> None:
    try:
        legacy_path = root / "argus_osint_memory.json"
        wal_path = root / "argus_mission_tick.wal"
        wal_path.touch(exist_ok=True)
        blob = copy.deepcopy(authoritative)
        blob["schemaVersion"] = "argus-durable-v3"
        sealed = storage.seal_checkpoint(blob)
        checkpoint = durability.verified_checkpoint(
            str(legacy_path), sealed, job_id=f"memory-probe-{index}",
            wal_path=str(wal_path), included_sequence=0,
            allow_wal_compaction=False, build_sha="resource-proof",
            mission_window_id=f"mw-resource-proof-{index:02d}")
        del blob, sealed
        if candidate:
            reclaim = v2.release_consumed_legacy_snapshot_memory(
                int(checkpoint.get("snapshotBytes") or 0))
        else:
            reclaim = {
                "attempted": False, "supported": True,
                "sourceBytes": int(checkpoint.get("snapshotBytes") or 0),
                "rssBeforeBytes": current_rss_bytes(),
                "rssAfterBytes": current_rss_bytes(),
                "rssReleasedBytes": 0,
                "reportedReleasedBytes": None,
                "testVariant": "pre_fix_without_parent_reclaim",
            }
        result = isolated.launch_isolated_generation(
            str(root / "argus_checkpoint_v2"),
            source_path=str(legacy_path), legacy_checkpoint=checkpoint,
            wal_path=str(wal_path), wal_upper_sequence=0,
            backend_build_sha="resource-proof",
            backend_boot_id="resource-proof-boot",
            mission_window_id=f"mw-resource-proof-{index:02d}",
            trigger_source="ec2_systemd",
            formal_soak_state="not_started")
        holder["result"] = {
            "legacyVerified": bool(checkpoint.get("verified")),
            "legacyReadBackVerified": bool(
                checkpoint.get("readBackVerified")),
            "v2Verified": bool(result.get("verified")),
            "childExitClassification": (
                result.get("childExitClassification") or
                (result.get("resourceTelemetry") or {}).get(
                    "childExitClassification")),
            "childExitCode": (result.get("resourceTelemetry") or {}).get(
                "childExitCode"),
            "childPeakRssBytes": (result.get("resourceTelemetry") or {}).get(
                "childPeakRssBytes"),
            "generationBytes": result.get("databaseBytes"),
            "generationRows": (result.get("resourceTelemetry") or {}).get(
                "generationRowCount"),
            "generationSections": result.get("sectionCount"),
            "pendingGenerations": (result.get("resourceTelemetry") or {}).get(
                "pendingGenerationCount"),
            "retainedGenerations": isolated.public_telemetry(result).get(
                "retainedGenerationCount"),
            "allocatorReclaim": reclaim,
        }
    except BaseException as exc:  # artifact records class only; no payload
        holder["errorClass"] = type(exc).__name__
        holder["errorClassification"] = str(
            getattr(exc, "classification", type(exc).__name__))[:120]


def run(*, source_json: str, root: str, variant: str, cycles: int):
    authoritative = json.loads(pathlib.Path(source_json).read_text(
        encoding="utf-8"))
    if not isinstance(authoritative, dict) or not authoritative:
        raise SystemExit("source_invalid")
    # The public snapshot can be captured after an arbitrary production WAL
    # sequence.  This resource proof uses an intentionally empty test WAL, so
    # align only its bounded durability counters with that exact zero boundary;
    # no production file or substantive checkpoint section is changed.
    durability_state = authoritative.get("missionTickDurability")
    if isinstance(durability_state, dict):
        durability_state.update({
            "walAppliedSequence": 0,
            "remoteWalAppliedSequence": 0,
            "verifiedWalSequence": 0,
            "compactReceiptHash": None,
        })
    run_root = pathlib.Path(root).resolve()
    run_root.mkdir(parents=True, exist_ok=True)
    baseline = {
        "rssBytes": current_rss_bytes(),
        "cgroupCurrentBytes": cgroup_value("memory.current"),
        "cgroupPeakBytes": cgroup_value("memory.peak"),
        "fdCount": _fd_count(), "threadCount": _thread_count(),
        **smaps_rollup_bytes(),
    }
    records = []
    candidate = variant == "candidate"
    for index in range(1, cycles + 1):
        holder: Dict[str, Any] = {}
        request = threading.Thread(
            target=_one_cycle, name=f"memory-probe-request-{index}",
            kwargs={"index": index, "authoritative": authoritative,
                    "root": run_root, "candidate": candidate,
                    "holder": holder})
        request.start()
        request.join()
        time.sleep(0.25)
        record = {
            "cycle": index, **holder,
            "rssBytes": current_rss_bytes(),
            "cgroupCurrentBytes": cgroup_value("memory.current"),
            "cgroupPeakBytes": cgroup_value("memory.peak"),
            "fdCount": _fd_count(), "threadCount": _thread_count(),
            **smaps_rollup_bytes(),
        }
        records.append(record)
        print(json.dumps({
            "schemaVersion": "argus-legacy-parent-memory-progress-v1",
            "variant": variant, "cycle": index,
            "rssBytes": record["rssBytes"],
            "anonymousBytes": record.get("AnonymousBytes"),
            "cgroupCurrentBytes": record["cgroupCurrentBytes"],
            "cgroupPeakBytes": record["cgroupPeakBytes"],
            "legacyVerified": (record.get("result") or {}).get(
                "legacyVerified"),
            "v2Verified": (record.get("result") or {}).get("v2Verified"),
            "errorClass": record.get("errorClass"),
        }, sort_keys=True), flush=True)
        if holder.get("errorClass"):
            break

    completed = len(records)
    successful = [row for row in records if not row.get("errorClass")]
    steady = successful[WARMUP_CYCLES:]
    rss = [int(row.get("rssBytes") or 0) for row in steady]
    anonymous = [int(row.get("Pss_AnonBytes") or 0) for row in steady]
    cgroup_peak = max((int(row.get("cgroupPeakBytes") or 0)
                       for row in records), default=0)
    failures = []
    if completed < cycles or len(successful) < cycles:
        failures.append("cycle_completion_failed")
    for row in successful:
        result = row.get("result") or {}
        if not (result.get("legacyVerified") and
                result.get("legacyReadBackVerified") and
                result.get("v2Verified")):
            failures.append("integrity_verification_failed")
        if result.get("childExitCode") not in (0, None) or \
                result.get("childExitClassification") not in (
                    "success", None):
            failures.append("isolated_writer_failed")
        if int(result.get("pendingGenerations") or 0) != 0 or \
                int(result.get("retainedGenerations") or 0) > 4:
            failures.append("generation_retention_failed")
    if rss:
        rss_band = _band(rss)
        if rss_band["growth"] >= RSS_GROWTH_LIMIT:
            failures.append("parent_rss_growth_exceeded")
        plateau = _band(rss[-PLATEAU_CYCLES:])
        if plateau["span"] > PLATEAU_SPAN_LIMIT:
            failures.append("parent_rss_plateau_failed")
    else:
        rss_band = plateau = None
    if cgroup_peak >= CGROUP_PEAK_LIMIT:
        failures.append("cgroup_peak_exceeded")
    if baseline["fdCount"] is not None and records and \
            records[-1]["fdCount"] > baseline["fdCount"]:
        failures.append("descriptor_growth")
    if baseline["threadCount"] is not None and records and \
            records[-1]["threadCount"] > baseline["threadCount"]:
        failures.append("thread_growth")
    failures = sorted(set(failures))
    if completed < cycles:
        classification = "INCONCLUSIVE"
    else:
        classification = "FAIL" if failures else "PASS"
    summary = {
        "schemaVersion": "argus-legacy-parent-memory-proof-v1",
        "variant": variant, "requestedCycles": cycles,
        "completedCycles": completed,
        "successfulCycles": len(successful),
        "finalClassification": classification,
        "failures": failures,
        "baseline": baseline,
        "rssBandAfterWarmup": rss_band,
        "anonymousBandAfterWarmup": _band(anonymous) if anonymous else None,
        "plateauWindowCycles": min(PLATEAU_CYCLES, len(rss)),
        "plateauRssBand": plateau,
        "cgroupPeakBytes": cgroup_peak,
        "maximumChildPeakRssBytes": max((int(
            (row.get("result") or {}).get("childPeakRssBytes") or 0)
            for row in successful), default=0),
        "maximumRetainedGenerations": max((int(
            (row.get("result") or {}).get("retainedGenerations") or 0)
            for row in successful), default=0),
        "maximumPendingGenerations": max((int(
            (row.get("result") or {}).get("pendingGenerations") or 0)
            for row in successful), default=0),
        "oomObserved": any(row.get("errorClassification") == "child_oom"
                           for row in records),
        "writerErrors": sorted(set(
            row.get("errorClassification") for row in records
            if row.get("errorClassification"))),
        "integrityMode": "legacy_stream_hash_readback_plus_isolated_v2",
        "legacyRestoreAuthority": True,
        "v2RestoreAuthority": False,
        "formalSoakState": "not_started",
        "records": records,
    }
    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-json", required=True)
    parser.add_argument("--root", required=True)
    parser.add_argument("--variant", choices=("pre_fix", "candidate"),
                        required=True)
    parser.add_argument("--cycles", type=int, default=MINIMUM_CYCLES)
    parser.add_argument("--output", required=True)
    parser.add_argument("--expect", choices=("PASS", "FAIL", "INCONCLUSIVE"))
    args = parser.parse_args()
    if args.cycles < MINIMUM_CYCLES:
        raise SystemExit("minimum_32_cycles_required")
    summary = run(source_json=args.source_json, root=args.root,
                  variant=args.variant, cycles=args.cycles)
    pathlib.Path(args.output).write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    print(json.dumps({key: summary[key] for key in (
        "schemaVersion", "variant", "requestedCycles", "completedCycles",
        "successfulCycles", "finalClassification", "failures",
        "rssBandAfterWarmup", "plateauRssBand", "cgroupPeakBytes",
        "maximumChildPeakRssBytes", "oomObserved", "writerErrors")},
        sort_keys=True))
    if args.expect and summary["finalClassification"] != args.expect:
        raise SystemExit("unexpected_classification")


if __name__ == "__main__":
    main()
