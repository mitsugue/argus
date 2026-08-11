"""Bounded, scalar-only mission memory attribution diagnostics.

This module is deliberately observational.  It never triggers garbage
collection, allocator reclamation, checkpoint work, or persistence.  Every
collector is fail-open so an unavailable Linux diagnostic cannot affect a
mission or checkpoint outcome.
"""

from __future__ import annotations

import copy
import ctypes
import datetime as dt
import json
import os
import pathlib
import re
import resource
import sys
import threading
import time
from collections import deque
from typing import Any, Dict, Iterable, Mapping, Optional


SCHEMA_VERSION = "argus-memory-attribution-v3"
OPERATION_SCHEMA_VERSION = "argus-operation-memory-v2"
UNKNOWN = "UNKNOWN"
NOT_APPLICABLE = "NOT_APPLICABLE"
DEFAULT_HISTORY_LIMIT = 16
MAXIMUM_HISTORY_LIMIT = 32
DEFAULT_OPERATION_LIMIT = 32
MAXIMUM_OPERATION_LIMIT = 64
DEFAULT_OPERATION_THRESHOLD_BYTES = 1024 * 1024
DEFAULT_HEAVY_HITTER_LIMIT = 16
MAXIMUM_HEAVY_HITTER_LIMIT = 16
DEFAULT_KNOWN_OPERATION_LIMIT = 64
DEFAULT_INTERMISSION_LIMIT = 16
DEFAULT_ACTIVE_OPERATION_LIMIT = 256
MAXIMUM_ACTIVE_OPERATION_LIMIT = 256

PHASES = (
    "T0", "T1", "T2", "T3", "T4", "T5", "T6",
    "T7", "T8", "T9", "T10", "T11", "T12",
)

PRELUDE_PHASES = (
    "P0", "P1", "P2", "P3", "P4",
)

MISSION_PATH_PHASES = (
    "M0", "M1", "M2", "M3", "M4", "M5", "M6", "M7", "M8",
    "M9", "M10", "M11", "M12", "M13", "M14", "M15", "M16",
    "M17", "M18", "M19", "M20", "M21", "M22", "M23",
)

SOURCE_PHASES = (
    "S0", "S1", "S2", "S3", "S4", "S5", "S6",
    "S7V0", "S7V1", "S7V2", "S7V3", "S7V4", "S7V5", "S7V6",
    "S7V7",
    "S7A0", "S7A1", "S7A2", "S7A3", "S7A4", "S7A5", "S7A6",
    "S7A7",
    "S7", "S8",
)

_SOURCE_DELTA_PATHS = {
    "rssBytes": ("process", "vmRssBytes"),
    "rssAnonBytes": ("process", "rssAnonBytes"),
    "rssFileBytes": ("process", "rssFileBytes"),
    "pssBytes": ("smapsRollup", "pssBytes"),
    "arenaBytes": ("allocatorMetrics", "arenaBytes"),
    "allocatedBytes": ("allocatorMetrics", "allocatedBytes"),
    "freeBytes": ("allocatorMetrics", "freeBytes"),
    "topReleasableBytes": ("allocatorMetrics", "topReleasableBytes"),
    "cgroupCurrentBytes": ("cgroup", "memoryCurrentBytes"),
    "cgroupAnonBytes": ("cgroup", "stat", "anon"),
}

_OPERATION_KINDS = {
    "HTTP", "scheduler", "background", "journal", "provider", "internal",
}
_OPERATION_METADATA_FIELDS = {
    "missionActive", "statusCode", "result", "errorClass", "taskClass",
    "triggerSource", "natural",
}

_STATUS_FIELDS = {
    "VmRSS": "vmRssBytes",
    "VmSize": "vmSizeBytes",
    "VmData": "vmDataBytes",
    "RssAnon": "rssAnonBytes",
    "RssFile": "rssFileBytes",
    "RssShmem": "rssShmemBytes",
    "Threads": "threads",
}

_SMAPS_FIELDS = {
    "Rss": "rssBytes",
    "Pss": "pssBytes",
    "Pss_Anon": "pssAnonBytes",
    "Pss_File": "pssFileBytes",
    "Private_Clean": "privateCleanBytes",
    "Private_Dirty": "privateDirtyBytes",
    "Shared_Clean": "sharedCleanBytes",
    "Shared_Dirty": "sharedDirtyBytes",
    "Anonymous": "anonymousBytes",
    "AnonHugePages": "anonHugePagesBytes",
    "Swap": "swapBytes",
}

_CGROUP_STAT_FIELDS = (
    "anon", "file", "kernel", "kernel_stack", "pagetables", "percpu",
    "sock", "shmem", "file_mapped", "file_dirty", "file_writeback",
    "slab", "slab_reclaimable", "slab_unreclaimable",
)

_LOGICAL_FIELDS = (
    "asyncioTasks", "pendingFutures", "subprocessHandles",
    "httpSessionObjects", "httpResponseObjects", "sqliteConnections",
    "sqliteCursors", "generationContexts", "missionBookkeepingEntries",
    "telemetryHistoryLength", "schedulerHistoryLength", "cacheEntryCount",
    "remoteJournalQueueCount", "retainedV2MetadataCount", "largeBytesCount",
    "largeBytearrayCount", "largeMemoryviewCount",
)


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def _unknown_map(keys: Iterable[str]) -> Dict[str, Any]:
    return {str(key): UNKNOWN for key in keys}


def _read_text(path: pathlib.Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except (FileNotFoundError, PermissionError, OSError, UnicodeError):
        return None


def _integer(value: Any) -> Any:
    if isinstance(value, bool):
        return UNKNOWN
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return UNKNOWN


def _parse_kib_file(path: pathlib.Path, fields: Mapping[str, str]) -> Dict[str, Any]:
    output = _unknown_map(fields.values())
    raw = _read_text(path)
    if raw is None:
        return output
    for line in raw.splitlines():
        if ":" not in line:
            continue
        source, value = line.split(":", 1)
        target = fields.get(source.strip())
        if not target:
            continue
        token = value.strip().split()
        parsed = _integer(token[0] if token else None)
        if parsed == UNKNOWN:
            continue
        output[target] = parsed if source.strip() == "Threads" else parsed * 1024
    return output


def process_metrics() -> Dict[str, Any]:
    metrics = _parse_kib_file(pathlib.Path("/proc/self/status"), _STATUS_FIELDS)
    try:
        metrics["fdCount"] = len(os.listdir("/proc/self/fd"))
    except (FileNotFoundError, PermissionError, OSError):
        metrics["fdCount"] = UNKNOWN
    if metrics["vmRssBytes"] == UNKNOWN:
        try:
            peak = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
            metrics["rssPeakBytes"] = peak if sys.platform == "darwin" else peak * 1024
        except (OSError, ValueError, OverflowError):
            metrics["rssPeakBytes"] = UNKNOWN
    else:
        metrics["rssPeakBytes"] = UNKNOWN
    return metrics


def smaps_rollup_metrics() -> Dict[str, Any]:
    return _parse_kib_file(
        pathlib.Path("/proc/self/smaps_rollup"), _SMAPS_FIELDS)


def _read_cgroup_number(path: pathlib.Path) -> Any:
    raw = _read_text(path)
    if raw is None:
        return UNKNOWN
    value = raw.strip()
    if value == "max":
        return "max"
    return _integer(value)


def cgroup_metrics(root: str = "/sys/fs/cgroup") -> Dict[str, Any]:
    base = pathlib.Path(root)
    output: Dict[str, Any] = {
        "memoryCurrentBytes": _read_cgroup_number(base / "memory.current"),
        "memoryPeakBytes": _read_cgroup_number(base / "memory.peak"),
        "memoryMaxBytes": _read_cgroup_number(base / "memory.max"),
        "stat": _unknown_map(_CGROUP_STAT_FIELDS),
    }
    raw = _read_text(base / "memory.stat")
    if raw is None:
        return output
    parsed: Dict[str, int] = {}
    for line in raw.splitlines():
        tokens = line.split()
        if len(tokens) == 2 and tokens[0] in _CGROUP_STAT_FIELDS:
            number = _integer(tokens[1])
            if number != UNKNOWN:
                parsed[tokens[0]] = number
    output["stat"].update(parsed)
    return output


class _Mallinfo2(ctypes.Structure):
    _fields_ = [
        ("arena", ctypes.c_size_t), ("ordblks", ctypes.c_size_t),
        ("smblks", ctypes.c_size_t), ("hblks", ctypes.c_size_t),
        ("hblkhd", ctypes.c_size_t), ("usmblks", ctypes.c_size_t),
        ("fsmblks", ctypes.c_size_t), ("uordblks", ctypes.c_size_t),
        ("fordblks", ctypes.c_size_t), ("keepcost", ctypes.c_size_t),
    ]


def allocator_metrics() -> Any:
    """Read glibc counters only; never invoke ``malloc_trim``."""
    if not sys.platform.startswith("linux"):
        return "UNAVAILABLE"
    try:
        libc = ctypes.CDLL(None)
        mallinfo2 = libc.mallinfo2
        mallinfo2.argtypes = []
        mallinfo2.restype = _Mallinfo2
        value = mallinfo2()
        return {
            "status": "AVAILABLE",
            "arenaBytes": int(value.arena),
            "freeChunkCount": int(value.ordblks),
            "mmapBytes": int(value.hblkhd),
            "allocatedBytes": int(value.uordblks),
            "freeBytes": int(value.fordblks),
            "topReleasableBytes": int(value.keepcost),
        }
    except (AttributeError, OSError, TypeError, ValueError):
        return "UNAVAILABLE"


def _sanitize_scalar(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value[:160]
    return UNKNOWN


def logical_metrics(values: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    output = _unknown_map(_LOGICAL_FIELDS)
    if not isinstance(values, Mapping):
        return output
    for key in _LOGICAL_FIELDS:
        if key in values:
            output[key] = _sanitize_scalar(values.get(key))
    return output


def memory_snapshot(logical: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """Collect one privacy-safe scalar snapshot without raising."""
    try:
        process = process_metrics()
    except Exception:
        process = {**_unknown_map(_STATUS_FIELDS.values()),
                   "fdCount": UNKNOWN, "rssPeakBytes": UNKNOWN}
    try:
        smaps = smaps_rollup_metrics()
    except Exception:
        smaps = _unknown_map(_SMAPS_FIELDS.values())
    try:
        cgroup = cgroup_metrics()
    except Exception:
        cgroup = {"memoryCurrentBytes": UNKNOWN, "memoryPeakBytes": UNKNOWN,
                  "memoryMaxBytes": UNKNOWN,
                  "stat": _unknown_map(_CGROUP_STAT_FIELDS)}
    try:
        allocator = allocator_metrics()
    except Exception:
        allocator = "UNAVAILABLE"
    return {
        "capturedAt": _now(),
        "process": process,
        "smapsRollup": smaps,
        "cgroup": cgroup,
        "allocatorMetrics": allocator,
        "logicalObjects": logical_metrics(logical),
    }


def operation_snapshot() -> Dict[str, Any]:
    """Collect the smaller request/task sample without reading smaps.

    Request boundaries can be frequent, so this intentionally omits PSS and
    logical-object collection.  It is still sufficient to attribute RSS,
    anonymous RSS, allocator and cgroup movement.
    """
    try:
        process = process_metrics()
    except Exception:
        process = {**_unknown_map(_STATUS_FIELDS.values()),
                   "fdCount": UNKNOWN, "rssPeakBytes": UNKNOWN}
    try:
        cgroup = cgroup_metrics()
    except Exception:
        cgroup = {"memoryCurrentBytes": UNKNOWN,
                  "memoryPeakBytes": UNKNOWN,
                  "memoryMaxBytes": UNKNOWN,
                  "stat": _unknown_map(_CGROUP_STAT_FIELDS)}
    try:
        allocator = allocator_metrics()
    except Exception:
        allocator = "UNAVAILABLE"
    return {"capturedAt": _now(), "process": process,
            "cgroup": cgroup, "allocatorMetrics": allocator}


def _nested(value: Any, path: Iterable[str]) -> Any:
    current = value
    for key in path:
        if not isinstance(current, Mapping):
            return UNKNOWN
        current = current.get(key, UNKNOWN)
    return current


def _metric_projection(sample: Mapping[str, Any]) -> Dict[str, Any]:
    return {name: _nested(sample, path)
            for name, path in _SOURCE_DELTA_PATHS.items()}


def _metric_deltas(before: Mapping[str, Any], after: Mapping[str, Any]
                   ) -> Dict[str, Any]:
    left, right = _metric_projection(before), _metric_projection(after)
    return {name: _safe_delta(left.get(name), right.get(name))
            for name in _SOURCE_DELTA_PATHS}


def _phase_projection(sample: Mapping[str, Any]) -> Dict[str, Any]:
    """Keep one fixed scalar projection for high-frequency phase boundaries."""
    process = sample.get("process") if isinstance(sample, Mapping) else {}
    cgroup = sample.get("cgroup") if isinstance(sample, Mapping) else {}
    return {
        "capturedAt": (sample.get("capturedAt")
                       if isinstance(sample, Mapping) else None) or _now(),
        "metrics": _metric_projection(sample),
        "vmDataBytes": ((process or {}).get("vmDataBytes", UNKNOWN)),
        "fdCount": ((process or {}).get("fdCount", UNKNOWN)),
        "threads": ((process or {}).get("threads", UNKNOWN)),
        "cgroupPeakBytes": ((cgroup or {}).get(
            "memoryPeakBytes", UNKNOWN)),
        "cgroupMaxBytes": ((cgroup or {}).get(
            "memoryMaxBytes", UNKNOWN)),
    }


def _projection_deltas(before: Mapping[str, Any],
                       after: Mapping[str, Any]) -> Dict[str, Any]:
    left = before.get("metrics") if isinstance(before, Mapping) else {}
    right = after.get("metrics") if isinstance(after, Mapping) else {}
    return {name: _safe_delta((left or {}).get(name), (right or {}).get(name))
            for name in _SOURCE_DELTA_PATHS}


def _positive(value: Any) -> int:
    return max(0, value) if isinstance(value, int) and not isinstance(
        value, bool) else 0


class _BoundedHeavyHitters:
    """Space-Saving cumulative or exact streaming-maximum top-K sketch."""

    def __init__(self, limit: int, *, mode: str, metric: str):
        self.limit = max(1, min(int(limit), MAXIMUM_HEAVY_HITTER_LIMIT))
        self.mode = mode
        self.metric = metric
        self._entries: Dict[str, Dict[str, Any]] = {}

    def reset(self) -> None:
        self._entries.clear()

    @staticmethod
    def _supplement(row: Mapping[str, Any]) -> Dict[str, Any]:
        deltas = row.get("deltas") or {}
        return {
            "eventCountSinceAdmission": 1,
            "positiveRssBytesSinceAdmission": _positive(
                deltas.get("rssBytes")),
            "positiveArenaBytesSinceAdmission": _positive(
                deltas.get("arenaBytes")),
            "positiveFreeBytesSinceAdmission": _positive(
                deltas.get("freeBytes")),
            "signedAllocatedBytesSinceAdmission": (
                deltas.get("allocatedBytes")
                if isinstance(deltas.get("allocatedBytes"), int) and
                not isinstance(deltas.get("allocatedBytes"), bool) else 0),
            "maxRssDeltaBytesSinceAdmission": (
                deltas.get("rssBytes")
                if isinstance(deltas.get("rssBytes"), int) else UNKNOWN),
            "maxArenaDeltaBytesSinceAdmission": (
                deltas.get("arenaBytes")
                if isinstance(deltas.get("arenaBytes"), int) else UNKNOWN),
            "maxFreeBytesDeltaSinceAdmission": (
                deltas.get("freeBytes")
                if isinstance(deltas.get("freeBytes"), int) else UNKNOWN),
            "maxDurationMsSinceAdmission": row.get("durationMs") or 0,
            "exclusiveCountSinceAdmission": int(
                row.get("concurrencyClass") == "EXCLUSIVE"),
            "overlappedCountSinceAdmission": int(
                row.get("concurrencyClass") == "OVERLAPPED"),
            "unknownCountSinceAdmission": int(
                row.get("concurrencyClass") == "UNKNOWN"),
            "sameThreadCountSinceAdmission": int(
                row.get("completionThreadClass") == "SAME_THREAD"),
            "crossThreadCountSinceAdmission": int(
                row.get("completionThreadClass") == "CROSS_THREAD"),
            "unknownThreadCountSinceAdmission": int(
                row.get("completionThreadClass") == "UNKNOWN"),
            "lastCompletedAt": row.get("completedAt"),
        }

    @staticmethod
    def _merge_supplement(entry: Dict[str, Any],
                          row: Mapping[str, Any]) -> None:
        extra = _BoundedHeavyHitters._supplement(row)
        for field in (
                "eventCountSinceAdmission", "positiveRssBytesSinceAdmission",
                "positiveArenaBytesSinceAdmission",
                "positiveFreeBytesSinceAdmission",
                "signedAllocatedBytesSinceAdmission",
                "exclusiveCountSinceAdmission", "overlappedCountSinceAdmission",
                "unknownCountSinceAdmission", "sameThreadCountSinceAdmission",
                "crossThreadCountSinceAdmission",
                "unknownThreadCountSinceAdmission"):
            entry[field] = int(entry.get(field) or 0) + int(
                extra.get(field) or 0)
        for field in (
                "maxRssDeltaBytesSinceAdmission",
                "maxArenaDeltaBytesSinceAdmission",
                "maxFreeBytesDeltaSinceAdmission",
                "maxDurationMsSinceAdmission"):
            incoming = extra.get(field)
            current = entry.get(field)
            if isinstance(incoming, (int, float)) and (
                    not isinstance(current, (int, float)) or incoming > current):
                entry[field] = incoming
        entry["lastCompletedAt"] = extra.get("lastCompletedAt")

    def observe(self, row: Mapping[str, Any]) -> None:
        key = str(row.get("operationName") or "internal:unknown")[:160]
        raw = (row.get("deltas") or {}).get(self.metric)
        score = _positive(raw) if self.mode == "cumulative" else (
            raw if isinstance(raw, int) and raw > 0 else 0)
        entry = self._entries.get(key)
        if entry is not None:
            if score > 0:
                if self.mode == "cumulative":
                    entry["scoreBytes"] += score
                else:
                    entry["scoreBytes"] = max(entry["scoreBytes"], score)
            self._merge_supplement(entry, row)
            return
        if score <= 0:
            return
        error = 0
        if len(self._entries) >= self.limit:
            victim_key, victim = min(
                self._entries.items(), key=lambda item: item[1]["scoreBytes"])
            if self.mode == "maximum" and score <= victim["scoreBytes"]:
                return
            error = victim["scoreBytes"] if self.mode == "cumulative" else 0
            del self._entries[victim_key]
        entry = {
            "operationType": row.get("operationType"),
            "operationName": key,
            "scoreBytes": score + error,
            "errorUpperBoundBytes": error,
        }
        entry.update(self._supplement(row))
        self._entries[key] = entry

    def view(self) -> list[Dict[str, Any]]:
        output = []
        for entry in sorted(
                self._entries.values(), key=lambda row: row["scoreBytes"],
                reverse=True):
            item = copy.deepcopy(entry)
            item[("estimatedBytes" if self.mode == "cumulative"
                  else "maximumBytes")] = item.pop("scoreBytes")
            if self.mode == "maximum":
                item.pop("errorUpperBoundBytes", None)
            output.append(item)
        return output


def normalize_operation_name(kind: str, name: str) -> str:
    """Return a bounded operation label with no query or dynamic identifier."""
    operation_kind = kind if kind in _OPERATION_KINDS else "internal"
    raw = str(name or "unknown").split("?", 1)[0].split("#", 1)[0]
    raw = re.sub(r"<[^>]+>", "<id>", raw)
    raw = re.sub(
        r"(?i)(?<![a-z0-9])[0-9a-f]{8}-[0-9a-f-]{27,36}(?![a-z0-9])",
        "<id>", raw)
    raw = re.sub(r"(?i)(?<![a-z0-9])[0-9a-f]{12,}(?![a-z0-9])",
                 "<id>", raw)
    raw = re.sub(r"(?<![a-z0-9])\d{3,}(?![a-z0-9])", "<id>", raw)
    raw = re.sub(r"\s+", " ", raw).strip()
    return f"{operation_kind}:{raw}"[:160]


def _operation_metadata(values: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    if not isinstance(values, Mapping):
        return {}
    return {key: _sanitize_scalar(values.get(key))
            for key in _OPERATION_METADATA_FIELDS if key in values}


def _safe_delta(before: Any, after: Any) -> Any:
    if before == NOT_APPLICABLE or after == NOT_APPLICABLE:
        return NOT_APPLICABLE
    if isinstance(before, int) and not isinstance(before, bool) and \
            isinstance(after, int) and not isinstance(after, bool):
        return after - before
    return UNKNOWN


def _rss(record: Mapping[str, Any], phase: str) -> Any:
    phase_row = (record.get("phases") or {}).get(phase) or {}
    if phase_row.get("status") == NOT_APPLICABLE:
        return NOT_APPLICABLE
    return (((phase_row.get("sample") or {}).get("process") or {})
            .get("vmRssBytes", UNKNOWN))


class MemoryAttributionRecorder:
    """Single-flight mission recorder with a bounded completed-history ring."""

    def __init__(self, maximum_records: int = DEFAULT_HISTORY_LIMIT):
        limit = max(1, min(int(maximum_records), MAXIMUM_HISTORY_LIMIT))
        self._maximum_records = limit
        self._history = deque(maxlen=limit)
        self._active: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.RLock()
        self._completed_count = 0
        self._dropped_count = 0
        self._last_end_rss: Any = UNKNOWN

    @property
    def maximum_records(self) -> int:
        return self._maximum_records

    @property
    def history_count(self) -> int:
        with self._lock:
            return len(self._history)

    def reset(self) -> None:
        with self._lock:
            self._history.clear()
            self._active.clear()
            self._completed_count = 0
            self._dropped_count = 0
            self._last_end_rss = UNKNOWN

    def begin(self, record_id: str, metadata: Mapping[str, Any], *,
              initial_sample: Optional[Mapping[str, Any]] = None,
              logical: Optional[Mapping[str, Any]] = None,
              prelude_samples: Optional[Mapping[str, Mapping[str, Any]]] = None,
              mission_path_initial_sample: Optional[Mapping[str, Any]] = None
              ) -> str:
        key = str(record_id or "unknown")[:160]
        clean_metadata = {
            str(name)[:80]: _sanitize_scalar(value)
            for name, value in dict(metadata or {}).items()
        }
        phases = {
            phase: {"status": UNKNOWN, "capturedAt": None, "sample": None,
                    "metadata": {}}
            for phase in PHASES
        }
        source_phases = {
            phase: {"status": UNKNOWN, "capturedAt": None, "sample": None,
                    "metadata": {}, "deltaFromPrevious": {}}
            for phase in SOURCE_PHASES
        }
        prelude_phases = {
            phase: {"status": UNKNOWN, "capturedAt": None,
                    "sampleProjection": None, "metadata": {},
                    "deltaFromPrevious": {}}
            for phase in PRELUDE_PHASES
        }
        mission_path_phases = {
            phase: {"status": UNKNOWN, "capturedAt": None,
                    "sampleProjection": None, "metadata": {},
                    "deltaFromPrevious": {}}
            for phase in MISSION_PATH_PHASES
        }
        with self._lock:
            record = {
                "schemaVersion": SCHEMA_VERSION,
                "recordId": key,
                "metadata": clean_metadata,
                "phases": phases,
                "phaseOrder": [],
                "sourceConstruction": {
                    "phaseLimit": len(SOURCE_PHASES),
                    "phases": source_phases,
                    "phaseOrder": [],
                },
                "preludeAttribution": {
                    "phaseLimit": len(PRELUDE_PHASES),
                    "phases": prelude_phases,
                    "phaseOrder": [],
                },
                "missionPathAttribution": {
                    "phaseLimit": len(MISSION_PATH_PHASES),
                    "phases": mission_path_phases,
                    "phaseOrder": [],
                    "baselineName": "T0",
                    "baselineProjection": _phase_projection(
                        initial_sample or {}),
                },
                "previousMissionEndRSS": self._last_end_rss,
                "differentials": {},
                "startedAt": _now(),
                "completedAt": None,
            }
            self._active[key] = record
        self.capture(key, "T0", sample=initial_sample, logical=logical)
        if isinstance(prelude_samples, Mapping):
            prelude_operations = {
                "P0": "request_entry",
                "P1": "auth_storage_body_lease_constructed",
                "P2": "tick_lease_acquired",
                "P3": "checkpoint_lock_acquired",
                "P4": "initial_wal_read_complete",
            }
            for phase in PRELUDE_PHASES:
                sample = prelude_samples.get(phase)
                if isinstance(sample, Mapping):
                    self.capture_prelude_phase(
                        key, phase, sample=sample,
                        metadata={"operation": prelude_operations[phase]})
        self.capture_mission_path_phase(
            key, "M0", sample=(mission_path_initial_sample or initial_sample),
            logical=logical,
            metadata={"operation": "mission_begin"})
        return key

    def update_metadata(self, record_id: str, values: Mapping[str, Any]) -> None:
        with self._lock:
            record = self._active.get(str(record_id))
            if not record:
                return
            for name, value in dict(values or {}).items():
                record["metadata"][str(name)[:80]] = _sanitize_scalar(value)

    def capture(self, record_id: str, phase: str, *,
                sample: Optional[Mapping[str, Any]] = None,
                logical: Optional[Mapping[str, Any]] = None,
                metadata: Optional[Mapping[str, Any]] = None) -> None:
        if phase not in PHASES:
            return
        key = str(record_id)
        with self._lock:
            record = self._active.get(key)
            if not record:
                return
            row = record["phases"][phase]
            already_captured = row.get("status") == "CAPTURED"
        collected = None
        if not already_captured:
            collected = copy.deepcopy(sample) if isinstance(sample, Mapping) \
                else memory_snapshot(logical)
        with self._lock:
            record = self._active.get(key)
            if not record:
                return
            row = record["phases"][phase]
            if row.get("status") != "CAPTURED":
                row.update({"status": "CAPTURED",
                            "capturedAt": (collected or {}).get(
                                "capturedAt") or _now(),
                            "sample": collected, "metadata": {}})
                record["phaseOrder"].append(phase)
            if isinstance(metadata, Mapping):
                for name, value in metadata.items():
                    row["metadata"][str(name)[:80]] = _sanitize_scalar(value)

    def capture_source_phase(self, record_id: str, phase: str, *,
                             sample: Optional[Mapping[str, Any]] = None,
                             logical: Optional[Mapping[str, Any]] = None,
                             metadata: Optional[Mapping[str, Any]] = None
                             ) -> None:
        """Capture one real source-construction boundary, once, scalar-only."""
        if phase not in SOURCE_PHASES:
            return
        key = str(record_id)
        with self._lock:
            record = self._active.get(key)
            if not record:
                return
            source = record["sourceConstruction"]
            row = source["phases"][phase]
            already_captured = row.get("status") == "CAPTURED"
        collected = None
        if not already_captured:
            collected = copy.deepcopy(sample) if isinstance(sample, Mapping) \
                else memory_snapshot(logical)
        with self._lock:
            record = self._active.get(key)
            if not record:
                return
            source = record["sourceConstruction"]
            row = source["phases"][phase]
            if row.get("status") != "CAPTURED":
                prior_sample: Mapping[str, Any] = {}
                if source["phaseOrder"]:
                    prior = source["phases"][source["phaseOrder"][-1]]
                    prior_sample = prior.get("sample") or {}
                row.update({
                    "status": "CAPTURED",
                    "capturedAt": (collected or {}).get("capturedAt") or _now(),
                    "sample": collected,
                    "metadata": {},
                    "deltaFromPrevious": (
                        _metric_deltas(prior_sample, collected or {})
                        if prior_sample else
                        {name: NOT_APPLICABLE for name in _SOURCE_DELTA_PATHS}),
                })
                source["phaseOrder"].append(phase)
            if isinstance(metadata, Mapping):
                for name, value in metadata.items():
                    row["metadata"][str(name)[:80]] = _sanitize_scalar(value)

    def _capture_projection_phase(
            self, record_id: str, container_name: str, allowed: Iterable[str],
            phase: str, *, sample: Optional[Mapping[str, Any]] = None,
            logical: Optional[Mapping[str, Any]] = None,
            metadata: Optional[Mapping[str, Any]] = None) -> None:
        if phase not in allowed:
            return
        key = str(record_id)
        with self._lock:
            record = self._active.get(key)
            if not record:
                return
            container = record[container_name]
            already = container["phases"][phase].get("status") == "CAPTURED"
        collected = None
        if not already:
            raw = (copy.deepcopy(sample) if isinstance(sample, Mapping)
                   else memory_snapshot(logical))
            collected = _phase_projection(raw)
        with self._lock:
            record = self._active.get(key)
            if not record:
                return
            container = record[container_name]
            row = container["phases"][phase]
            if row.get("status") != "CAPTURED":
                prior = {}
                if container["phaseOrder"]:
                    prior = container["phases"][
                        container["phaseOrder"][-1]].get(
                            "sampleProjection") or {}
                elif container_name == "missionPathAttribution":
                    prior = container.get("baselineProjection") or {}
                row.update({
                    "status": "CAPTURED",
                    "capturedAt": (collected or {}).get("capturedAt") or _now(),
                    "sampleProjection": collected,
                    "metadata": {},
                    "deltaFromPrevious": (
                        _projection_deltas(prior, collected or {})
                        if prior else
                        {name: NOT_APPLICABLE for name in _SOURCE_DELTA_PATHS}),
                })
                container["phaseOrder"].append(phase)
            if isinstance(metadata, Mapping):
                for name, value in metadata.items():
                    row["metadata"][str(name)[:80]] = _sanitize_scalar(value)

    def capture_prelude_phase(self, record_id: str, phase: str, **kwargs) -> None:
        self._capture_projection_phase(
            record_id, "preludeAttribution", PRELUDE_PHASES, phase, **kwargs)

    def capture_mission_path_phase(
            self, record_id: str, phase: str, **kwargs) -> None:
        self._capture_projection_phase(
            record_id, "missionPathAttribution", MISSION_PATH_PHASES,
            phase, **kwargs)

    def mark_not_applicable(self, record_id: str,
                            phases: Iterable[str], *, reason: str) -> None:
        with self._lock:
            record = self._active.get(str(record_id))
            if not record:
                return
            for phase in phases:
                if phase in PHASES:
                    container = record
                    sample_field = "sample"
                elif phase in PRELUDE_PHASES:
                    container = record["preludeAttribution"]
                    sample_field = "sampleProjection"
                elif phase in MISSION_PATH_PHASES:
                    container = record["missionPathAttribution"]
                    sample_field = "sampleProjection"
                elif phase in SOURCE_PHASES:
                    container = record["sourceConstruction"]
                    sample_field = "sample"
                else:
                    continue
                row = container["phases"][phase]
                if row.get("status") != UNKNOWN:
                    continue
                row.update({"status": NOT_APPLICABLE, "capturedAt": _now(),
                            sample_field: None,
                            "metadata": {"reason": str(reason)[:120]}})
                if "deltaFromPrevious" in row:
                    row["deltaFromPrevious"] = {
                        name: NOT_APPLICABLE for name in _SOURCE_DELTA_PATHS}
                container["phaseOrder"].append(phase)

    def complete(self, record_id: str) -> Optional[Dict[str, Any]]:
        key = str(record_id)
        with self._lock:
            record = self._active.pop(key, None)
            if not record:
                return None
            start = _rss(record, "T0")
            end = _rss(record, "T11")
            legacy_pre = _rss(record, "T2")
            legacy_post = _rss(record, "T4")
            v2_pre = _rss(record, "T6")
            v2_post = _rss(record, "T10")
            previous_end = record.get("previousMissionEndRSS", UNKNOWN)
            record["differentials"] = {
                "missionStartRSS": start,
                "missionEndRSS": end,
                "missionDeltaRSS": _safe_delta(start, end),
                "legacyPreRSS": legacy_pre,
                "legacyPostRSS": legacy_post,
                "legacyDeltaRSS": _safe_delta(legacy_pre, legacy_post),
                "V2PreRSS": v2_pre,
                "V2PostRSS": v2_post,
                "V2DeltaRSS": _safe_delta(v2_pre, v2_post),
                "previousMissionEndRSS": previous_end,
                "currentMissionStartRSS": start,
                "interMissionDeltaRSS": _safe_delta(previous_end, start),
            }
            record["completedAt"] = _now()
            if len(self._history) == self._maximum_records:
                self._dropped_count += 1
            self._history.append(copy.deepcopy(record))
            self._completed_count += 1
            self._last_end_rss = end
            return copy.deepcopy(record)

    def view(self) -> Dict[str, Any]:
        with self._lock:
            history = copy.deepcopy(list(self._history))
            active = [
                {"recordId": key,
                 "missionWindowId": value.get("metadata", {}).get(
                     "missionWindowId"),
                 "phaseOrder": list(value.get("phaseOrder") or []),
                 "sourcePhaseOrder": list(
                     (value.get("sourceConstruction") or {}).get(
                         "phaseOrder") or []),
                 "missionPathPhaseOrder": list(
                     (value.get("missionPathAttribution") or {}).get(
                         "phaseOrder") or [])}
                for key, value in self._active.items()
            ]
            encoded_bytes = len(json.dumps(
                history, separators=(",", ":"), sort_keys=True).encode("utf-8"))
            return {
                "schemaVersion": SCHEMA_VERSION,
                "historyLimit": self._maximum_records,
                "historyCount": len(history),
                "completedCount": self._completed_count,
                "droppedCount": self._dropped_count,
                "activeCount": len(active),
                "active": active,
                "historySerializedBytes": encoded_bytes,
                "records": history,
            }


class OperationAttributionRecorder:
    """Bounded scalar operation, concurrency and inter-mission attribution."""

    def __init__(self, maximum_records: int = DEFAULT_OPERATION_LIMIT, *,
                 threshold_bytes: int = DEFAULT_OPERATION_THRESHOLD_BYTES,
                 heavy_hitter_limit: int = DEFAULT_HEAVY_HITTER_LIMIT,
                 known_operation_limit: int = DEFAULT_KNOWN_OPERATION_LIMIT,
                 intermission_limit: int = DEFAULT_INTERMISSION_LIMIT,
                 active_operation_limit: int = DEFAULT_ACTIVE_OPERATION_LIMIT):
        limit = max(1, min(int(maximum_records), MAXIMUM_OPERATION_LIMIT))
        self._maximum_records = limit
        self._threshold_bytes = max(0, int(threshold_bytes))
        self._heavy_hitter_limit = max(1, min(
            int(heavy_hitter_limit), MAXIMUM_HEAVY_HITTER_LIMIT))
        self._known_operation_limit = max(1, min(
            int(known_operation_limit), 64))
        self._intermission_limit = max(1, min(int(intermission_limit), 32))
        self._active_operation_limit = max(1, min(
            int(active_operation_limit), MAXIMUM_ACTIVE_OPERATION_LIMIT))
        self._history = deque(maxlen=limit)
        self._intermission_history = deque(maxlen=self._intermission_limit)
        self._lock = threading.RLock()
        self._observed_count = 0
        self._qualified_count = 0
        self._dropped_count = 0
        self._known_rejected_count = 0
        self._known_operations: Dict[str, Dict[str, Any]] = {}
        self._heavy_hitters = {
            "cumulativePositiveArenaBytes": _BoundedHeavyHitters(
                self._heavy_hitter_limit, mode="cumulative",
                metric="arenaBytes"),
            "maximumSingleArenaDeltaBytes": _BoundedHeavyHitters(
                self._heavy_hitter_limit, mode="maximum",
                metric="arenaBytes"),
            "cumulativePositiveRssBytes": _BoundedHeavyHitters(
                self._heavy_hitter_limit, mode="cumulative",
                metric="rssBytes"),
        }
        self._active_operations: Dict[int, Dict[str, Any]] = {}
        self._overflow_active_count = 0
        self._active_tracking_overflow_count = 0
        self._next_operation_id = 0
        self._overlap_epoch = 0
        self._maximum_active_count = 0
        self._intermission_sequence = 0
        self._open_intermission: Optional[Dict[str, Any]] = None
        self._intermission_dropped_count = 0

    @property
    def history_count(self) -> int:
        with self._lock:
            return len(self._history)

    def reset(self) -> None:
        with self._lock:
            self._history.clear()
            self._intermission_history.clear()
            self._observed_count = 0
            self._qualified_count = 0
            self._dropped_count = 0
            self._known_rejected_count = 0
            self._known_operations.clear()
            for sketch in self._heavy_hitters.values():
                sketch.reset()
            self._active_operations.clear()
            self._overflow_active_count = 0
            self._active_tracking_overflow_count = 0
            self._next_operation_id = 0
            self._overlap_epoch = 0
            self._maximum_active_count = 0
            self._intermission_sequence = 0
            self._open_intermission = None
            self._intermission_dropped_count = 0

    def begin(self, *, kind: str, name: str, known: bool = False,
              metadata: Optional[Mapping[str, Any]] = None,
              sample: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
        clean = _operation_metadata(metadata)
        operation_type = kind if kind in _OPERATION_KINDS else "internal"
        operation_name = normalize_operation_name(kind, name)
        started_thread_id = threading.get_ident()
        registration = "REGISTERED"
        with self._lock:
            total_before = (len(self._active_operations) +
                            self._overflow_active_count)
            if total_before:
                self._overlap_epoch += 1
            self._next_operation_id += 1
            operation_id = self._next_operation_id
            interval_sequence = (
                self._open_intermission.get("sequence")
                if self._open_intermission else None)
            if len(self._active_operations) >= self._active_operation_limit:
                registration = "REJECTED_LIMIT"
                self._overflow_active_count += 1
                self._active_tracking_overflow_count += 1
            else:
                self._active_operations[operation_id] = {
                    "intervalSequence": interval_sequence,
                    "startedThreadId": started_thread_id,
                }
            active_count = total_before + 1
            self._maximum_active_count = max(
                self._maximum_active_count, active_count)
            overlap_epoch = self._overlap_epoch
        try:
            start_snapshot = (
                copy.deepcopy(sample) if isinstance(sample, Mapping)
                else operation_snapshot())
            start_projection = _metric_projection(start_snapshot)
        except Exception:
            with self._lock:
                if registration == "REGISTERED":
                    self._active_operations.pop(operation_id, None)
                else:
                    self._overflow_active_count = max(
                        0, self._overflow_active_count - 1)
            raise
        return {
            "schemaVersion": OPERATION_SCHEMA_VERSION,
            "operationId": operation_id,
            "operationType": operation_type,
            "operationName": operation_name,
            "knownOperation": bool(known),
            "startedAt": _now(),
            "startedMonotonic": time.monotonic(),
            "metadata": clean,
            "start": start_projection,
            "activeOperationCountStart": active_count,
            "overlapEpochStart": overlap_epoch,
            "intermissionSequenceStart": interval_sequence,
            "concurrencyRegistration": registration,
            "_attributionStartedThreadId": started_thread_id,
        }

    @staticmethod
    def _update_exact_aggregate(entry: Dict[str, Any],
                                row: Mapping[str, Any]) -> None:
        deltas = row.get("deltas") or {}
        entry["eventCount"] = int(entry.get("eventCount") or 0) + 1
        for metric, target in (
                ("rssBytes", "cumulativePositiveRssBytes"),
                ("arenaBytes", "cumulativePositiveArenaBytes"),
                ("freeBytes", "cumulativePositiveFreeBytes")):
            entry[target] = int(entry.get(target) or 0) + _positive(
                deltas.get(metric))
        allocated = deltas.get("allocatedBytes")
        if isinstance(allocated, int):
            entry["signedAllocatedBytes"] = int(
                entry.get("signedAllocatedBytes") or 0) + allocated
        for metric, target in (
                ("rssBytes", "maxRssDeltaBytes"),
                ("arenaBytes", "maxArenaDeltaBytes"),
                ("freeBytes", "maxFreeBytesDelta")):
            value = deltas.get(metric)
            if isinstance(value, int) and (
                    not isinstance(entry.get(target), int) or
                    value > entry[target]):
                entry[target] = value
        entry["maxDurationMs"] = max(
            float(entry.get("maxDurationMs") or 0),
            float(row.get("durationMs") or 0))
        classification = str(row.get("concurrencyClass") or "UNKNOWN")
        counts = entry.setdefault("concurrencyCounts", {
            "EXCLUSIVE": 0, "OVERLAPPED": 0, "UNKNOWN": 0})
        counts[classification if classification in counts else "UNKNOWN"] += 1
        thread_class = str(row.get("completionThreadClass") or "UNKNOWN")
        thread_counts = entry.setdefault("completionThreadCounts", {
            "SAME_THREAD": 0, "CROSS_THREAD": 0, "UNKNOWN": 0})
        thread_counts[
            thread_class if thread_class in thread_counts else "UNKNOWN"] += 1
        entry["lastCompletedAt"] = row.get("completedAt")

    def _observe_intermission(self, token: Mapping[str, Any],
                              row: Mapping[str, Any]) -> None:
        interval = self._open_intermission
        if not interval:
            return
        kind = str(row.get("operationType") or "internal")
        if kind not in _OPERATION_KINDS:
            kind = "internal"
        thread_class = str(row.get("completionThreadClass") or "UNKNOWN")
        if thread_class not in interval["completionThreadCounts"]:
            thread_class = "UNKNOWN"
        interval["observedCompletionCount"] += 1
        if token.get("intermissionSequenceStart") != interval["sequence"]:
            interval["boundarySpanningCompletedCount"] += 1
            interval["boundarySpanningKindCounts"][kind] += 1
            interval["boundarySpanningCompletionThreadCounts"][
                thread_class] += 1
            return
        interval["completedOperationCount"] += 1
        interval["kindCounts"][kind] += 1
        classification = str(row.get("concurrencyClass") or "UNKNOWN")
        if classification not in interval["concurrencyCounts"]:
            classification = "UNKNOWN"
        interval["concurrencyCounts"][classification] += 1
        interval["completionThreadCounts"][thread_class] += 1
        deltas = row.get("deltas") or {}
        kind_row = interval["kindAggregates"][kind]
        kind_row["count"] += 1
        kind_row["concurrencyCounts"][classification] += 1
        kind_row["completionThreadCounts"][thread_class] += 1
        for metric, stem in (
                ("rssBytes", "RssBytes"),
                ("arenaBytes", "ArenaBytes"),
                ("freeBytes", "FreeBytes")):
            value = deltas.get(metric)
            if isinstance(value, int):
                kind_row[f"signed{stem}"] += value
                kind_row[f"positive{stem}"] += _positive(value)
                maximum = f"max{stem[:-5]}DeltaBytes"
                current = kind_row[maximum]
                if not isinstance(current, int) or value > current:
                    kind_row[maximum] = value
        allocated = deltas.get("allocatedBytes")
        if isinstance(allocated, int) and not isinstance(allocated, bool):
            kind_row["signedAllocatedBytes"] += allocated
        kind_row["maxDurationMs"] = max(
            float(kind_row["maxDurationMs"]),
            float(row.get("durationMs") or 0))
        if classification == "EXCLUSIVE":
            for metric, target in (
                    ("rssBytes", "exclusiveSignedRssBytes"),
                    ("arenaBytes", "exclusiveSignedArenaBytes"),
                    ("freeBytes", "exclusiveSignedFreeBytes")):
                value = deltas.get(metric)
                if isinstance(value, int):
                    interval[target] += value
        elif classification == "OVERLAPPED":
            interval["overlappedPositiveRssBytes"] += _positive(
                deltas.get("rssBytes"))
            interval["overlappedPositiveArenaBytes"] += _positive(
                deltas.get("arenaBytes"))
            interval["overlappedPositiveFreeBytes"] += _positive(
                deltas.get("freeBytes"))
        else:
            interval["unknownPositiveRssBytes"] += _positive(
                deltas.get("rssBytes"))
            interval["unknownPositiveArenaBytes"] += _positive(
                deltas.get("arenaBytes"))
            interval["unknownPositiveFreeBytes"] += _positive(
                deltas.get("freeBytes"))
        for sketch in interval["topOperations"].values():
            sketch.observe(row)

    def complete(self, token: Optional[Mapping[str, Any]], *,
                 metadata: Optional[Mapping[str, Any]] = None,
                 sample: Optional[Mapping[str, Any]] = None
                 ) -> Optional[Dict[str, Any]]:
        if not isinstance(token, Mapping):
            return None
        completion_thread_id = threading.get_ident()
        with self._lock:
            operation_id = token.get("operationId")
            registration = token.get("concurrencyRegistration")
            already_completed = bool(token.get("_attributionCompleted"))
            state = (self._active_operations.get(operation_id)
                     if isinstance(operation_id, int) else None)
            started_thread_id = token.get("_attributionStartedThreadId")
            valid_completion = not already_completed and (
                state is not None or registration == "REJECTED_LIMIT")
            if not valid_completion or not isinstance(started_thread_id, int) \
                    or isinstance(started_thread_id, bool):
                completion_thread_class = "UNKNOWN"
            elif started_thread_id == completion_thread_id:
                completion_thread_class = "SAME_THREAD"
            else:
                completion_thread_class = "CROSS_THREAD"
            if valid_completion and isinstance(token, dict):
                token["_attributionCompleted"] = True
        try:
            end_snapshot = (
                copy.deepcopy(sample) if isinstance(sample, Mapping)
                else operation_snapshot())
            start = dict(token.get("start") or {})
            end = _metric_projection(end_snapshot)
            deltas = {name: _safe_delta(start.get(name), end.get(name))
                      for name in _SOURCE_DELTA_PATHS}
            duration_ms = round(max(
                0.0, (time.monotonic() -
                      float(token.get("startedMonotonic") or 0)) * 1000), 3)
            clean = dict(token.get("metadata") or {})
            clean.update(_operation_metadata(metadata))
            magnitude = max((
                abs(value) for value in deltas.values()
                if isinstance(value, int) and not isinstance(value, bool)),
                default=0)
            qualified = bool(token.get("knownOperation")) or \
                magnitude >= self._threshold_bytes
        except Exception:
            with self._lock:
                if valid_completion:
                    if state is not None:
                        self._active_operations.pop(operation_id, None)
                    elif registration == "REJECTED_LIMIT":
                        self._overflow_active_count = max(
                            0, self._overflow_active_count - 1)
            raise
        with self._lock:
            state_at_end = (self._active_operations.get(operation_id)
                            if isinstance(operation_id, int) else None)
            active_end = (len(self._active_operations) +
                          self._overflow_active_count)
            if already_completed or registration != "REGISTERED" or \
                    state_at_end is None:
                concurrency_class = "UNKNOWN"
            elif int(token.get("activeOperationCountStart") or 0) > 1 or \
                    active_end > 1 or \
                    token.get("overlapEpochStart") != self._overlap_epoch:
                concurrency_class = "OVERLAPPED"
            else:
                concurrency_class = "EXCLUSIVE"
            if valid_completion:
                if state_at_end is not None:
                    self._active_operations.pop(operation_id, None)
                elif registration == "REJECTED_LIMIT":
                    self._overflow_active_count = max(
                        0, self._overflow_active_count - 1)
            self._observed_count += 1
            row = {
                "schemaVersion": OPERATION_SCHEMA_VERSION,
                "operationType": token.get("operationType"),
                "operationName": token.get("operationName"),
                "knownOperation": bool(token.get("knownOperation")),
                "startedAt": token.get("startedAt"),
                "completedAt": _now(),
                "durationMs": duration_ms,
                "start": start,
                "end": end,
                "deltas": deltas,
                "metadata": clean,
                "activeOperationCountStart": token.get(
                    "activeOperationCountStart", UNKNOWN),
                "activeOperationCountEnd": active_end,
                "concurrencyClass": concurrency_class,
                "concurrencyScope": "instrumented_operations_only",
                "completionThreadClass": completion_thread_class,
                "completionThreadScope": "python_thread_identity",
                "sameThreadCompletion": (
                    completion_thread_class == "SAME_THREAD"
                    if completion_thread_class != "UNKNOWN" else UNKNOWN),
                "crossThreadCompletion": (
                    completion_thread_class == "CROSS_THREAD"
                    if completion_thread_class != "UNKNOWN" else UNKNOWN),
            }
            if bool(token.get("knownOperation")):
                operation_name = str(row.get("operationName") or "")[:160]
                aggregate = self._known_operations.get(operation_name)
                if aggregate is None:
                    if len(self._known_operations) < self._known_operation_limit:
                        aggregate = {
                            "operationType": row.get("operationType"),
                            "operationName": operation_name,
                            "knownOperation": True,
                        }
                        self._known_operations[operation_name] = aggregate
                    else:
                        self._known_rejected_count += 1
                if aggregate is not None:
                    self._update_exact_aggregate(aggregate, row)
            for sketch in self._heavy_hitters.values():
                sketch.observe(row)
            self._observe_intermission(token, row)
            if not qualified:
                return None
            if len(self._history) == self._maximum_records:
                self._dropped_count += 1
            self._history.append(row)
            self._qualified_count += 1
            return copy.deepcopy(row)

    def open_intermission(self, *, record_id: str,
                          mission_window_id: Optional[str],
                          sample: Mapping[str, Any]) -> None:
        projection = _phase_projection(sample)
        with self._lock:
            self._intermission_sequence += 1
            self._open_intermission = {
                "sequence": self._intermission_sequence,
                "previousRecordId": str(record_id)[:160],
                "previousMissionWindowId": _sanitize_scalar(
                    mission_window_id),
                "startedAt": projection["capturedAt"],
                "startProjection": projection,
                "inFlightAtOpen": (len(self._active_operations) +
                                   self._overflow_active_count),
                "trackedInFlightAtOpen": len(self._active_operations),
                "untrackedInFlightAtOpen": self._overflow_active_count,
                "observedCompletionCount": 0,
                "completedOperationCount": 0,
                "boundarySpanningCompletedCount": 0,
                "boundarySpanningKindCounts": {
                    kind: 0 for kind in sorted(_OPERATION_KINDS)},
                "boundarySpanningCompletionThreadCounts": {
                    "SAME_THREAD": 0, "CROSS_THREAD": 0, "UNKNOWN": 0},
                "kindCounts": {kind: 0 for kind in sorted(_OPERATION_KINDS)},
                "kindAggregates": {
                    kind: {
                        "count": 0,
                        "signedRssBytes": 0, "positiveRssBytes": 0,
                        "signedArenaBytes": 0, "positiveArenaBytes": 0,
                        "signedFreeBytes": 0, "positiveFreeBytes": 0,
                        "signedAllocatedBytes": 0,
                        "maxRssDeltaBytes": UNKNOWN,
                        "maxArenaDeltaBytes": UNKNOWN,
                        "maxFreeDeltaBytes": UNKNOWN,
                        "maxDurationMs": 0,
                        "concurrencyCounts": {
                            "EXCLUSIVE": 0, "OVERLAPPED": 0, "UNKNOWN": 0},
                        "completionThreadCounts": {
                            "SAME_THREAD": 0, "CROSS_THREAD": 0,
                            "UNKNOWN": 0},
                    }
                    for kind in sorted(_OPERATION_KINDS)
                },
                "concurrencyCounts": {
                    "EXCLUSIVE": 0, "OVERLAPPED": 0, "UNKNOWN": 0},
                "completionThreadCounts": {
                    "SAME_THREAD": 0, "CROSS_THREAD": 0, "UNKNOWN": 0},
                "exclusiveSignedRssBytes": 0,
                "exclusiveSignedArenaBytes": 0,
                "exclusiveSignedFreeBytes": 0,
                "overlappedPositiveRssBytes": 0,
                "overlappedPositiveArenaBytes": 0,
                "overlappedPositiveFreeBytes": 0,
                "unknownPositiveRssBytes": 0,
                "unknownPositiveArenaBytes": 0,
                "unknownPositiveFreeBytes": 0,
                "topOperations": {
                    "cumulativePositiveArenaBytes": _BoundedHeavyHitters(
                        4, mode="cumulative", metric="arenaBytes"),
                    "maximumSingleArenaDeltaBytes": _BoundedHeavyHitters(
                        4, mode="maximum", metric="arenaBytes"),
                    "cumulativePositiveRssBytes": _BoundedHeavyHitters(
                        4, mode="cumulative", metric="rssBytes"),
                },
            }

    def close_intermission(self, *, next_record_id: str,
                           next_mission_window_id: Optional[str],
                           sample: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
        end_projection = _phase_projection(sample)
        with self._lock:
            interval = self._open_intermission
            if not interval:
                return None
            self._open_intermission = None
            totals = _projection_deltas(
                interval["startProjection"], end_projection)
            started_during = sum(
                1 for state in self._active_operations.values()
                if state.get("intervalSequence") == interval["sequence"])
            started_before = max(
                0, len(self._active_operations) - started_during)
            untracked = self._overflow_active_count
            row = {
                key: copy.deepcopy(value)
                for key, value in interval.items() if key != "topOperations"
            }
            row.update({
                "schemaVersion": OPERATION_SCHEMA_VERSION,
                "nextRecordId": str(next_record_id)[:160],
                "nextMissionWindowId": _sanitize_scalar(
                    next_mission_window_id),
                "completedAt": end_projection["capturedAt"],
                "endProjection": end_projection,
                "boundaryDeltas": totals,
                "operationCount": interval["observedCompletionCount"],
                "inFlightAtClose": (len(self._active_operations) + untracked),
                "startedBeforeIntervalStillActiveAtClose": started_before,
                "startedDuringIntervalStillActiveAtClose": started_during,
                "untrackedStillActiveAtClose": untracked,
                "untrackedBoundaryClassification": (
                    "UNKNOWN" if untracked else NOT_APPLICABLE),
                "boundarySpanningInFlightCount": (
                    started_before + started_during + untracked),
                "boundarySpanningCount": (
                    interval["boundarySpanningCompletedCount"] +
                    started_before + started_during + untracked),
                "unexplainedResidual": {
                    "rssBytes": _safe_delta(
                        interval["exclusiveSignedRssBytes"],
                        totals.get("rssBytes")),
                    "arenaBytes": _safe_delta(
                        interval["exclusiveSignedArenaBytes"],
                        totals.get("arenaBytes")),
                    "freeBytes": _safe_delta(
                        interval["exclusiveSignedFreeBytes"],
                        totals.get("freeBytes")),
                },
                "topOperations": {
                    name: sketch.view()
                    for name, sketch in interval["topOperations"].items()
                },
            })
            if len(self._intermission_history) == self._intermission_limit:
                self._intermission_dropped_count += 1
            self._intermission_history.append(row)
            return copy.deepcopy(row)

    def view(self) -> Dict[str, Any]:
        with self._lock:
            history = copy.deepcopy(list(self._history))
            known = sorted(
                copy.deepcopy(list(self._known_operations.values())),
                key=lambda row: int(row.get(
                    "cumulativePositiveArenaBytes") or 0), reverse=True)
            intermission = copy.deepcopy(list(self._intermission_history))
            payload = {
                "schemaVersion": OPERATION_SCHEMA_VERSION,
                "historyLimit": self._maximum_records,
                "thresholdBytes": self._threshold_bytes,
                "historyCount": len(history),
                "observedCount": self._observed_count,
                "qualifiedCount": self._qualified_count,
                "droppedCount": self._dropped_count,
                "activeCount": (len(self._active_operations) +
                                self._overflow_active_count),
                "activeTrackedCount": len(self._active_operations),
                "activeTrackingLimit": self._active_operation_limit,
                "activeTrackingOverflowActiveCount": self._overflow_active_count,
                "activeTrackingOverflowCount": self._active_tracking_overflow_count,
                "maximumActiveCount": self._maximum_active_count,
                "concurrencyScope": "instrumented_operations_only",
                "knownOperationLimit": self._known_operation_limit,
                "knownOperationCount": len(known),
                "knownOperationRejectedCount": self._known_rejected_count,
                "knownOperations": known,
                "heavyHitterLimit": self._heavy_hitter_limit,
                "heavyHitters": {
                    name: sketch.view()
                    for name, sketch in self._heavy_hitters.items()
                },
                "intermissionHistory": {
                    "historyLimit": self._intermission_limit,
                    "historyCount": len(intermission),
                    "droppedCount": self._intermission_dropped_count,
                    "summaries": intermission,
                },
                "records": history,
            }
            payload["serializedBytes"] = len(json.dumps(
                payload, separators=(",", ":"), sort_keys=True).encode(
                    "utf-8"))
            payload["historySerializedBytes"] = len(json.dumps(
                history, separators=(",", ":"), sort_keys=True).encode(
                    "utf-8"))
            return payload
