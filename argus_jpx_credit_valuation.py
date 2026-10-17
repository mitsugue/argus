"""Auditable valuation P/L from official two-market margin workbook inputs.

This adapter does not collect, publish, change a sign rule or claim forecast
accuracy. Native amounts are JPY millions and shares are thousands; using the
same units throughout the official equation cancels the share conversion.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

METHOD_VERSION = 'jpx-credit-valuation-v1'
INPUTS = ('buyAmountMillionJpy', 'matchedThousandShares',
          'jsfFinanceThousandShares', 'ownFinanceThousandShares',
          'jsfFinanceMillionJpy', 'ownFinanceMillionJpy')
FORMULA_SOURCE = 'https://www.jpx.co.jp/glossary/ha/387.html'


def _number(value):
    if isinstance(value, bool):
        raise ValueError('credit_valuation_invalid_input')
    try:
        number = Decimal(str(value).replace(',', '').strip())
    except InvalidOperation:
        raise ValueError('credit_valuation_invalid_input') from None
    if not number.is_finite() or not 0 <= number <= Decimal("1e15"):
        raise ValueError('credit_valuation_invalid_input')
    return number


def calculate(inputs):
    """Loss is negative, profit positive; retain inputs before display rounding."""
    if not isinstance(inputs, dict) or set(inputs) != set(INPUTS):
        raise ValueError('credit_valuation_input_set')
    values = {key: _number(inputs[key]) for key in INPUTS}
    buy = values['buyAmountMillionJpy']
    shares = values['jsfFinanceThousandShares'] + values['ownFinanceThousandShares']
    funds = values['jsfFinanceMillionJpy'] + values['ownFinanceMillionJpy']
    if buy == 0 or shares == 0:
        raise ValueError('credit_valuation_zero_denominator')
    market_value = funds / shares * values['matchedThousandShares'] + funds
    percent = (market_value - buy) / buy * 100
    return {'methodVersion': METHOD_VERSION, 'formulaSource': FORMULA_SOURCE,
            'inputs': {key: float(value) for key, value in values.items()},
            'value': float(percent), 'unit': 'percent',
            'signConvention': 'loss_negative_profit_positive',
            'classification': 'derived_from_official_workbook'}


def extract(grid):
    """Distinguish financing from shares lent, weekly changes and Tokyo only."""
    from scripts.jpx_credit_weekly import parse_sheet
    balances = parse_sheet(grid)
    text = [[str(x or '').strip() for x in row] for row in grid]
    current = any('Total Outstanding Margin Trading' in x for row in text for x in row)
    def one(label):
        hits = [i for i, row in enumerate(text)
                if any(x.startswith(label) for x in row[:6])]
        if len(hits) != 1:
            raise ValueError('credit_valuation_layout_ambiguous')
        return hits[0]
    def cell(row, col):
        try:
            return _number(grid[row][col])
        except IndexError:
            raise ValueError('credit_valuation_layout_incomplete') from None
    def share_row(row, column):
        if not any('株数' in x and 'Shs.' in x for x in text[row]):
            raise ValueError('credit_valuation_share_row')
        return cell(row, column)
    def amount_row(row, column):
        if not any('金額' in x and 'Val.' in x for x in text[row]):
            raise ValueError('credit_valuation_amount_row')
        return cell(row, column)
    if not any('千株' in x and '百万円' in x for row in text[:6] for x in row):
        raise ValueError('credit_valuation_unit')
    if current:
        col = next(i for row in text[:8] for i, x in enumerate(row) if 'Tokyo&Nagoya' in x)
        matched = one('社内対当')
        jsf = one('貸借取引残高')
        own = one('自己貸株・自己融資')
        values = (share_row(matched, col), share_row(jsf, col + 2), share_row(own, col + 2),
                  amount_row(jsf + 1, col + 2), amount_row(own + 1, col + 2))
    else:
        header = one('貸借取引残高')
        if (len(text[header]) <= 11 or '自己融資' not in text[header][11]
                or len(text[header + 1]) <= 7 or '融資' not in text[header + 1][7]):
            raise ValueError('credit_valuation_financing_columns')
        markets = [i for i in range(header + 1, min(header + 6, len(text)))
                   if any('二市場計' in x for x in text[i])]
        if len(markets) != 1:
            raise ValueError('credit_valuation_two_market_row')
        row = markets[0]
        values = (share_row(row, 3), share_row(row, 7), share_row(row, 11),
                  amount_row(row + 1, 7), amount_row(row + 1, 11))
    inputs = dict(zip(INPUTS, [Decimal(balances['longJpy']) / 1000000, *values], strict=True))
    result = calculate(inputs)
    result['periodEnd'] = balances['periodEnd']
    return result


def extract_monthly_text(text):
    """Read the 22-column two-market block of an official monthly PDF page.

    This yields retrospective observations only. It does not invent historical
    publication/receipt timestamps from the month printed on the report.
    Layout changes or missing columns fail rather than shifting the equation.
    """
    import re
    from datetime import date
    if not isinstance(text, str) or len(text) > 2 * 1024 * 1024:
        raise ValueError('credit_valuation_monthly_size')
    if not all(label in text for label in ('信用取引現在高', '社内対当', '融資', '千株', '百万円')):
        raise ValueError('credit_valuation_monthly_headers')
    roles = ('委託', '自己 Members', '合計', '社内対当', '貸借取引残高', '自己貸株', '自己融資')
    headers = [line for line in text.splitlines() if all(role in line for role in roles)]
    if len(headers) != 1 or [headers[0].index(role) for role in roles] != sorted(
            headers[0].index(role) for role in roles):
        raise ValueError('credit_valuation_monthly_column_headers')
    active = False
    year = month = None
    out = []
    seen = set()
    for line in text.splitlines():
        line = line.strip()
        if '東京' in line and '名古屋' in line:
            if active:
                raise ValueError('credit_valuation_monthly_market_ambiguous')
            active = True
            continue
        if not active:
            continue
        if line.startswith(('注:', '注：', 'Notes:', '㈱')):
            break
        stamp = re.fullmatch(r'(?:\d{1,2}\s*\((20\d{2})\)|(20\d{2}))', line)
        if stamp:
            year = int(stamp.group(1) or stamp.group(2)); month = None
            continue
        matched = re.match(r'^(?:(\d{1,2})\.\s*)?(\d{1,2})\s+(.+)$', line)
        if not matched:
            continue
        if matched.group(1):
            next_month = int(matched.group(1))
            if month == 12 and next_month == 1 and year is not None:
                year += 1
            month = next_month
        values = matched.group(3).split()
        if year is None or month is None or len(values) != 22:
            raise ValueError('credit_valuation_monthly_columns')
        period = date(year, month, int(matched.group(2))).isoformat()
        if period in seen:
            raise ValueError('credit_valuation_monthly_duplicate_date')
        # Validate every numeric column to catch extraction damage, including
        # unused lending/change fields, before selecting the financing values.
        numbers = [None if value == '-' else _number(value) for value in values]
        inputs = dict(zip(INPUTS, [numbers[i] for i in (11, 13, 16, 20, 17, 21)], strict=True))
        if any(value is None for value in inputs.values()):
            result = {'methodVersion': METHOD_VERSION, 'formulaSource': FORMULA_SOURCE,
                      'inputs': {key: None if value is None else float(value)
                                 for key, value in inputs.items()},
                      'value': None, 'unit': 'percent',
                      'signConvention': 'loss_negative_profit_positive',
                      'classification': 'official_inputs_not_published',
                      'missingInputs': [key for key, value in inputs.items() if value is None]}
        else:
            result = calculate(inputs)
        result.update(periodEnd=period, historicalVintageVerified=False,
                      shortBalanceJpy=(None if numbers[9] is None else float(numbers[9] * 1000000)),
                      longBalanceJpy=(None if numbers[11] is None else float(numbers[11] * 1000000)))
        out.append(result); seen.add(period)
    if not active or not out:
        raise ValueError('credit_valuation_monthly_rows_missing')
    if [r['periodEnd'] for r in out] != sorted(r['periodEnd'] for r in out):
        raise ValueError('credit_valuation_monthly_date_order')
    return out


def ledger_observation(result, *, url, sha256, received_at, retrospective=False):
    """Same existing series, actual receipt, original six inputs; no PIT guess."""
    from copy import deepcopy
    from datetime import date, datetime
    period = date.fromisoformat(result['periodEnd']).isoformat()
    received = datetime.fromisoformat(received_at.replace('Z', '+00:00'))
    if received.tzinfo is None or received.date() < date.fromisoformat(period):
        raise ValueError('credit_valuation_receipt')
    calculation = {key: deepcopy(result[key]) for key in
                   ('methodVersion', 'formulaSource', 'inputs', 'value', 'unit',
                    'signConvention', 'classification')}
    if 'missingInputs' in result:
        calculation['missingInputs'] = list(result['missingInputs'])
    metadata = {'valuationCalculation': calculation,
                'sourceDocument': {'url': url, 'sha256': sha256, 'receivedAt': received_at},
                'availabilityBasis': 'ACTUAL_RECEIPT',
                'signConvention': 'negative_is_loss',
                'publicationVerified': False,
                'historicalVintageVerified': False,
                'retrospective': bool(retrospective)}
    row = {'seriesId': 'credit.valuation_loss_pct', 'periodEnd': period,
           'publishedAt': '', 'availableFrom': received_at, 'observedAt': received_at,
           'value': result['value'], 'unit': 'percent', 'sourceKind': 'derived',
           'status': 'live' if result['value'] is not None else 'missing',
           'source': f'JPX official inputs | {url} | sha256={sha256}',
           'metadata': metadata}
    validate_ledger_observation(row)
    return row


def validate_ledger_observation(row):
    """Only audited official-input calculations may use the display route."""
    import math
    import re
    from datetime import date, datetime
    from urllib.parse import urlparse
    if (row.get('seriesId') != 'credit.valuation_loss_pct' or row.get('unit') != 'percent'
            or row.get('sourceKind') != 'derived'):
        raise ValueError('credit_valuation_row_kind')
    metadata = row.get('metadata')
    if not isinstance(metadata, dict):
        raise ValueError('credit_valuation_metadata')
    document = metadata.get('sourceDocument')
    if not isinstance(document, dict):
        raise ValueError('credit_valuation_source')
    url = document.get('url')
    if not isinstance(url, str):
        raise ValueError('credit_valuation_source')
    parsed = urlparse(url)
    if (parsed.scheme != 'https' or parsed.netloc != 'www.jpx.co.jp'
            or parsed.query or parsed.fragment or '..' in parsed.path
            or not ((parsed.path.startswith('/markets/statistics-equities/margin/tvdivq0000001rk9-att/')
                     and parsed.path.endswith(('.xls', '.xlsx')))
                    or (parsed.path.startswith('/markets/statistics-equities/monthly/')
                        and parsed.path.endswith('.pdf')))):
        raise ValueError('credit_valuation_source')
    digest = document.get('sha256')
    if not isinstance(digest, str) or not re.fullmatch('[0-9a-f]{64}', digest):
        raise ValueError('credit_valuation_source_hash')
    if row.get('source') != f'JPX official inputs | {url} | sha256={digest}':
        raise ValueError('credit_valuation_source_identity')
    try:
        receipt = datetime.fromisoformat(document['receivedAt'].replace('Z', '+00:00'))
        available = datetime.fromisoformat(row['availableFrom'].replace('Z', '+00:00'))
        observed = datetime.fromisoformat(row['observedAt'].replace('Z', '+00:00'))
        period = date.fromisoformat(row['periodEnd'])
    except (KeyError, TypeError, ValueError, AttributeError):
        raise ValueError('credit_valuation_receipt') from None
    if (any(x.tzinfo is None for x in (receipt, available, observed))
            or receipt != available or receipt != observed or receipt.date() < period
            or row.get('publishedAt') or metadata.get('publicationVerified') is not False
            or metadata.get('historicalVintageVerified') is not False
            or metadata.get('availabilityBasis') != 'ACTUAL_RECEIPT'
            or metadata.get('signConvention') != 'negative_is_loss'
            or not isinstance(metadata.get('retrospective'), bool)):
        raise ValueError('credit_valuation_receipt')
    calc = metadata.get('valuationCalculation')
    fields = {'methodVersion', 'formulaSource', 'inputs', 'value', 'unit',
              'signConvention', 'classification'}
    if isinstance(calc, dict) and calc.get('classification') == 'official_inputs_not_published':
        fields.add('missingInputs')
    if not isinstance(calc, dict) or set(calc) != fields:
        raise ValueError('credit_valuation_calculation')
    inputs = calc.get('inputs')
    if not isinstance(inputs, dict) or set(inputs) != set(INPUTS):
        raise ValueError('credit_valuation_input_set')
    missing = [key for key in INPUTS if inputs[key] is None]
    if missing:
        expected = {'methodVersion': METHOD_VERSION, 'formulaSource': FORMULA_SOURCE,
                    'inputs': {key: None if value is None else float(_number(value))
                               for key, value in inputs.items()}, 'value': None,
                    'unit': 'percent', 'signConvention': 'loss_negative_profit_positive',
                    'classification': 'official_inputs_not_published', 'missingInputs': missing}
    else:
        expected = calculate(inputs)
    if calc != expected or isinstance(calc.get('value'), bool):
        raise ValueError('credit_valuation_calculation')
    value = row.get('value')
    if missing:
        if value is not None or row.get('status') not in ('missing', 'revised'):
            raise ValueError('credit_valuation_value')
        return expected
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) \
            or not math.isclose(value, expected['value'], rel_tol=0, abs_tol=1e-10):
        raise ValueError('credit_valuation_value')
    return expected


def audited_ledger_observation(row):
    try:
        validate_ledger_observation(row)
        return True
    except (ValueError, TypeError, AttributeError):
        return False


def ledger_observation_digest(row):
    """Bind saved inputs and receipt without repeating every workbook in the UI."""
    import hashlib
    import json
    validate_ledger_observation(row)
    content = {key: row.get(key) for key in
               ('seriesId', 'periodEnd', 'publishedAt', 'availableFrom', 'observedAt',
                'value', 'unit', 'source', 'sourceKind', 'metadata')}
    # The ledger normalizes an unknown publication stamp from empty to None.
    content['publishedAt'] = content['publishedAt'] or None
    return hashlib.sha256(json.dumps(content, sort_keys=True, ensure_ascii=False,
                                    allow_nan=False, separators=(',', ':')).encode()).hexdigest()


def extend_audited_credit_inputs(base, by_series):
    """Pass only verified official-input calculations to the existing D01 seam."""
    from copy import deepcopy
    out = list(base)
    for row in by_series.get('credit.valuation_loss_pct', []) or []:
        if audited_ledger_observation(row):
            out.append(deepcopy(row))
    return out
