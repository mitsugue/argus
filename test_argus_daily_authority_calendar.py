"""v13.5.36 — weekday-agnostic DAILY/EOD authority (owner directive
2026-08-26).

Invariant: a daily observation is decision-eligible iff it IS the
LATEST_COMPLETED_OFFICIAL_TRADING_SESSION per the canonical trading calendar
(registered J-Quants range > versioned official snapshot). No Friday/Monday/
weekend special cases anywhere in the authority path; when the calendar
cannot answer, authority fails conservatively — weekday arithmetic never
substitutes.
"""
from datetime import date, datetime, timezone

import pytest

import argus_market_clock as clock
import argus_single_decision as sd


JP = clock.JP_EQUITY


def _utc(iso):
    return datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _clean_registry():
    clock.clear_canonical_calendar()
    yield
    clock.clear_canonical_calendar()


def _latest(iso):
    return clock.latest_completed_session_date(JP, _utc(iso)).isoformat()


# ── Static official snapshot (2026) — holidays on real weekdays ────────────

def test_monday_holiday_marine_day():
    # 2026-07-20 (Mon) Marine Day: Monday evening → latest = Friday 07-17.
    assert _latest("2026-07-20T11:00:00Z") == "2026-07-17"


def test_wednesday_holiday_national_foundation_day():
    # 2026-02-11 (Wed): Wednesday evening → latest = Tuesday 02-10.
    assert _latest("2026-02-11T11:00:00Z") == "2026-02-10"


def test_substitute_holiday_furikae():
    # 2026-05-06 (Wed, 振替休日): evening → latest = Friday 05-01
    # (05-04/05 Mon/Tue holidays, 05-02/03 weekend).
    assert _latest("2026-05-06T11:00:00Z") == "2026-05-01"


def test_three_plus_consecutive_closed_days_silver_week():
    # 2026-09-19(Sat)..09-23(Wed) = five consecutive closed days:
    # Wednesday evening → latest = Friday 09-18.
    assert _latest("2026-09-23T11:00:00Z") == "2026-09-18"


def test_golden_week_stretch():
    # 04-29(Wed hol) → latest Tue 04-28; through 05-06 evening → 05-01.
    assert _latest("2026-04-29T11:00:00Z") == "2026-04-28"
    assert _latest("2026-05-05T11:00:00Z") == "2026-05-01"


def test_market_open_today_but_session_not_yet_completed():
    # Wednesday 10:00 JST (01:00Z): today's session incomplete → latest is
    # the PREVIOUS trading day, and at 15:31 JST it flips to today.
    assert _latest("2026-08-26T01:00:00Z") == "2026-08-25"
    assert _latest("2026-08-26T06:31:00Z") == "2026-08-26"


# ── Registered canonical calendar (synthetic; outranks the snapshot) ───────

def _register(days, start, end):
    clock.register_canonical_calendar(JP, days, start=start, end=end,
                                      source="test:synthetic")


def test_tuesday_thursday_friday_holidays_via_canonical_registration():
    # A synthetic week where Tue/Thu/Fri are official closures — the
    # registered canonical calendar decides, weekday identity is irrelevant.
    _register(["2026-06-01", "2026-06-03"],       # Mon, Wed only
              start="2026-06-01", end="2026-06-07")
    assert _latest("2026-06-02T11:00:00Z") == "2026-06-01"   # Tue holiday
    assert _latest("2026-06-04T11:00:00Z") == "2026-06-03"   # Thu holiday
    assert _latest("2026-06-05T11:00:00Z") == "2026-06-03"   # Fri holiday
    assert _latest("2026-06-07T11:00:00Z") == "2026-06-03"   # Sunday


def test_canonical_registration_outranks_static_snapshot():
    # The snapshot says 2026-08-25 (Tue) is a trading day; a registered
    # canonical closure (e.g., exchange emergency) must win.
    _register(["2026-08-24"], start="2026-08-24", end="2026-08-26")
    assert _latest("2026-08-25T11:00:00Z") == "2026-08-24"


def test_new_year_closure_across_snapshot_boundary_needs_canonical():
    # 2026-01-04(Sun) evening: walking back crosses 2025-12-31, which is
    # OUTSIDE the 2026 snapshot → conservative error without a canonical
    # range; with the canonical range registered, latest = 2025-12-30.
    with pytest.raises(clock.CalendarUnavailableError):
        clock.latest_completed_session_date(JP, _utc("2026-01-04T11:00:00Z"))
    _register(["2025-12-29", "2025-12-30"],
              start="2025-12-25", end="2026-01-10")
    assert _latest("2026-01-04T11:00:00Z") == "2025-12-30"


# ── Conservative failure (no weekday inference) ────────────────────────────

def test_calendar_unavailable_beyond_all_coverage_raises():
    with pytest.raises(clock.CalendarUnavailableError):
        clock.latest_completed_session_date(JP, _utc("2027-03-03T11:00:00Z"))


def test_canonical_trading_day_never_weekday_infers_outside_coverage():
    with pytest.raises(clock.CalendarUnavailableError):
        clock.canonical_trading_day(JP, date(2027, 3, 3))   # a Wednesday


def test_hatch_is_conservative_when_calendar_unavailable():
    # The SDA daily-authority hatch must data-gate, not guess.
    observation = {"observedAt": "2027-03-02T06:30:00Z"}
    subject = {"market": "JP", "instrumentId": "1321"}
    assert sd._latest_session_daily_authority(
        observation, subject, "2027-03-03T11:00:00Z") is False


def test_quote_eligibility_calendar_unavailable_is_ineligible():
    verdict = clock.quote_eligibility(
        "1321", _utc("2027-03-01T06:30:00Z"),
        now_utc=_utc("2027-03-03T11:00:00Z"))    # >36h → origin path
    assert verdict["eligible"] is False
    assert verdict["quoteStatus"] == "calendar_unavailable"


# ── Session identity decides eligibility, not wall-clock hours ─────────────

def test_latest_session_bar_is_authoritative_and_older_bar_is_not():
    # Completed session + matching bar → hatch True however old the clock;
    # a genuinely missing newer bar (older session date) → False.
    cutoff = "2026-07-20T11:00:00Z"                 # Monday holiday evening
    good = {"observedAt": "2026-07-17T06:30:00Z"}   # Friday close
    stale = {"observedAt": "2026-07-16T06:30:00Z"}  # Thursday close
    subject = {"market": "JP", "instrumentId": "1321"}
    assert sd._latest_session_daily_authority(good, subject, cutoff) is True
    assert sd._latest_session_daily_authority(stale, subject, cutoff) is False


def test_no_weekday_constants_in_daily_authority_sources():
    """Tripwire: the authority path must not contain weekday()==N special
    cases (the telemetry-only weekend check in is_trading_day is exempt)."""
    import inspect
    for fn in (clock.canonical_trading_day,
               clock._origin_trading_date,
               clock.latest_completed_session_date,
               sd._latest_session_daily_authority):
        source = inspect.getsource(fn)
        assert "weekday() == 4" not in source
        assert "weekday()==4" not in source
