"""Process allocator policy and resident-size inventory (pure, secret-free).

Production evidence (runtime diagnostics run 36279443457, build 22478dce,
2026-09-27): between mission ticks the web process held RSS 3.69 GB while the
glibc arena reported 2.03 GB total of which **1.85 GB was free but not
returned** (`fordblks`), with only 21 MB releasable from the arena top.  That
is allocator fragmentation left behind by generation-sized temporaries, not
live application state.

This module provides three small, independently testable pieces:

* ``startup_policy`` — fix the glibc mmap threshold (so generation-sized
  strings and lists are mapped and unmapped individually instead of growing
  the brk heap), cap the arena count, and set the trim threshold.  Applied
  once from the server entry point only; never from module import, so the
  measurement probes and tests observe the untouched allocator.
* ``reclaim_decision`` — decide, from the already-published allocator
  counters, whether a bounded reclaim (``malloc_trim`` through the existing
  checkpoint-v2 helper) is warranted.  It is rate limited, requires a large
  free-but-unreturned balance, and never runs while a mission tick owns the
  process.  This is a runtime hygiene measure with published before/after
  scalars; it is not a telemetry reset and does not touch the 4 GiB gates.
* ``resident_inventory`` — bounded, streaming serialized-size estimate of
  named in-memory containers.  Only names, types, lengths and byte counts are
  returned; no element value is ever copied into the result.

Nothing here reads environment secrets, persists anything, or raises to its
caller.
"""
from __future__ import annotations

import json
import os
import sys
import time
from typing import Any, Callable, Dict, Iterable, Mapping, Optional, Tuple

SCHEMA_VERSION = "argus-allocator-policy-v1"
INVENTORY_SCHEMA_VERSION = "argus-resident-inventory-v1"

# glibc mallopt parameter numbers (malloc.h).
M_TRIM_THRESHOLD = -1
M_MMAP_THRESHOLD = -3
M_ARENA_MAX = -8

DEFAULT_MMAP_THRESHOLD_BYTES = 1 * 1024 * 1024
DEFAULT_TRIM_THRESHOLD_BYTES = 8 * 1024 * 1024
DEFAULT_ARENA_MAX = 4

RECLAIM_MINIMUM_FREE_BYTES = 256 * 1024 * 1024
RECLAIM_MINIMUM_INTERVAL_SECONDS = 300.0

INVENTORY_DEFAULT_LIMIT = 48
INVENTORY_PER_OBJECT_BYTE_BUDGET = 192 * 1024 * 1024
INVENTORY_TOTAL_TIME_BUDGET_SECONDS = 8.0


def _int_env(env: Mapping[str, str], key: str, default: int,
             *, minimum: int, maximum: int) -> Tuple[int, Optional[str]]:
    raw = env.get(key)
    if raw is None or str(raw).strip() == "":
        return default, None
    try:
        value = int(str(raw).strip())
    except ValueError:
        return default, "invalid"
    if not minimum <= value <= maximum:
        return default, "out_of_range"
    return value, None


def startup_policy(env: Optional[Mapping[str, str]] = None, *,
                   platform: Optional[str] = None,
                   mallopt: Optional[Callable[[int, int], int]] = None
                   ) -> Dict[str, Any]:
    """Apply the allocator policy once; return a scalar report, never raise.

    ``ARGUS_MALLOC_MMAP_THRESHOLD_BYTES=0`` disables the policy entirely.
    Values are clamped to glibc's accepted ranges; an invalid override falls
    back to the default and is reported.
    """
    env = os.environ if env is None else env
    platform = sys.platform if platform is None else platform
    report: Dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION, "status": "UNSUPPORTED",
        "applied": {}, "rejected": {}, "overrideErrors": {}}
    mmap_threshold, err = _int_env(
        env, "ARGUS_MALLOC_MMAP_THRESHOLD_BYTES", DEFAULT_MMAP_THRESHOLD_BYTES,
        minimum=0, maximum=32 * 1024 * 1024)
    if err:
        report["overrideErrors"]["ARGUS_MALLOC_MMAP_THRESHOLD_BYTES"] = err
    if mmap_threshold == 0:
        report["status"] = "DISABLED"
        return report
    trim_threshold, err = _int_env(
        env, "ARGUS_MALLOC_TRIM_THRESHOLD_BYTES", DEFAULT_TRIM_THRESHOLD_BYTES,
        minimum=64 * 1024, maximum=256 * 1024 * 1024)
    if err:
        report["overrideErrors"]["ARGUS_MALLOC_TRIM_THRESHOLD_BYTES"] = err
    arena_max, err = _int_env(
        env, "ARGUS_MALLOC_ARENA_MAX", DEFAULT_ARENA_MAX, minimum=1, maximum=64)
    if err:
        report["overrideErrors"]["ARGUS_MALLOC_ARENA_MAX"] = err
    if not str(platform).startswith("linux"):
        return report
    if mallopt is None:
        try:
            import ctypes
            libc = ctypes.CDLL(None)
            native = libc.mallopt
            native.argtypes = [ctypes.c_int, ctypes.c_int]
            native.restype = ctypes.c_int
            mallopt = native
        except (AttributeError, OSError, TypeError, ValueError) as exc:
            report["status"] = "UNAVAILABLE"
            report["errorClass"] = type(exc).__name__
            return report
    settings = (
        ("mmapThresholdBytes", M_MMAP_THRESHOLD, mmap_threshold),
        ("trimThresholdBytes", M_TRIM_THRESHOLD, trim_threshold),
        ("arenaMax", M_ARENA_MAX, arena_max),
    )
    for name, parameter, value in settings:
        try:
            ok = int(mallopt(parameter, value)) == 1
        except Exception as exc:  # pragma: no cover - defensive
            ok = False
            report["errorClass"] = type(exc).__name__
        (report["applied"] if ok else report["rejected"])[name] = value
    report["status"] = "APPLIED" if report["applied"] and not report["rejected"] \
        else ("PARTIAL" if report["applied"] else "REJECTED")
    return report


def reclaim_decision(allocator_metrics: Any, *, now_monotonic: float,
                     last_reclaim_monotonic: Optional[float],
                     mission_active: bool,
                     minimum_free_bytes: int = RECLAIM_MINIMUM_FREE_BYTES,
                     minimum_interval_seconds: float =
                     RECLAIM_MINIMUM_INTERVAL_SECONDS,
                     force: bool = False) -> Dict[str, Any]:
    """Pure decision: reclaim only a large, idle, free-but-unreturned balance.

    ``force`` (used right after a checkpoint save) skips the interval and the
    size floor is halved, because the save has just released generation-sized
    temporaries and the process is otherwise idle.
    """
    decision = {"reclaim": False, "reason": None, "freeBytes": None}
    if mission_active:
        decision["reason"] = "mission_tick_active"
        return decision
    if not isinstance(allocator_metrics, Mapping) or \
            allocator_metrics.get("status") != "AVAILABLE":
        decision["reason"] = "allocator_metrics_unavailable"
        return decision
    try:
        free_bytes = int(allocator_metrics.get("freeBytes") or 0)
    except (TypeError, ValueError):
        decision["reason"] = "allocator_metrics_invalid"
        return decision
    decision["freeBytes"] = free_bytes
    floor = int(minimum_free_bytes // 2 if force else minimum_free_bytes)
    if free_bytes < floor:
        decision["reason"] = "free_below_floor"
        return decision
    if not force and last_reclaim_monotonic is not None and \
            now_monotonic - float(last_reclaim_monotonic) < \
            float(minimum_interval_seconds):
        decision["reason"] = "interval_not_elapsed"
        return decision
    decision.update({"reclaim": True, "reason": "forced" if force else "free_above_floor"})
    return decision


class _Budget(Exception):
    pass


def _serialized_size(value: Any, *, byte_budget: int, deadline: float
                     ) -> Tuple[int, str]:
    """Stream-encode ``value`` counting bytes; never materialize the text."""
    encoder = json.JSONEncoder(
        ensure_ascii=False, separators=(",", ":"), check_circular=True,
        default=lambda other: f"<{type(other).__name__}>")
    total = 0
    checks = 0
    for chunk in encoder.iterencode(value):
        total += len(chunk)
        checks += 1
        if total > byte_budget:
            return total, "TRUNCATED_BYTES"
        if checks % 4096 == 0 and time.monotonic() > deadline:
            return total, "TRUNCATED_TIME"
    return total, "MEASURED"


def resident_inventory(named: Mapping[str, Any], *,
                       limit: int = INVENTORY_DEFAULT_LIMIT,
                       per_object_byte_budget: int =
                       INVENTORY_PER_OBJECT_BYTE_BUDGET,
                       total_time_budget_seconds: float =
                       INVENTORY_TOTAL_TIME_BUDGET_SECONDS,
                       now: Callable[[], float] = time.monotonic
                       ) -> Dict[str, Any]:
    """Serialized-size estimate per named container, largest first.

    Rows carry ``name``, ``type``, ``length`` and ``serializedBytes`` only.
    A container mutated concurrently is reported as ``CONCURRENT_MUTATION``
    with whatever was counted before the mutation; the walk never retries.
    """
    started = now()
    deadline = started + float(total_time_budget_seconds)
    rows = []
    for name, value in named.items():
        row: Dict[str, Any] = {
            "name": str(name)[:80], "type": type(value).__name__,
            "length": None, "serializedBytes": 0, "status": "MEASURED"}
        try:
            row["length"] = len(value)  # type: ignore[arg-type]
        except TypeError:
            row["length"] = None
        if now() > deadline:
            row["status"] = "SKIPPED_TIME"
            rows.append(row)
            continue
        try:
            size, status = _serialized_size(
                value, byte_budget=per_object_byte_budget, deadline=deadline)
            row["serializedBytes"] = size
            row["status"] = status
        except RuntimeError:
            row["status"] = "CONCURRENT_MUTATION"
        except (TypeError, ValueError, RecursionError) as exc:
            row["status"] = f"UNSERIALIZABLE:{type(exc).__name__}"
        rows.append(row)
    rows.sort(key=lambda item: (-int(item["serializedBytes"] or 0), item["name"]))
    total = sum(int(item["serializedBytes"] or 0) for item in rows)
    return {
        "schemaVersion": INVENTORY_SCHEMA_VERSION,
        "measuredCount": len(rows),
        "totalSerializedBytes": total,
        "elapsedMs": int((now() - started) * 1000),
        "rows": rows[:max(1, int(limit))],
    }


def names_present(namespace: Mapping[str, Any], names: Iterable[str]
                  ) -> Dict[str, Any]:
    """Return the subset of ``names`` bound in ``namespace`` (no copies)."""
    return {name: namespace[name] for name in names if name in namespace}
