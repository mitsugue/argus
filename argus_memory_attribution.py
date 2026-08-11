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


SCHEMA_VERSION = "argus-memory-attribution-v2"
UNKNOWN = "UNKNOWN"
NOT_APPLICABLE = "NOT_APPLICABLE"
DEFAULT_HISTORY_LIMIT = 16
MAXIMUM_HISTORY_LIMIT = 32
DEFAULT_OPERATION_LIMIT = 32
MAXIMUM_OPERATION_LIMIT = 64
DEFAULT_OPERATION_THRESHOLD_BYTES = 1024 * 1024

PHASES = (
    "T0", "T1", "T2", "T3", "T4", "T5", "T6",
    "T7", "T8", "T9", "T10", "T11", "T12",
)

SOURCE_PHASES = (
    "S0", "S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8",
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
              logical: Optional[Mapping[str, Any]] = None) -> str:
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
                "previousMissionEndRSS": self._last_end_rss,
                "differentials": {},
                "startedAt": _now(),
                "completedAt": None,
            }
            self._active[key] = record
        self.capture(key, "T0", sample=initial_sample, logical=logical)
        self.capture_source_phase(
            key, "S0", sample=initial_sample, logical=logical,
            metadata={"operation": "mission_start"})
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

    def mark_not_applicable(self, record_id: str,
                            phases: Iterable[str], *, reason: str) -> None:
        with self._lock:
            record = self._active.get(str(record_id))
            if not record:
                return
            for phase in phases:
                if phase not in PHASES:
                    continue
                row = record["phases"][phase]
                if row.get("status") == "CAPTURED":
                    continue
                row.update({"status": NOT_APPLICABLE, "capturedAt": _now(),
                            "sample": None,
                            "metadata": {"reason": str(reason)[:120]}})
                record["phaseOrder"].append(phase)

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
    """Bounded request/background recorder retaining scalar metrics only."""

    def __init__(self, maximum_records: int = DEFAULT_OPERATION_LIMIT, *,
                 threshold_bytes: int = DEFAULT_OPERATION_THRESHOLD_BYTES):
        limit = max(1, min(int(maximum_records), MAXIMUM_OPERATION_LIMIT))
        self._maximum_records = limit
        self._threshold_bytes = max(0, int(threshold_bytes))
        self._history = deque(maxlen=limit)
        self._lock = threading.RLock()
        self._observed_count = 0
        self._qualified_count = 0
        self._dropped_count = 0

    @property
    def history_count(self) -> int:
        with self._lock:
            return len(self._history)

    def reset(self) -> None:
        with self._lock:
            self._history.clear()
            self._observed_count = 0
            self._qualified_count = 0
            self._dropped_count = 0

    def begin(self, *, kind: str, name: str, known: bool = False,
              metadata: Optional[Mapping[str, Any]] = None,
              sample: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
        clean = _operation_metadata(metadata)
        return {
            "schemaVersion": "argus-operation-memory-v1",
            "operationType": kind if kind in _OPERATION_KINDS else "internal",
            "operationName": normalize_operation_name(kind, name),
            "knownOperation": bool(known),
            "startedAt": _now(),
            "startedMonotonic": time.monotonic(),
            "metadata": clean,
            "start": _metric_projection(
                copy.deepcopy(sample) if isinstance(sample, Mapping)
                else operation_snapshot()),
        }

    def complete(self, token: Optional[Mapping[str, Any]], *,
                 metadata: Optional[Mapping[str, Any]] = None,
                 sample: Optional[Mapping[str, Any]] = None
                 ) -> Optional[Dict[str, Any]]:
        if not isinstance(token, Mapping):
            return None
        end_snapshot = (copy.deepcopy(sample) if isinstance(sample, Mapping)
                        else operation_snapshot())
        start = dict(token.get("start") or {})
        end = _metric_projection(end_snapshot)
        deltas = {name: _safe_delta(start.get(name), end.get(name))
                  for name in _SOURCE_DELTA_PATHS}
        duration_ms = round(max(0.0, (time.monotonic() -
                                      float(token.get("startedMonotonic") or 0)))
                            * 1000, 3)
        clean = dict(token.get("metadata") or {})
        clean.update(_operation_metadata(metadata))
        magnitude = max((abs(value) for value in deltas.values()
                         if isinstance(value, int) and not isinstance(value, bool)),
                        default=0)
        qualified = bool(token.get("knownOperation")) or \
            magnitude >= self._threshold_bytes
        with self._lock:
            self._observed_count += 1
            if not qualified:
                return None
            row = {
                "schemaVersion": "argus-operation-memory-v1",
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
            }
            if len(self._history) == self._maximum_records:
                self._dropped_count += 1
            self._history.append(row)
            self._qualified_count += 1
            return copy.deepcopy(row)

    def view(self) -> Dict[str, Any]:
        with self._lock:
            history = copy.deepcopy(list(self._history))
            encoded = len(json.dumps(
                history, separators=(",", ":"), sort_keys=True).encode("utf-8"))
            return {
                "schemaVersion": "argus-operation-memory-v1",
                "historyLimit": self._maximum_records,
                "thresholdBytes": self._threshold_bytes,
                "historyCount": len(history),
                "observedCount": self._observed_count,
                "qualifiedCount": self._qualified_count,
                "droppedCount": self._dropped_count,
                "historySerializedBytes": encoded,
                "records": history,
            }
