#!/usr/bin/env python3
"""Read a fixed window of the existing durable usage store; no API or writes.

Output is numeric/model metadata only, with unknown usage preserved. This
report does not assert invoice savings, quality parity or causal attribution.
"""
from datetime import datetime, timezone
from pathlib import Path
import argparse
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from argus_ai_usage_receipt import summarize, validate_receipt
from argus_ai_usage_store import read_page


def instant(value):
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('window_requires_timezone')
    return parsed.astimezone(timezone.utc)


def report(path, start, end):
    lower, upper = instant(start), instant(end)
    if lower >= upper:
        raise ValueError('invalid_window')
    watermark = None
    cache_groups, seen = {}, set()
    def selected():
        nonlocal watermark
        cursor = 0
        while True:
            page = read_page(path, after_sequence=cursor, through_sequence=watermark, limit=500)
            watermark = page['throughSequence']
            for item in page['rows']:
                row = item['receipt']
                if (row['feature'] == 'market_brief' and row['provider'] == 'openai'
                        and lower <= instant(row['startedAt']) < upper):
                    yield row
            if not page['hasMore']:
                return
            cursor = page['nextAfterSequence']
    def measured():
        for value in selected():
            row = validate_receipt(value)
            if row['callId'] not in seen:
                seen.add(row['callId'])
                key = (row['requestedModel'], row['returnedModel'])
                group = cache_groups.setdefault(key, {
                    'requestedModel': key[0], 'returnedModel': key[1], 'records': 0,
                    'knownCacheWriteInputTokens': 0, 'unknownCacheWriteRecords': 0})
                group['records'] += 1
                if row.get('cacheWriteInputTokens') is None:
                    group['unknownCacheWriteRecords'] += 1
                else:
                    group['knownCacheWriteInputTokens'] += row['cacheWriteInputTokens']
            yield row
    summary = summarize(measured())
    return {'schemaVersion':'argus-brief-cost-window-v1', 'startUtc':lower.isoformat(),
            'endUtcExclusive':upper.isoformat(), 'seconds':(upper-lower).total_seconds(),
            'throughSequence':watermark, 'summary':summary,
            'coverage':'all_committed_market_brief_openai_receipts_in_window',
            'status':'RECORDED_USAGE' if summary['uniqueReceipts'] else 'NO_RECORDED_GENERATION',
            'costBasis':'existing_normal_token_price_estimate_excludes_cache_discount_and_extra_charges',
            'cacheWrites': sorted(cache_groups.values(), key=lambda g: (g['requestedModel'] or '', g['returnedModel'] or '')),
            'cacheWriteFeeIncludedInEstimate': False,
            'qualityAcceptanceRate':'NOT_AVAILABLE_FROM_PROVIDER_RECEIPTS',
            'invoiceSavingsVerified':False, 'causalReductionVerified':False,
            'additionalAiCalls':0, 'providerFetches':0, 'applicationWrites':0}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--store', required=True)
    parser.add_argument('--start', required=True)
    parser.add_argument('--end', required=True)
    args = parser.parse_args()
    print(json.dumps(report(args.store, args.start, args.end), ensure_ascii=False, allow_nan=False))
