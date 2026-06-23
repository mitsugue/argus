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

from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Optional, Sequence, Tuple

CALENDAR_VERSION = "cal-2026.1"  # ↑ bump when holiday tables are corrected/extended
CLOCK_VERSION = "clock-v1"

# Markets
JP_EQUITY = "JP_EQUITY"
US_EQUITY = "US_EQUITY"
CRYPTO = "CRYPTO"
FX = "FX"
VIX_MKT = "VIX"

_JST = timezone(timedelta(hours=9))

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
# NYSE full-day closures 2026.
_US_HOLIDAYS_2026 = {
    "2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03",
    "2026-05-25", "2026-06-19", "2026-07-03", "2026-09-07",
    "2026-11-26", "2026-12-25",
}

_HOLIDAYS = {
    JP_EQUITY: _JP_HOLIDAYS_2026,
    US_EQUITY: _US_HOLIDAYS_2026,
    VIX_MKT: _US_HOLIDAYS_2026,   # Cboe follows the US holiday calendar
    FX: _US_HOLIDAYS_2026,        # use US/NY holidays as a pragmatic FX proxy
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


def is_trading_day(market: str, d: date) -> bool:
    if market == CRYPTO:
        return True  # 24/7
    if d.weekday() >= 5:  # Sat/Sun
        return False
    return d.isoformat() not in _HOLIDAYS.get(market, set())


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
        hour = 17 if market == FX else 16
        off = _us_eastern_offset(now_utc)
        et = timezone(off)
        return datetime(d.year, d.month, d.day, hour, 0, tzinfo=et).astimezone(timezone.utc)
    raise ValueError(market)


def _origin_trading_date(market: str, now_utc: datetime) -> date:
    """The most-recent COMPLETED trading session date as of now (post-close)."""
    if market == CRYPTO:
        return now_utc.date()
    # walk back from today to the latest trading day whose close has passed
    probe = now_utc.date()
    for _ in range(10):
        if is_trading_day(market, probe):
            close = _local_close(market, probe, now_utc)
            if now_utc >= close:
                return probe
        probe -= timedelta(days=1)
    return probe


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
        return {"eligible": False, "quoteStatus": "stale_quote",
                "missingReason": "stale_quote", "market": market,
                "sourceFreshnessSeconds": int(age)}
    return {"eligible": True, "quoteStatus": "fresh", "market": market,
            "sourceFreshnessSeconds": int(age)}
