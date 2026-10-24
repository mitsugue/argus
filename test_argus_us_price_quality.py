"""2026-10-20 (owner): the US price lamp judges coverage, source time and freshness, apart from the route."""
import argus_us_price_quality as q
import scanner


def row(age, *, route="twelvedata", price=100.0, status="live"):
    r = {"price": price, "status": status, "ageSec": age, "sourceTimeStatus": "PRESENT" if age is not None else "MISSING",
         "timestampInversion": False}
    if route == "moomoo":
        r["transportAgeSec"] = 5
    else:
        r["source"] = route
    return r


def test_all_targets_fresh_is_ok_with_the_routes_counted():
    out = q.assess(["A", "B", "C"], {"A": row(30, route="moomoo"), "B": row(500), "C": row(900)}, session_open=True)
    assert out["status"] == "ok"
    assert out["counts"]["routes"] == {"moomoo": 1, "twelvedata": 2, "other": 0}
    assert "3/3銘柄" in out["detailJa"] and "moomoo 1" in out["detailJa"]


def test_an_old_or_missing_price_is_a_service_warning_whatever_the_route():
    out = q.assess(["A", "B", "C"], {"A": row(30), "B": row(3600), "C": None}, session_open=True)
    assert out["status"] == "warning"
    assert "1/3銘柄" in out["detailJa"] and "古い・時刻不明 1" in out["detailJa"] and "価格なし 1" in out["detailJa"]


def test_no_price_at_all_warns_but_never_turns_the_analysis_red():
    out = q.assess(["A"], {"A": None}, session_open=True)
    assert out["status"] == "warning" and "0/1" in out["detailJa"]


def test_a_close_of_session_value_is_not_shown_as_a_live_receipt():
    out = q.assess(["A"], {"A": row(50000)}, session_open=False)
    assert out["status"] == "off" and "実時間の受信ではない" in out["detailJa"]


def test_an_unreadable_target_list_is_unconfirmed():
    assert "未確認" in q.assess(None, {}, session_open=True)["detailJa"]
    assert q.assess(None, {}, session_open=True)["status"] == "warning"


def test_mock_rows_and_a_missing_source_time_are_not_counted_as_fresh():
    out = q.assess(["A", "B"], {"A": row(10, status="mock"), "B": row(None)}, session_open=True)
    assert out["counts"]["priced"] == 1 and out["counts"]["fresh"] == 0


def test_the_lamp_is_wired_and_names_no_symbol(monkeypatch):
    # 2026-10-20: the targets are built from memory (curated + registrations), not
    # from the warm cache that every watchlist read clears.
    monkeypatch.setattr(scanner, "_US_WATCHLIST", [{"symbol": "NVDA"}])
    monkeypatch.setattr(scanner, "_OWNER_OVERVIEW_MEMBERSHIP", {"checkedAt": 1.0, "members": [
        {"symbol": "AAPL", "market": "US"}, {"symbol": "7203", "market": "JP"}]})
    monkeypatch.setattr(scanner, "_US_WARM_HINTS", {})
    monkeypatch.setitem(scanner._TD_WARM_UNIVERSE_CACHE, "data", None)
    monkeypatch.setattr(scanner, "_us_market_open", lambda: True)
    monkeypatch.setattr(scanner, "_quote_cached_only",
                        lambda sym, market: row(60) if sym == "NVDA" else None)
    lamps = {l["key"]: l for l in scanner._system_health(allow_provider_fetch=False)["lamps"]}
    lamp = lamps["prices_us"]
    assert lamp["status"] == "warning" and "1/10銘柄" in lamp["detailJa"]   # + the 8 regime ETFs
    assert "NVDA" not in lamp["detailJa"] and "AAPL" not in lamp["detailJa"]
    assert "設定済" not in lamp["detailJa"]           # a configured key is not a receipt


def test_the_regime_etfs_are_targets_once_and_the_lamp_rule_is_unchanged(monkeypatch):
    # 2026-10-24: the eight ETFs the market tone reads (SPY QQQ IWM XLK XLU GLD TLT HYG) are
    # counted by the lamp too, once each; missing ones stay amber (never red).
    etfs = ["SPY", "QQQ", "IWM", "XLK", "XLU", "GLD", "TLT", "HYG"]
    assert scanner._REGIME_ETFS == etfs
    monkeypatch.setattr(scanner, "_US_WATCHLIST", [{"symbol": "NVDA"}, {"symbol": "SPY"}])
    monkeypatch.setattr(scanner, "_OWNER_OVERVIEW_MEMBERSHIP", {"checkedAt": 1.0, "members": []})
    monkeypatch.setattr(scanner, "_US_WARM_HINTS", {})
    targets = scanner._us_price_targets()
    assert targets == ["NVDA", "SPY"] + etfs[1:]
    monkeypatch.setattr(scanner, "_us_market_open", lambda: True)
    monkeypatch.setattr(scanner, "_quote_cached_only", lambda sym, market: None if sym in etfs else row(60))
    lamps = {l["key"]: l for l in scanner._system_health(allow_provider_fetch=False)["lamps"]}
    assert lamps["prices_us"]["status"] == "warning" and "価格なし 8" in lamps["prices_us"]["detailJa"]
    monkeypatch.setattr(scanner, "_quote_cached_only", lambda sym, market: row(60))
    lamps = {l["key"]: l for l in scanner._system_health(allow_provider_fetch=False)["lamps"]}
    assert lamps["prices_us"]["status"] == "ok" and "9/9銘柄" in lamps["prices_us"]["detailJa"]


def test_targets_wait_for_the_registrations_instead_of_guessing(monkeypatch):
    monkeypatch.setattr(scanner, "_OWNER_OVERVIEW_MEMBERSHIP", {"checkedAt": 0.0, "members": None})
    assert scanner._us_price_targets() is None
    monkeypatch.setattr(scanner, "_us_market_open", lambda: True)
    lamps = {l["key"]: l for l in scanner._system_health(allow_provider_fetch=False)["lamps"]}
    assert "未確認" in lamps["prices_us"]["detailJa"]
