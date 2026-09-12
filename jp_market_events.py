"""Official-date Japan SQ planning, independent of AI and monetary policy gates."""
from __future__ import annotations

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
            "stage": stage, "calendarDaysUntil": (sq_day - today).days,
            "tradingSessionsUntil": distance if calendar_valid else None,
            "calendarStatus": "VERIFIED" if calendar_valid else "UNAVAILABLE_OR_CONFLICT",
            "calculationTiming": "OPENING_PRICES_ON_SQ_DATE",
            "fixedPublicationTime": None, "requiresAiResult": False,
            "directionalSignal": None, "priceReaction": "NOT_OBSERVED_BY_CALENDAR",
            "sourceRef": schedule["sourceRef"], "sourceSha256": schedule["sourceSha256"],
            "knownAt": schedule["knownAt"], "sourceCells": row.get("sourceCells"),
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
