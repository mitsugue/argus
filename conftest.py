"""Pytest fixtures shared across the ARGUS backend tests.

The production per-IP rate limiter (scanner._rate_limit / _RL_BUCKETS) counts every
request from a source IP within a rolling window. The Flask test client uses ONE
IP for the whole session, so as the suite grows, accumulated requests can trip the
limiter mid-suite and make an unrelated endpoint return the `rate_limited` JSON
(no `meta`/expected keys) — a false failure. Resetting the buckets before each test
gives every test a clean budget without weakening the limiter itself (a test that
intentionally exercises rate limiting still fills its own bucket within the test).
"""
import os
import tempfile

import pytest

# Parallel runs (pytest-xdist): scanner derives its default persistent root
# from the system temp directory at import time, so every worker process used
# the same checkpoint, recovery sidecar and sqlite files, and a test in one
# worker could see or erase another worker's state. Give each worker its own
# root before scanner is imported. Serial runs are unchanged.
# Individual-stock chart generation is retired in production (2026-10-01);
# the existing tests exercise that legacy path, so they keep it on. The
# retired behaviour has its own tests, which switch it off explicitly.
os.environ.setdefault("ARGUS_ASSET_CHART_GENERATION", "1")

if os.environ.get("PYTEST_XDIST_WORKER") and not os.environ.get("ARGUS_PERSISTENT_ROOT"):
    os.environ["ARGUS_PERSISTENT_ROOT"] = tempfile.mkdtemp(
        prefix="argus-test-%s-" % os.environ["PYTEST_XDIST_WORKER"])


class _PassiveTestPoller:
    """通常のHTTP単体検査から、終了しない外部取得スレッドを起動させない。"""
    def is_alive(self):
        return True


def _isolate_implicit_provider_pollers(monkeypatch):
    import argus_index_live
    import argus_macro_release_watch
    for module in (argus_index_live, argus_macro_release_watch):
        monkeypatch.setitem(module._state, "thread", _PassiveTestPoller())


@pytest.fixture(autouse=True)
def _passive_provider_pollers_for_http_unit_tests(monkeypatch):
    # 実際のbefore_requestとensure_startedの呼出しは残す。起動・巡回そのものの
    # 検査は新しい_stateと制御したThread/get/sleepを明示して実行する。
    _isolate_implicit_provider_pollers(monkeypatch)


@pytest.fixture(autouse=True)
def _reset_rate_limit_buckets():
    try:
        import scanner
        with scanner._RL_LOCK:
            scanner._RL_BUCKETS.clear()
        # V11.5.2: the explain-request / translation-request queues + their per-IP+symbol
        # throttles are module state too. The test client is one IP, so leftover throttle
        # stamps or queued entries would leak between tests (a later test posting the same
        # symbol reads `rate_limited`/`already_queued` unexpectedly). Clear them per test.
        for name in ("_MC_EXPLAIN_REQUESTS", "_MC_EXPLAIN_REQ_RL", "_NEWS_JA_VQUEUE",
                     "_NEWS_JA_VQUEUE_RL", "_INVESTIGATE_RL"):
            d = getattr(scanner, name, None)
            if isinstance(d, dict):
                d.clear()
        # V11.5.4: per-symbol sweep timestamps trip the investigate-now cooldown
        # across tests (single-IP test client) — clear per test.
        if isinstance(getattr(scanner, "_SWEEP_STATE", None), dict):
            scanner._SWEEP_STATE["bySymbol"] = {}
        # V12.2.9: the startup bootstrap (before_request) would otherwise run a
        # real /tmp+ledger restore on the suite's first request — nondeterministic
        # across machines. Normalize to a completed test-mode startup; tests that
        # exercise the bootstrap reset _STARTUP/_OSINT_PERSIST_STATE themselves.
        # V12.2.10: the tick-context remote read-back would hit the real GitHub
        # ledger from tests — disable per test; read-back tests inject a blob
        # directly into scanner._remote_readback_ack(blob=...).
        if isinstance(getattr(scanner, "_REMOTE_ACK", None), dict):
            scanner._REMOTE_ACK["disabled"] = True
        # 13.8.109: the scheduled brief tick now restores received macro results
        # first; without this a tick test reads the real GitHub ledger and leaves
        # its records in the shared worker. Restore tests reset the flag themselves.
        if isinstance(getattr(scanner, "_MACRO_ANALYSIS_STATE", None), dict):
            scanner._MACRO_ANALYSIS_STATE["restored"] = True
        # The adopted-rule results are reused by input identity; a test that
        # replaces a store reader must never inherit another test's results.
        import argus_earnings_history as _earnings_history
        if hasattr(_earnings_history, "clear_verified_originals"):
            _earnings_history.clear_verified_originals()
        # Owner decision 2026-10-16 limits cost-triggered full checkpoints to
        # one per 15 minutes in production; tests that assert the immediate
        # coalescing keep a zero interval, the limit has its own tests.
        if hasattr(scanner, "_COST_CHECKPOINT_MIN_INTERVAL_SEC"):
            scanner._COST_CHECKPOINT_MIN_INTERVAL_SEC = 0.0
            scanner._COST_CHECKPOINT_STATE["lastCostCheckpointMonotonic"] = None
            scanner._COST_CHECKPOINT_STATE["pendingSinceMonotonic"] = None
            scanner._COST_CHECKPOINT_STATE["pendingLatestMonotonic"] = None
            scanner._FULL_CHECKPOINT_STATE["lastVerifiedStartedMonotonic"] = None
        if isinstance(getattr(scanner, "_EVENT_NEWS_CONTEXT_MEMO", None), dict):
            scanner._EVENT_NEWS_CONTEXT_MEMO.clear()
        if isinstance(getattr(scanner, "_SAVED_VIEW_CALL_REPORT_MEMO", None), dict):
            scanner._SAVED_VIEW_CALL_REPORT_MEMO.clear()
        if isinstance(getattr(scanner, "_MARKET_BRIEF_SCHEDULE", None), dict):
            scanner._MARKET_BRIEF_SCHEDULE.update(coveredSlot=None, handledEventIds=[], eventDay=None,
                eventCount=0, lastCheckMonotonic=None, lastOutcomesMonotonic=None, lastDecision=None,
                editionsByKind={}, reusedNotScheduled=0)
        if isinstance(getattr(scanner, "_JP_FINANCIAL_VERIFY", None), dict):
            # Tests read the originals synchronously unless they test the warm.
            scanner._JP_FINANCIAL_VERIFY.update(state="DONE", errorClass=None)
        if isinstance(getattr(scanner, "_JP_ADOPTED_RULES_MEMO", None), dict):
            scanner._JP_ADOPTED_RULES_MEMO.update(key=None, at=0.0, results=None, performance=None)
        if isinstance(getattr(scanner, "_STARTUP", None), dict) and \
                scanner._STARTUP.get("state") == "bootstrapping":
            scanner._OSINT_PERSIST_STATE["restored"] = True
            now = scanner._ai_now_iso()
            scanner._STARTUP.update({"state": "ready",
                                     "restoreStartedAt": now,
                                     "restoreCompletedAt": now,
                                     "restoreOutcome": "test_mode"})
            scanner._RUNTIME["firstReadyAt"] = now
    except Exception:
        pass
    yield


@pytest.fixture(autouse=True)
def _isolate_market_store_residency():
    """v13.7.58: store residency is process state that a save flips.

    A test that persists a checkpoint detaches the derived market stores; an
    unrelated later test must still see them attached, exactly as a fresh
    process would.  Snapshot the residency rows before each test and restore
    them afterwards; clear the per-item read cache so no test reads another
    test's temporary files.
    """
    try:
        import copy
        import scanner
    except Exception:  # pragma: no cover - scanner import is the test's own problem
        yield
        return
    residency = getattr(scanner, "_MARKET_STORE_RESIDENCY", None)
    cache = getattr(scanner, "_MARKET_ITEM_CACHE", None)
    saved = copy.deepcopy(residency) if isinstance(residency, dict) else None
    try:
        yield
    finally:
        if saved is not None:
            for name, row in saved.items():
                live = residency.get(name)
                if isinstance(live, dict):
                    live.clear()
                    live.update(row)
        if cache is not None:
            try:
                cache.clear()
            except Exception:
                pass


# CI runs the suite with pytest-xdist in ``loadgroup`` mode. Every test file is
# kept on one worker (its module-level state never crosses workers), except
# the files below, whose tests are independent and long enough (dozens of
# 4-5 s cases) that keeping them together set the pace of the whole suite.
_PER_TEST_DISTRIBUTED_FILES = frozenset({
    "test_remote_recovery_publish.py",
})


@pytest.hookimpl(tryfirst=True)  # before xdist reads the group markers
def pytest_collection_modifyitems(config, items):
    if not config.pluginmanager.hasplugin("xdist"):
        return
    for item in items:
        name = item.path.name if hasattr(item, "path") else str(item.fspath).rsplit("/", 1)[-1]
        if name in _PER_TEST_DISTRIBUTED_FILES:
            continue
        item.add_marker(pytest.mark.xdist_group(name=name))
