"""Dependency-light smoke checks for the market-data truth boundary."""
import importlib.util
from pathlib import Path
import sys
from unittest.mock import patch

# Avoid importing the local OpenD SDK during a read-only unit check.
sys.modules["moomoo"] = None
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import scanner  # noqa: E402


class FakeFrame:
    def __init__(self, rows):
        self.rows = rows

    def iterrows(self):
        return enumerate(self.rows)


def pushed(now, age=None):
    return {
        "row": {
            "symbol": "SPY", "price": 700.0, "changeAbs": 1.0,
            "changePct": 0.1, "volume": 1, "status": "live",
            "source": "moomoo-rt", "entitlement": "unknown",
            "exchangeTs": None if age is None else now - age,
        },
        "ts": now - 12,
    }


def main():
    now = 1_800_000_000.0
    calendar = {"session": "REGULAR"}
    with patch.object(scanner.time, "time", return_value=now), \
            patch.object(scanner.argus_market_clock, "market_session", return_value=calendar):
        with patch.object(scanner, "_PUSHED_QUOTES", {"JP": {}, "US": {"SPY": pushed(now)}}):
            unknown = scanner._overlay_pushed(
                {"status": "live", "stocks": []}, "US", ["SPY"])
            assert unknown["quoteFreshness"]["delayClass"] == "UNKNOWN"
            assert unknown["stocks"][0]["ageSec"] is None
            assert unknown["stocks"][0]["transportAgeSec"] == 12

        with patch.object(scanner, "_PUSHED_QUOTES", {"JP": {}, "US": {"SPY": pushed(now, 30)}}):
            live = scanner._overlay_pushed(
                {"status": "mock", "stocks": []}, "US", ["SPY"])
            assert live["quoteFreshness"]["delayClass"] == "LIVE"
            assert live["status"] == "live"

        with patch.object(scanner, "_PUSHED_QUOTES", {"JP": {}, "US": {"SPY": pushed(now, 900)}}):
            delayed = scanner._overlay_pushed(
                {"status": "mock", "stocks": []}, "US", ["SPY"])
            assert delayed["quoteFreshness"]["delayClass"] == "15m"
            assert delayed["status"] == "delayed"

    with patch.object(scanner, "_yahoo_jp_row",
                      side_effect=AssertionError("Yahoo formal quote")), \
            patch.object(scanner, "_jq_fetch_bar_row",
                         return_value={"symbol": "1321", "status": "delayed",
                                       "source": "jquants"}):
        assert scanner._jquants_fetch_quote(
            {"symbol": "1321", "name": "ETF", "mock": {}}, {})["source"] == "jquants"

    with patch.object(scanner.requests, "get",
                      side_effect=AssertionError("provider fetch")), \
            patch.object(scanner, "_PUSHED_QUOTES", {"JP": {}, "US": {}}), \
            patch.object(scanner, "_JP_DYN_CACHE", {}), \
            patch.object(scanner, "_US_DYN_CACHE", {}), \
            patch.object(scanner, "_JP_CACHE", {"data": None, "expires": 0.0}), \
            patch.object(scanner, "_US_CACHE", {"data": None, "expires": 0.0}):
        with scanner.app.test_client() as client:
            assert client.get("/api/argus/japan-watchlist?symbols=1321").status_code == 200
            assert client.get("/api/argus/us-watchlist?symbols=SPY").status_code == 200

    spec = importlib.util.spec_from_file_location(
        "market_truth_bridge", "bridge/moomoo_push.py")
    bridge = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bridge)
    rows = bridge.rows_from_snapshot(FakeFrame([{
        "code": "US.NVDA", "last_price": 190.0,
        "prev_close_price": 185.0, "volume": 1000,
        "update_time": "2026-07-27 16:00:00",
    }]))
    assert rows[0]["exchangeTs"] == "2026-07-27T20:00:00Z"
    assert rows[0]["entitlement"] == "unknown"
    print("market_data_truth_smoke: ok")


if __name__ == "__main__":
    main()
