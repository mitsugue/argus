"""v11.8.1 — the search bucket is isolated from the heavy polling bucket.

Owner report: 「検索すると混雑してるとよく言われて出ないことが多い」— background
quote polling (3 devices on one IP) exhausted the shared heavy bucket and 429'd
interactive search. Now polling can never starve search, and vice versa.
"""
import time
from collections import deque

import scanner


def _fill(ip, n):
    scanner._RL_BUCKETS[ip] = deque([time.time()] * n)


def test_polling_exhaustion_does_not_block_search():
    with scanner.app.test_client() as c:
        # exhaust the ordinary heavy bucket for the test client's IP
        r0 = c.get("/api/argus/position-exposure/status")   # learn the bucket ip
        assert r0.status_code == 200
        ip = [k for k in scanner._RL_BUCKETS if not k.endswith(":search")][0]
        _fill(ip, scanner._RL_MAX_HEAVY + 50)
        # heavy polling endpoint is now rate-limited…
        r1 = c.get("/api/argus/flow-attribution?symbol=6146&market=JP")
        assert r1.status_code == 429
        # …but symbol-search still works (its own bucket)
        r2 = c.get("/api/argus/symbol-search?q=trend&market=US")
        assert r2.status_code != 429


def test_search_bucket_has_own_limit():
    with scanner.app.test_client() as c:
        c.get("/api/argus/position-exposure/status")
        ip = [k for k in scanner._RL_BUCKETS if not k.endswith(":search")][0]
        _fill(ip + ":search", scanner._RL_MAX_SEARCH + 5)
        r = c.get("/api/argus/symbol-search?q=trend&market=US")
        assert r.status_code == 429                     # search abuse still bounded
        r2 = c.get("/api/argus/position-exposure/status")
        assert r2.status_code == 200                    # normal traffic unaffected


def test_heavy_limit_raised():
    assert scanner._RL_MAX_HEAVY >= 140
    assert scanner._RL_MAX_SEARCH >= 20
