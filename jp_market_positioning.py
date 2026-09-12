"""Normalize the official JPY-only legacy COT report without trading authority."""
import hashlib
import json
import re
from datetime import datetime, timezone
from html.parser import HTMLParser


class _ReportText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)


def normalize_cftc_jpy_report(raw: bytes, *, received_at: str) -> dict:
    if not isinstance(raw, bytes) or not 1 <= len(raw) <= 1024 * 1024:
        raise ValueError('bounded_cftc_report_required')
    received = datetime.fromisoformat(received_at.replace('Z', '+00:00'))
    if received.tzinfo is None:
        raise ValueError('actual_receipt_timezone_required')
    parser = _ReportText()
    parser.feed(raw.decode('utf-8', errors='strict'))
    text = ''.join(parser.parts).replace('\r', '')
    title = r'^JAPANESE YEN - CHICAGO MERCANTILE EXCHANGE\s+Code-097741\s*$'
    titles = list(re.finditer(title, text, re.M))
    if len(titles) != 1:
        raise ValueError('unique_jpy_futures_report_required')
    section = text[titles[0].end():]
    next_contract = re.search(r'^.*Code-\d{6}\s*$', section, re.M)
    if next_contract:
        section = section[:next_contract.start()]
    def single(pattern):
        rows = re.findall(pattern, section, re.M)
        if len(rows) != 1:
            raise ValueError('unambiguous_cftc_field_required')
        return rows[0]
    def report_date(value):
        month, day, year = map(int, value.split('/'))
        return datetime(2000 + year, month, day).date()
    day = report_date(single(r'^FUTURES ONLY POSITIONS AS OF (\d{2}/\d{2}/\d{2})\s*\|$'))
    if day > received.astimezone(timezone.utc).date():
        raise ValueError('future_position_date')
    if 'NON-COMMERCIAL' not in section or 'SPREADS' not in section:
        raise ValueError('legacy_trader_categories_required')
    interest = int(single(r'^\(CONTRACTS OF JPY 12,500,000\)\s+OPEN INTEREST:\s+([\d,]+)\s*$').replace(',', ''))
    balances = single(r'^COMMITMENTS\s*\n([^\n]+)')
    change_date, interest_delta, changes = single(r'^CHANGES FROM (\d{2}/\d{2}/\d{2}) \(CHANGE IN OPEN INTEREST:\s+(-?[\d,]+)\)\s*\n([^\n]+)')
    previous_day = report_date(change_date)
    if not previous_day < day:
        raise ValueError('prior_report_date_required')
    def nine_numbers(line):
        values = line.split()
        if len(values) != 9 or any(not re.fullmatch(r'-?(?:\d{1,3}(?:,\d{3})+|\d+)', value) for value in values):
            raise ValueError('nine_position_columns_required')
        return [int(value.replace(',', '')) for value in values]
    balances, changes = nine_numbers(balances), nine_numbers(changes)
    interest_delta = int(interest_delta.replace(',', ''))
    def reconcile(values, total):
        a, b, spreads, commercial_long, commercial_short, report_long, report_short, other_long, other_short = values
        return (a + spreads + commercial_long == report_long and
                b + spreads + commercial_short == report_short and
                report_long + other_long == total and report_short + other_short == total)
    if min(balances) < 0 or not reconcile(balances, interest) or not reconcile(changes, interest_delta):
        raise ValueError('cftc_position_totals_inconsistent')
    previous = [balance - change for balance, change in zip(balances, changes)]
    if min(previous) < 0 or not reconcile(previous, interest - interest_delta):
        raise ValueError('cftc_previous_totals_inconsistent')
    def row(values):
        return {'longContracts': values[0], 'shortContracts': values[1],
                'spreadContracts': values[2], 'netContracts': values[0] - values[1]}
    result = {
        'schemaVersion': 'jp-market-jpy-position-v1', 'status': 'AVAILABLE',
        'instrumentId': 'JPY', 'contractCode': '097741',
        'contractSizeJpy': 12500000, 'unit': 'CONTRACTS',
        'reportType': 'LEGACY_FUTURES_ONLY', 'traderCategory': 'NON_COMMERCIAL',
        'positionDate': day.isoformat(), 'previousPositionDate': previous_day.isoformat(),
        'current': row(balances), 'previous': row(previous), 'change': row(changes),
        'openInterestContracts': interest, 'openInterestChangeContracts': interest_delta,
        'publishedAt': None, 'receivedAt': received.astimezone(timezone.utc).isoformat(),
        'availableFrom': received.astimezone(timezone.utc).isoformat(),
        'availabilityBasis': 'ACTUAL_RECEIPT', 'publicationTimeVerified': False,
        'positionAgeCalendarDays': (received.astimezone(timezone.utc).date() - day).days,
        'sourceRef': 'https://www.cftc.gov/dea/futures/deacmesf.htm',
        'sourceResponseSha256': hashlib.sha256(raw).hexdigest(),
        'historicalVintageVerified': False, 'observesCurrentLivePositions': False,
        'validationStatus': 'DESCRIPTIVE_NOT_PREDICTIVE', 'actionAuthority': False,
    }
    economic = {key: result[key] for key in ('instrumentId', 'contractCode', 'reportType',
        'traderCategory', 'positionDate', 'previousPositionDate', 'current', 'previous',
        'change', 'openInterestContracts', 'openInterestChangeContracts')}
    result['reportId'] = hashlib.sha256(json.dumps(economic, sort_keys=True,
        separators=(',', ':'), allow_nan=False).encode()).hexdigest()
    return result


POSITION_SERIES = {
    'fx.jpy.speculative.long': 'longContracts',
    'fx.jpy.speculative.short': 'shortContracts',
    'fx.jpy.speculative.spread': 'spreadContracts',
    'fx.jpy.speculative.net': 'netContracts',
}


def ledger_candidates(report: dict, state: dict) -> list[dict]:
    """Reuse Market Ledger revisions/checkpoints without rebasing old receipts.

    A newly downloaded entire exchange report can change for another contract.
    JPY's economic report identity remains the same in that case. The original
    receipt is preserved; only a changed JPY report appends a new revision.
    """
    existing = {(row.get('seriesId'), (row.get('metadata') or {}).get('reportId'))
                for row in state.get('observations', [])
                if row.get('importId') not in set(state.get('rolledBackImports', []))}
    return [{
        'seriesId': series, 'periodEnd': report['positionDate'],
        'publishedAt': report['publishedAt'], 'availableFrom': report['availableFrom'],
        'observedAt': report['receivedAt'], 'value': report['current'][field],
        'unit': 'CONTRACTS', 'source': report['sourceRef'], 'sourceKind': 'official',
        'status': 'live', 'metadata': dict(report),
    } for series, field in POSITION_SERIES.items() if (series, report['reportId']) not in existing]


def latest_from_ledger(state: dict, *, cutoff: str) -> dict:
    """Return one complete four-series vintage known by the actual cutoff."""
    at = datetime.fromisoformat(cutoff.replace('Z', '+00:00'))
    if at.tzinfo is None:
        raise ValueError('cutoff_timezone_required')
    groups = {}
    rolled = set(state.get('rolledBackImports', []))
    for row in state.get('observations', []):
        if row.get('seriesId') not in POSITION_SERIES or row.get('importId') in rolled:
            continue
        try:
            known = [datetime.fromisoformat(row[key].replace('Z', '+00:00'))
                     for key in ('availableFrom', 'observedAt')]
            if any(value.tzinfo is None or value > at for value in known):
                continue
            report = row['metadata']
            if (report['reportType'] != 'LEGACY_FUTURES_ONLY' or report['traderCategory'] != 'NON_COMMERCIAL'
                    or report['contractCode'] != '097741' or report['instrumentId'] != 'JPY'
                    or row['unit'] != 'CONTRACTS' or row['periodEnd'] != report['positionDate']
                    or row['value'] != report['current'][POSITION_SERIES[row['seriesId']]]):
                continue
            receipt = datetime.fromisoformat(report['receivedAt'])
            if receipt.tzinfo is None or receipt > at or row['observedAt'] != report['receivedAt']:
                continue
            economic = {field: report[field] for field in ('instrumentId', 'contractCode', 'reportType',
                'traderCategory', 'positionDate', 'previousPositionDate', 'current', 'previous',
                'change', 'openInterestContracts', 'openInterestChangeContracts')}
            digest = hashlib.sha256(json.dumps(economic, sort_keys=True,
                separators=(',', ':'), allow_nan=False).encode()).hexdigest()
            if report['reportId'] != digest or report['sourceRef'] != 'https://www.cftc.gov/dea/futures/deacmesf.htm':
                continue
            key = (report['positionDate'], report['receivedAt'], report['reportId'])
            groups.setdefault(key, {})[row['seriesId']] = report
        except (KeyError, TypeError, ValueError):
            continue
    complete = [(key, rows) for key, rows in groups.items()
                if set(rows) == set(POSITION_SERIES)
                and all(value == next(iter(rows.values())) for value in rows.values())]
    if not complete:
        return {'schemaVersion': 'jp-market-jpy-position-v1', 'status': 'UNAVAILABLE',
                'reason': 'complete_received_report_not_available', 'actionAuthority': False}
    key, rows = max(complete, key=lambda item: (item[0][0], datetime.fromisoformat(item[0][1])))
    result = dict(next(iter(rows.values())))
    result['positionAgeCalendarDays'] = (at.astimezone(timezone.utc).date() -
                                      datetime.fromisoformat(key[0]).date()).days
    result['status'] = 'STALE' if result['positionAgeCalendarDays'] > 14 else 'AVAILABLE'
    result['storageBasis'] = 'EXISTING_MARKET_LEDGER'
    return result
