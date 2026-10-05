"""Nominal JPX two-market weekly deadlines, never historical receipt times.

Uses the same authority calendar as the collector. No network or state writes.
"""
from datetime import date, datetime, timedelta, timezone
import argus_market_clock as clock

JST = timezone(timedelta(hours=9))


def publication_at(period: str):
    """Second actual TSE session after the held week, 16:00 JST, or unknown."""
    day = date.fromisoformat(period)
    sessions = 0
    try:
        for _ in range(14):
            day += timedelta(days=1)
            if clock.canonical_trading_day(clock.JP_EQUITY, day):
                sessions += 1
                if sessions == 2:
                    return datetime(day.year, day.month, day.day, 16, tzinfo=JST)
    except clock.CalendarUnavailableError:
        return None
    raise ValueError("jpx_publication_calendar_invalid")


def weekly_expectation(now: datetime):
    """Expected latest/next scheduled week; unknown if the calendar is missing."""
    if now.tzinfo is None:
        raise ValueError("jpx_publication_timezone_required")
    now = now.astimezone(JST)
    unknown = {"status": "calendar_unavailable", "latestDuePeriod": None,
               "latestDueAt": None, "nextPeriod": None, "nextPublicationAt": None}
    # A rolling six-week schedule includes the coming weekly publication.
    friday = now.date() + timedelta(days=(4 - now.weekday()) % 7)
    schedule = []
    try:
        for offset in range(6):
            end = friday - timedelta(days=7 * offset)
            for _ in range(5):
                if clock.canonical_trading_day(clock.JP_EQUITY, end):
                    break
                end -= timedelta(days=1)
            else:
                continue  # A wholly closed week has no observation.
            due = publication_at(end.isoformat())
            if due is None:
                return unknown
            schedule.append((due, end.isoformat()))
    except clock.CalendarUnavailableError:
        return unknown
    elapsed = sorted((due, period) for due, period in schedule if due <= now)
    upcoming = sorted((due, period) for due, period in schedule if due > now)
    if not elapsed or not upcoming:
        return unknown
    last, next_row = elapsed[-1], upcoming[0]
    return {"status": "scheduled", "latestDuePeriod": last[1],
            "latestDueAt": last[0].isoformat(), "nextPeriod": next_row[1],
            "nextPublicationAt": next_row[0].isoformat()}
