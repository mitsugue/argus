import json

import argus_analyst_targets as t
import scanner

PAYLOAD = {"quoteSummary": {"result": [{"financialData": {
    "currentPrice": {"raw": 5598.0}, "targetMeanPrice": {"raw": 7351.6665}, "targetMedianPrice": {"raw": 7500.0},
    "targetHighPrice": {"raw": 11700.0}, "targetLowPrice": {"raw": 3500.0},
    "numberOfAnalystOpinions": {"raw": 12}, "financialCurrency": "JPY", "recommendationKey": "buy"}}]}}


def test_parse_keeps_the_spread_and_count_but_no_recommendation_word():
    row = t.parse_financial_data("5803", PAYLOAD, fetched_at="2026-10-04T11:00:00Z")
    assert (row["mean"], row["median"], row["high"], row["low"], row["analysts"]) == (7351.67, 7500.0, 11700.0, 3500.0, 12)
    assert row["gapPct"] == 31.3 and row["currency"] == "JPY" and row["source"] == "Yahoo Finance"
    assert "buy" not in json.dumps(row) and row["actionAuthority"] is False
    assert t.parse_financial_data("1570", {"quoteSummary": {"result": [{"financialData": {}}]}}, fetched_at="x") is None
    assert t.yahoo_symbol("JP", "5803") == "5803.T" and t.yahoo_symbol("US", "NVDA") == "NVDA"
    assert t.due({"fetchedDayJst": "2026-10-04"}, "2026-10-04") is False and t.due(None, "2026-10-04") is True


def test_warm_fetches_once_a_day_and_the_route_never_fetches(monkeypatch, tmp_path):
    calls = []

    class Response:
        def __init__(self, status, body=None, text=""):
            self.status_code, self._body, self.text = status, body, text
        def json(self):
            return self._body

    class Session:
        headers = {}
        def get(self, url, params=None, **kw):
            calls.append(url)
            if "getcrumb" in url:
                return Response(200, text="crumb123")
            if "quoteSummary/5803.T" in url:
                return Response(200, PAYLOAD)
            if "quoteSummary" in url:
                return Response(200, {"quoteSummary": {"result": [{"financialData": {}}]}})
            return Response(200)

    monkeypatch.setattr(scanner.requests, "Session", Session)
    monkeypatch.setattr(scanner, "_analyst_targets_path", lambda: str(tmp_path / "targets.json"))
    monkeypatch.setattr(scanner, "_analyst_targets_symbols", lambda: [("JP", "5803"), ("JP", "1570")])
    monkeypatch.setattr(scanner, "_ANALYST_TARGETS", {"loaded": False, "items": {}, "lastAttemptAt": None,
                                                      "lastError": None, "fetchedLastWarm": 0})
    scanner._analyst_targets_warm()
    assert scanner._ANALYST_TARGETS["items"]["JP:5803"]["mean"] == 7351.67
    assert scanner._ANALYST_TARGETS["items"]["JP:1570"]["unavailable"] is True
    first = len(calls)
    scanner._analyst_targets_warm()                       # same JST day: nothing fetched
    assert len(calls) == first
    saved = json.loads((tmp_path / "targets.json").read_text())
    assert saved["schemaVersion"] == t.SCHEMA and "JP:5803" in saved["items"]
    client = scanner.app.test_client()
    body = client.get("/api/argus/analyst-targets").get_json()
    assert list(body["items"]) == ["JP:5803"] and body["actionAuthority"] is False
    assert len(calls) == first                            # the route never fetches
