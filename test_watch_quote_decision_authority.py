"""Hostile contracts for watch-quote decision authority.

Transport freshness and a numeric value can never make a source-invalid bridge
row actionable.  Current-move and prediction consumers additionally require the
exact latest completed exchange session for delayed daily evidence.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import argus_market_clock
import pytest
import scanner


NOW = datetime(2026, 8, 16, 3, 0, tzinfo=timezone.utc).timestamp()


def _latest(market):
    return argus_market_clock.latest_completed_session_date(
        market, datetime.fromtimestamp(NOW, timezone.utc)).isoformat()


def _live(symbol="AAPL", market="US", change=4.0):
    return {
        "symbol": symbol,
        "market": market,
        "name": symbol,
        "price": 100.0,
        "changePct": change,
        "volume": 1_000,
        "date": _latest(
            argus_market_clock.JP_EQUITY
            if market == "JP" else argus_market_clock.US_EQUITY),
        "source": "moomoo-rt",
        "sourceTimestamp": NOW - 30,
        "exchangeTs": NOW - 30,
        "entitlement": "realtime",
        "status": "live",
        "realtimeEvidence": True,
    }


def _daily(symbol="7203", market="JP", change=4.0, *, source="jquants",
           date=None):
    market_id = (argus_market_clock.JP_EQUITY
                 if market == "JP" else argus_market_clock.US_EQUITY)
    date = date or _latest(market_id)
    return {
        "symbol": symbol,
        "market": market,
        "name": symbol,
        "price": 100.0,
        "changePct": change,
        "volume": 1_000,
        "date": date,
        "sourceTimestamp": date,
        "source": source,
        "status": "delayed",
        "realtimeEvidence": False,
    }


def _invalid_bridge(symbol="AAPL", market="US", source_timestamp=None,
                    change=6.0):
    return {
        "symbol": symbol,
        "market": market,
        "name": symbol,
        "price": 100.0,
        "changePct": change,
        "volume": 1_000,
        "date": _latest(
            argus_market_clock.JP_EQUITY
            if market == "JP" else argus_market_clock.US_EQUITY),
        "source": "moomoo-rt",
        "sourceTimestamp": source_timestamp,
        "exchangeTs": source_timestamp,
        "entitlement": "realtime",
        "status": "delayed",
        "realtimeEvidence": False,
    }


def test_watch_quote_authority_separates_live_and_bounded_daily_truth():
    assert scanner._decision_usable_watch_quote_row(
        _live(), "US", now_epoch=NOW)["decisionUsable"] is True
    delayed = scanner._decision_usable_watch_quote_row(
        _daily(), "JP", now_epoch=NOW, require_latest_completed=True)
    assert delayed["decisionSourceKind"] == "bounded_daily_close"
    assert delayed["realtimeEvidence"] is False


def test_watch_quote_authority_rejects_source_invalid_bridge_rows():
    for timestamp in (None, NOW + 1, NOW - 3_600, "not-a-time"):
        assert scanner._decision_usable_watch_quote_row(
            _invalid_bridge(source_timestamp=timestamp), "US",
            now_epoch=NOW) is None


def test_watch_quote_authority_requires_latest_completed_daily_session():
    previous_day = datetime.fromisoformat(
        _latest(argus_market_clock.JP_EQUITY)).date() - timedelta(days=1)
    while not argus_market_clock.is_trading_day(
            argus_market_clock.JP_EQUITY, previous_day):
        previous_day -= timedelta(days=1)
    previous = previous_day.isoformat()
    row = _daily(date=previous)
    assert scanner._decision_usable_watch_quote_row(
        row, "JP", now_epoch=NOW, require_latest_completed=False) is not None
    assert scanner._decision_usable_watch_quote_row(
        row, "JP", now_epoch=NOW, require_latest_completed=True) is None


def _stub_action_dependencies(monkeypatch):
    monkeypatch.setattr(scanner.time, "time", lambda: NOW)
    monkeypatch.setattr(scanner, "get_rates_snapshot", lambda: {
        "status": "live", "ratesPressure": "Neutral"})
    monkeypatch.setattr(scanner, "_rates_posture", lambda _r: "neutral")
    monkeypatch.setattr(scanner, "get_japan_watchlist_snapshot", lambda *_a: {
        "status": "live", "stocks": []})
    monkeypatch.setattr(scanner, "get_events_snapshot", lambda **_k: {
        "status": "live", "events": []})
    monkeypatch.setattr(scanner, "get_market_regime_snapshot", lambda: {
        "status": "partial", "regime": {"label": "CAUTIOUS"}})
    monkeypatch.setattr(scanner, "_ledger_summary", lambda: None)
    monkeypatch.setattr(scanner, "_visibility_guard", lambda: {})
    monkeypatch.setattr(scanner, "_events_active_list", lambda: [])
    monkeypatch.setattr(
        scanner, "_learning_memory_compact_for_symbol", lambda *_a: None)


def test_action_labels_fail_closed_for_source_invalid_bridge(monkeypatch):
    _stub_action_dependencies(monkeypatch)
    monkeypatch.setattr(scanner, "get_us_watchlist_snapshot", lambda *_a: {
        "status": "delayed", "stocks": [_invalid_bridge()]})

    label = scanner.get_action_labels(
        jp_symbols=[], us_symbols=["AAPL"])["labels"][0]

    assert label["action"] == "HOLD"
    assert label["confidence"] == 0.2
    assert label["status"] == "mock"
    assert label["supportingData"]["price"] is None
    assert label["supportingData"]["changePct"] is None


def test_action_labels_keep_explicit_bounded_daily_close(monkeypatch):
    _stub_action_dependencies(monkeypatch)
    row = _daily("AAPL", "US", -3.0, source="twelvedata")
    monkeypatch.setattr(scanner, "get_us_watchlist_snapshot", lambda *_a: {
        "status": "delayed", "stocks": [row]})

    label = scanner.get_action_labels(
        jp_symbols=[], us_symbols=["AAPL"])["labels"][0]

    assert label["status"] == "delayed"
    assert label["supportingData"]["price"] == 100.0
    assert label["supportingData"]["changePct"] == -3.0
    assert label["confidence"] > 0.2


def test_layer2b_uses_exact_session_and_source_authority(monkeypatch):
    monkeypatch.setattr(scanner.time, "time", lambda: NOW)
    monkeypatch.setattr(scanner, "get_japan_watchlist_snapshot", lambda *_a: {
        "stocks": [
            _daily("7203", "JP", 1.0),
            _invalid_bridge("9984", "JP", None, 9.0),
        ]})
    monkeypatch.setattr(scanner, "get_us_watchlist_snapshot", lambda *_a: {
        "stocks": [_live("AAPL", "US", 2.0)]})
    monkeypatch.setattr(scanner, "get_crypto_watchlist_snapshot", lambda *_a: {
        "quotes": []})

    result = scanner._layer2b_live_prices([
        {"symbol": "7203", "market": "JP"},
        {"symbol": "9984", "market": "JP"},
        {"symbol": "AAPL", "market": "US"},
    ])

    assert result == {
        "7203": (100.0, 1.0, "JP"),
        "AAPL": (100.0, 2.0, "US"),
    }


def test_active_movers_ignore_source_invalid_watch_rows(monkeypatch):
    monkeypatch.setattr(scanner.time, "time", lambda: NOW)
    monkeypatch.setattr(scanner, "get_downside_incidents", lambda: {
        "incidents": []})
    monkeypatch.setattr(scanner, "get_japan_watchlist_snapshot", lambda: {
        "stocks": [
            _daily("7203", "JP", 4.0),
            _invalid_bridge("9984", "JP", None, 12.0),
        ]})
    monkeypatch.setattr(scanner, "get_us_watchlist_snapshot", lambda: {
        "stocks": [_invalid_bridge("AAPL", "US", NOW - 3_600, 15.0)]})
    monkeypatch.setattr(scanner, "_moomoo_us_movers", lambda: [])
    monkeypatch.setattr(scanner, "_YAHOO_MOVERS_CACHE", {"data": None})

    result = scanner._collect_active_movers()

    assert [(row["market"], row["symbol"]) for row in result] == [
        ("JP", "7203")]


def test_cause_attribution_excludes_invalid_target_and_peer_quotes(monkeypatch):
    monkeypatch.setattr(scanner.time, "time", lambda: NOW)
    monkeypatch.setattr(scanner, "get_japan_watchlist_snapshot", lambda: {
        "stocks": []})
    monkeypatch.setattr(scanner, "get_us_watchlist_snapshot", lambda: {
        "stocks": [
            _invalid_bridge("NVDA", "US", None, -8.0),
            _invalid_bridge("SMH", "US", NOW - 3_600, -6.0),
        ]})
    monkeypatch.setattr(scanner, "get_catalysts_snapshot", lambda: {
        "items": []})
    monkeypatch.setattr(scanner, "get_company_news", lambda *_a: [])
    monkeypatch.setattr(scanner, "get_market_news", lambda: {
        "status": "unavailable", "items": []})

    result = scanner.get_cause_attribution("NVDA", "US")

    assert result["changePct"] is None
    assert (result.get("contagion") or {}).get("peerCount", 0) == 0


def _jp_close_epoch():
    now_utc = datetime.fromtimestamp(NOW, timezone.utc)
    session_date = argus_market_clock.latest_completed_session_date(
        argus_market_clock.JP_EQUITY, now_utc)
    return argus_market_clock._local_close(
        argus_market_clock.JP_EQUITY, session_date, now_utc).timestamp()


def test_jp_sector_rotation_rejects_timestamp_less_yahoo_rows(monkeypatch):
    monkeypatch.setattr(scanner.time, "time", lambda: NOW)
    monkeypatch.setattr(scanner, "_yahoo_jp_row", lambda code, name: {
        "symbol": code, "name": name, "price": 100.0,
        "changePct": 11.0, "date": None, "sourceTimestamp": None,
        "source": "yahoo-delayed", "status": "delayed",
    })

    groups = scanner._jp_sector_rotation()

    assert groups and all(row["available"] is False for row in groups)
    assert all(row["momentum1d"] is None for row in groups)


def test_jp_sector_rotation_accepts_exact_latest_completed_source(monkeypatch):
    monkeypatch.setattr(scanner.time, "time", lambda: NOW)
    source_epoch = _jp_close_epoch()
    source_iso = datetime.fromtimestamp(
        source_epoch, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    source_date = datetime.fromtimestamp(
        source_epoch, scanner.TZ_JST).date().isoformat()
    monkeypatch.setattr(scanner, "_yahoo_jp_row", lambda code, name: {
        "symbol": code, "name": name, "price": 100.0,
        "changePct": 1.5, "date": source_date,
        "sourceTimestamp": source_iso,
        "source": "yahoo-delayed", "status": "delayed",
    })

    groups = scanner._jp_sector_rotation()

    assert groups and all(row["available"] is True for row in groups)
    assert all(row["momentum1d"] == 1.5 for row in groups)
    assert all(row["validUntil"] for row in groups)


def test_regime_cache_expires_at_jp_watch_source_deadline(monkeypatch):
    now = [NOW]
    monkeypatch.setattr(scanner.time, "time", lambda: now[0])
    monkeypatch.setattr(scanner, "_REGIME_CACHE", {
        "data": None, "expires": 0.0})
    monkeypatch.setattr(scanner, "_REGIME_LAST_GOOD", {
        "data": None, "ts": 0.0})
    monkeypatch.setattr(scanner, "_ETF_LAST_PRICE", {
        symbol: {"sourceTimestamp": now[0] - 60}
        for symbol in scanner._REGIME_ETFS
    })
    series = {
        symbol: [100.0] * scanner._REGIME_ETF_REQUIRED_BARS
        for symbol in scanner._REGIME_ETFS
    }
    monkeypatch.setattr(
        scanner, "_etf_series_with_moomoo", lambda _symbols: series)
    monkeypatch.setattr(scanner, "get_events_snapshot", lambda: {"events": []})
    monkeypatch.setattr(scanner, "_jp_sector_rotation", lambda: [])
    monkeypatch.setattr(scanner, "get_rates_snapshot", lambda: {
        "status": "live",
        "us10y": {"latestValue": 4.0, "change": 0.0},
        "us2y": {"latestValue": 3.8},
        "usReal10y": {"latestValue": 2.0},
        "vix": {"latestValue": 15.0},
        "hyOas": {"latestValue": 3.0, "change": 0.0},
    })
    calls = []

    def jp_snapshot():
        calls.append(now[0])
        return {"status": "live", "stocks": [{
            **_live("7203", "JP", 2.0),
            "sourceTimestamp": NOW - 1_199,
            "exchangeTs": NOW - 1_199,
        }]}

    monkeypatch.setattr(scanner, "get_japan_watchlist_snapshot", jp_snapshot)

    first = scanner.get_market_regime_snapshot()
    assert first["jpWatchEvidence"]["decisionUsableCount"] == 1
    assert first["jpIntradayOverlay"] is not None
    assert now[0] < scanner._REGIME_CACHE["expires"] <= now[0] + 1

    now[0] += 2
    second = scanner.get_market_regime_snapshot()
    assert len(calls) == 2
    assert second["jpWatchEvidence"]["decisionUsableCount"] == 0
    assert second["jpIntradayOverlay"] is None
    assert second["sourceStatuses"]["jquants"] == "unavailable"
    assert not any("日本株ウォッチリスト" in item
                   for item in second["supportingEvidence"])


def test_legacy_scheduler_uses_canonical_us_holiday_calendar():
    assert scanner.is_us_trading_day(datetime(
        2026, 6, 18, 16, tzinfo=timezone.utc)) is True
    assert scanner.is_us_trading_day(datetime(
        2026, 6, 19, 16, tzinfo=timezone.utc)) is False  # Juneteenth
    assert scanner.is_us_trading_day(datetime(
        2026, 7, 3, 16, tzinfo=timezone.utc)) is False  # observed July 4
    assert scanner.is_us_trading_day(datetime(
        2026, 8, 16, 16, tzinfo=timezone.utc)) is False  # Sunday
    assert scanner.is_us_trading_day(datetime(2026, 6, 18)) is False


def _stub_evidence_pack_dependencies(monkeypatch):
    monkeypatch.setattr(scanner.time, "time", lambda: NOW)
    monkeypatch.setattr(scanner, "_visibility_guard_cached_only", lambda: {
        "visibilityLevel": "full", "reasonCodes": [],
        "blockedActions": []})
    monkeypatch.setattr(scanner, "_events_active_list", lambda: [])
    monkeypatch.setattr(scanner, "_tdnet_recent_cached_only", lambda: {
        "bySymbol": {}})
    monkeypatch.setattr(scanner.argus_caos_audit, "snapshot", lambda **_k: {
        "items": []})
    monkeypatch.setattr(scanner, "_source_coverage_cached_only", lambda: {
        "summary": {"totalItems": 0, "canGroundJudgmentItems": 0,
                    "weakSignalItems": 0}})
    monkeypatch.setattr(scanner, "_market_depth_proof_cached_only", lambda: {
        "summary": {"trueDepthLiveCount": 0,
                    "computedIndicatorsLiveCount": 0,
                    "requiresContractCount": 0}})
    monkeypatch.setattr(scanner, "_official_events_by_symbol", lambda *_a, **_k: [])
    monkeypatch.setattr(
        scanner, "_learning_memory_compact_for_symbol", lambda *_a: None)
    monkeypatch.setattr(scanner, "_INTEL_STORE", [])


@pytest.mark.parametrize("source_timestamp", [
    None, NOW + 1, NOW - 3_600, "not-a-time",
])
def test_evidence_pack_cannot_ground_on_source_invalid_quote(
        monkeypatch, source_timestamp):
    _stub_evidence_pack_dependencies(monkeypatch)
    monkeypatch.setattr(scanner, "_quote_cached_only", lambda *_a: {
        **_invalid_bridge(source_timestamp=source_timestamp),
        "decisionUsable": False,
    })

    pack = scanner._build_evidence_pack("AAPL", "US")

    assert pack["quote"] == {}
    assert pack["allowedUse"]["canGroundJudgment"] is False
    assert "cache:quote" in pack["missingConfirmations"]


def test_evidence_pack_keeps_exact_source_current_quote(monkeypatch):
    _stub_evidence_pack_dependencies(monkeypatch)
    monkeypatch.setattr(scanner, "_quote_cached_only", lambda *_a: _live())

    pack = scanner._build_evidence_pack("AAPL", "US")

    assert pack["quote"]["price"] == 100.0
    assert pack["allowedUse"]["canGroundJudgment"] is True
    assert "cache:quote" not in pack["missingConfirmations"]
