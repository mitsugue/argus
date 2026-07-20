"""A.R.G.U.S. — Calibration Ledger v4 Phase 2: market-specific forecast clocks.

Pure-stdlib, side-effect-free. Replaces the legacy "everything at 16:05 JST"
assumption: each asset is forecast against ITS OWN market session/calendar, and
horizons mean the right thing per market (JP/US trading-day closes; crypto 24/
72/120h; FX NY-close trading days). Computes the per-prediction timing metadata
the v4 schema requires, and an eligibility verdict so stale/invalid bases are
NOT silently recorded.

This module does NOT touch the live ledger branch or the recording workflow —
Phase 3 wires it in. Holiday tables are best-effort 2026 (JPX / NYSE) and are
VERSIONED + overridable; they must be verified against the official calendars
and extended each year (CALENDAR_VERSION).

No external tz libraries: JST is a fixed UTC+9; US Eastern is computed with the
post-2007 US DST rule (2nd Sun Mar 02:00 → 1st Sun Nov 02:00 local).
"""
from __future__ import annotations

from datetime import date, datetime, time as dt_time, timedelta, timezone
from typing import Any, Dict, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

CALENDAR_VERSION = "cal-2026.2"  # ↑ bump when holiday tables are corrected/extended
CLOCK_VERSION = "clock-v2"

# Markets
JP_EQUITY = "JP_EQUITY"
US_EQUITY = "US_EQUITY"
CRYPTO = "CRYPTO"
FX = "FX"
VIX_MKT = "VIX"

_JST = timezone(timedelta(hours=9))
_ET = ZoneInfo("America/New_York")

# Sensors/known symbols → market. Unknown 4-digit/alnum JP codes default JP.
_US_TICKERS = {"SPY", "QQQ", "SMH", "IWM", "TLT", "HYG", "GLD",
               "NVDA", "AAPL", "TSLA", "META", "GOOGL", "AMZN", "MSFT"}


def asset_market(symbol: str) -> str:
    s = (symbol or "").upper()
    if s == "VIX":
        return VIX_MKT
    if s == "USDJPY" or s.endswith("=X"):
        return FX
    if s in ("BTC", "ETH", "SOL") or s.endswith("USD") and s not in _US_TICKERS:
        return CRYPTO
    if s in _US_TICKERS:
        return US_EQUITY
    # JP listing codes: 4 digits, or 4-char alnum like "285A"
    if len(s) == 4 and (s.isdigit() or (s[:3].isdigit() and s[3].isalpha())):
        return JP_EQUITY
    return US_EQUITY  # fallback: treat unknown as US-session


# ── Holiday tables (best-effort 2026; verify against official calendars) ──────
# JPX (TSE) full-day closures 2026, incl. year-end/start 12/31–1/3.
_JP_HOLIDAYS_2026 = {
    "2026-01-01", "2026-01-02", "2026-01-03", "2026-01-12",
    "2026-02-11", "2026-02-23", "2026-03-20", "2026-04-29",
    "2026-05-03", "2026-05-04", "2026-05-05", "2026-05-06",
    "2026-07-20", "2026-08-11", "2026-09-21", "2026-09-22", "2026-09-23",
    "2026-10-12", "2026-11-03", "2026-11-23", "2026-12-31",
}
_JP_HOLIDAY_NAMES_2026 = {
    "2026-01-01": "New Year's Day / 元日",
    "2026-01-02": "Market Holiday / 年始休業",
    "2026-01-03": "Market Holiday / 年始休業",
    "2026-01-12": "Coming of Age Day / 成人の日",
    "2026-02-11": "National Foundation Day / 建国記念の日",
    "2026-02-23": "Emperor's Birthday / 天皇誕生日",
    "2026-03-20": "Vernal Equinox Day / 春分の日",
    "2026-04-29": "Showa Day / 昭和の日",
    "2026-05-03": "Constitution Memorial Day / 憲法記念日",
    "2026-05-04": "Greenery Day / みどりの日",
    "2026-05-05": "Children's Day / こどもの日",
    "2026-05-06": "Substitute Holiday / 振替休日",
    "2026-07-20": "Marine Day / 海の日",
    "2026-08-11": "Mountain Day / 山の日",
    "2026-09-21": "Respect for the Aged Day / 敬老の日",
    "2026-09-22": "National Holiday / 国民の休日",
    "2026-09-23": "Autumnal Equinox Day / 秋分の日",
    "2026-10-12": "Sports Day / スポーツの日",
    "2026-11-03": "Culture Day / 文化の日",
    "2026-11-23": "Labor Thanksgiving Day / 勤労感謝の日",
    "2026-12-31": "Market Holiday / 年末休業",
}
# NYSE full-day closures 2026.
_US_HOLIDAYS_2026 = {
    "2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03",
    "2026-05-25", "2026-06-19", "2026-07-03", "2026-09-07",
    "2026-11-26", "2026-12-25",
}
_US_HOLIDAY_NAMES_2026 = {
    "2026-01-01": "New Year's Day",
    "2026-01-19": "Martin Luther King Jr. Day",
    "2026-02-16": "Washington's Birthday",
    "2026-04-03": "Good Friday",
    "2026-05-25": "Memorial Day",
    "2026-06-19": "Juneteenth National Independence Day",
    "2026-07-03": "Independence Day (Observed)",
    "2026-09-07": "Labor Day",
    "2026-11-26": "Thanksgiving Day",
    "2026-12-25": "Christmas Day",
}
_US_EARLY_CLOSES_2026 = {
    "2026-11-27": "Day after Thanksgiving",
    "2026-12-24": "Christmas Eve",
}

_HOLIDAYS = {
    JP_EQUITY: _JP_HOLIDAYS_2026,
    US_EQUITY: _US_HOLIDAYS_2026,
    VIX_MKT: _US_HOLIDAYS_2026,   # Cboe follows the US holiday calendar
    FX: set(),                    # FX is independent 24/5
}

_HOLIDAY_NAMES = {
    JP_EQUITY: _JP_HOLIDAY_NAMES_2026,
    US_EQUITY: _US_HOLIDAY_NAMES_2026,
    VIX_MKT: _US_HOLIDAY_NAMES_2026,
}


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """nth (1-based) weekday (Mon=0) in a month."""
    d = date(year, month, 1)
    offset = (weekday - d.weekday()) % 7
    return d + timedelta(days=offset + 7 * (n - 1))


def _first_weekday_after(year: int, month: int, day: int, weekday: int) -> date:
    d = date(year, month, day)
    return d + timedelta(days=(weekday - d.weekday()) % 7)


def _is_us_dst(dt_utc: datetime) -> bool:
    """US DST: 2nd Sun Mar 02:00 local → 1st Sun Nov 02:00 local. Approximate the
    boundary using the UTC instant (close enough for daily post-close timing)."""
    y = dt_utc.year
    dst_start = _nth_weekday(y, 3, 6, 2)   # 2nd Sunday of March
    dst_end = _nth_weekday(y, 11, 6, 1)    # 1st Sunday of November
    # transitions at 02:00 local ≈ 07:00 UTC (EST start) / 06:00 UTC (EDT end)
    start_utc = datetime(dst_start.year, dst_start.month, dst_start.day, 7, tzinfo=timezone.utc)
    end_utc = datetime(dst_end.year, dst_end.month, dst_end.day, 6, tzinfo=timezone.utc)
    return start_utc <= dt_utc < end_utc


def _us_eastern_offset(dt_utc: datetime) -> timedelta:
    return timedelta(hours=-4) if _is_us_dst(dt_utc) else timedelta(hours=-5)


def is_trading_day(market: str, d: date,
                   *, extra_closures: Sequence[str] = ()) -> bool:
    if market == CRYPTO:
        return True  # 24/7
    if d.weekday() >= 5:  # Sat/Sun
        return False
    key = d.isoformat()
    return (key not in _HOLIDAYS.get(market, set())
            and key not in set(extra_closures or ()))


def add_trading_days(market: str, start: date, n: int) -> date:
    """The date that is n trading days AFTER `start` (n>=1). Crypto = calendar."""
    if market == CRYPTO:
        return start + timedelta(days=n)
    d = start
    remaining = n
    while remaining > 0:
        d += timedelta(days=1)
        if is_trading_day(market, d):
            remaining -= 1
    return d


def _local_close(market: str, d: date, now_utc: datetime) -> datetime:
    """The UTC instant of `d`'s session close for the market."""
    if market == JP_EQUITY:
        # TSE closing auction is 15:30 JST (extended from 15:00 in Nov 2024) =
        # 06:30 UTC. Using 15:30 avoids treating 15:00–15:30 prices as the close.
        return datetime(d.year, d.month, d.day, 15, 30, tzinfo=_JST).astimezone(timezone.utc)
    if market in (US_EQUITY, VIX_MKT, FX):
        # US regular close 16:00 ET; FX NY close 17:00 ET (use 16:00 for equities/VIX)
        hour = (17 if market == FX else
                13 if d.isoformat() in _US_EARLY_CLOSES_2026 else 16)
        return datetime(d.year, d.month, d.day, hour, 0,
                        tzinfo=_ET).astimezone(timezone.utc)
    raise ValueError(market)


def _origin_trading_date(market: str, now_utc: datetime) -> date:
    """The most-recent COMPLETED trading session date as of now (post-close)."""
    if market == CRYPTO:
        return now_utc.date()
    # walk back from today to the latest trading day whose close has passed
    local_tz = _JST if market == JP_EQUITY else _ET
    probe = now_utc.astimezone(local_tz).date()
    for _ in range(10):
        if is_trading_day(market, probe):
            close = _local_close(market, probe, now_utc)
            if now_utc >= close:
                return probe
        probe -= timedelta(days=1)
    return probe


def market_session(market: str, now_utc: Optional[datetime] = None, *,
                   provider_status: Optional[str] = None,
                   extra_closures: Sequence[str] = ()) -> Dict[str, Any]:
    """Return official-calendar-first session truth for one market.

    Provider state is auxiliary evidence and never overrides the exchange
    calendar. extra_closures supports exchange-announced emergency closures.
    """
    now_utc = now_utc or datetime.now(timezone.utc)
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    if market == CRYPTO:
        return {
            "market": market, "marketDate": now_utc.date().isoformat(),
            "isTradingDay": True, "session": "CONTINUOUS",
            "holidayName": None, "nextTradingDay": None,
            "timezone": "UTC", "calendarVersion": CALENDAR_VERSION,
            "officialCalendar": "CRYPTO_24_7",
            "providerStatus": provider_status, "providerConflict": False,
            "providerRole": "auxiliary_only",
        }
    local_tz = _JST if market == JP_EQUITY else _ET
    local_now = now_utc.astimezone(local_tz)
    market_date = local_now.date()
    key = market_date.isoformat()
    emergency = key in set(extra_closures or ())
    trading = is_trading_day(
        market, market_date, extra_closures=extra_closures)
    holiday_name = (_HOLIDAY_NAMES.get(market, {}).get(key)
                    or ("Emergency exchange closure" if emergency else None))
    if not trading:
        session = ("EMERGENCY_CLOSED" if emergency else
                   "WEEKEND_CLOSED" if market_date.weekday() >= 5 else
                   "HOLIDAY_CLOSED")
    elif market == JP_EQUITY:
        hm = local_now.hour * 60 + local_now.minute
        session = ("PRE_MARKET" if hm < 9 * 60 else
                   "MORNING_SESSION" if hm < 11 * 60 + 30 else
                   "LUNCH_BREAK" if hm < 12 * 60 + 30 else
                   "AFTERNOON_SESSION" if hm < 15 * 60 + 30 else
                   "POST_MARKET")
    elif market in (US_EQUITY, VIX_MKT):
        hm = local_now.hour * 60 + local_now.minute
        close_minute = (13 if key in _US_EARLY_CLOSES_2026 else 16) * 60
        session = ("OVERNIGHT_CLOSED" if hm < 4 * 60 else
                   "PRE_MARKET" if hm < 9 * 60 + 30 else
                   "REGULAR" if hm < close_minute else
                   "AFTER_HOURS" if hm < 20 * 60 else
                   "OVERNIGHT_CLOSED")
    else:
        session = "CONTINUOUS"
    nxt = add_trading_days(market, market_date, 1)
    open_local = datetime.combine(
        market_date,
        dt_time(9, 0) if market == JP_EQUITY else dt_time(9, 30),
        tzinfo=local_tz)
    close_local = _local_close(
        market, market_date, now_utc).astimezone(local_tz)
    provider = str(provider_status or "").strip().upper() or None
    provider_open = provider in (
        "OPEN", "REGULAR", "PREMARKET", "AFTERHOURS")
    official_open = session in (
        "MORNING_SESSION", "AFTERNOON_SESSION", "REGULAR")
    provider_conflict = bool(provider and (
        (provider_open and not trading)
        or (provider == "CLOSED" and official_open)))
    return {
        "market": market, "marketDate": key,
        "isTradingDay": trading, "session": session,
        "holidayName": holiday_name, "nextTradingDay": nxt.isoformat(),
        "timezone": "Asia/Tokyo" if market == JP_EQUITY
                    else "America/New_York",
        "regularOpenJst": open_local.astimezone(_JST).isoformat(),
        "regularCloseJst": close_local.astimezone(_JST).isoformat(),
        "earlyClose": (market in (US_EQUITY, VIX_MKT)
                       and key in _US_EARLY_CLOSES_2026),
        "calendarVersion": CALENDAR_VERSION,
        "officialCalendar": (
            "JPX_TSE" if market == JP_EQUITY
            else "NYSE_NASDAQ" if market in (US_EQUITY, VIX_MKT)
            else "FX_24_5"),
        "providerStatus": provider, "providerConflict": provider_conflict,
        "providerRole": "auxiliary_only",
    }


def forecast_clock(symbol: str, now_utc: Optional[datetime] = None) -> Dict[str, Any]:
    """Full per-prediction timing metadata for `symbol` at `now_utc`.

    For equities/VIX/FX: 1D/3D/5D map to the 1st/3rd/5th FUTURE trading-session
    close on that market's calendar. For crypto: 24h/72h/120h wall-clock anchors.
    """
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    market = asset_market(symbol)

    if market == CRYPTO:
        anchor = now_utc.replace(minute=0, second=0, microsecond=0)
        targets = {h: (anchor + timedelta(hours=hrs)).isoformat()
                   for h, hrs in (("1d", 24), ("3d", 72), ("5d", 120))}
        return {
            "symbol": symbol, "market": market, "clockVersion": CLOCK_VERSION,
            "marketCalendar": "crypto_utc_24_7", "timezone": "UTC",
            "originSession": "utc_anchor", "originTradingDate": anchor.date().isoformat(),
            "forecastGeneratedAt": now_utc.isoformat(),
            "horizonDefinition": "elapsed_hours(24/72/120)",
            "targets": [{"horizon": h, "targetTimestamp": t} for h, t in targets.items()],
            "calendarVersion": CALENDAR_VERSION,
        }

    origin = _origin_trading_date(market, now_utc)
    tz_name = "JST" if market == JP_EQUITY else "ET"
    cal = {JP_EQUITY: "JPX_TSE", US_EQUITY: "NYSE_NASDAQ",
           VIX_MKT: "CBOE", FX: "NY_CLOSE"}[market]
    targets = []
    for h, n in (("1d", 1), ("3d", 3), ("5d", 5)):
        td = add_trading_days(market, origin, n)
        targets.append({
            "horizon": h, "targetTradingDate": td.isoformat(),
            "targetClose": _local_close(market, td, now_utc).isoformat(),
        })
    return {
        "symbol": symbol, "market": market, "clockVersion": CLOCK_VERSION,
        "marketCalendar": cal, "timezone": tz_name,
        "originSession": "post_close", "originTradingDate": origin.isoformat(),
        "originClose": _local_close(market, origin, now_utc).isoformat(),
        "forecastGeneratedAt": now_utc.isoformat(),
        "horizonDefinition": "trading_session_closes(1/3/5)",
        "targets": targets,
        "calendarVersion": CALENDAR_VERSION,
    }


def quote_eligibility(
    symbol: str,
    price_as_of: Optional[datetime],
    now_utc: Optional[datetime] = None,
    *,
    max_age_seconds: Optional[int] = None,
) -> Dict[str, Any]:
    """Decide whether a base price may anchor a forecast. Stale/missing/invalid
    → eligible=False so the caller records a MISSING row (with reason), never a
    silent bad forecast.

    Default freshness budgets: JP/US post-close prices can legitimately be hours
    old (the close is the close), so the budget is generous; crypto/FX must be
    fresh. Pass max_age_seconds to override.
    """
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    market = asset_market(symbol)
    if price_as_of is None:
        return {"eligible": False, "quoteStatus": "no_price",
                "missingReason": "no_price", "market": market}
    if price_as_of.tzinfo is None:
        price_as_of = price_as_of.replace(tzinfo=timezone.utc)
    if price_as_of > now_utc + timedelta(minutes=5):
        return {"eligible": False, "quoteStatus": "invalid_timestamp",
                "missingReason": "invalid_timestamp", "market": market}
    age = (now_utc - price_as_of).total_seconds()
    budget = max_age_seconds if max_age_seconds is not None else (
        300 if market in (CRYPTO, FX) else 36 * 3600)
    if age > budget:
        if market in (JP_EQUITY, US_EQUITY, VIX_MKT):
            local_tz = _JST if market == JP_EQUITY else _ET
            session = market_session(market, now_utc)
            quote_date = price_as_of.astimezone(local_tz).date()
            origin = _origin_trading_date(market, now_utc)
            if (session["session"] not in (
                    "MORNING_SESSION", "AFTERNOON_SESSION", "REGULAR")
                    and quote_date == origin):
                return {
                    "eligible": True,
                    "quoteStatus": "official_close_current",
                    "market": market,
                    "sourceFreshnessSeconds": int(age),
                    "calendarVersion": CALENDAR_VERSION,
                }
        return {"eligible": False, "quoteStatus": "stale_quote",
                "missingReason": "stale_quote", "market": market,
                "sourceFreshnessSeconds": int(age)}
    return {"eligible": True, "quoteStatus": "fresh", "market": market,
            "sourceFreshnessSeconds": int(age)}
