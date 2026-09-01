"""Official-calendar-first JP cash-session truth for live Tachibana frames."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from enum import Enum
from zoneinfo import ZoneInfo

import argus_market_clock

from .models import MarketStatus, ProviderHealth


_MAX_PROVIDER_CLOCK_SKEW_SECONDS = 30.0
_TOKYO = ZoneInfo("Asia/Tokyo")


class JapanCashPhase(str, Enum):
    PREOPEN = "PREOPEN"
    OPEN = "OPEN"
    LUNCH_CLOSED_INTERVAL = "LUNCH_CLOSED_INTERVAL"
    AFTERNOON_OPEN = "AFTERNOON_OPEN"
    CLOSED = "CLOSED"
    HALTED = "HALTED"
    MAINTENANCE = "MAINTENANCE"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class SessionTruth:
    phase: JapanCashPhase
    market_status: MarketStatus
    market_date: date
    market_date_verified: bool
    calendar_version: str
    valid_until: datetime


def parse_provider_datetime(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.strptime(value, "%Y.%m.%d-%H:%M:%S.%f")
    except ValueError:
        return None
    return parsed.replace(tzinfo=_TOKYO).astimezone(timezone.utc)


def resolve_jp_cash_session(
    *,
    now: datetime,
    provider_time: datetime | None,
    provider_health: ProviderHealth = ProviderHealth.AVAILABLE,
    provider_market_status: MarketStatus = MarketStatus.UNKNOWN,
) -> SessionTruth:
    """Resolve a frame against ARGUS's versioned JPX calendar.

    Tachibana SS/US status is auxiliary and can only close, halt, degrade, or
    invalidate the calendar result. A frame must carry a same-session,
    bounded-skew ``p_date`` before time-of-day fields can be anchored to the
    current exchange date.
    """
    if (
        not isinstance(now, datetime)
        or now.tzinfo is None
        or now.utcoffset() is None
        or provider_time is not None
        and (provider_time.tzinfo is None or provider_time.utcoffset() is None)
        or not isinstance(provider_health, ProviderHealth)
        or not isinstance(provider_market_status, MarketStatus)
    ):
        raise ValueError("invalid_session_truth_input")
    current = now.astimezone(timezone.utc)
    state = argus_market_clock.market_session(
        argus_market_clock.JP_EQUITY, current
    )
    market_date = date.fromisoformat(state["marketDate"])
    valid_until = datetime.fromisoformat(
        state["sessionValidUntil"].replace("Z", "+00:00")
    ).astimezone(timezone.utc)
    phase = {
        "PRE_MARKET": JapanCashPhase.PREOPEN,
        "MORNING_SESSION": JapanCashPhase.OPEN,
        "LUNCH_BREAK": JapanCashPhase.LUNCH_CLOSED_INTERVAL,
        "AFTERNOON_SESSION": JapanCashPhase.AFTERNOON_OPEN,
        "POST_MARKET": JapanCashPhase.CLOSED,
        "WEEKEND_CLOSED": JapanCashPhase.CLOSED,
        "HOLIDAY_CLOSED": JapanCashPhase.CLOSED,
        "EMERGENCY_CLOSED": JapanCashPhase.CLOSED,
    }.get(state["session"], JapanCashPhase.UNKNOWN)
    market_status = (
        MarketStatus.OPEN
        if phase in {JapanCashPhase.OPEN, JapanCashPhase.AFTERNOON_OPEN}
        else MarketStatus.CLOSED
        if phase in {
            JapanCashPhase.PREOPEN,
            JapanCashPhase.LUNCH_CLOSED_INTERVAL,
            JapanCashPhase.CLOSED,
        }
        else MarketStatus.UNKNOWN
    )
    frame_verified = bool(
        provider_time is not None
        and provider_time.astimezone(_TOKYO).date() == market_date
        and abs((current - provider_time.astimezone(timezone.utc)).total_seconds())
        <= _MAX_PROVIDER_CLOCK_SKEW_SECONDS
    )

    if provider_health == ProviderHealth.MAINTENANCE:
        phase = JapanCashPhase.MAINTENANCE
        market_status = MarketStatus.MAINTENANCE
        frame_verified = False
    elif provider_health not in {
        ProviderHealth.AVAILABLE,
        ProviderHealth.DEGRADED,
    }:
        phase = JapanCashPhase.UNKNOWN
        market_status = MarketStatus.UNKNOWN
        frame_verified = False
    elif provider_market_status == MarketStatus.HALTED:
        phase = JapanCashPhase.HALTED
        market_status = MarketStatus.HALTED
    elif (
        market_status == MarketStatus.OPEN
        and provider_market_status in {
            MarketStatus.CLOSED,
            MarketStatus.MAINTENANCE,
        }
    ):
        phase = JapanCashPhase.UNKNOWN
        market_status = MarketStatus.UNKNOWN
        frame_verified = False
    elif market_status == MarketStatus.OPEN and not frame_verified:
        phase = JapanCashPhase.UNKNOWN
        market_status = MarketStatus.UNKNOWN

    return SessionTruth(
        phase=phase,
        market_status=market_status,
        market_date=market_date,
        market_date_verified=frame_verified,
        calendar_version=str(state["calendarVersion"]),
        valid_until=valid_until,
    )


__all__ = [
    "JapanCashPhase",
    "SessionTruth",
    "parse_provider_datetime",
    "resolve_jp_cash_session",
]
