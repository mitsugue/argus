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
