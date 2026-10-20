"""Owner diagnostic privacy, partial progress and existing warm boundary."""
import ast
import copy
import json
from pathlib import Path
from types import SimpleNamespace
import threading
from datetime import date, timedelta

from flask import Flask, jsonify, request
import pytest

import argus_level_map_acquisition as diagnostic
import jp_market_level_map as level_map


def test_partial_selection_is_not_received_or_saved():
    record = diagnostic.begin(current_only=False, attempted_at="2026-10-14T00:17:24Z", cursor=None)
    diagnostic.selected(record, ["2017-04-12", "2017-04-13"])
    diagnostic.outcome(record, "2017-04-12", "STARTED")
    view = diagnostic.projection({"acquisitionDiagnostics": {"HISTORICAL": record}}, worker_active=True)
    assert view["historical"]["phase"] == "READING"
    assert [r["status"] for r in view["historical"]["outcomes"]] == ["STARTED", None]
    assert view["historical"]["outcomes"][0]["missingEarnings"] is None
    assert view["workerActive"] is True


def test_outcomes_separate_empty_incomplete_and_correction():
    record = diagnostic.begin(current_only=False, attempted_at="2026-10-14T00:17:24Z", cursor="2017-04-14")
    days = ["2017-04-12", "2017-04-13", "2017-04-14"]
    diagnostic.selected(record, days)
    diagnostic.outcome(record, days[0], "NO_VALUATION_ROWS")
    diagnostic.outcome(record, days[1], "INPUT_INCOMPLETE", {"missingEarnings": 3, "missingMarketCap": 0})
    diagnostic.outcome(record, days[2], "STORED_CORRECTION", {"missingEarnings": 0, "missingMarketCap": 0})
    diagnostic.finish(record, cursor="2017-04-12", warm_status="AVAILABLE")
    historical = diagnostic.projection({"acquisitionDiagnostics": {"HISTORICAL": record}})["historical"]
    assert historical["cursorBefore"] == "2017-04-14"
    assert historical["cursorAfter"] == "2017-04-12"
    assert [r["status"] for r in historical["outcomes"]] == ["NO_VALUATION_ROWS", "INPUT_INCOMPLETE", "STORED_CORRECTION"]
    assert historical["outcomes"][0]["missingEarnings"] is None
    assert historical["outcomes"][1]["missingEarnings"] == 3


def test_current_warm_retains_historical_attempt():
    prior = diagnostic.begin(current_only=False, attempted_at="2026-10-14T00:17:24Z", cursor="2017-04-14")
    diagnostic.selected(prior, ["2017-04-12"])
    diagnostic.finish(prior, cursor="2017-04-12", warm_status="AVAILABLE")
    current = diagnostic.begin(current_only=True, attempted_at="2026-10-14T07:35:00Z", cursor="2017-04-12")
    state = {"acquisitionDiagnostics": {"HISTORICAL": prior, "CURRENT": current}}
    before = copy.deepcopy(state)
    view = diagnostic.projection(state)
    assert view["historical"]["selectedCount"] == 1
    assert view["current"]["selectedCount"] is None
    assert state == before


@pytest.mark.parametrize("value", [True, -1, 226, float("nan"), "secret", {}])
def test_invalid_counts_are_unknown_not_zero(value):
    record = diagnostic.begin(current_only=True, attempted_at="2026-10-14T00:17:24Z", cursor=None)
    diagnostic.selected(record, ["2026-10-13"])
    diagnostic.outcome(record, "2026-10-13", "INPUT_INCOMPLETE", {"missingEarnings": value})
    view = diagnostic.projection({"acquisitionDiagnostics": {"CURRENT": record}})
    assert view["current"]["outcomes"][0]["missingEarnings"] is None


@pytest.mark.parametrize("days", [["2017-04-12"] * 2, ["invalid"], ["2017-04-12"] * 21])
def test_invalid_or_over_bound_selection_does_not_claim_complete(days):
    record = {"selectedDates": days, "outcomes": {}}
    view = diagnostic.projection({"acquisitionDiagnostics": {"HISTORICAL": record}})["historical"]
    assert view["selectionValid"] is False
    assert view["selectedCount"] is None
    assert view["outcomes"] == []


def test_unsafe_text_and_prices_never_enter_owner_projection():
    state = {"loaded": True, "eps": {"2026-10-13": {"eps": 9999, "owner": "sensitive-sentinel"}},
             "epsBackfillCursor": "sensitive-sentinel",
             "acquisitionDiagnostics": {"HISTORICAL": {
                 "mode": "sensitive-sentinel", "phase": "sensitive-sentinel",
                 "attemptedAt": "sensitive-sentinel", "warmStatus": {},
                 "errorClass": "sensitive-sentinel", "selectedDates": ["2017-04-12"],
                 "outcomes": {"2017-04-12": {"status": {}, "owner": "sensitive-sentinel"}}}}}
    view = diagnostic.projection(state)
    assert "sensitive-sentinel" not in json.dumps(view)
    assert "9999" not in json.dumps(view)
    assert view["historical"]["errorClass"] == "OTHER_ERROR"
    assert view["currentCursor"] is None


def _existing_endpoint(state):
    tree = ast.parse(Path("scanner.py").read_text(encoding="utf-8"))
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "api_argus_admin_memory_attribution")
    function.decorator_list = []
    app = Flask(__name__)
    calls = []
    def forbidden():
        calls.append("forbidden")
        raise AssertionError("No provider, collection, history or AI call is permitted")
    scope = {"request": request, "jsonify": jsonify, "copy": copy,
             "_require_admin": lambda: (True, None, 200) if request.headers.get("X-ARGUS-ADMIN-TOKEN") == "synthetic-admin" else (False, {"error": "unauthorized"}, 401),
             "_MEMORY_ATTRIBUTION": SimpleNamespace(view=lambda: {}),
             "_MEMORY_OPERATIONS": SimpleNamespace(view=lambda: {}),
             "_ALLOCATOR_RECLAIM_STATE": {}, "_STARTUP_RSS": {}, "_HEAVY_TICK_STATE": {},
             "_process_peak_memory_mb": lambda: 1, "_startup_rss_mib": lambda: 1,
             "_market_store_residency_projection": lambda: {}, "_LEVEL_MAP": state,
             "_LEVEL_MAP_LOCK": threading.Lock(), "_level_map_warm": forbidden,
             "_jq_valuation_for_date": forbidden, "_index_research_warm": forbidden,
             # 2026-10-20: names the current endpoint reads (diagnostics added
             # after 2026-10-14), as harmless scalars; none of them collects.
             "_diagnostic_counters_copy": lambda value: dict(value or {}),
             "_MISSION_PHASE_TIMING": {"phases": {}, "startedAt": None}, "_CHECKPOINT_PERSIST_STATS": {},
             "_MARKET_BRIEF_SCHEDULE": {}, "_JP_FINANCIAL_VERIFY": {}, "_material_research_diagnostics": lambda: {},
             "_INTEL_COLLECT_LOCK": threading.Lock(), "_INTEL_COLLECT_LAST": {}, "_INTEL_COLLECT_RUN": {},
             "INTEL_COLLECT_RESIDENT_INTERVAL_SECONDS": 1800,
             "_jp_index_official_factor_status": lambda: {"status": "NOT_CONFIGURED"}, "_JSF_DAILY_STATUS": {},
             "_INDEX_RESEARCH_STATUS": {}, "_INDEX_RESEARCH_REPORTS": {}, "_JP_MARKET_FEATURE_HISTORY": {},
             "_JP_ANALOG_RESEARCH_INPUTS": {}, "_JP_INPUT_BACKUP_STATUS": {}, "_JP_INPUT_BACKUP_LOCK": threading.Lock(),
             "_resident_inventory": forbidden, "_runtime_thread_dump": forbidden,
             "_ANALYSIS_HISTORY_FORM": {},
             "_DURABLE_STORAGE_STATUS": {}}
    exec(compile(ast.Module(body=[function], type_ignores=[]), "scanner.py", "exec"), scope)
    app.add_url_rule("/api/argus/admin/memory-attribution", view_func=scope[function.name])
    return app, calls


def test_existing_get_requires_auth_and_explicit_opt_in_without_collection():
    state = {"loaded": True, "eps": {"2026-10-13": {"owner": "sensitive-sentinel"}}, "epsBackfillCursor": "2017-04-12"}
    before = copy.deepcopy(state)
    app, calls = _existing_endpoint(state)
    with app.test_client() as client:
        denied = client.get("/api/argus/admin/memory-attribution?level-map-inputs=1")
        ordinary = client.get("/api/argus/admin/memory-attribution", headers={"X-ARGUS-ADMIN-TOKEN": "synthetic-admin"})
        read = client.get("/api/argus/admin/memory-attribution?level-map-inputs=1", headers={"X-ARGUS-ADMIN-TOKEN": "synthetic-admin"})
    assert denied.status_code == 401 and "levelMapInputs" not in denied.get_json()
    assert ordinary.status_code == 200 and "levelMapInputs" not in ordinary.get_json()
    view = read.get_json()["levelMapInputs"]
    assert read.status_code == 200 and view["currentCursor"] == "2017-04-12"
    assert view["admittedEstimateCount"] == 1
    assert "sensitive-sentinel" not in json.dumps(view)
    assert calls == [] and state == before


def _existing_warm(*, fail_at=None):
    tree = ast.parse(Path("scanner.py").read_text(encoding="utf-8"))
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_level_map_warm")
    bars = [{"date": (date(2026, 9, 1) + timedelta(days=i)).isoformat(), "close": 1000} for i in range(30)]
    history = [{"date": (date(2017, 4, 1) + timedelta(days=i)).isoformat(), "close": 1000} for i in range(30)]
    members = ["1001", "1002", "1003"]
    requests, writes, corrections = [], [], []
    state = {"loaded": True, "eps": {}, "mornings": [], "missedMornings": [], "conflicts": 0,
             "epsBackfillCursor": "2017-04-28", "status": "NOT_RUN"}
    def valuation(day, headers):
        requests.append(day)
        if len(requests) == fail_at:
            raise TimeoutError("sensitive-sentinel")
        if len(requests) == 2:
            return {}
        rows = {code: {"MktCap": 100, "FwdPER": 10} for code in members}
        if len(requests) == 3:
            rows.pop(members[0])
        if len(requests) == 4:
            return {code: {"MktCap": -1, "FwdPER": 10} for code in members}
        return rows
    def original(path, estimate):
        writes.append(copy.deepcopy(estimate))
        return {"inserted": len(requests) != 5, "conflict": len(requests) == 5}
    def correction(path, estimate):
        corrections.append(copy.deepcopy(estimate))
        return {"inserted": True}
    def no_retrospective(*args, **kwargs):
        raise level_map.LevelMapError("synthetic_no_morning")
    arithmetic = SimpleNamespace(**{k: getattr(level_map, k) for k in (
        "pending_eps_sessions", "weighted_eps", "estimate_input_usable", "daily_close_repairable", "LevelMapError")})
    arithmetic.zigzag = lambda rows: []
    arithmetic.constituents_on = lambda day, constituents, as_of, changes: (members, day)
    arithmetic.score_records = lambda *a: {}
    arithmetic.morning_map = no_retrospective
    scope = {"_LEVEL_MAP": state, "_LEVEL_MAP_LOCK": threading.Lock(),
             "_ai_now_iso": lambda: "2026-10-14T00:17:24Z", "_level_map_history_path": lambda: "synthetic-history",
             "argus_analysis_history": SimpleNamespace(initialize=lambda p: None, append_level_map_eps=original,
                                                       append_level_map_eps_correction=correction),
             "_level_map_admitted_eps": lambda: dict(state["eps"]),
             "_level_map_completed_bars": lambda rows, now: bars, "_N225_ANALOG_HISTORY": {"data": history},
             "_JP_INDEX_PROXY": {"factors": {"factors": dict.fromkeys(members, 1)}, "weightsAsOf": bars[-1]["date"]},
             "_JQUANTS_API_KEY": "synthetic-api", "_LEVEL_MAP_EPS_SINCE": "2016-10-03", "_LEVEL_MAP_EPS_PER_WARM": 20,
             "_LEVEL_MAP_MAP_SINCE": "2026-06-01", "jp_market_level_map": arithmetic,
             "_jq_valuation_for_date": valuation, "_nikkei225_constituent_changes": lambda: [],
             "_JQ_VALUATION_DAY_CACHE": {}, "_level_map_next_session": lambda day: None,
             "_CANDIDATES": {}, "_candidates_warm": lambda *a: None, "_level_map_remote": lambda: None}
    exec(compile(ast.Module(body=[function], type_ignores=[]), "scanner.py", "exec"), scope)
    return scope, requests, writes, corrections, bars


def test_real_warm_observes_same_twenty_date_calls_and_existing_append_decisions():
    scope, requests, writes, corrections, bars = _existing_warm()
    scope["_level_map_warm"](bars)
    state = scope["_LEVEL_MAP"]
    view = diagnostic.projection(state)["historical"]
    assert len(requests) == 20 and [row["date"] for row in view["outcomes"]] == requests
    assert [row["status"] for row in view["outcomes"][:5]] == ["STORED_ORIGINAL", "NO_VALUATION_ROWS", "INPUT_INCOMPLETE", "INVALID_ESTIMATE", "STORED_CORRECTION"]
    assert len(writes) == 17 and len(corrections) == 1 and state["estimatesLastWarm"] == 17
    assert all(row["coverage"]["missingMarketCap"] == row["coverage"]["missingEarnings"] == 0 for row in writes)
    assert view["cursorAfter"] == requests[-1] and view["phase"] == "FINISHED"
    prior = copy.deepcopy(state["acquisitionDiagnostics"]["HISTORICAL"])
    scope["_level_map_warm"](bars, current_only=True)
    assert state["acquisitionDiagnostics"]["HISTORICAL"] == prior
    assert diagnostic.projection(state)["current"]["selectedCount"] <= 1
    assert not scope["_LEVEL_MAP_LOCK"].locked()


def test_real_warm_failure_keeps_selected_vs_received_distinction_and_unlocks():
    scope, requests, writes, corrections, bars = _existing_warm(fail_at=3)
    scope["_level_map_warm"](bars)
    view = diagnostic.projection(scope["_LEVEL_MAP"])["historical"]
    assert len(requests) == 3 and len(writes) == 1 and corrections == []
    assert view["phase"] == "FAILED" and view["errorClass"] == "TimeoutError"
    assert [row["status"] for row in view["outcomes"][:4]] == ["STORED_ORIGINAL", "NO_VALUATION_ROWS", "STARTED", None]
    assert "sensitive-sentinel" not in json.dumps(view)
    assert not scope["_LEVEL_MAP_LOCK"].locked()
