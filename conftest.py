"""Pytest fixtures shared across the ARGUS backend tests.

The production per-IP rate limiter (scanner._rate_limit / _RL_BUCKETS) counts every
request from a source IP within a rolling window. The Flask test client uses ONE
IP for the whole session, so as the suite grows, accumulated requests can trip the
limiter mid-suite and make an unrelated endpoint return the `rate_limited` JSON
(no `meta`/expected keys) — a false failure. Resetting the buckets before each test
gives every test a clean budget without weakening the limiter itself (a test that
intentionally exercises rate limiting still fills its own bucket within the test).
"""
import pytest


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
