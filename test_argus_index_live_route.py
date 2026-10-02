import argus_index_live as live
import scanner


def test_index_chart_live_reads_the_last_quote_without_a_provider_call(monkeypatch):
    quote = live.parse_quote({"chart": {"result": [{"meta": {"regularMarketPrice": 68250.39,
        "regularMarketTime": 1790904410, "chartPreviousClose": 68956.72,
        "currentTradingPeriod": {"regular": {"start": 1790899200, "end": 1790922600}}}}]}}, received_epoch=1790905315)
    monkeypatch.setattr(live, "_state", {"quote": quote, "error": None, "thread": None})
    monkeypatch.setattr(scanner.requests, "get", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no fetch")))
    body = scanner.app.test_client().get("/api/argus/index-chart?index=N225&live=1").get_json()
    assert body["status"] == "AVAILABLE" and body["quote"]["price"] == 68250.39
    assert body["quote"]["realtime"] is False and body["actionAuthority"] is False


def test_live_is_nikkei_only(monkeypatch):
    reply = scanner.app.test_client().get("/api/argus/index-chart?index=TOPIX&live=1")
    assert reply.status_code in (400,)
