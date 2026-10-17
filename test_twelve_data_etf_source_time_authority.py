"""Hostile source-time tests for Twelve Data ETF decision consumers.

Transport/cache freshness is deliberately held fresh in these tests.  A daily
bar is decision-usable only when the date attached to the latest close is an
exact, bounded US trading-session date.
"""
from datetime import datetime, timezone

import pytest

import scanner


NOW = datetime(2026, 8, 12, 12, 0, tzinfo=timezone.utc).timestamp()
LATEST_TRADING_DATE = "2026-08-11"
STALE_TRADING_DATE = "2020-08-11"


class _Resp:
    def __init__(self, body):
        self._body = body

    def raise_for_status(self):
        return None

    def json(self):
        return self._body


@pytest.fixture(autouse=True)
def _isolate_etf_state(monkeypatch):
    monkeypatch.setattr(scanner, "_TWELVEDATA_API_KEY", "test-key")
    monkeypatch.setattr(scanner.time, "time", lambda: NOW)
    monkeypatch.setattr(scanner, "_ETF_LAST_PRICE", {})
    monkeypatch.setattr(scanner, "_TD_TS_CACHE", {})
    monkeypatch.setattr(
        scanner, "_ALERT_ETF_CACHE", {"data": None, "expires": 0.0})
    monkeypatch.setattr(
        scanner, "_ALERTS_CACHE", {"data": None, "expires": 0.0})
    monkeypatch.setattr(scanner, "_SENSOR_ETF_CACHE", {"expires": 0.0})


def _values(latest_date, prior_date="2026-08-10"):
    return [
        {"datetime": latest_date, "close": "101"},
        {"datetime": prior_date, "close": "100"},
    ]


def _body(source_dates):
    return {
        symbol: {"status": "ok", "values": _values(source_date)}
        for symbol, source_date in source_dates.items()
    }


def _stash_row(source_date, *, now=NOW, price=101.0):
    return {
        "price": price,
        "m1d": 1.0,
        "ts": now,
        "source": "twelvedata",
        "sourceTimestamp": source_date,
        "receivedAt": "2026-08-12T12:00:00Z",
        "status": "delayed",
    }


def test_td_timeseries_rejects_all_2020_dates_despite_fresh_receipt(monkeypatch):
    symbols = ["SPY", "QQQ", "GLD"]
    old = {
        symbol: {
            "status": "ok",
            "values": _values("2020-08-11", "2020-08-10"),
        }
        for symbol in symbols
    }
    monkeypatch.setattr(
        scanner.requests, "get", lambda *_args, **_kwargs: _Resp(old))

    assert scanner._td_timeseries(symbols) == {}
    assert scanner._ETF_LAST_PRICE == {}


def test_td_timeseries_one_stale_symbol_cannot_hide_among_fresh_symbols(
        monkeypatch):
    symbols = ["SPY", "QQQ", "GLD"]
    monkeypatch.setattr(
        scanner.requests,
        "get",
        lambda *_args, **_kwargs: _Resp(_body({
            "SPY": LATEST_TRADING_DATE,
            "QQQ": STALE_TRADING_DATE,
            "GLD": LATEST_TRADING_DATE,
        })),
    )

    result = scanner._td_timeseries(symbols)

    assert set(result) == {"SPY", "GLD"}
    assert set(scanner._ETF_LAST_PRICE) == {"SPY", "GLD"}
    cached = scanner._TD_TS_CACHE[",".join(symbols)]
    assert set(cached["data"]) == {"SPY", "GLD"}


@pytest.mark.parametrize(
    "latest_row",
    [
        {"close": "101"},
        {"datetime": "not-a-date", "close": "101"},
        {"datetime": "2026-08-13", "close": "101"},
        {"datetime": "2026-08-09", "close": "101"},
    ],
    ids=["missing", "malformed", "future", "weekend"],
)
def test_td_timeseries_rejects_invalid_date_on_latest_close(
        monkeypatch, latest_row):
    # The second close has a legitimate date.  It must not be borrowed as the
    # source date for the newer first close when that first date is absent.
    response = {
        "SPY": {
            "status": "ok",
            "values": [latest_row, {
                "datetime": "2026-08-10", "close": "100"}],
        }
    }
    monkeypatch.setattr(
        scanner.requests, "get", lambda *_args, **_kwargs: _Resp(response))

    assert scanner._td_timeseries(["SPY"]) == {}
    assert "SPY" not in scanner._ETF_LAST_PRICE


def test_td_timeseries_accepts_valid_latest_completed_trading_date(monkeypatch):
    monkeypatch.setattr(
        scanner.requests,
        "get",
        lambda *_args, **_kwargs: _Resp(_body({
            "SPY": LATEST_TRADING_DATE,
        })),
    )

    assert scanner._td_timeseries(["SPY"]) == {"SPY": [101.0, 100.0]}
    assert scanner._ETF_LAST_PRICE["SPY"]["sourceTimestamp"] == \
        LATEST_TRADING_DATE


def test_td_timeseries_rejects_current_us_session_before_its_close(monkeypatch):
    # NOW is 08:00 EDT.  Aug 12 is a trading day, but it has not opened or
    # completed; date-only EOD evidence cannot exist for it yet.
    monkeypatch.setattr(
        scanner.requests,
        "get",
        lambda *_args, **_kwargs: _Resp(_body({"SPY": "2026-08-12"})),
    )

    assert scanner.argus_market_clock.latest_completed_session_date(
        scanner.argus_market_clock.US_EQUITY,
        datetime.fromtimestamp(NOW, timezone.utc)).isoformat() == \
        LATEST_TRADING_DATE
    assert scanner._td_timeseries(["SPY"]) == {}
    assert "SPY" not in scanner._ETF_LAST_PRICE


def test_td_cache_hit_reages_source_date_across_seven_day_boundary(monkeypatch):
    # 23:59 EDT on Aug 11: Aug 4 is exactly seven calendar days old.
    now = [datetime(2026, 8, 12, 3, 59, tzinfo=timezone.utc).timestamp()]
    monkeypatch.setattr(scanner.time, "time", lambda: now[0])
    calls = []

    def fetch(*_args, **_kwargs):
        calls.append(now[0])
        return _Resp(_body({"SPY": "2026-08-04"}))

    monkeypatch.setattr(scanner.requests, "get", fetch)
    assert set(scanner._td_timeseries(["SPY"])) == {"SPY"}

    # 00:01 EDT on Aug 12: the exact same bar is now eight calendar days old.
    # The transport cache remains fresh, but its payload authority has expired.
    now[0] += 120
    assert scanner._td_timeseries(["SPY"]) == {}
    assert "SPY" not in scanner._ETF_LAST_PRICE
    assert len(calls) == 1


def test_alert_momentum_and_action_cards_drop_one_stale_member(monkeypatch):
    scanner._ETF_LAST_PRICE.update({
        "GLD": _stash_row(LATEST_TRADING_DATE),
        "TLT": _stash_row(STALE_TRADING_DATE),
        "XLRE": _stash_row(LATEST_TRADING_DATE),
    })
    monkeypatch.setattr(
        scanner,
        "_td_timeseries",
        lambda _symbols: {
            "GLD": [101.0, 100.0],
            "TLT": [101.0, 100.0],
            "XLRE": [101.0, 100.0],
        },
    )

    momentum = scanner._alert_etf_momentum()
    assert set(momentum) == {"GLD", "XLRE"}

    monkeypatch.setattr(scanner, "get_action_labels", lambda: {
        "marketPosture": {"label": "MIXED"}, "labels": []})
    monkeypatch.setattr(scanner, "get_market_regime_snapshot", lambda: {
        "rotationGroups": [], "ratesBackdrop": {}})
    monkeypatch.setattr(scanner, "get_rates_snapshot", lambda: {})
    monkeypatch.setattr(
        scanner, "get_crypto_watchlist_snapshot", lambda _ids: {"quotes": []})

    cards = {
        row["assetClass"]: row for row in scanner.get_action_alerts()["cards"]}
    # A daily bar stays explicitly partial/delayed, but it is usable for the
    # bounded momentum calculation.  The stale member has no such data point.
    assert cards["GOLD"]["status"] == "partial"
    assert cards["GOLD"]["dataPoints"]
    assert cards["REIT"]["status"] == "partial"
    assert cards["REIT"]["dataPoints"]
    assert cards["BOND"]["status"] == "partial"
    assert cards["BOND"]["dataPoints"] == []


def test_alert_cache_hit_reages_source_date_at_seven_day_boundary(monkeypatch):
    now = [datetime(2026, 8, 12, 3, 59, tzinfo=timezone.utc).timestamp()]
    monkeypatch.setattr(scanner.time, "time", lambda: now[0])
    scanner._ETF_LAST_PRICE["GLD"] = _stash_row(
        "2026-08-04", now=now[0])
    monkeypatch.setattr(
        scanner, "_td_timeseries", lambda _symbols: {"GLD": [101.0, 100.0]})

    assert set(scanner._alert_etf_momentum()) == {"GLD"}
    assert scanner._ALERT_ETF_CACHE["expires"] > now[0] + 120

    now[0] += 120
    assert scanner._alert_etf_momentum() == {}


def _stub_prediction_dependencies(monkeypatch):
    monkeypatch.setattr(scanner, "get_action_labels", lambda: {
        "marketPosture": {"label": "RISK_ON"}, "labels": []})
    monkeypatch.setattr(
        scanner, "get_japan_watchlist_snapshot",
        lambda *_args, **_kwargs: {"stocks": []})
    monkeypatch.setattr(
        scanner, "get_us_watchlist_snapshot",
        lambda *_args, **_kwargs: {"stocks": []})
    monkeypatch.setattr(scanner, "get_market_regime_snapshot", lambda: {
        "regime": {}, "ratesBackdrop": {}})
    monkeypatch.setattr(scanner, "get_rates_snapshot", lambda: {})
    monkeypatch.setattr(scanner, "_fred_vix_history", lambda: [])
    monkeypatch.setattr(
        scanner, "_canonical_vix_assess", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(scanner, "_alert_etf_momentum", lambda: {})
    monkeypatch.setattr(scanner, "_ensure_sensor_etfs", lambda: None)
    monkeypatch.setattr(
        scanner, "get_crypto_watchlist_snapshot", lambda _ids: {"quotes": []})
    monkeypatch.setattr(
        scanner,
        "_canonical_prediction_ledger_projection",
        lambda **_kwargs: {"status": "INCOMPLETE"},
    )
    monkeypatch.setattr(
        scanner, "_AI_RESULT_CACHE", {"data": None, "expires": 0.0})


def test_prediction_snapshot_omits_stale_class_sensor_and_posture(monkeypatch):
    _stub_prediction_dependencies(monkeypatch)
    scanner._ETF_LAST_PRICE.update({
        "SPY": _stash_row(STALE_TRADING_DATE),
        "GLD": _stash_row(LATEST_TRADING_DATE),
    })

    snapshot = scanner.get_prediction_snapshot()

    assert {row["symbol"] for row in snapshot["classPredictions"]} == {"GLD"}
    assert {row["sensor"] for row in snapshot["sensors"]} == {"GLD"}
    assert snapshot["posturePrediction"] is None


def test_prediction_snapshot_uses_valid_daily_class_sensor_and_posture(monkeypatch):
    _stub_prediction_dependencies(monkeypatch)
    scanner._ETF_LAST_PRICE["SPY"] = _stash_row(LATEST_TRADING_DATE)

    snapshot = scanner.get_prediction_snapshot()

    assert {row["symbol"] for row in snapshot["classPredictions"]} == {"SPY"}
    assert {row["sensor"] for row in snapshot["sensors"]} == {"SPY"}
    assert snapshot["posturePrediction"] == {
        "posture": "RISK_ON", "proxy": "SPY", "price": 101.0,
        "rule": {"type": "direction", "sign": 1},
    }


def _stub_quote_route_dependencies(monkeypatch):
    monkeypatch.setattr(
        scanner, "get_japan_watchlist_snapshot",
        lambda *_args, **_kwargs: {"stocks": []})
    monkeypatch.setattr(scanner, "get_market_regime_snapshot", lambda: {})
    monkeypatch.setattr(scanner, "_alert_etf_momentum", lambda: {})
    monkeypatch.setattr(scanner, "_ensure_sensor_etfs", lambda: None)
    monkeypatch.setattr(
        scanner, "get_crypto_watchlist_snapshot", lambda _ids: {"quotes": []})
    monkeypatch.setattr(scanner, "get_rates_snapshot", lambda: {})


@pytest.mark.parametrize(
    "invalid_date",
    [None, "2020-08-11", "bad-date", "2026-08-13", "2026-08-09"],
    ids=["missing", "stale", "malformed", "future", "weekend"],
)
def test_quote_routes_omit_source_invalid_etf_stash(monkeypatch, invalid_date):
    _stub_quote_route_dependencies(monkeypatch)
    scanner._ETF_LAST_PRICE.update({
        "SPY": _stash_row(invalid_date),
        "GLD": _stash_row(LATEST_TRADING_DATE),
    })
    client = scanner.app.test_client()

    sensor_quotes = client.get("/api/argus/sensor-quotes").get_json()["quotes"]
    class_quotes = client.get("/api/argus/class-quotes").get_json()["quotes"]

    assert "SPY" not in sensor_quotes
    assert "SPY" not in class_quotes
    assert sensor_quotes["GLD"] == 101.0
    assert class_quotes["GLD"]["price"] == 101.0


def test_ensure_sensor_etfs_rechecks_cached_gate_after_source_boundary(
        monkeypatch):
    now = [datetime(2026, 8, 12, 3, 59, tzinfo=timezone.utc).timestamp()]
    monkeypatch.setattr(scanner.time, "time", lambda: now[0])
    scanner._ETF_LAST_PRICE.update({
        symbol: _stash_row("2026-08-04", now=now[0])
        for symbol in scanner._SENSOR_ETF_EXTRA
    })
    calls = []
    monkeypatch.setattr(
        scanner, "_td_timeseries", lambda symbols: calls.append(list(symbols)) or {})

    scanner._ensure_sensor_etfs()
    assert calls == []
    assert scanner._SENSOR_ETF_CACHE["expires"] > now[0] + 120

    now[0] += 120
    scanner._ensure_sensor_etfs()
    assert calls == [scanner._SENSOR_ETF_EXTRA]
