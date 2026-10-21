"""Where the EPS backfill stands, kept across restarts (2026-10-21 owner decision).

The historical EPS collection retries up to twenty missing dates a warm and
remembered its position only in process memory, so every restart began again
from the newest twenty dates (2026-10-20 diagnostic: all twenty missed one
member's market cap, every time). The position is now kept on disk, and a date
whose retries give the same result three times is set aside as not fillable
from the current source; it is tried again once after thirty days, since the
provider may later complete it. Nothing here changes a stored estimate, an
original, a correction or the request bounds.

Pure functions; the caller reads and writes the file.
"""
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, Optional, Set

SCHEMA = 'level-map-eps-backfill-v1'
# The estimate method the set-aside dates were tried with. A new method (for
# example the 2026-10-21 supplement of blank members) starts the position and
# the set-aside dates afresh, so dates the old method could not fill are
# tried again at once instead of after thirty days.
METHOD = 'blank-member-supplement-2026-10-21'
EXHAUST_AFTER = 3
RETRY_AFTER = timedelta(days=30)
MAX_ENTRIES = 4000
FILENAME = 'level_map_backfill_state.json'


def empty() -> Dict[str, Any]:
    return {'schemaVersion': SCHEMA, 'method': METHOD, 'cursor': None, 'attempts': {}, 'exhausted': {}}


def _day(value: Any) -> Optional[str]:
    if not isinstance(value, str) or len(value) != 10:
        return None
    try:
        return value if datetime.strptime(value, '%Y-%m-%d').strftime('%Y-%m-%d') == value else None
    except ValueError:
        return None


def _instant(value: str) -> datetime:
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


def parse(value: Any) -> Dict[str, Any]:
    """A validated state; anything malformed starts empty rather than guessing."""
    if not isinstance(value, dict) or value.get('schemaVersion') != SCHEMA or value.get('method') != METHOD:
        return empty()
    state = empty()
    state['cursor'] = _day(value.get('cursor'))
    for key in ('attempts', 'exhausted'):
        rows = value.get(key)
        if isinstance(rows, dict):
            for day, row in list(rows.items())[:MAX_ENTRIES]:
                if _day(day) and isinstance(row, dict) and isinstance(row.get('signature'), str):
                    state[key][day] = dict(row)
    return state


def signature(status: str, coverage: Optional[Dict[str, Any]] = None) -> str:
    coverage = coverage if isinstance(coverage, dict) else {}
    return f"{status}:{coverage.get('missingMarketCap')}:{coverage.get('missingEarnings')}"


def note(state: Dict[str, Any], day: str, sign: str, now_iso: str) -> bool:
    """Record one unsuccessful retry; True when the date is now set aside."""
    attempts = state['attempts']
    row = attempts.get(day)
    if row and row.get('signature') == sign:
        row.update(count=int(row.get('count') or 0) + 1, lastAt=now_iso)
    else:
        row = attempts[day] = {'signature': sign, 'count': 1, 'firstAt': now_iso, 'lastAt': now_iso}
    if row['count'] >= EXHAUST_AFTER:
        state['exhausted'][day] = {'signature': sign, 'attempts': row['count'], 'since': now_iso}
        return True
    _trim(state)
    return False


def clear(state: Dict[str, Any], day: str) -> None:
    state['attempts'].pop(day, None)
    state['exhausted'].pop(day, None)


def set_aside(state: Dict[str, Any], now_iso: str) -> Set[str]:
    """Dates to skip now; those past the retry period get one more attempt."""
    now = _instant(now_iso)
    skip = set()
    for day, row in list(state['exhausted'].items()):
        try:
            since = _instant(str(row.get('since')))
        except ValueError:
            since = now
        if now - since >= RETRY_AFTER:
            state['exhausted'].pop(day, None)
            attempt = state['attempts'].setdefault(day, {'signature': row.get('signature'), 'firstAt': now_iso})
            attempt.update(count=EXHAUST_AFTER - 1, lastAt=now_iso)
        else:
            skip.add(day)
    return skip


def wanted_without_set_aside(wanted: Iterable[str], skip: Set[str], keep: Optional[str]) -> list:
    """The latest session is always tried; other set-aside dates are not."""
    return [day for day in wanted if day == keep or day not in skip]


def summary(state: Dict[str, Any]) -> Dict[str, Any]:
    by_signature: Dict[str, int] = {}
    for row in state['exhausted'].values():
        by_signature[row['signature']] = by_signature.get(row['signature'], 0) + 1
    return {'cursor': state.get('cursor'), 'setAsideCount': len(state['exhausted']),
            'setAsideBySignature': dict(sorted(by_signature.items())),
            'attemptsTracked': len(state['attempts'])}


def _trim(state: Dict[str, Any]) -> None:
    attempts = state['attempts']
    if len(attempts) > MAX_ENTRIES:
        for day in sorted(attempts, key=lambda d: attempts[d].get('lastAt') or '')[:len(attempts) - MAX_ENTRIES]:
            attempts.pop(day, None)
