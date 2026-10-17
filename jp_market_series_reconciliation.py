"""Expected dates against stored dates for every condition input (2026-10-18).

Counts alone can hide a gap: a duplicated day makes up for a missing one.
Each input is compared with the dates it should have, inside its own first
and last date, and the differences are named: missing, unexpected and
duplicated dates, revisions, and values that are not finite numbers.

Only the Tokyo exchange calendar is held for the whole period (the stored
official table, the market clock where it answers). US, bond and currency
inputs have no official calendar here yet, so they are counted but never
called complete. Derived and proxy inputs are outside the check. The
2020-10-01 exchange outage is not an expected date (actual-trading basis,
owner decision 2026-10-17). No values leave this module.

Pure functions: no clock, no store, no network.
"""
from datetime import date
import math
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence

SCHEMA = 'jp-market-series-reconciliation-v1'
MAX_DAYS = 6000
MAX_ROWS = 120000
LIST_LIMIT = 50
#: 1570 balances are daily from this application date; weekly before it.
MARGIN_DAILY_FROM = '2026-09-25'
#: Scheduled sessions on which the exchange did not trade.
KNOWN_NONTRADING_DAYS = {'2020-10-01': 'TSE_FULL_DAY_OUTAGE'}

JP_SESSIONS, JP_WEEKS, MARGIN_WEEKS_THEN_SESSIONS = 'JP_SESSIONS', 'JP_WEEKS', 'MARGIN_WEEKS_THEN_SESSIONS'
NO_CALENDAR, NOT_CHECKED = 'NO_OFFICIAL_CALENDAR', 'NOT_CHECKED'
CALENDARS = {
    'price_series:nikkei': JP_SESSIONS,
    'price_series:topix': JP_SESSIONS,
    'price_series:index_per': JP_SESSIONS,
    'two_market_credit': JP_WEEKS,
    'foreign_flow': JP_WEEKS,
    'margin_1570': MARGIN_WEEKS_THEN_SESSIONS,
    'price_series:sp500': NO_CALENDAR,
    'price_series:vix': NO_CALENDAR,
    'price_series:us10y': NO_CALENDAR,
    'price_series:usdjpy': NO_CALENDAR,
    'price_series:jp10y': NO_CALENDAR,
    'valuation_loss': NOT_CHECKED,     # proxy calculation, no official series
    'sq_events': NOT_CHECKED,          # derived from the calendar itself
}
REASONS = {NO_CALENDAR: 'official_calendar_not_held', NOT_CHECKED: 'derived_or_proxy_series'}
#: Which of the sixteen condition features read each input.
AFFECTED_FEATURES = {
    'price_series:nikkei': ('relative_jp_us.return20', 'nt.ratio_change5', 'credit.loss_pct'),
    'price_series:topix': ('nt.ratio_change5',),
    'price_series:sp500': ('relative_jp_us.return20',),
    'price_series:vix': ('vix.level', 'vix.change5', 'vix.macd_histogram'),
    'price_series:usdjpy': ('fx.usdjpy_change5',),
    'price_series:us10y': ('rate.us10y_change5',),
    'price_series:jp10y': ('rate.jp10y_change5',),
    'price_series:index_per': (),
    'two_market_credit': ('credit.ratio', 'credit.ratio_change', 'credit.loss_pct'),
    'valuation_loss': ('credit.loss_pct',),
    'margin_1570': ('margin1570.ratio', 'margin1570.long_change_pct', 'margin1570.short_change_pct'),
    'foreign_flow': ('foreign_flow.net4w',),
    'sq_events': ('event.sq_sessions',),
}


def _day(row: Mapping[str, Any]) -> str:
    return str(row.get('periodEnd') or row.get('date') or '')[:10]


def _week(day: str) -> str:
    year, week, _ = date.fromisoformat(day).isocalendar()
    return f'{year}-W{week:02d}'


def _invalid(row: Mapping[str, Any]) -> bool:
    for key in ('value', 'close'):
        if key in row:
            value = row[key]
            return isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)
    return False


def _listed(values: Iterable[str]) -> Dict[str, Any]:
    values = sorted(values)
    return {'count': len(values), 'first': values[:LIST_LIMIT], 'truncated': len(values) > LIST_LIMIT}


def reconcile_series(key: str, rows: Sequence[Any], *, open_days: Iterable[str],
                     unknown_days: Iterable[str] = ()) -> Dict[str, Any]:
    """One input against its expected calendar; dates and counts only."""
    calendar = CALENDARS.get(key, NOT_CHECKED)
    if len(rows or ()) > MAX_ROWS:
        raise ValueError('reconciliation_row_bound')
    seen: Dict[tuple, set] = {}
    days, invalid, malformed = set(), set(), 0
    for row in rows or ():
        day = _day(row) if isinstance(row, Mapping) else ''
        try:
            date.fromisoformat(day)
        except ValueError:
            malformed += 1
            continue
        days.add(day)
        part = str(row.get('seriesId') or row.get('field') or '')
        known = str(row.get('knownAt') or row.get('availableFrom') or row.get('observedAt') or '')
        seen.setdefault((part, day), set())
        if known in seen[(part, day)]:
            seen[(part, day)].add(known + '\x00dup')   # same part, day and receipt twice
        seen[(part, day)].add(known)
        if _invalid(row):
            invalid.add(day)
    duplicated = {day for (part, day), receipts in seen.items() if any(r.endswith('\x00dup') for r in receipts)}
    revised = {day for (part, day), receipts in seen.items()
               if len({r for r in receipts if not r.endswith('\x00dup')}) > 1}
    parts = sorted({part for part, _ in seen})
    base = {'calendar': calendar, 'rows': len(rows or ()), 'distinctDates': len(days),
            'first': min(days, default=None), 'last': max(days, default=None), 'parts': len(parts),
            'duplicatedDates': _listed(duplicated), 'revisedDates': len(revised),
            'invalidValueDates': _listed(invalid), 'malformedRows': malformed,
            'affectedFeatures': list(AFFECTED_FEATURES.get(key, ()))}
    if calendar in (NO_CALENDAR, NOT_CHECKED):
        return {**base, 'status': 'EXPECTED_CALENDAR_UNAVAILABLE' if calendar == NO_CALENDAR else 'NOT_EXPECTED',
                'reason': REASONS[calendar], 'expected': None, 'missingDates': None, 'unexpectedDates': None}
    if not days:
        return {**base, 'status': 'NO_ROWS', 'reason': None, 'expected': 0,
                'missingDates': _listed(()), 'unexpectedDates': _listed(())}
    first, last = base['first'], base['last']
    open_set = {d for d in open_days if first <= d <= last and d not in KNOWN_NONTRADING_DAYS}
    unknown = {d for d in unknown_days if first <= d <= last}
    if len(open_set) > MAX_DAYS:
        raise ValueError('reconciliation_day_bound')
    outage_rows = sorted(d for d in days if d in KNOWN_NONTRADING_DAYS)
    stored = {d for d in days if d not in KNOWN_NONTRADING_DAYS}
    if calendar == MARGIN_WEEKS_THEN_SESSIONS:
        # The application date's own week is the first daily week, not a weekly one.
        switch = _week(MARGIN_DAILY_FROM)
        weekly = _weekly({d for d in stored if d < MARGIN_DAILY_FROM},
                         {d for d in open_set if d < MARGIN_DAILY_FROM and _week(d) != switch})
        daily = _daily({d for d in stored if d >= MARGIN_DAILY_FROM}, {d for d in open_set if d >= MARGIN_DAILY_FROM})
        expected, missing, unexpected = (weekly[0] + daily[0], weekly[1] | daily[1], weekly[2] | daily[2])
    elif calendar == JP_WEEKS:
        expected, missing, unexpected = _weekly(stored, open_set)
    else:
        expected, missing, unexpected = _daily(stored, open_set)
    # A date the calendar could not answer is neither expected nor unexpected.
    unexpected = {d for d in unexpected if d not in unknown}
    gaps = bool(missing or unexpected or duplicated or invalid or malformed)
    status = 'GAPS_FOUND' if gaps else 'COMPLETE' if not unknown else 'COMPLETE_WHERE_CALENDAR_KNOWN'
    return {**base, 'status': status, 'reason': None, 'expected': expected,
            'missingDates': _listed(missing), 'unexpectedDates': _listed(unexpected),
            'calendarUnknownDays': len(unknown), 'knownNontradingRows': outage_rows}


def _daily(stored: set, open_set: set):
    return len(open_set), open_set - stored, stored - open_set


def _weekly(stored: set, open_set: set):
    """One date per week that has a session; the week, not the weekday, is checked."""
    weeks = {_week(d) for d in open_set}
    by_week: Dict[str, list] = {}
    for d in stored:
        by_week.setdefault(_week(d), []).append(d)
    missing = {w for w in weeks if w not in by_week}
    unexpected = {d for w, ds in by_week.items() if w not in weeks for d in ds}
    unexpected |= {d for ds in by_week.values() if len(ds) > 1 for d in sorted(ds)[:-1]}
    return len(weeks), missing, unexpected


def reconcile(inputs: Mapping[str, Any], *, open_days: Iterable[str], unknown_days: Iterable[str] = (),
              measured_at: Optional[str] = None) -> Dict[str, Any]:
    """Every input list of the condition features, keyed like the input spans."""
    lists = {'price_series:' + k: v for k, v in (inputs.get('price_series') or {}).items()}
    lists.update({k: v for k, v in inputs.items() if k != 'price_series'})
    open_days, unknown_days = sorted(set(open_days)), sorted(set(unknown_days))
    series = {key: reconcile_series(key, rows or (), open_days=open_days, unknown_days=unknown_days)
              for key, rows in sorted(lists.items())}
    statuses = [row['status'] for row in series.values()]
    return {'schemaVersion': SCHEMA, 'measuredAt': measured_at, 'series': series,
            'gapsFound': sorted(k for k, row in series.items() if row['status'] == 'GAPS_FOUND'),
            'calendarUnavailable': sorted(k for k, row in series.items()
                                          if row['status'] == 'EXPECTED_CALENDAR_UNAVAILABLE'),
            'complete': statuses.count('COMPLETE'), 'historicalVintageVerified': False,
            'automaticRepair': False, 'actionAuthority': False}


def summary(document: Mapping[str, Any]) -> Dict[str, Any]:
    """Counts and status only, for the product document."""
    def count(row, key):
        value = row.get(key)
        return value.get('count') if isinstance(value, Mapping) else None
    return {'schemaVersion': document.get('schemaVersion'), 'measuredAt': document.get('measuredAt'),
            'series': {key: {'status': row.get('status'), 'expected': row.get('expected'),
                             'actual': row.get('distinctDates'), 'missing': count(row, 'missingDates'),
                             'unexpected': count(row, 'unexpectedDates'),
                             'duplicated': count(row, 'duplicatedDates'),
                             'invalidValues': count(row, 'invalidValueDates')}
                       for key, row in (document.get('series') or {}).items()},
            'gapsFound': list(document.get('gapsFound') or ()), 'actionAuthority': False}
