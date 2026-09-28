"""Hostile source-time tests for the retained Finnhub daily-candle path.

Provider success and numeric payloads cannot substitute for a current provider
timestamp.  The legacy quote/macro/OpenD helpers were removed with the old
scanner phases; only get_stock_candles remains a decision input.
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
class _Missing:
    pass


_MISSING = _Missing()


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
