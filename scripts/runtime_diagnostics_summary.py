#!/usr/bin/env python3
"""Plain-language summary of the owner-only runtime snapshot (v13.5.61).

Input: the JSON returned by /api/argus/admin/memory-attribution?threads=1.
Output: private Markdown. Locations and counters only — the
document never carries values, environment, or owner data, and this script
adds nothing of its own beyond formatting. The optional identity projection
contains only observed build/readiness scalars.
"""
from __future__ import annotations

import json
from datetime import datetime
import re
import sys
from typing import Any


def observed_backend_identity(before: dict, after: dict, ready: dict, *, at: str) -> dict:
    """Bind a private snapshot to matching observed health/readiness probes."""
    if not all(isinstance(value, dict) for value in (before, after, ready)):
        raise ValueError('runtime_backend_identity_invalid')
    try:
        stamp = datetime.fromisoformat(at.replace('Z', '+00:00'))
    except (AttributeError, TypeError, ValueError):
        raise ValueError('runtime_backend_identity_invalid') from None
    shas = [value.get('buildSha') for value in (before, after, ready)]
    versions = [value.get('backendVersion') or value.get('appVersion') for value in (before, after)]
    if (stamp.tzinfo is None or any(not isinstance(sha, str) or not re.fullmatch(r'[0-9a-f]{40}', sha)
                                 for sha in shas)
            or any(not isinstance(version, str) or not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', version)
                   for version in versions)):
        raise ValueError('runtime_backend_identity_invalid')
    if (len(set(shas)) != 1 or len(set(versions)) != 1
            or before.get('status') != 'ok' or after.get('status') != 'ok'
            or ready.get('ready') is not True):
        raise ValueError('runtime_backend_identity_inconsistent')
    return {'schemaVersion': 'argus-runtime-observed-backend-identity-v1',
            'capturedAt': at, 'observedBackendSha': shas[0], 'backendVersion': versions[0],
            'healthBeforeAndAfterMatch': True, 'readyBuildMatches': True, 'status': 'verified'}


def _frames(thread: dict, limit: int) -> str:
    rows = thread.get("frames") or []
    tail = rows[-limit:] if rows else []
    if not tail:
        return "(no Python frame)"
    return " ← ".join(f"{f.get('file')}:{f.get('line')} {f.get('function')}" for f in reversed(tail))


def summarize(doc: dict[str, Any]) -> str:
    out: list[str] = ["# ARGUS runtime diagnostics", ""]
    threads = doc.get("runtimeThreads") or {}
    out.append(f"- generatedAt: `{threads.get('generatedAt')}`")
    out.append(f"- threads alive: **{threads.get('threadCount')}**")
    out.append(f"- decision-evidence cache size: {threads.get('decisionEvidenceCacheSize')}")
    flight = threads.get("singleFlight") or []
    out.append(f"- single-flight in progress: {len(flight)}"
               + (" — " + ", ".join(f"`{row.get('key')}` {row.get('ageSec')}s" for row in flight) if flight else ""))
    out.append("")
    out.append("## Threads (innermost frame first)")
    out.append("")
    rows = threads.get("threads") or []
    request_threads = [t for t in rows if str(t.get("name", "")).startswith("Thread-")]
    named = [t for t in rows if not str(t.get("name", "")).startswith("Thread-")]
    out.append(f"request threads: {len(request_threads)} · named threads: {len(named)}")
    out.append("")
    for thread in named + request_threads[:24]:
        out.append(f"- **{thread.get('name')}**"
                   f"{' (daemon)' if thread.get('daemon') else ''}: {_frames(thread, 4)}")
    if len(request_threads) > 24:
        out.append(f"- … {len(request_threads) - 24} more request threads (see artifact)")
    out.append("")
    out.append("## Memory attribution (scalar history)")
    out.append("")
    for key in ("historyCount", "completedCount", "droppedCount", "activeCount", "historyLimit"):
        if key in doc:
            out.append(f"- {key}: {doc.get(key)}")
    operations = doc.get("operationAttribution") or {}
    for key in ("observedCount", "qualifiedCount", "droppedCount", "thresholdBytes"):
        if key in operations:
            out.append(f"- operations.{key}: {operations.get(key)}")
    active = doc.get("active") or []
    if active:
        out.append(f"- active phases: {len(active)}")
    reclaim = doc.get("allocatorReclaim") or {}
    if reclaim:
        out.append("")
        out.append("## Allocator policy and reclaim")
        out.append("")
        policy = reclaim.get("startupPolicy") or {}
        out.append(f"- startup policy: {policy.get('status')} {policy.get('applied') or ''}")
        out.append(f"- reclaims: {reclaim.get('count')} · last at {reclaim.get('lastAt')} "
                   f"· reason {reclaim.get('lastReason')}")
        last = reclaim.get("last") or {}
        if last:
            out.append(f"- last reclaim: rss {_mib(last.get('rssBeforeBytes'))} → "
                       f"{_mib(last.get('rssAfterBytes'))} MiB, free arena "
                       f"{_mib((last.get('allocatorBefore') or {}).get('freeBytes'))} → "
                       f"{_mib((last.get('allocatorAfter') or {}).get('freeBytes'))} MiB, "
                       f"{last.get('durationMs')} ms")
    inventory = doc.get("residentInventory") or {}
    coverage = inventory.get("memoryCoverage") or {}
    if coverage:
        out.append("")
        out.append("## Current process and cgroup memory")
        for phase in ("before", "after"):
            sample = coverage.get(phase) or {}
            group = sample.get("cgroup") or {}
            allocator = sample.get("allocatorMetrics") or {}
            allocator = allocator if isinstance(allocator, dict) else {}
            out.append(f"- {phase}: cgroup current/peak/max MiB "
                       f"{_mib(group.get('memoryCurrentBytes'))}/"
                       f"{_mib(group.get('memoryPeakBytes'))}/{_mib(group.get('memoryMaxBytes'))}; "
                       f"glibc allocated/free/mmap MiB {_mib(allocator.get('allocatedBytes'))}/"
                       f"{_mib(allocator.get('freeBytes'))}/{_mib(allocator.get('mmapBytes'))}")
            out.append(f"- {phase} memory events: {group.get('events')}")
            small = coverage.get("pythonAllocator" + phase.title()) or {}
            out.append(f"- {phase} CPython allocator: {small.get('status')}; "
                       f"reserved/allocated/available/unused-pool MiB "
                       f"{_mib(small.get('arenaBytesCurrent'))}/"
                       f"{_mib(small.get('allocatedSmallBlockBytes'))}/"
                       f"{_mib(small.get('availableSmallBlockBytes'))}/"
                       f"{_mib(small.get('unusedPoolBytes'))}; reservations are not RSS")
        graph = coverage.get("builtinGraph") or {}
        out.append(f"- builtin graph: {graph.get('status')}; selected roots, "
                   "first discovery, non-atomic; not a whole-heap or RSS measurement")
        for row in graph.get("rows") or []:
            out.append(f"- `{row.get('name')}`: new shallow MiB "
                       f"{_mib(row.get('newlyVisitedShallowBytes'))}, "
                       f"objects {row.get('newObjectCount')}, shared {row.get('sharedReferenceCount')}, "
                       f"opaque {row.get('opaqueReferenceCount')}, {row.get('status')}")
    rows = inventory.get("rows") or []
    if rows:
        out.append("")
        out.append("## Resident inventory (serialized size, largest first)")
        out.append("")
        out.append(f"total {_mib(inventory.get('totalSerializedBytes'))} MiB across "
                   f"{inventory.get('measuredCount')} containers in {inventory.get('elapsedMs')} ms")
        out.append("")
        out.append("| container | type | length | MiB | status |")
        out.append("|---|---|---:|---:|---|")
        for row in rows[:24]:
            out.append(f"| `{row.get('name')}` | {row.get('type')} | {row.get('length')} | "
                       f"{_mib(row.get('serializedBytes'))} | {row.get('status')} |")
    return "\n".join(out) + "\n"


def _mib(value: Any) -> str:
    try:
        return f"{int(value) / (1024 * 1024):.1f}"
    except (TypeError, ValueError):
        return "?"


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: runtime_diagnostics_summary.py <snapshot.json>", file=sys.stderr)
        return 2
    with open(argv[1], encoding="utf-8") as fh:
        doc = json.load(fh)
    if not isinstance(doc, dict):
        print("snapshot is not an object", file=sys.stderr)
        return 1
    sys.stdout.write(summarize(doc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
