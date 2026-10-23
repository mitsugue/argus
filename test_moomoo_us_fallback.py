"""2026-10-22 (owner: moomoo is the primary US source; Twelve Data will be
cancelled once its use is zero): when the bridge row is missing or stale the US
price falls back to the existing delayed Yahoo route, marked as delayed, and the
Twelve Data price endpoint is no longer called."""
from datetime import datetime, timezone

import pytest

import argus_td_warm
import scanner

IN_SESSION = datetime(2026, 10, 22, 15, 0, tzinfo=timezone.utc)     # 11:00 New York
AFTER_CLOSE = datetime(2026, 10, 22, 22, 0, tzinfo=timezone.utc)    # 18:00 New York
CLOSE_EPOCH = datetime(2026, 10, 22, 20, 0, tzinfo=timezone.utc).timestamp()


class _Resp:
    def __init__(self, status, meta):
        self.status_code = status
        self._meta = meta

    def json(self):
        return {"chart": {"result": [{"meta": self._meta}]}}


@pytest.fixture
def yahoo(monkeypatch):
    urls = []
    state = {"status": 200, "meta": {}}

    def get(url, params=None, **kw):
        assert "twelvedata" not in url
        urls.append(url)
        return _Resp(state["status"], state["meta"])

    monkeypatch.setattr(scanner.requests, "get", get)
    monkeypatch.setattr(scanner, "_td_get", lambda *a, **k: (_ for _ in ()).throw(AssertionError("Twelve Data")))
    return urls, state


def _session(monkeypatch, value):
    monkeypatch.setattr(scanner, "_td_us_session", lambda now_utc=None: value)


def test_in_session_fallback_is_marked_delayed_and_leaves_the_change_missing(yahoo, monkeypatch):
    urls, state = yahoo
    _session(monkeypatch, "REGULAR")
    state["meta"] = {"regularMarketPrice": 101.25, "chartPreviousClose": 90.0,
                     "regularMarketTime": int(IN_SESSION.timestamp()) - 120}
    row = scanner._us_yahoo_delayed_row("BRK.B", now=IN_SESSION.timestamp())
    assert "/chart/BRK-B?" in urls[-1]
    assert row["source"] == "yahoo-delayed" and row["status"] == "delayed"
    assert row["delayClass"] == "20m" and row["realtimeEvidence"] is False
    assert row["changeAbs"] is None and row["changePct"] is None     # base is not proven to be yesterday
    assert row["sourceTimestamp"] == "2026-10-22T14:58:00Z"


def test_after_the_close_the_fallback_is_that_days_close(yahoo, monkeypatch):
    _urls, state = yahoo
    _session(monkeypatch, "AFTER_HOURS")
    state["meta"] = {"regularMarketPrice": 100.0, "regularMarketTime": int(CLOSE_EPOCH)}
    row = scanner._us_yahoo_delayed_row("NVDA", now=AFTER_CLOSE.timestamp())
    assert row["sourceTimestamp"] == "2026-10-22" and row["delayClass"] == "EOD"
    assert row["providerTimestamp"] == "2026-10-22T20:00:00Z"


def test_a_value_without_its_own_time_is_not_used(yahoo, monkeypatch):
    _urls, state = yahoo
    _session(monkeypatch, "REGULAR")
    state["meta"] = {"regularMarketPrice": 100.0}
    assert scanner._us_yahoo_delayed_row("NVDA", now=IN_SESSION.timestamp()) is None


def test_dynamic_snapshot_fetches_only_symbols_without_a_warm_row(yahoo, monkeypatch):
    urls, state = yahoo
    _session(monkeypatch, "REGULAR")
    now = scanner.time.time()
    state["meta"] = {"regularMarketPrice": 50.0, "regularMarketTime": int(now) - 60}
    monkeypatch.setattr(scanner, "_US_DYN_CACHE", {})
    monkeypatch.setattr(scanner, "_US_WARM_ROWS", {})
    scanner._td_warm_store([{"symbol": "NVDA", "price": 180.0, "source": "moomoo-rt",
                             "sourceTimestamp": now - 5, "status": "live"}], now, "REGULAR")
    snap = scanner._get_us_watchlist_core(["NVDA", "MU"], allow_provider_fetch=True)
    assert [row["symbol"] for row in snap["stocks"]] == ["NVDA", "MU"]
    assert len(urls) == 1 and "/chart/MU?" in urls[0]
    mu = snap["stocks"][1]
    assert mu["source"] == "yahoo-delayed" and mu["status"] == "delayed"


def test_warm_tick_backs_off_on_a_yahoo_rate_limit_without_twelve_data(yahoo, monkeypatch):
    urls, state = yahoo
    _session(monkeypatch, "REGULAR")
    monkeypatch.setattr(scanner, "_TWELVEDATA_API_KEY", None)
    monkeypatch.setattr(scanner, "_TD_WARM_STATE", argus_td_warm.new_state())
    monkeypatch.setattr(scanner, "_US_WARM_ROWS", {})
    monkeypatch.setattr(scanner, "_PUSHED_QUOTES", {"JP": {}, "US": {}})
    monkeypatch.setattr(scanner, "FINNHUB_API_KEY", "")
    monkeypatch.setattr(scanner, "_td_warm_universe",
                        lambda now=None: {"symbols": ["NVDA", "MU", "AMD"], "cadenceFit": {}})
    state["status"] = 429
    first = scanner._td_warm_tick(IN_SESSION)
    assert first["rateLimited"] is True and first["ok"] is False and len(urls) == 1
    held = scanner._td_warm_tick(datetime.fromtimestamp(IN_SESSION.timestamp() + 61, timezone.utc))
    assert held["action"] == "skip" and held["reason"] == "rate_limited_backoff"


def test_us_price_lamp_does_not_require_a_twelve_data_key(monkeypatch):
    monkeypatch.setattr(scanner, "_TWELVEDATA_API_KEY", None)
    health = scanner._system_health(allow_provider_fetch=False)
    lamp = next(row for row in health["lamps"] if row["key"] == "prices_us")
    assert "Twelve Data" not in lamp["detailJa"]
