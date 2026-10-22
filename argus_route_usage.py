"""Calls per route per UTC day, kept across restarts (2026-10-22 owner decision).

Retiring a route was decided from "no caller in the repository", which missed
the six-hourly smoke test and could not see callers outside the repository
(the EC2 bridge, other tools). This counts what actually arrives: the matched
route rule (never the raw path or query, so no symbol, id or token is kept),
the method, the status class and whether the caller looked like a browser.
Nothing here blocks or changes a request. Pure functions; the caller holds the
lock and reads and writes the file.
"""
from typing import Any, Dict, Iterable, Optional

SCHEMA = 'route-usage-v1'
KEEP_DAYS = 35
MAX_KEYS_PER_DAY = 600
OTHER_KEY = '<other> *'
FILENAME = 'route_usage.json'
_FIELDS = ('calls', 'ok', 'clientError', 'serverError', 'browser', 'other')


def empty() -> Dict[str, Any]:
    return {'schemaVersion': SCHEMA, 'days': {}}


def parse(value: Any) -> Dict[str, Any]:
    """A validated state; anything malformed starts empty rather than guessing."""
    state = empty()
    if not isinstance(value, dict) or value.get('schemaVersion') != SCHEMA or not isinstance(value.get('days'), dict):
        return state
    for day, rows in sorted(value['days'].items())[-KEEP_DAYS:]:
        if not (isinstance(day, str) and len(day) == 10 and isinstance(rows, dict)):
            continue
        kept = {}
        for key, row in list(rows.items())[:MAX_KEYS_PER_DAY]:
            if isinstance(key, str) and len(key) <= 220 and isinstance(row, dict) and \
                    all(type(row.get(f, 0)) is int and row.get(f, 0) >= 0 for f in _FIELDS):
                kept[key] = {f: int(row.get(f, 0)) for f in _FIELDS}
        state['days'][day] = kept
    return state


def caller_kind(user_agent: Optional[str]) -> str:
    """'browser' for a browser's user agent, 'other' for scripts, monitors and bridges."""
    return 'browser' if 'Mozilla/' in str(user_agent or '') else 'other'


def note(state: Dict[str, Any], *, day: str, rule: Optional[str], method: str, status: int, caller: str) -> None:
    days = state['days']
    rows = days.setdefault(day, {})
    key = f"{str(rule or '<unmatched>')[:200]} {str(method or '').upper()[:10]}"
    if key not in rows and len(rows) >= MAX_KEYS_PER_DAY:
        key = OTHER_KEY
    row = rows.setdefault(key, dict.fromkeys(_FIELDS, 0))
    row['calls'] += 1
    code = int(status or 0)
    row['ok' if code < 400 else 'clientError' if code < 500 else 'serverError'] += 1
    row['browser' if caller == 'browser' else 'other'] += 1
    for old in sorted(days)[:-KEEP_DAYS]:
        days.pop(old, None)


def summary(state: Dict[str, Any], *, catalog: Iterable[Any] = (), last_days: Optional[int] = None) -> Dict[str, Any]:
    """Totals per route over the kept days, and the catalogued routes never called."""
    days = sorted(state['days'])
    if last_days:
        days = days[-int(last_days):]
    totals: Dict[str, Dict[str, int]] = {}
    for day in days:
        for key, row in state['days'][day].items():
            total = totals.setdefault(key, dict.fromkeys(_FIELDS, 0))
            for field in _FIELDS:
                total[field] += row.get(field, 0)
    called_rules = {key.rsplit(' ', 1)[0] for key in totals}
    never = []
    for entry in catalog or ():
        route, trust = getattr(entry, 'route', None), getattr(entry, 'trustDomain', None)
        if route and route not in called_rules:
            never.append({'route': route, 'trustDomain': trust})
    return {'schemaVersion': SCHEMA, 'firstDay': days[0] if days else None, 'lastDay': days[-1] if days else None,
            'days': len(days), 'routes': dict(sorted(totals.items(), key=lambda kv: -kv[1]['calls'])),
            'catalogNeverCalled': sorted(never, key=lambda row: (str(row['trustDomain']), row['route'])),
            'note': 'Counted from the first deployment of this counter; a route not called in this window may '
                    'still have rare callers. The raw path and query are never kept.'}
