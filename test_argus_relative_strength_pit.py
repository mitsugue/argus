from datetime import date, timedelta

import scanner


def _bars(start, count, step):
    day, rows, value = start, [], 100.0
    while len(rows) < count:
        if day.weekday() < 5:
            rows.append({"date": day.isoformat(), "close": value})
            value *= step
        day += timedelta(days=1)
    return rows


def test_relative_strength_uses_only_us_sessions_closed_before_the_jp_close(monkeypatch):
    jp = _bars(date(2026, 8, 3), 25, 1.0)
    us = _bars(date(2026, 8, 3), 25, 1.0)
    us[-1] = {**us[-1], "close": us[-2]["close"] * 2}     # same-date US close: unknown at the JP close
    monkeypatch.setattr(scanner, "_chart_history_cached",
                        lambda symbol, market: jp if symbol == "1321" else us)
    row = scanner._jp_market_engine_relative_strength_proxy()
    assert row["date"] == jp[-1]["date"] and row["availableFrom"] == jp[-1]["date"] + "T07:00:00Z"
    assert row["value"] == 0.0


def test_relative_strength_needs_enough_prior_us_sessions(monkeypatch):
    jp = _bars(date(2026, 8, 3), 25, 1.0)
    us = [row for row in _bars(date(2026, 8, 3), 25, 1.0) if row["date"] >= jp[-21]["date"]]
    monkeypatch.setattr(scanner, "_chart_history_cached",
                        lambda symbol, market: jp if symbol == "1321" else us)
    assert scanner._jp_market_engine_relative_strength_proxy() is None
