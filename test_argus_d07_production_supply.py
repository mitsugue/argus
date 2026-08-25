"""v13.5.36 — SHO D07 production supply (earnings response evidence).

The pure evaluate_d07 existed but production supplied nothing. These tests
drive the scanner-side supply: PIT knownAt from official DisclosedDate/Time,
first-tradable-session via the canonical calendar (weekday-agnostic),
original-vs-correction separation, conservative classification when timing
or calendar truth is unavailable, and the no-lookahead / non-authority
invariants the owner directive requires.
"""
from datetime import date, datetime, timezone

import pytest

import argus_market_clock as clock
import argus_sho
import scanner


@pytest.fixture(autouse=True)
def _calendar():
    # Canonical week: Mon 2026-08-24 .. Fri 2026-08-28 trading; weekend off;
    # Monday 2026-08-31 an official closure (holiday), Tuesday 09-01 trading.
    days = ["2026-08-24", "2026-08-25", "2026-08-26", "2026-08-27",
            "2026-08-28", "2026-09-01", "2026-09-02", "2026-09-03",
            "2026-09-04"]
    clock.register_canonical_calendar(
        clock.JP_EQUITY, days, start="2026-08-20", end="2026-09-05",
        source="test:d07")
    yield
    clock.clear_canonical_calendar()


def _stmt(code="7203", d="2026-08-25", t="15:00:00", doc="FY", pe="2026-06-30",
          **extra):
    row = {"LocalCode": f"{code}0", "DisclosedDate": d, "DisclosedTime": t,
           "TypeOfDocument": doc, "CurrentPeriodEndDate": pe,
           "EarningsPerShare": 123.4, "NetSales": 1000}
    row.update(extra)
    return row


def _seed(rows, monkeypatch):
    monkeypatch.setitem(scanner._SHO_STATEMENTS_CACHE, "rows", rows)
    monkeypatch.setitem(scanner._SHO_STATEMENTS_CACHE, "source",
                        "jquants_fins_statements")


def test_during_session_disclosure_same_day_with_resolution_flag(monkeypatch):
    _seed([_stmt(t="14:00:00")], monkeypatch)
    event, source = scanner._sho_earnings_event()
    assert source == "jquants_fins_statements"
    assert event["date"] == "2026-08-25"
    assert event["intradayDisclosureDailyResolutionLimited"] is True
    assert event["knownAt"].startswith("2026-08-25T05:00")   # 14:00 JST → UTC


def test_before_open_disclosure_same_day_without_flag(monkeypatch):
    _seed([_stmt(t="08:00:00")], monkeypatch)
    event, _ = scanner._sho_earnings_event()
    assert event["date"] == "2026-08-25"
    assert "intradayDisclosureDailyResolutionLimited" not in event


def test_after_close_disclosure_anchors_next_trading_session(monkeypatch):
    _seed([_stmt(t="16:30:00")], monkeypatch)
    event, _ = scanner._sho_earnings_event()
    assert event["date"] == "2026-08-26"


def test_next_day_holiday_and_weekend_skip_via_canonical_calendar(monkeypatch):
    # Friday after close → Monday 08-31 is an official closure → Tuesday 09-01.
    _seed([_stmt(d="2026-08-28", t="16:00:00")], monkeypatch)
    event, _ = scanner._sho_earnings_event()
    assert event["date"] == "2026-09-01"


def test_date_only_disclosure_is_conservative(monkeypatch):
    _seed([_stmt(t="")], monkeypatch)
    event, _ = scanner._sho_earnings_event()
    assert event["publicationTimePrecision"] == "date_only_conservative"
    assert event["date"] == "2026-08-26"        # never same-day without time
    assert event["knownAt"].startswith("2026-08-25T14:59")  # 23:59 JST → UTC


def test_correction_never_overwrites_the_original_event(monkeypatch):
    original = _stmt(t="15:00:00", EarningsPerShare=123.4)
    corrected = _stmt(d="2026-08-27", t="10:00:00", EarningsPerShare=99.9)
    _seed([corrected, original], monkeypatch)     # order must not matter
    event, _ = scanner._sho_earnings_event()
    assert event["knownAt"].startswith("2026-08-25T06:00")  # original 15:00
    assert event["epsActual"] == 123.4
    assert event["correctionCountWithinWindow"] == 1


def test_duplicate_disclosure_rows_collapse(monkeypatch):
    row = _stmt(t="15:00:00")
    _seed([row, dict(row)], monkeypatch)
    event, _ = scanner._sho_earnings_event()
    assert event["correctionCountWithinWindow"] == 1  # exact dup counted, not doubled
    assert event["epsActual"] == 123.4


def test_calendar_unavailable_yields_no_event(monkeypatch):
    clock.clear_canonical_calendar()
    _seed([_stmt(d="2027-03-02", t="16:00:00")], monkeypatch)
    event, source = scanner._sho_earnings_event()
    assert event is None
    assert source == "first_session_calendar_unavailable"


def test_unrecognized_schema_stays_missing(monkeypatch):
    _seed([{"totally": "different"}], monkeypatch)
    event, source = scanner._sho_earnings_event()
    assert event is None and source == "schema_unrecognized"
    verdict = argus_sho.evaluate_d07(
        cutoff="2026-08-26T12:00:00Z", earnings_event=None)
    assert verdict["status"] == "MISSING"
    assert verdict["missing"] == ["supported_earnings_event"]


def test_no_lookahead_event_invisible_before_disclosure_instant():
    event = {
        "instrumentId": "7203", "date": "2026-08-26",
        "knownAt": "2026-08-25T06:00:00Z",
        "availableFrom": "2026-08-25T06:00:00Z", "epsActual": 123.4,
        "epsEstimate": None,
    }
    before = argus_sho.evaluate_d07(
        cutoff="2026-08-25T05:59:00Z", earnings_event=event)
    assert before["status"] == "MISSING"          # future disclosure invisible
    bars = [{"instrumentId": "7203", "date": d, "open": o, "high": o + 2,
             "low": o - 2, "close": c, "volume": 1000,
             "availableFrom": f"{d}T10:00:00Z"}
            for d, o, c in (("2026-08-24", 100.0, 101.0),
                            ("2026-08-25", 101.0, 102.0),
                            ("2026-08-26", 104.0, 105.0),
                            ("2026-08-27", 106.0, 107.0),
                            ("2026-08-28", 106.0, 108.0),
                            ("2026-09-01", 108.0, 110.0))]
    after = argus_sho.evaluate_d07(
        cutoff="2026-09-02T12:00:00Z", earnings_event=event, stock_bars=bars)
    assert after["status"] == "AVAILABLE"
    reaction = after["reaction"]
    assert reaction["gapPct"] == pytest.approx((104.0 / 102.0 - 1) * 100, rel=1e-6)
    assert reaction["return1dPct"] is not None
    # future bars beyond the cutoff never contribute
    early = argus_sho.evaluate_d07(
        cutoff="2026-08-26T23:00:00Z", earnings_event=event, stock_bars=bars)
    assert early["reaction"]["return3dPct"] is None    # 3D not yet knowable


def test_market_relative_reaction_and_consensus_stay_honest():
    event = {"instrumentId": "7203", "date": "2026-08-26",
             "knownAt": "2026-08-25T06:00:00Z",
             "availableFrom": "2026-08-25T06:00:00Z",
             "epsActual": 123.4, "epsEstimate": None}
    mk = lambda base, iid: [
        {"instrumentId": iid, "date": d, "open": base + i, "high": base + i + 2,
         "low": base + i - 2, "close": base + i + 1, "volume": 500,
         "availableFrom": f"{d}T10:00:00Z"}
        for i, d in enumerate(("2026-08-24", "2026-08-25", "2026-08-26",
                               "2026-08-27", "2026-08-28", "2026-09-01",
                               "2026-09-02", "2026-09-03", "2026-09-04"))]
    verdict = argus_sho.evaluate_d07(
        cutoff="2026-09-05T12:00:00Z", earnings_event=event,
        stock_bars=mk(100.0, "7203"), index_bars=mk(200.0, "N225"))
    assert verdict["reaction"]["relativeToIndex5dPct"] is not None
    assert verdict["supportedBeatMiss"] is None       # no consensus dataset
    assert "sector_reaction" in verdict["missing"]    # no canonical sector


def test_d07_missing_is_unknown_and_never_a_final_action():
    verdict = argus_sho.evaluate_d07(cutoff="2026-08-26T12:00:00Z")
    assert verdict["status"] == "MISSING"
    assert verdict["validationStatus"] == "UNVALIDATED"
    serialized = str(verdict)
    for order in ("BUY", "HOLD", "WAIT", "REDUCE", "EXIT"):
        assert f"'{order}'" not in serialized
    assert verdict["lineage"] == "SHO_ORIGINAL"
