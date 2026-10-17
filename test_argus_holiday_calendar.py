"""Rule-generated exchange holidays (owner request 2026-10-02: cover 15 more years)."""
from datetime import date

import pytest

import argus_market_clock as clock

# The official 2026 snapshots the rules must reproduce exactly.
OFFICIAL_JP_2026 = {
    "2026-01-01", "2026-01-02", "2026-01-03", "2026-01-12", "2026-02-11", "2026-02-23", "2026-03-20",
    "2026-04-29", "2026-05-03", "2026-05-04", "2026-05-05", "2026-05-06", "2026-07-20", "2026-08-11",
    "2026-09-21", "2026-09-22", "2026-09-23", "2026-10-12", "2026-11-03", "2026-11-23", "2026-12-31"}
OFFICIAL_US_2026 = {
    "2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25", "2026-06-19", "2026-07-03",
    "2026-09-07", "2026-11-26", "2026-12-25"}


def test_rules_reproduce_the_official_2026_calendars():
    assert set(clock._hol_jp_holidays(2026)) == OFFICIAL_JP_2026
    assert clock._hol_jp_holidays(2026)["2026-09-22"] == "National Holiday / 国民の休日"
    assert clock._hol_jp_holidays(2026)["2026-05-06"] == "Substitute Holiday / 振替休日"
    assert set(clock._hol_us_holidays(2026)) == OFFICIAL_US_2026
    assert clock._hol_us_early_closes(2026) == {"2026-11-27": "Day after Thanksgiving", "2026-12-24": "Christmas Eve"}


def test_later_years_follow_the_law_and_exchange_rules():
    jp = clock._hol_jp_holidays
    assert {"2027-03-21", "2027-03-22", "2027-09-23"} <= set(jp(2027))   # equinox on Sunday → Monday
    assert jp(2032)["2032-09-21"] == "National Holiday / 国民の休日"      # between 9/20 and 9/22
    assert {"2041-01-02", "2041-01-03", "2041-12-31"} <= set(jp(2041))
    us = clock._hol_us_holidays
    assert "2027-06-18" in us(2027) and "2027-07-05" in us(2027) and "2027-12-24" in us(2027)
    assert "2027-12-31" not in us(2027) and "2028-01-01" not in us(2028)   # Saturday New Year: no closure
    assert "2028-04-14" in us(2028)                                        # Good Friday (Easter 4/16)
    assert clock._hol_us_early_closes(2025) == {"2025-07-03": "Independence Day Eve",
                                                "2025-11-28": "Day after Thanksgiving",
                                                "2025-12-24": "Christmas Eve"}


def test_coverage_runs_through_2041_and_stops_there():
    clock.clear_canonical_calendar()
    assert clock.canonical_trading_day(clock.JP_EQUITY, date(2027, 3, 22)) is False
    assert clock.canonical_trading_day(clock.JP_EQUITY, date(2041, 12, 30)) is True
    assert clock.canonical_trading_day(clock.US_EQUITY, date(2041, 11, 28)) is False   # Thanksgiving
    with pytest.raises(clock.CalendarUnavailableError):
        clock.canonical_trading_day(clock.JP_EQUITY, date(2042, 1, 6))
