"""Read the two completed daily bars for an existing next-session outcome.

No provider calls, fabricated receipt times, delayed display prices or writes.
The caller supplies the already-received chart-cache revision.
"""
from datetime import date, datetime, timezone
import math

import argus_market_clock as clock


def _instant(value):
    try:
        result = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return result.astimezone(timezone.utc) if result.tzinfo else None
    except (TypeError, ValueError, OverflowError):
        return None


def closing_pair(rows, *, market, issued_day, now):
    """Keep gaps/conflicts/unreceived revisions unresolved; never use a later bar."""
    kind = {'JP': clock.JP_EQUITY, 'US': clock.US_EQUITY}.get(market)
    cutoff = _instant(now)
    try:
        start = date.fromisoformat(issued_day)
        if kind is None or cutoff is None or not clock.is_trading_day(kind, start):
            return []
        end = clock.add_trading_days(kind, start, 1)
    except (TypeError, ValueError, OverflowError):
        return []
    wanted = {start.isoformat(), end.isoformat()}
    expected_close = {day: _instant(clock.market_session_bounds(
        kind, date.fromisoformat(day))['regularCloseUtc']) for day in wanted}
    selected = {}
    if not isinstance(rows, list):
        return []
    for row in rows:
        if not isinstance(row, dict) or row.get('date') not in wanted:
            continue
        known = _instant(row.get('knownAt'))
        observed = _instant(row.get('observedAt'))
        close = row.get('close')
        if (known is None or observed is None or known > cutoff or observed > cutoff
                or observed != expected_close[row['date']] or known < observed
                or isinstance(close, bool) or not isinstance(close, (int, float))
                or not math.isfinite(close) or close <= 0
                or not isinstance(row.get('adjusted'), bool)):
            return []
        day = row['date']
        identity = (close, row['adjusted'], row.get('source'), row.get('datasetId'))
        if day in selected and selected[day][0] != identity:
            return []
        selected[day] = (identity, {'date': day, 'close': close})
    if set(selected) != wanted or selected[start.isoformat()][0][1:] != selected[end.isoformat()][0][1:]:
        return []
    return [selected[day][1] for day in sorted(wanted)]
