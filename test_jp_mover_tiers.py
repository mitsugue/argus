"""JP mover provider authority and source-time fail-closed contracts."""

from datetime import date, datetime, timezone

import pytest

import scanner


_LATEST_COMPLETED_JP_SESSION = date(2026, 8, 17)
_PREVIOUS_COMPLETED_JP_SESSION = date(2026, 8, 14)


def _capture(monkeypatch):
    """Capture what _record_event is asked to record."""
    recorded = []

    def fake_record(market, symbol, trig, now, session,
                    bucket_minutes=1440, source=None, **_kwargs):
        recorded.append({"market": market, "symbol": symbol,
                         "session": session, "source": source})
        return {"symbol": symbol}

    monkeypatch.setattr(scanner, "_record_event", fake_record)
    monkeypatch.setattr(scanner, "_EVENT_BACKBONE_ENABLED", True)
    monkeypatch.setattr(scanner, "_MARKET_MOVER_NOTIFY_MAX", 10)
    monkeypatch.setattr(
        scanner.argus_events, "detect_market_mover",
        lambda sym, chg, price, **_kwargs: [
            {"type": "MARKET_MOVER", "severity": 4}])
    return recorded


def _freeze_latest_completed_jp_session(monkeypatch):
    calls = []

    def latest_completed(market, now_utc=None):
        calls.append((market, now_utc))
        return _LATEST_COMPLETED_JP_SESSION

    monkeypatch.setattr(
        scanner.argus_market_clock, "latest_completed_session_date",
        latest_completed)
    return calls


def _jq_row(source_timestamp, *, symbol="1234"):
    return {
        "symbol": symbol,
        "name": symbol,
        "price": 500.0,
        "changePct": 12.0,
        "sourceTimestamp": source_timestamp,
        "sourceTimeStatus": "DATE_ONLY_EOD",
        "freshness": "DELAYED",
        "completeness": "COMPLETE",
        "decisionUsable": True,
    }


def _jq_envelope(as_of, *, row_source_timestamp=None, status="delayed"):
    if row_source_timestamp is None:
        row_source_timestamp = as_of
    return {
        "status": status,
        "asOf": as_of,
        "expectedCompletedSession": _LATEST_COMPLETED_JP_SESSION.isoformat(),
        "sourceTimestamp": as_of,
        "sourceTimeStatus": "DATE_ONLY_EOD",
        "freshness": "DELAYED",
        "completeness": "COMPLETE",
        "gainers": [_jq_row(row_source_timestamp)],
        "losers": [],
    }


def test_jp_mover_push_requires_current_per_row_source_time_for_authority(
        monkeypatch):
    now = 1_800_000_000.0
    monkeypatch.setattr(scanner.time, "time", lambda: now)
    monkeypatch.setattr(scanner, "_require_admin", lambda: (True, None, 200))
    monkeypatch.setattr(
        scanner, "_verify_bridge_signature", lambda _raw: (True, "verified"))
    monkeypatch.setattr(scanner, "_MOOMOO_JP_MOVERS", {
        "rows": [], "ts": 0.0, "asOf": None})
    payload = {"movers": [
        {"symbol": "6758", "price": 100.0, "changePct": 14.0},
        {"symbol": "9984", "price": 101.0, "changePct": 14.0,
         "exchangeTs": now + 1},
        {"symbol": "8035", "price": 102.0, "changePct": 14.0,
         "exchangeTs": now - 3600},
        {"symbol": "7203", "price": 103.0, "changePct": 14.0,
         "exchangeTs": now - 30},
    ], "asOf": now}
    with scanner.app.test_client() as client:
        response = client.post("/api/argus/jp-movers-push", json=payload)
    assert response.status_code == 200
    assert response.get_json()["accepted"] == 4
    authoritative = scanner._moomoo_jp_movers()
    assert [row["symbol"] for row in authoritative] == ["7203"]
    stored = {row["symbol"]: row
              for row in scanner._MOOMOO_JP_MOVERS["rows"]}
    assert stored["6758"]["sourceTimeStatus"] == "MISSING"
    assert stored["9984"]["timestampInversion"] is True
    assert stored["8035"]["ageSec"] == 3600

    recorded = _capture(monkeypatch)
    monkeypatch.setattr(scanner, "_jp_market_open", lambda *a, **k: True)
    monkeypatch.setattr(
        scanner, "_yahoo_jp_movers",
        lambda: {"status": "unavailable", "gainers": [], "losers": []})
    assert scanner._scan_jp_market_movers() == 1
    assert [(row["market"], row["symbol"]) for row in recorded] == [
        ("JP", "7203")]


def test_yahoo_ranking_without_provider_timestamp_is_diagnostic_only(
        monkeypatch):
    monkeypatch.setattr(scanner, "_YAHOO_MOVERS_CACHE", {
        "data": None, "expires": 0.0})
    ranking = {
        "up": [{"symbol": "7203", "name": "Toyota", "price": 3000.0,
                "changePct": 10.0}],
        "down": [{"symbol": "6758", "name": "Sony", "price": 3500.0,
                  "changePct": -10.0}],
    }
    monkeypatch.setattr(
        scanner, "_yahoo_rank", lambda direction: ranking[direction])

    result = scanner._yahoo_jp_movers()

    assert result["status"] == "partial"
    assert result["dataAsOf"] is None
    assert result["sourceTimeStatus"] == "MISSING"
    assert result["freshness"] == "UNKNOWN"
    assert result["completeness"] == "PARTIAL"
    assert result["decisionUsable"] is False
    for row in result["gainers"] + result["losers"]:
        assert row["sourceTimestamp"] is None
        assert row["sourceTimeStatus"] == "MISSING"
        assert row["freshness"] == "UNKNOWN"
        assert row["completeness"] == "PARTIAL"
        assert row["decisionUsable"] is False


@pytest.mark.parametrize(
    "claimed_source_timestamp",
    [None, 1_800_000_001.0, 1_799_996_400.0],
    ids=["missing", "future", "stale"],
)
def test_open_scan_never_promotes_yahoo_claims_without_real_source_time(
        monkeypatch, claimed_source_timestamp):
    recorded = _capture(monkeypatch)
    monkeypatch.setattr(scanner, "_jp_market_open", lambda *a, **k: True)
    monkeypatch.setattr(scanner, "_moomoo_jp_movers", lambda: [])
    monkeypatch.setattr(scanner, "_yahoo_jp_movers", lambda: {
        "status": "live",
        "asOf": claimed_source_timestamp,
        "dataAsOf": claimed_source_timestamp,
        "sourceTimeStatus": "VALID",
        "freshness": "LIVE",
        "completeness": "COMPLETE",
        "decisionUsable": True,
        "gainers": [{
            "symbol": "9999", "price": 500.0, "changePct": 20.0,
            "sourceTimestamp": claimed_source_timestamp,
            "sourceTimeStatus": "VALID", "freshness": "LIVE",
            "completeness": "COMPLETE", "decisionUsable": True,
        }],
        "losers": [],
    })

    assert scanner._scan_jp_market_movers() == 0
    assert recorded == []


def test_open_scan_uses_source_timed_moomoo_and_keeps_yahoo_diagnostic(
        monkeypatch):
    recorded = _capture(monkeypatch)
    monkeypatch.setattr(scanner, "_jp_market_open", lambda *a, **k: True)
    monkeypatch.setattr(scanner, "_moomoo_jp_movers", lambda: [{
        "symbol": "7203", "changePct": 12.0, "price": 3000.0,
        "sourceTimestamp": 1_800_000_000.0,
        "sourceTimeStatus": "VALID", "decisionUsable": True,
    }])
    monkeypatch.setattr(scanner, "_yahoo_jp_movers", lambda: {
        "status": "partial", "dataAsOf": None,
        "gainers": [{
            "symbol": "9999", "changePct": 20.0, "price": 500.0,
            "sourceTimestamp": None, "decisionUsable": False,
        }],
        "losers": [],
    })

    assert scanner._scan_jp_market_movers() == 1
    assert recorded == [{
        "market": "JP", "symbol": "7203", "session": "JP_RT",
        "source": "moomoo-rt",
    }]


def test_candidate_mover_universe_never_reads_yahoo_rankings(monkeypatch):
    monkeypatch.setattr(
        scanner, "_yahoo_jp_movers",
        lambda: (_ for _ in ()).throw(
            AssertionError("Yahoo ranking is diagnostic-only")))
    monkeypatch.setattr(scanner, "_jq_market_movers", lambda: {
        "status": "unavailable", "gainers": [], "losers": []})
    monkeypatch.setattr(scanner, "_moomoo_us_movers", lambda: [])

    assert scanner._mover_universe() == []


def test_jquants_requests_and_labels_exact_latest_completed_session(
        monkeypatch):
    clock_calls = _freeze_latest_completed_jp_session(monkeypatch)
    now = datetime(2026, 8, 17, 8, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(scanner.time, "time", lambda: now.timestamp())
    monkeypatch.setattr(scanner, "_JQUANTS_API_KEY", "test-key")
    monkeypatch.setattr(scanner, "_JP_MOVERS_CACHE", {
        "data": None, "expires": 0.0})
    monkeypatch.setattr(scanner, "_jq_name_for", lambda symbol: symbol)
    requested_dates = []

    def all_for_date(date_str, _headers, max_pages=40):
        requested_dates.append(date_str)
        if date_str == _LATEST_COMPLETED_JP_SESSION.isoformat():
            return {"1234": {
                "Code": "1234", "Date": date_str, "C": 550.0}}
        if date_str == _PREVIOUS_COMPLETED_JP_SESSION.isoformat():
            return {"1234": {
                "Code": "1234", "Date": date_str, "C": 500.0}}
        return {}

    monkeypatch.setattr(scanner, "_jq_all_for_date", all_for_date)

    result = scanner._jq_market_movers()

    assert clock_calls
    assert clock_calls[0][0] == scanner.argus_market_clock.JP_EQUITY
    assert clock_calls[0][1].tzinfo is not None
    assert requested_dates == [
        _LATEST_COMPLETED_JP_SESSION.isoformat(),
        _PREVIOUS_COMPLETED_JP_SESSION.isoformat(),
    ]
    assert result["status"] == "delayed"
    assert result["asOf"] == _LATEST_COMPLETED_JP_SESSION.isoformat()
    assert result["expectedCompletedSession"] == result["asOf"]
    assert result["sourceTimestamp"] == result["asOf"]
    assert result["sourceTimeStatus"] == "DATE_ONLY_EOD"
    assert result["freshness"] == "DELAYED"
    assert result["completeness"] == "COMPLETE"
    assert result["gainers"]
    assert all(row["sourceTimestamp"] == result["asOf"]
               and row["decisionUsable"] is True
               for row in result["gainers"] + result["losers"])


@pytest.mark.parametrize(
    "provider_row_date",
    ["2026-08-10", "2026-08-16", "2026-08-18", None],
    ids=["seven-days-old", "non-session", "future", "missing"],
)
def test_jquants_rejects_latest_rows_without_exact_provider_date(
        monkeypatch, provider_row_date):
    _freeze_latest_completed_jp_session(monkeypatch)
    now = datetime(2026, 8, 17, 8, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(scanner.time, "time", lambda: now.timestamp())
    monkeypatch.setattr(scanner, "_JQUANTS_API_KEY", "test-key")
    monkeypatch.setattr(scanner, "_JP_MOVERS_CACHE", {
        "data": None, "expires": 0.0})

    def all_for_date(date_str, _headers, max_pages=40):
        if date_str == _LATEST_COMPLETED_JP_SESSION.isoformat():
            row = {"Code": "1234", "C": 550.0}
            if provider_row_date is not None:
                row["Date"] = provider_row_date
            return {"1234": row}
        if date_str == _PREVIOUS_COMPLETED_JP_SESSION.isoformat():
            return {"1234": {
                "Code": "1234", "Date": date_str, "C": 500.0}}
        return {}

    monkeypatch.setattr(scanner, "_jq_all_for_date", all_for_date)

    result = scanner._jq_market_movers()

    assert result["status"] != "delayed"
    assert result["gainers"] == []
    assert result["losers"] == []


def test_jquants_missing_latest_session_does_not_backfill_old_data(monkeypatch):
    _freeze_latest_completed_jp_session(monkeypatch)
    now = datetime(2026, 8, 17, 8, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(scanner.time, "time", lambda: now.timestamp())
    monkeypatch.setattr(scanner, "_JQUANTS_API_KEY", "test-key")
    monkeypatch.setattr(scanner, "_JP_MOVERS_CACHE", {
        "data": None, "expires": 0.0})
    requested_dates = []

    def all_for_date(date_str, _headers, max_pages=40):
        requested_dates.append(date_str)
        if date_str == _PREVIOUS_COMPLETED_JP_SESSION.isoformat():
            return {"1234": {
                "Code": "1234", "Date": date_str, "C": 500.0}}
        return {}

    monkeypatch.setattr(scanner, "_jq_all_for_date", all_for_date)

    result = scanner._jq_market_movers()

    assert requested_dates[0] == _LATEST_COMPLETED_JP_SESSION.isoformat()
    assert result["status"] == "unavailable"
    assert result["asOf"] is None
    assert result["gainers"] == []
    assert result["losers"] == []


def test_closed_scan_and_mover_universe_accept_exact_jquants_session(
        monkeypatch):
    _freeze_latest_completed_jp_session(monkeypatch)
    recorded = _capture(monkeypatch)
    expected = _LATEST_COMPLETED_JP_SESSION.isoformat()
    payload = _jq_envelope(expected)
    monkeypatch.setattr(scanner, "_jp_market_open", lambda *a, **k: False)
    monkeypatch.setattr(scanner, "_moomoo_jp_movers", lambda: [])
    monkeypatch.setattr(scanner, "_jq_market_movers", lambda: payload)
    monkeypatch.setattr(scanner, "_yahoo_jp_movers", lambda: (
        _ for _ in ()).throw(
            AssertionError("Yahoo should not be called when closed")))
    monkeypatch.setattr(scanner, "_moomoo_us_movers", lambda: [])

    assert scanner._scan_jp_market_movers() == 1
    assert recorded == [{
        "market": "JP", "symbol": "1234", "session": "JP_EOD",
        "source": "jquants-eod",
    }]
    assert scanner._mover_universe() == [{
        "symbol": "1234", "name": "1234", "market": "JP",
        "changePct": 12.0,
    }]


@pytest.mark.parametrize(
    "invalid_as_of",
    ["2026-08-10", "2026-08-16", "2026-08-18", None],
    ids=["seven-days-old", "non-session", "future", "missing"],
)
def test_scan_and_mover_universe_reject_noncanonical_jquants_session(
        monkeypatch, invalid_as_of):
    _freeze_latest_completed_jp_session(monkeypatch)
    recorded = _capture(monkeypatch)
    payload = _jq_envelope(invalid_as_of)
    monkeypatch.setattr(scanner, "_jp_market_open", lambda *a, **k: False)
    monkeypatch.setattr(scanner, "_moomoo_jp_movers", lambda: [])
    monkeypatch.setattr(scanner, "_jq_market_movers", lambda: payload)
    monkeypatch.setattr(scanner, "_moomoo_us_movers", lambda: [])

    scan_count = scanner._scan_jp_market_movers()
    universe = scanner._mover_universe()

    assert (scan_count, universe) == (0, [])
    assert recorded == []


@pytest.mark.parametrize(
    "invalid_row_source",
    ["2026-08-10", "2026-08-16", "2026-08-18", None],
    ids=["seven-days-old", "non-session", "future", "missing"],
)
def test_scan_and_mover_universe_require_exact_jquants_row_source_date(
        monkeypatch, invalid_row_source):
    _freeze_latest_completed_jp_session(monkeypatch)
    recorded = _capture(monkeypatch)
    expected = _LATEST_COMPLETED_JP_SESSION.isoformat()
    payload = _jq_envelope(expected, row_source_timestamp=invalid_row_source)
    if invalid_row_source is None:
        payload["gainers"][0]["sourceTimestamp"] = None
    monkeypatch.setattr(scanner, "_jp_market_open", lambda *a, **k: False)
    monkeypatch.setattr(scanner, "_moomoo_jp_movers", lambda: [])
    monkeypatch.setattr(scanner, "_jq_market_movers", lambda: payload)
    monkeypatch.setattr(scanner, "_moomoo_us_movers", lambda: [])

    scan_count = scanner._scan_jp_market_movers()
    universe = scanner._mover_universe()

    assert (scan_count, universe) == (0, [])
    assert recorded == []


@pytest.mark.parametrize("status", ["live", "partial", "unavailable", None])
def test_scan_and_mover_universe_require_delayed_jquants_status(
        monkeypatch, status):
    _freeze_latest_completed_jp_session(monkeypatch)
    recorded = _capture(monkeypatch)
    expected = _LATEST_COMPLETED_JP_SESSION.isoformat()
    payload = _jq_envelope(expected, status=status)
    monkeypatch.setattr(scanner, "_jp_market_open", lambda *a, **k: False)
    monkeypatch.setattr(scanner, "_moomoo_jp_movers", lambda: [])
    monkeypatch.setattr(scanner, "_jq_market_movers", lambda: payload)
    monkeypatch.setattr(scanner, "_moomoo_us_movers", lambda: [])

    scan_count = scanner._scan_jp_market_movers()
    universe = scanner._mover_universe()

    assert (scan_count, universe) == (0, [])
    assert recorded == []


# ── v13.5.35 compatibility: these legacy fixtures predate the canonical-
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
