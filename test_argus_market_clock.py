"""Tests for Calibration Ledger v4 Phase 2 — market-specific clocks.

Pure-logic; deterministic by passing explicit `now_utc` (never wall-clock).
"""
from datetime import date, datetime, timezone, timedelta

import argus_market_clock as MC


def _utc(y, m, d, h=0, mi=0):
    return datetime(y, m, d, h, mi, tzinfo=timezone.utc)


# ── market classification ────────────────────────────────────────────────────
def test_asset_market_classification():
    assert MC.asset_market("7203") == MC.JP_EQUITY
    assert MC.asset_market("285A") == MC.JP_EQUITY      # alnum JP code
    assert MC.asset_market("NVDA") == MC.US_EQUITY
    assert MC.asset_market("SPY") == MC.US_EQUITY
    assert MC.asset_market("BTC") == MC.CRYPTO
    assert MC.asset_market("USDJPY") == MC.FX
    assert MC.asset_market("VIX") == MC.VIX_MKT


# ── trading-day calendar (weekends + holidays) ───────────────────────────────
def test_weekend_not_trading():
    assert MC.is_trading_day(MC.JP_EQUITY, date(2026, 6, 20)) is False  # Sat
    assert MC.is_trading_day(MC.US_EQUITY, date(2026, 6, 21)) is False  # Sun


def test_new_year_holiday_both_markets():
    assert MC.is_trading_day(MC.JP_EQUITY, date(2026, 1, 1)) is False
    assert MC.is_trading_day(MC.US_EQUITY, date(2026, 1, 1)) is False


def test_crypto_always_trades():
    assert MC.is_trading_day(MC.CRYPTO, date(2026, 1, 1)) is True
    assert MC.is_trading_day(MC.CRYPTO, date(2026, 6, 20)) is True  # Sat


def test_add_trading_days_skips_weekend():
    # Fri 2026-06-19 +1 trading day → Mon 2026-06-22 (Sat/Sun skipped)
    assert MC.add_trading_days(MC.US_EQUITY, date(2026, 6, 19), 1) == date(2026, 6, 22)


def test_add_trading_days_skips_holiday():
    # JP: Fri 2026-05-01 +1 trading day must skip the May 3-6 cluster AND the
    # weekend → next trading day is Thu 2026-05-07.
    assert MC.add_trading_days(MC.JP_EQUITY, date(2026, 5, 1), 1) == date(2026, 5, 7)


def test_crypto_add_is_calendar():
    assert MC.add_trading_days(MC.CRYPTO, date(2026, 6, 19), 3) == date(2026, 6, 22)


# ── US DST handling ──────────────────────────────────────────────────────────
def test_us_dst_summer_vs_winter():
    assert MC._is_us_dst(_utc(2026, 7, 1, 12)) is True    # July = EDT
    assert MC._is_us_dst(_utc(2026, 1, 15, 12)) is False  # January = EST


def test_us_close_utc_shifts_with_dst():
    # 16:00 ET: EDT → 20:00 UTC, EST → 21:00 UTC
    summer = MC._local_close(MC.US_EQUITY, date(2026, 7, 10), _utc(2026, 7, 10, 12))
    winter = MC._local_close(MC.US_EQUITY, date(2026, 1, 15), _utc(2026, 1, 15, 12))
    assert summer.hour == 20
    assert winter.hour == 21


# ── forecast clock: JP ───────────────────────────────────────────────────────
def test_jp_clock_origin_and_targets():
    # After JP close on Fri 2026-06-19 (15:00 JST = 06:00 UTC) → origin = 06-19,
    # 1D target = next JP session = Mon 06-22.
    now = _utc(2026, 6, 19, 9)  # 18:00 JST, after close
    clk = MC.forecast_clock("7203", now)
    assert clk["market"] == MC.JP_EQUITY
    assert clk["marketCalendar"] == "JPX_TSE"
    assert clk["originTradingDate"] == "2026-06-19"
    t1 = next(t for t in clk["targets"] if t["horizon"] == "1d")
    assert t1["targetTradingDate"] == "2026-06-22"


def test_jp_origin_is_prior_session_before_close():
    # Before today's close (10:00 JST = 01:00 UTC), origin must be the PRIOR
    # completed session, not today.
    now = _utc(2026, 6, 19, 1)  # 10:00 JST Fri, before 15:00 close
    clk = MC.forecast_clock("7203", now)
    assert clk["originTradingDate"] == "2026-06-18"


# ── forecast clock: US uses US calendar, not 16:05 JST ───────────────────────
def test_us_clock_uses_us_calendar():
    # Thu 2026-06-18 after US close. Note 06-19 is Juneteenth (US holiday) — so
    # the 1D target must skip it AND the weekend → Mon 06-22.
    now = _utc(2026, 6, 18, 21)
    clk = MC.forecast_clock("NVDA", now)
    assert clk["market"] == MC.US_EQUITY
    assert clk["marketCalendar"] == "NYSE_NASDAQ"
    assert clk["timezone"] == "ET"
    assert clk["originTradingDate"] == "2026-06-18"
    t1 = next(t for t in clk["targets"] if t["horizon"] == "1d")
    assert t1["targetTradingDate"] == "2026-06-22"  # Juneteenth + weekend skipped


# ── forecast clock: crypto 24/72/120h ────────────────────────────────────────
def test_crypto_clock_hour_horizons():
    now = _utc(2026, 6, 20, 13, 30)  # a Saturday — still valid for crypto
    clk = MC.forecast_clock("BTC", now)
    assert clk["market"] == MC.CRYPTO
    assert clk["horizonDefinition"] == "elapsed_hours(24/72/120)"
    t = {x["horizon"]: x["targetTimestamp"] for x in clk["targets"]}
    # anchored to the hour: 13:00; +24h → next day 13:00
    assert t["1d"].startswith("2026-06-21T13:00")
    assert t["3d"].startswith("2026-06-23T13:00")
    assert t["5d"].startswith("2026-06-25T13:00")


# ── FX uses NY close ─────────────────────────────────────────────────────────
def test_fx_clock_ny_close():
    now = _utc(2026, 6, 19, 22)
    clk = MC.forecast_clock("USDJPY", now)
    assert clk["market"] == MC.FX
    assert clk["marketCalendar"] == "NY_CLOSE"


# ── eligibility: never silently record stale/missing ─────────────────────────
def test_eligibility_fresh():
    now = _utc(2026, 6, 19, 12)
    r = MC.quote_eligibility("BTC", now - timedelta(seconds=60), now)
    assert r["eligible"] is True and r["quoteStatus"] == "fresh"


def test_eligibility_crypto_stale():
    now = _utc(2026, 6, 19, 12)
    r = MC.quote_eligibility("BTC", now - timedelta(hours=2), now)
    assert r["eligible"] is False and r["missingReason"] == "stale_quote"


def test_eligibility_jp_postclose_price_ok_hours_old():
    # a JP close price several hours old at 16:05 JST is legitimate, not stale
    now = _utc(2026, 6, 19, 7)  # 16:00 JST
    price_as_of = _utc(2026, 6, 19, 6)  # 15:00 JST close, 1h old
    r = MC.quote_eligibility("7203", price_as_of, now)
    assert r["eligible"] is True


def test_eligibility_missing_and_future():
    now = _utc(2026, 6, 19, 12)
    assert MC.quote_eligibility("7203", None, now)["missingReason"] == "no_price"
    future = MC.quote_eligibility("7203", now + timedelta(hours=1), now)
    assert future["missingReason"] == "invalid_timestamp"


def test_calendar_version_present():
    clk = MC.forecast_clock("7203", _utc(2026, 6, 19, 9))
    assert clk["calendarVersion"] == MC.CALENDAR_VERSION
