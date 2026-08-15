"""ETF cache preserves fresh rows without renewing absent/stale symbols."""
import scanner


class _Resp:
    def __init__(self, body): self._b = body
    def raise_for_status(self): pass
    def json(self): return self._b


def _full_body(syms):
    return {s: {"status": "ok", "values": [{"close": "100"}, {"close": "99"}]} for s in syms}


def _setup(monkeypatch):
    monkeypatch.setattr(scanner, "_TWELVEDATA_API_KEY", "k")
    scanner._TD_TS_CACHE.clear()
    scanner._ETF_LAST_PRICE.clear()


def test_full_then_error_serves_last_good(monkeypatch):
    _setup(monkeypatch)
    syms = ["SPY", "QQQ", "GLD"]
    monkeypatch.setattr(scanner.requests, "get", lambda *a, **k: _Resp(_full_body(syms)))
    first = scanner._td_timeseries(syms)
    assert len(first) == 3                      # full coverage cached
    # next refresh: provider rate-limited (top-level error)
    monkeypatch.setattr(scanner.requests, "get", lambda *a, **k: _Resp({"status": "error"}))
    # expire the cache so it actually refetches
    scanner._TD_TS_CACHE[",".join(syms)]["expires"] = 0
    second = scanner._td_timeseries(syms)
    assert len(second) == 3                      # served last-good, NOT {} → no partial


def test_partial_fetch_merges_with_last_good(monkeypatch):
    _setup(monkeypatch)
    syms = ["SPY", "QQQ", "GLD"]
    monkeypatch.setattr(scanner.requests, "get", lambda *a, **k: _Resp(_full_body(syms)))
    scanner._td_timeseries(syms)
    # refresh returns only 1 of 3 symbols
    monkeypatch.setattr(scanner.requests, "get", lambda *a, **k: _Resp(_full_body(["SPY"])))
    scanner._TD_TS_CACHE[",".join(syms)]["expires"] = 0
    merged = scanner._td_timeseries(syms)
    assert len(merged) == 3                      # missing QQQ/GLD kept from last-good


def test_network_error_serves_last_good(monkeypatch):
    _setup(monkeypatch)
    syms = ["SPY", "QQQ"]
    monkeypatch.setattr(scanner.requests, "get", lambda *a, **k: _Resp(_full_body(syms)))
    scanner._td_timeseries(syms)
    def _boom(*a, **k): raise RuntimeError("net down")
    monkeypatch.setattr(scanner.requests, "get", _boom)
    scanner._TD_TS_CACHE[",".join(syms)]["expires"] = 0
    out = scanner._td_timeseries(syms)
    assert len(out) == 2                          # last-good, never {}


def test_partial_refresh_does_not_renew_stale_missing_symbols(monkeypatch):
    _setup(monkeypatch)
    syms = ["SPY", "QQQ", "GLD"]
    now = 1_700_000_000.0
    monkeypatch.setattr(scanner.time, "time", lambda: now)
    scanner._TD_TS_CACHE[",".join(syms)] = {
        "data": {s: [100.0, 99.0] for s in syms},
        "symbolUpdatedAt": {
            "SPY": now - 10,
            "QQQ": now - scanner._TD_TS_TTL - 1,
            "GLD": now - scanner._TD_TS_TTL - 1,
        },
        "expires": 0,
    }
    monkeypatch.setattr(
        scanner.requests, "get", lambda *a, **k: _Resp(_full_body(["SPY"])))
    out = scanner._td_timeseries(syms)
    assert set(out) == {"SPY"}
    cached = scanner._TD_TS_CACHE[",".join(syms)]
    assert set(cached["symbolUpdatedAt"]) == {"SPY"}


def test_partial_refresh_does_not_extend_whole_cache_past_carried_member_expiry(
        monkeypatch):
    _setup(monkeypatch)
    syms = ["SPY", "QQQ", "GLD"]
    now = [1_700_000_000.0]
    monkeypatch.setattr(scanner.time, "time", lambda: now[0])
    key = ",".join(syms)
    scanner._TD_TS_CACHE[key] = {
        "data": {s: [100.0, 99.0] for s in syms},
        "symbolUpdatedAt": {
            s: now[0] - scanner._TD_TS_TTL + 10 for s in syms},
        "expires": 0,
    }
    calls = []

    def partial(*_args, **_kwargs):
        calls.append(True)
        return _Resp(_full_body(["SPY"]))

    monkeypatch.setattr(scanner.requests, "get", partial)
    first = scanner._td_timeseries(syms)
    assert set(first) == set(syms)
    # Whole-cache validity is capped by QQQ/GLD's independent 10s lifetime,
    # not renewed for the full two-hour TTL by SPY's response.
    assert scanner._TD_TS_CACHE[key]["expires"] == now[0] + 10

    now[0] += 20
    second = scanner._td_timeseries(syms)
    assert set(second) == {"SPY"}
    assert len(calls) == 2


def test_empty_partial_response_cannot_extend_carried_member_expiry(monkeypatch):
    _setup(monkeypatch)
    syms = ["SPY", "QQQ"]
    now = 1_700_000_000.0
    monkeypatch.setattr(scanner.time, "time", lambda: now)
    key = ",".join(syms)
    scanner._TD_TS_CACHE[key] = {
        "data": {s: [100.0, 99.0] for s in syms},
        "symbolUpdatedAt": {
            s: now - scanner._TD_TS_TTL + 5 for s in syms},
        "expires": 0,
    }
    monkeypatch.setattr(scanner.requests, "get", lambda *_a, **_k: _Resp({}))

    assert set(scanner._td_timeseries(syms)) == set(syms)
    assert scanner._TD_TS_CACHE[key]["expires"] == now + 5
