"""ETF daily-close cache + merge-fallback (v10.134): a flaky Twelve Data refresh
must NOT drop coverage to partial — serve last-good / merge instead."""
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
