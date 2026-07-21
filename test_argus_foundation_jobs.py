import copy
import json
import sys
import types

import pytest

import argus_foundation_jobs as jobs
import argus_market_ledger as ledger
import argus_sho_phase3 as sho


def _master(code, market, name="会社"):
    return {"Code": code, "MktNm": market, "CoName": name}


def _bar(code, date, adjusted, raw=None):
    return {"Code": code, "Date": date, "AdjC": adjusted, "C": raw}


def test_historical_universe_and_adjusted_advance_decline_contract():
    master = [
        _master("11110", "プライム"),
        _master("22220", "スタンダード"),
        _master("33330", "グロース"),
        _master("13060", "ETF・ETN", "ETF"),
        _master("99990", "プライム", "外国株式"),
    ]
    previous = {"11110": 100, "22220": 100, "33330": 100,
                "13060": 100, "99990": 100, "44440": 100}
    bars = [
        _bar("11110", "2026-07-17", 110, raw=110),
        # Raw price resembles a split, adjusted close correctly says unchanged.
        _bar("22220", "2026-07-17", 100, raw=50),
        _bar("33330", "2026-07-17", 90, raw=90),
        _bar("13060", "2026-07-17", 120, raw=120),
        _bar("99990", "2026-07-17", 120, raw=120),
    ]
    result = jobs.calculate_daily(
        date="2026-07-17", master_rows=master, bar_rows=bars,
        previous_adjusted_closes=previous)
    prime = result["universes"]["tse_prime_domestic_common"]
    all_market = result["universes"]["tse_all_domestic_common"]
    assert prime["issueCount"] == 1
    assert prime["counts"] == {"advancers": 1, "decliners": 0,
                               "unchanged": 0, "unavailable": 0}
    assert all_market["issueCount"] == 3
    assert all_market["counts"] == {"advancers": 1, "decliners": 1,
                                    "unchanged": 1, "unavailable": 0}
    # Delisted/non-member 44440 is not counted despite a prior close.
    assert "44440" not in all_market["sourceObservationIds"]


def test_missing_adjusted_price_is_unavailable_not_zero():
    result = jobs.calculate_daily(
        date="2026-07-17", master_rows=[_master("11110", "Prime")],
        bar_rows=[_bar("11110", "2026-07-17", None, raw=0)],
        previous_adjusted_closes={"11110": 100})
    prime = result["universes"]["tse_prime_domestic_common"]
    assert prime["counts"]["unavailable"] == 1
    assert prime["counts"]["decliners"] == 0
    candidates = jobs.ledger_candidates(result, calculated_at="2026-07-17T08:05:00Z")
    assert all(row["value"] >= 0 for row in candidates)
    assert all("previousAdjustedCloses" not in json.dumps(row) for row in candidates)


def test_missing_session_close_keeps_prior_comparable_close_while_listed():
    master = [_master("11110", "Prime")]
    missing = jobs.calculate_daily(
        date="2026-07-16", master_rows=master, bar_rows=[],
        previous_adjusted_closes={"11110": 100})
    assert missing["universes"]["tse_prime_domestic_common"]["counts"][
        "unavailable"] == 1
    assert missing["nextAdjustedCloses"]["11110"] == 100
    following = jobs.calculate_daily(
        date="2026-07-17", master_rows=master,
        bar_rows=[_bar("11110", "2026-07-17", 110)],
        previous_adjusted_closes=missing["nextAdjustedCloses"])
    counts = following["universes"]["tse_prime_domestic_common"]["counts"]
    assert counts["unavailable"] == 0
    assert counts["advancers"] == 1


def test_prior_close_is_dropped_when_issue_leaves_historical_master():
    missing = jobs.calculate_daily(
        date="2026-07-16", master_rows=[], bar_rows=[],
        previous_adjusted_closes={"11110": 100})
    assert "11110" not in missing["nextAdjustedCloses"]


def test_ratios_and_zero_denominator_are_deterministic():
    daily = [{"asOfDate": f"2026-07-{day:02d}", "advancers": day,
              "decliners": 2, "observationId": str(day), "complete": True}
             for day in range(1, 7)]
    row = jobs.ratio_rows(daily, 6)[0]
    assert row["advancerSum"] == 21 and row["declinerSum"] == 12
    assert row["ratio"] == 175.0
    for item in daily:
        item["decliners"] = 0
    assert jobs.ratio_rows(daily, 6)[0]["ratio"] is None


def test_market_ledger_two_universes_and_legacy_restore():
    state = ledger.empty_state()
    rows = []
    for index in range(25):
        date = f"2026-06-{index + 1:02d}"
        for universe in ("prime", "all"):
            for name, value in (("advancers", 100 + index), ("decliners", 50),
                                ("unchanged", 10), ("unavailable", 1)):
                rows.append({"seriesId": f"breadth.{universe}.{name}",
                             "periodEnd": date,
                             "availableFrom": f"{date}T17:00:00+09:00",
                             "value": value, "unit": "count", "source": "J-Quants",
                             "sourceKind": "derived"})
    imported = ledger.import_rows(state, rows, now_iso="2026-07-20T00:00:00Z",
                                  dry_run=False)
    assert imported["ok"]
    history = ledger.derived_history(imported["state"], "2026-07-20T00:00:00Z")
    assert history["breadth.prime.ratio25"][-1]["value"] > 120
    assert history["breadth.all.ratio6"][-1]["classification"] == "sho_heuristic"
    legacy = ledger.normalize_state({"schemaVersion": "argus-market-ledger-v1",
                                     "observations": []})
    assert legacy["schemaVersion"] == "argus-market-ledger-v1"
    assert legacy["backtests"] == []


def test_job_lifecycle_idempotency_cancel_and_checkpoint_restore():
    state = jobs.empty_state()
    first = jobs.start_job(state, job_type="JQUANTS_BREADTH_BACKFILL",
                           now_iso="2026-07-20T00:00:00Z",
                           parameters={"from": "2008-05-07"})
    duplicate = jobs.start_job(first["state"],
                               job_type="JQUANTS_BREADTH_BACKFILL",
                               now_iso="2026-07-20T00:00:01Z",
                               parameters={"from": "2008-05-07"})
    assert not duplicate["created"]
    running = jobs.update_job(first["state"], first["job"]["jobId"],
                              now_iso="2026-07-20T00:01:00Z", status="running",
                              checkpoint={"lastCommittedDate": "2020-01-06"})
    restored = jobs.normalize_state(copy.deepcopy(running))
    assert restored["jobs"][-1]["checkpoint"]["lastCommittedDate"] == "2020-01-06"
    cancelled = jobs.request_cancel(restored, first["job"]["jobId"],
                                    now_iso="2026-07-20T00:02:00Z")
    assert cancelled["jobs"][-1]["cancelRequested"] is True


def test_pipeline_preflight_is_registered_without_consuming_benchmark_state():
    started = jobs.start_job(
        jobs.empty_state(), job_type="RESEARCH_PIPELINE_PREFLIGHT",
        now_iso="2026-07-20T00:00:00Z")
    assert started["created"] is True
    assert started["job"]["jobType"] == "RESEARCH_PIPELINE_PREFLIGHT"


def test_pipeline_preflight_exercises_stages_and_preserves_holdout(monkeypatch):
    import scanner
    import argus_cost_policy as cost_policy

    previous_jobs = copy.deepcopy(scanner._FOUNDATION_JOBS)
    previous_benchmark = copy.deepcopy(scanner._FORMAL_BENCHMARK)
    previous_cost = copy.deepcopy(scanner._COST_POLICY)
    state = jobs.empty_state()
    gemini = jobs.start_job(
        state, job_type="GEMINI_PREFLIGHT",
        now_iso="2026-07-20T00:00:00Z")
    state = jobs.update_job(
        gemini["state"], gemini["job"]["jobId"],
        now_iso="2026-07-20T00:00:01Z", status="completed",
        result={"status": "verified",
                "selectedBaselineModel": "gemini-3.1-pro-preview"})
    pipeline = jobs.start_job(
        state, job_type="RESEARCH_PIPELINE_PREFLIGHT",
        now_iso="2026-07-20T00:00:02Z")
    scanner._FOUNDATION_JOBS.clear()
    scanner._FOUNDATION_JOBS.update(pipeline["state"])
    scanner._FORMAL_BENCHMARK.clear()
    scanner._FORMAL_BENCHMARK.update({
        **previous_benchmark, "holdoutConsumedBy": None})
    scanner._COST_POLICY.clear()
    scanner._COST_POLICY.update(cost_policy.default_state())

    provider_meta = {"requestedModel": "requested",
                     "responseModel": "response",
                     "usage": {"inputTokens": 1, "outputTokens": 1}}

    def gemini_call(*args, diagnostic_context=None, **kwargs):
        if diagnostic_context is not None:
            diagnostic_context.update({"status": "ok", "errorClass": None})
        return {"claims": [], "_providerMeta": {
            "provider": "gemini", **provider_meta}}, "ok"

    def openai_call(*args, diagnostic_context=None, **kwargs):
        if diagnostic_context is not None:
            diagnostic_context.update({"status": "ok", "errorClass": None})
        return {"claims": [], "_providerMeta": {
            "provider": "openai", **provider_meta}}, "ok"

    def referee(*args, diagnostic_context=None, **kwargs):
        if diagnostic_context is not None:
            diagnostic_context.update({"status": "ok", "errorClass": None})
        return {"A": {}, "B": {}}, "ok", {"provider": "openai"}

    monkeypatch.setattr(scanner, "_gemini_osint", gemini_call)
    monkeypatch.setattr(scanner, "_gpt_osint", openai_call)
    monkeypatch.setattr(scanner, "_formal_blind_evaluate", referee)
    monkeypatch.setattr(scanner, "_osint_persist", lambda: None)
    try:
        scanner._research_pipeline_preflight_worker(pipeline["job"]["jobId"])
        final = scanner._foundation_job(pipeline["job"]["jobId"])
        assert final["status"] == "completed"
        assert final["result"]["status"] == "verified"
        assert set(final["result"]["stages"]) == {
            "geminiSearch", "openaiSearch", "referee"}
        assert scanner._FORMAL_BENCHMARK.get("holdoutConsumedBy") is None
        assert scanner._COST_POLICY["mode"] == "DETERMINISTIC"
    finally:
        scanner._FOUNDATION_JOBS.clear()
        scanner._FOUNDATION_JOBS.update(previous_jobs)
        scanner._FORMAL_BENCHMARK.clear()
        scanner._FORMAL_BENCHMARK.update(previous_benchmark)
        scanner._COST_POLICY.clear()
        scanner._COST_POLICY.update(previous_cost)


def test_bounded_backoff_honors_provider_and_has_deterministic_jitter():
    assert jobs.bounded_backoff_seconds(2, "12", "x") == 12
    assert jobs.bounded_backoff_seconds(2, seed="same") == \
        jobs.bounded_backoff_seconds(2, seed="same")
    assert jobs.bounded_backoff_seconds(20, seed="cap") < 61


def test_walk_forward_has_no_future_leakage_and_stays_heuristic():
    prices = [{"date": f"2026-06-{day:02d}", "close": 100 + day,
               "availableFrom": f"2026-06-{day:02d}T17:00:00+09:00"}
              for day in range(1, 25)]
    signals = [{"id": "s1", "effectiveFrom": "2026-06-01",
                "availableFrom": "2026-06-01T17:00:00+09:00",
                "detectedAt": "2026-06-01T17:00:00+09:00"}]
    result = sho.walk_forward_backtest(signals, prices)
    assert result["noFutureLeakage"] is True
    assert result["classification"] == "insufficient_data"


def test_exact_model_pricing_and_response_model_contract(monkeypatch):
    moomoo = types.ModuleType("moomoo")
    moomoo.OpenQuoteContext = lambda *a, **k: None
    moomoo.OpenSecTradeContext = lambda *a, **k: None
    moomoo.RET_OK = 0
    sys.modules.setdefault("moomoo", moomoo)
    import scanner
    assert scanner._AI_PRICING["gpt-5.6-sol"] == {"in": 5.0, "out": 30.0}
    assert scanner._AI_PRICING["gpt-5.6-terra"] == {"in": 2.5, "out": 15.0}
    assert scanner._AI_PRICING["gemini-3.1-pro-preview"] == {"in": 2.0, "out": 12.0}
    assert scanner._AI_PRICING["gemini-2.5-pro"] == {"in": 1.25, "out": 10.0}
    dry = scanner._formal_benchmark_dry_run_value()
    assert dry["models"] == {"gemini": "gemini-3.1-pro-preview",
                              "argus": "gpt-5.6-sol",
                              "evaluator": "gpt-5.6-terra"}
    assert dry["estimatedCostJpy"] <= 2000
    assert dry["effectiveBudgetJpy"] == 2000
    assert dry["outputTokensPerCall"] == 4096
    assert dry["pricingVersion"] == "official-2026-07-21-v2"


def test_secure_admin_job_route_does_not_start_from_public(monkeypatch):
    import scanner
    monkeypatch.setattr(scanner, "_ARGUS_ADMIN_TOKEN", "test-admin")
    client = scanner.app.test_client()
    assert client.post("/api/argus/admin/foundation-jobs",
                       json={"jobType": "JOURNAL_REVERIFY",
                             "confirm": True}).status_code == 401
    public = client.get("/api/argus/foundation-jobs")
    assert public.status_code == 200
    assert "JQUANTS_API_KEY" not in json.dumps(public.get_json())


def test_jquants_v2_auth_pagination_and_429_recovery(monkeypatch):
    import scanner

    class Response:
        def __init__(self, status, body, headers=None):
            self.status_code = status
            self._body = body
            self.headers = headers or {}

        def json(self):
            return self._body

    calls = []
    responses = [
        Response(429, {}, {"Retry-After": "0"}),
        Response(200, {"data": [{"Code": "11110"}],
                       "pagination_key": "next"}, {"x-request-id": "r1"}),
        Response(200, {"data": [{"Code": "22220"}]},
                 {"x-request-id": "r2"}),
    ]

    def fake_get(url, headers, params, timeout):
        calls.append({"url": url, "headers": headers, "params": dict(params),
                      "timeout": timeout})
        return responses.pop(0)

    monkeypatch.setattr(scanner, "_JQUANTS_API_KEY", "configured-test-value")
    monkeypatch.setattr(scanner.requests, "get", fake_get)
    monkeypatch.setattr(scanner.time, "sleep", lambda _: None)
    proof = {}
    rows = scanner._jquants_secure_rows(
        "/equities/master", {"date": "2026-07-17"}, proof=proof)
    assert [row["Code"] for row in rows] == ["11110", "22220"]
    assert all(call["headers"] == {"x-api-key": "configured-test-value"}
               for call in calls)
    assert calls[-1]["params"]["pagination_key"] == "next"
    assert all(call["params"]["date"] == "20260717" for call in calls)
    assert proof["apiVersion"] == "v2" and proof["httpStatus"] == 200
    assert proof["method"] == "GET" and proof["dateFormat"] == "YYYYMMDD"
    assert proof["query"]["date"] == "20260717"
    assert proof["paginationObserved"] is True
    assert len(proof["paginationTokenHashes"]) == 1
    assert proof["endpointSummary"]["/equities/master"]["errorClass"] is None
    assert "configured-test-value" not in json.dumps(proof)


def test_jquants_hyphenated_historical_date_is_normalized_at_transport():
    assert jobs.normalize_jquants_query({
        "code": "86970", "date": "2008-05-07"}) == {
            "code": "86970", "date": "20080507"}
    assert jobs.normalize_jquants_query({
        "code": "86970", "from": "2023-03-24", "to": "20230327"}) == {
            "code": "86970", "from": "20230324", "to": "20230327"}


def test_jquants_date_filtered_response_fails_closed_on_wrong_session():
    import scanner
    rows = [
        {"Date": "20260717", "Code": "72030", "AdjC": 100},
        {"Date": "2026-07-20", "Code": "72030", "AdjC": 101},
        {"date": "2026/07/17", "Code": "67580", "AdjC": 200},
        {"Code": "99840", "AdjC": 300},
    ]
    exact = scanner._jquants_exact_date_rows(rows, "2026-07-17")
    assert [row["Code"] for row in exact] == ["72030", "67580"]
    assert scanner._jquants_exact_date_rows(rows, "2026-07-21") == []


def test_breadth_spot_match_requires_effective_official_counts():
    import scanner
    daily = jobs.calculate_daily(
        date="2026-07-21",
        master_rows=[_master("11110", "Prime")],
        bar_rows=[_bar("11110", "2026-07-21", 110)],
        previous_adjusted_closes={"11110": 100})
    effective = {
        "breadth.prime.advancers": [{"periodEnd": "2026-07-21", "value": 1}],
        "breadth.prime.decliners": [{"periodEnd": "2026-07-21", "value": 0}],
        "breadth.prime.unchanged": [{"periodEnd": "2026-07-21", "value": 0}],
        "breadth.prime.unavailable": [{"periodEnd": "2026-07-21", "value": 0}],
        "breadth.all.advancers": [{"periodEnd": "2026-07-21", "value": 1}],
        "breadth.all.decliners": [{"periodEnd": "2026-07-21", "value": 0}],
        "breadth.all.unchanged": [{"periodEnd": "2026-07-21", "value": 0}],
        "breadth.all.unavailable": [{"periodEnd": "2026-07-21", "value": 0}],
    }
    assert scanner._breadth_daily_matches(effective, daily) is True
    effective["breadth.all.advancers"][0]["value"] = 0
    assert scanner._breadth_daily_matches(effective, daily) is False


def test_jquants_error_metadata_is_safe_and_entitlement_is_explicit(monkeypatch):
    import scanner

    class Response:
        status_code = 400
        headers = {"content-type": "application/json; charset=utf-8",
                   "x-request-id": "request-safe"}

        @staticmethod
        def json():
            return {"code": "INVALID_PARAMETER", "message": "date format invalid"}

    monkeypatch.setattr(scanner, "_JQUANTS_API_KEY", "never-log-this")
    monkeypatch.setattr(scanner.requests, "get", lambda *a, **k: Response())
    proof = {}
    with pytest.raises(RuntimeError, match="jquants_http_400"):
        scanner._jquants_secure_page(
            "/equities/bars/daily", {"date": "2008-05-07"}, proof=proof)
    assert proof["query"] == {"date": "20080507"}
    assert proof["contentType"] == "application/json"
    assert proof["responseErrorCode"] == "INVALID_PARAMETER"
    assert proof["responseErrorMessage"] == "date format invalid"
    assert proof["planEntitlementError"] is False
    assert "never-log-this" not in json.dumps(proof)


def test_gemini_raw_metadata_classifies_thought_token_exhaustion_without_text():
    import scanner
    response = types.SimpleNamespace(
        model_version="gemini-3.1-pro-preview-001", response_id="response-safe",
        candidates=[types.SimpleNamespace(
            finish_reason="MAX_TOKENS", finish_message="output limit",
            content=types.SimpleNamespace(parts=[]), safety_ratings=[])],
        prompt_feedback=types.SimpleNamespace(
            block_reason=None, block_reason_message=None, safety_ratings=[]),
        usage_metadata=types.SimpleNamespace(
            prompt_token_count=6, thoughts_token_count=16,
            candidates_token_count=0, total_token_count=22))
    metadata = scanner._gemini_response_metadata(
        response, "gemini-3.1-pro-preview", "ARGUS_GEMINI_OK")
    assert metadata["responseId"] == "response-safe"
    assert metadata["candidates"][0]["finishReason"] == "MAX_TOKENS"
    assert metadata["tokenCounts"]["thoughtsTokenCount"] == 16
    assert metadata["textPartExists"] is False
    assert jobs.classify_gemini_preflight(metadata) == "max_tokens"


def test_gemini_preflight_success_and_latest_stable_selection():
    metadata = {"candidates": [{"finishReason": "STOP"}],
                "textPartExists": True, "nonEmptyTextPartExists": True,
                "matchedExpectedText": True, "promptFeedback": {},
                "errorClass": None}
    assert jobs.classify_gemini_preflight(metadata) == "success"
    assert jobs.select_latest_stable_gemini_pro([
        {"name": "models/gemini-3.1-pro-preview",
         "supportedActions": ["generateContent"]},
        {"name": "models/gemini-2.0-pro",
         "supportedActions": ["generateContent"]},
        {"name": "models/gemini-2.5-pro",
         "supportedActions": ["generateContent", "countTokens"]},
        {"name": "models/gemini-2.5-pro-latest",
         "supportedActions": ["generateContent"]},
        {"name": "models/gemini-3-pro-image",
         "supportedActions": ["generateContent"]},
        {"name": "models/gemini-3.1-pro-preview-customtools",
         "supportedActions": ["generateContent"]},
    ]) == "gemini-2.5-pro"


def test_jquants_calendar_uses_provider_confirmed_seven_day_windows(monkeypatch):
    import scanner
    calls = []

    def fake_rows(path, params, *, proof, max_pages=200):
        calls.append((path, dict(params)))
        return [{"Date": params["from"], "HolDiv": "1"}]

    monkeypatch.setattr(scanner, "_jquants_secure_rows", fake_rows)
    dates = scanner._jquants_calendar_dates(
        "2026-07-01", "2026-07-20", {})
    assert dates == ["2026-07-01", "2026-07-08", "2026-07-15"]
    assert [x[1] for x in calls] == [
        {"from": "2026-07-01", "to": "2026-07-07"},
        {"from": "2026-07-08", "to": "2026-07-14"},
        {"from": "2026-07-15", "to": "2026-07-20"},
    ]


def test_historical_candidates_exclude_weekends_but_do_not_claim_holidays():
    assert jobs.weekday_candidates("2026-07-17", "2026-07-21") == [
        "2026-07-17", "2026-07-20", "2026-07-21"]
    # Marine Day remains only a candidate; the worker requires non-empty
    # official bars before treating it as a trading date.


def test_provider_history_boundary_never_requires_a_pre_start_seed():
    dates = jobs.weekday_candidates("2016-07-20", "2016-07-22")
    assert dates[0] == jobs.ENTITLEMENT_START_DATE
    assert all(date >= jobs.ENTITLEMENT_START_DATE for date in dates)


def test_standard_boundary_rolls_with_execution_date_and_handles_leap_day():
    assert jobs.rolling_entitlement_start("2026-07-20") == "2016-07-20"
    assert jobs.rolling_entitlement_start("2026-07-21") == "2016-07-21"
    assert jobs.rolling_entitlement_start("2024-02-29", years=1) == "2023-02-28"


def test_five_year_production_scope_is_explicit_and_archive_is_non_core():
    assert jobs.production_calendar_start("2026-07-21") == "2021-07-21"
    scope = jobs.production_scope_metadata(
        latest_confirmed_date="2026-07-21",
        production_start_date="2021-07-21",
        entitlement_start_date="2016-07-21")
    assert scope == {
        "contractScope": "rolling_5_years",
        "productionHistoryYears": 5,
        "productionFiveYearStartDate": "2021-07-21",
        "productionFiveYearEndDate": "2026-07-21",
        "entitlementPolicy": "rolling_10_years",
        "entitlementStartDate": "2016-07-21",
        "archiveBackfillStatus": "deferred",
        "archiveScope": {"from": "2016-07-21", "to": "2021-07-20"},
        "coreRequired": False,
    }


def test_five_year_stages_are_bounded_and_reject_unknown_stage():
    full = jobs.staged_production_range(
        "full_5y", latest_confirmed_date="2026-07-21")
    one_year = jobs.staged_production_range(
        "one_year", latest_confirmed_date="2026-07-21")
    one_month = jobs.staged_production_range(
        "canary_1m", latest_confirmed_date="2026-07-21")
    five_days = jobs.staged_production_range(
        "canary_5d", latest_confirmed_date="2026-07-21")
    assert full == ("2021-07-21", "2026-07-21")
    assert one_year == ("2025-07-21", "2026-07-21")
    assert one_month == ("2026-06-20", "2026-07-21")
    assert five_days == ("2026-07-11", "2026-07-21")
    with pytest.raises(ValueError, match="invalid_breadth_stage"):
        jobs.staged_production_range(
            "ten_years", latest_confirmed_date="2026-07-21")


def test_breadth_supervisor_runs_work_in_independent_process(monkeypatch):
    import scanner

    previous_jobs = copy.deepcopy(scanner._FOUNDATION_JOBS)
    previous_ledger = copy.deepcopy(scanner._MARKET_LEDGER)
    scanner._MARKET_LEDGER.clear()
    scanner._MARKET_LEDGER.update(scanner.argus_market_ledger.empty_state())
    started = jobs.start_job(
        jobs.empty_state(), job_type="JQUANTS_BREADTH_BACKFILL",
        now_iso="2026-07-21T00:00:00Z", parameters={"stage": "canary_5d"})
    scanner._FOUNDATION_JOBS.clear()
    scanner._FOUNDATION_JOBS.update(started["state"])

    def child_body(job_id):
        scanner._foundation_job_update(job_id, status="running")
        scanner._breadth_commit_rows([{
            "seriesId": "breadth.all.advancers",
            "periodEnd": "2026-07-21",
            "publishedAt": "2026-07-21T17:00:00+09:00",
            "availableFrom": "2026-07-21T17:00:00+09:00",
            "observedAt": "2026-07-21T17:00:01+09:00",
            "value": 100, "unit": "count", "source": "test aggregate",
            "sourceKind": "derived", "status": "live", "metadata": {},
        }], "2026-07-21T17:00:01+09:00")
        rebuilt = scanner.argus_market_ledger.rebuild(
            scanner._MARKET_LEDGER, "2026-07-21T17:00:02+09:00")
        scanner._MARKET_LEDGER.clear()
        scanner._MARKET_LEDGER.update(rebuilt)
        scanner._foundation_job_update(job_id, status="completed", result={
            "status": "completed", "backtests": {}, "stateHash": "child"})

    monkeypatch.setattr(scanner, "_jquants_breadth_worker_process_body",
                        child_body)
    monkeypatch.setattr(scanner, "_osint_persist", lambda: None)
    try:
        scanner._jquants_breadth_worker(started["job"]["jobId"])
        final = scanner._foundation_job(started["job"]["jobId"])
        assert final["status"] == "completed"
        assert final["result"]["executionMode"] == "independent_os_process"
        assert final["result"]["workerConcurrency"] == 1
        assert final["result"]["workerMemorySoftLimitMb"] == 1024
        assert final["result"]["backendRestartCountDuringJob"] == 0
        assert any(row.get("seriesId") == "breadth.all.advancers" for row in
                   scanner._MARKET_LEDGER["observations"])
        assert scanner._MARKET_LEDGER["derivedStateDirty"] is False
    finally:
        scanner._FOUNDATION_JOBS.clear()
        scanner._FOUNDATION_JOBS.update(previous_jobs)
        scanner._MARKET_LEDGER.clear()
        scanner._MARKET_LEDGER.update(previous_ledger)


def test_provider_probe_advances_to_first_accessible_trading_day(monkeypatch):
    import scanner
    calls = []

    def fake_rows(path, params, *, proof, max_pages):
        day = str(params["date"])
        calls.append(day)
        if day == "2016-07-21":
            proof["planEntitlementError"] = True
            raise RuntimeError("jquants_http_400")
        proof["planEntitlementError"] = False
        return ([{"Date": day, "Code": "72030", "AdjC": 100}]
                if day == "2016-07-22" else [])

    monkeypatch.setattr(scanner, "_jquants_secure_rows", fake_rows)
    proof = {}
    start, rows = scanner._jquants_discover_entitlement_start(
        "2026-07-21", proof)
    assert start == "2016-07-22"
    assert rows[0]["Code"] == "72030"
    assert calls == ["2016-07-21", "2016-07-22"]
    assert proof["rollingCalendarBoundary"] == "2016-07-21"


def test_production_probe_advances_to_first_trading_day_in_five_year_window(
        monkeypatch):
    import scanner
    calls = []

    def fake_rows(path, params, *, proof, max_pages):
        day = str(params["date"])
        calls.append(day)
        return ([{"Date": day, "Code": "72030", "AdjC": 100}]
                if day == "2021-07-21" else [])

    monkeypatch.setattr(scanner, "_jquants_secure_rows", fake_rows)
    proof = {}
    start, rows = scanner._jquants_discover_production_start(
        "2026-07-20", proof)
    assert start == "2021-07-21"
    assert rows[0]["Code"] == "72030"
    assert calls == ["2021-07-20", "2021-07-21"]
    assert proof["productionCalendarBoundary"] == "2021-07-20"


def test_provider_probe_ignores_rows_from_a_different_embedded_date(monkeypatch):
    import scanner
    calls = []

    def fake_rows(path, params, *, proof, max_pages):
        day = str(params["date"])
        calls.append(day)
        if day == "2016-07-21":
            return [{"Date": "20160720", "Code": "72030", "AdjC": 99}]
        return [{"Date": day, "Code": "72030", "AdjC": 100}]

    monkeypatch.setattr(scanner, "_jquants_secure_rows", fake_rows)
    proof = {}
    start, rows = scanner._jquants_discover_entitlement_start(
        "2026-07-21", proof)
    assert start == "2016-07-22"
    assert rows[0]["Date"] == "2016-07-22"
    assert calls == ["2016-07-21", "2016-07-22"]


def test_journal_reverify_job_records_verified_ack(monkeypatch):
    import scanner
    previous_jobs = copy.deepcopy(scanner._FOUNDATION_JOBS)
    previous_cycle = copy.deepcopy(scanner._REMOTE_CYCLE)
    previous_ack = copy.deepcopy(scanner._REMOTE_ACK)
    started = jobs.start_job(jobs.empty_state(), job_type="JOURNAL_REVERIFY",
                             now_iso="2026-07-20T00:00:00Z")
    scanner._FOUNDATION_JOBS.clear()
    scanner._FOUNDATION_JOBS.update(started["state"])
    scanner._REMOTE_CYCLE.update({"expectedHash": "a" * 16,
                                  "actualHash": "a" * 16,
                                  "remoteCommitSha": "b" * 40,
                                  "readBackVerified": True,
                                  "pendingCount": 0, "acknowledgedCount": 4,
                                  "errorClass": None})
    scanner._REMOTE_ACK.update({"lastReceiptStatus": "verified",
                                "lastVerifiedRemoteAckAt":
                                "2026-07-20T00:01:00Z"})
    monkeypatch.setattr(scanner, "_remote_readback_ack",
                        lambda now: {"verificationStatus": "verified"})
    monkeypatch.setattr(scanner, "_osint_persist", lambda: None)
    monkeypatch.setattr(scanner, "_journal", lambda *args, **kwargs: None)
    try:
        scanner._journal_reverify_worker(started["job"]["jobId"])
        final = scanner._foundation_job(started["job"]["jobId"])
        assert final["status"] == "completed"
        assert final["result"]["readBackVerified"] is True
        assert final["result"]["ack"]["receiptStatus"] == "verified"
    finally:
        scanner._FOUNDATION_JOBS.clear()
        scanner._FOUNDATION_JOBS.update(previous_jobs)
        scanner._REMOTE_CYCLE.clear()
        scanner._REMOTE_CYCLE.update(previous_cycle)
        scanner._REMOTE_ACK.clear()
        scanner._REMOTE_ACK.update(previous_ack)
