"""Hostile source-time tests for legacy provider decision paths.

These old helpers intentionally retain their public return shapes, but provider
success and numeric payloads cannot substitute for a current provider timestamp.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

import scanner


NOW = 1_800_000_000.0
# NOW is Friday 2027-01-15 03:00 ET, before the US session.  Thursday's
# 16:00 ET close is therefore the one exact latest-completed daily session.
LATEST_COMPLETED_DAILY = datetime(
    2027, 1, 14, 21, 0, tzinfo=timezone.utc).timestamp()
PREVIOUS_COMPLETED_DAILY = datetime(
    2027, 1, 13, 21, 0, tzinfo=timezone.utc).timestamp()
OLDER_COMPLETED_DAILY = datetime(
    2027, 1, 12, 21, 0, tzinfo=timezone.utc).timestamp()
LEGACY_QUOTE_KEYS = {
    "current", "open", "high", "low", "prev_close", "change_pct", "volume",
}
LEGACY_MACRO_KEYS = {
    "vix", "vix_20d_avg", "vix_spike_pct", "fear_level",
    "sp500_change", "alerts",
}
LEGACY_OPEND_PRICE_KEYS = {
    "current", "open", "high", "low", "volume", "change_pct",
}


def _finnhub_quote(timestamp, *, current=102.0, previous=100.0):
    row = {
        "c": current,
        "o": 100.5,
        "h": 103.0,
        "l": 99.5,
        "pc": previous,
    }
    if timestamp is not _MISSING:
        row["t"] = timestamp
    return row


class _Missing:
    pass


_MISSING = _Missing()


def _invalid_timestamps():
    return [
        pytest.param(_MISSING, id="missing"),
        pytest.param("not-a-timestamp", id="malformed"),
        pytest.param(NOW + 60, id="future"),
        pytest.param(
            NOW - scanner._DECISION_QUOTE_LIVE_MAX_AGE_SEC - 1,
            id="stale",
        ),
    ]


def test_legacy_get_quote_accepts_only_exact_current_finnhub_timestamp(
        monkeypatch):
    monkeypatch.setattr(scanner.time, "time", lambda: NOW)
    calls = []

    def finnhub_get(endpoint, params=None):
        calls.append((endpoint, params))
        return _finnhub_quote(NOW - 30)

    monkeypatch.setattr(scanner, "finnhub_get", finnhub_get)

    result = scanner.get_quote("AAPL")

    assert calls == [("quote", {"symbol": "AAPL"})]
    assert set(result) == LEGACY_QUOTE_KEYS
    assert result["current"] == 102.0
    assert result["open"] == 100.5
    assert result["high"] == 103.0
    assert result["low"] == 99.5
    assert result["prev_close"] == 100.0
    assert result["change_pct"] == 2.0


@pytest.mark.parametrize("timestamp", _invalid_timestamps())
def test_legacy_get_quote_rejects_invalid_finnhub_source_time(
        monkeypatch, timestamp):
    monkeypatch.setattr(scanner.time, "time", lambda: NOW)
    monkeypatch.setattr(
        scanner, "finnhub_get",
        lambda *_args, **_kwargs: _finnhub_quote(timestamp),
    )

    assert scanner.get_quote("AAPL") is None


def _candle_payload(latest_timestamp):
    payload = {
        "s": "ok",
        "o": [99.0, 100.0],
        "h": [101.0, 103.0],
        "l": [98.0, 99.5],
        "c": [100.0, 102.0],
        "v": [100_000, 123_456],
    }
    if latest_timestamp is not _MISSING:
        payload["t"] = [PREVIOUS_COMPLETED_DAILY, latest_timestamp]
    return payload


def test_get_stock_candles_accepts_exact_latest_completed_us_daily_session(
        monkeypatch):
    monkeypatch.setattr(scanner.time, "time", lambda: NOW)
    calls = []

    def finnhub_get(endpoint, params=None):
        calls.append((endpoint, dict(params or {})))
        return _candle_payload(LATEST_COMPLETED_DAILY)

    monkeypatch.setattr(scanner, "finnhub_get", finnhub_get)

    result = scanner.get_stock_candles("AAPL", resolution="D", days=30)

    assert calls == [("stock/candle", {
        "symbol": "AAPL",
        "resolution": "D",
        "from": int(NOW) - 30 * 86400,
        "to": int(NOW),
    })]
    assert result == [
        {
            "timestamp": PREVIOUS_COMPLETED_DAILY,
            "open": 99.0,
            "high": 101.0,
            "low": 98.0,
            "close": 100.0,
            "volume": 100_000,
        },
        {
            "timestamp": LATEST_COMPLETED_DAILY,
            "open": 100.0,
            "high": 103.0,
            "low": 99.5,
            "close": 102.0,
            "volume": 123_456,
        },
    ]
    assert all(set(row) == {
        "timestamp", "open", "high", "low", "close", "volume",
    } for row in result)


@pytest.mark.parametrize(
    "latest_timestamp",
    [
        pytest.param(_MISSING, id="missing"),
        pytest.param("not-a-timestamp", id="malformed"),
        pytest.param(NOW + 60, id="future"),
        pytest.param(NOW - 30, id="current-uncompleted-session"),
        pytest.param(OLDER_COMPLETED_DAILY, id="old-latest-session"),
    ],
)
def test_get_stock_candles_rejects_noncanonical_latest_daily_session(
        monkeypatch, latest_timestamp):
    monkeypatch.setattr(scanner.time, "time", lambda: NOW)
    monkeypatch.setattr(
        scanner, "finnhub_get",
        lambda *_args, **_kwargs: _candle_payload(latest_timestamp),
    )

    assert scanner.get_stock_candles("AAPL", resolution="D", days=30) == []


class _Response:
    status_code = 200
    ok = True

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def _indicator_payload(indicator_timestamp):
    payload = {"sma": [19.0, 20.0]}
    if indicator_timestamp is not _MISSING:
        payload["t"] = [PREVIOUS_COMPLETED_DAILY, indicator_timestamp]
    return payload


def _macro_get(*, vix_timestamp, spy_timestamp, indicator_timestamp, calls):
    def get(url, *, params, timeout):
        calls.append((url, dict(params), timeout))
        if url.endswith("/indicator"):
            return _Response(_indicator_payload(indicator_timestamp))
        symbol = params["symbol"]
        if symbol == "SPY":
            return _Response(_finnhub_quote(
                spy_timestamp, current=98.0, previous=100.0))
        return _Response(_finnhub_quote(
            vix_timestamp, current=25.0, previous=24.0))

    return get


def _configure_macro(monkeypatch, *, vix_timestamp, spy_timestamp,
                     indicator_timestamp=LATEST_COMPLETED_DAILY):
    calls = []
    monkeypatch.setattr(scanner.time, "time", lambda: NOW)
    monkeypatch.setattr(scanner, "finnhub_rate_limit", lambda: None)
    monkeypatch.setattr(
        scanner.requests,
        "get",
        _macro_get(
            vix_timestamp=vix_timestamp,
            spy_timestamp=spy_timestamp,
            indicator_timestamp=indicator_timestamp,
            calls=calls,
        ),
    )
    return calls


def test_finnhub_macro_accepts_current_vix_and_spy_without_shape_change(
        monkeypatch):
    calls = _configure_macro(
        monkeypatch, vix_timestamp=NOW - 30, spy_timestamp=NOW - 45)

    result = scanner.get_finnhub_macro()

    assert set(result) == LEGACY_MACRO_KEYS
    assert result == {
        "vix": 25.0,
        "vix_20d_avg": 20.0,
        "vix_spike_pct": 25.0,
        "fear_level": "ELEVATED",
        "sp500_change": -2.0,
        "alerts": [
            "⚠️ VIX ELEVATED: +25.0%",
            "🚨 S&P500 Risk-off: -2.0%",
        ],
    }
    assert any(url.endswith("/indicator") for url, _params, _timeout in calls)


@pytest.mark.parametrize("timestamp", _invalid_timestamps())
def test_finnhub_macro_rejects_invalid_vix_and_spy_source_times(
        monkeypatch, timestamp):
    calls = _configure_macro(
        monkeypatch, vix_timestamp=timestamp, spy_timestamp=timestamp)

    result = scanner.get_finnhub_macro()

    assert set(result) == LEGACY_MACRO_KEYS
    assert result == {
        "vix": None,
        "vix_20d_avg": None,
        "vix_spike_pct": 0,
        "fear_level": "NORMAL",
        "sp500_change": None,
        "alerts": [],
    }
    assert not any(url.endswith("/indicator")
                   for url, _params, _timeout in calls)


def test_finnhub_macro_gates_vix_and_spy_independently(monkeypatch):
    _configure_macro(
        monkeypatch,
        vix_timestamp=NOW - scanner._DECISION_QUOTE_LIVE_MAX_AGE_SEC - 1,
        spy_timestamp=NOW - 30,
    )
    spy_only = scanner.get_finnhub_macro()
    assert spy_only["vix"] is None
    assert spy_only["vix_20d_avg"] is None
    assert spy_only["sp500_change"] == -2.0
    assert spy_only["alerts"] == ["🚨 S&P500 Risk-off: -2.0%"]

    _configure_macro(
        monkeypatch,
        vix_timestamp=NOW - 30,
        spy_timestamp=NOW + 60,
    )
    vix_only = scanner.get_finnhub_macro()
    assert vix_only["vix"] == 25.0
    assert vix_only["vix_20d_avg"] == 20.0
    assert vix_only["sp500_change"] is None
    assert vix_only["alerts"] == ["⚠️ VIX ELEVATED: +25.0%"]


@pytest.mark.parametrize(
    "indicator_timestamp",
    [
        pytest.param(_MISSING, id="missing"),
        pytest.param(OLDER_COMPLETED_DAILY, id="stale"),
    ],
)
def test_finnhub_macro_rejects_unproven_indicator_session_but_keeps_current_vix(
        monkeypatch, indicator_timestamp):
    _configure_macro(
        monkeypatch,
        vix_timestamp=NOW - 30,
        spy_timestamp=NOW - 30,
        indicator_timestamp=indicator_timestamp,
    )

    result = scanner.get_finnhub_macro()

    assert set(result) == LEGACY_MACRO_KEYS
    assert result["vix"] == 25.0
    assert result["vix_20d_avg"] is None
    assert result["vix_spike_pct"] == 0
    assert result["fear_level"] == "NORMAL"
    assert result["sp500_change"] == -2.0
    assert result["alerts"] == ["🚨 S&P500 Risk-off: -2.0%"]


class _Frame:
    def __init__(self, rows):
        self._rows = rows

    def iterrows(self):
        return enumerate(self._rows)


class _QuoteContext:
    def __init__(self, row):
        self.row = row
        self.calls = []

    def get_market_snapshot(self, symbols):
        self.calls.append(list(symbols))
        return 0, _Frame([self.row])


def _opend_local_time(epoch):
    return datetime.fromtimestamp(epoch, scanner.TZ_ET).strftime(
        "%Y-%m-%d %H:%M:%S")


def _opend_row(update_time):
    row = {
        "code": "US.AAPL",
        "last_price": 102.0,
        "open_price": 100.5,
        "high_price": 103.0,
        "low_price": 99.5,
        "volume": 123_456,
        "price_change_rate": 2.0,
    }
    if update_time is not _MISSING:
        row["update_time"] = update_time
    return row


def _run_opend(monkeypatch, update_time):
    monkeypatch.setattr(scanner.time, "time", lambda: NOW)
    # scanner deliberately tolerates installations without the optional SDK;
    # supply only its public success sentinel for this adapter unit test.
    monkeypatch.setattr(scanner, "RET_OK", 0, raising=False)
    context = _QuoteContext(_opend_row(update_time))
    monkeypatch.setattr(scanner, "moomoo_connect_quote", lambda: context)
    fallbacks = []

    def fallback(symbol):
        fallbacks.append(symbol)
        return None

    monkeypatch.setattr(scanner, "get_quote", fallback)
    monkeypatch.setattr(scanner, "PRICE_HISTORY", {})
    return scanner.get_realtime_prices(["AAPL"]), context, fallbacks


def test_direct_opend_realtime_prices_accepts_current_market_local_source_time(
        monkeypatch):
    result, context, fallbacks = _run_opend(
        monkeypatch, _opend_local_time(NOW - 30))

    assert context.calls == [["US.AAPL"]]
    assert fallbacks == []
    assert set(result) == {"AAPL"}
    assert set(result["AAPL"]) == LEGACY_OPEND_PRICE_KEYS
    assert result["AAPL"] == {
        "current": 102.0,
        "open": 100.5,
        "high": 103.0,
        "low": 99.5,
        "volume": 123_456,
        "change_pct": 2.0,
    }
    assert len(scanner.PRICE_HISTORY["AAPL"]) == 1
    assert scanner.PRICE_HISTORY["AAPL"][0]["price"] == 102.0


@pytest.mark.parametrize(
    "update_time",
    [
        pytest.param(_MISSING, id="missing"),
        pytest.param("not-a-timestamp", id="malformed"),
        pytest.param(_opend_local_time(NOW + 60), id="future"),
        pytest.param(
            _opend_local_time(
                NOW - scanner._DECISION_QUOTE_LIVE_MAX_AGE_SEC - 1),
            id="stale",
        ),
    ],
)
def test_direct_opend_realtime_prices_rejects_invalid_source_time_before_history(
        monkeypatch, update_time):
    result, context, _fallbacks = _run_opend(monkeypatch, update_time)

    assert context.calls == [["US.AAPL"]]
    assert result == {}
    assert scanner.PRICE_HISTORY == {}


# ── v13.5.36 compatibility: these legacy fixtures predate the canonical-
# calendar authority (weekday-agnostic daily sessions). Register a wide
# synthetic Mon-Fri canonical range so their historical/frozen dates keep the
# session semantics they were written under; production stays strict.
import pytest as _pytest
import argus_market_clock as _clock
from datetime import date as _date, timedelta as _timedelta


@_pytest.fixture(autouse=True)
def _legacy_wide_canonical_calendar():
    days = []
    cursor = _date(2020, 1, 1)
    while cursor <= _date(2030, 12, 31):
        if cursor.weekday() < 5:
            days.append(cursor.isoformat())
        cursor += _timedelta(days=1)
    for market in (_clock.JP_EQUITY, _clock.US_EQUITY, _clock.VIX_MKT):
        _clock.register_canonical_calendar(
            market, days, start="2020-01-01", end="2030-12-31",
            source="test:legacy-weekday-world")
    yield
    _clock.clear_canonical_calendar()
