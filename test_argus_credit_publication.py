from datetime import datetime, timezone
import pytest
from argus_credit_publication import publication_at, weekly_expectation


def test_collector_and_monitor_share_the_same_holiday_deadline():
    from scripts.jpx_credit_weekly import publication_due
    before = datetime.fromisoformat("2026-10-14T15:59:59+09:00")
    at = datetime.fromisoformat("2026-10-14T16:00:00+09:00")
    assert publication_at("2026-10-09") == at  # Sports Day on Monday.
    assert publication_due("2026-10-09", before) is False
    assert publication_due("2026-10-09", at) is True
    assert weekly_expectation(before)["latestDuePeriod"] == "2026-10-02"
    assert weekly_expectation(at)["latestDuePeriod"] == "2026-10-09"


def test_closed_friday_uses_the_weeks_last_actual_session():
    schedule = weekly_expectation(datetime.fromisoformat("2026-03-24T16:00:00+09:00"))
    assert schedule["latestDuePeriod"] == "2026-03-19"
    assert schedule["latestDueAt"] == "2026-03-24T16:00:00+09:00"


def test_schedule_requires_aware_clock_and_preserves_unknown_calendar():
    with pytest.raises(ValueError, match="timezone_required"):
        weekly_expectation(datetime(2026, 10, 6))
    assert publication_at("2015-10-02") is None
    assert weekly_expectation(datetime.fromisoformat("2015-10-06T16:00:00+09:00"))["status"] == "calendar_unavailable"


def test_current_consumer_collector_and_monitor_share_the_publication_bound():
    from jp_market_acquisition import enforce_two_market_publication
    row = {"periodEnd": "2026-10-09", "availableFrom": "2026-10-13T07:00:00Z",
           "knownAt": "2026-10-13T07:00:00Z", "publishedAt": None}
    result = enforce_two_market_publication([row], sessions=[])[0]
    due = publication_at(row["periodEnd"])
    assert result["availableFrom"] == due.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert weekly_expectation(due)["latestDuePeriod"] == row["periodEnd"]
    assert row["availableFrom"] == "2026-10-13T07:00:00Z" and result["publishedAt"] is None
