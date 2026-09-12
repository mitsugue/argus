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


def test_same_runtime_balances_reach_unified_ai_with_provenance(feed, monkeypatch):
    scanner._jq_weekly_margin("1570")
    monkeypatch.setattr(scanner, "_important_events_data", lambda: {"events": [], "imminent": []})
    monkeypatch.setattr(scanner, "get_market_shock", lambda: {"events": []})
    monkeypatch.setattr(scanner, "_brief_market_view_summary", lambda: {})
    monkeypatch.setattr(scanner, "_brief_news_events", lambda: [])
    result = scanner._compose_market_brief()
    facts = result["facts"]
    raw = next(r for r in facts if r["source"] == "licensed_market_data")
    derived = next(r for r in facts if r["source"] == "derived_margin_change")
    assert "買残150口" in raw["text"] and "売残15口" in raw["text"]
    assert raw["verification"] == "VERIFIED"
    assert raw["provenance"]["publishedAt"] is None
    assert raw["provenance"]["receivedAt"] == "2026-09-12T01:12:11+00:00"
    assert len(raw["provenance"]["sourceResponseSha256"]) == 64
    assert derived["verification"] == "UNCONFIRMED"
    assert "買い戻し注文は未観測" in derived["text"]
    context = scanner.argus_market_brief.unified_context(result)
    assert any(r["text"] == raw["text"] for r in context["facts"])
    changed = copy.deepcopy(result)
    next(r for r in changed["facts"] if r["source"] == "licensed_market_data")["provenance"]["sourceRowSha256"] = "f" * 64
    assert scanner.argus_market_brief.unified_context(changed)["contextId"] != context["contextId"]


def test_margin_addition_preserves_full_news_and_event_slots(feed):
    scanner._jq_weekly_margin("1570")
    mb = scanner.argus_market_brief
    result = mb.compose_brief(now_iso=AT, margin_dynamics=scanner._jp_market_margin_1570_dynamics(),
        market_view_summary={"label": "市場の参考観測"},
        news_events=[{"severity": "HIGH", "headlineJa": "ニュース" + str(i),
                      "impactDirection": {"transmissionJa": "波及" + str(i)}} for i in range(2)],
        shock_events=[{"severity": "HIGH", "headlineJa": "市場リスク" + str(i), "whyJa": "背景"} for i in range(2)],
        imminent_events=[{"title": "SQ接近" + str(i)} for i in range(2)],
        next_events=[{"title": "次の予定" + str(i)} for i in range(2)])
    assert len(result["facts"]) == 16
    assert any("SQ接近" in r["text"] for r in result["facts"])
    assert len([r for r in result["facts"] if r["priority"] == "P3"]) == 3
    assert len(mb.unified_context(result)["facts"]) == 16


def test_failed_margin_fetch_is_not_a_new_confirmed_ai_fact(feed):
    scanner._jq_weekly_margin("1570")
    scanner._JQ_MARGIN_CACHE["1570"]["expires"] = 0
    feed[0].status_code = 503
    scanner._jq_weekly_margin("1570")
    result = scanner.argus_market_brief.compose_brief(now_iso=AT,
        margin_dynamics=scanner._jp_market_margin_1570_dynamics())
    raw = next(r for r in result["facts"] if r["source"] == "licensed_market_data")
    assert raw["verification"] == "UNCONFIRMED"
    assert "更新失敗・前回取得" in raw["text"]
