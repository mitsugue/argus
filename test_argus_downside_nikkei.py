"""急落の分類の地合いは日経平均そのもので見る(2026-10-23)。

立花の 101(リアルタイム)を先に使い、無い時は Yahoo の遅延値を使って遅延の印を
残す。どちらも無い時は地合い不明で、1306/1321 の平均や監視銘柄の平均で埋めない。"""
from datetime import datetime, timezone

import pytest

import argus_downside
import argus_index_live
import scanner

# 2026-10-22 (木) 11:00 JST — 東京の立会時間中。
NOW = datetime(2026, 10, 22, 2, 0, tzinfo=timezone.utc).timestamp()


def _iso(epoch):
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat().replace("+00:00", "Z")


def _quote(*, change=-1.8, traded=NOW - 20 * 60, realtime=False, source="Yahoo Finance (delayed)"):
    return {"status": "AVAILABLE", "actionAuthority": False, "quote": {
        "instrumentId": "NIKKEI_225_INDEX", "symbol": "^N225", "price": 38000.0,
        "previousClose": 38700.0, "changePct": change, "tradedAt": _iso(traded),
        "receivedAt": _iso(NOW), "delaySeconds": int(NOW - traded),
        "sessionOpen": True, "source": source, "realtime": realtime,
        "actionAuthority": False}}


def _use(monkeypatch, value):
    monkeypatch.setattr(argus_index_live, "current_quote_safe", lambda: value)


def test_realtime_tachibana_value_is_used_without_a_delay_mark(monkeypatch):
    _use(monkeypatch, _quote(change=-2.04, traded=NOW - 5, realtime=True, source="立花証券"))
    row = scanner._jp_index_proxy(now_epoch=NOW)
    assert row["changePct"] == -2.04 and row["instrumentId"] == "NIKKEI_225_INDEX"
    assert row["realtime"] is True and row["delayed"] is False
    assert row["source"] == "立花証券" and row["ageSeconds"] == 5


def test_delayed_yahoo_value_is_used_and_marked_delayed(monkeypatch):
    _use(monkeypatch, _quote(change=-1.8, traded=NOW - 20 * 60))
    row = scanner._jp_index_proxy(now_epoch=NOW)
    assert row["changePct"] == -1.8
    assert row["realtime"] is False and row["delayed"] is True
    assert row["ageSeconds"] == 20 * 60
    assert row["source"] == "Yahoo Finance (delayed)"


@pytest.mark.parametrize("value", [
    {"status": "UNAVAILABLE", "reason": "not_yet_fetched", "quote": None},
    None,
    _quote(change=None),
    _quote(change=float("nan")),
    _quote(traded=NOW - 26 * 3600),          # 前日の値は今日の地合いではない
    _quote(traded=NOW - 31 * 60),            # 場中に30分を超えて古い遅延値
])
def test_missing_or_stale_nikkei_is_unknown(monkeypatch, value):
    _use(monkeypatch, value)
    assert scanner._jp_index_proxy(now_epoch=NOW) is None


def test_after_the_close_the_days_last_delayed_value_still_counts(monkeypatch):
    after_close = datetime(2026, 10, 22, 8, 0, tzinfo=timezone.utc).timestamp()   # 17:00 JST
    _use(monkeypatch, _quote(traded=after_close - 90 * 60))                       # 15:30 JST
    row = scanner._jp_index_proxy(now_epoch=after_close)
    assert row["delayed"] is True and row["ageSeconds"] == 90 * 60


def _downside(monkeypatch, quote):
    _use(monkeypatch, quote)
    seen = {}
    monkeypatch.setattr(scanner.time, "time", lambda: NOW)
    monkeypatch.setitem(scanner._DOWNSIDE_CACHE, "data", None)
    monkeypatch.setitem(scanner._DOWNSIDE_CACHE, "expires", 0.0)

    def watchlist(*args, **kwargs):
        seen.setdefault("watchlistArgs", []).append(args)
        return {"stocks": []}
    monkeypatch.setattr(scanner, "get_japan_watchlist_snapshot", watchlist)
    monkeypatch.setattr(scanner, "get_us_watchlist_snapshot", lambda: {"stocks": []})
    monkeypatch.setattr(scanner, "_owner_symbols_cached", lambda: {})
    monkeypatch.setattr(scanner, "get_market_news", lambda: {"status": "unavailable", "items": []})
    monkeypatch.setattr(scanner, "get_catalysts_snapshot", lambda: {"status": "unavailable"})
    monkeypatch.setattr(scanner, "get_tdnet_recent", lambda: {"official": False, "status": "unavailable"})
    original = argus_downside.classify_incidents

    def capture(assets, m=None, now_iso=None):
        seen["market"] = dict(m)
        return original(assets, m, now_iso=now_iso)
    monkeypatch.setattr(argus_downside, "classify_incidents", capture)
    return scanner.get_downside_incidents(), seen


def test_downside_market_context_reads_the_nikkei_and_records_the_delay(monkeypatch):
    payload, seen = _downside(monkeypatch, _quote(change=-2.7))
    assert seen["market"]["nikkeiProxyPct"] == -2.7
    assert seen["market"]["nikkeiStatus"] == "AVAILABLE"
    assert payload["jpIndex"]["status"] == "AVAILABLE"
    assert payload["jpIndex"]["delayed"] is True and payload["jpIndex"]["ageSeconds"] == 20 * 60
    assert payload["jpIntradayOverlay"] == "RISK_OFF_WATCH"        # -2.7% <= NIKKEI_RISK_HARD
    # The 1306/1321 ETFs are no longer read for the market tone.
    assert all(args == () for args in seen["watchlistArgs"])


def test_downside_without_the_nikkei_is_unknown_not_filled(monkeypatch):
    payload, seen = _downside(monkeypatch, {"status": "UNAVAILABLE", "quote": None})
    assert seen["market"]["nikkeiProxyPct"] is None
    assert seen["market"]["nikkeiStatus"] == "UNKNOWN"
    assert payload["jpIndex"] == {"instrumentId": "NIKKEI_225_INDEX", "status": "UNKNOWN",
                                  "changePct": None}
    assert "JP_INDEX_UNKNOWN" in payload["overlay"]["flags"]
    assert "地合いは不明" in payload["overlay"]["reasonJa"]
    assert "大きな崩れは確認されていない" not in payload["overlay"]["reasonJa"]
