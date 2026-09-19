"""Validate a reviewed export; --apply appends to the existing valuation DB."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import jp_market_valuation as valuation


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--csv', type=Path, required=True)
    parser.add_argument('--store', type=Path, required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    at = datetime.now(timezone.utc).isoformat()
    with args.csv.open('rb') as handle:
        raw = handle.read(2 * 1024 * 1024 + 1)
    rows = valuation.parse_export(raw, received_at=at)
    if args.apply:
        valuation.initialize(args.store)
        db = valuation._connect(args.store)
        try:
            db.execute('CREATE TABLE IF NOT EXISTS raw_exports(sha256 TEXT PRIMARY KEY, received_at TEXT NOT NULL, raw BLOB NOT NULL)')
            db.execute('INSERT OR IGNORE INTO raw_exports VALUES(?,?,?)', (rows[0]['sourceExportSha256'], at, raw))
        finally:
            db.close()
        for row in rows:
            valuation.append(args.store, row)
    print(json.dumps({'status': 'IMPORTED' if args.apply else 'VALIDATED_ONLY',
        'rows': len(rows), 'firstDate': rows[0]['date'], 'lastDate': rows[-1]['date'],
        'sourceExportSha256': rows[0]['sourceExportSha256'],
        'historicalVintageVerified': False, 'predictivePowerVerified': False}))


if __name__ == '__main__':
    main()
