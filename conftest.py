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
    except Exception:
        pass
    yield
