import copy
import json

import pytest

import scanner


ROWS = [
    {"Date": "2026-08-28", "Code": "15700", "LongVol": 120, "ShrtVol": 20,
     "LongStdVol": 80, "LongNegVol": 40, "ShrtStdVol": 18, "ShrtNegVol": 2},
    {"Date": "2026-09-04", "Code": "15700", "LongVol": 150, "ShrtVol": 15,
     "LongStdVol": 100, "LongNegVol": 50, "ShrtStdVol": 12, "ShrtNegVol": 3},
]
AT = "2026-09-12T01:12:11Z"


@pytest.fixture
def feed(monkeypatch):
    class Response:
        status_code = 200
        payload = {"data": copy.deepcopy(ROWS)}
        @property
        def content(self):
            return json.dumps(self.payload).encode()
        def json(self):
            return self.payload
    response = Response()
    calls = []
    def get(*args, **kwargs):
        calls.append(args[0])
        return response
    monkeypatch.setattr(scanner, "_JQ_MARGIN_CACHE", {})
    monkeypatch.setattr(scanner, "_JQUANTS_API_KEY", "test-only")
    monkeypatch.setattr(scanner, "_ai_now_iso", lambda: AT)
    monkeypatch.setattr(scanner.requests, "get", get)
    return response, calls


def test_collect_preserves_old_totals_and_all_credit_components(feed):
    result = scanner._jq_weekly_margin("1570")
    assert result == [{"date": r["Date"], "longVol": float(r["LongVol"]),
                       "shortVol": float(r["ShrtVol"])} for r in reversed(ROWS)]
    snapshot = scanner._JQ_MARGIN_CACHE["1570"]["sourceSnapshot"]
    assert len(snapshot["rows"]) == 12
    assert {r["seriesId"] for r in snapshot["rows"]} == {
        "margin.long_balance", "margin.short_balance", "margin.standardized.long_balance",
        "margin.standardized.short_balance", "margin.negotiable.long_balance", "margin.negotiable.short_balance"}
    assert all(r["publishedAt"] is None and not r["creditTermKnown"] for r in snapshot["rows"])


def test_ratio_formula_preserved_with_actual_availability(feed):
    result = scanner._jp_market_engine_margin_1570_rows(fetch=True)
    assert [r["value"] for r in result] == [6, 10]
    assert all(r["availableFrom"] == "2026-09-12T01:12:11+00:00" for r in result)
    assert scanner._jp_market_margin_1570_dynamics(cutoff="2026-09-11T23:00:00Z")["current"] is None
    current = scanner._jp_market_margin_1570_dynamics(cutoff="2026-09-12T02:00:00Z")
    assert current["change"]["ratioChange"] == 4
    assert current["change"]["longContribution"] + current["change"]["shortContribution"] == pytest.approx(4)
    assert current["observedCoveringOrders"] is False
    assert current["predictiveProbability"] is None


def test_public_reads_do_not_fetch_or_mutate(feed):
    scanner._jq_weekly_margin("1570")
    before = copy.deepcopy(scanner._JQ_MARGIN_CACHE)
    calls = len(feed[1])
    scanner._jp_market_margin_1570_dynamics()
    scanner._jp_market_engine_margin_1570_rows()
    assert scanner._JQ_MARGIN_CACHE == before
    assert len(feed[1]) == calls


@pytest.mark.parametrize("failure", [403, 503, "empty", "malformed"])
def test_failed_acquisition_retains_last_good_with_failure_status(feed, failure):
    scanner._jq_weekly_margin("1570")
    before = copy.deepcopy(scanner._JQ_MARGIN_CACHE["1570"]["sourceSnapshot"])
    scanner._JQ_MARGIN_CACHE["1570"]["expires"] = 0
    if isinstance(failure, int):
        feed[0].status_code = failure
    elif failure == "empty":
        feed[0].payload = {"data": []}
    else:
        feed[0].payload = {"data": [dict(ROWS[-1], LongStdVol=999)]}
    scanner._jq_weekly_margin("1570")
    after = scanner._jp_market_margin_1570_dynamics()
    assert scanner._JQ_MARGIN_CACHE["1570"]["sourceSnapshot"] == before
    assert after["acquisitionStatus"] not in {"AVAILABLE", "PARTIAL"}
    assert after["lastSuccessfulAcquisitionAt"] == before["observedAt"]


def test_legacy_cache_has_no_invented_receipt(feed):
    scanner._JQ_MARGIN_CACHE["1570"] = {"data": [{"date": "2026-09-04", "longVol": 150, "shortVol": 15}], "expires": 0}
    assert scanner._jp_market_engine_margin_1570_rows() == []
    assert scanner._jp_market_margin_1570_dynamics()["acquisitionStatus"] == "NOT_ACQUIRED"
    assert feed[1] == []


def test_incomplete_pagination_is_visible(feed):
    feed[0].payload["pagination_key"] = "not-exposed"
    scanner._jq_weekly_margin("1570")
    result = scanner._jp_market_margin_1570_dynamics()
    assert result["paginationRemaining"] is True
    assert result["sourceStatus"] == "PARTIAL"
    assert "not-exposed" not in json.dumps(result)
