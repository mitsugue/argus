"""US mover routing (v10.146): moomoo realtime preferred over Alpha Vantage; regime
ETF series overlays the realtime moomoo price on the current close."""
import pytest
import scanner


def test_us_mover_push_requires_current_per_row_source_time_for_authority(
        monkeypatch):
    now = 1_800_000_000.0
    monkeypatch.setattr(scanner.time, "time", lambda: now)
    monkeypatch.setattr(scanner, "_require_admin", lambda: (True, None, 200))
    monkeypatch.setattr(
        scanner, "_verify_bridge_signature", lambda _raw: (True, "verified"))
    monkeypatch.setattr(scanner, "_MOOMOO_US_MOVERS", {
        "rows": [], "ts": 0.0, "asOf": None})
    payload = {"movers": [
        {"symbol": "AAPL", "price": 100.0, "changePct": 14.0},
        {"symbol": "MSFT", "price": 101.0, "changePct": 14.0,
         "exchangeTs": now + 1},
        {"symbol": "NVDA", "price": 102.0, "changePct": 14.0,
         "exchangeTs": now - 3600},
        {"symbol": "SPY", "price": 103.0, "changePct": 14.0,
         "exchangeTs": now - 30},
    ], "asOf": now}
    with scanner.app.test_client() as client:
        response = client.post("/api/argus/us-movers-push", json=payload)
    assert response.status_code == 200
    assert response.get_json()["accepted"] == 4
    authoritative = scanner._moomoo_us_movers()
    assert [row["symbol"] for row in authoritative] == ["SPY"]
    stored = {row["symbol"]: row
              for row in scanner._MOOMOO_US_MOVERS["rows"]}
    assert stored["AAPL"]["sourceTimeStatus"] == "MISSING"
    assert stored["MSFT"]["timestampInversion"] is True
    assert stored["NVDA"]["ageSec"] == 3600

    recorded = []
    monkeypatch.setattr(scanner, "_EVENT_BACKBONE_ENABLED", True)
    monkeypatch.setattr(scanner, "_us_market_open", lambda *a, **k: True)
    monkeypatch.setattr(scanner.argus_events, "detect_market_mover",
                        lambda *_a, **_k: [{
                            "type": "MARKET_MOVER", "severity": 4}])
    monkeypatch.setattr(
        scanner, "_record_event",
        lambda market, symbol, *_a, **_k: recorded.append(
            (market, symbol)) or {"symbol": symbol})
    monkeypatch.setattr(
        scanner, "_av_market_movers",
        lambda **_k: (_ for _ in ()).throw(AssertionError("AV called")))
    assert scanner._scan_market_movers() == 1
    assert recorded == [("US", "SPY")]


def test_us_movers_prefer_moomoo(monkeypatch):
    rec = []
    monkeypatch.setattr(scanner, "_EVENT_BACKBONE_ENABLED", True)
    monkeypatch.setattr(scanner, "_us_market_open", lambda *a, **k: True)
    monkeypatch.setattr(scanner, "_MARKET_MOVER_NOTIFY_MAX", 5)
    monkeypatch.setattr(scanner, "_moomoo_us_movers",
                        lambda: [{"symbol": "NVDA", "changePct": 14.0,
                                  "price": 120.0, "name": "NVDA",
                                  "sourceTimestamp": __import__("time").time()}])
    # Alpha Vantage must NOT be consulted when moomoo has fresh data
    monkeypatch.setattr(scanner, "_av_market_movers", lambda **k: (_ for _ in ()).throw(AssertionError("AV called")))
    monkeypatch.setattr(scanner.argus_events, "detect_market_mover",
                        lambda s, c, p, **k: [{"type": "MARKET_MOVER", "severity": 4}])
    monkeypatch.setattr(scanner, "_record_event",
                        lambda m, s, t, now, sess, **k: rec.append({"sym": s, "src": k.get("source")}) or {"symbol": s})
    n = scanner._scan_market_movers()
    assert n == 1 and rec[0]["sym"] == "NVDA" and rec[0]["src"] == "moomoo-rt"


def test_us_movers_fallback_av_when_no_moomoo(monkeypatch):
    monkeypatch.setattr(scanner, "_EVENT_BACKBONE_ENABLED", True)
    monkeypatch.setattr(scanner, "_us_market_open", lambda *a, **k: True)
    monkeypatch.setattr(scanner, "_moomoo_us_movers", lambda: [])      # moomoo idle
    called = {"av": False}
    def _av(**k):
        called["av"] = True
        return {"status": "unavailable"}
    monkeypatch.setattr(scanner, "_av_market_movers", _av)
    scanner._scan_market_movers()
    assert called["av"] is True                                       # AV used as fallback


@pytest.mark.parametrize("source_epoch", [
    None, "malformed", True, float("nan"),
    1_800_000_001.0,
    1_800_000_000.0 - scanner._MOVER_FRESH_SEC - 1,
])
def test_alpha_vantage_invalid_source_time_is_diagnostic_only(
        monkeypatch, source_epoch):
    now = 1_800_000_000.0
    monkeypatch.setattr(scanner.time, "time", lambda: now)
    monkeypatch.setattr(scanner, "_EVENT_BACKBONE_ENABLED", True)
    monkeypatch.setattr(scanner, "_us_market_open", lambda *a, **k: True)
    monkeypatch.setattr(scanner, "_moomoo_us_movers", lambda: [])
    monkeypatch.setattr(scanner, "_av_market_movers", lambda **_k: {
        "status": "live", "asOf": "provider-value",
        "asOfEpoch": source_epoch,
        "gainers": [{"symbol": "AAPL", "price": 100.0, "changePct": 14.0}],
        "losers": [],
    })
    monkeypatch.setattr(
        scanner.argus_events, "detect_market_mover",
        lambda *_a, **_k: [{"type": "MARKET_MOVER", "severity": 4}])
    recorded = []
    monkeypatch.setattr(
        scanner, "_record_event",
        lambda *_a, **_k: recorded.append((_a, _k)) or {})

    assert scanner._scan_market_movers() == 0
    assert recorded == []


def test_alpha_vantage_bounded_source_time_can_create_current_event(monkeypatch):
    now = 1_800_000_000.0
    monkeypatch.setattr(scanner.time, "time", lambda: now)
    monkeypatch.setattr(scanner, "_EVENT_BACKBONE_ENABLED", True)
    monkeypatch.setattr(scanner, "_us_market_open", lambda *a, **k: True)
    monkeypatch.setattr(scanner, "_moomoo_us_movers", lambda: [])
    monkeypatch.setattr(scanner, "_av_market_movers", lambda **_k: {
        "status": "live", "asOf": "provider-value", "asOfEpoch": now - 30,
        "gainers": [{"symbol": "AAPL", "price": 100.0, "changePct": 14.0}],
        "losers": [],
    })
    monkeypatch.setattr(
        scanner.argus_events, "detect_market_mover",
        lambda *_a, **_k: [{"type": "MARKET_MOVER", "severity": 4}])
    recorded = []
    monkeypatch.setattr(
        scanner, "_record_event",
        lambda *_a, **kwargs: recorded.append(kwargs) or {"symbol": "AAPL"})

    assert scanner._scan_market_movers() == 1
    assert len(recorded) == 1
    assert recorded[0]["source"] == "alphavantage"
    assert "suppress_notify" not in recorded[0]


def test_etf_overlay_uses_moomoo_price(monkeypatch):
    now = 1_800_000_000.0
    monkeypatch.setattr(scanner.time, "time", lambda: now)
    monkeypatch.setattr(scanner, "_td_timeseries", lambda syms: {"SPY": [500.0, 498.0, 495.0]})
    scanner._PUSHED_QUOTES["US"]["SPY"] = {
        "row": {"price": 511.0, "exchangeTs": now - 30}, "ts": now - 5}
    out = scanner._etf_series_with_moomoo(["SPY"])
    assert out["SPY"][0] == 511.0 and out["SPY"][1:] == [498.0, 495.0]   # realtime current + TD history
    scanner._PUSHED_QUOTES["US"].pop("SPY", None)


def test_etf_moomoo_quote_never_synthesizes_history_when_td_down(monkeypatch):
    now = 1_800_000_000.0
    monkeypatch.setattr(scanner.time, "time", lambda: now)
    monkeypatch.setattr(scanner, "_td_timeseries", lambda syms: {})   # TD fully down
    scanner._PUSHED_QUOTES["US"]["QQQ"] = {
        "row": {"price": 440.0, "changePct": 2.0,
                "exchangeTs": now - 30}, "ts": now - 5}
    out = scanner._etf_series_with_moomoo(["QQQ"])
    assert out == {}
    scanner._PUSHED_QUOTES["US"].pop("QQQ", None)


def test_transport_fresh_moomoo_without_source_time_cannot_overlay_history(
        monkeypatch):
    now = 1_800_000_000.0
    monkeypatch.setattr(scanner.time, "time", lambda: now)
    monkeypatch.setattr(
        scanner, "_td_timeseries", lambda _syms: {"SPY": [500.0, 499.0]})
    scanner._PUSHED_QUOTES["US"]["SPY"] = {
        "row": {"price": 999.0, "exchangeTs": None}, "ts": now - 1}
    try:
        assert scanner._etf_series_with_moomoo(["SPY"]) == {
            "SPY": [500.0, 499.0]}
    finally:
        scanner._PUSHED_QUOTES["US"].pop("SPY", None)
