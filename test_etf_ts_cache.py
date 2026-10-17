"""ETF cache preserves fresh rows without renewing absent/stale symbols."""
import scanner


class _Resp:
    def __init__(self, body): self._b = body
    def raise_for_status(self): pass
    def json(self): return self._b


def _latest_us_session_day():
    return scanner.argus_market_clock.latest_completed_session_date(
        scanner.argus_market_clock.US_EQUITY,
        scanner.datetime.fromtimestamp(
            scanner.time.time(), scanner.pytz.utc)).isoformat()


def _full_body(syms, source_day=None):
    source_day = source_day or _latest_us_session_day()
    return {s: {"status": "ok", "values": [
        {"close": "100", "datetime": source_day},
        {"close": "99", "datetime": source_day},
    ]} for s in syms}


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
        "symbolSourceTimestamp": {
            s: _latest_us_session_day() for s in syms},
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
        "symbolSourceTimestamp": {
            s: _latest_us_session_day() for s in syms},
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
        "symbolSourceTimestamp": {
            s: _latest_us_session_day() for s in syms},
        "symbolUpdatedAt": {
            s: now - scanner._TD_TS_TTL + 5 for s in syms},
        "expires": 0,
    }
    monkeypatch.setattr(scanner.requests, "get", lambda *_a, **_k: _Resp({}))

    assert set(scanner._td_timeseries(syms)) == set(syms)
    assert scanner._TD_TS_CACHE[key]["expires"] == now + 5


def test_regime_full_history_requires_every_symbol_and_twenty_prior_bars(
        monkeypatch):
    now = 1_800_000_000.0
    monkeypatch.setattr(scanner.time, "time", lambda: now)
    symbols = ["SPY", "QQQ"]
    source_day = scanner.datetime.fromtimestamp(
        now - 86400, scanner.pytz.utc).strftime("%Y-%m-%d")
    scanner._ETF_LAST_PRICE.clear()
    scanner._ETF_LAST_PRICE.update({
        symbol: {"sourceTimestamp": source_day} for symbol in symbols})

    partial_symbols = scanner._regime_etf_coverage(
        {"SPY": [100.0] * 21}, symbols, now_epoch=now)
    assert partial_symbols["historyCompleteness"] == "partial"
    assert partial_symbols["completeSymbolCount"] == 1
    assert partial_symbols["fullPredicateSatisfied"] is False

    short_history = scanner._regime_etf_coverage(
        {symbol: [100.0, 99.0] for symbol in symbols}, symbols,
        now_epoch=now)
    assert short_history["historyCompleteness"] == "partial"
    assert short_history["completeSymbolCount"] == 0
    assert short_history["fullPredicateSatisfied"] is False

    complete = scanner._regime_etf_coverage(
        {symbol: [100.0] * 21 for symbol in symbols}, symbols,
        now_epoch=now)
    assert complete["historyCompleteness"] == "complete"
    assert complete["freshness"] == "delayed"  # daily source time is never LIVE
    assert complete["fullPredicateSatisfied"] is True
    assert all(row["decisionUsable"] for row in complete["rows"])


def test_one_stale_etf_source_limits_aggregate_freshness(monkeypatch):
    now = 1_800_000_000.0
    monkeypatch.setattr(scanner.time, "time", lambda: now)
    fresh_day = scanner.datetime.fromtimestamp(
        now - 86400, scanner.pytz.utc).strftime("%Y-%m-%d")
    stale_day = scanner.datetime.fromtimestamp(
        now - 10 * 86400, scanner.pytz.utc).strftime("%Y-%m-%d")
    scanner._ETF_LAST_PRICE.clear()
    scanner._ETF_LAST_PRICE.update({
        "SPY": {"sourceTimestamp": fresh_day},
        "QQQ": {"sourceTimestamp": stale_day},
    })
    coverage = scanner._regime_etf_coverage(
        {"SPY": [100.0] * 21, "QQQ": [100.0] * 21},
        ["SPY", "QQQ"], now_epoch=now)
    assert coverage["historyCompleteness"] == "complete"
    assert coverage["freshness"] == "stale"
    assert coverage["fullPredicateSatisfied"] is False
    assert coverage["decisionUsableSymbolCount"] == 1
    assert next(row for row in coverage["rows"]
                if row["symbol"] == "QQQ")["decisionUsable"] is False


def test_regime_last_good_never_restores_full_truth_after_weakest_etf_stales(
        monkeypatch):
    now = [1_800_000_000.0]
    monkeypatch.setattr(scanner.time, "time", lambda: now[0])
    monkeypatch.setattr(scanner, "_REGIME_CACHE", {
        "data": None, "expires": 0.0})
    monkeypatch.setattr(scanner, "_REGIME_LAST_GOOD", {
        "data": None, "ts": 0.0})
    monkeypatch.setattr(scanner, "_ETF_LAST_PRICE", {})

    series = {symbol: [100.0] * scanner._REGIME_ETF_REQUIRED_BARS
              for symbol in scanner._REGIME_ETFS}
    series_calls = []
    def get_series(_symbols):
        series_calls.append(now[0])
        return series
    monkeypatch.setattr(scanner, "_etf_series_with_moomoo", get_series)
    monkeypatch.setattr(scanner, "get_rates_snapshot", lambda: {
        "status": "live",
        "us10y": {"latestValue": 4.0, "change": 0.0},
        "us2y": {"latestValue": 3.8},
        "usReal10y": {"latestValue": 2.0},
        "vix": {"latestValue": 15.0},
    })
    monkeypatch.setattr(
        scanner, "get_events_snapshot", lambda: {"events": []})
    monkeypatch.setattr(scanner, "get_japan_watchlist_snapshot", lambda: {
        "status": "mock", "stocks": []})
    monkeypatch.setattr(scanner, "fetch_fred_series", lambda _series_id: {
        "status": "live", "latestValue": 3.0, "change": 0.0})
    monkeypatch.setattr(scanner, "_jp_sector_rotation", lambda: [])

    # HYG starts just inside the seven-day decision-usable boundary; all other
    # required members have recent independent source timestamps.
    scanner._ETF_LAST_PRICE.update({
        symbol: {"sourceTimestamp": now[0] - 60}
        for symbol in scanner._REGIME_ETFS})
    scanner._ETF_LAST_PRICE["HYG"]["sourceTimestamp"] = (
        now[0] - 7 * 86400 + 60)
    full = scanner.get_market_regime_snapshot()
    assert full["etfCoverage"]["fullPredicateSatisfied"] is True
    assert full["etfCoverage"]["decisionUsableSymbolCount"] == len(
        scanner._REGIME_ETFS)
    assert full["labelStability"]["state"] == "CURRENT"
    # The aggregate 45-minute cache is capped by HYG's independent one-minute
    # evidence lifetime, without a caller having to expire it manually.
    assert now[0] < scanner._REGIME_CACHE["expires"] <= now[0] + 60

    # Two minutes later HYG has crossed the source-age boundary.  Refresh the
    # other members.  The evidence deadline itself must force recomputation.
    now[0] += 120
    for symbol in scanner._REGIME_ETFS:
        if symbol != "HYG":
            scanner._ETF_LAST_PRICE[symbol]["sourceTimestamp"] = now[0] - 60
    degraded = scanner.get_market_regime_snapshot()
    assert len(series_calls) == 2

    assert degraded["etfCoverage"]["historyCompleteness"] == "complete"
    assert degraded["etfCoverage"]["fullPredicateSatisfied"] is False
    assert degraded["etfCoverage"]["freshness"] == "stale"
    assert degraded["etfCoverage"]["decisionUsableSymbolCount"] == len(
        scanner._REGIME_ETFS) - 1
    hyg = next(row for row in degraded["etfCoverage"]["rows"]
               if row["symbol"] == "HYG")
    assert hyg["freshness"] == "stale"
    assert hyg["decisionUsable"] is False
    assert hyg["sourceAgeSec"] > 7 * 86400

    # Consumer-facing current truth remains degraded.  The prior label survives
    # only as an explicitly non-authoritative reference, never as held payload.
    assert degraded["status"] == "partial"
    assert degraded["sourceStatuses"]["twelveData"] == "partial"
    assert next(group for group in degraded["rotationGroups"]
                if group["id"] == "credit")["available"] is False
    assert not any("ハイイールド(HYG)" in item
                   for item in degraded["supportingEvidence"])
    assert "heldOverMin" not in degraded
    assert degraded["labelStability"] == {
        "state": "LAST_GOOD_REFERENCE_AVAILABLE",
        "authoritativeLabelSource": "current_refresh",
        "lastGoodLabel": full["regime"]["label"],
        "lastGoodAsOf": full["asOf"],
        "lastGoodAgeMin": 2,
    }


def test_regime_cache_expires_when_canonical_rate_crosses_fresh_boundary(
        monkeypatch):
    now = [1_800_000_000.0]
    monkeypatch.setattr(scanner.time, "time", lambda: now[0])
    monkeypatch.setattr(scanner, "_REGIME_CACHE", {
        "data": None, "expires": 0.0})
    monkeypatch.setattr(scanner, "_REGIME_LAST_GOOD", {
        "data": None, "ts": 0.0})
    monkeypatch.setattr(scanner, "_ETF_LAST_PRICE", {})

    series = {symbol: [100.0] * scanner._REGIME_ETF_REQUIRED_BARS
              for symbol in scanner._REGIME_ETFS}
    scanner._ETF_LAST_PRICE.update({
        symbol: {"sourceTimestamp": now[0] - 60}
        for symbol in scanner._REGIME_ETFS})
    monkeypatch.setattr(
        scanner, "_etf_series_with_moomoo", lambda _symbols: series)
    monkeypatch.setattr(
        scanner, "get_events_snapshot", lambda: {"events": []})
    monkeypatch.setattr(scanner, "get_japan_watchlist_snapshot", lambda: {
        "status": "mock", "stocks": []})
    monkeypatch.setattr(scanner, "fetch_fred_series", lambda _series_id: {
        "status": "live", "latestValue": 3.0, "change": 0.0})
    monkeypatch.setattr(scanner, "_jp_sector_rotation", lambda: [])

    observed = now[0] - scanner._RATE_EXACT_FRESH_SEC + 60
    calls = []
    def rates_snapshot():
        calls.append(now[0])
        freshness = ("FRESH" if now[0] - observed <=
                     scanner._RATE_EXACT_FRESH_SEC else "DELAYED")
        status = "live" if freshness == "FRESH" else "partial"
        def row(value):
            observed_at = scanner.datetime.fromtimestamp(
                observed, scanner.pytz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            return {
                "latestValue": value, "selectedValue": value,
                "change": 0.0, "status": status,
                "observedAt": observed_at, "receivedAt": observed_at,
                "knownAt": observed_at, "freshness": freshness,
                "completeness": "COMPLETE", "selectedProvider": "yahoo",
                "selectedObservationId": "obs-rate",
                "providerSelectionPolicyId": "market-truth-authority-v1",
                "selectionReason": "freshest exact observation",
                "providerCandidates": [], "providerAlternates": [],
                "providerDisagreement": {},
            }
        return {
            "status": status, "freshness": freshness,
            "completeness": "COMPLETE", "missingSeries": [],
            "us10y": row(4.0), "us2y": row(3.8),
            "usReal10y": row(2.0), "vix": row(15.0),
            "usdJpy": row(150.0),
        }
    monkeypatch.setattr(scanner, "get_rates_snapshot", rates_snapshot)

    first = scanner.get_market_regime_snapshot()
    assert first["ratesBackdrop"]["rateTruthEvidence"]["series"][
        "us10y"]["freshness"] == "FRESH"
    assert now[0] < scanner._REGIME_CACHE["expires"] <= now[0] + 60

    # Do not mutate aggregate cache state.  Its evidence cap forces a refresh
    # and the same observation is reclassified once it crosses twenty minutes.
    now[0] += 120
    second = scanner.get_market_regime_snapshot()
    assert len(calls) == 2
    assert second["ratesBackdrop"]["rateTruthEvidence"]["series"][
        "us10y"]["freshness"] == "DELAYED"


# ── v13.5.36 compatibility: these legacy fixtures predate the canonical-
# calendar authority (weekday-agnostic daily sessions). Register a wide
# synthetic Mon-Fri canonical range so their historical/frozen dates keep the
# session semantics they were written under; production stays strict.
import pytest as _pytest
import argus_market_clock as _clock
from datetime import date as _date, timedelta as _timedelta


@_pytest.fixture(autouse=True)
def _legacy_wide_canonical_calendar():
    days = []
    cursor = _date(2020, 1, 1)
    while cursor <= _date(2030, 12, 31):
        if cursor.weekday() < 5:
            days.append(cursor.isoformat())
        cursor += _timedelta(days=1)
    for market in (_clock.JP_EQUITY, _clock.US_EQUITY, _clock.VIX_MKT):
        _clock.register_canonical_calendar(
            market, days, start="2020-01-01", end="2030-12-31",
            source="test:legacy-weekday-world")
    yield
    _clock.clear_canonical_calendar()
