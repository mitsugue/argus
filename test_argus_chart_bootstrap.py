"""v13.5.42 — boot-time asset chart bootstrap (argus_chart_bootstrap) tests.

The host is a fake module exposing the scanner functions the bootstrap
relies on; no network, no real scheduler.
"""
from __future__ import annotations

import threading
import types

import argus_asset_chart_cache
import argus_chart_bootstrap as boot


import pytest


@pytest.fixture(autouse=True)
def _isolate_product_stores():
    """Module stores (boot warm, derived valuation, statements state) must never
    leak into other auto-discovered suites (e.g. D07 expects MISSING when cold)."""
    import argus_chart_bootstrap as _boot
    import argus_japan_valuation as _val
    _boot._reset_for_tests(); _val._reset_for_tests()
    yield
    _boot._reset_for_tests(); _val._reset_for_tests()



def _report(symbol, market):
    """Minimal report accepted by argus_asset_chart_cache._valid_report."""
    return {"reportId": f"{symbol}-daily", "status": "ok", "market": market, "symbol": symbol,
            "indicators": {"bars": [{"date": "2026-09-02", "close": 1.0}]}}


def _host(targets, missing):
    """Fake scanner host: reports exist for every target except `missing`."""
    store = argus_asset_chart_cache.empty_store()
    host = types.SimpleNamespace()
    host._ASSET_CHART_REPORTS = store
    host.calls = []
    host.restored = 0

    def _restore():
        host.restored += 1

    def _targets():
        return list(targets)

    def _tick(deadline_monotonic=None):
        cursor = int(store.get("cursor") or 0) % len(targets)
        symbol, market = targets[cursor]
        store["cursor"] = (cursor + 1) % len(targets)
        host.calls.append((symbol, market, deadline_monotonic))
        if (symbol, market) in missing:
            missing.discard((symbol, market))
            report = _report(symbol, market)
            nxt, _pub = argus_asset_chart_cache.publish(
                argus_asset_chart_cache.normalize_store(store), market=market, symbol=symbol,
                timeframe="daily", dataset_hash="h1", method_version="m1", report=report,
                published_at="2026-09-03T07:00:00Z")
            store.clear(); store.update(nxt)
            return {"status": "published"}
        return {"status": "unchanged"}

    host._osint_restore_once = _restore
    host._asset_chart_targets = _targets
    host._precompute_asset_chart_tick = _tick
    return host


def test_bootstrap_declines_unsupported_hosts_and_kill_switch():
    boot._reset_for_tests()
    assert boot.ensure_started(types.SimpleNamespace(), environ={}) == "HOST_UNSUPPORTED"
    assert boot.ensure_started(None, environ={"ARGUS_CHART_BOOTSTRAP": "0"}) == "DISABLED"
    assert boot.status()["status"] == "NOT_STARTED"


def test_bootstrap_walks_every_target_once_after_restore_and_is_idempotent():
    boot._reset_for_tests()
    targets = [("5803", "JP"), ("9984", "JP"), ("NVDA", "US")]
    missing = {("5803", "JP"), ("NVDA", "US")}
    host = _host(targets, missing)
    # publish 9984 up front so the bootstrap only has to fill the gaps
    host._ASSET_CHART_REPORTS.update(argus_asset_chart_cache.publish(
        argus_asset_chart_cache.normalize_store(host._ASSET_CHART_REPORTS), market="JP", symbol="9984",
        timeframe="daily", dataset_hash="h0", method_version="m1",
        report=_report("9984", "JP"), published_at="2026-09-03T06:00:00Z")[0])
    done = threading.Event()
    sleeps = []

    def _sleep(seconds):
        sleeps.append(seconds)

    token = boot.ensure_started(host, environ={}, delay_seconds=0.0, per_symbol_seconds=7.0,
                                pause_seconds=0.0, sleeper=_sleep, clock=lambda: 100.0)
    assert token == "STARTED"
    boot._STATE["thread"].join(timeout=5)
    summary = boot.status()
    assert summary["status"] == "DONE"
    assert host.restored == 1
    assert summary["missingBefore"] == 2 and summary["missingAfter"] == 0
    assert summary["published"] == 2
    assert all(call[2] == 107.0 for call in host.calls)          # bounded per-symbol deadline
    assert len(host.calls) <= len(targets)
    assert boot.ensure_started(host, environ={}) == "DONE"       # single run per process
    assert host.restored == 1


def test_bootstrap_tolerates_tick_exceptions():
    boot._reset_for_tests()
    targets = [("5803", "JP")]
    host = _host(targets, {("5803", "JP")})

    def _boom(deadline_monotonic=None):
        raise RuntimeError("provider down")

    host._precompute_asset_chart_tick = _boom
    boot.ensure_started(host, environ={}, delay_seconds=0.0, pause_seconds=0.0,
                        sleeper=lambda s: None, clock=lambda: 0.0)
    boot._STATE["thread"].join(timeout=5)
    summary = boot.status()
    assert summary["status"] == "DONE" and summary["degraded"] == 1 and summary["missingAfter"] == 1


# ── v13.5.44: boot warm (SHO inputs, interest history, derived valuation) ──
def test_boot_warm_warms_sho_and_interest_history_and_publishes_valuation():
    import argus_japan_valuation as val
    boot._reset_for_tests(); val._reset_for_tests()
    targets = [("5803", "JP")]
    host = _host(targets, set())
    host._ASSET_CHART_REPORTS.update(argus_asset_chart_cache.publish(
        argus_asset_chart_cache.normalize_store(host._ASSET_CHART_REPORTS), market="JP", symbol="5803",
        timeframe="daily", dataset_hash="h0", method_version="m1",
        report=_report("5803", "JP"), published_at="2026-09-03T06:00:00Z")[0])
    host.sho_calls = []
    host._sho_pit_inputs = lambda warm=False: (host.sho_calls.append(warm) or
                                               {"sourceStatus": {"margin1570": "jquants_weekly"}})
    host.history_calls = []
    host._jq_price_history = lambda code: (host.history_calls.append(code) or {"closes": [4951.0, 5090.0]})
    host._DECISION_EVIDENCE_CACHE = {"6965": {}, "314A": {}, "NVDA": {}, "6330": {}}
    host._SD_EXTRA_SYMBOLS = {"6330": {"market": "JP"}, "AAPL": {"market": "US"}}
    host._JP_SEEN_SYMBOLS = {"7203": 1.0}
    host._JP_WATCHLIST = [{"symbol": "8058"}, {"symbol": "5803"}]
    host._SHO_STATEMENTS_CACHE = {"rows": [
        {"LocalCode": "58030", "DisclosedDate": "2026-08-05", "ForecastEarningsPerShare": "250.0"}],
        "source": "jquants"}
    host._JP_CACHE = {"data": {"stocks": [{"symbol": "5803", "price": 4951.0}]}}
    host._JQ_HISTORY_CACHE = {"8058": {"data": {"closes": [5059.0]}}}
    boot._STATE["warmMaxCycles"] = 1
    boot.ensure_started(host, environ={}, delay_seconds=0.0, pause_seconds=0.0,
                        sleeper=lambda s: None, clock=lambda: 0.0)
    boot._STATE["thread"].join(timeout=5)
    warm = boot.warm_status()
    assert warm["status"] == "DONE" and warm["cycles"] == 1
    assert host.sho_calls == [True]
    assert warm["shoSourceStatus"]["margin1570"] == "jquants_weekly"
    # interest = 5803 + curated + device-requested JP codes (US symbols excluded), bounded
    assert warm["interestSymbols"][:2] == ["5803", "8058"]
    assert set(warm["interestSymbols"]) == {"5803", "8058", "6965", "314A", "6330", "7203"}
    assert warm["interestRegistrySize"] == 4                      # registry keeps device codes
    assert set(warm["interestSymbols"]) <= set(host.history_calls)
    assert "1321" in host.history_calls                          # SIG-03 proxy history
    assert warm["historyWarmed"] == len(warm["interestSymbols"])
    evidence = val.current_evidence()
    assert evidence["status"] == "AVAILABLE" and evidence["coverage"] == 1
    assert val.statements_state()["rowCount"] == 1
    assert boot.interest_symbols(host)[0] == "5803"


def test_boot_warm_is_isolated_from_host_failures():
    import argus_japan_valuation as val
    boot._reset_for_tests(); val._reset_for_tests()
    host = _host([("5803", "JP")], set())
    host._ASSET_CHART_REPORTS.update(argus_asset_chart_cache.publish(
        argus_asset_chart_cache.normalize_store(host._ASSET_CHART_REPORTS), market="JP", symbol="5803",
        timeframe="daily", dataset_hash="h0", method_version="m1",
        report=_report("5803", "JP"), published_at="2026-09-03T06:00:00Z")[0])

    def _boom(warm=False):
        raise RuntimeError("provider down")

    host._sho_pit_inputs = _boom
    host._jq_price_history = _boom
    boot._STATE["warmMaxCycles"] = 1
    boot.ensure_started(host, environ={}, delay_seconds=0.0, pause_seconds=0.0,
                        sleeper=lambda s: None, clock=lambda: 0.0)
    boot._STATE["thread"].join(timeout=5)
    warm = boot.warm_status()
    assert warm["status"] == "DONE" and warm["errorClass"].startswith("sho_warm:")
    assert warm["historyWarmed"] == 0 and warm["cycles"] == 1



def test_interest_registry_outlives_host_cache_expiry_and_is_symbol_safe():
    import argus_japan_valuation as val
    boot._reset_for_tests(); val._reset_for_tests()
    host = _host([("5803", "JP")], set())
    host._DECISION_EVIDENCE_CACHE = {"6965": {}}
    boot.scan_interest(host, 100.0)
    host._DECISION_EVIDENCE_CACHE = {}                           # host cache expired (120 s TTL)
    assert boot.interest_symbols(host, 200.0)[-1] == "6965"      # registry remembers it
    boot.scan_interest(host, 100.0 + boot.INTEREST_TTL_SECONDS + 1)
    assert "6965" not in boot.interest_symbols(host)             # 7-day TTL
    safe = boot.warm_status_safe()
    assert "interestSymbols" not in safe and "interestCount" in safe and "chart" in safe


def test_warm_cycle_warms_curated_reference_and_statements_when_offered():
    import argus_japan_valuation as val
    boot._reset_for_tests(); val._reset_for_tests()
    host = _host([("5803", "JP")], set())
    host._ASSET_CHART_REPORTS.update(argus_asset_chart_cache.publish(
        argus_asset_chart_cache.normalize_store(host._ASSET_CHART_REPORTS), market="JP", symbol="5803",
        timeframe="daily", dataset_hash="h0", method_version="m1",
        report=_report("5803", "JP"), published_at="2026-09-03T06:00:00Z")[0])
    calls = {"curated": 0, "jq": [], "us": [], "stmt": []}
    host.get_japan_watchlist_snapshot = lambda **kw: calls.__setitem__("curated", calls["curated"] + 1)
    host._jq_price_history = lambda code: (calls["jq"].append(code) or {"closes": [1.0]})
    host._us_price_history = lambda code: (calls["us"].append(code) or {"closes": [1.0]})
    host._jquants_paginated = lambda path, params, max_pages=2, request_timeout=8: (
        calls["stmt"].append(params["code"]) or [
            {"LocalCode": params["code"] + "0", "DisclosedDate": "2026-08-10", "ForecastEarningsPerShare": "100"}])
    host._sho_pit_inputs = lambda warm=False: {"sourceStatus": {}}
    host._SHO_STATEMENTS_CACHE = {"rows": [], "source": "jquants"}
    host._JQ_HISTORY_CACHE = {"5803": {"data": {"closes": [4951.0]}}}
    host._JP_WATCHLIST = [{"symbol": "5803"}]
    boot._STATE["warmMaxCycles"] = 1
    boot.ensure_started(host, environ={}, delay_seconds=0.0, pause_seconds=0.0,
                        sleeper=lambda s: None, clock=lambda: 0.0)
    boot._STATE["thread"].join(timeout=5)
    warm = boot.warm_status()
    assert calls["curated"] == 1 and warm["curatedWarmedAt"]
    assert "1321" in calls["jq"] and calls["us"] == ["SPY"] and warm["referenceWarmed"] == 2
    assert calls["stmt"] == ["5803"] and warm["statementsFetched"] == 1
    evidence = val.current_evidence()
    assert evidence["status"] == "AVAILABLE" and evidence["coverage"] == 1   # per-code statements merged
