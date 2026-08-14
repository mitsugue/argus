#!/usr/bin/env python3
"""Reproducible standalone benchmark for detailed checkpoint accounting.

Normal acceptance fixture: 145 MiB canonical JSON (must remain 130-160 MiB).
CI smoke: ``python scripts/recovery_measurement_benchmark.py --smoke``.
"""
from __future__ import annotations

import argparse
import gc
import json
import math
import pathlib
import resource
import sys
import time
from typing import Dict, List


ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import argus_recovery_measurement as measurement  # noqa: E402
import argus_recovery_registry as registry  # noqa: E402


MIB = 1024 * 1024


def _rss_bytes() -> int:
    try:
        with open("/proc/self/status", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) * 1024
    except (FileNotFoundError, OSError, ValueError, IndexError):
        pass
    value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return value if sys.platform == "darwin" else value * 1024


def _p95(values: List[float]) -> float:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * .95) - 1)]


def _unique_text(index: int, characters: int) -> str:
    # Every record owns a distinct string object and record-specific content.
    alphabet = "abcdefghijklmnopqrstuvwxyz0123456789"
    offset = index % len(alphabet)
    pattern = alphabet[offset:] + alphabet[:offset]
    prefix = f"record-{index:08d}:"
    return prefix + (pattern * math.ceil(
        (characters - len(prefix)) / len(pattern)))[:characters-len(prefix)]


def build_fixture(target_mib: int) -> Dict[str, object]:
    keys = list(registry.registered_checkpoint_keys())
    if not keys or len(keys) > measurement.MAX_CHECKPOINT_SECTION_KEYS:
        raise RuntimeError("registered_section_budget_invalid")
    fixture: Dict[str, object] = {key: [] for key in keys}
    target_payload = target_mib * MIB
    content_chars = 16 * 1024
    rows = max(1, target_payload // (content_chars + 256))
    timestamp = "2026-08-15T00:00:00Z"
    for index in range(rows):
        key = keys[index % len(keys)]
        section = fixture[key]
        assert isinstance(section, list)
        section.append({
            "recordId": f"benchmark-{index:08d}",
            "sequence": index,
            "observedAt": timestamp,
            "sourceRevision": f"revision-{index:08x}",
            "numericVector": [index, index % 997, index % 65_521],
            "flags": {"active": bool(index % 2), "verified": True},
            "uniqueNestedData": _unique_text(index, content_chars),
        })
    fixture["schemaVersion"] = "argus-durable-v3"
    return fixture


def run(target_mib: int, samples: int, *, smoke: bool) -> Dict[str, object]:
    fixture = build_fixture(target_mib)
    before_rss = _rss_bytes()
    baseline_seconds = []
    accounting_seconds = []
    accounting = None
    for _ in range(samples):
        started = time.perf_counter()
        baseline_bytes = measurement.streaming_canonical_size(fixture)
        baseline_seconds.append(time.perf_counter() - started)
        started = time.perf_counter()
        accounting = measurement.streaming_checkpoint_accounting(fixture)
        accounting_seconds.append(time.perf_counter() - started)
        if accounting.total_serialized_bytes != baseline_bytes:
            raise RuntimeError("streaming_count_mismatch")
    peak_delta = max(0, _rss_bytes() - before_rss)
    gc.collect()
    retained_delta = max(0, _rss_bytes() - before_rss)
    assert accounting is not None
    baseline_p95 = _p95(baseline_seconds)
    accounting_p95 = _p95(accounting_seconds)
    ratio = accounting_p95 / baseline_p95 if baseline_p95 else 0.0
    size_mib = accounting.total_serialized_bytes / MIB
    gates = {
        "fixtureSizeInRange": smoke or 130 <= size_mib <= 160,
        "sectionAccountingP95Seconds": smoke or accounting_p95 <= 2.0,
        "canonicalPassRatio": ratio <= 1.25,
        "measurementEnabledRatio": ratio <= 1.25,
        "attributablePeakRssBytes": peak_delta <= 32 * MIB,
        "postGcRetainedRssBytes": retained_delta <= 8 * MIB,
        "fullSizeBuffers": accounting.full_size_buffers == 0,
        "outputChunkBound": (
            accounting.output_chunk_limit_bytes <= measurement.MAX_STREAM_CHUNK_BYTES),
    }
    return {
        "schemaVersion": "argus-recovery-measurement-benchmark-v1",
        "mode": "smoke" if smoke else "acceptance",
        "targetMiB": target_mib,
        "fixtureCanonicalBytes": accounting.total_serialized_bytes,
        "fixtureCanonicalMiB": round(size_mib, 3),
        "registeredSectionCount": len(accounting.registered_section_bytes),
        "samples": samples,
        "baselineCanonicalCountP95Seconds": round(baseline_p95, 6),
        "sectionAccountingP95Seconds": round(accounting_p95, 6),
        "accountingToCanonicalPassRatio": round(ratio, 4),
        "measurementEnabledToDisabledRatio": round(ratio, 4),
        "attributablePeakRssBytes": peak_delta,
        "postGcRetainedRssBytes": retained_delta,
        "fullSizeBuffers": accounting.full_size_buffers,
        "outputChunkLimitBytes": accounting.output_chunk_limit_bytes,
        "gates": gates,
        "passed": all(gates.values()),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target-mib", type=int, default=145)
    parser.add_argument("--samples", type=int, default=5)
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()
    target = 2 if args.smoke and args.target_mib == 145 else args.target_mib
    samples = 1 if args.smoke and args.samples == 5 else args.samples
    if target < 1 or not 1 <= samples <= 20:
        raise SystemExit("benchmark_arguments_invalid")
    report = run(target, samples, smoke=args.smoke)
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
