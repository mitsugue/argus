"""Bounded dated issue classifications on the existing master collection lane."""
from copy import deepcopy
from datetime import date, datetime
import hashlib
import json
import re

MAX_EDITIONS = 2
MAX_ROWS = 6000
MAX_PAGES = 40
MAX_PAGE_BYTES = 2 * 1024 * 1024
TTL_SECONDS = 24 * 3600
SOURCE = 'J-Quants V2 equities/master'


def _date(value):
    if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
        raise ValueError('classification_date_invalid')
    return value


def lookup(cache, symbol, day):
    """Read only; an expired successful receipt keeps its original source time."""
    edition = (cache.get('comparisonByDate') or {}).get(day) or {}
    row = (edition.get('rows') or {}).get(symbol)
    return deepcopy(row) if isinstance(row, dict) and row.get('effectiveDate') == day else None


def editions(cache):
    return {day: entry['rows'] for day, entry in (cache.get('comparisonByDate') or {}).items()
            if isinstance(entry, dict) and isinstance(entry.get('rows'), dict)}


def warm(cache, days, *, get, base, headers, now_iso, monotonic, wall_time, deadline):
    """No retry, no new scheduler/store: publish only a complete dated response."""
    if not isinstance(days, (tuple, list)) or not 1 <= len(days) <= MAX_EDITIONS:
        raise ValueError('classification_date_count')
    days = list(dict.fromkeys(_date(day) for day in days))
    pages = 0; failures = {}; available = []
    for day in days:
        previous = (cache.get('comparisonByDate') or {}).get(day) or {}
        if previous.get('rows') and wall_time() < previous.get('expires', 0):
            available.append(day)
            continue
        try:
            rows = {}; token = None; seen_tokens = set(); complete = False
            while pages < MAX_PAGES:
                remaining = deadline - monotonic()
                if remaining <= 0: raise ValueError('classification_deadline')
                params = {'date': day}
                if token is not None: params['pagination_key'] = token
                pages += 1
                with get(base + '/equities/master', headers=headers, params=params,
                         timeout=(min(5, remaining), min(12, remaining)),
                         stream=True, allow_redirects=False) as response:
                    if response.status_code != 200: raise ValueError('classification_http')
                    parts = []; size = 0
                    for part in response.iter_content(32768):
                        if monotonic() >= deadline: raise ValueError('classification_deadline')
                        size += len(part)
                        if size > MAX_PAGE_BYTES: raise ValueError('classification_page_bound')
                        parts.append(part)
                body = json.loads(b''.join(parts))
                items = body.get('data')
                if not isinstance(items, list) or not items:
                    raise ValueError('classification_empty')
                received = now_iso()
                if datetime.fromisoformat(received.replace('Z', '+00:00')).tzinfo is None:
                    raise ValueError('classification_receipt')
                for item in items:
                    if not isinstance(item, dict) or item.get('Date') != day:
                        raise ValueError('classification_response_date')
                    code = item.get('Code')
                    if not isinstance(code, str) or not re.fullmatch(r'[0-9][0-9A-Z]{3}[0-9]?', code):
                        raise ValueError('classification_code')
                    if len(code) == 5 and code[-1] != '0': continue
                    symbol = code[:4]
                    if symbol in rows: raise ValueError('classification_duplicate')
                    sector = item.get('S17');subsector = item.get('S33')
                    if sector is None: sector = ''
                    if not isinstance(sector, str) or not re.fullmatch(r'[0-9]{0,2}', sector):
                        raise ValueError('classification_sector')
                    if subsector is not None and (not isinstance(subsector, str)
                            or not re.fullmatch(r'[0-9]{0,4}', subsector)):
                        raise ValueError('classification_subsector')
                    rows[symbol] = {'sector17Code': sector, 'sector33Code': subsector,
                        'effectiveDate': day, 'receivedAt': received, 'source': SOURCE}
                    if len(rows) > MAX_ROWS: raise ValueError('classification_row_bound')
                token = body.get('pagination_key')
                if token is None or token == '':
                    complete = True
                    break
                if not isinstance(token, str) or len(token) > 4096 or token in seen_tokens:
                    raise ValueError('classification_pagination')
                seen_tokens.add(token)
            if not complete or not rows: raise ValueError('classification_incomplete')
            digest = hashlib.sha256(json.dumps(rows, ensure_ascii=False, sort_keys=True,
                separators=(',', ':'), allow_nan=False).encode()).hexdigest()
            for row in rows.values(): row['sourceSnapshotSha256'] = digest
            updated = dict(cache.get('comparisonByDate') or {})
            updated.pop(day, None)
            updated[day] = {'rows': rows, 'expires': wall_time() + TTL_SECONDS,
                            'sourceSnapshotSha256': digest}
            cache['comparisonByDate'] = dict(list(updated.items())[-MAX_EDITIONS:])
            available.append(day)
        except Exception as exc:
            known = {'classification_deadline','classification_http','classification_page_bound',
                     'classification_empty','classification_response_date','classification_code',
                     'classification_duplicate','classification_sector','classification_subsector','classification_receipt',
                     'classification_row_bound','classification_pagination','classification_incomplete'}
            failures[day] = str(exc) if isinstance(exc, ValueError) and str(exc) in known else 'classification_unavailable'
    return {'status': 'AVAILABLE' if not failures else 'PARTIAL', 'requestedDates': days,
            'availableDates': available, 'failures': failures, 'pages': pages}
