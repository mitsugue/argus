"""Hostile source-age tests for cached legacy decision consumers.

These tests deliberately exercise the consumer boundaries rather than the
Entry Scout helpers.  A live cache TTL is receipt metadata only: each consumer
must also validate the provider's own session date before admitting evidence.
"""
from datetime import datetime, timezone

import pytest

import scanner


NOW = datetime(2026, 8, 16, 12, tzinfo=timezone.utc).timestamp()
JP_SYMBOL = "7203"
US_SYMBOL = "AAPL"
CURRENT = "2026-08-14"
CURRENT_JSF = "2026/08/14"


def _history(source_date):
    return {
        "dates": [source_date] + ["2026-08-13"] * 24,
        "closes": [110.0, 108.0, 106.0, 104.0, 102.0, 100.0, 98.0]
        + [98.0] * 18,
        "volumes": [2_000] + [1_000] * 24,
        "highs": [111.0] * 25,
        "lows": [97.0] * 25,
    }


def _margin(source_date=CURRENT, previous_date="2026-08-07"):
    return [
        {"date": source_date, "longVol": 100.0, "shortVol": 200.0},
        {"date": previous_date, "longVol": 90.0, "shortVol": 150.0},
    ]


def _jsf_row():
    return {
        "loan": 60_000,
        "short": 100_000,
        "net": -40_000,
        "loanNew": 100,
        "loanRepay": 100,
        "shortNew": 5_000,
        "shortRepay": 1_000,
    }


def _set_current_caches(monkeypatch):
    monkeypatch.setattr(scanner.time, "time", lambda: NOW)
    monkeypatch.setattr(scanner, "_JQ_MARGIN_CACHE", {
        JP_SYMBOL: {"data": _margin(), "expires": NOW + 60},
    })
    monkeypatch.setattr(scanner, "_JSF_CACHE", {
        "table": {JP_SYMBOL: _jsf_row()},
        "date": CURRENT_JSF,
        "expires": NOW + 60,
    })
    monkeypatch.setattr(scanner, "_JQ_HISTORY_CACHE", {
        JP_SYMBOL: {"data": _history(CURRENT), "expires": NOW + 60},
    })
    monkeypatch.setattr(scanner, "_US_HISTORY_CACHE", {
        US_SYMBOL: {"data": _history(CURRENT), "expires": NOW + 60},
    })


def _capture_supply_demand(monkeypatch, symbol, market):
    captured = {}
    monkeypatch.setattr(scanner, "_flow_evidence_for", lambda *_a: {})
    monkeypatch.setattr(scanner, "_quote_cached_only", lambda *_a: None)

    def classify(_symbol, _market, evidence, _now_iso):
        captured.update(evidence)
        return evidence

    monkeypatch.setattr(scanner.argus_supply_demand, "classify", classify)
    scanner._supply_demand_signal_for(symbol, market)
    return captured


def _is_missing(evidence, *keys):
    return all(key not in evidence or evidence[key] is None for key in keys)


@pytest.mark.parametrize(
    ("source", "missing_keys"),
    [
        ("margin", ("marginBuying", "marginSelling", "marginBuyingPrev",
                    "marginSellingPrev", "marginDate")),
        ("jsf", ("jsfLoan", "jsfLending", "jsfDate")),
        ("history", ("avgDailyVolume",)),
    ],
)
def test_supply_demand_jp_rejects_expired_provider_cache(
        monkeypatch, source, missing_keys):
    _set_current_caches(monkeypatch)
    if source == "margin":
        scanner._JQ_MARGIN_CACHE[JP_SYMBOL]["expires"] = NOW
    elif source == "jsf":
        scanner._JSF_CACHE["expires"] = NOW
    else:
        scanner._JQ_HISTORY_CACHE[JP_SYMBOL]["expires"] = NOW

    evidence = _capture_supply_demand(monkeypatch, JP_SYMBOL, "JP")
    assert _is_missing(evidence, *missing_keys)


@pytest.mark.parametrize(
    "source_date",
    [None, "2026-8-14", "2026-08-17", "2026-08-15", "2026-07-31"],
    ids=["missing", "malformed", "future", "non-session", "stale"],
)
def test_supply_demand_jp_rejects_hostile_margin_dates(
        monkeypatch, source_date):
    _set_current_caches(monkeypatch)
    scanner._JQ_MARGIN_CACHE[JP_SYMBOL]["data"] = _margin(source_date)

    evidence = _capture_supply_demand(monkeypatch, JP_SYMBOL, "JP")
    assert _is_missing(
        evidence, "marginBuying", "marginSelling", "marginBuyingPrev",
        "marginSellingPrev", "marginDate")


@pytest.mark.parametrize(
    "source_date",
    [None, "2026/8/14", "2026/08/17", "2026/08/15", "2026/08/07"],
    ids=["missing", "malformed", "future", "non-session", "stale"],
)
def test_supply_demand_jp_rejects_hostile_jsf_dates(
        monkeypatch, source_date):
    _set_current_caches(monkeypatch)
    scanner._JSF_CACHE["date"] = source_date

    evidence = _capture_supply_demand(monkeypatch, JP_SYMBOL, "JP")
    assert _is_missing(evidence, "jsfLoan", "jsfLending", "jsfDate")


@pytest.mark.parametrize(
    "source_date",
    [None, "2026-8-14", "2026-08-17", "2026-08-15", "2026-08-07"],
    ids=["missing", "malformed", "future", "non-session", "stale"],
)
def test_supply_demand_jp_rejects_hostile_history_dates(
        monkeypatch, source_date):
    _set_current_caches(monkeypatch)
    scanner._JQ_HISTORY_CACHE[JP_SYMBOL]["data"] = _history(source_date)

    evidence = _capture_supply_demand(monkeypatch, JP_SYMBOL, "JP")
    assert _is_missing(evidence, "avgDailyVolume")


@pytest.mark.parametrize(
    ("source_date", "expires"),
    [
        (CURRENT, NOW),
        (None, NOW + 60),
        ("2026-8-14", NOW + 60),
        ("2026-08-17", NOW + 60),
        ("2026-08-15", NOW + 60),
        ("2026-08-07", NOW + 60),
    ],
    ids=["expired", "missing", "malformed", "future", "non-session", "stale"],
)
def test_supply_demand_us_rejects_expired_or_hostile_history(
        monkeypatch, source_date, expires):
    _set_current_caches(monkeypatch)
    scanner._US_HISTORY_CACHE[US_SYMBOL] = {
        "data": _history(source_date), "expires": expires,
    }

    evidence = _capture_supply_demand(monkeypatch, US_SYMBOL, "US")
    assert _is_missing(evidence, "avgDailyVolume", "priorRunupPct")


def test_supply_demand_admits_only_current_live_provider_evidence(monkeypatch):
    _set_current_caches(monkeypatch)

    jp = _capture_supply_demand(monkeypatch, JP_SYMBOL, "JP")
    assert jp["marginBuying"] == 100.0
    assert jp["marginBuyingPrev"] == 90.0
    assert jp["jsfLoan"] == 60_000
    assert jp["marginDate"] == CURRENT
    assert jp["jsfDate"] == CURRENT_JSF
    assert jp["avgDailyVolume"] == 1_000

    us = _capture_supply_demand(monkeypatch, US_SYMBOL, "US")
    assert us["avgDailyVolume"] == 1_000
    assert us["priorRunupPct"] is not None


def _quiet_mover_dependencies(monkeypatch):
    monkeypatch.setattr(scanner, "_tdnet_recent_cached_only", lambda: None)
    monkeypatch.setattr(scanner, "_official_events_restore_once", lambda: None)
    monkeypatch.setattr(scanner, "_official_events_by_symbol", lambda _sym: [])
    monkeypatch.setattr(scanner, "_CAT_CACHE", {})
    monkeypatch.setattr(scanner, "_INTEL_STORE", [])
    monkeypatch.setattr(scanner, "_DOWNSIDE_THEMES", {})
    monkeypatch.setattr(scanner, "_macro_analysis_restore_once", lambda: None)
    monkeypatch.setattr(scanner, "_MOVER_MACRO_VIEW", lambda: [])
    monkeypatch.setattr(scanner, "_REGIME_CACHE", {})


@pytest.mark.parametrize(
    ("source_date", "expires"),
    [
        (CURRENT, NOW),
        (None, NOW + 60),
        ("2026-8-14", NOW + 60),
        ("2026-08-17", NOW + 60),
        ("2026-08-15", NOW + 60),
        ("2026-07-31", NOW + 60),
    ],
    ids=["expired", "missing", "malformed", "future", "non-session", "stale"],
)
def test_mover_cause_rejects_expired_or_hostile_jq_margin(
        monkeypatch, source_date, expires):
    _set_current_caches(monkeypatch)
    _quiet_mover_dependencies(monkeypatch)
    scanner._JQ_MARGIN_CACHE[JP_SYMBOL] = {
        "data": _margin(source_date), "expires": expires,
    }

    evidence = scanner._build_mover_cause_inputs(
        JP_SYMBOL, "JP", -5.0, cached_only=True, caos_lead={})
    assert "margin" not in evidence


@pytest.mark.parametrize(
    ("source_date", "expires"),
    [
        (CURRENT, NOW),
        (None, NOW + 60),
        ("2026-8-14", NOW + 60),
        ("2026-08-17", NOW + 60),
        ("2026-08-15", NOW + 60),
        ("2026-08-07", NOW + 60),
    ],
    ids=["expired", "missing", "malformed", "future", "non-session", "stale"],
)
def test_mover_cause_rejects_expired_or_hostile_jq_history(
        monkeypatch, source_date, expires):
    _set_current_caches(monkeypatch)
    _quiet_mover_dependencies(monkeypatch)
    scanner._JQ_HISTORY_CACHE[JP_SYMBOL] = {
        "data": _history(source_date), "expires": expires,
    }

    evidence = scanner._build_mover_cause_inputs(
        JP_SYMBOL, "JP", -5.0, cached_only=True, caos_lead={})
    assert "technical" not in evidence
    assert evidence["coverage"]["technicalChecked"] is False


def test_mover_cause_admits_current_live_jq_margin_and_history(monkeypatch):
    _set_current_caches(monkeypatch)
    _quiet_mover_dependencies(monkeypatch)

    evidence = scanner._build_mover_cause_inputs(
        JP_SYMBOL, "JP", -5.0, cached_only=True, caos_lead={})
    assert evidence["margin"] == {"shortHeavy": True}
    assert evidence["technical"]["priorRunupPct"] is not None
    assert evidence["coverage"]["technicalChecked"] is True


@pytest.mark.parametrize(
    ("source_date", "expires"),
    [
        (CURRENT, NOW),
        (None, NOW + 60),
        ("2026-8-14", NOW + 60),
        ("2026-08-17", NOW + 60),
        ("2026-08-15", NOW + 60),
        ("2026-08-07", NOW + 60),
    ],
    ids=["expired", "missing", "malformed", "future", "non-session", "stale"],
)
def test_market_confirmation_rejects_expired_or_hostile_jq_history(
        monkeypatch, source_date, expires):
    _set_current_caches(monkeypatch)
    scanner._JQ_HISTORY_CACHE[JP_SYMBOL] = {
        "data": _history(source_date), "expires": expires,
    }
    monkeypatch.setattr(scanner, "_DOWNSIDE_THEMES", {})
    monkeypatch.setattr(scanner, "_PUSH_HISTORY", {})
    monkeypatch.setattr(scanner, "_quote_cached_only", lambda symbol, _market: {
        "symbol": symbol, "volume": 2_000, "changePct": -1.0,
    })
    monkeypatch.setattr(scanner, "_decision_usable_quote_row", lambda row: row)

    inputs = scanner._market_confirmation_inputs(JP_SYMBOL, "JP", -5.0)
    assert "avgVolume" not in inputs


def test_market_confirmation_admits_current_live_jq_history(monkeypatch):
    _set_current_caches(monkeypatch)
    monkeypatch.setattr(scanner, "_DOWNSIDE_THEMES", {})
    monkeypatch.setattr(scanner, "_PUSH_HISTORY", {})
    monkeypatch.setattr(scanner, "_quote_cached_only", lambda symbol, _market: {
        "symbol": symbol, "volume": 2_000, "changePct": -1.0,
    })
    monkeypatch.setattr(scanner, "_decision_usable_quote_row", lambda row: row)

    inputs = scanner._market_confirmation_inputs(JP_SYMBOL, "JP", -5.0)
    assert inputs["avgVolume"] == 1_000


@pytest.mark.parametrize(
    ("margin_date", "jsf_date", "history_date"),
    [
        ("2026-8-14", CURRENT_JSF, CURRENT),
        (CURRENT, "2026/8/14", CURRENT),
        (CURRENT, CURRENT_JSF, "2026-8-14"),
        ("2026-08-17", "2026/08/17", "2026-08-17"),
        ("2026-08-15", "2026/08/15", "2026-08-15"),
        ("2026-07-31", "2026/08/07", "2026-08-07"),
    ],
    ids=["bad-margin", "bad-jsf", "bad-history", "future", "non-session", "stale"],
)
def test_supply_demand_sources_reports_only_admissible_current_sources(
        monkeypatch, margin_date, jsf_date, history_date):
    _set_current_caches(monkeypatch)
    scanner._JQ_MARGIN_CACHE[JP_SYMBOL]["data"] = _margin(margin_date)
    scanner._JSF_CACHE["date"] = jsf_date
    scanner._JQ_HISTORY_CACHE[JP_SYMBOL]["data"] = _history(history_date)

    result = scanner._supply_demand_sources()
    expected = []
    if margin_date == CURRENT:
        expected.append("jquants-margin-weekly")
    if jsf_date == CURRENT_JSF:
        expected.append("jsf-daily-balance")
    if history_date == CURRENT:
        expected.append("jquants-daily-bars")
    assert result["enabled"] == expected
    assert result["jqMargin"] is (margin_date == CURRENT)
    assert result["jsf"] is (jsf_date == CURRENT_JSF)


def test_supply_demand_sources_rejects_expired_caches_and_accepts_live_current(
        monkeypatch):
    _set_current_caches(monkeypatch)
    current = scanner._supply_demand_sources()
    assert current["enabled"] == [
        "jquants-margin-weekly", "jsf-daily-balance",
        "jquants-daily-bars",
    ]
    assert current["jqMargin"] is True
    assert current["jsf"] is True

    scanner._JQ_MARGIN_CACHE[JP_SYMBOL]["expires"] = NOW
    scanner._JSF_CACHE["expires"] = NOW
    scanner._JQ_HISTORY_CACHE[JP_SYMBOL]["expires"] = NOW
    expired = scanner._supply_demand_sources()
    assert expired["enabled"] == []
    assert expired["jqMargin"] is False
    assert expired["jsf"] is False
