#!/usr/bin/env python3
"""Production-shaped full-vs-compact memory snapshot resource proof.

Two fresh long-lived workers create the same deterministic public-safe stores.
One exercises only the compact HTTP route and the other only the full restore
route, preventing lifetime RSS/allocator peaks from contaminating the compact
measurement. Neither worker contacts a provider, persists state, invokes a
runtime memory control, or changes a runtime setting. Response bodies are
discarded inside workers; the supervisor receives only hashes and scalar
resource evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import pathlib
import resource
import subprocess
import sys
import time
import types
from typing import Any, Dict, Iterable, Mapping


ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Local macOS validation cannot initialize the vendor SDK because its default
# log location is outside the isolated worktree.  CI installs and imports the
# real package; this opt-in import-only stub never participates in CI.
if os.environ.get("ARGUS_RESOURCE_PROBE_STUB_MOOMOO") == "1":
    moomoo = types.ModuleType("moomoo")
    moomoo.OpenQuoteContext = type("OpenQuoteContext", (), {})
    moomoo.OpenSecTradeContext = type("OpenSecTradeContext", (), {})
    moomoo.RET_OK = 0
    sys.modules["moomoo"] = moomoo

import argus_asset_chart_cache as asset_cache
import argus_chart_intelligence
import argus_market_ledger
import argus_market_replay
import argus_memory_attribution as memory
import argus_remote_journal
import argus_today_intelligence
import argus_verified_snapshot as verified_snapshot
import scanner
from scripts import normalized_hash_resource_probe as fixture


MIB = 1024 * 1024
GIB = 1024 * MIB
MINIMUM_CYCLES = 32
PLATEAU_LIMIT_BYTES = 128 * MIB
LOGICAL_PEAK_LIMIT_BYTES = 3 * GIB
EXPECTED_CGROUP_MAX_BYTES = 4 * GIB
MINIMUM_MATERIAL_RSS_REDUCTION_BYTES = 1 * MIB
MINIMUM_MATERIAL_RESPONSE_REDUCTION_BYTES = 100 * MIB
MINIMUM_PRODUCTION_FULL_RESPONSE_BYTES = 120 * MIB
MAXIMUM_PRODUCTION_FULL_RESPONSE_BYTES = 140 * MIB
DEFAULT_VERIFIED_BARS_PER_RECORD = 9_140
DEFAULT_ASSET_BARS_PER_RECORD = 5_024
COMPACT_RESPONSE_MIN_BYTES = 650 * 1024
COMPACT_RESPONSE_MAX_BYTES = 750 * 1024
SECTION_SIZE_TOLERANCE = 0.05
MAX_FILLER_BYTES_PER_ROW = 64 * 1024
SECTION_TARGET_BYTES = {
    "marketLedger": 62_168_679,
    "verifiedViewSnapshots": 27_393_104,
    "assetChartReports": 15_209_906,
    "chartIntelligence": 10_996_745,
    "marketReplay": 6_696_436,
    "todayIntelligence": 4_971_964,
    "opsJournal": 240_333,
    "outcomes": 394_997,
}
SECTION_TARGET_COUNTS = {
    "marketLedger": {
        "observations": 45_148, "derivedMetrics": 815,
        "turningPoints": 4_622, "backtests": 34, "imports": 219,
        "rolledBackImports": 0,
    },
    "chartIntelligence": {
        "snapshots": 295, "zones": 1_916, "turningPoints": 12_021,
        "reactionAnomalies": 0, "relationshipBreaks": 1,
        "invalidations": 1_183,
    },
    "todayIntelligence": {
        "snapshots": 332, "shortSellingHistory": 1_234,
        "failedRallyOutcomes": 652,
    },
    "marketReplay": {"contexts": 24, "contextHistory": 369},
}
EXPECTED_JOURNAL_COUNT = 400
EXPECTED_OUTCOME_COUNT = 10
EXPECTED_JOURNAL_AGGREGATE_COUNT = 26
PATH_MODES = ("compact", "full")
FIXED_NOW = "2026-08-12T00:00:00Z"
METRIC_KEYS = (
    "processRssBytes", "rssAnonBytes", "rssFileBytes", "pssBytes",
    "arenaBytes", "uordblksBytes", "fordblksBytes",
    "topReleasableBytes", "cgroupCurrentBytes", "cgroupPeakBytes",
)
PLATEAU_KEYS = (
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


def _peak_rss_bytes() -> int | str:
    try:
        peak = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        return peak if sys.platform == "darwin" else peak * 1024
    except (OSError, TypeError, ValueError, OverflowError):
        return memory.UNKNOWN


def _memory_events() -> Dict[str, int | str]:
    output: Dict[str, int | str] = {
        "oom": memory.UNKNOWN,
        "oomKill": memory.UNKNOWN,
    }
    try:
        raw = pathlib.Path("/sys/fs/cgroup/memory.events").read_text(
            encoding="utf-8")
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
        "rssFileBytes": _metric(process.get("rssFileBytes")),
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


def _deltas(before: Mapping[str, Any], after: Mapping[str, Any]) \
        -> Dict[str, int | str]:
    return {
        key: _difference(before.get(key), after.get(key))
        for key in METRIC_KEYS
    }


def _request(client: Any, route: str) -> Dict[str, Any]:
    before = _snapshot()
    started = time.perf_counter_ns()
    response = client.get(route)
    body = response.get_data()
    duration_ms = (time.perf_counter_ns() - started) / 1_000_000.0
    body_live = _snapshot()
    result = {
        "statusCode": response.status_code,
        "responseBytes": len(body),
        "durationMs": round(duration_ms, 3),
        "before": before,
        "bodyLive": body_live,
        "bodyLiveDelta": _deltas(before, body_live),
        "body": body,
    }
    del response
    return result


def _mark_released(result: Dict[str, Any]) -> None:
    result["afterRelease"] = _snapshot()
    result["retainedDelta"] = _deltas(
        result["before"], result["afterRelease"])


def _metric_percentile(
        rows: list[Dict[str, Any]], section: str, key: str,
        percentile: float) -> int | str:
    values = [
        row[section][key] for row in rows
        if isinstance(row.get(section), Mapping) and
        _integer(row[section].get(key)) is not None
    ]
    return int(_percentile(values, percentile)) if values else memory.UNKNOWN


def _telemetry_complete(
        rows: list[Dict[str, Any]], baseline: Mapping[str, Any],
        final: Mapping[str, Any]) -> bool:
    required = (*METRIC_KEYS, "processPeakRssBytes", "cgroupMaxBytes")
    samples = [baseline, final]
    for row in rows:
        samples.extend((row.get("before") or {}, row.get("bodyLive") or {},
                        row.get("afterRelease") or {}))
    return bool(rows) and all(
        _integer(sample.get(key)) is not None
        for sample in samples for key in required)


def _mode_summary(
        rows: list[Dict[str, Any]], baseline: Mapping[str, Any],
        final: Mapping[str, Any]) -> Dict[str, Any]:
    durations = [row["durationMs"] for row in rows]
    response_bytes = [row["responseBytes"] for row in rows]
    steady = rows[2:] if len(rows) > 2 else rows
    plateau_spans = {
        key: _span(row["afterRelease"].get(key) for row in steady)
        for key in PLATEAU_KEYS
    }
    observed_plateaus = [
        value for value in plateau_spans.values()
        if _integer(value) is not None
    ]
    return {
        "cycles": len(rows),
        "http200Count": sum(row["statusCode"] == 200 for row in rows),
        "responseBytes": {
            "minimum": min(response_bytes) if response_bytes else 0,
            "maximum": max(response_bytes) if response_bytes else 0,
            "p50": int(_percentile(response_bytes, 50)),
        },
        "durationMs": {
            "total": round(sum(durations), 3),
            "p50": _percentile(durations, 50),
            "p95": _percentile(durations, 95),
            "maximum": round(max(durations), 3) if durations else 0,
        },
        "baseline": dict(baseline),
        "final": dict(final),
        "processPeakRssBytes": _maximum([
            baseline.get("processPeakRssBytes"),
            final.get("processPeakRssBytes"),
            *(row[section].get("processPeakRssBytes")
              for row in rows
              for section in ("before", "bodyLive", "afterRelease")),
        ]),
        "bodyLiveMaximums": {
            key: _maximum(row["bodyLive"].get(key) for row in rows)
            for key in METRIC_KEYS
        },
        "bodyLiveDeltaP50": {
            key: _metric_percentile(rows, "bodyLiveDelta", key, 50)
            for key in METRIC_KEYS
        },
        "retainedDeltaP50": {
            key: _metric_percentile(rows, "retainedDelta", key, 50)
            for key in METRIC_KEYS
        },
        "plateauSpanBytesCycles3Plus": plateau_spans,
        "plateauBelow128MiB": (
            len(observed_plateaus) == len(PLATEAU_KEYS) and
            all(value < PLATEAU_LIMIT_BYTES
                for value in observed_plateaus)),
        "requiredLinuxTelemetryComplete": _telemetry_complete(
            rows, baseline, final),
        "rows": rows,
    }


def _comparison_metrics(
        compact: Mapping[str, Any], full: Mapping[str, Any]) -> Dict[str, Any]:
    compact_peak = compact.get("processPeakRssBytes")
    full_peak = full.get("processPeakRssBytes")
    peak_reduction = (
        full_peak - compact_peak
        if _integer(full_peak) is not None and
        _integer(compact_peak) is not None else memory.UNKNOWN)
    compact_p50 = (compact.get("durationMs") or {}).get("p50")
    full_p50 = (full.get("durationMs") or {}).get("p50")
    duration_reduction = (
        round(float(full_p50) - float(compact_p50), 3)
        if isinstance(full_p50, (int, float)) and
        isinstance(compact_p50, (int, float)) else memory.UNKNOWN)
    compact_bytes = (compact.get("responseBytes") or {}).get("maximum")
    full_bytes = (full.get("responseBytes") or {}).get("minimum")
    response_reduction = (
        full_bytes - compact_bytes
        if _integer(full_bytes) is not None and
        _integer(compact_bytes) is not None else memory.UNKNOWN)
    response_percent = (
        round((1.0 - compact_bytes / full_bytes) * 100.0, 6)
        if _integer(full_bytes) is not None and full_bytes > 0 and
        _integer(compact_bytes) is not None else memory.UNKNOWN)
    compact_arena = (compact.get("bodyLiveMaximums") or {}).get(
        "arenaBytes")
    full_arena = (full.get("bodyLiveMaximums") or {}).get("arenaBytes")
    arena_reduction = (
        full_arena - compact_arena
        if _integer(full_arena) is not None and
        _integer(compact_arena) is not None else memory.UNKNOWN)
    return {
        "compactProcessPeakRssBytes": compact_peak,
        "fullProcessPeakRssBytes": full_peak,
        "processPeakRssReductionBytes": peak_reduction,
        "minimumMaterialRssReductionBytes":
            MINIMUM_MATERIAL_RSS_REDUCTION_BYTES,
        "compactArenaMaximumBytes": compact_arena,
        "fullArenaMaximumBytes": full_arena,
        "arenaMaximumReductionBytes": arena_reduction,
        "minimumMaterialArenaReductionBytes":
            MINIMUM_MATERIAL_RSS_REDUCTION_BYTES,
        "compactDurationP50Ms": compact_p50,
        "fullDurationP50Ms": full_p50,
        "durationP50ReductionMs": duration_reduction,
        "responseByteReductionBytes": response_reduction,
        "responseByteReductionPercent": response_percent,
        "minimumMaterialResponseReductionBytes":
            MINIMUM_MATERIAL_RESPONSE_REDUCTION_BYTES,
        "minimumProductionFullResponseBytes":
            MINIMUM_PRODUCTION_FULL_RESPONSE_BYTES,
        "maximumProductionFullResponseBytes":
            MAXIMUM_PRODUCTION_FULL_RESPONSE_BYTES,
    }


def _encoded_size(value: Any) -> int:
    encoder = json.JSONEncoder(
        sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return sum(
        len(chunk.encode("utf-8")) for chunk in encoder.iterencode(value))


def _proof_prefix(namespace: str, index: int) -> str:
    digest = hashlib.sha256(
        f"{namespace}:{index}".encode("utf-8")).hexdigest()[:16]
    return f"proof-{namespace}-{index:06d}-{digest}-"


def _pad_rows_to_exact_size(
        container: Any, rows: list[Dict[str, Any]], target_bytes: int,
        namespace: str) -> None:
    if not rows:
        raise ValueError(f"{namespace}_has_no_padding_rows")
    for index, row in enumerate(rows):
        row["resourceProofFiller"] = _proof_prefix(namespace, index)
    remaining = target_bytes - _encoded_size(container)
    if remaining < 0:
        raise ValueError(f"{namespace}_base_exceeds_target")
    each, extra = divmod(remaining, len(rows))
    for index, row in enumerate(rows):
        addition = each + (1 if index < extra else 0)
        row["resourceProofFiller"] += "x" * addition
        if len(row["resourceProofFiller"].encode("utf-8")) > \
                MAX_FILLER_BYTES_PER_ROW:
            raise ValueError(f"{namespace}_filler_exceeds_bound")
    if _encoded_size(container) != target_bytes:
        raise AssertionError(f"{namespace}_target_size_mismatch")


def _state_rows(state: Mapping[str, Any], keys: Iterable[str]) \
        -> list[Dict[str, Any]]:
    return [
        row for key in keys for row in (state.get(key) or [])
        if isinstance(row, dict)
    ]


def _market_ledger_fixture() -> Dict[str, Any]:
    state = argus_market_ledger.empty_state()
    series = sorted(argus_market_ledger.SERIES)
    for index in range(SECTION_TARGET_COUNTS[
            "marketLedger"]["observations"]):
        series_id = series[index % len(series)]
        state["observations"].append({
            "id": f"market-observation-{index:06d}",
            "seriesId": series_id,
            "periodEnd": f"2024-{1 + (index // 28) % 12:02d}-{1 + index % 28:02d}",
            "availableFrom": "2026-08-12T00:00:00Z",
            "value": round(100.0 + index / 100.0, 4),
            "unit": argus_market_ledger.SERIES[series_id][0],
            "source": "deterministic_resource_proof",
            "sourceKind": "derived",
            "status": "live", "sequence": index + 1,
        })
    for index in range(SECTION_TARGET_COUNTS[
            "marketLedger"]["derivedMetrics"]):
        state["derivedMetrics"].append({
            "id": f"market-derived-{index:06d}",
            "asOf": f"2026-08-12T00:{index % 60:02d}:00Z",
            "metric": f"derived-{index % 32:02d}",
            "value": round(index / 100.0, 4),
        })
    for index in range(SECTION_TARGET_COUNTS[
            "marketLedger"]["turningPoints"]):
        state["turningPoints"].append({
            "id": f"market-turn-{index:06d}",
            "effectiveFrom": f"2026-08-12T{index % 24:02d}:00:00Z",
            "kind": "deterministic_turn", "sequence": index + 1,
        })
    for index in range(SECTION_TARGET_COUNTS[
            "marketLedger"]["backtests"]):
        state["backtests"].append({
            "id": f"market-backtest-{index:06d}",
            "asOf": FIXED_NOW, "status": "verified",
        })
    for index in range(SECTION_TARGET_COUNTS[
            "marketLedger"]["imports"]):
        state["imports"].append({
            "importId": f"market-import-{index:06d}",
            "asOf": FIXED_NOW, "status": "verified",
        })
    state["lastUpdatedAt"] = FIXED_NOW
    state["lastRebuiltObservationCount"] = len(state["observations"])
    state["lastRebuiltAt"] = FIXED_NOW
    normalized = argus_market_ledger.normalize_state(state)
    _pad_rows_to_exact_size(
        normalized,
        _state_rows(normalized, (
            "observations", "derivedMetrics", "turningPoints",
            "backtests", "imports")),
        SECTION_TARGET_BYTES["marketLedger"], "market")
    return normalized


def _chart_intelligence_fixture() -> Dict[str, Any]:
    counts = SECTION_TARGET_COUNTS["chartIntelligence"]
    state = argus_chart_intelligence.empty_state()
    definitions = (
        ("snapshots", "chart-snapshot", "periodEnd", counts["snapshots"]),
        ("zones", "chart-zone", "effectiveFrom", counts["zones"]),
        ("turningPoints", "chart-turn", "effectiveFrom",
         counts["turningPoints"]),
        ("reactionAnomalies", "chart-reaction", "effectiveFrom",
         counts["reactionAnomalies"]),
        ("relationshipBreaks", "chart-relation", "effectiveFrom",
         counts["relationshipBreaks"]),
        ("invalidations", "chart-invalidation", "invalidatedAt",
         counts["invalidations"]),
    )
    for key, prefix, time_key, count in definitions:
        state[key] = [{
            "id": f"{prefix}-{index:06d}",
            time_key: f"2026-08-12T{index % 24:02d}:{index % 60:02d}:00Z",
            "status": "verified", "sequence": index + 1,
        } for index in range(count)]
    state["lastUpdatedAt"] = FIXED_NOW
    normalized = argus_chart_intelligence.normalize_state(state)
    _pad_rows_to_exact_size(
        normalized, _state_rows(normalized, counts),
        SECTION_TARGET_BYTES["chartIntelligence"], "chart")
    return normalized


def _today_intelligence_fixture() -> Dict[str, Any]:
    counts = SECTION_TARGET_COUNTS["todayIntelligence"]
    state = argus_today_intelligence.empty_state()
    state["snapshots"] = [{
        "id": f"today-snapshot-{index:06d}",
        "asOf": f"2026-08-12T{index % 24:02d}:{index % 60:02d}:00Z",
        "status": "verified", "sequence": index + 1,
    } for index in range(counts["snapshots"])]
    state["shortSellingHistory"] = [{
        "id": f"today-short-{index:06d}",
        "date": f"2024-{1 + (index // 28) % 12:02d}-{1 + index % 28:02d}",
        "revision": 0, "value": round(index / 100.0, 4),
    } for index in range(counts["shortSellingHistory"])]
    state["failedRallyOutcomes"] = [{
        "id": f"today-outcome-{index:06d}",
        "date": f"2025-{1 + (index // 28) % 12:02d}-{1 + index % 28:02d}",
        "status": "resolved", "sequence": index + 1,
    } for index in range(counts["failedRallyOutcomes"])]
    state["lastUpdatedAt"] = FIXED_NOW
    normalized = argus_today_intelligence.normalize_state(state)
    _pad_rows_to_exact_size(
        normalized, _state_rows(normalized, counts),
        SECTION_TARGET_BYTES["todayIntelligence"], "today")
    return normalized


def _market_replay_fixture() -> Dict[str, Any]:
    counts = SECTION_TARGET_COUNTS["marketReplay"]
    state = argus_market_replay.empty_state()
    state["contexts"] = [{
        "contextId": f"replay-context-{index:06d}",
        "instrumentId": f"resource-instrument-{index:06d}",
        "horizon": argus_market_replay.HORIZONS[
            index % len(argus_market_replay.HORIZONS)],
        "methodVersion": argus_market_replay.METHOD_VERSION,
        "asOf": f"2026-08-12T{index % 24:02d}:00:00Z",
        "status": "verified",
    } for index in range(counts["contexts"])]
    state["contextHistory"] = [{
        "contextId": f"replay-history-{index:06d}",
        "instrumentId": f"resource-instrument-{index % 24:06d}",
        "horizon": argus_market_replay.HORIZONS[
            index % len(argus_market_replay.HORIZONS)],
        "methodVersion": argus_market_replay.METHOD_VERSION,
        "asOf": f"2026-08-12T{index % 24:02d}:{index % 60:02d}:00Z",
    } for index in range(counts["contextHistory"])]
    state["lastUpdatedAt"] = FIXED_NOW
    normalized = argus_market_replay.normalize_state(state)
    _pad_rows_to_exact_size(
        normalized, _state_rows(normalized, counts),
        SECTION_TARGET_BYTES["marketReplay"], "replay")
    return normalized


def _journal_fixture() -> list[Dict[str, Any]]:
    events = []
    for index in range(EXPECTED_JOURNAL_COUNT):
        event_key = hashlib.sha256(
            f"event:{index}".encode("utf-8")).hexdigest()
        body = {
            "eventId": f"evt-{event_key[:15]}",
            "idempotencyKey": f"resource-proof-{event_key[:40]}",
            "aggregateType": "mission",
            "aggregateId": f"mission-{index % 26:011d}",
            "sequence": index + 1,
            "eventType": "diagnostic_cycle_closed",
            "occurredAt": FIXED_NOW,
            "privacyClassification": "public_safe",
            "integrityHash": "0" * 16,
        }
        events.append(body)
    _pad_rows_to_exact_size(
        events, events, SECTION_TARGET_BYTES["opsJournal"], "journal")
    for event in events:
        event["integrityHash"] = argus_remote_journal._h({
            key: value for key, value in event.items()
            if key != "integrityHash"})
    if _encoded_size(events) != SECTION_TARGET_BYTES["opsJournal"]:
        raise AssertionError("journal_hash_size_changed")
    return events


def _outcome_fixture() -> list[Dict[str, Any]]:
    outcomes = [{
        "id": f"out-{hashlib.sha256(f'outcome:{index}'.encode()).hexdigest()[:15]}",
        "forecastId": f"forecast-{index:06d}",
        "resolvedAt": FIXED_NOW,
        "status": "resolved",
        "privacyClassification": "public_safe",
        "integrityHash": "0" * 16,
    } for index in range(EXPECTED_OUTCOME_COUNT)]
    _pad_rows_to_exact_size(
        outcomes, outcomes, SECTION_TARGET_BYTES["outcomes"], "outcome")
    for outcome in outcomes:
        outcome["integrityHash"] = argus_remote_journal._h({
            key: value for key, value in outcome.items()
            if key != "integrityHash"})
    if _encoded_size(outcomes) != SECTION_TARGET_BYTES["outcomes"]:
        raise AssertionError("outcome_hash_size_changed")
    return outcomes


def _section_counts(value: Mapping[str, Any], keys: Iterable[str]) \
        -> Dict[str, int]:
    return {
        key: len(value.get(key) or {})
        for key in keys
    }


def _section_evidence(
        value: Any, counts: Mapping[str, int]) -> Dict[str, Any]:
    return {"encodedBytes": _encoded_size(value), "counts": dict(counts)}


def _receipt_evidence(receipt: Mapping[str, Any]) -> Dict[str, Any]:
    ops = receipt.get("opsJournal") or []
    manifest = receipt.get("integrityManifest") or {}
    outcomes = receipt.get("outcomes") or []
    return {
        "encodedBytes": _encoded_size(receipt),
        "opsJournalBytes": _encoded_size(ops),
        "opsJournalCount": len(ops),
        "integrityManifestBytes": _encoded_size(manifest),
        "manifestEventCount": len(manifest.get("eventIds") or []),
        "manifestIdempotencyCount": len(
            manifest.get("idempotencyKeys") or []),
        "manifestAggregateCount": len(
            manifest.get("highestSequenceByAggregate") or {}),
        "outcomesBytes": _encoded_size(outcomes),
        "outcomeCount": len(outcomes),
    }


def _within_size_band(value: Any, target: int) -> bool:
    return bool(
        _integer(value) is not None and
        target * (1.0 - SECTION_SIZE_TOLERANCE) <= value <=
        target * (1.0 + SECTION_SIZE_TOLERANCE))


def _fixture_sections_verified(shape: Mapping[str, Any]) -> bool:
    sections = shape.get("sections") or {}
    size_keys = (
        "marketLedger", "verifiedViewSnapshots", "assetChartReports",
        "chartIntelligence", "marketReplay", "todayIntelligence",
        "opsJournal", "outcomes",
    )
    sizes_ok = all(
        _within_size_band(
            (sections.get(key) or {}).get("encodedBytes"),
            SECTION_TARGET_BYTES[key])
        for key in size_keys)
    counts_ok = all(
        (sections.get(key) or {}).get("counts") == expected
        for key, expected in SECTION_TARGET_COUNTS.items())
    journal_ok = (
        (sections.get("opsJournal") or {}).get("counts", {}).get(
            "events") == EXPECTED_JOURNAL_COUNT and
        (sections.get("integrityManifest") or {}).get("counts") == {
            "eventIds": EXPECTED_JOURNAL_COUNT,
            "idempotencyKeys": EXPECTED_JOURNAL_COUNT,
            "highestSequenceByAggregate":
                EXPECTED_JOURNAL_AGGREGATE_COUNT,
        } and
        (sections.get("outcomes") or {}).get("counts", {}).get(
            "outcomes") == EXPECTED_OUTCOME_COUNT)
    return sizes_ok and counts_ok and journal_ok


def _configure_fixture(
        verified_bars_per_record: int,
        asset_bars_per_record: int) -> Dict[str, Any]:
    verified = verified_snapshot.normalize_store(
        fixture._verified_store(verified_bars_per_record))
    assets = asset_cache.normalize_store(
        fixture._asset_store(asset_bars_per_record))
    market = _market_ledger_fixture()
    chart = _chart_intelligence_fixture()
    today = _today_intelligence_fixture()
    replay = _market_replay_fixture()
    journal = _journal_fixture()
    outcomes = _outcome_fixture()
    compacted = [{
        "batchId": f"resource-batch-{index:04d}",
        "eventCount": 10, "compactedAt": FIXED_NOW,
    } for index in range(40)]

    scanner._VERIFIED_VIEW_SNAPSHOTS = verified
    scanner._ASSET_CHART_REPORTS = assets
    scanner._MARKET_LEDGER = market
    scanner._CHART_INTELLIGENCE = chart
    scanner._TODAY_INTELLIGENCE = today
    scanner._MARKET_REPLAY = replay
    scanner._OPS_JOURNAL = journal
    scanner._OPS_JOURNAL_META = {"totalObserved": len(journal) + 40}
    scanner._OPS_JOURNAL_COMPACT = compacted
    scanner._OUTCOME_LEDGER = outcomes
    scanner._OSINT_PERSIST_STATE["restored"] = True

    journal_projection = argus_remote_journal.snapshot_journal_section(
        events=journal, meta=scanner._OPS_JOURNAL_META,
        compacted=compacted, now_iso=FIXED_NOW)
    sections = {
        "marketLedger": _section_evidence(
            market, _section_counts(
                market, SECTION_TARGET_COUNTS["marketLedger"])),
        "verifiedViewSnapshots": _section_evidence(verified, {
            "current": len(verified.get("current") or {}),
            "history": len(verified.get("history") or []),
        }),
        "assetChartReports": _section_evidence(assets, {
            "records": len(assets.get("records") or {}),
            "current": len(assets.get("current") or {}),
        }),
        "chartIntelligence": _section_evidence(
            chart, _section_counts(
                chart, SECTION_TARGET_COUNTS["chartIntelligence"])),
        "todayIntelligence": _section_evidence(
            today, _section_counts(
                today, SECTION_TARGET_COUNTS["todayIntelligence"])),
        "marketReplay": _section_evidence(
            replay, _section_counts(
                replay, SECTION_TARGET_COUNTS["marketReplay"])),
        "opsJournal": _section_evidence(journal, {
            "events": len(journal),
        }),
        "integrityManifest": _section_evidence(
            journal_projection["integrityManifest"], {
                "eventIds": len(journal_projection[
                    "integrityManifest"].get("eventIds") or []),
                "idempotencyKeys": len(journal_projection[
                    "integrityManifest"].get("idempotencyKeys") or []),
                "highestSequenceByAggregate": len(journal_projection[
                    "integrityManifest"].get(
                        "highestSequenceByAggregate") or {}),
            }),
        "outcomes": _section_evidence(outcomes, {
            "outcomes": len(outcomes),
        }),
    }
    return {
        "verifiedAssetCalibrationBasis": (
            "accepted-normalized-hash-production-byte-calibrated-stores"),
        "verifiedCurrentCount": len(verified.get("current") or {}),
        "verifiedHistoryCount": len(verified.get("history") or []),
        "verifiedBarsPerRecord": verified_bars_per_record,
        "assetRecordCount": len(assets.get("records") or {}),
        "assetCurrentCount": len(assets.get("current") or {}),
        "assetBarsPerRecord": asset_bars_per_record,
        "sections": sections,
    }


def _worker(
        mode: str, cycles: int, verified_bars_per_record: int,
        asset_bars_per_record: int,
        require_cgroup_max_bytes: int) -> Dict[str, Any]:
    if mode not in PATH_MODES:
        raise ValueError("invalid_worker_mode")
    cycles = int(cycles)
    shape = _configure_fixture(
        verified_bars_per_record, asset_bars_per_record)
    original_now = scanner._ai_now_iso
    original_jsonify = scanner.jsonify
    scanner._ai_now_iso = lambda: FIXED_NOW
    captured_receipts: list[Dict[str, Any]] = []

    def observing_jsonify(*args: Any, **kwargs: Any) -> Any:
        if len(args) == 1 and isinstance(args[0], Mapping):
            captured_receipts.append(
                argus_remote_journal.compact_readback_snapshot(args[0]))
        return original_jsonify(*args, **kwargs)

    scanner.jsonify = observing_jsonify
    events_before = _memory_events()
    baseline = _snapshot()
    rows: list[Dict[str, Any]] = []
    receipt_hashes: list[str] = []
    receipt_verified_count = 0
    try:
        with scanner.app.test_client() as client:
            for cycle in range(1, cycles + 1):
                route = ("/api/argus/osint/remote-readback" if
                         mode == "compact" else
                         "/api/argus/osint/memory-snapshot")
                capture_start = len(captured_receipts)
                row = _request(client, route)
                body = row.pop("body")
                del body
                if len(captured_receipts) != capture_start + 1:
                    raise RuntimeError("jsonify_capture_count_mismatch")
                receipt = captured_receipts.pop()
                receipt_hash = str(receipt.get("receiptHash") or "")
                receipt_shape = _receipt_evidence(receipt)
                verified = (
                    argus_remote_journal.verify_compact_readback_snapshot(
                        receipt))
                if verified:
                    receipt_verified_count += 1
                receipt_hashes.append(receipt_hash)
                row.update({
                    "cycle": cycle,
                    "receiptVerified": verified,
                    "receiptCapture": "server_jsonify_observer",
                    "projectedReceiptBytes": receipt_shape["encodedBytes"],
                    "receiptShape": receipt_shape,
                })
                del receipt
                _mark_released(row)
                rows.append(row)
    finally:
        scanner._ai_now_iso = original_now
        scanner.jsonify = original_jsonify

    final = _snapshot()
    events_after = _memory_events()
    summary = _mode_summary(rows, baseline, final)
    conservative_peak = _maximum([
        baseline.get("processPeakRssBytes"),
        final.get("processPeakRssBytes"),
        baseline.get("cgroupPeakBytes"), final.get("cgroupPeakBytes"),
        *(row["bodyLive"].get("processRssBytes")
          for row in rows),
        *(row["bodyLive"].get("pssBytes")
          for row in rows),
        *(row["bodyLive"].get("cgroupCurrentBytes")
          for row in rows),
    ])
    oom_delta = _difference(events_before.get("oom"), events_after.get("oom"))
    oom_kill_delta = _difference(
        events_before.get("oomKill"), events_after.get("oomKill"))
    cgroup_max = final.get("cgroupMaxBytes")
    strict_linux = bool(require_cgroup_max_bytes)
    receipt_shapes = [row.get("receiptShape") or {} for row in rows]
    checks = {
        "exactly32LongLivedCycles": (
            cycles == MINIMUM_CYCLES and len(rows) == MINIMUM_CYCLES),
        "allHttpResponsesSuccessful": summary["http200Count"] == cycles,
        "receiptVerified100Percent": receipt_verified_count == cycles,
        "receiptDigestStable": (
            len(receipt_hashes) == cycles and
            len(set(receipt_hashes)) == 1 and bool(receipt_hashes[0])),
        "fixtureSectionsProductionShaped": _fixture_sections_verified(shape),
        "receiptProductionSized": bool(receipt_shapes) and all(
            COMPACT_RESPONSE_MIN_BYTES <= item.get("encodedBytes", 0) <=
            COMPACT_RESPONSE_MAX_BYTES for item in receipt_shapes),
        "receiptCountsProductionShaped": bool(receipt_shapes) and all(
            item.get("opsJournalCount") == EXPECTED_JOURNAL_COUNT and
            item.get("manifestEventCount") == EXPECTED_JOURNAL_COUNT and
            item.get("manifestIdempotencyCount") ==
            EXPECTED_JOURNAL_COUNT and
            item.get("manifestAggregateCount") ==
            EXPECTED_JOURNAL_AGGREGATE_COUNT and
            item.get("outcomeCount") == EXPECTED_OUTCOME_COUNT
            for item in receipt_shapes),
        "compactHttpResponseProductionSized": (
            mode != "compact" or all(
                COMPACT_RESPONSE_MIN_BYTES <= row["responseBytes"] <=
                COMPACT_RESPONSE_MAX_BYTES for row in rows)),
        "plateauBelow128MiB": summary["plateauBelow128MiB"],
        "logicalPeakBelow3GiB": (
            _integer(conservative_peak) is not None and
            conservative_peak < LOGICAL_PEAK_LIMIT_BYTES),
        "requiredLinuxTelemetryComplete": (
            not strict_linux or summary["requiredLinuxTelemetryComplete"]),
        "exact4GiBCgroup": (
            not strict_linux or
            cgroup_max == require_cgroup_max_bytes),
        "oomDeltaZero": (
            not strict_linux or oom_delta == 0),
        "oomKillDeltaZero": (
            not strict_linux or oom_kill_delta == 0),
        "productionShapedFullResponse": (
            mode != "full" or
            MINIMUM_PRODUCTION_FULL_RESPONSE_BYTES <=
            summary["responseBytes"]["minimum"] <=
            MAXIMUM_PRODUCTION_FULL_RESPONSE_BYTES),
    }
    return {
        "schemaVersion": "argus-memory-snapshot-resource-worker-v2",
        "processTopology": "one-long-lived-worker-one-http-mode",
        "mode": mode,
        "processId": os.getpid(),
        "cycles": cycles,
        "fixtureShape": shape,
        "fixedProjectionTime": FIXED_NOW,
        "baseline": baseline,
        "final": final,
        "summary": summary,
        "receiptShape": receipt_shapes[0] if receipt_shapes else {},
        "receiptHashes": receipt_hashes,
        "receiptVerifiedCount": receipt_verified_count,
        "conservativePeakBytes": conservative_peak,
        "cgroup": {
            "requiredMaxBytes": require_cgroup_max_bytes,
            "observedMaxBytes": cgroup_max,
            "eventsBefore": events_before,
            "eventsAfter": events_after,
            "oomDelta": oom_delta,
            "oomKillDelta": oom_kill_delta,
        },
        "runtimeActions": {
            "forcedCollectionInvoked": False,
            "allocatorTrimInvoked": False,
            "restartInvoked": False,
        },
        "checks": checks,
        "passed": all(checks.values()),
    }


def _worker_command(
        mode: str, cycles: int, verified_bars_per_record: int,
        asset_bars_per_record: int,
        require_cgroup_max_bytes: int) -> list[str]:
    return [
        sys.executable, "-B", str(pathlib.Path(__file__).resolve()),
        "--worker-mode", mode, "--cycles", str(cycles),
        "--verified-bars-per-record", str(verified_bars_per_record),
        "--asset-bars-per-record", str(asset_bars_per_record),
        "--require-cgroup-max-bytes", str(require_cgroup_max_bytes),
    ]


def run(
        cycles: int = MINIMUM_CYCLES, *,
        verified_bars_per_record: int =
        DEFAULT_VERIFIED_BARS_PER_RECORD,
        asset_bars_per_record: int = DEFAULT_ASSET_BARS_PER_RECORD,
        require_cgroup_max_bytes: int = 0) -> Dict[str, Any]:
    cycles = int(cycles)
    environment = dict(os.environ)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PYTHONHASHSEED"] = "0"
    started = time.monotonic()
    workers = [
        _run_worker(
            mode, cycles, verified_bars_per_record,
            asset_bars_per_record, require_cgroup_max_bytes, environment)
        for mode in PATH_MODES
    ]
    by_mode = {worker.get("mode"): worker for worker in workers}
    compact_worker = by_mode.get("compact") or {}
    full_worker = by_mode.get("full") or {}
    compact = compact_worker.get("summary") or {}
    full = full_worker.get("summary") or {}
    compact_hashes = compact_worker.get("receiptHashes") or []
    full_hashes = full_worker.get("receiptHashes") or []
    parity_count = sum(
        left == right and bool(left)
        for left, right in zip(compact_hashes, full_hashes))
    comparison = _comparison_metrics(compact, full)
    comparison.update({
        "exactReceiptParityCount": parity_count,
        "compactReceiptVerifiedCount": compact_worker.get(
            "receiptVerifiedCount", 0),
        "fullProjectionReceiptVerifiedCount": full_worker.get(
            "receiptVerifiedCount", 0),
        "conservativePeakBytes": _maximum(
            worker.get("conservativePeakBytes") for worker in workers),
        "logicalPeakLimitBytes": LOGICAL_PEAK_LIMIT_BYTES,
        "plateauLimitBytes": PLATEAU_LIMIT_BYTES,
    })
    abnormal_exit_count = sum(
        int(worker.get("abnormalExitCount") or 0) for worker in workers)
    oom_values = [
        (worker.get("cgroup") or {}).get("oomDelta")
        for worker in workers
    ]
    oom_kill_values = [
        (worker.get("cgroup") or {}).get("oomKillDelta")
        for worker in workers
    ]
    oom_count = (sum(oom_values)
                 if all(_integer(value) is not None for value in oom_values)
                 else memory.UNKNOWN)
    oom_kill_count = (
        sum(oom_kill_values)
        if all(_integer(value) is not None for value in oom_kill_values)
        else memory.UNKNOWN)
    pids = [worker.get("processId") for worker in workers]
    fixture_shapes = [worker.get("fixtureShape") for worker in workers]
    cgroup_maxima = [
        (worker.get("cgroup") or {}).get("observedMaxBytes")
        for worker in workers
    ]
    compact_rows = compact.get("rows") or []
    full_rows = full.get("rows") or []
    checks = {
        "exactlyTwoFreshLongLivedWorkers": (
            len(workers) == 2 and len(set(pids)) == 2 and
            all(_integer(pid) is not None for pid in pids)),
        "exactly32CyclesPerWorker": (
            cycles == MINIMUM_CYCLES and
            all(worker.get("cycles") == MINIMUM_CYCLES
                for worker in workers)),
        "workersExitedNormallyWithoutStderr": all(
            worker.get("returnCode") == 0 and
            worker.get("timedOut") is False and
            worker.get("outputValid") is True and
            worker.get("stderrPresent") is False
            for worker in workers),
        "workerSelfChecksPassed": all(
            worker.get("passed") is True for worker in workers),
        "fixtureShapeAndProjectionTimeIdentical": (
            len(fixture_shapes) == 2 and
            fixture_shapes[0] == fixture_shapes[1] and
            all(worker.get("fixedProjectionTime") == FIXED_NOW
                for worker in workers)),
        "productionShapedSectionsAndReceipt": all(
            (worker.get("checks") or {}).get(
                "fixtureSectionsProductionShaped") is True and
            (worker.get("checks") or {}).get(
                "receiptProductionSized") is True and
            (worker.get("checks") or {}).get(
                "receiptCountsProductionShaped") is True
            for worker in workers),
        "exactReceiptParity100Percent": (
            len(compact_hashes) == len(full_hashes) == MINIMUM_CYCLES and
            parity_count == MINIMUM_CYCLES),
        "receiptVerification100Percent": (
            compact_worker.get("receiptVerifiedCount") == MINIMUM_CYCLES and
            full_worker.get("receiptVerifiedCount") == MINIMUM_CYCLES),
        "candidateResponseSmallerEveryCycle": (
            len(compact_rows) == len(full_rows) == MINIMUM_CYCLES and
            all(left.get("responseBytes", 0) < right.get("responseBytes", 0)
                for left, right in zip(compact_rows, full_rows))),
        "compactResponseProductionSized": (
            _integer((compact.get("responseBytes") or {}).get("minimum")) is
            not None and
            COMPACT_RESPONSE_MIN_BYTES <=
            compact["responseBytes"]["minimum"] <=
            compact["responseBytes"]["maximum"] <=
            COMPACT_RESPONSE_MAX_BYTES),
        "productionShapedFullResponse": (
            _integer((full.get("responseBytes") or {}).get("minimum")) is
            not None and
            MINIMUM_PRODUCTION_FULL_RESPONSE_BYTES <=
            full["responseBytes"]["minimum"] <=
            MAXIMUM_PRODUCTION_FULL_RESPONSE_BYTES),
        "materialResponseReduction": (
            _integer(comparison["responseByteReductionBytes"]) is not None and
            comparison["responseByteReductionBytes"] >=
            MINIMUM_MATERIAL_RESPONSE_REDUCTION_BYTES),
        "processPeakRssMateriallyReduced": (
            _integer(comparison["processPeakRssReductionBytes"]) is not None and
            comparison["processPeakRssReductionBytes"] >=
            MINIMUM_MATERIAL_RSS_REDUCTION_BYTES),
        "arenaMaximumMateriallyReduced": (
            _integer(comparison["arenaMaximumReductionBytes"]) is not None and
            comparison["arenaMaximumReductionBytes"] >=
            MINIMUM_MATERIAL_RSS_REDUCTION_BYTES),
        "durationP50Reduced": (
            isinstance(comparison["durationP50ReductionMs"], (int, float)) and
            comparison["durationP50ReductionMs"] > 0),
        "bothPlateausBelow128MiB": (
            compact.get("plateauBelow128MiB") is True and
            full.get("plateauBelow128MiB") is True),
        "bothLogicalPeaksBelow3GiB": all(
            _integer(worker.get("conservativePeakBytes")) is not None and
            worker["conservativePeakBytes"] < LOGICAL_PEAK_LIMIT_BYTES
            for worker in workers),
        "requiredLinuxTelemetryComplete": all(
            (worker.get("summary") or {}).get(
                "requiredLinuxTelemetryComplete") is True
            for worker in workers),
        "exact4GiBCgroupForBothWorkers": (
            bool(require_cgroup_max_bytes) and
            all(value == require_cgroup_max_bytes
                for value in cgroup_maxima)),
        "oomAndOomKillZero": oom_count == 0 and oom_kill_count == 0,
        "noRuntimeControlActions": all(
            not any((worker.get("runtimeActions") or {}).values())
            for worker in workers),
    }
    worker_evidence = []
    for worker in workers:
        worker_evidence.append({
            key: worker.get(key) for key in (
                "mode", "processId", "cycles", "fixtureShape",
                "fixedProjectionTime", "receiptHashes",
                "receiptVerifiedCount", "receiptShape",
                "conservativePeakBytes", "cgroup",
                "runtimeActions", "checks", "returnCode", "signal",
                "timedOut", "outputValid", "stderrPresent",
                "abnormalExitCount", "passed")
        })
    return {
        "schemaVersion": "argus-memory-snapshot-resource-proof-v2",
        "processTopology": "two-fresh-long-lived-workers-one-mode-each",
        "cyclesPerMode": cycles,
        "fixtureShape": (fixture_shapes[0] if fixture_shapes else {}),
        "fixedProjectionTime": FIXED_NOW,
        "workers": worker_evidence,
        "compact": compact,
        "full": full,
        "comparison": comparison,
        "cgroup": {
            "requiredMaxBytes": require_cgroup_max_bytes,
            "observedMaxBytesPerWorker": cgroup_maxima,
            "oomDelta": oom_count,
            "oomKillDelta": oom_kill_count,
        },
        "runtimeActions": {
            "forcedCollectionInvoked": False,
            "allocatorTrimInvoked": False,
            "restartInvoked": False,
        },
        "returnCode": 0 if abnormal_exit_count == 0 else 1,
        "signal": None,
        "timedOut": any(worker.get("timedOut") for worker in workers),
        "outputValid": all(worker.get("outputValid") for worker in workers),
        "stderrPresent": any(worker.get("stderrPresent") for worker in workers),
        "abnormalExitCount": abnormal_exit_count,
        "oomCount": oom_count,
        "supervisorElapsedMs": round(
            (time.monotonic() - started) * 1000, 3),
        "checks": checks,
        "passed": all(checks.values()),
    }


def _run_worker(
        mode: str, cycles: int, verified_bars_per_record: int,
        asset_bars_per_record: int, require_cgroup_max_bytes: int,
        environment: Mapping[str, str]) -> Dict[str, Any]:
    started = time.monotonic()
    try:
        completed = subprocess.run(
            _worker_command(
                mode, cycles, verified_bars_per_record,
                asset_bars_per_record, require_cgroup_max_bytes),
            cwd=str(ROOT), env=dict(environment), capture_output=True,
            text=True, timeout=1800, check=False)
    except subprocess.TimeoutExpired:
        return {
            "mode": mode, "cycles": cycles, "returnCode": None,
            "signal": None, "timedOut": True, "outputValid": False,
            "stderrPresent": False, "abnormalExitCount": 1,
            "runtimeActions": {
                "forcedCollectionInvoked": False,
                "allocatorTrimInvoked": False,
                "restartInvoked": False,
            },
            "passed": False,
        }
    try:
        report = json.loads(completed.stdout)
        output_valid = isinstance(report, dict)
    except (TypeError, ValueError, json.JSONDecodeError):
        report = {}
        output_valid = False
    report.update({
        "mode": mode,
        "returnCode": completed.returncode,
        "signal": -completed.returncode if completed.returncode < 0 else None,
        "timedOut": False,
        "outputValid": output_valid,
        "stderrPresent": bool(completed.stderr.strip()),
        "abnormalExitCount": 0 if completed.returncode == 0 else 1,
        "workerElapsedMs": round((time.monotonic() - started) * 1000, 3),
    })
    report["passed"] = bool(
        report.get("passed") and output_valid and
        completed.returncode == 0 and not completed.stderr.strip())
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cycles", type=int, default=MINIMUM_CYCLES)
    parser.add_argument(
        "--verified-bars-per-record", type=int,
        default=DEFAULT_VERIFIED_BARS_PER_RECORD)
    parser.add_argument(
        "--asset-bars-per-record", type=int,
        default=DEFAULT_ASSET_BARS_PER_RECORD)
    parser.add_argument("--require-cgroup-max-bytes", type=int, default=0)
    parser.add_argument("--output")
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--worker-mode", choices=PATH_MODES,
                        help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker_mode:
        report = _worker(
            args.worker_mode, args.cycles, args.verified_bars_per_record,
            args.asset_bars_per_record, args.require_cgroup_max_bytes)
    else:
        report = run(
            args.cycles,
            verified_bars_per_record=args.verified_bars_per_record,
            asset_bars_per_record=args.asset_bars_per_record,
            require_cgroup_max_bytes=args.require_cgroup_max_bytes)
    encoded = json.dumps(
        report, ensure_ascii=False, indent=2, sort_keys=True)
    if not args.quiet:
        print(encoded)
    if args.output:
        pathlib.Path(args.output).write_text(
            encoded + "\n", encoding="utf-8")
    return 0 if report.get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
