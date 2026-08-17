#!/usr/bin/env python3
"""Linux-safe deep memory attribution proof for the real legacy write path.

The probe runs only in its own temporary directory.  It never contacts a
provider, production backend, Remote Journal, Render, or GitHub.  It exercises
the same source construction, sealing, verified checkpoint, disabled-V2
adapter, Flask GET instrumentation, and bounded operation recorder used by the
service.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import tempfile
import threading
import time
from typing import Any, Dict

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import argus_asset_chart_cache
import argus_memory_attribution as memory
import argus_persistent_storage
import scanner


MIB = 1024 * 1024

EXPECTED_SOURCE_OPERATIONS = {
    "internal:source.formal_benchmark.normalize",
    "internal:source.formal_benchmark_v2.normalize",
    "internal:source.foundation_jobs.normalize",
    "internal:source.cost_policy.normalize",
    "internal:source.market_ledger.normalize",
    "internal:source.market_ledger.hash_with_transient_normalize",
    "internal:source.chart_intelligence.normalize",
    "internal:source.chart_intelligence.hash_with_transient_normalize",
    "internal:source.today_intelligence.normalize",
    "internal:source.today_intelligence.hash_with_transient_normalize",
    "internal:source.market_replay.normalize",
    "internal:source.market_replay.hash_with_transient_normalize",
    "internal:source.verified_snapshots.normalize",
    "internal:source.verified_snapshots.hash_normalized",
    "internal:source.asset_chart_reports.normalize",
    "internal:source.asset_chart_reports.hash_normalized",
}


def _integer(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) \
        else None


def _rss() -> int | None:
    return _integer(memory.process_metrics().get("vmRssBytes"))


def _delta(before: int | None, after: int | None) -> int | str:
    if before is None or after is None:
        return memory.UNKNOWN
    return after - before


def _production_shaped_asset_store(
        records: int = argus_asset_chart_cache.MAX_RECORDS,
        bars_per_record: int = 750) -> Dict[str, Any]:
    """Create structural load without retaining private/provider payloads."""
    store = argus_asset_chart_cache.empty_store()
    for record_index in range(records):
        market = "JP" if record_index % 2 == 0 else "US"
        symbol = f"PROBE{record_index:02d}"
        identity = argus_asset_chart_cache.identity_key(
            market, symbol, "daily")
        logical = f"{identity}:dataset-{record_index}:probe-v1"
        bars = [
            {
                "index": bar_index,
                "open": 100.0 + bar_index / 100,
                "high": 101.0 + bar_index / 100,
                "low": 99.0 + bar_index / 100,
                "close": 100.5 + bar_index / 100,
                "volume": record_index * 100_000 + bar_index,
            }
            for bar_index in range(bars_per_record)
        ]
        payload = {
            "market": market,
            "symbol": symbol,
            "timeframe": "daily",
            "status": "probe",
            "periodEnd": "2026-08-10",
            "indicators": {"bars": bars},
        }
        store["records"][logical] = {
            "schemaVersion": argus_asset_chart_cache.SCHEMA_VERSION,
            "logicalKey": logical,
            "identityKey": identity,
            "market": market,
            "symbol": symbol,
            "timeframe": "daily",
            "datasetHash": f"dataset-{record_index}",
            "methodVersion": "probe-v1",
            "publishedAt": "2026-08-10T00:00:00Z",
            "periodEnd": "2026-08-10",
            "payloadHash": "probe-local-only",
            "payload": payload,
        }
        store["current"][identity] = logical
    store["lastUpdatedAt"] = "2026-08-10T00:00:00Z"
    return store


def _configure_temporary_legacy_root(root: pathlib.Path) -> None:
    paths = argus_persistent_storage.configured_paths(
        {"ARGUS_PERSISTENT_ROOT": str(root)}, production=False)
    scanner._DURABILITY_PRODUCTION = False
    scanner._DURABILITY_PATHS = paths
    scanner._OSINT_PERSIST_FILE = paths["checkpoint"]
    scanner._MISSION_WAL_FILE = paths["wal"]
    scanner._MISSION_LEASE_FILE = paths["lease"]
    scanner._MISSION_CURSOR_FILE = paths["cursor"]
    scanner._MISSION_RECEIPT_FILE = paths["receipt"]
    scanner._REMOTE_RECEIPT_QUEUE_FILE = paths["receiptQueue"]
    scanner._CHECKPOINT_V2_ROOT = str(root / "argus_checkpoint_v2")
    scanner._CHECKPOINT_V2_STAGE1_ENABLED = False
    scanner._CHECKPOINT_V2_STATUS = {
        "schemaVersion": scanner.argus_checkpoint_v2.SCHEMA,
        "state": "disabled",
    }
    scanner._DURABLE_STORAGE_STATUS.update({
        "valid": True, "errorClass": None, "errorReason": None,
        "runtimeVerified": True,
    })


def _phase_scalar(record: Dict[str, Any], phase: str) -> Dict[str, Any]:
    row = (record.get("sourceConstruction") or {}).get("phases", {}).get(
        phase, {})
    return {
        "status": row.get("status"),
        "operation": (row.get("metadata") or {}).get("operation"),
        "deltas": dict(row.get("deltaFromPrevious") or {}),
        "metadata": dict(row.get("metadata") or {}),
    }


def _source_operation_scalars() -> list[Dict[str, Any]]:
    """Copy only the bounded scalar source rows before later tasks rotate them."""
    latest: Dict[str, Dict[str, Any]] = {}
    for row in scanner._MEMORY_OPERATIONS.view().get("records") or []:
        name = str(row.get("operationName") or "")
        if name not in EXPECTED_SOURCE_OPERATIONS:
            continue
        latest[name] = {
            "operationName": name,
            "durationMs": row.get("durationMs"),
            "start": dict(row.get("start") or {}),
            "end": dict(row.get("end") or {}),
            "deltas": dict(row.get("deltas") or {}),
        }
    return [latest[name] for name in sorted(latest)]


def _legacy_cycle(index: int) -> Dict[str, Any]:
    job_id = f"deep-memory-probe-{index:02d}"
    window = {
        "missionWindowId": f"mw-deep-memory-probe-{index:02d}",
        "triggerSource": "ec2_systemd",
        "scheduledFor": "2026-08-10T00:00:00Z",
    }
    scanner._MISSION_TICK_CONTEXT.update({
        "active": True,
        "jobId": job_id,
        "ownerThread": threading.get_ident(),
        "triggerSource": "ec2_systemd",
        "missionWindowId": window["missionWindowId"],
        "memoryAttributionRecordId": None,
        "memoryAttributionT0": memory.memory_snapshot(
            scanner._memory_attribution_logical_counts()),
    })
    scanner._memory_attribution_begin(window, "2026-08-10T00:00:01Z")
    started = time.monotonic()
    checkpoint = scanner._osint_persist()
    source_operations = _source_operation_scalars()
    scanner._memory_attribution_capture("T11", {
        "checkpointVerified": bool(checkpoint.get("verified")),
    })
    scanner._memory_attribution_capture("T12", {
        "missionFinalized": True,
    })
    record = scanner._MEMORY_ATTRIBUTION.complete(job_id)
    scanner._MISSION_TICK_CONTEXT.update({
        "active": False,
        "ownerThread": None,
        "memoryAttributionRecordId": None,
        "memoryAttributionT0": None,
    })
    phases = record.get("phases") or {}
    return {
        "cycle": index + 1,
        "jobId": job_id,
        "elapsedMs": round((time.monotonic() - started) * 1000, 3),
        "checkpointVerified": bool(checkpoint.get("verified")),
        "checkpointBytes": checkpoint.get("snapshotBytes"),
        "phaseOrder": list(record.get("phaseOrder") or []),
        "sourcePhaseOrder": list(
            (record.get("sourceConstruction") or {}).get("phaseOrder") or []),
        "missionDifferentials": dict(record.get("differentials") or {}),
        "sourceConstruction": {
            phase: _phase_scalar(record, phase)
            for phase in memory.SOURCE_PHASES
        },
        "sourceOperations": source_operations,
        "v2Statuses": {
            phase: (phases.get(phase) or {}).get("status")
            for phase in ("T6", "T7", "T8", "T9", "T10")
        },
    }


def _representative_gets() -> Dict[str, Any]:
    scanner._ARGUS_ADMIN_TOKEN = "deep-probe-admin"
    requests = [
        ("/healthz", {}),
        ("/readyz", {}),
        ("/api/state", {}),
        ("/api/argus/system-health", {}),
        ("/api/argus/admin/memory-attribution",
         {"X-ARGUS-ADMIN-TOKEN": "deep-probe-admin"}),
    ]
    rows = []
    with scanner.app.test_client() as client:
        for path, headers in requests:
            response = client.get(path, headers=headers)
            rows.append({"route": path, "statusCode": response.status_code,
                         "responseBytes": len(response.get_data())})
    return {"requests": rows,
            "allSuccessful": all(row["statusCode"] == 200 for row in rows)}


def _background_boundaries(cycles: int = 32) -> Dict[str, Any]:
    for _ in range(cycles):
        scanner._memory_operation_run(
            "scheduler", "scheduler.bookkeeping_snapshot",
            scanner._memory_attribution_logical_counts)
        scanner._memory_operation_run(
            "background", "background.durability_cursor_snapshot",
            scanner._mission_tick_durability_snapshot)
    return {"cycles": cycles, "completedOperations": cycles * 2}


def _bounded_privacy_proof(events: int = 250) -> Dict[str, Any]:
    recorder = memory.OperationAttributionRecorder(32, threshold_bytes=0)
    rss_before = _rss()
    for index in range(events):
        token = recorder.begin(
            kind="HTTP",
            name=("GET /api/argus/provider/"
                  "123e4567-e89b-12d3-a456-426614174000"
                  "?symbol=PRIVATE&token=DO_NOT_STORE"),
            known=True,
            metadata={"requestBody": "DO_NOT_STORE", "natural": True})
        recorder.complete(token, metadata={"statusCode": 200})
    rss_after = _rss()
    view = recorder.view()
    encoded = json.dumps(view, sort_keys=True)
    return {
        "events": events,
        "historyLimit": view["historyLimit"],
        "historyCount": view["historyCount"],
        "droppedCount": view["droppedCount"],
        "historySerializedBytes": view["historySerializedBytes"],
        "rssGrowthBytes": _delta(rss_before, rss_after),
        "privacySafe": all(value not in encoded for value in (
            "PRIVATE", "DO_NOT_STORE", "123e4567")),
    }


def run(cycles: int = 32) -> Dict[str, Any]:
    cycles = max(32, int(cycles))
    rss_before = _rss()
    scanner._MEMORY_ATTRIBUTION = memory.MemoryAttributionRecorder(16)
    scanner._MEMORY_OPERATIONS = memory.OperationAttributionRecorder(
        32, threshold_bytes=MIB)
    scanner._ASSET_CHART_REPORTS = _production_shaped_asset_store()
    with tempfile.TemporaryDirectory(prefix="argus-deep-memory-") as temp:
        root = pathlib.Path(temp)
        _configure_temporary_legacy_root(root)
        lifecycle = [_legacy_cycle(index) for index in range(cycles)]
        get_probe = _representative_gets()
        background_probe = _background_boundaries()
        checkpoint_exists = pathlib.Path(
            scanner._OSINT_PERSIST_FILE).is_file()
        checkpoint_bytes = pathlib.Path(
            scanner._OSINT_PERSIST_FILE).stat().st_size \
            if checkpoint_exists else 0
    privacy = _bounded_privacy_proof()
    rss_after = _rss()
    operations = scanner._MEMORY_OPERATIONS.view()
    checks = {
        "legacyCyclesComplete": len(lifecycle) == cycles,
        "legacyActualCheckpointCyclesAtLeast32": (
            cycles >= 32 and len(lifecycle) >= 32),
        "allLegacyCheckpointsVerified": all(
            row["checkpointVerified"] for row in lifecycle),
        "allLegacyCheckpointBytesPositive": all(
            isinstance(row.get("checkpointBytes"), int) and
            row["checkpointBytes"] > 0 for row in lifecycle),
        "sourceS0ThroughS8Exact": all(
            row["sourcePhaseOrder"] == list(memory.SOURCE_PHASES)
            for row in lifecycle),
        "sourceOperationBoundariesExact": all(
            len(row["sourceOperations"]) == len(EXPECTED_SOURCE_OPERATIONS)
            and {item["operationName"] for item in row["sourceOperations"]}
                == EXPECTED_SOURCE_OPERATIONS
            for row in lifecycle),
        "phaseT0ThroughT12Exact": all(
            row["phaseOrder"] == list(memory.PHASES)
            for row in lifecycle),
        "stage1RemainedDisabled": all(
            set(row["v2Statuses"].values()) == {memory.NOT_APPLICABLE}
            for row in lifecycle),
        "checkpointCreatedOnlyUnderTemporaryRoot": checkpoint_exists,
        "representativeGetsSuccessful": get_probe["allSuccessful"],
        "operationHistoryBounded": (
            operations["historyCount"] <= 32 and
            operations["historySerializedBytes"] < 2 * MIB),
        "privacyHistoryBounded": (
            privacy["historyCount"] == 32 and
            privacy["historySerializedBytes"] < MIB),
        "privacyFieldsExcluded": privacy["privacySafe"],
        "noV2Generation": not pathlib.Path(
            scanner._CHECKPOINT_V2_ROOT).exists(),
    }
    return {
        "schemaVersion": "argus-deep-memory-attribution-proof-v1",
        "processTopology": "single_process_local_diagnostic",
        "cycles": cycles,
        "rssBeforeBytes": rss_before,
        "rssAfterBytes": rss_after,
        "rssGrowthBytes": _delta(rss_before, rss_after),
        "checkpointBytes": checkpoint_bytes,
        "lifecycle": lifecycle,
        "representativeGets": get_probe,
        "background": background_probe,
        "operationAttribution": operations,
        "privacyAndBounds": privacy,
        "checks": checks,
        "passed": all(checks.values()),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cycles", type=int, default=32)
    parser.add_argument("--output")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()
    report = run(args.cycles)
    encoded = json.dumps(report, ensure_ascii=False, indent=2,
                         sort_keys=True)
    if not args.quiet:
        print(encoded)
    if args.output:
        pathlib.Path(args.output).write_text(
            encoded + "\n", encoding="utf-8")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
