from datetime import datetime, timezone

import argus_index_live as live


def _payload(price=69123.4, traded=1790900700, previous=68956.7, start=1790899200, end=1790922600):
    return {"chart": {"result": [{"meta": {"regularMarketPrice": price, "regularMarketTime": traded,
        "chartPreviousClose": previous, "currentTradingPeriod": {"regular": {"start": start, "end": end}}}}]}}


def test_quote_carries_trade_time_delay_and_change():
    quote = live.parse_quote(_payload(), received_epoch=1790901900)
    assert quote["price"] == 69123.4 and quote["previousClose"] == 68956.7
    assert abs(quote["changePct"] - (69123.4 / 68956.7 - 1) * 100) < 1e-9
    assert quote["delaySeconds"] == 1200 and quote["sessionOpen"] is True
    assert quote["realtime"] is False and quote["actionAuthority"] is False
    assert quote["tradedAt"].endswith("Z") and quote["source"].startswith("Yahoo")


def test_missing_price_or_time_is_rejected_and_closed_session_is_marked():
    assert live.parse_quote(_payload(price=None), received_epoch=1790901900) is None
    assert live.parse_quote(_payload(traded=None), received_epoch=1790901900) is None
    assert live.parse_quote({"chart": {"result": []}}, received_epoch=1) is None
    assert live.parse_quote(_payload(), received_epoch=1790930000)["sessionOpen"] is False


def test_session_window_is_tokyo_weekday_daytime():
    assert live.session_window(datetime(2026, 10, 2, 1, 0, tzinfo=timezone.utc))       # Fri 10:00 JST
    assert not live.session_window(datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc))   # Fri 17:00 JST
    assert not live.session_window(datetime(2026, 10, 3, 1, 0, tzinfo=timezone.utc))   # Sat


def test_refresh_keeps_the_last_good_quote_and_reports_failures(monkeypatch):
    monkeypatch.setattr(live, "_state", {"quote": None, "error": None, "thread": None})
    assert live.current_quote_safe()["status"] == "UNAVAILABLE"

    class Response:
        status_code = 200
        def json(self): return _payload()
    assert live.refresh_once(lambda *a, **k: Response(), now_epoch=1790901900)["price"] == 69123.4

    class Broken:
        status_code = 503
        def json(self): return {}
    assert live.refresh_once(lambda *a, **k: Broken(), now_epoch=1790901960) is None
    state = live.current_quote_safe()
    assert state["status"] == "AVAILABLE" and state["quote"]["price"] == 69123.4
    assert state["lastError"] == "ValueError"


def test_overnight_futures_are_read_outside_the_session_and_reported(monkeypatch):
    monkeypatch.setattr(live, "_state", {"quote": None, "error": None, "thread": None,
                                         "futures": None, "futuresError": None})
    calls = []

    class Response:
        status_code = 200
        def __init__(self, symbol): self.symbol = symbol
        def json(self):
            if self.symbol == live.FUTURES_SYMBOL:
                return _payload(price=69785.0, traded=1790971140, previous=68555.0, start=1790950000, end=1790990000)
            return _payload()
    def get(url, **kwargs):
        calls.append(url)
        return Response(live.FUTURES_SYMBOL if live.FUTURES_SYMBOL in url else live.SYMBOL)
    quote = live.refresh_futures_once(get, now_epoch=1790972000)
    assert quote["symbol"] == "NKD=F" and quote["price"] == 69785.0
    assert quote["instrumentId"] == "NIKKEI_225_CME_FUTURES_USD"
    assert quote["realtime"] is False and quote["actionAuthority"] is False
    state = live.current_quote_safe()
    assert state["status"] == "UNAVAILABLE" and state["overnightFutures"]["price"] == 69785.0

    class Broken:
        status_code = 500
        def json(self): return {}
    assert live.refresh_futures_once(lambda *a, **k: Broken(), now_epoch=1790972900) is None
    state = live.current_quote_safe()
    assert state["overnightFutures"]["price"] == 69785.0
    assert state["overnightFuturesError"] == "ValueError"


def test_loop_reads_futures_every_fifteen_minutes_only_outside_the_session(monkeypatch):
    monkeypatch.setattr(live, "_state", {"quote": None, "error": None, "thread": None,
                                         "futures": None, "futuresError": None})
    clock = [0.0]; urls = []; stop = 6
    class Done(Exception): pass

    class Response:
        status_code = 200
        def json(self): return _payload()
    def get(url, **kwargs):
        urls.append(url); return Response()
    def sleep(seconds):
        clock[0] += seconds
        if clock[0] >= stop * 300: raise Done()
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None): return datetime(2026, 10, 3, 1, 0, tzinfo=timezone.utc)   # Sat 10:00 JST
    monkeypatch.setattr(live, "datetime", Clock)
    monkeypatch.setattr(live, "POLL_SECONDS", 300)
    try:
        live._loop(get, sleep, clock=lambda: clock[0])
    except Done:
        pass
    futures = [u for u in urls if live.FUTURES_SYMBOL in u]
    assert len(futures) == 2                       # at 0 s and 900 s within 1,800 s
    assert len([u for u in urls if live.POLICY_RATE_SYMBOL in u]) == 2      # read alongside the future
    assert len([u for u in urls if live.SYMBOL in u]) == 1


def test_session_hours_do_not_read_futures(monkeypatch):
    monkeypatch.setattr(live, "_state", {"quote": None, "error": None, "thread": None,
                                         "futures": None, "futuresError": None})
    urls = []
    class Done(Exception): pass
    class Response:
        status_code = 200
        def json(self): return _payload()
    def sleep(seconds):
        if len(urls) >= 3: raise Done()
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None): return datetime(2026, 10, 2, 1, 0, tzinfo=timezone.utc)   # Fri 10:00 JST
    monkeypatch.setattr(live, "datetime", Clock)
    try:
        live._loop(lambda url, **k: (urls.append(url), Response())[1], sleep, clock=lambda: 0.0)
    except Done:
        pass
    assert urls and all(live.FUTURES_SYMBOL not in u for u in urls)


def test_policy_rate_future_is_read_with_the_overnight_future_and_bounded(monkeypatch):
    monkeypatch.setattr(live, "_state", {"quote": None, "error": None, "thread": None,
                                         "futures": None, "futuresError": None, "policyRate": None, "policyRateError": None})
    class Response:
        status_code = 200
        def __init__(self, price): self.price = price
        def json(self): return _payload(price=self.price, traded=1790971140, previous=96.05)
    quote = live.refresh_policy_rate_once(lambda url, **k: Response(96.07), now_epoch=1790972000)
    assert quote["symbol"] == "ZQ=F" and quote["impliedRatePct"] == 3.93
    assert live.current_quote_safe()["policyRateFutures"]["impliedRatePct"] == 3.93
    assert live.refresh_policy_rate_once(lambda url, **k: Response(5.0), now_epoch=1790972900) is None
    assert live.current_quote_safe()["policyRateFuturesError"] == "ValueError"
    assert live.current_quote_safe()["policyRateFutures"]["impliedRatePct"] == 3.93


# ── 2026-10-22: Tachibana Nikkei (101) uses the same minute-aware rule ──────
from datetime import timedelta  # noqa: E402

import argus_tachibana_live  # noqa: E402

_START = datetime(2026, 10, 22, 6, 0, tzinfo=timezone.utc)  # 15:00 JST


def _nikkei(monkeypatch, *, age, receipt_age=1.0, precision="MINUTE", status="OPEN",
            freshness="FRESH", approved=True):
    now = _START + timedelta(seconds=age)

    class Fixed(datetime):
        @classmethod
        def now(cls, tz=None):
            return now

    row = {"provider": "TACHIBANA", "price": 49123.4, "previousClose": 48900.0, "changePct": 0.46,
           "sourceTimestamp": _START.isoformat(), "sourceTimestampPrecision": precision,
           "receivedAt": (now - timedelta(seconds=receipt_age)).isoformat(),
           "freshness": freshness, "marketStatus": status}
    monkeypatch.setattr(live, "datetime", Fixed)
    monkeypatch.setattr(live, "_state", {"quote": None, "error": None, "thread": None})
    monkeypatch.setattr(argus_tachibana_live, "current_evidence_safe",
                        lambda *a, **k: {"displayApproved": approved, "symbols": {"101": row}})
    return live.current_quote_safe()


def test_tachibana_nikkei_minute_time_26_seconds_old_is_shown_with_its_own_minute(monkeypatch):
    state = _nikkei(monkeypatch, age=26)
    assert state["status"] == "AVAILABLE"
    quote = state["quote"]
    assert quote["source"] == "立花証券" and quote["realtime"] is True
    assert quote["tradedAt"] == _START.isoformat()  # never the receipt time
    assert quote["tradedAtPrecision"] == "MINUTE" and quote["delaySeconds"] == 26


def test_tachibana_nikkei_falls_back_when_old_unproven_future_or_closed(monkeypatch):
    for kwargs in ({"age": 80}, {"age": 16, "precision": "SECOND"}, {"age": 30, "receipt_age": 20},
                   {"age": -30}, {"age": 26, "status": "CLOSED"}, {"age": 26, "freshness": "DELAYED"},
                   {"age": 26, "approved": False}, {"age": 26, "precision": "UNAVAILABLE"}):
        state = _nikkei(monkeypatch, **kwargs)
        assert state["status"] == "UNAVAILABLE", kwargs
        assert state["quote"] is None


def test_tachibana_nikkei_second_precision_keeps_fifteen_seconds(monkeypatch):
    state = _nikkei(monkeypatch, age=15, precision="SECOND")
    assert state["status"] == "AVAILABLE" and state["quote"]["tradedAtPrecision"] == "SECOND"
