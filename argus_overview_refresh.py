"""When a saved subject explanation may be written again (owner cost decision 2026-11-10).

Measured 2026-11-09: 1,475 owner_dialogue calls and 27.1M input tokens in one
day. Every market-brief edition (14-25 a weekday) changed the shared market
facts inside each subject's inputs, so all registered subjects were written
again after each edition. The market facts stay in the explanation; they no
longer decide by themselves when it is rewritten.

A saved SUCCEEDED explanation with changed inputs is rewritten only when
  * it was completed before the latest weekday refresh time (16:00 JST, after
    the 15:45 close edition), or
  * the subject's own materials (saved earnings, related news, the selected
    official event) changed and the saved one is at least an hour old.
At most a fixed number of generations start per subject and JST day, so a
rejected answer is not retried on every new market edition. No clock is
added: the existing resident tick asks this module.
"""
from datetime import datetime, timedelta, timezone
import hashlib
import json

JST = timezone(timedelta(hours=9))
DAILY_REFRESH_JST = (16, 0)
MATERIAL_MIN_AGE = timedelta(hours=1)
MAX_STARTS_PER_SUBJECT_DAY = 3
MATERIAL_SOURCES = ('subject_news_metadata', 'subject_saved_earnings', 'selected_event', 'event_focus')
_VOLATILE = ('receivedAt', 'fetchedAt', 'acquiredAt', 'observedAt', 'checkedAt')


def _instant(value):
    parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('refresh_time_without_zone')
    return parsed.astimezone(timezone.utc)


def refresh_boundary(now):
    """Latest weekday 16:00 JST at or before now (UTC)."""
    local = _instant(now).astimezone(JST)
    day = local.replace(hour=DAILY_REFRESH_JST[0], minute=DAILY_REFRESH_JST[1], second=0, microsecond=0)
    if local < day:
        day -= timedelta(days=1)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return day.astimezone(timezone.utc)


def _stable(value):
    if isinstance(value, dict):
        return {k: _stable(v) for k, v in value.items() if k not in _VOLATILE}
    if isinstance(value, list):
        return [_stable(v) for v in value]
    return value


def material_key(context):
    """Identity of the subject's own materials, without fetch times."""
    rows = []
    for fact in (context or {}).get('facts') or []:
        if not isinstance(fact, dict) or fact.get('source') not in MATERIAL_SOURCES:
            continue
        if fact['source'] == 'subject_news_metadata':
            value = fact.get('materialInput') or {}
            rows.append(['news', value.get('url'), value.get('title'), value.get('publishedAt'), value.get('updatedAt')])
        elif fact['source'] == 'subject_saved_earnings':
            rows.append(['earnings', _stable(fact.get('materialInput'))])
        else:
            rows.append(['event', (fact.get('provenance') or {}).get('sourceRowSha256'), fact.get('text')])
    rows.sort(key=lambda row: json.dumps(row, ensure_ascii=False, sort_keys=True))
    return hashlib.sha256(json.dumps(rows, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


class RefreshPolicy:
    """Decide and count new generations; in memory, reset by a restart."""

    def __init__(self, max_starts=MAX_STARTS_PER_SUBJECT_DAY):
        self.max_starts = max_starts
        self.starts = {}

    def _day(self, now):
        return _instant(now).astimezone(JST).date().isoformat()

    def decide(self, *, subject, previous_context, previous_completed_at, context, now):
        """Return (due, reason). previous_* belong to the saved SUCCEEDED edition."""
        key = (subject, self._day(now))
        if self.starts.get(key, 0) >= self.max_starts:
            return False, 'DAILY_START_LIMIT'
        completed = _instant(previous_completed_at)
        if completed < refresh_boundary(now):
            return True, 'DAILY_REFRESH'
        if material_key(context) != material_key(previous_context):
            if _instant(now) - completed >= MATERIAL_MIN_AGE:
                return True, 'SUBJECT_MATERIAL_CHANGED'
            return False, 'SUBJECT_MATERIAL_TOO_RECENT'
        return False, 'REFRESH_NOT_DUE'

    def started(self, *, subject, now):
        key = (subject, self._day(now))
        self.starts = {k: v for k, v in self.starts.items() if k[1] == key[1]}
        self.starts[key] = self.starts.get(key, 0) + 1

    def next_refresh_at(self, now):
        candidate = refresh_boundary(now) + timedelta(days=1)
        while candidate.astimezone(JST).weekday() >= 5:
            candidate += timedelta(days=1)
        return candidate.isoformat()
