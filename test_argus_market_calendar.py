"""Official-calendar-first market session regression tests."""
from contextlib import ExitStack
from datetime import date, datetime, timezone
import sys
import types
from unittest import mock

import argus_market_clock as mc

sys.modules.setdefault("moomoo", types.SimpleNamespace(
    OpenQuoteContext=object, OpenSecTradeContext=object, RET_OK=0))
import scanner


def utc(y, m, d, hour=0, minute=0):
    return datetime(y, m, d, hour, minute, tzinfo=timezone.utc)


def test_jp_holiday_us_trading_day():
    now = utc(2026, 7, 20, 5, 0)  # 14:00 JST / 01:00 EDT
    jp = mc.market_session(mc.JP_EQUITY, now)
    us = mc.market_session(mc.US_EQUITY, now)
    assert jp["marketDate"] == "2026-07-20"
    assert jp["isTradingDay"] is False
    assert jp["session"] == "HOLIDAY_CLOSED"
    assert jp["holidayName"] == "Marine Day / 海の日"
    assert jp["nextTradingDay"] == "2026-07-21"
    assert us["marketDate"] == "2026-07-20"
    assert us["isTradingDay"] is True
    assert us["session"] == "OVERNIGHT_CLOSED"
    assert us["regularOpenJst"] == "2026-07-20T22:30:00+09:00"
    assert us["regularCloseJst"] == "2026-07-21T05:00:00+09:00"


def test_us_holiday_jp_trading_day():
    now = utc(2026, 6, 19, 14, 0)  # 23:00 JST / 10:00 EDT
    jp = mc.market_session(mc.JP_EQUITY, now)
    us = mc.market_session(mc.US_EQUITY, now)
    assert jp["isTradingDay"] is True
    assert jp["session"] == "POST_MARKET"
    assert us["isTradingDay"] is False
    assert us["session"] == "HOLIDAY_CLOSED"


def test_both_markets_trading_and_both_closed():
    assert mc.is_trading_day(mc.JP_EQUITY, date(2026, 7, 21))
    assert mc.is_trading_day(mc.US_EQUITY, date(2026, 7, 21))
    assert not mc.is_trading_day(mc.JP_EQUITY, date(2026, 1, 1))
    assert not mc.is_trading_day(mc.US_EQUITY, date(2026, 1, 1))


def test_jp_lunch_break():
    state = mc.market_session(mc.JP_EQUITY, utc(2026, 7, 21, 3, 0))
    assert state["session"] == "LUNCH_BREAK"


def test_us_dst_changes_jst_open_and_close():
    winter = mc.market_session(mc.US_EQUITY, utc(2026, 1, 15, 12))
    summer = mc.market_session(mc.US_EQUITY, utc(2026, 7, 20, 12))
    assert winter["regularOpenJst"].endswith("23:30:00+09:00")
    assert winter["regularCloseJst"].endswith("06:00:00+09:00")
    assert summer["regularOpenJst"].endswith("22:30:00+09:00")
    assert summer["regularCloseJst"].endswith("05:00:00+09:00")


def test_us_early_close():
    state = mc.market_session(mc.US_EQUITY, utc(2026, 11, 27, 15))
    assert state["earlyClose"] is True
    assert state["regularCloseJst"] == "2026-11-28T03:00:00+09:00"
    assert mc._local_close(
        mc.US_EQUITY, date(2026, 11, 27),
        utc(2026, 11, 27, 12)).hour == 18


def test_provider_closed_does_not_override_official_open():
    state = mc.market_session(
        mc.JP_EQUITY, utc(2026, 7, 21, 1),
        provider_status="CLOSED")
    assert state["isTradingDay"] is True
    assert state["session"] == "MORNING_SESSION"
    assert state["providerConflict"] is True
    assert state["providerRole"] == "auxiliary_only"


def test_provider_unavailable_still_uses_official_calendar():
    state = mc.market_session(mc.JP_EQUITY, utc(2026, 7, 20, 5))
    assert state["providerStatus"] is None
    assert state["session"] == "HOLIDAY_CLOSED"
    assert state["officialCalendar"] == "JPX_TSE"


def test_emergency_closure_and_next_trading_day():
    state = mc.market_session(
        mc.US_EQUITY, utc(2026, 7, 21, 15),
        extra_closures=("2026-07-21",))
    assert state["session"] == "EMERGENCY_CLOSED"
    assert state["nextTradingDay"] == "2026-07-22"


def test_holiday_price_pause_is_not_stale_failure():
    now = utc(2026, 7, 20, 5, 40)
    prior_jp_close = utc(2026, 7, 17, 6, 30)
    result = mc.quote_eligibility("7203", prior_jp_close, now)
    assert result["eligible"] is True
    assert result["quoteStatus"] == "official_close_current"


def test_fx_and_crypto_are_independent():
    us_holiday = utc(2026, 7, 3, 15)
    assert mc.market_session(mc.FX, us_holiday)["isTradingDay"] is True
    assert mc.market_session(mc.CRYPTO, utc(2026, 7, 4, 15))["session"] == "CONTINUOUS"


def test_scheduler_uses_independent_exchange_holidays():
    states = scanner._market_calendar_states(utc(2026, 7, 20, 5))
    missions = scanner.argus_scheduler.generate_daily_missions(
        session_date="2026-07-20",
        now_iso="2026-07-20T14:00:00+09:00",
        jp_holiday=not states["JP"]["isTradingDay"],
        us_holiday=not states["US"]["isTradingDay"])
    jp = [m for m in missions if m["market"] == "JP"]
    us = [m for m in missions if m["market"] == "US"]
    assert jp and all(m["status"] == "skipped" for m in jp)
    assert all(m["failureReasonRedacted"] == "market_holiday" for m in jp)
    assert us and all(m["status"] == "scheduled" for m in us)


def test_holiday_outcome_retry_is_suppressed():
    forecasts_before = list(scanner._FORECAST_LEDGER)
    outcomes_before = list(scanner._OUTCOME_LEDGER)
    try:
        scanner._FORECAST_LEDGER[:] = [{
            "id": "forecast-jp-holiday", "symbol": "7203", "market": "JP",
            "issuedAt": "2026-07-17T15:40:00+09:00",
            "forecastValue": "up", "forecastHorizon": "next_session",
        }]
        scanner._OUTCOME_LEDGER[:] = [{
            "id": "outcome-stable", "forecastId": "forecast-jp-holiday",
            "status": "unresolved", "resolutionState": "retry_pending",
            "retryCount": 2, "nextRetryAt": "2026-07-20T13:30:00+09:00",
        }]
        with mock.patch.object(
                scanner, "_price_history_cached",
                return_value=[{"date": "2026-07-17", "close": 100},
                              {"date": "2026-07-20", "close": 110}],
                create=True) as prices:
            resolved = scanner._dl_resolve_matured(
                "2026-07-20T14:00:00+09:00")
        assert resolved == 0
        assert scanner._OUTCOME_LEDGER[0]["id"] == "outcome-stable"
        assert scanner._OUTCOME_LEDGER[0]["retryCount"] == 2
        prices.assert_not_called()
    finally:
        scanner._FORECAST_LEDGER[:] = forecasts_before
        scanner._OUTCOME_LEDGER[:] = outcomes_before


def test_holiday_reaction_engine_expected_skip():
    with ExitStack() as stack:
        stack.enter_context(mock.patch.object(
            scanner, "_ai_now_iso",
            return_value="2026-07-20T14:00:00+09:00"))
        stack.enter_context(mock.patch.object(
            scanner, "_official_events_restore_once"))
        history = stack.enter_context(mock.patch.object(
            scanner, "_jq_price_history"))
        result = scanner._official_events_track()
    assert result["status"] == "expected_skip"
    assert result["reason"] == "market_holiday"
    history.assert_not_called()


def test_holiday_chart_state_is_not_mutated():
    before = scanner.argus_chart_intelligence.state_hash(
        scanner._CHART_INTELLIGENCE)
    with ExitStack() as stack:
        stack.enter_context(mock.patch.object(
            scanner, "_ai_now_iso",
            return_value="2026-07-20T14:00:00+09:00"))
        stack.enter_context(mock.patch.object(
            scanner, "_jq_price_history", return_value={}))
        stack.enter_context(mock.patch.object(
            scanner, "get_events_snapshot", return_value={"events": []}))
        report = scanner._chart_public_report("7203", "JP")
    assert report["stateUpdate"] == {
        "status": "expected_skip", "reason": "market_holiday"}
    assert scanner.argus_chart_intelligence.state_hash(
        scanner._CHART_INTELLIGENCE) == before
