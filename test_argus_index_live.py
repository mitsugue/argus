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
