"""2026-10-27 (owner): an unreachable source is shown as 未取得, never as a
made-up price. The "mock" rows keep their names and carry no numbers."""
import scanner


def _no_numbers(row, keys):
    return all(row.get(k) is None for k in keys)


def test_japan_and_us_fallback_rows_carry_no_price():
    for row in scanner._jp_mock_snapshot()["stocks"] + scanner._us_mock_snapshot()["stocks"]:
        assert row["status"] == "mock" and row["name"]
        assert _no_numbers(row, ("price", "changeAbs", "changePct", "volume"))
    assert all("mock" not in s for s in scanner._JP_WATCHLIST + scanner._US_WATCHLIST)


def test_rates_fallback_has_no_values_and_no_signals(monkeypatch):
    for series_id in scanner._FRED_SERIES:
        row = scanner._fred_mock_series(series_id)
        assert row["status"] == "mock" and _no_numbers(row, ("latestValue", "previousValue", "change", "changeBp"))
    pressure, volatility, summary = scanner._rates_base_signals(
        scanner._fred_mock_series("DGS10"), scanner._fred_mock_series("VIXCLS"))
    assert pressure is None and volatility is None and "unavailable" in summary
    monkeypatch.setattr(scanner, "_RATES_CACHE", {"data": None, "expires": 0.0})
    snap = scanner._rates_snapshot_cached_only()
    assert snap["vix"].get("latestValue") is None and snap["us10y"].get("latestValue") is None


def test_crypto_fallback_is_empty_not_made_up(monkeypatch):
    monkeypatch.setattr(scanner, "_CRYPTO_CACHE", {})
    monkeypatch.setattr(scanner, "_crypto_coinbase_fallback", lambda ids: [])
    def down(*a, **k):
        raise scanner.requests.ConnectionError("down")
    monkeypatch.setattr(scanner.requests, "get", down)
    snap = scanner.get_crypto_watchlist_snapshot(["bitcoin"])
    assert snap.get("quotes") == [] or all(q.get("priceUsd") is None for q in snap.get("quotes") or [])
    assert not hasattr(scanner, "_CRYPTO_MOCK") and not hasattr(scanner, "_FRED_MOCK")
