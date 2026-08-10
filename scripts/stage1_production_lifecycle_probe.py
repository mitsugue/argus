#!/usr/bin/env python3
"""Long-lived production lifecycle proof for Checkpoint V2 Stage 1.

This probe uses the real Flask mission-tick route and the real legacy
checkpoint/V2 isolated-writer path in one long-lived parent.  Provider work is
replaced with deterministic no-I/O results; persistence, normalization, state
hashing, legacy sealing/read-back, WAL validation, child validation,
promotion, pruning, and request teardown are not replaced.  The source is the
privacy-safe exact public-state artifact produced by the gate.
"""
from __future__ import annotations

import argparse
import contextlib
import gc
import json
import os
import pathlib
import sqlite3
import sys
import threading
import time
import tracemalloc
import types
from datetime import datetime, timedelta, timezone
from typing import Any, Dict
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.checkpoint_v2_resource_probe import (  # noqa: E402
    cgroup_value, current_rss_bytes, smaps_rollup_bytes)


MINIMUM_CYCLES = 32
WARMUP_CYCLES = 2
PLATEAU_CYCLES = 6
RSS_GROWTH_LIMIT = 128 * 1024 ** 2
PLATEAU_SPAN_LIMIT = 64 * 1024 ** 2
CGROUP_PEAK_LIMIT = 3 * 1024 ** 3
TRACE_DIAGNOSTIC_CYCLES = frozenset({1, 2, 4, 8, 16, 32})


def _band(values):
    return {
        "first": values[0], "last": values[-1],
        "minimum": min(values), "maximum": max(values),
        "growth": values[-1] - values[0],
        "span": max(values) - min(values),
        "strictlyMonotonic": len(values) > 1 and all(
            right > left for left, right in zip(values, values[1:])),
    }


def _fd_count():
    for path in (pathlib.Path("/proc/self/fd"), pathlib.Path("/dev/fd")):
        try:
            return len(list(path.iterdir()))
        except OSError:
            pass
    return None


def _thread_count():
    try:
        return len(list(pathlib.Path("/proc/self/task").iterdir()))
    except OSError:
        return threading.active_count()


def _mapping_counts():
    result = {"mappingCount": None, "sqliteOrTempMappingCount": None}
    try:
        lines = pathlib.Path("/proc/self/maps").read_text().splitlines()
    except (FileNotFoundError, OSError):
        return result
    result["mappingCount"] = len(lines)
    result["sqliteOrTempMappingCount"] = sum(
        "checkpoint-v2.sqlite" in line or ".v2-isolated-job-" in line
        for line in lines)
    return result


def _python_owner_counts():
    counts = {"dict": 0, "list": 0, "future": 0,
              "sqliteConnection": 0, "sqliteCursor": 0}
    future_type = None
    try:
        import concurrent.futures
        future_type = concurrent.futures.Future
    except ImportError:
        pass
    for value in gc.get_objects():
        try:
            if isinstance(value, dict):
                counts["dict"] += 1
            elif isinstance(value, list):
                counts["list"] += 1
            if future_type is not None and isinstance(value, future_type):
                counts["future"] += 1
            counts["sqliteConnection"] += isinstance(
                value, sqlite3.Connection)
            counts["sqliteCursor"] += isinstance(value, sqlite3.Cursor)
        except ReferenceError:
            continue
    counts["totalGcTracked"] = len(gc.get_objects())
    counts["allocatedBlocks"] = (
        sys.getallocatedblocks() if hasattr(sys, "getallocatedblocks")
        else None)
    return counts


def _resources(*, trace=False):
    traced_current = traced_peak = None
    if trace and tracemalloc.is_tracing():
        traced_current, traced_peak = tracemalloc.get_traced_memory()
    return {
        "rssBytes": current_rss_bytes(),
        "cgroupCurrentBytes": cgroup_value("memory.current"),
        "cgroupPeakBytes": cgroup_value("memory.peak"),
        "fdCount": _fd_count(), "threadCount": _thread_count(),
        "tracedCurrentBytes": traced_current,
        "tracedPeakBytes": traced_peak,
        **smaps_rollup_bytes(), **_mapping_counts(),
        "pythonOwners": _python_owner_counts(),
    }


def _set_mapping(target: Dict[str, Any], value: Any) -> None:
    target.clear()
    if isinstance(value, dict):
        target.update(value)


def _set_list(target, value: Any) -> None:
    target[:] = list(value) if isinstance(value, list) else []


def _configure_scanner(source_path: str, run_root: pathlib.Path):
    # Environment must be fixed before scanner binds durability paths.
    os.environ.update({
        "ARGUS_DURABILITY_TEST_MODE": "1",
        "ARGUS_PERSISTENT_ROOT": str(run_root),
        "ARGUS_CHECKPOINT_V2_STAGE1": "1",
        "ARGUS_ADMIN_TOKEN": "stage1-resource-proof",
        "RENDER_GIT_COMMIT": "f" * 40,
    })
    # Importing the optional desktop moomoo SDK opens its user-home log file.
    # The production lifecycle exercised here never calls the broker adapter,
    # so install an inert import-compatible module before scanner import.
    moomoo = types.ModuleType("moomoo")
    moomoo.OpenQuoteContext = None
    moomoo.OpenSecTradeContext = None
    moomoo.RET_OK = 0
    sys.modules["moomoo"] = moomoo
    import scanner  # noqa: E402
    scanner.MOOMOO_AVAILABLE = False
    import argus_checkpoint_v2_stage1 as stage1  # noqa: E402
    import argus_remote_receipt_queue as receipt_queue  # noqa: E402

    source = json.loads(pathlib.Path(source_path).read_text(encoding="utf-8"))
    if not isinstance(source, dict) or source.get("schemaVersion") != \
            "argus-durable-v3":
        raise SystemExit("source_invalid")

    paths = {
        "root": str(run_root),
        "wal": str(run_root / "argus_mission_tick.wal"),
        "checkpoint": str(run_root / "argus_osint_memory.json"),
        "lease": str(run_root / "argus_mission_tick.lease"),
        "cursor": str(run_root / "argus_mission_tick.cursor.json"),
        "receipt": str(run_root / "argus_mission_tick.receipt.json"),
        "receiptQueue": str(run_root / "argus_remote_receipt_queue.json"),
        "tempDirectory": str(run_root),
    }
    run_root.mkdir(parents=True, exist_ok=True)
    pathlib.Path(paths["wal"]).touch(exist_ok=True)
    scanner._DURABILITY_PATHS = paths
    scanner._OSINT_PERSIST_FILE = paths["checkpoint"]
    scanner._MISSION_WAL_FILE = paths["wal"]
    scanner._MISSION_LEASE_FILE = paths["lease"]
    scanner._MISSION_CURSOR_FILE = paths["cursor"]
    scanner._MISSION_RECEIPT_FILE = paths["receipt"]
    scanner._REMOTE_RECEIPT_QUEUE_FILE = paths["receiptQueue"]
    scanner._CHECKPOINT_V2_ROOT = str(run_root / "argus_checkpoint_v2")
    scanner._FOUNDATION_JOBS_FILE = str(
        run_root / "argus_foundation_jobs.json")

    _set_mapping(scanner._OSINT_TERM_OVERLAY, source.get("termOverlay"))
    _set_list(scanner._OSINT_MEMORY, source.get("memory"))
    _set_mapping(scanner._OSINT_URL_CACHE, source.get("urlCache"))
    _set_mapping(scanner._OSINT_CANARY_LAST, source.get("canaryLast"))
    _set_list(scanner._OSINT_RPS_HISTORY, source.get("rpsHistory"))
    _set_list(scanner._OSINT_BASELINE_RUNS, source.get("baselineRuns"))
    _set_list(scanner._OSINT_BENCHMARK_RUNS, source.get("benchmarkRuns"))
    _set_mapping(scanner._FORMAL_BENCHMARK,
                 source.get("formalResearchBenchmark"))
    _set_mapping(scanner._FORMAL_BENCHMARK_V2,
                 source.get("formalResearchBenchmarkV2"))
    _set_mapping(scanner._FOUNDATION_JOBS, source.get("foundationJobs"))
    _set_mapping(scanner._SOAK, source.get("soak"))
    _set_list(scanner._SOAK_HISTORY, source.get("soakHistory"))
    _set_mapping(scanner._SOAK_CONTROL, source.get("soakControl"))
    _set_list(scanner._MISSIONS, source.get("missions"))
    _set_list(scanner._MISSION_WINDOWS, source.get("missionWindows"))
    _set_list(scanner._FORECAST_LEDGER, source.get("forecasts"))
    _set_list(scanner._OUTCOME_LEDGER, source.get("outcomes"))
    _set_list(scanner._INCIDENTS, source.get("incidents"))
    _set_list(scanner._OPS_JOURNAL, source.get("opsJournal"))
    _set_mapping(scanner._OPS_JOURNAL_META, source.get("opsJournalMeta"))
    _set_list(scanner._OPS_JOURNAL_COMPACT,
              source.get("opsJournalCompacted"))
    _set_mapping(scanner._REMOTE_CYCLE, source.get("remoteJournalCycle"))
    _set_mapping(scanner._COST_POLICY, source.get("costPolicy"))
    _set_mapping(scanner._MARKET_LEDGER, source.get("marketLedger"))
    _set_mapping(scanner._CHART_INTELLIGENCE,
                 source.get("chartIntelligence"))
    _set_mapping(scanner._TODAY_INTELLIGENCE,
                 source.get("todayIntelligence"))
    _set_mapping(scanner._MARKET_REPLAY, source.get("marketReplay"))
    _set_mapping(scanner._VERIFIED_VIEW_SNAPSHOTS,
                 source.get("verifiedViewSnapshots"))
    _set_mapping(scanner._ASSET_CHART_REPORTS,
                 source.get("assetChartReports"))
    scanner._REMOTE_ACK.update({"disabled": True, "ackedKeys": []})
    scanner._REMOTE_RECEIPT_QUEUE = receipt_queue.empty_store()
    scanner._MISSION_BATCH_STATE.update({
        "cursor": int((source.get("missionTickDurability") or {}).get(
            "cursor") or 0),
        "remainingCount": 0, "lastJobId": None, "lastResult": None,
        "lastCompletedAt": None, "walAppliedSequence": 0,
    })
    scanner._CHECKPOINT_V2_STAGE1_ENABLED = True
    scanner._CHECKPOINT_V2_STAGE1_CONTROL = stage1.empty_state("f" * 40)
    scanner._CHECKPOINT_V2_STATUS = {
        "schemaVersion": scanner.argus_checkpoint_v2.SCHEMA,
        "state": "stage1_dual_write_pending",
    }
    scanner._DURABLE_STATE.update({
        "schemaVersion": "argus-durable-v3", "integrityStatus": "ok",
        "lastCheckpoint": None, "writeCount": 0, "successCount": 0,
        "failureCount": 0, "consecutiveFailureCount": 0,
        "lastCheckpointError": None,
    })
    scanner._DURABLE_STORAGE_STATUS.update({"valid": True,
                                            "runtimeVerified": True})
    scanner._STARTUP.update({
        "state": "ready", "restoreOutcome": "test_mode",
        "restoreCompletedAt": scanner._ai_now_iso(),
    })
    scanner._ARGUS_ADMIN_TOKEN = "stage1-resource-proof"
    scanner._SHUTDOWN.update({"requested": False, "requestedAt": None,
                              "signal": None})
    # Drop the monolithic parsed source owner. The scanner globals above are
    # the sole long-lived authoritative graph, matching production ownership.
    del source
    gc.collect()
    return scanner


def _no_reclaim(source_bytes: int) -> Dict[str, Any]:
    rss = current_rss_bytes()
    return {"attempted": False, "supported": True,
            "sourceBytes": int(source_bytes), "rssBeforeBytes": rss,
            "rssAfterBytes": rss, "rssReleasedBytes": 0,
            "reportedReleasedBytes": None,
            "testVariant": "exact_pre_fix_without_parent_reclaim"}


def _run_request(scanner, client, *, index: int, scheduled_for: str):
    holder: Dict[str, Any] = {}

    def execute():
        try:
            response = client.post(
                "/api/argus/admin/missions/tick",
                headers={"X-ARGUS-ADMIN-TOKEN": "stage1-resource-proof"},
                json={"triggerSource": "ec2_systemd",
                      "scheduledFor": scheduled_for,
                      "expectedBuildSha": "f" * 40,
                      "diagnostic": True})
            payload = response.get_json(silent=True) or {}
            holder.update({
                "httpStatus": response.status_code,
                "status": payload.get("status"),
                "result": payload.get("result"),
                "jobId": payload.get("jobId"),
                "missionWindowId": (payload.get("missionWindow") or {}).get(
                    "missionWindowId"),
                "checkpointCreated": payload.get("checkpointCreated"),
                "snapshotBytes": (payload.get("checkpoint") or {}).get(
                    "snapshotBytes"),
            })
        except BaseException as exc:
            holder["errorClass"] = type(exc).__name__
            holder["errorClassification"] = str(
                getattr(exc, "classification", type(exc).__name__))[:120]

    request = threading.Thread(
        target=execute, name=f"production-lifecycle-request-{index}")
    request.start()
    request.join()
    return holder


def run(*, source_json: str, root: str, variant: str, cycles: int,
        trace_allocations: bool = False):
    run_root = pathlib.Path(root).resolve()
    scanner = _configure_scanner(source_json, run_root)
    client = scanner.app.test_client()
    if trace_allocations:
        tracemalloc.start(8)
    baseline = _resources(trace=trace_allocations)
    records = []
    start = datetime.now(timezone.utc).replace(
        second=0, microsecond=0) - timedelta(minutes=30 * (cycles + 1))
    patches = [
        mock.patch.object(
            scanner, "_market_calendar_states", return_value={
                "JP": {"isTradingDay": False},
                "US": {"isTradingDay": False}}),
        mock.patch.object(
            scanner, "_precompute_verified_market_view",
            return_value=({"reportId": "resource-proof", "status": "ok"},
                          {"status": "verified"})),
        mock.patch.object(
            scanner, "_precompute_asset_chart_tick",
            return_value={"status": "verified", "generated": False,
                          "stateHash": "resource-proof"}),
        mock.patch.object(
            scanner, "_dl_resolve_matured",
            return_value={"processed": 0, "resolved": 0, "remaining": 0}),
        mock.patch.object(
            scanner.argus_scheduler, "generate_daily_missions",
            return_value=[]),
        mock.patch.object(
            scanner.argus_scheduler, "generate_periodic_missions",
            return_value=[]),
        mock.patch.object(scanner.argus_scheduler, "detect_missed",
                          return_value=[]),
    ]
    if variant == "pre_fix":
        patches.append(mock.patch.object(
            scanner.argus_checkpoint_v2,
            "release_consumed_legacy_snapshot_memory",
            side_effect=_no_reclaim))
    with contextlib.ExitStack() as stack:
        for patch in patches:
            stack.enter_context(patch)
        for index in range(1, cycles + 1):
            scheduled = (start + timedelta(minutes=30 * index)).isoformat(
                ).replace("+00:00", "Z")
            holder = _run_request(
                scanner, client, index=index, scheduled_for=scheduled)
            time.sleep(0.25)
            if trace_allocations and index in TRACE_DIAGNOSTIC_CYCLES:
                gc.collect()
            record = {
                "cycle": index, **holder,
                **_resources(trace=trace_allocations),
            }
            checkpoint = scanner._DURABLE_STATE.get("lastCheckpoint") or {}
            v2_status = checkpoint.get("checkpointV2") or {}
            telemetry = v2_status.get("resourceTelemetry") or {}
            reclaim = checkpoint.get("legacyAllocatorReclaim") or {}
            record.update({
                "legacyVerified": checkpoint.get("verified"),
                "legacyReadBackVerified": checkpoint.get(
                    "readBackVerified"),
                "walRemainingRecords": (checkpoint.get("walCompaction") or
                                        {}).get("remainingRecords"),
                "v2Verified": v2_status.get("lastWriteVerified"),
                "childExitCode": telemetry.get("childExitCode"),
                "childExitClassification": telemetry.get(
                    "childExitClassification"),
                "pendingGenerations": telemetry.get(
                    "pendingGenerationCount"),
                "retainedGenerations": (v2_status.get("isolatedWriter") or
                                        {}).get("retainedGenerationCount"),
                "generationBytes": telemetry.get("generationBytes"),
                "generationRows": telemetry.get("generationRowCount"),
                "generationSections": telemetry.get(
                    "generationSectionCount"),
                "allocatorReclaim": reclaim,
            })
            records.append(record)
            print(json.dumps({
                "schemaVersion": "argus-stage1-production-lifecycle-progress-v1",
                "variant": variant, "cycle": index,
                "httpStatus": record.get("httpStatus"),
                "rssBytes": record.get("rssBytes"),
                "pssAnonBytes": record.get("Pss_AnonBytes"),
                "tracedCurrentBytes": record.get("tracedCurrentBytes"),
                "cgroupCurrentBytes": record.get("cgroupCurrentBytes"),
                "cgroupPeakBytes": record.get("cgroupPeakBytes"),
                "legacyVerified": record.get("legacyVerified"),
                "v2Verified": record.get("v2Verified"),
                "errorClass": record.get("errorClass"),
            }, sort_keys=True), flush=True)
            if holder.get("errorClass") or holder.get("httpStatus") != 200:
                break

    successful = [row for row in records
                  if not row.get("errorClass") and
                  row.get("httpStatus") == 200]
    steady = successful[WARMUP_CYCLES:]
    rss = [int(row.get("rssBytes") or 0) for row in steady]
    pss_anon = [int(row.get("Pss_AnonBytes") or 0) for row in steady]
    traced = [int(row.get("tracedCurrentBytes") or 0) for row in steady]
    failures = []
    if len(successful) < cycles:
        failures.append("cycle_completion_failed")
    for row in successful:
        if not (row.get("legacyVerified") and
                row.get("legacyReadBackVerified") and row.get("v2Verified")):
            failures.append("integrity_verification_failed")
        if row.get("childExitCode") not in (0, None) or \
                row.get("childExitClassification") not in ("success", None):
            failures.append("isolated_writer_failed")
        if int(row.get("pendingGenerations") or 0) != 0 or \
                int(row.get("retainedGenerations") or 0) > 4:
            failures.append("generation_retention_failed")
    rss_band = _band(rss) if rss else None
    plateau = _band(rss[-PLATEAU_CYCLES:]) if rss else None
    if rss_band and rss_band["growth"] >= RSS_GROWTH_LIMIT:
        failures.append("parent_rss_growth_exceeded")
    if plateau and plateau["span"] > PLATEAU_SPAN_LIMIT:
        failures.append("parent_rss_plateau_failed")
    cgroup_peak = max((int(row.get("cgroupPeakBytes") or 0)
                       for row in records), default=0)
    if cgroup_peak >= CGROUP_PEAK_LIMIT:
        failures.append("cgroup_peak_exceeded")
    ending = records[-1] if records else baseline
    for key, failure in (("fdCount", "descriptor_growth"),
                         ("threadCount", "thread_growth"),
                         ("sqliteOrTempMappingCount", "mapping_growth")):
        if baseline.get(key) is not None and ending.get(key) is not None and \
                int(ending[key]) > int(baseline[key]):
            failures.append(failure)
    for key, failure in (("future", "future_growth"),
                         ("sqliteConnection", "connection_growth"),
                         ("sqliteCursor", "cursor_growth")):
        before = (baseline.get("pythonOwners") or {}).get(key)
        after = (ending.get("pythonOwners") or {}).get(key)
        if before is not None and after is not None and int(after) > int(before):
            failures.append(failure)
    failures = sorted(set(failures))
    classification = ("INCONCLUSIVE" if len(records) < cycles else
                      "FAIL" if failures else "PASS")
    summary = {
        "schemaVersion": "argus-stage1-production-lifecycle-proof-v1",
        "variant": variant, "requestedCycles": cycles,
        "completedCycles": len(records),
        "successfulCycles": len(successful),
        "finalClassification": classification,
        "failures": failures, "baseline": baseline,
        "rssBandAfterWarmup": rss_band,
        "pssAnonBandAfterWarmup": _band(pss_anon) if pss_anon else None,
        "tracedCurrentBandAfterWarmup": _band(traced) if traced else None,
        "plateauRssBand": plateau,
        "cgroupPeakBytes": cgroup_peak,
        "maximumRetainedGenerations": max((int(
            row.get("retainedGenerations") or 0) for row in successful),
            default=0),
        "maximumPendingGenerations": max((int(
            row.get("pendingGenerations") or 0) for row in successful),
            default=0),
        "oomObserved": any(row.get("errorClassification") == "child_oom"
                           for row in records),
        "writerErrors": sorted(set(
            row.get("errorClassification") for row in records
            if row.get("errorClassification"))),
        "lifecycle": {
            "longLivedParent": True,
            "actualFlaskMissionTickRoute": True,
            "actualLegacyCheckpoint": True,
            "actualStateNormalizationAndHashes": True,
            "actualIsolatedWriter": True,
            "actualValidationPromotionPruning": True,
            "providerNetworkCalls": 0,
            "formalSoakState": "not_started",
            "legacyRestoreAuthority": True,
            "v2RestoreAuthority": False,
        },
        "records": records,
    }
    if tracemalloc.is_tracing():
        tracemalloc.stop()
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
    parser.add_argument("--trace-allocations", action="store_true")
    args = parser.parse_args()
    if args.cycles < MINIMUM_CYCLES:
        raise SystemExit("minimum_32_cycles_required")
    summary = run(source_json=args.source_json, root=args.root,
                  variant=args.variant, cycles=args.cycles,
                  trace_allocations=args.trace_allocations)
    pathlib.Path(args.output).write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    print(json.dumps({key: summary[key] for key in (
        "schemaVersion", "variant", "requestedCycles", "completedCycles",
        "successfulCycles", "finalClassification", "failures",
        "rssBandAfterWarmup", "pssAnonBandAfterWarmup",
        "tracedCurrentBandAfterWarmup", "plateauRssBand",
        "cgroupPeakBytes", "maximumRetainedGenerations", "oomObserved",
        "writerErrors")}, sort_keys=True))
    if args.expect and summary["finalClassification"] != args.expect:
        raise SystemExit("unexpected_classification")


if __name__ == "__main__":
    main()
