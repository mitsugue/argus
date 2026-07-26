import datetime as dt
import time
import types
from unittest import mock

import argus_asset_chart_cache as asset_cache

import sys
sys.modules.setdefault("moomoo", types.SimpleNamespace(
    OpenQuoteContext=object, OpenSecTradeContext=object, RET_OK=0))
import scanner


def chart_rows(count=320):
    rows = []
    day = dt.date(2025, 1, 1)
    price = 100.0
    while len(rows) < count:
        if day.weekday() < 5:
            price += 0.2
            rows.append({
                "date": day.isoformat(),
                "availableFrom": day.isoformat(),
                "open": price - 0.1,
                "high": price + 1.0,
                "low": price - 1.0,
                "close": price,
                "volume": 1_000_000 + len(rows),
                "adjusted": False,
            })
        day += dt.timedelta(days=1)
    return rows


def test_target_universe_is_bounded_public_watchlist_and_5803_first():
    targets = scanner._asset_chart_targets()
    assert targets[0] == ("5803", "JP")
    assert len(targets) == (
        len(scanner._JP_WATCHLIST) + len(scanner._US_WATCHLIST))
    assert set(targets) == {
        (str(item["symbol"]).upper(), market)
        for market, items in (
            ("JP", scanner._JP_WATCHLIST),
            ("US", scanner._US_WATCHLIST),
        )
        for item in items
    }


def test_natural_tick_publishes_daily_and_weekly_and_get_is_provider_free():
    saved_store = asset_cache.normalize_store(scanner._ASSET_CHART_REPORTS)
    scanner._ASSET_CHART_REPORTS.clear()
    scanner._ASSET_CHART_REPORTS.update(asset_cache.empty_store())
    rows = chart_rows()

    def cached_history(symbol, market):
        return rows if (symbol, market) in {
            ("5803", "JP"), ("1306", "JP"),
        } else []

    try:
        with mock.patch.object(
                scanner, "_chart_history_cached",
                side_effect=cached_history), \
                mock.patch.object(
                    scanner, "_chart_history",
                    side_effect=AssertionError("provider path called")), \
                mock.patch.object(
                    scanner, "get_events_snapshot",
                    return_value={"events": []}), \
                mock.patch.object(
                    scanner, "_jp_daily_short_history", return_value=[]), \
                mock.patch.object(scanner, "_journal"):
            tick = scanner._precompute_asset_chart_tick()
        assert tick["status"] == "published"
        assert tick["instrument"] == "5803"
        assert [item["timeframe"] for item in tick["publications"]] == [
            "daily", "weekly"]
        daily = asset_cache.current(
            scanner._ASSET_CHART_REPORTS, "JP", "5803", "daily")
        weekly = asset_cache.current(
            scanner._ASSET_CHART_REPORTS, "JP", "5803", "weekly")
        assert daily and weekly
        assert daily["datasetHash"] == weekly["datasetHash"]

        with mock.patch.object(
                scanner, "_chart_public_report",
                side_effect=AssertionError("GET recomputed report")), \
                mock.patch.object(
                    scanner, "_chart_history",
                    side_effect=AssertionError("GET called provider")):
            response = scanner.app.test_client().get(
                "/api/argus/chart-intelligence?"
                "scope=asset&symbol=5803&market=JP&timeframe=daily")
        assert response.status_code == 200
        assert response.json["assetChartCache"]["status"] == "hit"
        assert response.json["automaticAiCalls"] == 0
        assert len(response.json["indicators"]["bars"]) == len(rows)

        scanner._ASSET_CHART_REPORTS["cursor"] = 0
        with mock.patch.object(
                scanner, "_chart_history_cached",
                side_effect=cached_history), \
                mock.patch.object(
                    scanner, "_chart_public_report",
                    side_effect=AssertionError(
                        "unchanged dataset recomputed")):
            unchanged = scanner._precompute_asset_chart_tick()
        assert unchanged["status"] == "unchanged"
        assert unchanged["generated"] is False
    finally:
        scanner._ASSET_CHART_REPORTS.clear()
        scanner._ASSET_CHART_REPORTS.update(saved_store)


def test_target_get_requires_completed_report_not_warm_raw_cache():
    saved_store = asset_cache.normalize_store(scanner._ASSET_CHART_REPORTS)
    scanner._ASSET_CHART_REPORTS.clear()
    scanner._ASSET_CHART_REPORTS.update(asset_cache.empty_store())
    try:
        with mock.patch.object(
                scanner, "_chart_history_cached",
                return_value=chart_rows()), \
                mock.patch.object(
                    scanner, "_chart_public_report",
                    side_effect=AssertionError("GET assembled warm raw cache")):
            response = scanner.app.test_client().get(
                "/api/argus/chart-intelligence?"
                "scope=asset&symbol=5803&market=JP&timeframe=daily")
        assert response.status_code == 200
        assert response.json["status"] == "expected_skip"
        assert response.json["stateUpdate"]["reason"] == \
            "price_cache_unavailable"
        assert response.json["assetChartCache"]["status"] == "miss"
    finally:
        scanner._ASSET_CHART_REPORTS.clear()
        scanner._ASSET_CHART_REPORTS.update(saved_store)


def test_bounded_jp_provider_seed_normalizes_without_exposing_auth():
    raw = [{
        "Date": (dt.date(2026, 1, 1) + dt.timedelta(days=index)).isoformat(),
        "O": 100 + index, "H": 102 + index, "L": 99 + index,
        "C": 101 + index, "Vo": 1000 + index,
    } for index in range(30)]
    scanner._ASSET_CHART_SOURCE_CACHE.clear()
    with mock.patch.object(scanner, "_JQUANTS_API_KEY", "configured"), \
            mock.patch.object(
                scanner, "_jquants_paginated", return_value=raw) as fetch:
        rows, source = scanner._asset_chart_provider_history("5803", "JP")
    assert len(rows) == 30
    assert source == {
        "source": "bounded_provider_seed",
        "status": "live",
        "errorClass": None,
    }
    assert rows[-1]["close"] == 130.0
    assert fetch.call_args.kwargs["max_pages"] == 2
    assert fetch.call_args.kwargs["request_timeout"] == 8
    assert fetch.call_args.args[1]["code"] == "5803"
    assert len(fetch.call_args.args[1]["from"]) == 10
    scanner._ASSET_CHART_SOURCE_CACHE.clear()


def test_tick_time_guard_skips_provider_seed():
    saved_store = asset_cache.normalize_store(scanner._ASSET_CHART_REPORTS)
    scanner._ASSET_CHART_REPORTS.clear()
    scanner._ASSET_CHART_REPORTS.update(asset_cache.empty_store())
    try:
        with mock.patch.object(
                scanner, "_chart_history_cached", return_value=[]), \
                mock.patch.object(
                    scanner, "_asset_chart_provider_history",
                    side_effect=AssertionError("provider seed crossed deadline")):
            result = scanner._precompute_asset_chart_tick(
                deadline_monotonic=time.monotonic() + 5)
        assert result["status"] == "expected_skip"
        assert result["reason"] == "insufficient_tick_time"
    finally:
        scanner._ASSET_CHART_REPORTS.clear()
        scanner._ASSET_CHART_REPORTS.update(saved_store)
