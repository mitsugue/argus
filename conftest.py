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
                     "_NEWS_JA_VQUEUE_RL"):
            d = getattr(scanner, name, None)
            if isinstance(d, dict):
                d.clear()
    except Exception:
        pass
    yield
