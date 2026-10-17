"""Official-calendar-first JP cash-session truth for live Tachibana frames."""

from __future__ import annotations

import argus_fastdate  # v13.5.52: lock-free strptime (no _strptime._cache_lock)
from dataclasses import dataclass
from datetime import date, datetime, time as wall_time, timezone
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
    AFTERNOON_PREOPEN = "AFTERNOON_PREOPEN"
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
    provider_calendar_date: date | None
    provider_calendar_current: bool
    event_packet_date: date | None
    event_packet_current: bool
    is_trading_day: bool
    session_truth_confident: bool
    calendar_version: str
    valid_until: datetime


def parse_provider_datetime(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = argus_fastdate.strptime(value, "%Y.%m.%d-%H:%M:%S.%f")
    except ValueError:
        return None
    return parsed.replace(tzinfo=_TOKYO).astimezone(timezone.utc)


def resolve_jp_cash_session(
    *,
    now: datetime,
    provider_time: datetime | None,
    provider_calendar_date: date | None = None,
    provider_health: ProviderHealth = ProviderHealth.AVAILABLE,
    provider_market_status: MarketStatus = MarketStatus.UNKNOWN,
    control_state_confident: bool = True,
) -> SessionTruth:
    """Resolve a frame against ARGUS's versioned JPX calendar.

    Tachibana SS/US status is auxiliary and can only close, halt, degrade, or
    invalidate the calendar result. The official day-key 001 provider date and
    a same-date, bounded-skew ``p_date`` must corroborate the versioned JPX
    trading date before time-only execution fields can be anchored.
    """
    if (
        not isinstance(now, datetime)
        or now.tzinfo is None
        or now.utcoffset() is None
        or provider_time is not None
        and (provider_time.tzinfo is None or provider_time.utcoffset() is None)
        or provider_calendar_date is not None
        and not isinstance(provider_calendar_date, date)
        or not isinstance(provider_health, ProviderHealth)
        or not isinstance(provider_market_status, MarketStatus)
        or type(control_state_confident) is not bool
    ):
        raise ValueError("invalid_session_truth_input")
    current = now.astimezone(timezone.utc)
    state = argus_market_clock.market_session(
        argus_market_clock.JP_EQUITY, current
    )
    market_date = date.fromisoformat(state["marketDate"])
    is_trading_day = bool(state["isTradingDay"])
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
    local_time = current.astimezone(_TOKYO).time()
    # The canonical ARGUS calendar owns trading-day truth and the execution
    # boundaries.  JPX's published order-acceptance boundaries refine its
    # coarse PRE_MARKET/LUNCH_BREAK phases for this read-only sensor only.
    if phase == JapanCashPhase.PREOPEN and local_time < wall_time(8, 0):
        phase = JapanCashPhase.CLOSED
    elif (
        phase == JapanCashPhase.LUNCH_CLOSED_INTERVAL
        and local_time >= wall_time(12, 5)
    ):
        phase = JapanCashPhase.AFTERNOON_PREOPEN
    market_status = (
        MarketStatus.OPEN
        if phase in {JapanCashPhase.OPEN, JapanCashPhase.AFTERNOON_OPEN}
        else MarketStatus.CLOSED
        if phase in {
            JapanCashPhase.PREOPEN,
            JapanCashPhase.LUNCH_CLOSED_INTERVAL,
            JapanCashPhase.AFTERNOON_PREOPEN,
            JapanCashPhase.CLOSED,
        }
        else MarketStatus.UNKNOWN
    )
    provider_calendar_current = bool(
        provider_calendar_date is not None
        and provider_calendar_date == current.astimezone(_TOKYO).date()
        and provider_calendar_date == market_date
    )
    event_packet_date = (
        provider_time.astimezone(_TOKYO).date()
        if provider_time is not None else None
    )
    event_packet_current = bool(
        provider_time is not None
        and event_packet_date == provider_calendar_date
        and abs((current - provider_time.astimezone(timezone.utc)).total_seconds())
        <= _MAX_PROVIDER_CLOCK_SKEW_SECONDS
    )
    frame_verified = bool(
        provider_calendar_current and event_packet_current and is_trading_day
    )
    session_truth_confident = frame_verified

    if provider_health == ProviderHealth.MAINTENANCE:
        phase = JapanCashPhase.MAINTENANCE
        market_status = MarketStatus.MAINTENANCE
    elif provider_health != ProviderHealth.AVAILABLE:
        # A current operation fault is represented as DEGRADED by the status
        # reconciler.  Its packet/date evidence remains usable, but it cannot
        # authorize a calendar-derived continuous-trading phase.
        phase = JapanCashPhase.UNKNOWN
        market_status = MarketStatus.UNKNOWN
        session_truth_confident = False
    elif not control_state_confident:
        phase = JapanCashPhase.UNKNOWN
        market_status = MarketStatus.UNKNOWN
        session_truth_confident = False
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
        session_truth_confident = False
    elif market_status == MarketStatus.OPEN and not frame_verified:
        phase = JapanCashPhase.UNKNOWN
        market_status = MarketStatus.UNKNOWN
        session_truth_confident = False

    return SessionTruth(
        phase=phase,
        market_status=market_status,
        market_date=market_date,
        market_date_verified=frame_verified,
        provider_calendar_date=provider_calendar_date,
        provider_calendar_current=provider_calendar_current,
        event_packet_date=event_packet_date,
        event_packet_current=event_packet_current,
        is_trading_day=is_trading_day,
        session_truth_confident=session_truth_confident,
        calendar_version=str(state["calendarVersion"]),
        valid_until=valid_until,
    )


__all__ = [
    "JapanCashPhase",
    "SessionTruth",
    "parse_provider_datetime",
    "resolve_jp_cash_session",
]
