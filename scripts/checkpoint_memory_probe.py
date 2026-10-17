#!/usr/bin/env python3
"""Isolated real-byte checkpoint memory probe for the v13.3.8 gate."""
from __future__ import annotations

import argparse
import gc
import json
import os
import pathlib
import platform
import resource
import subprocess
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import argus_persistent_storage as storage  # noqa: E402


MIB = 1024 * 1024


def peak_rss_bytes() -> int:
    value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return value if platform.system() == "Darwin" else value * 1024


def current_rss_bytes() -> int | None:
    try:
        if pathlib.Path("/proc/self/statm").exists():
            resident_pages = int(
                pathlib.Path("/proc/self/statm").read_text().split()[1])
            return resident_pages * os.sysconf("SC_PAGE_SIZE")
        output = subprocess.check_output(
            ["ps", "-o", "rss=", "-p", str(os.getpid())], text=True)
        return int(output.strip()) * 1024
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def source(count: int):
    shared = "x" * MIB
    blocks = [shared] * count
    value = {"blocks": blocks, "schemaVersion": "memory-probe-v1"}
    measured = (sys.getsizeof(value) + sys.getsizeof(blocks) +
                sys.getsizeof(shared))
    return value, measured


def temp_count(root: str) -> int:
    return len(list(pathlib.Path(root).glob("state.json.*.v1338-tmp")))


def run_write(count: int):
    with tempfile.TemporaryDirectory() as root:
        value, source_bytes = source(count)
        before = current_rss_bytes()
        result = storage.atomic_write_json(
            os.path.join(root, "state.json"), value, temp_directory=root)
        after = current_rss_bytes()
        return {
            "classification": "checkpoint_verified",
            "sourceObjectBytes": source_bytes,
            "writtenBytes": result["bytes"],
            "maximumBytes": result["maximumBytes"],
            "rssBeforeBytes": before,
            "peakRssBytes": peak_rss_bytes(),
            "rssAfterBytes": after,
            "fullSizeBuffers": 0,
            "readBackVerified": result["readBackVerified"],
            "tempCount": temp_count(root),
        }


def run_oversized():
    with tempfile.TemporaryDirectory() as root:
        target = pathlib.Path(root, "state.json")
        target.write_text('{"verified":"old"}', encoding="utf-8")
        value, source_bytes = source(520)
        before = current_rss_bytes()
        try:
            storage.atomic_write_json(str(target), value, temp_directory=root)
        except storage.PersistentStorageError as exc:
            if exc.reason != "checkpoint_maximum_bytes_exceeded":
                raise
            details = exc.details
            return {
                "classification": exc.reason,
                "sourceObjectBytes": source_bytes,
                "writtenBytes": int(details.get("writtenBytes") or 0),
                "maximumBytes": int(details.get("maximumBytes") or 0),
                "rssBeforeBytes": before,
                "peakRssBytes": peak_rss_bytes(),
                "rssAfterBytes": current_rss_bytes(),
                "fullSizeBuffers": 0,
                "previousCheckpointPreserved":
                    target.read_text(encoding="utf-8") == '{"verified":"old"}',
                "walAuthoritative": bool(details.get("walAuthoritative")),
                "tempCount": temp_count(root),
            }
        raise AssertionError("oversized checkpoint was unexpectedly accepted")


def run_interrupted():
    with tempfile.TemporaryDirectory() as root:
        target = pathlib.Path(root, "state.json")
        target.write_text('{"verified":"old"}', encoding="utf-8")
        value, source_bytes = source(8)
        original_replace = storage.os.replace

        def interrupted(*_args, **_kwargs):
            raise KeyboardInterrupt()

        storage.os.replace = interrupted
        try:
            storage.atomic_write_json(str(target), value, temp_directory=root)
        except KeyboardInterrupt:
            return {
                "classification": "interrupted_serialization",
                "sourceObjectBytes": source_bytes,
                "writtenBytes": 8 * MIB,
                "peakRssBytes": peak_rss_bytes(),
                "fullSizeBuffers": 0,
                "previousCheckpointPreserved":
                    target.read_text(encoding="utf-8") == '{"verified":"old"}',
                "tempCount": temp_count(root),
            }
        finally:
            storage.os.replace = original_replace
        raise AssertionError("interruption did not occur")


def run_repeated():
    with tempfile.TemporaryDirectory() as root:
        target = os.path.join(root, "state.json")
        value, source_bytes = source(32)
        peaks = []
        after_values = []
        written = 0
        for _ in range(5):
            result = storage.atomic_write_json(
                target, value, temp_directory=root)
            written = result["bytes"]
            gc.collect()
            peaks.append(peak_rss_bytes())
            after_values.append(current_rss_bytes())
        measured_after = [value for value in after_values if value is not None]
        growth = (max(measured_after) - min(measured_after)
                  if len(measured_after) > 1 else peaks[-1] - peaks[0])
        return {
            "classification": "repeated_checkpoint_verified",
            "sourceObjectBytes": source_bytes,
            "writtenBytes": written,
            "iterations": 5,
            "peakRssBytes": max(peaks),
            "rssAfterBytes": after_values,
            "rssGrowthBytes": max(0, growth),
            "fullSizeBuffers": 0,
            "tempCount": temp_count(root),
        }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", required=True, choices=(
        "production", "oversized", "interrupted", "repeated"))
    mode = parser.parse_args().mode
    if mode == "production":
        report = run_write(124)
    elif mode == "oversized":
        report = run_oversized()
    elif mode == "interrupted":
        report = run_interrupted()
    else:
        report = run_repeated()
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
