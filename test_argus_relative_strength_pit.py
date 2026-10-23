"""D03 の日米相対力は日経平均÷S&P500 だけで見る(2026-10-23)。

以前は日経平均の日足が無い時に 1321 対 SPY の日足へ切り替えていた。
その代わりの経路は廃止し、日経平均が無ければ欠測のままにする。"""
from datetime import date, timedelta

import jp_market_engine
import scanner


def _bars(start, count, step):
    day, rows, value = start, [], 100.0
    while len(rows) < count:
        if day.weekday() < 5:
            rows.append({"date": day.isoformat(), "close": value})
            value *= step
        day += timedelta(days=1)
    return rows


def test_the_1321_vs_spy_fallback_no_longer_exists():
    assert not hasattr(scanner, "_jp_market_engine_relative_strength_proxy")


def test_warm_etf_charts_do_not_fill_a_missing_nikkei(monkeypatch):
    etf = _bars(date(2026, 8, 3), 25, 1.01)
    monkeypatch.setattr(scanner, "_chart_history_cached", lambda symbol, market: etf)
    monkeypatch.setattr(scanner, "_JP_MARKET_ENGINE_INDEX_OHLCV_CACHE", {})
    monkeypatch.setattr(scanner, "_ai_now_iso", lambda: "2026-09-10T00:00:00Z")
    direct = scanner._jp_market_engine_relative_strength_direct()
    assert direct is None
    d03 = jp_market_engine.evaluate_d01_d07(
        cutoff="2026-09-10T00:00:00Z",
        relative_strength_direct=direct)["families"]["D03"]
    assert d03["status"] == "MISSING"
    assert d03["sourceType"] == "NONE"
    assert d03["relativeStrengthValue"] is None and d03["conditionMet"] is None
