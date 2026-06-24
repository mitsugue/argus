"""US mover routing (v10.146): moomoo realtime preferred over Alpha Vantage; regime
ETF series overlays the realtime moomoo price on the current close."""
import scanner


def test_us_movers_prefer_moomoo(monkeypatch):
    rec = []
    monkeypatch.setattr(scanner, "_EVENT_BACKBONE_ENABLED", True)
    monkeypatch.setattr(scanner, "_us_market_open", lambda *a, **k: True)
    monkeypatch.setattr(scanner, "_MARKET_MOVER_NOTIFY_MAX", 5)
    monkeypatch.setattr(scanner, "_moomoo_us_movers",
                        lambda: [{"symbol": "NVDA", "changePct": 14.0, "price": 120.0, "name": "NVDA"}])
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


def test_etf_overlay_uses_moomoo_price(monkeypatch):
    import time
    monkeypatch.setattr(scanner, "_td_timeseries", lambda syms: {"SPY": [500.0, 498.0, 495.0]})
    scanner._PUSHED_QUOTES["US"]["SPY"] = {"row": {"price": 511.0}, "ts": time.time()}
    out = scanner._etf_series_with_moomoo(["SPY"])
    assert out["SPY"][0] == 511.0 and out["SPY"][1:] == [498.0, 495.0]   # realtime current + TD history
    scanner._PUSHED_QUOTES["US"].pop("SPY", None)
