"""Hostile source-date tests for Entry Scout JP credit evidence."""
from datetime import datetime, timezone

import pytest

import scanner


NOW = datetime(2026, 8, 16, 12, tzinfo=timezone.utc).timestamp()
SYMBOL = "7203"


def _margin_row(source_date, long_vol=100.0, short_vol=200.0):
    return {"date": source_date, "longVol": long_vol,
            "shortVol": short_vol}


def _jsf_row():
    return {"loan": 60_000, "short": 100_000, "net": -40_000,
            "loanNew": 100, "loanRepay": 100,
            "shortNew": 5_000, "shortRepay": 1_000}


def _entry_harness(monkeypatch, *, margin_rows=None, jsf=(None, None),
                   jpx=(None, None)):
    calls = {"jsf_for": 0}
    history = {
        "dates": ["2026-08-14"] * 25,
        "closes": [100.0] * 25,
        "volumes": [1_000] * 25,
        "highs": [101.0] * 25,
        "lows": [99.0] * 25,
    }
    monkeypatch.setattr(scanner.time, "time", lambda: NOW)
    monkeypatch.setattr(scanner, "_SCOUT_CACHE", {})
    monkeypatch.setattr(scanner, "_PUSHED_QUOTES", {"JP": {}})
    monkeypatch.setattr(scanner, "_jq_price_history", lambda _sym: history)
    monkeypatch.setattr(scanner, "_entry_metrics", lambda *_a: {
        "change20dPct": 0.0, "rsi14": 50.0, "volumeRatio": 1.0})
    monkeypatch.setattr(scanner, "get_events_snapshot", lambda: {"events": []})
    monkeypatch.setattr(scanner, "_region_event_escalation", lambda *_a: None)
    monkeypatch.setattr(scanner, "get_rates_snapshot", lambda: {})
    monkeypatch.setattr(scanner, "_rates_posture", lambda _rates: "neutral")
    monkeypatch.setattr(scanner, "_fred_vix_history", lambda: [])
    monkeypatch.setattr(scanner, "_canonical_vix_assess", lambda *_a, **_k: {})
    monkeypatch.setattr(scanner, "get_market_regime_snapshot", lambda: {
        "status": "unavailable"})
    monkeypatch.setattr(scanner, "get_catalysts_snapshot", lambda: {"items": []})
    monkeypatch.setattr(scanner, "_ai_cached_result", lambda: None)
    monkeypatch.setattr(scanner, "_jq_name_for", lambda _sym: "Toyota")
    monkeypatch.setattr(scanner, "_scout_summary", lambda: None)
    monkeypatch.setattr(scanner, "_ledger_summary", lambda: None)
    monkeypatch.setattr(scanner, "get_news_radar", lambda: {})
    monkeypatch.setattr(scanner, "_jq_weekly_margin",
                        lambda _sym: margin_rows)
    monkeypatch.setattr(scanner, "_jsf_balance_table", lambda: jsf)
    monkeypatch.setattr(scanner, "_jpx_short_table", lambda: jpx)

    def jsf_for(_sym):
        calls["jsf_for"] += 1
        row = dict((jsf[0] or {})[_sym])
        row["date"] = jsf[1]
        row["ratio"] = round(row["loan"] / row["short"], 2)
        return row

    monkeypatch.setattr(scanner, "_jsf_for", jsf_for)

    def assess(*_args, **kwargs):
        calls["assess"] = {
            "margin": kwargs.get("margin_sig"),
            "jsf": kwargs.get("jsf_sig"),
            "short": kwargs.get("short_disclosed"),
        }
        return {"score": 0.0, "label": "neutral"}

    def infer(_metrics, _flow, jsf_sig, short_sig):
        calls["inference"] = {"jsf": jsf_sig, "short": short_sig}
        return {"classification": "unknown"}

    def narrative(*args):
        calls["narrative"] = {"jsf": args[3], "short": args[4]}
        return "call", "narrative"

    monkeypatch.setattr(scanner, "_entry_scout_assess", assess)
    monkeypatch.setattr(scanner, "_flow_inference", infer)
    monkeypatch.setattr(scanner, "_scout_narrative", narrative)
    return scanner.get_entry_scout(SYMBOL, "JP"), calls


def test_bounded_market_session_date_is_exact_calendar_aware_and_bounded():
    valid, reason = scanner._bounded_market_session_date(
        "2026-08-14", "JP", 7, accepted_formats=("%Y-%m-%d",),
        now_epoch=NOW)
    assert valid.isoformat() == "2026-08-14"
    assert reason == "current_source_date"

    hostile = {
        None: "malformed_source_date",
        "2026-8-14": "malformed_source_date",
        "2026/08/14": "malformed_source_date",
        "2026-08-14junk": "malformed_source_date",
        "2026-08-15": "non_trading_source_date",  # Saturday
        "2026-08-11": "non_trading_source_date",  # JPX holiday
        "2026-08-17": "future_source_date",
        "2026-08-07": "stale_source_date",
    }
    for raw, expected_reason in hostile.items():
        parsed, actual_reason = scanner._bounded_market_session_date(
            raw, "JP", 7, accepted_formats=("%Y-%m-%d",),
            now_epoch=NOW)
        assert parsed is None
        assert actual_reason == expected_reason

    slash, _ = scanner._bounded_market_session_date(
        "2026/08/14", "JP", 7, accepted_formats=("%Y/%m/%d",),
        now_epoch=NOW)
    assert slash.isoformat() == "2026-08-14"


def test_weekly_margin_requires_two_distinct_recent_exact_session_dates():
    rows, reason = scanner._entry_weekly_margin_evidence([
        _margin_row("2026-08-14"), _margin_row("2026-08-07"),
        _margin_row("2026-07-31")], now_epoch=NOW)
    assert [row["date"] for row in rows] == ["2026-08-14", "2026-08-07"]
    assert reason == "current_source_dates"

    for hostile in (None, "2026/08/14", "2026-08-15",
                    "2026-08-17", "2026-07-01"):
        rows, _ = scanner._entry_weekly_margin_evidence([
            _margin_row(hostile), _margin_row("2026-08-07")],
            now_epoch=NOW)
        assert rows is None


@pytest.mark.parametrize("hostile_date", [
    None, "2026/08/14", "2026-08-15", "2026-08-17", "2026-07-01",
])
def test_hostile_weekly_margin_never_reaches_score_inference_or_narrative(
        monkeypatch, hostile_date):
    result, calls = _entry_harness(monkeypatch, margin_rows=[
        _margin_row(hostile_date), _margin_row("2026-08-07")])
    assert result["margin"] is None
    assert calls["assess"]["margin"] is None
    assert calls["inference"]["jsf"] is None
    assert calls["narrative"]["jsf"] is None


@pytest.mark.parametrize("hostile_date", [
    None, "2026-08-14", "2026/08/15", "2026/08/17", "2026/07/01",
])
def test_hostile_jsf_date_never_reaches_score_inference_or_narrative(
        monkeypatch, hostile_date):
    result, calls = _entry_harness(
        monkeypatch, jsf=({SYMBOL: _jsf_row()}, hostile_date))
    assert result["nisshokin"] is None
    assert result["nisshokinStatus"] == "source_unavailable"
    assert calls["jsf_for"] == 0
    assert calls["assess"]["jsf"] is None
    assert calls["inference"]["jsf"] is None
    assert calls["narrative"]["jsf"] is None


@pytest.mark.parametrize("hostile_date", [
    None, "2026-08-14", "2026/08/15", "2026/08/17", "2026/07/01",
])
def test_hostile_jpx_short_date_never_reaches_score_inference_or_narrative(
        monkeypatch, hostile_date):
    result, calls = _entry_harness(
        monkeypatch, jpx=({SYMBOL: {"ratio": 0.01, "reporters": 2}},
                          hostile_date))
    assert result["shortDisclosed"] is None
    assert result["shortDisclosedStatus"] == "source_unavailable"
    assert calls["assess"]["short"] is None
    assert calls["inference"]["short"] is None
    assert calls["narrative"]["short"] is None


def test_valid_credit_dates_reach_all_consumers_and_cache_is_reaged(monkeypatch):
    result, calls = _entry_harness(
        monkeypatch,
        margin_rows=[_margin_row("2026-08-14"),
                     _margin_row("2026-08-07", 90.0, 150.0)],
        jsf=({SYMBOL: _jsf_row()}, "2026/08/14"),
        jpx=({SYMBOL: {"ratio": 0.01, "reporters": 2}}, "2026/08/14"))
    assert result["margin"] is not None
    assert result["nisshokin"] is not None
    assert result["shortDisclosed"] == {
        "ratioPct": 1.0, "reporters": 2, "date": "2026/08/14"}
    assert all(calls["assess"][key] is not None
               for key in ("margin", "jsf", "short"))
    assert calls["inference"]["jsf"] is not None
    assert calls["inference"]["short"] is not None
    assert calls["narrative"]["jsf"] is not None
    assert calls["narrative"]["short"] is not None

    cache_row = scanner._SCOUT_CACHE[f"JP:{SYMBOL}"]
    assert scanner._entry_cached_credit_dates_usable(
        cache_row, "JP", now_epoch=NOW) is True
    expired_cache_row = dict(cache_row, expires=NOW - 1)
    assert scanner._entry_cached_credit_dates_usable(
        expired_cache_row, "JP", now_epoch=NOW) is False
    assert scanner._entry_cached_credit_dates_usable(
        cache_row, "JP", now_epoch=datetime(
            2026, 9, 1, 12, tzinfo=timezone.utc).timestamp()) is False


def test_absence_inferences_require_current_jsf_and_jpx_file_dates(monkeypatch):
    current_jsf, _ = _entry_harness(
        monkeypatch, jsf=({}, "2026/08/14"))
    assert current_jsf["nisshokin"] is None
    assert current_jsf["nisshokinStatus"] == "not_loanable"
    assert scanner._SCOUT_CACHE[f"JP:{SYMBOL}"]["creditDates"]["jsf"] == \
        "2026/08/14"

    stale_jsf, _ = _entry_harness(
        monkeypatch, jsf=({}, "2026/07/01"))
    assert stale_jsf["nisshokin"] is None
    assert stale_jsf["nisshokinStatus"] == "source_unavailable"

    current, _ = _entry_harness(
        monkeypatch, jpx=({}, "2026/08/14"))
    assert current["shortDisclosed"] is None
    assert current["shortDisclosedStatus"] == "none_disclosed"

    stale, _ = _entry_harness(monkeypatch, jpx=({}, "2026/07/01"))
    assert stale["shortDisclosed"] is None
    assert stale["shortDisclosedStatus"] == "source_unavailable"
