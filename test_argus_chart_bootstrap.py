"""v13.5.42 — boot-time asset chart bootstrap (argus_chart_bootstrap) tests.

The host is a fake module exposing the scanner functions the bootstrap
relies on; no network, no real scheduler.
"""
from __future__ import annotations

import threading
import types

import argus_asset_chart_cache
import argus_chart_bootstrap as boot


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
