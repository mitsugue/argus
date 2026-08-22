import copy
from unittest import mock

import argus_decision_ledger
import argus_market_data_truth
import scanner
from scripts import run_prediction_ledger


DECISION_AT = "2026-08-14T06:40:00Z"
GENERATED_AT = "2026-08-14T06:40:01Z"
BUILD_SHA = "a" * 40


def _legacy_prediction():
    return {
        "symbol": "7203", "market": "JP", "price": 2800.0,
        "action": "buy_dip",
        "scenarios": [
            {"label": "downside_continuation", "p": 20},
            {"label": "sideways_stabilization", "p": 50},
            {"label": "rebound_attempt", "p": 30},
        ],
    }


def _jquants_row(**changes):
    row = {
        "symbol": "7203", "price": 2800.0, "changePct": 1.0,
        "volume": 1000, "open": 2770.0, "high": 2820.0,
        "low": 2750.0, "close": 2800.0,
        "date": "2026-08-14", "sourceTimestamp": "2026-08-14",
        "receivedAt": DECISION_AT, "source": "jquants",
        "status": "live",
    }
    row.update(changes)
    return row


def _projection(*, legacy_rows=None, quote_rows=None,
                decision_at=DECISION_AT, generated_at=GENERATED_AT):
    with mock.patch.object(scanner, "_backend_exact_sha",
                           return_value=BUILD_SHA):
        return scanner._canonical_prediction_ledger_projection(
            legacy_rows=(legacy_rows if legacy_rows is not None else
                         [("tactical_rule", _legacy_prediction())]),
            quote_rows=(quote_rows if quote_rows is not None else
                        [("JP", "jquants", _jquants_row())]),
            decision_at=decision_at, generated_at=generated_at,
            engine_version="fixture-v1")


def _epoch_iso(value):
    return scanner.datetime.fromtimestamp(
        value, scanner.pytz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _rate_row(provider, value, source_timestamp, *,
              received_at="2026-08-14T00:59:50Z", status="live"):
    return {
        "label": "US 10Y", "latestValue": value,
        "previousValue": value, "change": 0.0, "changeBp": 0.0,
        "latestDate": str(source_timestamp or "")[:10] or None,
        "sourceTimestamp": source_timestamp,
        "receivedAt": received_at, "knownAt": received_at,
        "source": provider, "status": status,
    }


def test_one_source_age_contract_never_promotes_missing_old_or_future():
    now = 1_800_000_000.0
    missing = scanner._canonical_quote_source_age(None, now_epoch=now)
    old = scanner._canonical_quote_source_age(
        _epoch_iso(now - 3600), now_epoch=now)
    future = scanner._canonical_quote_source_age(
        _epoch_iso(now + 1), now_epoch=now)
    fresh = scanner._canonical_quote_source_age(
        _epoch_iso(now - 60), now_epoch=now)

    assert [missing["status"], old["status"], future["status"]] == [
        "delayed", "delayed", "delayed"]
    assert missing["ageSec"] is None
    assert future["ageSec"] is None and future["timestampInversion"] is True
    assert fresh["status"] == "live" and fresh["ageSec"] == 60


def test_moomoo_push_ingestion_and_cached_read_never_use_transport_as_live(
        monkeypatch):
    now = 1_800_000_000.0
    monkeypatch.setattr(scanner.time, "time", lambda: now)
    monkeypatch.setattr(scanner, "_PUSHED_QUOTES", {"JP": {}, "US": {}})
    monkeypatch.setattr(scanner, "_PUSH_HISTORY", {"JP": {}, "US": {}})
    monkeypatch.setattr(scanner, "_require_admin", lambda: (True, None, 200))
    monkeypatch.setattr(
        scanner, "_verify_bridge_signature", lambda _raw: (True, "verified"))
    monkeypatch.setattr(scanner, "_process_events_from_push",
                        lambda _market, _rows: None)

    payload = {"stocks": [
        {"market": "US", "symbol": "AAPL", "price": 100.0,
         "entitlement": "realtime"},
        {"market": "US", "symbol": "MSFT", "price": 101.0,
         "exchangeTs": now + 1, "entitlement": "realtime"},
        {"market": "US", "symbol": "NVDA", "price": 102.0,
         "exchangeTs": now - 3600, "entitlement": "realtime"},
        {"market": "US", "symbol": "SPY", "price": 103.0,
         "exchangeTs": now - 30, "entitlement": "realtime"},
        {"market": "US", "symbol": "QQQ", "price": 104.0,
         "exchangeTs": now - 30, "entitlement": "delayed"},
    ]}
    with scanner.app.test_client() as client:
        response = client.post("/api/argus/quote-push", json=payload)
    assert response.status_code == 200
    assert response.get_json()["accepted"] == 5

    ingested = {symbol: pushed["row"] for symbol, pushed in
                scanner._PUSHED_QUOTES["US"].items()}
    assert ingested["AAPL"]["status"] == "delayed"
    assert ingested["AAPL"]["sourceTimeStatus"] == "MISSING"
    assert ingested["MSFT"]["status"] == "delayed"
    assert ingested["MSFT"]["timestampInversion"] is True
    assert ingested["NVDA"]["status"] == "delayed"
    assert ingested["NVDA"]["ageSec"] == 3600
    assert ingested["SPY"]["status"] == "live"
    assert ingested["SPY"]["realtimeEvidence"] is True
    assert ingested["QQQ"]["status"] == "delayed"
    assert ingested["QQQ"]["delayClass"] == "15m"

    cached = {symbol: scanner._quote_cached_only(symbol, "US")
              for symbol in ingested}
    assert cached["AAPL"]["status"] == "delayed"
    assert cached["AAPL"]["realtimeEvidence"] is False
    assert cached["MSFT"]["status"] == "delayed"
    assert cached["MSFT"]["timestampInversion"] is True
    assert cached["NVDA"]["status"] == "delayed"
    assert cached["NVDA"]["ageSec"] == 3600
    assert cached["SPY"]["status"] == "live"
    assert cached["SPY"]["ageSec"] == 30
    assert cached["QQQ"]["status"] == "delayed"
    assert all(cached[symbol]["transportAgeSec"] == 0 for symbol in cached)


def test_moomoo_push_invalid_source_time_cannot_enter_history_or_events(
        monkeypatch):
    now = 1_800_000_000.0
    monkeypatch.setattr(scanner.time, "time", lambda: now)
    monkeypatch.setattr(scanner, "_PUSHED_QUOTES", {"JP": {}, "US": {}})
    monkeypatch.setattr(scanner, "_PUSH_HISTORY", {"JP": {}, "US": {}})
    monkeypatch.setattr(scanner, "_require_admin", lambda: (True, None, 200))
    monkeypatch.setattr(
        scanner, "_verify_bridge_signature", lambda _raw: (True, "verified"))
    monkeypatch.setattr(scanner, "_EVENT_BACKBONE_ENABLED", True)
    monkeypatch.setattr(scanner, "_us_market_open", lambda: True)
    monkeypatch.setattr(scanner, "_EVENT_STATE", {
        "lastDetectionAt": None, "detections": 0})
    monkeypatch.setattr(scanner.argus_events, "detect_anomalies",
                        lambda *_a, **_k: [{
                            "type": "PRICE_SPIKE", "severity": 4}])
    monkeypatch.setattr(
        scanner.argus_events, "detect_acceleration", lambda *_a, **_k: [])
    recorded = []
    monkeypatch.setattr(
        scanner, "_record_event",
        lambda market, symbol, *_a, **_k: recorded.append(
            (market, symbol)) or {"symbol": symbol})

    payload = {"stocks": [
        {"market": "US", "symbol": "AAPL", "price": 100.0,
         "changePct": 6.0, "entitlement": "realtime"},
        {"market": "US", "symbol": "MSFT", "price": 101.0,
         "changePct": 6.0, "exchangeTs": now + 1,
         "entitlement": "realtime"},
        {"market": "US", "symbol": "NVDA", "price": 102.0,
         "changePct": 6.0, "exchangeTs": now - 3600,
         "entitlement": "realtime"},
        {"market": "US", "symbol": "SPY", "price": 103.0,
         "changePct": 6.0, "exchangeTs": now - 30,
         "entitlement": "realtime"},
    ]}
    with scanner.app.test_client() as client:
        response = client.post("/api/argus/quote-push", json=payload)
    assert response.status_code == 200
    assert response.get_json()["accepted"] == 4
    assert set(scanner._PUSH_HISTORY["US"]) == {"SPY"}
    assert recorded == [("US", "SPY")]

    # The processing boundary also revalidates source time instead of trusting
    # a forged/stale stored realtimeEvidence marker.
    recorded.clear()
    scanner._process_events_from_push("US", [{
        "symbol": "AAPL", "price": 100.0, "changePct": 6.0,
        "realtimeEvidence": True, "exchangeTs": None,
        "entitlement": "realtime",
    }])
    assert recorded == []


def test_yahoo_rate_source_time_hostile_matrix(monkeypatch):
    now = 1_800_000_000.0
    monkeypatch.setattr(scanner.time, "time", lambda: now)
    monkeypatch.setattr(scanner, "_ai_now_iso", lambda: _epoch_iso(now))

    def normalized(source_timestamp):
        scanner._YF_RT_CACHE.clear()
        scanner._YF_RT_CACHE.update({"data": None, "expires": 0.0})
        monkeypatch.setattr(
            scanner, "_yf_quote",
            lambda _sym: (4.0, 3.9, source_timestamp))
        return scanner._yahoo_rates_rt()["us10y"]

    plus_one = normalized(now + 1)
    plus_hour = normalized(now + 3600)
    malformed = normalized("not-a-source-time")
    missing = normalized(None)
    stale_transport_fresh = normalized(now - 3600)
    delayed_transport_allowed = normalized(now - 600)

    for row in (plus_one, plus_hour):
        assert row["status"] != "live"
        assert row["sourceTimeStatus"] == "FUTURE"
        assert row["sourceAgeSec"] is None
        assert row["timestampInversion"] is True
    assert malformed["status"] != "live"
    assert malformed["sourceTimeStatus"] == "MALFORMED"
    assert missing["status"] != "live"
    assert missing["sourceTimeStatus"] == "MISSING"
    assert stale_transport_fresh["status"] != "live"
    assert stale_transport_fresh["sourceAgeSec"] == 3600
    # Source and receipt remain separate; a bounded ten-minute delivery delay is
    # still decision-fresh under the explicit twenty-minute rate budget.
    assert delayed_transport_allowed["status"] == "live"
    assert delayed_transport_allowed["sourceAgeSec"] == 600


def test_canonical_rate_disagreement_and_fallback_matrix():
    decision_at = "2026-08-14T01:00:00Z"
    yahoo = _rate_row("yahoo-rt", 4.0, "2026-08-14T00:59:00Z")
    fred_equal = _rate_row(
        "fred", 4.0, "2026-08-13", status="live")
    exact = scanner._select_rate_truth(
        "us10y", [fred_equal, yahoo], decision_at)
    assert exact["selectedProvider"] == "yahoo"
    assert exact["latestValue"] == 4.0
    assert exact["providerDisagreement"]["status"] == "NONE"
    assert exact["providerSelectionPolicyId"] == \
        argus_market_data_truth.AUTHORITY_POLICY_ID
    assert exact["observedAt"] and exact["receivedAt"] and exact["knownAt"]
    assert exact["freshness"] == argus_market_data_truth.FRESH
    assert exact["completeness"] == argus_market_data_truth.COMPLETE

    small = scanner._select_rate_truth(
        "us10y", [yahoo, _rate_row(
            "fred", 4.002, "2026-08-13", status="live")], decision_at)
    assert small["providerDisagreement"]["status"] == "PRESENT"
    assert small["providerDisagreement"]["material"] is False

    material = scanner._select_rate_truth(
        "us10y", [yahoo, _rate_row(
            "fred", 4.2, "2026-08-13", status="live")], decision_at)
    assert material["providerDisagreement"]["status"] == "PRESENT"
    assert material["providerDisagreement"]["material"] is True
    comparison = material["providerDisagreement"]["comparisons"][0]
    assert any(field["field"] == "rate" and field["absoluteDelta"] == 0.2
               for field in comparison["fields"])

    stale_yahoo = _rate_row(
        "yahoo-rt", 9.0, "2026-08-01T00:00:00Z",
        received_at="2026-08-14T00:59:50Z")
    fallback = scanner._select_rate_truth(
        "us10y", [stale_yahoo, fred_equal], decision_at)
    assert fallback["selectedProvider"] == "fred"
    assert fallback["selectionReason"] == \
        "selected_effective_quality_then_repository_priority"
    assert any(row["provider"] == "yahoo" and
               row["reason"] == "lower_effective_freshness"
               for row in fallback["providerAlternates"])

    one_missing = scanner._select_rate_truth(
        "us10y", [None, fred_equal], decision_at)
    assert one_missing["selectedProvider"] == "fred"
    assert len(one_missing["providerCandidates"]) == 1
    malformed_yahoo = _rate_row("yahoo-rt", 9.0, "bad-time")
    source_fallback = scanner._select_rate_truth(
        "us10y", [malformed_yahoo, fred_equal], decision_at)
    assert source_fallback["selectedProvider"] == "fred"
    assert len(source_fallback["providerCandidates"]) == 1

    reverse = scanner._select_rate_truth(
        "us10y", [yahoo, fred_equal], decision_at)
    assert reverse["providerCandidates"] == exact["providerCandidates"]
    assert reverse["providerDisagreement"] == exact["providerDisagreement"]


def test_rate_provider_disagreement_survives_every_downstream_adapter(monkeypatch):
    decision_at = "2026-08-14T01:00:00Z"
    def selected(key, yahoo_value, fred_value):
        return scanner._select_rate_truth(key, [
            _rate_row("yahoo-rt", yahoo_value,
                      "2026-08-14T00:59:00Z"),
            _rate_row("fred", fred_value, "2026-08-13", status="live"),
        ], decision_at)

    rates = {
        "us10y": selected("us10y", 4.0, 4.2),
        "us2y": selected("us2y", 4.1, 4.1),
        "usReal10y": selected("usReal10y", 1.8, 1.8),
        "vix": selected("vix", 18.0, 19.0),
        "usdJpy": selected("usdJpy", 150.0, 151.0),
        "status": "partial", "freshness": "delayed",
        "completeness": "complete", "missingSeries": [],
    }
    backdrop = scanner._regime_rates_backdrop(
        rates, {"latestValue": 3.0, "change": 0.0})
    evidence = backdrop["rateTruthEvidence"]
    ten_year = evidence["series"]["us10y"]
    assert evidence["schemaVersion"] == "canonical-rate-evidence-v1"
    assert ten_year["selectedProvider"] == "yahoo"
    assert ten_year["providerSelectionPolicyId"] == \
        argus_market_data_truth.AUTHORITY_POLICY_ID
    assert ten_year["selectionReason"]
    assert len(ten_year["candidates"]) == 2
    assert len(ten_year["alternates"]) == 1
    assert ten_year["disagreement"]["status"] == "PRESENT"
    assert ten_year["disagreement"]["material"] is True
    assert ten_year["observedAt"] and ten_year["receivedAt"] \
        and ten_year["knownAt"]
    digest_projection = scanner._bounded_rates_backdrop_projection({
        **backdrop, "arbitrary": {"mustNotSurvive": True}})
    assert digest_projection["rateTruthEvidence"] == evidence
    assert "arbitrary" not in digest_projection

    contexts = scanner._prediction_rate_context_variables(rates)
    assert [row["contextId"] for row in contexts] == [
        "fx_usdjpy", "volatility_vix"]
    for row in contexts:
        assert row["asOf"] == row["observedAt"]
        assert row["providerEvidence"]["providerSelectionPolicyId"] == \
            argus_market_data_truth.AUTHORITY_POLICY_ID
        assert row["providerEvidence"]["alternates"]
        assert row["providerEvidence"]["disagreement"]["status"] == "PRESENT"

    empty = {"status": "live", "stocks": [], "events": [], "labels": [],
             "items": [], "sources": []}
    regime = {
        "status": "live", "engineVersion": "regime-v1",
        "regime": {}, "ratesBackdrop": backdrop, "matrix": {},
        "rotationGroups": [], "topRotations": [],
        "supportingEvidence": [], "sourceStatuses": {},
    }
    monkeypatch.setattr(scanner, "get_rates_snapshot", lambda: rates)
    monkeypatch.setattr(scanner, "get_japan_watchlist_snapshot", lambda: empty)
    monkeypatch.setattr(scanner, "get_us_watchlist_snapshot", lambda: empty)
    monkeypatch.setattr(scanner, "get_events_snapshot", lambda: empty)
    monkeypatch.setattr(scanner, "get_action_labels", lambda: empty)
    monkeypatch.setattr(scanner, "get_catalysts_snapshot", lambda: empty)
    monkeypatch.setattr(scanner, "get_market_regime_snapshot", lambda: regime)
    for name in ("_pro_events_section", "_pro_downside_section"):
        monkeypatch.setattr(scanner, name, lambda: "")
    for name in ("_institutional_signals", "_flow_attribution_list",
                 "_supply_demand_list", "_scenario_list", "_trade_plan_list",
                 "_action_priority_items", "_watchlist_theme_items"):
        monkeypatch.setattr(scanner, name, lambda *args, **kwargs: [])
    monkeypatch.setattr(scanner, "_session_brief_public", lambda: {})
    handoff = scanner._build_pro_handoff()
    assert handoff["rateTruthEvidence"] == evidence
    prompt = handoff["promptText"]
    assert "Canonical Rate Provider Evidence" in prompt
    assert "us10y: selectedProvider=yahoo" in prompt
    assert argus_market_data_truth.AUTHORITY_POLICY_ID in prompt
    assert "fred:4.2" in prompt
    assert "disagreement=PRESENT" in prompt
    assert "delta=[fred." in prompt


def test_future_and_missing_rate_observations_fail_before_market_truth():
    received = "2026-08-14T00:59:50Z"
    decision = "2026-08-14T01:00:00Z"
    for source in (
            "2026-08-14T00:59:51Z",  # +1 second versus receipt
            "2026-08-14T01:59:50Z",  # +1 hour versus receipt
            "malformed", None):
        row = _rate_row("yahoo-rt", 4.0, source, received_at=received)
        assert scanner._rate_observation("us10y", row, decision) is None


def test_hy_oas_cannot_affect_regime_without_canonical_usable_source_time():
    decision = "2026-08-14T01:00:00Z"
    rates = {
        "us10y": {"latestValue": 4.0, "change": 0.0},
        "us2y": {"latestValue": 3.8},
        "usReal10y": {"latestValue": 2.0},
        "vix": {"latestValue": 15.0},
    }
    hostile = [
        _rate_row("fred", 8.0, "2026-08-04", status="live"),
        _rate_row("fred", 8.0, None, status="live"),
        _rate_row("fred", 8.0, "2026-08-15", status="live"),
    ]
    for raw in hostile:
        selected = scanner._select_rate_truth("hyOas", [raw], decision)
        assert selected["latestValue"] is None
        assert selected["status"] in {"stale", "unavailable"}
        backdrop = scanner._regime_rates_backdrop(rates, selected)
        assert backdrop["hyOas"] == 0.0
        assert backdrop["posture"] != "stress"

    usable = scanner._select_rate_truth(
        "hyOas", [_rate_row(
            "fred", 8.0, "2026-08-13", status="live")], decision)
    assert usable["latestValue"] == 8.0
    assert usable["freshness"] == "DELAYED"
    assert scanner._regime_rates_backdrop(
        rates, usable)["posture"] == "stress"


def test_entry_history_requires_exact_recent_trading_session_for_jp_and_us(
        monkeypatch):
    now = scanner.datetime(2026, 8, 16, 12, tzinfo=scanner.pytz.utc).timestamp()
    monkeypatch.setattr(scanner.time, "time", lambda: now)
    current = {"dates": ["2026-08-14"]}
    assert scanner._entry_history_source_usable(
        current, "JP", now_epoch=now)[0] is True
    assert scanner._entry_history_source_usable(
        current, "US", now_epoch=now)[0] is True
    for hostile in (None, "2025-01-25", "2026-08-17",
                    "2026-08-16junk", "2026-08-15"):
        history = {"dates": [] if hostile is None else [hostile]}
        assert scanner._entry_history_source_usable(
            history, "JP", now_epoch=now)[0] is False
        assert scanner._entry_history_source_usable(
            history, "US", now_epoch=now)[0] is False

    stale = {
        "dates": ["2025-01-24"] * 25,
        "closes": [100.0] * 25, "volumes": [1000] * 25,
        "highs": [101.0] * 25, "lows": [99.0] * 25,
    }
    monkeypatch.setattr(scanner, "_SCOUT_CACHE", {})
    monkeypatch.setattr(scanner, "_jq_price_history", lambda _sym: stale)
    monkeypatch.setattr(scanner, "_td_price_history", lambda _sym: stale)
    for market, symbol in (("JP", "7203"), ("US", "AAPL")):
        result = scanner.get_entry_scout(symbol, market)
        assert result["status"] == "unavailable"
        assert result["sourceTimeReason"] == "stale_latest_session_date"
        assert "assessment" not in result


def test_pushed_quote_decision_authority_rejects_missing_future_and_stale():
    now = 1_800_000_000.0
    for source_timestamp in (None, now + 1, now - 3600):
        pushed = {"ts": now, "row": {
            "symbol": "AAPL", "changePct": 5.0,
            "exchangeTs": source_timestamp,
            "entitlement": "realtime", "realtimeEvidence": True,
        }}
        assert scanner._pushed_quote_decision_row(
            pushed, now_epoch=now) is None
    fresh = {"ts": now, "row": {
        "symbol": "AAPL", "changePct": 5.0,
        "exchangeTs": now - 30, "entitlement": "realtime",
        "status": "live", "realtimeEvidence": True,
    }}
    assert scanner._pushed_quote_decision_row(
        fresh, now_epoch=now)["realtimeEvidence"] is True


def test_action_labels_never_borrow_quote_time_for_flow_authority(monkeypatch):
    monkeypatch.setattr(scanner, "get_rates_snapshot", lambda: {
        "status": "live", "ratesPressure": "Neutral"})
    monkeypatch.setattr(scanner, "get_japan_watchlist_snapshot", lambda *_a: {
        "status": "live", "stocks": []})
    monkeypatch.setattr(scanner, "get_events_snapshot", lambda **_k: {
        "status": "live", "events": []})
    monkeypatch.setattr(scanner, "get_market_regime_snapshot", lambda: {
        "status": "partial", "regime": {"label": "CAUTIOUS"}})
    monkeypatch.setattr(scanner, "_ledger_summary", lambda: None)
    monkeypatch.setattr(scanner, "_visibility_guard", lambda: {})
    monkeypatch.setattr(scanner, "_events_active_list", lambda: [])
    monkeypatch.setattr(
        scanner, "_learning_memory_compact_for_symbol", lambda *_a: None)

    def label(source_timestamp, ratio):
        row = {
            "symbol": "AAPL", "name": "Apple", "price": 100.0,
            "changePct": -3.0, "volume": 1000, "date": "2026-08-16",
            "status": "delayed", "source": "moomoo-rt",
            "sourceTimestamp": source_timestamp,
            "realtimeEvidence": False,
            "flow": {"bigNetRatio": ratio},
        }
        monkeypatch.setattr(scanner, "get_us_watchlist_snapshot", lambda *_a: {
            "status": "delayed", "stocks": [row]})
        return scanner.get_action_labels(
            jp_symbols=[], us_symbols=["AAPL"])["labels"][0]

    baseline = label(None, None)
    for source_timestamp, ratio in (
            (None, 0.25), (1_800_000_001.0, 0.25),
            (1_799_996_400.0, -0.30)):
        hostile = label(source_timestamp, ratio)
        assert hostile["action"] == baseline["action"] == "HOLD"
        assert hostile["confidence"] == baseline["confidence"]
        assert hostile["supportingData"]["bigFlowRatio"] is None
        assert "大口" not in hostile["reasonJa"]


def test_market_confirmation_rejects_source_invalid_benchmark_peers_and_volume(
        monkeypatch):
    rows = {
        "SPY": {"symbol": "SPY", "changePct": -0.2,
                "volume": 1000, "realtimeEvidence": False},
        "NVDA": {"symbol": "NVDA", "changePct": -6.0,
                 "volume": 1000, "realtimeEvidence": False},
        "AAPL": {"symbol": "AAPL", "changePct": -5.0,
                 "volume": 1000, "realtimeEvidence": False},
    }
    monkeypatch.setattr(
        scanner, "_quote_cached_only",
        lambda symbol, _market: rows.get(symbol))
    inputs = scanner._market_confirmation_inputs("NVDA", "US", -6.0)
    assert "indexMovePct" not in inputs
    assert inputs.get("peerMoves") == []
    assert "todayVolume" not in inputs


def test_vix_current_level_and_velocity_require_canonical_source_truth(
        monkeypatch):
    now = 1_800_000_000.0
    observed = _epoch_iso(now - 30)
    fresh_yahoo = {
        "latestValue": 15.0, "selectedProvider": "yahoo",
        "freshness": "FRESH", "completeness": "COMPLETE",
        "observedAt": observed,
    }
    assessed = scanner._canonical_vix_assess(
        [35.0, 20.0] + [18.0] * 68, fresh_yahoo, now_epoch=now)
    assert assessed["level"] == 15.0
    assert assessed["zone"] != "shock"
    assert assessed["spike"] is False

    for hostile in (
            {**fresh_yahoo, "observedAt": None},
            {**fresh_yahoo, "observedAt": _epoch_iso(now + 1)},
            {**fresh_yahoo, "observedAt": _epoch_iso(now - 3600)},
            {**fresh_yahoo, "freshness": "STALE"}):
        assert scanner._canonical_vix_assess(
            [35.0, 20.0], hostile, now_epoch=now) is None

    monkeypatch.setattr(scanner.time, "time", lambda: now)
    monkeypatch.setattr(scanner, "_FRED_API_KEY", "key")
    monkeypatch.setattr(scanner, "_VIX_HIST_CACHE", {
        "data": [35.0, 20.0] + [18.0] * 68,
        "sourceTimestamp": "2020-01-02", "expires": now + 3600,
    })
    assert scanner._fred_vix_history() == []


def test_jquants_daily_date_is_never_realtime_source_proof(monkeypatch):
    today = scanner.datetime.now(scanner.TZ_JST).strftime("%Y-%m-%d")

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"data": [
                {"Date": "2026-01-01", "C": 99.0, "O": 98.0,
                 "H": 100.0, "L": 97.0, "Vo": 100},
                {"Date": today, "C": 100.0, "O": 99.0,
                 "H": 101.0, "L": 98.0, "Vo": 200},
            ]}

    monkeypatch.setattr(scanner.requests, "get", lambda *_a, **_k: Response())
    row = scanner._jq_fetch_bar_row("7203", "Toyota", {})
    assert row["status"] == "delayed"
    assert row["sourceTimestamp"] == today
    assert row["delayClass"] == "EOD"
    assert row["realtimeEvidence"] is False


def test_cached_provider_status_is_reaged_and_cannot_remain_live(monkeypatch):
    now = 1_800_000_000.0
    monkeypatch.setattr(scanner.time, "time", lambda: now)
    cached = {
        "status": "live", "provider": "twelvedata",
        "stocks": [{"symbol": "AAPL", "status": "live",
                    "sourceTimestamp": _epoch_iso(now - 3600)}],
    }
    reaged = scanner._canonical_quote_snapshot_age(cached, "stocks")
    assert cached["status"] == "live"  # cache provenance is not rewritten
    assert reaged["status"] == "delayed"
    assert reaged["stocks"][0]["status"] == "delayed"
    assert reaged["stocks"][0]["ageSec"] == 3600


def test_cached_only_dynamic_quotes_reage_missing_future_and_stale_rows(
        monkeypatch):
    now = 1_800_000_000.0
    monkeypatch.setattr(scanner.time, "time", lambda: now)
    monkeypatch.setattr(scanner, "_PUSHED_QUOTES", {"JP": {}, "US": {}})
    monkeypatch.setattr(scanner, "_US_CACHE", {
        "data": None, "expires": 0.0})
    rows = [
        {"symbol": "AAPL", "status": "live", "sourceTimestamp": None},
        {"symbol": "MSFT", "status": "live",
         "sourceTimestamp": _epoch_iso(now + 1)},
        {"symbol": "NVDA", "status": "live",
         "sourceTimestamp": _epoch_iso(now - 3600)},
        {"symbol": "SPY", "status": "live",
         "sourceTimestamp": _epoch_iso(now - 60)},
    ]
    dynamic = {
        ("AAPL", "MSFT", "NVDA", "SPY"): {
            "data": {"status": "live", "stocks": rows},
            "expires": now + 600,
        },
    }
    monkeypatch.setattr(scanner, "_US_DYN_CACHE", dynamic)

    cached = {row["symbol"]: scanner._quote_cached_only(
        row["symbol"], "US") for row in rows}
    assert cached["AAPL"]["status"] == "delayed"
    assert cached["AAPL"]["sourceTimeStatus"] == "MISSING"
    assert cached["MSFT"]["status"] == "delayed"
    assert cached["MSFT"]["timestampInversion"] is True
    assert cached["NVDA"]["status"] == "delayed"
    assert cached["NVDA"]["ageSec"] == 3600
    assert cached["SPY"]["status"] == "live"
    assert cached["SPY"]["realtimeEvidence"] is True
    assert all(row["status"] == "live" for row in rows)


def test_cached_only_curated_quotes_reage_missing_future_and_stale_rows(
        monkeypatch):
    now = 1_800_000_000.0
    monkeypatch.setattr(scanner.time, "time", lambda: now)
    monkeypatch.setattr(scanner, "_PUSHED_QUOTES", {"JP": {}, "US": {}})
    monkeypatch.setattr(scanner, "_US_DYN_CACHE", {})
    rows = [
        {"symbol": "AAPL", "status": "live", "sourceTimestamp": None},
        {"symbol": "MSFT", "status": "live",
         "sourceTimestamp": _epoch_iso(now + 1)},
        {"symbol": "NVDA", "status": "live",
         "sourceTimestamp": _epoch_iso(now - 3600)},
        {"symbol": "SPY", "status": "live",
         "sourceTimestamp": _epoch_iso(now - 60)},
    ]
    monkeypatch.setattr(scanner, "_US_CACHE", {
        "data": {"status": "live", "stocks": rows},
        "expires": now + 600,
    })

    cached = {row["symbol"]: scanner._quote_cached_only(
        row["symbol"], "US") for row in rows}
    assert cached["AAPL"]["status"] == "delayed"
    assert cached["AAPL"]["sourceTimeStatus"] == "MISSING"
    assert cached["MSFT"]["status"] == "delayed"
    assert cached["MSFT"]["timestampInversion"] is True
    assert cached["NVDA"]["status"] == "delayed"
    assert cached["NVDA"]["ageSec"] == 3600
    assert cached["SPY"]["status"] == "live"
    assert cached["SPY"]["realtimeEvidence"] is True
    assert all(row["status"] == "live" for row in rows)


def test_twelve_data_finnhub_coingecko_and_coinbase_use_source_age(
        monkeypatch):
    now = 1_800_000_000.0
    monkeypatch.setattr(scanner.time, "time", lambda: now)
    fresh_iso = _epoch_iso(now - 60)
    old_iso = _epoch_iso(now - 3600)
    future_iso = _epoch_iso(now + 1)
    meta = {"symbol": "AAPL", "name": "Apple"}
    quote = {"close": "100", "change": "1", "percent_change": "1"}
    assert scanner._td_parse_row(
        meta, {**quote, "datetime": fresh_iso})["status"] == "live"
    assert scanner._td_parse_row(
        meta, {**quote, "datetime": old_iso})["status"] == "delayed"
    td_future = scanner._td_parse_row(
        meta, {**quote, "datetime": future_iso})
    assert td_future["status"] == "delayed"
    assert td_future["timestampInversion"] is True

    class FinnhubResponse:
        ok = True

        def json(self):
            return {"c": 100.0, "d": 1.0, "dp": 1.0}

    monkeypatch.setattr(scanner, "FINNHUB_API_KEY", "fixture")
    scanner._FINNHUB_QUOTE_CACHE.clear()
    monkeypatch.setattr(scanner.requests, "get",
                        lambda *_args, **_kwargs: FinnhubResponse())
    finnhub = scanner._finnhub_quote_row("AAPL")
    assert finnhub["status"] == "delayed"
    assert finnhub["sourceTimestamp"] is None
    assert finnhub["realtimeEvidence"] is False

    class CryptoResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {"bitcoin": {
                "usd": 100.0, "usd_24h_change": 1.0,
                "usd_24h_vol": 1000.0,
                "last_updated_at": int(now - 3600),
            }}

    scanner._CRYPTO_CACHE.clear()
    monkeypatch.setattr(scanner.requests, "get",
                        lambda *_args, **_kwargs: CryptoResponse())
    coingecko = scanner.get_crypto_watchlist_snapshot(["bitcoin"])
    assert coingecko["status"] == "delayed"
    assert coingecko["quotes"][0]["status"] == "delayed"
    assert coingecko["quotes"][0]["ageSec"] == 3600

    class CoinbaseResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {"last": "100", "open": "99", "volume": "10"}

    monkeypatch.setattr(scanner.requests, "get",
                        lambda *_args, **_kwargs: CoinbaseResponse())
    coinbase = scanner._crypto_coinbase_fallback(["bitcoin"])[0]
    assert coinbase["status"] == "delayed"
    assert coinbase["sourceTimestamp"] is None
    assert coinbase["ageSec"] is None


def test_scanner_projection_binds_truth_distribution_mode_and_session():
    projection = _projection()

    assert projection["status"] == "COMPLETE"
    assert projection["mode"] == "forward_live"
    assert projection["authority"] == "PREDICTION_EVIDENCE_ONLY"
    assert projection["finalDecisionAuthorityActive"] is False
    assert argus_market_data_truth.verify_decision_snapshot(
        projection["marketTruthSnapshot"])[0]
    assert projection["marketTruthSnapshot"]["buildIdentity"] == BUILD_SHA
    assert len(projection["issuedDecisions"]) == 3
    assert projection["candidateCount"] == 3
    assert projection["issuedCount"] == 3
    assert projection["omittedCandidateCount"] == 0
    assert projection["truthQualityComplete"] is True
    for issued in projection["issuedDecisions"]:
        assert argus_decision_ledger.verify_prediction_record_v2(issued)
        assert issued["mode"] == "forward_live"
        # v13.6.0: every issued decision records the canonical SDA action
        # (server-side owner context is UNKNOWN → sealed data-gated WAIT), so
        # WAIT opportunity scoring can resolve (owner spec §19-21).
        assert issued["candidateAction"] == "WAIT"
        assert issued["engine"]["buildSha"] == BUILD_SHA
        assert issued["forecastDistribution"]["classLabels"] == list(
            scanner.argus_calibration.CLASSES)
        # The selected canonical quote change (+1%) produces 30/50/20; the
        # contradictory legacy scenarios (20/50/30) are not an input.
        assert issued["forecastDistribution"]["probabilities"] == [
            0.3, 0.5, 0.2]
        assert issued["maturity"]["targetSessionId"].startswith(
            "JPX_TSE:cal-2026.2:")
        assert issued["targetLadder"][0]["comparator"] == "<"
        assert issued["targetLadder"][1]["comparator"] == ">"
        assert [row["targetId"] for row in issued["targetLadder"]] == [
            "scenario.downside_boundary", "scenario.rebound_boundary"]
        assert [row["value"] for row in issued["targetLadder"]] == [-2.0, 2.0]
        assert all(row["unit"] == "%" for row in issued["targetLadder"])
        assert len(issued["evaluationPolicy"]["parametersHash"]) == 64
    assert {row["forecastHorizon"] for row in
            projection["issuedDecisions"]} == {"1d", "3d", "5d"}
    assert projection["outcomeTruthObservations"]
    assert projection["outcomeTruthObservations"][0]["factType"] == "OHLCV_BAR"


def test_future_quote_timestamp_is_excluded_not_rounded_to_fresh():
    future = _jquants_row(
        sourceTimestamp="2026-08-14T07:00:00Z", date="2026-08-14")
    projection = _projection(
        quote_rows=[("JP", "jquants", future)])
    assert projection["status"] == "INCOMPLETE"
    assert projection["issuedDecisions"] == []


def test_provider_candidates_and_disagreement_survive_scanner_adapter():
    row = _jquants_row(
        selectionPolicyId="jp-moomoo-jquants-v1",
        providerCandidates=[
            {"value": 2810.0, "source": "moomoo-rt",
             "sourceTimestamp": "2026-08-14T06:39:00Z",
             "receivedAt": DECISION_AT, "status": "live", "selected": True},
            {"value": 2800.0, "source": "jquants",
             "sourceTimestamp": "2026-08-14", "receivedAt": DECISION_AT,
             "status": "delayed", "selected": False},
        ])
    projection = _projection(
        quote_rows=[("JP", "moomoo-bridge", row)])
    selection = projection["marketTruthSnapshot"]["selections"][0]
    assert selection["selected"]["observation"]["source"][
        "providerKey"] == "moomoo"
    assert selection["alternates"][0]["observation"]["source"][
        "providerKey"] == "jquants"
    assert selection["disagreement"]["status"] == "PRESENT"
    assert all(item["dissent"] == ["provider_disagreement:PRESENT"]
               for item in projection["issuedDecisions"])


def test_official_close_is_explicit_delayed_and_runner_eligible_at_1605_jst():
    decision_at = "2026-08-14T07:05:00Z"  # 16:05 JST, 35m after close
    projection = _projection(
        quote_rows=[("JP", "jquants", _jquants_row(
            # Cached just after close; freshness must still be evaluated at the
            # later decision cutoff rather than frozen at receipt.
            receivedAt="2026-08-14T06:31:00Z"))],
        decision_at=decision_at, generated_at="2026-08-14T07:05:01Z")

    assert projection["status"] == "COMPLETE"
    assert projection["truthQualityComplete"] is True
    selection = projection["marketTruthSnapshot"]["selections"][0]
    assert selection["freshness"] == argus_market_data_truth.DELAYED
    assert selection["completeness"] == argus_market_data_truth.COMPLETE
    assert len(projection["issuedDecisions"]) == 3
    assert all(row["missingEvidence"] == []
               for row in projection["issuedDecisions"])
    context = run_prediction_ledger._validate_input(
        {"asOf": decision_at, "generatedAt": "2026-08-14T07:05:01Z",
         "canonicalPredictionLedger": projection},
        expected_mode="forward_live", runner_build_sha="b" * 40)
    assert len(context["decisions"]) == 3


def test_stale_quote_is_never_admitted_to_canonical_predictions():
    decision_at = "2026-08-16T19:00:00Z"
    projection = _projection(
        quote_rows=[("JP", "jquants", _jquants_row(
            receivedAt=decision_at))],
        decision_at=decision_at, generated_at="2026-08-16T19:00:01Z")
    assert projection["status"] == "INCOMPLETE"
    assert projection["truthQualityComplete"] is False
    assert projection["issuedDecisions"] == []


def test_mock_provider_alternate_never_enters_truth_or_dissent():
    row = _jquants_row(
        source="moomoo-rt",
        sourceTimestamp="2026-08-14T06:39:00Z",
        providerCandidates=[
            {"value": 2810.0, "source": "moomoo-rt",
             "sourceTimestamp": "2026-08-14T06:39:00Z",
             "receivedAt": DECISION_AT, "status": "live", "selected": True},
            # Display-only fallback: no independent source timestamp or receipt.
            {"value": 9999.0, "source": "jquants", "status": "mock",
             "selected": False},
        ])
    projection = _projection(
        quote_rows=[("JP", "moomoo-bridge", row)])
    selection = projection["marketTruthSnapshot"]["selections"][0]
    assert projection["status"] == "COMPLETE"
    assert selection["alternates"] == []
    assert selection["candidateCount"] == 1
    assert selection["disagreement"]["status"] == "NONE"
    assert all(item["dissent"] == []
               for item in projection["issuedDecisions"])


def test_unavailable_or_unclassified_alternate_cannot_borrow_parent_truth():
    row = _jquants_row(
        source="moomoo-rt", sourceTimestamp="2026-08-14T06:39:00Z",
        providerCandidates=[
            {"value": 2810.0, "source": "moomoo-rt",
             "sourceTimestamp": "2026-08-14T06:39:00Z",
             "receivedAt": DECISION_AT, "status": "live", "selected": True},
            {"value": 2800.0, "source": "jquants",
             "sourceTimestamp": "2026-08-14", "receivedAt": DECISION_AT,
             "status": "unavailable", "selected": False},
            {"value": 2790.0, "source": "twelvedata",
             "sourceTimestamp": "2026-08-14T06:38:00Z",
             "receivedAt": DECISION_AT, "selected": False},
            # A nominally-live alternate cannot borrow the parent row's source
            # timestamp, receipt instant, or provider identity.
            {"value": 2780.0, "source": "finnhub", "status": "live",
             "selected": False},
            {"value": 2770.0, "sourceTimestamp": "2026-08-14T06:37:00Z",
             "receivedAt": DECISION_AT, "status": "live", "selected": False},
        ])
    projection = _projection(quote_rows=[("JP", "moomoo-bridge", row)])
    selection = projection["marketTruthSnapshot"]["selections"][0]
    assert projection["status"] == "COMPLETE"
    assert selection["candidateCount"] == 1
    assert selection["alternates"] == []
    assert selection["disagreement"]["status"] == "NONE"


def test_legacy_action_cannot_change_canonical_prediction_identity():
    wait = _legacy_prediction()
    wait["action"] = "WAIT"
    buy = _legacy_prediction()
    buy["action"] = "BUY"
    left = _projection(legacy_rows=[("tactical_rule", wait)])
    right = _projection(legacy_rows=[("tactical_rule", buy)])

    assert left["status"] == right["status"] == "COMPLETE"
    # The sealed forecast identity stays independent of LEGACY action labels —
    # a legacy WAIT row and a legacy BUY row produce byte-identical records.
    # The recorded candidateAction comes from the canonical SDA (data-gated →
    # WAIT), never from the legacy emitters (v13.6.0, owner spec §17/§19).
    assert [row["id"] for row in left["issuedDecisions"]] == [
        row["id"] for row in right["issuedDecisions"]]
    assert [row["integrityHash"] for row in left["issuedDecisions"]] == [
        row["integrityHash"] for row in right["issuedDecisions"]]
    assert all(row["candidateAction"] == "WAIT"
               for row in left["issuedDecisions"] + right["issuedDecisions"])


def test_cached_history_keeps_actual_cache_knowledge_time_and_partial_ohlc():
    previous = copy.deepcopy(scanner._JQ_HISTORY_CACHE)
    try:
        acquired = 1_776_000_000.0
        scanner._JQ_HISTORY_CACHE.clear()
        scanner._JQ_HISTORY_CACHE["7203"] = {
            "expires": acquired + scanner._JQ_HISTORY_TTL,
            "data": {
                "dates": ["2026-04-12"], "opens": [100.0],
                "highs": [None], "lows": [98.0], "closes": [101.0],
                "volumes": [1000],
            },
        }
        rows = scanner._canonical_history_observations(
            [("JP", "7203")], DECISION_AT)
        assert len(rows) == 1
        assert rows[0]["completeness"] == "PARTIAL"
        assert rows[0]["missingFields"] == ["high"]
        assert rows[0]["knownAt"] != DECISION_AT
    finally:
        scanner._JQ_HISTORY_CACHE.clear()
        scanner._JQ_HISTORY_CACHE.update(previous)


def test_chart_cache_import_is_bound_to_acquisition_not_backdated_bar_date():
    previous = copy.deepcopy(scanner._JQ_HISTORY_CACHE)
    try:
        acquired = scanner.time.time() - 10.0
        scanner._JQ_HISTORY_CACHE.clear()
        scanner._JQ_HISTORY_CACHE["7203"] = {
            "expires": acquired + scanner._JQ_HISTORY_TTL,
            "data": {
                "dates": ["2026-04-12"], "opens": [100.0],
                "highs": [102.0], "lows": [98.0], "closes": [101.0],
                "volumes": [1000], "adjusted": [True],
            },
        }
        rows = scanner._chart_history_cached("7203", "JP")
        assert len(rows) == 1
        expected_known = scanner._canonical_truth_iso(acquired, "JP")
        assert rows[0]["knownAt"] == expected_known
        assert rows[0]["knownAt"] != rows[0]["date"]
        assert rows[0]["datasetId"].startswith("jquants:7203:")
        before = scanner._canonical_truth_iso(acquired - 1, "JP")
        after = scanner._canonical_truth_iso(acquired + 1, "JP")
        assert argus_market_data_truth.point_in_time_rows(rows, before)[0] == []
        admitted, proof = argus_market_data_truth.point_in_time_rows(rows, after)
        assert len(admitted) == 1
        assert argus_market_data_truth.verify_point_in_time_proof(proof)[0]
    finally:
        scanner._JQ_HISTORY_CACHE.clear()
        scanner._JQ_HISTORY_CACHE.update(previous)


def test_optional_projection_failure_has_no_legacy_route_side_effect():
    with mock.patch.object(
            scanner.argus_market_data_truth, "build_decision_snapshot",
            side_effect=ValueError("fixture")):
        projection = _projection()
    assert projection["status"] == "INCOMPLETE"
    assert projection["issuedDecisions"] == []


def test_missing_exact_build_identity_issues_no_forward_live_record():
    with mock.patch.object(scanner, "_backend_exact_sha", return_value=None):
        projection = scanner._canonical_prediction_ledger_projection(
            legacy_rows=[("tactical_rule", _legacy_prediction())],
            quote_rows=[("JP", "jquants", _jquants_row())],
            decision_at=DECISION_AT, generated_at=GENERATED_AT,
            engine_version="fixture-v1")
    assert projection["status"] == "INCOMPLETE"
    assert projection["reason"] == "build_identity_unavailable"
    assert projection["marketTruthSnapshot"] is None
    assert projection["issuedDecisions"] == []


def test_snapshot_request_overflow_is_bounded_visible_and_incomplete():
    legacy_rows = []
    quote_rows = []
    for index in range(argus_market_data_truth.MAX_SNAPSHOT_REQUESTS + 1):
        symbol = str(1000 + index)
        legacy_rows.append(("tactical_rule", {
            **_legacy_prediction(), "symbol": symbol, "price": 100.0,
        }))
        quote_rows.append(("JP", "jquants", _jquants_row(
            symbol=symbol, price=100.0, close=100.0, open=99.0,
            high=101.0, low=98.0)))
    projection = _projection(legacy_rows=legacy_rows, quote_rows=quote_rows)
    assert projection["status"] == "INCOMPLETE"
    assert projection["marketTruthSnapshotVerified"] is True
    assert len(projection["marketTruthSnapshot"]["selections"]) == \
        argus_market_data_truth.MAX_SNAPSHOT_REQUESTS
    assert projection["sourceCandidateCount"] == 65
    assert projection["candidateCount"] == 195
    assert projection["issuedCount"] == 192
    assert projection["omittedCandidateCount"] == 1
    assert len(projection["omittedCandidateIds"]) == 1
    assert projection["omittedCandidateIdsTruncated"] is False


def test_duplicate_source_candidates_are_deterministically_bounded():
    legacy_rows = [("tactical_rule", _legacy_prediction())
                   for _ in range(100)]
    projection = _projection(legacy_rows=legacy_rows)
    assert projection["status"] == "INCOMPLETE"
    assert projection["sourceCandidateCount"] == 100
    assert projection["candidateCount"] == 300
    assert projection["issuedCount"] == 192
    assert len(projection["issuedDecisions"]) == 192
    assert projection["omittedCandidateCount"] == 36
    assert len(projection["omittedCandidateIds"]) == 36
