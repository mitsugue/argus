"""休日・取引時間外に長期の指数履歴を取り直さない(2026-10-25)。"""
from datetime import datetime, timezone

import pytest

import scanner

U = timezone.utc


def _held(acquired):
    return {"data": [{"date": "2026-10-23", "close": 1.0}],
            "lastFetchStatus": "AVAILABLE", "acquiredAt": acquired.isoformat(),
            "historyRange": "10y", "expires": 0}


@pytest.mark.parametrize("symbol,now,acquired,settled", [
    ("^GSPC", datetime(2026, 10, 25, 3, tzinfo=U), datetime(2026, 10, 24, 1, tzinfo=U), True),
    ("^GSPC", datetime(2026, 10, 25, 3, tzinfo=U), datetime(2026, 10, 23, 18, tzinfo=U), False),
    ("^GSPC", datetime(2026, 10, 26, 15, tzinfo=U), datetime(2026, 10, 24, 1, tzinfo=U), False),
    ("^VIX", datetime(2026, 10, 26, 3, tzinfo=U), datetime(2026, 10, 24, 1, tzinfo=U), True),
    ("^VIX", datetime(2026, 10, 27, 1, tzinfo=U), datetime(2026, 10, 26, 18, tzinfo=U), False),
    ("^VIX", datetime(2026, 10, 27, 1, tzinfo=U), datetime(2026, 10, 26, 20, 45, tzinfo=U), True),
    ("JPY=X", datetime(2026, 10, 25, 3, tzinfo=U), datetime(2026, 10, 24, 1, tzinfo=U), True),
    ("JPY=X", datetime(2026, 10, 26, 1, tzinfo=U), datetime(2026, 10, 24, 1, tzinfo=U), False),
    ("^N225", datetime(2026, 10, 25, 3, tzinfo=U), datetime(2026, 10, 24, 1, tzinfo=U), False),
])
def test_settled_only_after_the_latest_close_and_outside_the_session(
        symbol, now, acquired, settled):
    assert scanner._index_history_settled(symbol, _held(acquired), now) is settled


def test_failed_or_naive_acquisition_always_refetches():
    now = datetime(2026, 10, 25, 3, tzinfo=U)
    failed = {**_held(datetime(2026, 10, 24, 1, tzinfo=U)), "lastFetchStatus": "FAILED"}
    naive = {**_held(datetime(2026, 10, 24, 1, tzinfo=U)), "acquiredAt": "2026-10-24T01:00:00"}
    assert scanner._index_history_settled("^GSPC", failed, now) is False
    assert scanner._index_history_settled("^GSPC", naive, now) is False


def test_settled_history_is_served_without_a_request(monkeypatch):
    held = _held(datetime(2026, 10, 24, 1, tzinfo=U))
    monkeypatch.setitem(scanner._JP_MARKET_ENGINE_INDEX_OHLCV_CACHE, "^GSPC", held)
    monkeypatch.setattr(scanner, "_index_history_settled", lambda *a: True)

    def no_request(*args, **kwargs):
        raise AssertionError("settled history must not be refetched")

    monkeypatch.setattr(scanner.requests, "get", no_request)
    rows = scanner._yahoo_index_ohlcv("^GSPC", "SP500", fetch=True, range_="10y")
    assert rows == held["data"]
    assert held["expires"] > 0


def test_wider_scope_request_is_not_short_circuited(monkeypatch):
    held = {**_held(datetime(2026, 10, 24, 1, tzinfo=U)), "historyRange": "2y"}
    monkeypatch.setitem(scanner._JP_MARKET_ENGINE_INDEX_OHLCV_CACHE, "^GSPC", held)
    monkeypatch.setattr(scanner, "_index_history_settled", lambda *a: True)
    called = []

    def failing_request(*args, **kwargs):
        called.append(kwargs.get("params"))
        raise ValueError("offline")

    monkeypatch.setattr(scanner.requests, "get", failing_request)
    scanner._yahoo_index_ohlcv("^GSPC", "SP500", fetch=True, range_="10y")
    assert called and called[0]["range"] == "10y"


def test_jquants_history_is_held_on_a_tokyo_holiday_only():
    held = {"dates": ["2026-10-23", "2026-10-22"]}
    sunday = datetime(2026, 10, 25, 3, tzinfo=U)
    monday = datetime(2026, 10, 26, 3, tzinfo=U)
    assert scanner._jq_history_holiday_hold(held, sunday) is True
    assert scanner._jq_history_holiday_hold(held, monday) is False
    assert scanner._jq_history_holiday_hold({"dates": ["2026-10-22"]}, sunday) is False
    assert scanner._jq_history_holiday_hold({"dates": []}, sunday) is False


def test_expired_jquants_history_is_not_refetched_on_a_holiday(monkeypatch):
    held = {"dates": ["2026-10-23"], "rows": []}
    monkeypatch.setitem(scanner._JQ_HISTORY_CACHE, "9999", {"data": held, "expires": 0})
    monkeypatch.setattr(scanner, "_jq_history_holiday_hold", lambda data: True)

    def no_request(*args, **kwargs):
        raise AssertionError("holiday history must not be refetched")

    monkeypatch.setattr(scanner.requests, "get", no_request)
    assert scanner._jq_price_history("9999") is held
    assert scanner._JQ_HISTORY_CACHE["9999"]["expires"] > 0
