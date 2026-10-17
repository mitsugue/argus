#!/usr/bin/env python3
"""Publish a bounded, replaceable lookup from already committed predictions.

Run after the canonical ledger Git push. This contains original sealed pairs
for retrieval; it never scores a forecast, rewrites the ledger, or calls AI.
"""
import argparse
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import argus_event_prediction_results as results
from scripts import run_prediction_ledger as runner


def export(ledger_root, output, *, source_commit):
    root, target = Path(ledger_root).resolve(), Path(output)
    if not re.fullmatch(r'[a-f0-9]{40}', source_commit):
        raise ValueError('event_result_source_commit_required')
    if target.is_symlink() or target.resolve().is_relative_to(root):
        raise ValueError('event_result_output_must_not_replace_canonical_data')
    def read_head():
        with (root / 'commit-head.json').open('rb') as source:
            raw = source.read(runner.MAX_COMMIT_HEAD_BYTES + 1)
        if len(raw) > runner.MAX_COMMIT_HEAD_BYTES:
            raise ValueError('event_result_commit_head_bound')
        return raw
    before = read_head()
    package = results.load_recent_pairs(root)
    if read_head() != before:
        raise ValueError('event_result_source_changed')
    package['sourceCommit'] = source_commit
    package['rebuildable'] = True
    runner._atomic_write(target, package, maximum=results.MAX_PAIR_BYTES + 32 * 1024,
                         overflow_error='event_result_export_bound')
    return {key: value for key, value in package.items() if key != 'pairs'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ledger-root', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--source-commit', required=True)
    args = parser.parse_args()
    import json
    print(json.dumps(export(args.ledger_root, args.output, source_commit=args.source_commit)))


if __name__ == '__main__':
    main()
