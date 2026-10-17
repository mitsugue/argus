"""The official release schedule of the weekly CFTC report (2026-10-18).

The report for Tuesday's positions is usually released on Friday at 3:30 p.m.
Eastern time. Federal holidays move some releases; those moves come from the
official schedule page and are listed here per year. A position date whose
release falls outside a listed year, or that is not a Tuesday, gets no
scheduled time: a guessed time would read as a publication time.

This is the nominal schedule, never the actual moment of publication, which
no free source records. Pure functions: no clock, no store, no network.
"""
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo

SCHEMA = 'cftc-release-schedule-v1'
SOURCE = 'https://www.cftc.gov/MarketReports/CommitmentsofTraders/ReleaseSchedule/index.htm'
CURATED_AS_OF = '2026-10-16'
RELEASE_TIME_ET = time(15, 30)
#: Releases moved off Friday by a federal holiday, by release year.
SHIFTED_RELEASES = {
    2026: frozenset(date.fromisoformat(d) for d in (
        '2026-01-05', '2026-06-22', '2026-07-06', '2026-11-16', '2026-11-30', '2026-12-28')),
}
_EASTERN = ZoneInfo('America/New_York')


def release_schedule(position_date: str, *, received_at: Optional[str] = None) -> Dict[str, Any]:
    """The scheduled release of one report, and whether it was received before it."""
    day = date.fromisoformat(position_date)
    base = {'schemaVersion': SCHEMA, 'source': SOURCE, 'curatedAsOf': CURATED_AS_OF,
            'publicationBasis': 'nominal_schedule_not_actual_receipt', 'scheduledReleaseAt': None,
            'scheduledReleaseDate': None, 'shifted': False, 'receiptBeforeSchedule': None}
    if day.weekday() != 1:
        return {**base, 'status': 'SCHEDULE_UNCERTAIN', 'reason': 'position_date_not_tuesday'}
    friday = day + timedelta(days=3)
    shifted = sorted(d for d in SHIFTED_RELEASES.get(friday.year, frozenset()) | SHIFTED_RELEASES.get(friday.year + 1, frozenset())
                     if day < d <= day + timedelta(days=7))
    release = shifted[0] if shifted else friday
    if release.year not in SHIFTED_RELEASES:
        return {**base, 'status': 'OUT_OF_TABLE', 'reason': 'release_year_not_curated'}
    at = datetime.combine(release, RELEASE_TIME_ET, _EASTERN).astimezone(timezone.utc)
    early = None
    if received_at:
        received = datetime.fromisoformat(received_at.replace('Z', '+00:00'))
        early = received < at if received.tzinfo else None
    return {**base, 'status': 'OFFICIAL_SCHEDULE', 'reason': None, 'scheduledReleaseAt': at.isoformat(),
            'scheduledReleaseDate': release.isoformat(), 'shifted': bool(shifted), 'receiptBeforeSchedule': early}
