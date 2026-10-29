"""Process-resident collection cadence (2026-10-19): the 30-minute collection starts in-process."""
import time

import scanner


def _fresh(monkeypatch, *, started_ago, last_ago=None, running=False):
    now = 100_000.0
    monkeypatch.setattr(scanner, "_INTEL_COLLECT_PROCESS_STARTED", now - started_ago)
    monkeypatch.setattr(scanner, "_INTEL_COLLECT_RUN", {"status": "running", "runId": "x"} if running else {})
    monkeypatch.setattr(scanner, "_INTEL_COLLECT_LAST", {
        "finishedMonotonic": None if last_ago is None else now - last_ago, "finishedAt": None,
        "status": None, "trigger": None, "residentStarted": 0})
    return now


def test_not_during_the_first_ten_minutes_after_a_start(monkeypatch):
    now = _fresh(monkeypatch, started_ago=300)
    assert scanner._intel_collect_resident_tick(now) is None


def test_not_while_a_collection_runs_or_within_thirty_minutes(monkeypatch):
    now = _fresh(monkeypatch, started_ago=3600, running=True)
    assert scanner._intel_collect_resident_tick(now) is None
    now = _fresh(monkeypatch, started_ago=3600, last_ago=29 * 60)
    assert scanner._intel_collect_resident_tick(now) is None


def test_starts_one_tracked_collection_when_due_and_records_its_end(monkeypatch):
    now = _fresh(monkeypatch, started_ago=3600, last_ago=31 * 60)
    calls = []
    monkeypatch.setattr(scanner, "_collect_institutional_intel_and_warm", lambda: calls.append(1) or {"ok": True})
    assert scanner._intel_collect_resident_tick(now) is True
    for _ in range(100):
        if scanner._INTEL_COLLECT_RUN.get("status") != "running":
            break
        time.sleep(0.02)
    assert calls == [1] and scanner._INTEL_COLLECT_RUN["status"] == "done"
    assert scanner._INTEL_COLLECT_LAST["trigger"] == "resident" and scanner._INTEL_COLLECT_LAST["residentStarted"] == 1
    assert scanner._INTEL_COLLECT_RUN["runId"].startswith("resident-")
    # Just finished: the next tick waits another 30 minutes.
    assert scanner._intel_collect_resident_tick(time.monotonic()) is None


def test_an_external_request_also_counts_as_the_last_collection(monkeypatch):
    _fresh(monkeypatch, started_ago=3600, last_ago=None)
    monkeypatch.setattr(scanner, "_collect_institutional_intel_and_warm", lambda: {"ok": True})
    scanner._intel_collect_tracked("external-run-1")
    for _ in range(100):
        if scanner._INTEL_COLLECT_RUN.get("status") != "running":
            break
        time.sleep(0.02)
    assert scanner._INTEL_COLLECT_LAST["trigger"] == "request"
    assert scanner._intel_collect_resident_tick(time.monotonic()) is None


def test_the_scheduler_starts_the_resident_tick():
    source = open("scanner.py", encoding="utf-8").read()
    assert 'target=_intel_collect_resident_tick, daemon=True, name="intel-collect-resident"' in source


def test_market_input_diagnostics_preserve_inputs_and_measure_each_group(monkeypatch):
    scanner._INTEL_COLLECT_CONTEXT.run_id = "pit-test-run"
    scanner._INTEL_COLLECT_CONTEXT.stage_started = None
    monkeypatch.setattr(scanner, "_INTEL_COLLECT_RUN", {"status": "running", "runId": "pit-test-run"})
    monkeypatch.setattr(scanner, "_JP_MARKET_ENGINE_PIT_INPUT_MEMO", {"data": None, "ts": 0})
    noop = lambda *a, **k: None
    names = ("_jp_market_stored_inputs_restore _index_research_restore _n225_analog_history_restore "
             "_fred_us10y_history_dated _jquants_topix_history _fred_history_dated _jp_historical_release_refresh "
             "_cftc_jpy_autorefresh _future_map_scoring_tick _jp_index_valuation_warm _jp_index_proxy_warm "
             "_level_map_warm _analyst_targets_warm _jp_internals_warm _jq_margin_history_backfill "
             "_jp_market_engine_statements_rows _fred_vix_history_dated _n225_analog_history_warm "
             "_jp_official_sources_warm _jp_market_feature_history_warm _index_research_warm "
             "_jp_market_inputs_backup_schedule").split()
    for name in names:
        monkeypatch.setattr(scanner, name, noop)
    monkeypatch.setattr(scanner, "_jp_market_engine_vix_rows", lambda **k: ([{"vix": 1}], "test"))
    monkeypatch.setattr(scanner, "_yahoo_index_ohlcv", lambda *a, **k: [{"close": 1}])
    monkeypatch.setattr(scanner, "_jpx_credit_rows_effective", lambda: [1])
    monkeypatch.setattr(scanner, "_jp_market_engine_margin_1570_rows", lambda **k: [2])
    monkeypatch.setattr(scanner, "_jp_market_engine_relative_strength_direct", lambda: [3])
    monkeypatch.setattr(scanner, "_jp_market_engine_foreign_flow_rows", lambda: [4])
    monkeypatch.setattr(scanner, "_jp_market_engine_earnings_event", lambda: (None, "missing"))
    try:
        result = scanner._jp_market_engine_pit_inputs(warm=True)
        assert result["creditRows"] == [1] and result["margin1570Rows"] == [2]
        assert result["rsDirect"] == [3] and result["flowRows"] == [4]
        stages = [row["stage"] for row in scanner._INTEL_COLLECT_RUN["completedStages"]]
        assert stages == ["pit_restore", "pit_vix_nikkei", "pit_fx_sp500", "pit_macro_history",
                          "pit_credit", "pit_future_valuation", "pit_level_map", "pit_targets_internals",
                          "pit_margin", "pit_statements", "pit_earnings", "pit_vix_analog",
                          "pit_official", "pit_feature_history", "pit_research"]
        assert scanner._INTEL_COLLECT_RUN["stage"] == "pit_backup"
        assert all(row["elapsedSeconds"] >= 0 for row in scanner._INTEL_COLLECT_RUN["completedStages"])
    finally:
        scanner._INTEL_COLLECT_CONTEXT.run_id = None
        scanner._INTEL_COLLECT_CONTEXT.stage_started = None
