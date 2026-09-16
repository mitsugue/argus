#!/usr/bin/env python3
"""Offline arithmetic compatibility audit; never imports fixtures into production."""
from pathlib import Path
from decimal import Decimal, ROUND_HALF_UP
import argparse
import hashlib
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from jp_market_price_paths import index_valuation_scale, VALUATION_BASIS

MAX_BYTES = 1024 * 1024


def verify(path, *, checked_at):
    with Path(path).open("rb") as handle:
        raw = handle.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError('fixture_size_bound')
    pack = json.loads(raw)
    if (pack.get('handoff_context', {}).get('status_scope') != 'THIS_ATTACHMENT_ONLY'
            or pack.get('status', {}).get('production_import_enabled') is not False
            or pack.get('canonical_valuation', {}).get('per_basis') != 'INDEX_BASED'):
        raise ValueError('fixture_scope_or_definition_invalid')
    rows = pack.get('rows')
    if not isinstance(rows, list) or not 1 <= len(rows) <= 1000:
        raise ValueError('fixture_row_bound')
    results = []
    for row in rows:
        if (row.get('usage') != 'ARITHMETIC_FIXTURE_ONLY' or row.get('instrument_id') != 'NIKKEI_225'
                or row.get('per_basis') != 'INDEX_BASED' or row.get('probability') is not None):
            raise ValueError('fixture_row_scope_invalid')
        # This is today's isolated arithmetic fixture. checked_at is NOT a historical
        # publication timestamp, and none of these synthetic inputs leave this audit.
        value = {'instrumentId': 'NIKKEI_225_INDEX', 'basis': VALUATION_BASIS,
            'currency': 'JPY', 'date': row['trade_date'], 'indexClose': row['close_jpy'],
            'per': row['per_index'], 'sourceRef': 'arithmetic-fixture:' + row['record_id'],
            'availableFrom': checked_at, 'knownAt': checked_at, 'publishedAt': None}
        args = {'cutoff': checked_at, 'anchor_date': row['trade_date'], 'anchor_price': row['close_jpy']}
        actual = index_valuation_scale(value, **args)
        if actual['status'] != 'AVAILABLE':
            raise ValueError('runtime_arithmetic_unavailable')
        rounded = Decimal(str(actual['eps'])).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)
        expected = (Decimal(str(row['close_jpy'])) / Decimal(str(row['per_index']))).quantize(
            Decimal('.01'), rounding=ROUND_HALF_UP)
        if rounded != expected or rounded != Decimal(str(row['eps_submitted_jpy'])):
            raise ValueError('runtime_eps_arithmetic_mismatch')
        for invalid in ({**value, 'basis':'WEIGHTED_AVERAGE'}, {**value, 'per':0},
                        {**value, 'date':'1900-01-01'}, {**value, 'availableFrom':None,'knownAt':None}):
            if index_valuation_scale(invalid, **args)['status'] != 'UNAVAILABLE':
                raise ValueError('runtime_definition_or_time_guard_failed')
        results.append({'recordId': row['record_id'], 'tradeDate':row['trade_date'],
            'runtimeEpsRounded':str(rounded), 'arithmeticStatus':'MATCH',
            'primaryStatusFromAttachment':row['primary_status'],
            'historicalPublicationVerified':False, 'backtestEligible':False})
    return {'schemaVersion':'argus-valuation-arithmetic-audit-v1', 'packId':pack['pack_id'],
        'attachmentSha256':hashlib.sha256(raw).hexdigest(), 'checkedAt':checked_at,
        'scope':'ATTACHMENT_ARITHMETIC_AND_EXISTING_RUNTIME_COMPATIBILITY_ONLY',
        'engine':'jp_market_price_paths.index_valuation_scale', 'status':'PASS',
        'arithmeticMatches':len(results), 'rows':results, 'primarySourcesRefetched':False,
        'productionImportPerformed':False, 'existingAssetStatusModified':False,
        'forecastValidationPerformed':False, 'probability':None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--anchors', type=Path, required=True)
    parser.add_argument('--checked-at', required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    result = verify(args.anchors, checked_at=args.checked_at)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({key:result[key] for key in ('status','packId','arithmeticMatches','productionImportPerformed')}))


if __name__ == '__main__':
    main()
