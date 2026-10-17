#!/usr/bin/env python3
"""Secret-safe top-level size inventory for an ARGUS checkpoint snapshot."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


def canonical_chunks(value):
    encoder = json.JSONEncoder(
        ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    for text in encoder.iterencode(value):
        yield text.encode("utf-8")


def serialized_stats(value):
    digest = hashlib.sha256()
    size = 0
    for chunk in canonical_chunks(value):
        size += len(chunk)
        digest.update(chunk)
    return size, digest.hexdigest()


def deep_size(value) -> int:
    seen = set()

    def visit(item):
        identity = id(item)
        if identity in seen:
            return 0
        seen.add(identity)
        size = sys.getsizeof(item)
        if isinstance(item, dict):
            size += sum(visit(key) + visit(child)
                        for key, child in item.items())
        elif isinstance(item, (list, tuple, set)):
            size += sum(visit(child) for child in item)
        return size

    return visit(value)


def item_count(value) -> int:
    if isinstance(value, (dict, list, tuple, set)):
        return len(value)
    return 1 if value is not None else 0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("checkpoint")
    args = parser.parse_args()
    source = Path(args.checkpoint)
    blob = json.loads(source.read_text(encoding="utf-8"))
    rows = []
    hashes = {}
    for key, value in blob.items():
        serialized, digest = serialized_stats(value)
        row = {
            "section": key,
            "serializedBytes": serialized,
            "itemCount": item_count(value),
            "approximatePythonBytes": deep_size(value),
            "sha256": digest,
        }
        rows.append(row)
        hashes.setdefault(digest, []).append(key)
    total = sum(row["serializedBytes"] for row in rows)
    for row in rows:
        row["percentage"] = round(
            100 * row["serializedBytes"] / max(1, total), 4)
    report = {
        "sourceBytes": source.stat().st_size,
        "sectionSerializedBytes": total,
        "approximatePythonBytes": deep_size(blob),
        "sectionCount": len(rows),
        "sections": sorted(
            rows, key=lambda row: row["serializedBytes"], reverse=True),
        "duplicateSectionGroups": [
            names for names in hashes.values() if len(names) > 1],
    }
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
