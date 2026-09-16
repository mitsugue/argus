"""Cached runtime integration: actual route, temporal limits and failure isolation."""
import copy
from datetime import date, timedelta

import pytest
import requests

import argus_market_clock as clock
from jp_market_price_paths import cached_index_comparison
import scanner


def history():
    start = date(2026, 1, 1)
    days = [(start + timedelta(days=i)).isoformat() for i in range(250)
            if clock.canonical_trading_day(clock.JP_EQUITY, start + timedelta(days=i))]
    rows = [{"instrumentId": "NIKKEI_225_INDEX", "field": "close", "date": day,
             "availableFrom": day + "T07:00:00Z", "close": 40000 + (i % 23) * 30,
             "sourceRef": "test:direct-index"} for i, day in enumerate(days)]
    return days, rows


def test_runtime_layers_reuse_one_selection_with_no_probability_authority():
    days, rows = history()
    result = cached_index_comparison(rows, cutoff=days[-1] + "T08:00:00Z", session_dates=days)
    chart = result["comparison"]
    assert result["status"] == "available"
    assert len(chart["candidates"]) >= 2
    assert len(chart["actual"]) == 21
    assert len(chart["forecast"]["line"]) == 6
    assert chart["calculationIdentity"]["selectionId"] == result["selection"]["selectionId"]
    assert chart["unit"] == "ANCHOR_100"
    assert result["selection"]["predictiveProbability"] is None
    assert result["selection"]["outcomesUsedForSelection"] is False
    assert result["actionAuthority"] is False
    assert result["historicalVintageVerified"] is False
    assert all(c["comparisonKind"] == "PARTIAL_COMPARISON" for c in chart["candidates"])


def test_post_cutoff_prices_cannot_change_any_runtime_calculation_identity():
    days, rows = history()
    cutoff = days[-2] + "T08:00:00Z"
    before = cached_index_comparison(rows, cutoff=cutoff, session_dates=days)
    changed = copy.deepcopy(rows)
    changed[-1]["close"] *= 100
    assert before == cached_index_comparison(changed, cutoff=cutoff, session_dates=days)


def test_missing_current_session_never_bridges_the_gap():
    days, rows = history()
    del rows[-4]
    result = cached_index_comparison(rows, cutoff=days[-1] + "T08:00:00Z", session_dates=days)
    assert result["comparison"] is None
    assert result["reason"] == "current_exchange_sessions_missing"


def test_missing_past_session_excludes_overlapping_candidates():
    days, rows = history()
    missing_day = rows[35]["date"]
    del rows[35]
    result = cached_index_comparison(rows, cutoff=days[-1] + "T08:00:00Z", session_dates=days)
    forbidden = set(days[35:56])
    assert missing_day in forbidden
    assert all(c["anchorDate"] not in forbidden for c in result["comparison"]["candidates"])


@pytest.mark.parametrize("horizon", [1, 5, 10, 20])
def test_existing_public_route_is_read_only_even_with_no_ai_budget(monkeypatch, horizon):
    days, rows = history()
    cached = {"data": rows, "acquiredAt": days[-1] + "T08:00:00Z", "expires": 0}
    monkeypatch.setattr(scanner, "_JP_MARKET_ENGINE_INDEX_OHLCV_CACHE", {"^N225": cached})
    monkeypatch.setattr(scanner, "_ai_now_iso", lambda: days[-1] + "T09:00:00Z")
    def forbidden(*args, **kwargs):
        raise AssertionError("cached comparison must not fetch, charge or write")
    monkeypatch.setattr(requests.sessions.Session, "request", forbidden)
    for name in ("_openai_prose", "_openai_judge", "_cost_policy_persist_durable"):
        monkeypatch.setattr(scanner, name, forbidden)
    before = copy.deepcopy(cached)
    monkeypatch.setattr(scanner, "_INDEX_RESEARCH_REPORTS", {})
    monkeypatch.setattr(scanner, "_INDEX_RESEARCH_STATUS", {"restoreAttempted": False})
    monkeypatch.setattr(scanner, "_index_research_path", lambda: None)
    monkeypatch.setattr(scanner.argus_index_research_cache, "KEYS", {f"comparison:N225:{horizon}"})
    scanner._index_research_warm()
    monkeypatch.setattr(scanner, "_jp_market_comparison_calculate", forbidden)
    monkeypatch.setattr(scanner, "_index_research_warm", forbidden)
    with scanner.app.test_client() as client:
        response = client.get(f"/api/argus/index-chart?index=N225&comparison=1&horizon={horizon}")
    assert response.status_code == 200
    body = response.get_json()
    assert body["status"] == "available"
    assert body["comparison"]["forecast"]["horizonSessions"] == horizon
    assert body["lastSuccessfulAcquisitionAt"] == cached["acquiredAt"]
    assert before == cached


def test_cold_and_invalid_requests_are_explicit(monkeypatch):
    monkeypatch.setattr(scanner, "_INDEX_RESEARCH_REPORTS", {})
    monkeypatch.setattr(scanner, "_JP_MARKET_ENGINE_INDEX_OHLCV_CACHE", {})
    with scanner.app.test_client() as client:
        body = client.get("/api/argus/index-chart?index=N225&comparison=1").get_json()
        assert body["reason"] == "index_research_preparing"
        assert body["comparison"] is None
        for params in ("index=SPX", "index=N225&timeframe=weekly", "horizon=0", "horizon=bad"):
            assert client.get("/api/argus/index-chart?comparison=1&" + params).status_code == 400


def test_runtime_compares_available_market_state_order_and_reaction_without_authority():
    days, rows = history()
    states = [{"instrumentId": "NIKKEI_225_INDEX", "date": day, "seriesId": "vix.level",
               "value": 20 + i % 3, "unit": "INDEX_POINTS", "availableFrom": day + "T07:00:00Z",
               "sourceRef": "test:observed-volatility"} for i, day in enumerate(days)]
    conditions = [{**row, "seriesId": "vix_macd_cross", "unit": "DIRECTION", "value": 1}
                  for i, row in enumerate(states) if i % 10 == 0]
    reactions = [{**row, "seriesId": "policy_reaction", "unit": "PERCENT", "value": 1,
                  "eventId": "test:policy:" + row["date"], "eventType": "MONETARY_POLICY",
                  "reactionWindowSessions": 1} for i, row in enumerate(states) if i % 10 == 0]
    before = copy.deepcopy([states, conditions, reactions])
    result = cached_index_comparison(rows, cutoff=days[-1] + "T08:00:00Z", session_dates=days,
                                    state_rows=states, condition_rows=conditions, reaction_rows=reactions)
    evidence = result["comparison"]["marketEvidence"]
    assert evidence["currentCounts"]["states"] == 1
    assert evidence["candidateCoverage"]["states"] > 0
    assert all(value > 0 for value in evidence["currentCounts"].values())
    assert any("marketState" in candidate["similarityReasons"] for candidate in result["selection"]["selected"])
    assert result["selection"]["status"] == "PARTIAL_COMPARISONS_ONLY"
    assert result["selection"]["predictiveProbability"] is None
    assert result["actionAuthority"] is False and before == [states, conditions, reactions]


def test_runtime_late_revision_does_not_replace_past_known_market_state():
    days, rows = history()
    states = [{"instrumentId": "NIKKEI_225_INDEX", "date": day, "seriesId": "vix.level",
               "value": 20, "unit": "INDEX_POINTS", "availableFrom": day + "T07:00:00Z",
               "sourceRef": "test:observed-volatility", "revision": 0} for day in days]
    args = {"cutoff": days[-1] + "T08:00:00Z", "session_dates": days}
    baseline = cached_index_comparison(rows, state_rows=states, **args)
    corrected = {**states[35], "value": 200, "revision": 1, "knownAt": args["cutoff"]}
    assert baseline == cached_index_comparison(rows, state_rows=states + [corrected], **args)
    future = {**states[-1], "value": 300, "revision": 1, "knownAt": days[-1] + "T09:00:00Z"}
    assert baseline == cached_index_comparison(rows, state_rows=states + [future], **args)


def test_runtime_bounds_market_evidence_before_comparison():
    days, rows = history()
    with pytest.raises(ValueError, match="market_evidence_history_bound_exceeded"):
        cached_index_comparison(rows, cutoff=days[-1] + "T08:00:00Z", session_dates=days,
                                state_rows=[{}] * 60001)


def test_ten_year_candidate_search_includes_past_years_and_exposes_its_scope():
    # Deliberately synthetic trading-day sequence, independently passed as calendar.
    first=date(2016,9,16)
    days=[(first+timedelta(days=i)).isoformat() for i in range(3652)
          if (first+timedelta(days=i)).weekday()<5]
    rows=[{'instrumentId':'NIKKEI_225_INDEX','field':'close','date':day,'close':40000+(i%20)*20,
           'availableFrom':day+'T07:00:00Z','sourceRef':'test:ten-year-direct-index'}
          for i,day in enumerate(days)]
    result=cached_index_comparison(rows,cutoff=days[-1]+'T23:59:59Z',session_dates=days)
    coverage=result['comparison']['historyCoverage']
    assert coverage['sourceBars']>2400
    assert coverage['candidateStart']<'2017-01-01'
    assert all(str(year) in coverage['candidatesByYear'] for year in range(2017,2026))
    assert any(row['anchorDate']<'2020-01-01' for row in result['selection']['selected'])
    assert result['selection']['outcomesUsedForSelection'] is False
    assert coverage['allMarketFeaturesTenYearsVerified'] is False
    assert coverage==result['historyCoverage']
