"""Official-date Japan SQ planning, independent of AI and monetary policy gates."""
from __future__ import annotations

import json
from pathlib import Path
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Callable, Mapping, Sequence

from argus_market_clock import JP_EQUITY, CalendarUnavailableError, canonical_trading_day

JST = timezone(timedelta(hours=9))
SCHEMA_VERSION = "jp-market-sq-calendar-v1"


def _now(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("timezone_aware_now_required")
    return value.astimezone(JST)


def _date(value: Any) -> date:
    if not isinstance(value, str):
        raise ValueError("date_string_required")
    result = date.fromisoformat(value)
    if result.isoformat() != value:
        raise ValueError("exact_iso_date_required")
    return result


def _instant(value: Any) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("schedule_knowledge_timezone_required")
    return parsed.astimezone(JST)


def _trading_day(day: date) -> bool:
    return canonical_trading_day(JP_EQUITY, day)


def sq_calendar(*, now: datetime, schedule: Mapping[str, Any], horizon_days: int = 30,
                trading_day: Callable[[date], bool] = _trading_day) -> dict[str, Any]:
    """Project published dates; a calendar conflict is visible, never shifted.

    Notification proposals carry stable event+phase IDs but make no delivery
    claim. An authenticated persistent sender and actual device receipt are
    separate required integration steps.
    """
    current = _now(now)
    today = current.date()
    if isinstance(horizon_days, bool) or not isinstance(horizon_days, int) or not 1 <= horizon_days <= 90:
        raise ValueError("invalid_calendar_horizon")
    end = today + timedelta(days=horizon_days)
    result: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION, "asOf": current.isoformat(), "timezone": "Asia/Tokyo",
        "rangeStart": today.isoformat(), "rangeEnd": end.isoformat(), "events": [],
        "notificationProposals": [], "status": "AVAILABLE", "gaps": [],
        "dependsOnAi": False, "actionAuthority": False,
    }
    known = _instant(schedule.get("knownAt"))
    if known > current:
        return {**result, "status": "UNAVAILABLE", "gaps": ["schedule_not_known_at_cutoff"]}
    start_coverage, end_coverage = _date(schedule.get("coverageStart")), _date(schedule.get("coverageEnd"))
    if today < start_coverage or end > end_coverage:
        result["status"] = "PARTIAL"
        result["gaps"].append("official_schedule_does_not_cover_full_horizon")
    if not schedule.get("sourceRef") or not schedule.get("sourceSha256"):
        raise ValueError("official_schedule_provenance_required")
    seen = set()
    for row in schedule.get("rows", []):
        sq_day, last_day = _date(row.get("sqDate")), _date(row.get("lastTradingDate"))
        contract = _date(row.get("contractMonth"))
        if contract.day != 1 or contract.year != sq_day.year or contract.month != sq_day.month \
                or not last_day < sq_day:
            raise ValueError("inconsistent_official_contract_dates")
        if sq_day in seen:
            raise ValueError("duplicate_monthly_sq_date")
        seen.add(sq_day)
        if not today <= sq_day <= end:
            continue
        identifier = "jp-monthly-sq-" + contract.strftime("%Y-%m")
        major = contract.month in (3, 6, 9, 12)
        stage = ("TODAY" if today == sq_day else "LAST_TRADING_DAY" if today == last_day else
                 "EVENT_WEEK" if today.isocalendar()[:2] == sq_day.isocalendar()[:2] else "UPCOMING")
        calendar_valid = True
        gap = None
        distance = None
        week_first = sq_day - timedelta(days=sq_day.weekday())
        try:
            if not trading_day(sq_day) or not trading_day(last_day):
                calendar_valid, gap = False, "official_schedule_and_calendar_conflict"
            distance = sum(trading_day(today + timedelta(days=n))
                           for n in range(1, (sq_day - today).days + 1))
            after_last = [last_day + timedelta(days=n) for n in range(1, (sq_day - last_day).days + 1)
                          if trading_day(last_day + timedelta(days=n))]
            if after_last != [sq_day]:
                calendar_valid, gap = False, "last_trading_day_not_previous_session"
            while week_first < sq_day and not trading_day(week_first):
                week_first += timedelta(days=1)
        except CalendarUnavailableError:
            calendar_valid, gap, distance = False, "trading_calendar_unavailable", None
        if not calendar_valid:
            result["status"] = "PARTIAL"
            result["gaps"].append(gap)
        event = {
            "eventId": identifier, "eventType": "DERIVATIVES_SQ", "market": "JP",
            "title": "メジャーSQ" if major else "SQ", "kind": "MAJOR_SQ" if major else "MONTHLY_SQ",
            "contractMonth": contract.strftime("%Y-%m"), "sqDate": sq_day.isoformat(),
            "lastTradingDate": last_day.isoformat(), "timezone": "Asia/Tokyo",
            "lastTradingSession": "DAY_SESSION_ONLY",
            "calculatedAt": current.isoformat(), "stage": stage, "calendarDaysUntil": (sq_day - today).days,
            "tradingSessionsUntil": distance if calendar_valid else None,
            "calendarStatus": "VERIFIED" if calendar_valid else "UNAVAILABLE_OR_CONFLICT",
            "calculationTiming": "OPENING_PRICES_ON_SQ_DATE",
            "fixedPublicationTime": None, "requiresAiResult": False,
            "directionalSignal": None, "priceReaction": "NOT_OBSERVED_BY_CALENDAR",
            "sourceRef": row.get("sourceRef") or schedule["sourceRef"],
            "sourceSha256": row.get("sourceSha256") or schedule["sourceSha256"],
            "knownAt": row.get("knownAt") or schedule["knownAt"], "sourceCells": row.get("sourceCells"),
            "detailKey": identifier,
            "summary": "先物・オプションの清算に関係する日程です。SQだけで相場の下落や回復は判断しません。",
        }
        result["events"].append(event)
        # Only today's highest-priority notice is proposed. A restarted worker
        # does not emit missed weekly notices together with today's notice.
        notice = ("DAY" if today == sq_day else "PREVIOUS_SESSION" if today == last_day else
                  "WEEK" if today == week_first else None)
        due = datetime.combine(today, time(8), JST)
        if calendar_valid and notice and due <= current and current.hour < 16:
            result["notificationProposals"].append({
                "deduplicationKey": identifier + ":" + notice,
                "eventId": identifier, "phase": notice, "dueAt": due.isoformat(),
                "expiresAt": datetime.combine(today, time(16), JST).isoformat(),
                "deliveryStatus": "NOT_SENT", "requiresUserPermission": True,
                "title": event["title"] + ("当日です" if notice == "DAY" else
                                            "の最終取引日です" if notice == "PREVIOUS_SESSION" else "の週です"),
                "detailKey": identifier,
            })
    month = date(max(today, start_coverage).year, max(today, start_coverage).month, 1)
    covered_end = min(end, end_coverage)
    supplied_months = {(day.year, day.month) for day in seen}
    while month <= covered_end:
        if (month.year, month.month) not in supplied_months:
            result["status"] = "PARTIAL"
            result["gaps"].append("missing_official_monthly_schedule")
        month = date(month.year + (month.month == 12), month.month % 12 + 1, 1)
    result["events"].sort(key=lambda row: row["sqDate"])
    result["gaps"] = sorted(set(result["gaps"]))
    return result


SQ_SCHEDULE_DIR = Path(__file__).parent / "ops/calendar"
SQ_SCHEDULE_SCHEMA = "jp-official-monthly-sq-schedule-v1"


def load_published_sq_schedule(now: datetime, directory: Path | None = None) -> dict[str, Any]:
    """Merge the yearly official schedules (jp_index_sq_<year>.json) into one.

    Each file keeps its own source, hash and receipt time; a year whose receipt
    is after `now` is not yet known. Years must be contiguous: a missing year is
    reported as a gap by the calendar, never filled. Rows carry their own source
    so an event names the file it came from.
    """
    current = _now(now)
    merged: dict[str, Any] | None = None
    previous_end: date | None = None
    for path in sorted((directory or SQ_SCHEDULE_DIR).glob("jp_index_sq_*.json")):
        with path.open("rb") as handle:
            raw = handle.read(65537)
        if len(raw) > 65536:
            raise ValueError("schedule_size_limit")
        schedule = json.loads(raw)
        if schedule.get("schemaVersion") != SQ_SCHEDULE_SCHEMA:
            raise ValueError("schedule_schema_invalid")
        if not schedule.get("sourceRef") or not schedule.get("sourceSha256"):
            raise ValueError("official_schedule_provenance_required")
        if _instant(schedule.get("knownAt")) > current:
            continue
        start, end = _date(schedule.get("coverageStart")), _date(schedule.get("coverageEnd"))
        rows = [{**row, "sourceRef": schedule["sourceRef"], "sourceSha256": schedule["sourceSha256"],
                 "knownAt": schedule["knownAt"]} for row in schedule.get("rows", [])]
        if merged is None:
            merged = {**schedule, "rows": rows}
        elif previous_end is not None and start == previous_end + timedelta(days=1):
            merged["rows"] = merged["rows"] + rows
            merged["coverageEnd"] = schedule["coverageEnd"]
            merged["knownAt"] = max(str(merged["knownAt"]), str(schedule["knownAt"]))
        else:
            break                          # a missing year ends the covered range
        previous_end = end
    if merged is None:
        raise ValueError("schedule_unavailable")
    return merged


def published_sq_calendar(*, now: datetime, schedule_path: Path | None = None) -> dict[str, Any]:
    """Read the shipped official schedule without external acquisition or AI.

    The bounded file is reread so a calendar deployment takes effect directly.
    Missing coverage remains explicit; next year's dates are never extrapolated.
    """
    try:
        if schedule_path is not None:
            with schedule_path.open("rb") as handle:
                raw = handle.read(65537)
            if len(raw) > 65536:
                raise ValueError("schedule_size_limit")
            schedule = json.loads(raw)
            if schedule.get("schemaVersion") != SQ_SCHEDULE_SCHEMA:
                raise ValueError("schedule_schema_invalid")
        else:
            schedule = load_published_sq_schedule(now)
        result = sq_calendar(now=now, schedule=schedule)
        return {**result, "automaticAiCalls": 0, "lastSuccessfulAcquisitionAt": schedule["knownAt"]}
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        current = _now(now)
        return {"schemaVersion": SCHEMA_VERSION, "asOf": current.isoformat(),
                "timezone": "Asia/Tokyo", "rangeStart": current.date().isoformat(),
                "rangeEnd": (current.date() + timedelta(days=30)).isoformat(),
                "status": "UNAVAILABLE", "gaps": ["official_schedule_unavailable"],
                "events": [], "notificationProposals": [], "dependsOnAi": False,
                "actionAuthority": False, "automaticAiCalls": 0,
                "lastSuccessfulAcquisitionAt": None}


SQ_RULE_SOURCE = "rule:jpx-index-sq-second-friday-prior-session"


def rule_derived_sq_rows(session_dates: Sequence[str], *, calculation_dates: Sequence[str]) -> list[dict[str, Any]]:
    """Historical monthly SQ distance from the exchange calendar rule.

    The index SQ falls on the second Friday of the month, or the preceding
    session when that Friday is not one. No published schedule archive exists
    for past years, so history is labelled RULE_DERIVED (never VERIFIED) and
    the published schedule still governs the present. One row per JST
    calculation date: the number of sessions after that date up to and
    including the next SQ date. Rows are known at their own calculation
    instant (00:00 JST of that date) and cannot affect an earlier cutoff.
    """
    sessions = sorted(set(str(day) for day in session_dates))
    if not sessions or len(sessions) > 4000 or any(len(day) != 10 for day in sessions):
        raise ValueError("bounded_session_calendar_required")
    session_set = set(sessions)
    ordered = [date.fromisoformat(day) for day in sessions]
    last_session = ordered[-1]

    def sq_day_for(year: int, month: int):
        first = date(year, month, 1)
        friday = first + timedelta(days=(4 - first.weekday()) % 7) + timedelta(days=7)
        candidate = friday
        while candidate >= first and candidate.isoformat() not in session_set:
            candidate -= timedelta(days=1)
        return candidate if candidate >= first else None

    rows = []
    for calc in sorted(set(str(day)[:10] for day in calculation_dates)):
        today = date.fromisoformat(calc)
        year, month = today.year, today.month
        sq_day = None
        for _ in range(3):
            candidate = sq_day_for(year, month)
            if candidate and candidate >= today:
                sq_day = candidate; break
            month += 1
            if month == 13:
                year, month = year + 1, 1
        if sq_day is None or sq_day > last_session:
            continue  # the calendar does not reach the next SQ: no distance
        distance = sum(1 for day in ordered if today < day <= sq_day)
        known = f"{calc}T00:00:00+09:00"
        rows.append({"eventId": f"jp-monthly-sq-{sq_day.strftime('%Y-%m')}", "eventType": "DERIVATIVES_SQ",
                     "market": "JP", "kind": "MAJOR_SQ" if sq_day.month in (3, 6, 9, 12) else "MONTHLY_SQ",
                     "contractMonth": sq_day.strftime("%Y-%m"), "sqDate": sq_day.isoformat(),
                     "calculatedAt": known, "knownAt": known, "date": calc,
                     "tradingSessionsUntil": distance, "calendarDaysUntil": (sq_day - today).days,
                     "calendarStatus": "RULE_DERIVED", "sourceRef": SQ_RULE_SOURCE,
                     "historicalVintageVerified": False, "actionAuthority": False})
    return rows
