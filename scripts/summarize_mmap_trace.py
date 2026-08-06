#!/usr/bin/env python3
"""Summarize test-only strace mmap lifecycle without publishing raw paths."""
from __future__ import annotations

import argparse
import json
import pathlib
import re

CALL = re.compile(
    r"^(?P<time>\d+(?:\.\d+)?)\s+"
    r"(?P<call>mmap2?|munmap|mremap|brk)\((?P<args>.*)\)\s+=\s+"
    r"(?P<result>\S+)")


def _redact_args(args):
    args = re.sub(r"/[^,\])]+/([^,\])]+)", r"<file>/\1", args)
    args = re.sub(r"v2-generation-[0-9a-f]{32}",
                  "v2-generation-<id>", args)
    return args


def summarize(paths):
    live = {}
    created = unmapped = remapped = brk = 0
    creators = []
    for path in paths:
        process = path.name.rsplit(".", 1)[-1]
        for line in path.read_text(errors="replace").splitlines():
            match = CALL.match(line)
            if not match:
                continue
            call, args, result = (match["call"], match["args"],
                                  match["result"])
            if call.startswith("mmap") and result.startswith("0x"):
                created += 1
                size_match = re.match(r"[^,]+,\s*(\d+)", args)
                size = int(size_match.group(1)) if size_match else None
                live[(process, result)] = {"process": process,
                                            "address": result,
                                            "requestedBytes": size,
                                            "arguments": _redact_args(args)}
                creators.append(live[(process, result)])
            elif call == "munmap" and result == "0":
                unmapped += 1
                address = args.split(",", 1)[0].strip()
                live.pop((process, address), None)
            elif call == "mremap":
                remapped += 1
            elif call == "brk":
                brk += 1
    persistent = list(live.values())
    return {"schemaVersion": "argus-mmap-syscall-trace-v1",
            "traceProcesses": sorted({row["process"] for row in creators}),
            "mappingsCreated": created, "mappingsUnmapped": unmapped,
            "mappingsRemapped": remapped, "brkCalls": brk,
            "persistentMappings": len(persistent),
            "persistentAnonymousMappings": sum(
                "MAP_ANONYMOUS" in row["arguments"] for row in persistent),
            "persistentFileMappings": sum(
                "MAP_ANONYMOUS" not in row["arguments"] for row in persistent),
            "creationSources": sorted({
                "anonymous_allocator_candidate" if "MAP_ANONYMOUS" in
                row["arguments"] else "file_backed_mmap"
                for row in creators}),
            "persistent": persistent}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-dir", required=True, type=pathlib.Path)
    parser.add_argument("--output", required=True, type=pathlib.Path)
    args = parser.parse_args()
    report = summarize(sorted(args.trace_dir.glob("mmap-trace*")))
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
