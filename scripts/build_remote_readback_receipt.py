#!/usr/bin/env python3
"""Create a bounded Remote Journal read-back proof from a durable snapshot."""
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import argus_remote_journal


def main(argv=None):
    args = list(argv if argv is not None else sys.argv[1:])
    if len(args) != 2:
        raise SystemExit("usage: build_remote_readback_receipt.py INPUT OUTPUT")
    source, destination = map(pathlib.Path, args)
    blob = json.loads(source.read_text(encoding="utf-8"))
    receipt = argus_remote_journal.compact_readback_snapshot(blob)
    destination.write_text(
        json.dumps(receipt, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8")


if __name__ == "__main__":
    main()
