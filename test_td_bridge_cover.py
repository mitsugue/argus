"""2026-10-22 (owner: moomoo is the primary US source): symbols the bridge already
delivers live are not bought again from Twelve Data during the regular session."""
from datetime import datetime

import pytz

import scanner

NOW = datetime(2026, 10, 22, 15, 0, tzinfo=pytz.utc)   # 11:00 New York, regular session


def _live_row(sym):
    return {"symbol": sym, "price": 101.5, "changeAbs": 1.0, "changePct": 1.0, "volume": 10,
            "date": "2026-10-22", "source": "moomoo-rt", "entitlement": "realtime",
            "exchangeTs": NOW.timestamp() - 5, "sourceTimestamp": NOW.timestamp() - 5,
            "status": "live", "realtimeEvidence": True}


def _setup(monkeypatch, pushed):
    now = NOW.timestamp()
    monkeypatch.setattr(scanner, "_TWELVEDATA_API_KEY", "test-only")
    monkeypatch.setattr(scanner, "_td_us_session", lambda now_utc=None: "REGULAR")
    monkeypatch.setattr(scanner, "_td_warm_universe",
                        lambda now=None: {"symbols": ["AAPL", "NVDA", "SPY"], "cadenceFit": {}})
    monkeypatch.setattr(scanner, "_PUSHED_QUOTES", {"US": {sym: {"row": row, "ts": now - ago}
                                                           for sym, (row, ago) in pushed.items()}, "JP": {}})
    monkeypatch.setattr(scanner, "_decision_usable_quote_row", lambda row, now_epoch=None:
                        row if row.get("realtimeEvidence") is True and row.get("status") == "live" else None)
    monkeypatch.setattr(scanner, "_US_WARM_ROWS", {})
    monkeypatch.setattr(scanner, "_TD_WARM_STATE", {})
    asked = []
    monkeypatch.setattr(scanner, "_td_warm_fetch", lambda batch: (asked.append(list(batch)) or ([], True, False, None)))
    return asked


def test_bridge_live_symbols_are_served_from_the_bridge_and_not_bought(monkeypatch):
    asked = _setup(monkeypatch, {"AAPL": (_live_row("AAPL"), 10), "NVDA": (_live_row("NVDA"), 10)})
    scanner._td_warm_tick(NOW)
    assert all("AAPL" not in batch and "NVDA" not in batch for batch in asked)
    assert scanner._US_WARM_ROWS["AAPL"]["row"]["source"] == "moomoo-rt"
    assert scanner._TD_WARM_STATE["bridgeCovered"] == 2


def test_stale_or_delayed_bridge_rows_still_use_twelve_data(monkeypatch):
    delayed = {**_live_row("NVDA"), "status": "delayed", "realtimeEvidence": False}
    asked = _setup(monkeypatch, {"AAPL": (_live_row("AAPL"), 600), "NVDA": (delayed, 10)})
    scanner._td_warm_tick(NOW)
    assert scanner._TD_WARM_STATE["bridgeCovered"] == 0
    assert "AAPL" not in scanner._US_WARM_ROWS and "NVDA" not in scanner._US_WARM_ROWS


def test_outside_the_regular_session_nothing_is_covered(monkeypatch):
    _setup(monkeypatch, {"AAPL": (_live_row("AAPL"), 10)})
    assert scanner._td_bridge_covered_rows(["AAPL"], NOW.timestamp(), "POST_MARKET") == {}
    assert set(scanner._td_bridge_covered_rows(["AAPL"], NOW.timestamp(), "REGULAR")) == {"AAPL"}
