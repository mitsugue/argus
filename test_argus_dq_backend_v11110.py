"""V11.11.0 backend wiring — price-history cached-only, DQ status redacted,
US supply/demand live path, and the standing regressions."""
import json

import scanner


class _Boom:
    def __getattr__(self, name):
        raise AssertionError(f"network call attempted via requests.{name}")


def test_price_history_cached_only(monkeypatch):
    monkeypatch.setattr(scanner, "requests", _Boom())
    scanner._US_HISTORY_CACHE["TESTX"] = {
        "data": {"dates": ["2026-07-02", "2026-07-01"], "closes": [101.0, 100.0],
                 "volumes": [1, 1]}, "expires": 9e12}
    try:
        with scanner.app.test_client() as c:
            r = c.get("/api/argus/price-history?symbol=TESTX&market=US")
            assert r.status_code == 200
            d = r.get_json()
            assert d["available"] and d["closes"] == [101.0, 100.0]
            r2 = c.get("/api/argus/price-history?symbol=0000&market=JP")
            d2 = r2.get_json()
            assert d2["available"] is False and d2["closes"] == []
            assert "自動取得" in d2["noteJa"]
    finally:
        scanner._US_HISTORY_CACHE.pop("TESTX", None)


def test_us_supply_demand_rejects_source_invalid_bridge_flow(monkeypatch):
    monkeypatch.setattr(scanner, "requests", _Boom())
    scanner._PUSHED_QUOTES.setdefault("US", {})["SDUS"] = {
        "row": {"symbol": "SDUS", "price": 100.0, "changePct": 3.0,
                "volume": 2_000_000, "status": "live",
                "flow": {"bigNetRatio": 0.3, "bigIn": 1e8, "bigOut": 4e7}},
        "ts": 9e12}
    scanner._US_HISTORY_CACHE["SDUS"] = {
        "data": {"dates": [f"2026-06-{d:02d}" for d in range(30, 2, -1)],
                 "closes": [100.0] * 28, "volumes": [1_000_000] * 28}, "expires": 9e12}
    try:
        sig = scanner._supply_demand_signal_for("SDUS", "US")
        assert sig["market"] == "US"
        # Receipt freshness and an untimebound bridge flow are not market-time
        # authority.  The row may remain diagnostic, but it cannot mint a
        # direct-data A/B supply-demand classification.
        assert sig["directness"] == "insufficient"
        assert sig["condition"] == "unknown"
        assert sig["supplyDemandRank"] == "Unknown"
        assert sig["evidence"]["measuredFlowNetRatio"] is None
        assert any("実測大口フロー" in m for m in sig["missingEvidence"])
        assert any("FINRA" in m for m in sig["missingEvidence"])
        assert "未取得" in sig["sourceLimitNote"]
    finally:
        scanner._PUSHED_QUOTES["US"].pop("SDUS", None)
        scanner._US_HISTORY_CACHE.pop("SDUS", None)


def test_supply_demand_list_includes_us(monkeypatch):
    monkeypatch.setattr(scanner, "requests", _Boom())
    sigs = scanner._supply_demand_list(cap=30)
    mkts = {s["market"] for s in sigs}
    assert "JP" in mkts and "US" in mkts


def test_supply_demand_endpoint_respects_market_param(monkeypatch):
    # production bug (2026-07-04): ?symbol=NVDA&market=US classified as JP and
    # listed 週次信用残/日証金 as missing. US must get the US missing list.
    monkeypatch.setattr(scanner, "requests", _Boom())
    with scanner.app.test_client() as c:
        d = c.get("/api/argus/supply-demand?symbol=NVDA&market=US").get_json()
        sig = d["signal"]
        assert sig["market"] == "US"
        assert any("FINRA" in m for m in sig["missingEvidence"])
        assert not any("日証金" in m for m in sig["missingEvidence"])
