"""Official Nikkei 225 price adjustment factors from the owner's file (2026-10-20).

The owner saves Nikkei's member list with its 株価換算係数 column from a
browser and places it on the server as a secret file, like the month-end
weight table. Nikkei marks the file as its copyrighted material: it never
leaves the process (not logged, not served, not committed); only its date,
member count and digest are reported.

With these factors the start session's official close implies the divisor,
and the end session is reproduced exactly while no factor or divisor changes
inside the period (checked on 2026-10-07: the official close to the sen).

Pure functions: no clock, no store, no network.
"""
import csv
from decimal import Decimal, InvalidOperation
import io
import re
from datetime import date
from typing import Any, Dict

HEADER = ('対象日付', 'コード', '銘柄名', '株価換算係数')
MEMBERS = 225
MAX_BYTES = 512 * 1024
FACTOR_BASIS = 'OFFICIAL_PRICE_ADJUSTMENT_FACTOR'


def decode(raw: bytes) -> str:
    if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_BYTES:
        raise ValueError('price_factor_file_bound')
    try:
        return raw.decode('cp932')
    except UnicodeDecodeError:
        return raw.decode('utf-8-sig')


def looks_like(text: str) -> bool:
    """Cheap check before parsing: the header names the factor column."""
    first = (text.splitlines() or [''])[0]
    return '株価換算係数' in first and 'コード' in first


def parse(text: str) -> Dict[str, Any]:
    """{'asOf', 'factors': {code: decimal string}, 'members'} or ValueError.

    The whole list of one date or nothing: an unexpected header, a second
    date, a duplicate or malformed code, a non-positive factor or a member
    count other than 225 rejects the file. The trailing copyright note (one
    column) ends the table."""
    rows = list(csv.reader(io.StringIO(text)))
    if not rows or tuple(cell.strip() for cell in rows[0][:4]) != HEADER:
        raise ValueError('price_factor_header')
    factors, days = {}, set()
    for row in rows[1:]:
        if len(row) < 4:
            if any(cell.strip() for cell in row) and not factors:
                raise ValueError('price_factor_rows_missing')
            break                                        # the copyright note
        day_text, code, _, factor_text = (cell.strip() for cell in row[:4])
        if not re.fullmatch(r'\d{4}/\d{2}/\d{2}', day_text):
            raise ValueError('price_factor_date')
        day = date(int(day_text[:4]), int(day_text[5:7]), int(day_text[8:10])).isoformat()
        if not re.fullmatch(r'[0-9A-Z]{4}', code):
            raise ValueError('price_factor_code')
        if code in factors:
            raise ValueError('price_factor_duplicate')
        try:
            factor = Decimal(factor_text)
        except InvalidOperation:
            raise ValueError('price_factor_value') from None
        if not factor.is_finite() or factor <= 0:
            raise ValueError('price_factor_value')
        factors[code] = str(factor)
        days.add(day)
    if len(days) != 1:
        raise ValueError('price_factor_single_date')
    if len(factors) != MEMBERS:
        raise ValueError('price_factor_member_count')
    return {'asOf': days.pop(), 'factors': factors, 'members': len(factors), 'factorBasis': FACTOR_BASIS}


def applies(table: Dict[str, Any], *, start: str, members_start, members_end) -> bool:
    """Use the official factors only from their date and for exactly their members."""
    codes = set(table.get('factors') or ())
    return (bool(codes) and table.get('asOf', '9999') <= start
            and set(members_start) == codes and set(members_end) == codes)
