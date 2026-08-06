"""Bounded transactional checkpoint V2 with an atomic manifest pointer.

Stage 1 dual-writes immutable SQLite generations while the legacy checkpoint
remains restore authority. Values are recursively partitioned into <=8 MiB
canonical JSON rows, so neither write nor restore needs a checkpoint-sized
serialized buffer or a second complete object graph.
"""
from __future__ import annotations

import contextlib
import ctypes
import datetime as dt
import fcntl
import gc
import hashlib
import json
import os
import pathlib
import resource
import shutil
import sqlite3
import threading
import time
import uuid
from typing import Any, Dict, Iterable, Mapping, MutableMapping, Optional, Tuple

import argus_persistent_storage as legacy


UTC = dt.timezone.utc
SCHEMA = "argus-checkpoint-v2"
ROW_SCHEMA = "argus-checkpoint-v2-row-v1"
MANIFEST_NAME = "checkpoint-v2-manifest.json"
DATABASE_NAME = "checkpoint.sqlite3"
MAXIMUM_TOTAL_BYTES = 256 * 1024 * 1024
MAXIMUM_ROW_BYTES = 8 * 1024 * 1024
MAXIMUM_GENERATIONS = 4
MINIMUM_FREE_SPACE_RESERVE = 1024 * 1024 * 1024
MAXIMUM_RETAINED_GENERATION_BYTES = MAXIMUM_GENERATIONS * MAXIMUM_TOTAL_BYTES
MAXIMUM_IN_PROGRESS_GENERATION_BYTES = MAXIMUM_TOTAL_BYTES
MAXIMUM_METADATA_BYTES = 1024 * 1024
ALLOCATOR_RECLAIM_MINIMUM_SOURCE_BYTES = 32 * 1024 * 1024
MAXIMUM_V2_OWNED_BYTES = (
    MAXIMUM_RETAINED_GENERATION_BYTES +
    MAXIMUM_IN_PROGRESS_GENERATION_BYTES + MAXIMUM_METADATA_BYTES)
# These are rebuildable presentation caches, retained as immutable archive
# segments but not required to construct authoritative runtime state at boot.
ARCHIVE_SECTIONS = frozenset({"verifiedViewSnapshots", "assetChartReports"})

SECTION_LIMITS = {
    "marketLedger": 120 * 1024 * 1024,
    "verifiedViewSnapshots": 40 * 1024 * 1024,
    "assetChartReports": 24 * 1024 * 1024,
    "chartIntelligence": 16 * 1024 * 1024,
    "marketReplay": 12 * 1024 * 1024,
    "todayIntelligence": 8 * 1024 * 1024,
}
DEFAULT_SECTION_LIMIT = 8 * 1024 * 1024
COUNT_LIMITS = {
    "memory": 400, "urlCache": 120, "rpsHistory": 40,
    "baselineRuns": 24, "benchmarkRuns": 20, "soakHistory": 8,
    "missions": 120, "missionWindows": 240, "forecasts": 200,
    "outcomes": 200, "incidents": 20, "opsJournal": 400,
    "opsJournalCompacted": 40,
}
NESTED_COUNT_LIMITS = {
    "marketLedger": {
        "observations": 90_000, "derivedMetrics": 5_000,
        "turningPoints": 25_000, "backtests": 64, "imports": 1_000,
        "rolledBackImports": 1_000,
    },
    "verifiedViewSnapshots": {"current": 24, "history": 48},
    "assetChartReports": {"current": 24, "records": 24},
    "chartIntelligence": {
        "snapshots": 512, "zones": 4_000, "turningPoints": 20_000,
        "reactionAnomalies": 2_000, "relationshipBreaks": 2_000,
        "invalidations": 4_000,
    },
    "todayIntelligence": {
        "snapshots": 1_024, "shortSellingHistory": 3_000,
        "failedRallyOutcomes": 5_000,
    },
    "marketReplay": {"contexts": 32, "contextHistory": 1_024},
    "remoteAck": {"ackedKeys": 800, "outcomeAckedIds": 400},
}


class CheckpointV2Error(RuntimeError):
    def __init__(self, classification: str, **details):
        super().__init__(classification)
        self.classification = classification
        self.details = details


def _process_rss_bytes() -> Optional[int]:
    """Best-effort current RSS without exposing process or host identity."""
    try:
        with open("/proc/self/status", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) * 1024
    except (FileNotFoundError, OSError, ValueError, IndexError):
        pass
    try:
        # macOS reports bytes; Linux reports KiB.
        raw = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        return raw if os.uname().sysname == "Darwin" else raw * 1024
    except (AttributeError, OSError, ValueError):
        return None


def _process_peak_rss_bytes() -> Optional[int]:
    try:
        raw = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        return raw if os.uname().sysname == "Darwin" else raw * 1024
    except (AttributeError, OSError, ValueError):
        return None


def _read_int(paths: Iterable[str]) -> Optional[int]:
    for path in paths:
        try:
            raw = pathlib.Path(path).read_text(encoding="utf-8").strip()
            if raw and raw != "max":
                return int(raw)
        except (FileNotFoundError, OSError, ValueError):
            continue
    return None


def _cgroup_current_bytes() -> Optional[int]:
    return _read_int(("/sys/fs/cgroup/memory.current",
                      "/sys/fs/cgroup/memory/memory.usage_in_bytes"))


def _cgroup_peak_bytes() -> Optional[int]:
    return _read_int(("/sys/fs/cgroup/memory.peak",
                      "/sys/fs/cgroup/memory/memory.max_usage_in_bytes"))


def _release_unused_allocator_memory(source_bytes: int) -> Dict[str, Any]:
    """Return freed checkpoint arenas only after their last owner is gone.

    Production-shaped JSON and SQLite row encoding temporarily allocates more
    than 100 MiB.  CPython releases those objects by reference counting, but
    glibc may keep the now-empty anonymous heap arenas mapped indefinitely.
    This is deliberately scoped to a consumed, generation-sized snapshot; it
    is not a periodic GC or a telemetry reset.
    """
    before = _process_rss_bytes()
    report: Dict[str, Any] = {
        "attempted": False,
        "supported": False,
        "sourceBytes": int(source_bytes or 0),
        "rssBeforeBytes": before,
        "rssAfterBytes": before,
        "rssReleasedBytes": 0,
        "reportedReleasedBytes": None,
    }
    if int(source_bytes or 0) < ALLOCATOR_RECLAIM_MINIMUM_SOURCE_BYTES:
        return report
    report["attempted"] = True
    try:
        allocator = ctypes.CDLL(None)
        system = os.uname().sysname
        if system == "Linux" and hasattr(allocator, "malloc_trim"):
            trim = allocator.malloc_trim
            trim.argtypes = [ctypes.c_size_t]
            trim.restype = ctypes.c_int
            report["supported"] = True
            trim(0)
        elif system == "Darwin" and hasattr(
                allocator, "malloc_zone_pressure_relief"):
            relief = allocator.malloc_zone_pressure_relief
            relief.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
            relief.restype = ctypes.c_size_t
            report["supported"] = True
            report["reportedReleasedBytes"] = int(relief(None, 0))
    except (AttributeError, OSError, TypeError, ValueError):
        # Unsupported allocators keep correctness; the resource gate still
        # observes the unchanged RSS and fails closed when necessary.
        pass
    after = _process_rss_bytes()
    report["rssAfterBytes"] = after
    if before is not None and after is not None:
        report["rssReleasedBytes"] = max(0, before - after)
    return report


class _ResourceSampler:
    """Sample per-generation current memory without resetting cgroup state."""

    def __init__(self) -> None:
        self._stop = threading.Event()
        self.process_peak = _process_rss_bytes()
        self.cgroup_peak = _cgroup_current_bytes()
        self._thread = threading.Thread(
            target=self._run, name="checkpoint-v2-resource-sampler",
            daemon=True)

    def start(self) -> None:
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.wait(0.025):
            rss = _process_rss_bytes()
            cgroup = _cgroup_current_bytes()
            if rss is not None:
                self.process_peak = max(self.process_peak or 0, rss)
            if cgroup is not None:
                self.cgroup_peak = max(self.cgroup_peak or 0, cgroup)

    def finish(self) -> None:
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=0.2)
        rss = _process_rss_bytes()
        cgroup = _cgroup_current_bytes()
        if rss is not None:
            self.process_peak = max(self.process_peak or 0, rss)
        if cgroup is not None:
            self.cgroup_peak = max(self.cgroup_peak or 0, cgroup)


def _legacy_temp_count(checkpoint_path: Optional[str],
                       temp_directory: Optional[str]) -> Optional[int]:
    """Metadata-only count; names and inode details never enter telemetry."""
    if not checkpoint_path:
        return None
    final = os.path.abspath(checkpoint_path)
    directory = os.path.realpath(
        temp_directory or os.path.dirname(final) or ".")
    base = os.path.basename(final)
    count = 0
    try:
        with os.scandir(directory) as entries:
            for entry in entries:
                if entry.is_symlink() or not entry.is_file(
                        follow_symlinks=False):
                    continue
                if entry.name.startswith(base + ".") and (
                        entry.name.endswith(".tmp") or
                        entry.name.endswith(".v1338-tmp") or
                        ".bootstrap-" in entry.name or
                        ".v1338-bootstrap-" in entry.name):
                    count += 1
    except OSError:
        return None
    return count


def _resource_telemetry(*, started: float, rss_before: Optional[int],
                        cgroup_before: Optional[int],
                        cgroup_peak_before: Optional[int],
                        sampler: _ResourceSampler,
                        database_bytes: Optional[int], row_count: int,
                        section_count: int, disk_free_before: Optional[int],
                        disk_free_after: Optional[int], pending_count: int,
                        lock_wait_ms: float, success: bool,
                        legacy_temp_before: Optional[int],
                        legacy_temp_after: Optional[int],
                        allocator_reclaim: Optional[Mapping[str, Any]] = None
                        ) -> Dict[str, Any]:
    sampler.finish()
    rss_after = _process_rss_bytes()
    return {
        "schemaVersion": "argus-checkpoint-v2-generation-resource-v1",
        "success": bool(success),
        "processRssBeforeBytes": rss_before,
        "processPeakRssBytes": sampler.process_peak,
        "processLifetimePeakRssBytes": _process_peak_rss_bytes(),
        "processRssAfterBytes": rss_after,
        "processRssDeltaBytes": (
            rss_after - rss_before
            if rss_after is not None and rss_before is not None else None),
        "cgroupMemoryCurrentBeforeBytes": cgroup_before,
        "cgroupMemoryCurrentAfterBytes": _cgroup_current_bytes(),
        "cgroupMemoryPeakBeforeBytes": cgroup_peak_before,
        "cgroupMemoryPeakBytes": sampler.cgroup_peak,
        "cgroupMemoryLifetimePeakBytes": _cgroup_peak_bytes(),
        "generationBytes": database_bytes,
        "rowCount": int(row_count),
        "sectionCount": int(section_count),
        "durationMs": round((time.monotonic() - started) * 1000, 3),
        "diskFreeBeforeBytes": disk_free_before,
        "diskFreeAfterBytes": disk_free_after,
        "pendingGenerationCount": int(pending_count),
        "writerLockWaitMs": round(lock_wait_ms, 3),
        "legacyTempBaselineCount": legacy_temp_before,
        "legacyTempAfterCount": legacy_temp_after,
        "newLegacyTempCount": (
            max(0, legacy_temp_after - legacy_temp_before)
            if legacy_temp_before is not None and
            legacy_temp_after is not None else None),
        "allocatorReclaim": dict(allocator_reclaim or {}),
    }


def _iso_now() -> str:
    return dt.datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _fsync_directory(path: str) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _stream_stats(value: Any) -> Tuple[int, str]:
    size = 0
    digest = hashlib.sha256()
    for chunk in legacy._canonical_chunks(value):
        size += len(chunk)
        digest.update(chunk)
    return size, digest.hexdigest()


def _file_stats(path: str) -> Tuple[int, str]:
    size = 0
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            digest.update(chunk)
    return size, digest.hexdigest()


def _encode_bounded(value: Any) -> bytes:
    chunks = []
    size = 0
    for chunk in legacy._canonical_chunks(value):
        size += len(chunk)
        if size > MAXIMUM_ROW_BYTES:
            raise CheckpointV2Error(
                "checkpoint_v2_row_too_large", bytes=size,
                maximumBytes=MAXIMUM_ROW_BYTES)
        chunks.append(chunk)
    return b"".join(chunks)


def _partition(value: Any, path=()):
    """Yield container descriptors and bounded leaf/subtree rows."""
    size, _ = _stream_stats(value)
    if size <= MAXIMUM_ROW_BYTES:
        yield "row", path, value
        return
    if isinstance(value, Mapping):
        yield "container", path, {"kind": "dict", "length": len(value)}
        for key, child in value.items():
            if not isinstance(key, str):
                raise CheckpointV2Error("checkpoint_v2_non_string_key")
            yield from _partition(child, path + (key,))
        return
    if isinstance(value, list):
        yield "container", path, {"kind": "list", "length": len(value)}
        for index, child in enumerate(value):
            yield from _partition(child, path + (index,))
        return
    raise CheckpointV2Error(
        "checkpoint_v2_unsplittable_value", bytes=size,
        maximumBytes=MAXIMUM_ROW_BYTES)


def _connect(path: str) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA journal_mode=DELETE")
    connection.execute("PRAGMA synchronous=FULL")
    connection.execute("PRAGMA temp_store=FILE")
    connection.executescript("""
      CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
      CREATE TABLE sections (
        name TEXT PRIMARY KEY, root_kind TEXT NOT NULL, root_length INTEGER,
        source_bytes INTEGER NOT NULL, source_sha256 TEXT NOT NULL,
        row_count INTEGER NOT NULL, container_count INTEGER NOT NULL,
        schema_version TEXT NOT NULL, generation_id TEXT NOT NULL);
      CREATE TABLE containers (
        section TEXT NOT NULL, path TEXT NOT NULL, kind TEXT NOT NULL,
        length INTEGER NOT NULL, generation_id TEXT NOT NULL,
        PRIMARY KEY(section, path));
      CREATE TABLE rows (
        section TEXT NOT NULL, path TEXT NOT NULL, payload BLOB NOT NULL,
        payload_bytes INTEGER NOT NULL, payload_sha256 TEXT NOT NULL,
        schema_version TEXT NOT NULL, generation_id TEXT NOT NULL,
        PRIMARY KEY(section, path));
    """)
    return connection


def _root_descriptor(value: Any):
    if isinstance(value, Mapping):
        return "dict", len(value)
    if isinstance(value, list):
        return "list", len(value)
    return "scalar", None


def _validate_collection_bounds(section: str, value: Any) -> None:
    limits = NESTED_COUNT_LIMITS.get(section) or {}
    if not limits or not isinstance(value, Mapping):
        return
    for key, maximum in limits.items():
        collection = value.get(key)
        if isinstance(collection, (list, dict)) and len(collection) > maximum:
            raise CheckpointV2Error(
                "checkpoint_v2_nested_count_limit_exceeded",
                section=section, collection=key, count=len(collection),
                maximum=maximum)


def _remove_pending(path: pathlib.Path) -> None:
    """Remove only a V2-owned, not-yet-published generation."""
    if not path.name.startswith(".v2-pending-"):
        raise CheckpointV2Error("checkpoint_v2_cleanup_scope_rejected")
    for child in path.iterdir():
        if child.is_symlink() or not child.is_file():
            raise CheckpointV2Error("checkpoint_v2_cleanup_shape_rejected")
        child.unlink()
    path.rmdir()


def reconcile_pending_generations(root: str) -> Dict[str, Any]:
    """Remove only abandoned V2-owned pending dirs under the writer lock."""
    root_path = pathlib.Path(root).resolve()
    removed = 0
    malformed = 0
    if not root_path.exists():
        return {"detectedCount": 0, "removedCount": 0,
                "malformedCount": 0}
    candidates = [
        path for path in root_path.iterdir()
        if path.is_dir() and not path.is_symlink() and
        path.name.startswith(".v2-pending-")]
    for path in candidates[:16]:
        try:
            _remove_pending(path)
            removed += 1
        except (OSError, CheckpointV2Error):
            malformed += 1
    return {"detectedCount": len(candidates), "removedCount": removed,
            "malformedCount": malformed}


def _prune_generations(root: pathlib.Path, retained_ids) -> None:
    """Bound V2 disk use without ever touching legacy or incident evidence."""
    retained = set(retained_ids)
    candidates = sorted(
        (path for path in root.iterdir()
         if path.is_dir() and not path.is_symlink()
         and path.name.startswith("v2-generation-")),
        key=lambda path: path.stat().st_mtime_ns, reverse=True)
    keep = set(path.name.removeprefix("v2-generation-")
               for path in candidates[:MAXIMUM_GENERATIONS]) | retained
    for path in candidates:
        generation_id = path.name.removeprefix("v2-generation-")
        if generation_id in keep:
            continue
        children = list(path.iterdir())
        if len(children) != 1 or children[0].name != DATABASE_NAME or \
                children[0].is_symlink() or not children[0].is_file():
            continue
        children[0].unlink()
        path.rmdir()


def disk_budget_status(root: str, *, disk_usage_fn=shutil.disk_usage,
                       minimum_free_space_reserve: int =
                       MINIMUM_FREE_SPACE_RESERVE) -> Dict[str, Any]:
    """Return a V2-only capacity view; never enumerate legacy temp names."""
    root_path = pathlib.Path(root).resolve()
    retained_bytes = pending_bytes = 0
    retained_count = pending_count = 0
    if root_path.exists():
        for path in root_path.iterdir():
            if path.is_symlink() or not path.is_dir():
                continue
            if path.name.startswith("v2-generation-"):
                retained_count += 1
                database = path / DATABASE_NAME
                if database.is_file() and not database.is_symlink():
                    retained_bytes += database.stat().st_size
            elif path.name.startswith(".v2-pending-"):
                pending_count += 1
                database = path / DATABASE_NAME
                if database.is_file() and not database.is_symlink():
                    pending_bytes += database.stat().st_size
    usage = disk_usage_fn(str(root_path))
    free = int(getattr(usage, "free", usage[2]))
    return {
        "schemaVersion": "argus-checkpoint-v2-disk-budget-v1",
        "retainedGenerationCount": retained_count,
        "retainedGenerationBytes": retained_bytes,
        "pendingGenerationCount": pending_count,
        "pendingGenerationBytes": pending_bytes,
        "maximumRetainedGenerationCount": MAXIMUM_GENERATIONS,
        "maximumRetainedGenerationBytes": MAXIMUM_RETAINED_GENERATION_BYTES,
        "maximumInProgressGenerationBytes": MAXIMUM_IN_PROGRESS_GENERATION_BYTES,
        "maximumV2OwnedBytes": MAXIMUM_V2_OWNED_BYTES,
        "minimumFreeSpaceReserve": int(minimum_free_space_reserve),
        "freeBytes": free,
    }


def _preflight_disk_budget(root: pathlib.Path, *, maximum_total_bytes: int,
                           disk_usage_fn, minimum_free_space_reserve: int):
    status = disk_budget_status(
        str(root), disk_usage_fn=disk_usage_fn,
        minimum_free_space_reserve=minimum_free_space_reserve)
    if status["pendingGenerationCount"]:
        raise CheckpointV2Error(
            "checkpoint_v2_pending_generation_present",
            pendingGenerationCount=status["pendingGenerationCount"])
    if status["retainedGenerationCount"] > MAXIMUM_GENERATIONS or \
            status["retainedGenerationBytes"] > \
            MAXIMUM_RETAINED_GENERATION_BYTES:
        raise CheckpointV2Error(
            "checkpoint_v2_owned_budget_exceeded",
            retainedGenerationCount=status["retainedGenerationCount"],
            retainedGenerationBytes=status["retainedGenerationBytes"])
    required = int(minimum_free_space_reserve) + int(maximum_total_bytes)
    if status["freeBytes"] < required:
        raise CheckpointV2Error(
            "checkpoint_v2_disk_reserve_insufficient",
            freeBytes=status["freeBytes"], requiredFreeBytes=required,
            minimumFreeSpaceReserve=int(minimum_free_space_reserve),
            generationBudgetBytes=int(maximum_total_bytes))
    return status


def _prior_generation_history(root: pathlib.Path):
    path = root / MANIFEST_NAME
    try:
        with open(path, encoding="utf-8") as handle:
            manifest = json.load(handle)
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return []
    history = manifest.get("generationHistory")
    if not isinstance(history, list):
        history = []
    return [row for row in history[-(MAXIMUM_GENERATIONS - 1):]
            if isinstance(row, dict) and row.get("generationId")]


def write_generation(root: str, snapshot: Mapping[str, Any], *,
                     source_generation: str,
                     maximum_total_bytes: int = MAXIMUM_TOTAL_BYTES,
                     fault_after: Optional[str] = None,
                     validation_context: Optional[Mapping[str, Any]] = None,
                     consume_snapshot: bool = False,
                     disk_usage_fn=shutil.disk_usage,
                     minimum_free_space_reserve: int =
                     MINIMUM_FREE_SPACE_RESERVE) -> Dict[str, Any]:
    if consume_snapshot and not isinstance(snapshot, MutableMapping):
        raise CheckpointV2Error(
            "checkpoint_v2_consumable_snapshot_required")
    started = time.monotonic()
    rss_before = _process_rss_bytes()
    cgroup_before = _cgroup_current_bytes()
    cgroup_peak_before = _cgroup_peak_bytes()
    sampler = _ResourceSampler()
    sampler.start()
    database_bytes = None
    section_manifest: Dict[str, Any] = {}
    disk_before: Dict[str, Any] = {}
    lock_wait_ms = 0.0
    allocator_reclaim: Dict[str, Any] = {}
    value: Any = None
    source_total = 0
    reclaim_source_bytes = 0
    legacy_temp_before = _legacy_temp_count(
        (validation_context or {}).get("legacyCheckpointPath"),
        (validation_context or {}).get("legacyTempDirectory"))
    root_path = pathlib.Path(root).resolve()
    root_path.mkdir(parents=True, exist_ok=True)
    lock_path = root_path / "checkpoint-v2.writer.lock"
    lock = open(lock_path, "a+b")
    phase = "writer_lock"
    try:
        lock_started = time.monotonic()
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise CheckpointV2Error("checkpoint_v2_writer_busy") from exc
        lock_wait_ms = (time.monotonic() - lock_started) * 1000
        pending_reconciliation = reconcile_pending_generations(str(root_path))
        if pending_reconciliation["malformedCount"] or \
                pending_reconciliation["detectedCount"] > 16:
            raise CheckpointV2Error(
                "checkpoint_v2_pending_generation_malformed",
                **pending_reconciliation)
        disk_before = _preflight_disk_budget(
            root_path, maximum_total_bytes=maximum_total_bytes,
            disk_usage_fn=disk_usage_fn,
            minimum_free_space_reserve=minimum_free_space_reserve)
        generation_id = uuid.uuid4().hex
        pending = root_path / f".v2-pending-{generation_id}"
        final = root_path / f"v2-generation-{generation_id}"
        pending.mkdir(mode=0o700)
        phase = "transaction"
        database = pending / DATABASE_NAME
        connection = _connect(str(database))
        section_manifest = {}
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.executemany(
                "INSERT INTO metadata(key,value) VALUES (?,?)", (
                    ("schemaVersion", SCHEMA),
                    ("generationId", generation_id),
                    ("sourceGeneration", source_generation),
                    ("createdAt", _iso_now()),
                ))
            for section in list(snapshot):
                value = snapshot[section]
                _validate_collection_bounds(section, value)
                count_limit = COUNT_LIMITS.get(section)
                if count_limit is not None and isinstance(value, (list, dict)) \
                        and len(value) > count_limit:
                    raise CheckpointV2Error(
                        "checkpoint_v2_count_limit_exceeded",
                        section=section, count=len(value), maximum=count_limit)
                source_bytes, source_hash = _stream_stats(value)
                reclaim_source_bytes = max(
                    reclaim_source_bytes, source_total + source_bytes)
                section_limit = SECTION_LIMITS.get(
                    section, DEFAULT_SECTION_LIMIT)
                if source_bytes > section_limit:
                    raise CheckpointV2Error(
                        "checkpoint_v2_section_limit_exceeded",
                        section=section, bytes=source_bytes,
                        maximumBytes=section_limit)
                source_total += source_bytes
                if source_total > maximum_total_bytes:
                    raise CheckpointV2Error(
                        "checkpoint_v2_total_limit_exceeded",
                        bytes=source_total, maximumBytes=maximum_total_bytes)
                rows = containers = 0
                for item_type, item_path, item in _partition(value):
                    path_json = json.dumps(
                        item_path, ensure_ascii=False, separators=(",", ":"))
                    if item_type == "container":
                        connection.execute(
                            "INSERT INTO containers VALUES (?,?,?,?,?)",
                            (section, path_json, item["kind"], item["length"],
                             generation_id))
                        containers += 1
                        continue
                    payload = _encode_bounded(item)
                    connection.execute(
                        "INSERT INTO rows VALUES (?,?,?,?,?,?,?)",
                        (section, path_json, payload, len(payload),
                         hashlib.sha256(payload).hexdigest(), ROW_SCHEMA,
                         generation_id))
                    rows += 1
                    del payload
                    if fault_after == "segment":
                        raise OSError("injected_during_segment")
                root_kind, root_length = _root_descriptor(value)
                connection.execute(
                    "INSERT INTO sections VALUES (?,?,?,?,?,?,?,?,?)",
                    (section, root_kind, root_length, source_bytes,
                     source_hash, rows, containers, SCHEMA, generation_id))
                section_manifest[section] = {
                    "schemaVersion": SCHEMA, "generationId": generation_id,
                    "sourceBytes": source_bytes, "sourceSha256": source_hash,
                    "rowCount": rows, "containerCount": containers,
                    "hardLimitBytes": section_limit,
                    "countLimit": count_limit,
                }
                if consume_snapshot:
                    del snapshot[section]
                value = None
            connection.commit()
            if fault_after == "transaction":
                raise OSError("injected_after_transaction")
        except BaseException:
            with contextlib.suppress(Exception):
                connection.rollback()
            raise
        finally:
            connection.close()
        descriptor = os.open(database, os.O_RDONLY)
        phase = "database_fsync"
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        _fsync_directory(str(pending))
        phase = "database_checksum"
        database_bytes, database_hash = _file_stats(str(database))
        if database_bytes > maximum_total_bytes:
            raise CheckpointV2Error(
                "checkpoint_v2_database_limit_exceeded",
                bytes=database_bytes, maximumBytes=maximum_total_bytes)
        if fault_after == "database_fsync":
            raise OSError("injected_after_database_fsync")
        phase = "generation_rename"
        os.replace(pending, final)
        phase = "root_fsync"
        _fsync_directory(str(root_path))
        if fault_after == "generation_rename":
            raise OSError("injected_after_generation_rename")
        manifest = {
            "schemaVersion": SCHEMA, "generationId": generation_id,
            "createdAt": _iso_now(), "sourceGeneration": source_generation,
            "database": {"name": DATABASE_NAME, "bytes": database_bytes,
                         "sha256": database_hash},
            "sourceSerializedBytes": source_total,
            "hardLimitBytes": maximum_total_bytes,
            "maximumRowBytes": MAXIMUM_ROW_BYTES,
            "sections": section_manifest,
        }
        provenance = {
            "generationId": generation_id,
            "createdAt": manifest["createdAt"],
            "triggerSource": str(
                (validation_context or {}).get("triggerSource") or "unknown"),
            "missionWindowId": (validation_context or {}).get(
                "missionWindowId"),
            "natural": bool((validation_context or {}).get("natural")),
            "legacyRestoreAuthority": True,
            "formalSoakState": str(
                (validation_context or {}).get("formalSoakState") or
                "not_started"),
            "databaseBytes": database_bytes,
            "sourceSerializedBytes": source_total,
            "requiredSectionsPresent": True,
            "transactionCommitted": True,
            "manifestPromoted": True,
        }
        manifest["generationHistory"] = (
            _prior_generation_history(root_path) + [provenance])[-MAXIMUM_GENERATIONS:]
        manifest["stage1Validation"] = provenance
        manifest["diskBudgetBefore"] = disk_before
        phase = "manifest_promotion"
        manifest_write = legacy.atomic_write_json(
            str(root_path / MANIFEST_NAME), manifest,
            temp_directory=str(root_path), maximum_bytes=1024 * 1024)
        phase = "retention_prune"
        _prune_generations(root_path, (generation_id,))
        disk_after = disk_budget_status(
            str(root_path), disk_usage_fn=disk_usage_fn,
            minimum_free_space_reserve=minimum_free_space_reserve)
        if consume_snapshot:
            snapshot.clear()
            value = None
            allocator_reclaim = _release_unused_allocator_memory(
                source_total)
        telemetry = _resource_telemetry(
            started=started, rss_before=rss_before,
            cgroup_before=cgroup_before,
            cgroup_peak_before=cgroup_peak_before,
            sampler=sampler,
            database_bytes=database_bytes,
            row_count=sum(int(row.get("rowCount") or 0)
                          for row in section_manifest.values()),
            section_count=len(section_manifest),
            disk_free_before=disk_before.get("freeBytes"),
            disk_free_after=disk_after.get("freeBytes"),
            pending_count=disk_after.get("pendingGenerationCount") or 0,
            lock_wait_ms=lock_wait_ms, success=True,
            legacy_temp_before=legacy_temp_before,
            legacy_temp_after=_legacy_temp_count(
                (validation_context or {}).get("legacyCheckpointPath"),
                (validation_context or {}).get("legacyTempDirectory")),
            allocator_reclaim=allocator_reclaim)
        provenance["resourceTelemetry"] = telemetry
        manifest["stage1Validation"] = provenance
        manifest["generationHistory"][-1] = provenance
        # Persist the telemetry as part of the promoted manifest. Rewriting the
        # small pointer is atomic and never touches the immutable generation.
        manifest_write = legacy.atomic_write_json(
            str(root_path / MANIFEST_NAME), manifest,
            temp_directory=str(root_path), maximum_bytes=1024 * 1024)
        return {"verified": True, "generationId": generation_id,
                "createdAt": manifest["createdAt"],
                "manifest": str(root_path / MANIFEST_NAME),
                "databaseBytes": database_bytes,
                "sourceSerializedBytes": source_total,
                "sectionCount": len(section_manifest),
                "validation": provenance,
                "diskBudgetBefore": disk_before,
                "pendingReconciliation": pending_reconciliation,
                "manifestWrite": manifest_write,
                "resourceTelemetry": telemetry}
    except BaseException as exc:
        if consume_snapshot:
            snapshot.clear()
            value = None
            allocator_reclaim = _release_unused_allocator_memory(
                reclaim_source_bytes)
        if "pending" in locals() and pending.exists():
            with contextlib.suppress(OSError, CheckpointV2Error):
                _remove_pending(pending)
        failure_telemetry = _resource_telemetry(
            started=started, rss_before=rss_before,
            cgroup_before=cgroup_before,
            cgroup_peak_before=cgroup_peak_before,
            sampler=sampler,
            database_bytes=database_bytes,
            row_count=sum(int(row.get("rowCount") or 0)
                          for row in section_manifest.values()),
            section_count=len(section_manifest),
            disk_free_before=disk_before.get("freeBytes"),
            disk_free_after=(disk_budget_status(
                str(root_path), disk_usage_fn=disk_usage_fn,
                minimum_free_space_reserve=minimum_free_space_reserve
            ).get("freeBytes") if root_path.exists() else None),
            pending_count=0, lock_wait_ms=lock_wait_ms, success=False,
            legacy_temp_before=legacy_temp_before,
            legacy_temp_after=_legacy_temp_count(
                (validation_context or {}).get("legacyCheckpointPath"),
                (validation_context or {}).get("legacyTempDirectory")),
            allocator_reclaim=allocator_reclaim)
        if isinstance(exc, CheckpointV2Error):
            exc.details.setdefault("resourceTelemetry", failure_telemetry)
            raise
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
        classification = {
            "transaction": "checkpoint_v2_transaction_failed",
            "database_fsync": "checkpoint_v2_fsync_failed",
            "database_checksum": "checkpoint_v2_checksum_failed",
            "generation_rename": "checkpoint_v2_generation_rename_failed",
            "root_fsync": "checkpoint_v2_fsync_failed",
            "manifest_promotion": "checkpoint_v2_manifest_promotion_failed",
            "retention_prune": "checkpoint_v2_retention_prune_failed",
        }.get(phase, "checkpoint_v2_write_failed")
        raise CheckpointV2Error(
            classification, phase=phase,
            causeClass=type(exc).__name__,
            resourceTelemetry=failure_telemetry) from exc
    finally:
        sampler.finish()
        with contextlib.suppress(OSError):
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        lock.close()


def _empty(kind: str, length: Optional[int]):
    if kind == "dict":
        return {}
    if kind == "list":
        return [None] * int(length or 0)
    return None


def _assign(root: Any, path: Tuple[Any, ...], value: Any) -> Any:
    if not path:
        return value
    cursor = root
    for part in path[:-1]:
        cursor = cursor[part]
    cursor[path[-1]] = value
    return root


def _verify_rows_without_parsing(connection: sqlite3.Connection, section: str,
                                 row_count: int, generation_id: str) -> None:
    seen = 0
    rows = connection.execute(
        "SELECT payload,payload_bytes,payload_sha256,schema_version,"
        "generation_id FROM rows WHERE section=?", (section,))
    for payload, payload_bytes, payload_hash, schema, row_generation in rows:
        if schema != ROW_SCHEMA or row_generation != generation_id:
            raise CheckpointV2Error("checkpoint_v2_row_schema_invalid")
        if len(payload) != payload_bytes or \
                hashlib.sha256(payload).hexdigest() != payload_hash:
            raise CheckpointV2Error("checkpoint_v2_row_hash_mismatch")
        del payload
        seen += 1
    if seen != row_count:
        raise CheckpointV2Error("checkpoint_v2_row_missing")


def restore_generation(root: str, *,
                       include_archived: bool = True) -> Dict[str, Any]:
    root_path = pathlib.Path(root).resolve()
    manifest_path = root_path / MANIFEST_NAME
    with open(manifest_path, encoding="utf-8") as handle:
        manifest = json.load(handle)
    if manifest.get("schemaVersion") != SCHEMA:
        raise CheckpointV2Error("checkpoint_v2_manifest_schema_unsupported")
    generation_id = str(manifest.get("generationId") or "")
    database_meta = manifest.get("database") or {}
    database = root_path / f"v2-generation-{generation_id}" / DATABASE_NAME
    try:
        size, digest = _file_stats(str(database))
    except FileNotFoundError as exc:
        raise CheckpointV2Error("checkpoint_v2_database_missing") from exc
    if size != int(database_meta.get("bytes") or -1) or \
            digest != database_meta.get("sha256"):
        raise CheckpointV2Error("checkpoint_v2_database_hash_mismatch")
    uri = f"file:{database}?mode=ro&immutable=1"
    connection = sqlite3.connect(uri, uri=True)
    restored = {}
    try:
        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise CheckpointV2Error("checkpoint_v2_sqlite_integrity_failed")
        sections = connection.execute(
            "SELECT name,root_kind,root_length,source_bytes,source_sha256,"
            "row_count,container_count,schema_version,generation_id "
            "FROM sections ORDER BY name").fetchall()
        for (name, kind, length, source_bytes, source_hash, row_count,
             container_count, schema_version, row_generation) in sections:
            if schema_version != SCHEMA or row_generation != generation_id:
                raise CheckpointV2Error("checkpoint_v2_generation_mismatch")
            if name in ARCHIVE_SECTIONS and not include_archived:
                _verify_rows_without_parsing(
                    connection, name, row_count, generation_id)
                continue
            value = _empty(kind, length)
            containers = connection.execute(
                "SELECT path,kind,length,generation_id FROM containers "
                "WHERE section=? ORDER BY length(path),path", (name,)).fetchall()
            if len(containers) != container_count:
                raise CheckpointV2Error("checkpoint_v2_container_missing")
            for path_json, child_kind, child_length, child_generation in containers:
                if child_generation != generation_id:
                    raise CheckpointV2Error("checkpoint_v2_generation_mismatch")
                path = tuple(json.loads(path_json))
                value = _assign(value, path, _empty(child_kind, child_length))
            rows = connection.execute(
                "SELECT path,payload,payload_bytes,payload_sha256,"
                "schema_version,generation_id FROM rows WHERE section=? "
                "ORDER BY path", (name,))
            seen_rows = 0
            for (path_json, payload, payload_bytes, payload_hash,
                 row_schema, row_generation) in rows:
                if row_schema != ROW_SCHEMA or row_generation != generation_id:
                    raise CheckpointV2Error("checkpoint_v2_row_schema_invalid")
                if len(payload) != payload_bytes or \
                        hashlib.sha256(payload).hexdigest() != payload_hash:
                    raise CheckpointV2Error("checkpoint_v2_row_hash_mismatch")
                child = json.loads(payload)
                value = _assign(value, tuple(json.loads(path_json)), child)
                del child, payload
                seen_rows += 1
            if seen_rows != row_count:
                raise CheckpointV2Error("checkpoint_v2_row_missing")
            actual_bytes, actual_hash = _stream_stats(value)
            if actual_bytes != source_bytes or actual_hash != source_hash:
                raise CheckpointV2Error("checkpoint_v2_section_hash_mismatch")
            restored[name] = value
            gc.collect()
    finally:
        connection.close()
    return {"verified": True, "generationId": generation_id,
            "sourceGeneration": manifest.get("sourceGeneration"),
            "snapshot": restored, "sectionCount": len(restored),
            "archivedSections": sorted(
                ARCHIVE_SECTIONS & set(manifest.get("sections") or {}))
                if not include_archived else []}


def migrate_legacy_checkpoint(legacy_path: str, root: str, *,
                              require_seal: bool = True,
                              fault_after: Optional[str] = None) -> Dict[str, Any]:
    """Idempotently create V2 without modifying the old checkpoint.

    Production migration is intended to run in an isolated 4 GiB-capped
    process. The source is parsed once, transferred to the V2 writer without a
    deep copy, then released. The original inode identity must remain stable.
    """
    source = pathlib.Path(legacy_path).resolve()
    before = source.stat()
    source_bytes, source_hash = _file_stats(str(source))
    source_generation = f"legacy-sha256:{source_hash}"
    status = public_status(root)
    if status.get("sourceGeneration") == source_generation:
        verified = restore_generation(root)
        del verified["snapshot"]
        return {"verified": True, "status": "already_migrated",
                "sourceGeneration": source_generation,
                "sourceBytes": source_bytes,
                "generationId": status.get("generationId")}
    snapshot = legacy.load_checkpoint(
        str(source), require_seal=require_seal,
        allow_legacy_file_seal=True)
    try:
        result = write_generation(
            root, snapshot, source_generation=source_generation,
            fault_after=fault_after)
    finally:
        del snapshot
        gc.collect()
    after = source.stat()
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != \
            (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
        raise CheckpointV2Error("checkpoint_v2_legacy_source_changed")
    return {**result, "status": "migrated",
            "sourceGeneration": source_generation,
            "sourceBytes": source_bytes}


def public_status(root: str) -> Dict[str, Any]:
    path = pathlib.Path(root).resolve() / MANIFEST_NAME
    try:
        with open(path, encoding="utf-8") as handle:
            manifest = json.load(handle)
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {"schemaVersion": SCHEMA, "state": "not_created"}
    history = [row for row in (manifest.get("generationHistory") or [])
               if isinstance(row, dict)]
    natural = [row for row in history
               if row.get("natural") is True and
               row.get("triggerSource") == "ec2_systemd"]
    natural_windows = {
        str(row.get("missionWindowId")) for row in natural
        if str(row.get("missionWindowId") or "").startswith("mw-")
    }
    return {"schemaVersion": SCHEMA, "state": "stage1_dual_write",
            "generationId": manifest.get("generationId"),
            "sourceGeneration": manifest.get("sourceGeneration"),
            "sourceSerializedBytes": manifest.get("sourceSerializedBytes"),
            "hardLimitBytes": manifest.get("hardLimitBytes"),
            "maximumRowBytes": manifest.get("maximumRowBytes"),
            "sectionCount": len(manifest.get("sections") or {}),
            "validationWindowCount": len(natural_windows),
            "generationCount": len(natural),
            # Compatibility alias; this is a physical-generation count, not
            # the Stage 1 acceptance window count.
            "naturalGenerationCount": len(natural),
            "generationHistory": history,
            "legacyRestoreAuthority": True,
            "v2RestoreAuthority": False,
            "formalSoakState": (manifest.get("stage1Validation") or {}).get(
                "formalSoakState") or "not_started"}
