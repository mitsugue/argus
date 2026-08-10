#!/usr/bin/env python3
"""CI-safe bounded memory-attribution lifecycle proof.

The probe exercises diagnostic capture only.  It never writes a checkpoint,
WAL, Remote Journal record, or V2 generation.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
import threading
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import argus_memory_attribution as memory


def _rss() -> object:
    metrics = memory.process_metrics()
    current = metrics.get("vmRssBytes", memory.UNKNOWN)
    return (metrics.get("rssPeakBytes", memory.UNKNOWN)
            if current == memory.UNKNOWN else current)


def _difference(before, after):
    if isinstance(before, int) and isinstance(after, int):
        return after - before
    return memory.UNKNOWN


def _run_cycle(recorder, index: int, *, stage1: bool):
    mode = "stage1" if stage1 else "legacy"
    key = f"{mode}-{index}"
    recorder.begin(key, {
        "missionWindowId": f"mw-{mode}-{index}",
        "triggerSource": "github_schedule" if stage1 else "ec2_systemd",
        "scheduledAt": "2026-08-10T00:00:00Z",
        "actualAt": "2026-08-10T00:00:01Z",
        "checkpointWriteNumber": index + 1,
        "stage1EffectiveState": "enabled" if stage1 else "disabled",
        "v2GenerationAttempted": stage1,
        "v2GenerationId": f"generation-{index}" if stage1 else None,
        "legacyCheckpointAttempted": True,
    })
    for phase in ("T1", "T2", "T3", "T4", "T5"):
        recorder.capture(key, phase)
    if stage1:
        for phase in ("T6", "T7", "T8", "T9", "T10"):
            recorder.capture(key, phase)
    else:
        recorder.mark_not_applicable(
            key, ("T6", "T7", "T8", "T9", "T10"),
            reason="checkpoint_v2_disabled")
    recorder.capture(key, "T11")
    recorder.capture(key, "T12")
    return recorder.complete(key)


def run(cycles: int = 32, bounded_cycles: int = 100):
    started = time.monotonic()
    rss_before = _rss()
    fd_before = memory.process_metrics().get("fdCount", memory.UNKNOWN)
    threads_before = threading.active_count()
    legacy = memory.MemoryAttributionRecorder(16)
    stage1 = memory.MemoryAttributionRecorder(16)
    bounded = memory.MemoryAttributionRecorder(16)
    for index in range(cycles):
        _run_cycle(legacy, index, stage1=False)
        _run_cycle(stage1, index, stage1=True)
    for index in range(bounded_cycles):
        _run_cycle(bounded, index, stage1=False)
    rss_after = _rss()
    fd_after = memory.process_metrics().get("fdCount", memory.UNKNOWN)
    threads_after = threading.active_count()
    legacy_view = legacy.view()
    stage1_view = stage1.view()
    bounded_view = bounded.view()
    legacy_last = legacy_view["records"][-1]
    stage1_last = stage1_view["records"][-1]
    rss_growth = _difference(rss_before, rss_after)
    fd_growth = _difference(fd_before, fd_after)
    checks = {
        "legacyCyclesComplete": legacy_view["completedCount"] == cycles,
        "stage1CyclesComplete": stage1_view["completedCount"] == cycles,
        "boundedHistory100": (
            bounded_view["completedCount"] == bounded_cycles and
            bounded_view["historyCount"] == 16),
        "legacyV2NotApplicable": all(
            legacy_last["phases"][phase]["status"] == memory.NOT_APPLICABLE
            for phase in ("T6", "T7", "T8", "T9", "T10")),
        "stage1AllPhasesCaptured": all(
            stage1_last["phases"][phase]["status"] == "CAPTURED"
            for phase in memory.PHASES),
        "phaseOrderExact": (
            legacy_last["phaseOrder"] == list(memory.PHASES) and
            stage1_last["phaseOrder"] == list(memory.PHASES)),
        "historyBelow2MiB": max(
            legacy_view["historySerializedBytes"],
            stage1_view["historySerializedBytes"],
            bounded_view["historySerializedBytes"]) < 2 * 1024 * 1024,
        "rssGrowthBelow128MiB": (
            rss_growth == memory.UNKNOWN or rss_growth < 128 * 1024 * 1024),
        "fdStable": fd_growth == memory.UNKNOWN or fd_growth == 0,
        "threadsStable": threads_after == threads_before,
    }
    return {
        "schemaVersion": "argus-memory-attribution-probe-v1",
        "cyclesPerMode": cycles,
        "boundedHistoryCycles": bounded_cycles,
        "historyLimit": 16,
        "legacyCompleted": legacy_view["completedCount"],
        "stage1Completed": stage1_view["completedCount"],
        "boundedCompleted": bounded_view["completedCount"],
        "rssBeforeBytes": rss_before,
        "rssAfterBytes": rss_after,
        "rssGrowthBytes": rss_growth,
        "fdBefore": fd_before,
        "fdAfter": fd_after,
        "fdGrowth": fd_growth,
        "threadsBefore": threads_before,
        "threadsAfter": threads_after,
        "maximumHistorySerializedBytes": max(
            legacy_view["historySerializedBytes"],
            stage1_view["historySerializedBytes"],
            bounded_view["historySerializedBytes"]),
        "elapsedMs": round((time.monotonic() - started) * 1000, 3),
        "checks": checks,
        "passed": all(checks.values()),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cycles", type=int, default=32)
    parser.add_argument("--bounded-cycles", type=int, default=100)
    parser.add_argument("--output")
    args = parser.parse_args()
    report = run(max(32, args.cycles), max(100, args.bounded_cycles))
    encoded = json.dumps(report, indent=2, sort_keys=True)
    print(encoded)
    if args.output:
        pathlib.Path(args.output).write_text(encoded + "\n", encoding="utf-8")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
