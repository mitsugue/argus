"""Events a Japanese index ETF holder needs, each with what it means."""
from datetime import date, datetime, timezone

import jp_equity_event_calendar as cal

NOW = datetime(2026, 10, 2, 13, 0, tzinfo=timezone.utc)   # 22:00 JST Friday


def test_every_event_says_what_it_means_for_the_etfs():
    result = cal.equity_event_calendar(now=NOW, horizon_days=90)
    assert result["status"] == "AVAILABLE" and result["actionAuthority"] is False
    assert result["automaticAiCalls"] == 0
    kinds = {row["kind"] for row in result["events"]}
    assert {"JP_CPI", "JP_TOKYO_CPI", "JP_TANKAN", "JP_GDP", "SQ", "MAJOR_SQ",
            "LAST_CUM_DIVIDEND", "EX_DIVIDEND", "JP_MARKET_CLOSED", "US_MARKET_CLOSED"} <= kinds
    for row in result["events"]:
        assert row["whatJa"] and row["soWhatJa"] and row["watchJa"], row["eventId"]
        assert row["actionAuthority"] is False
    assert [row["at"][:10] for row in result["events"]] == sorted(row["at"][:10] for row in result["events"])


def test_dividend_dates_follow_the_record_date_rule():
    rows = cal.dividend_events(date(2026, 9, 1), date(2027, 3, 31))
    assert [(row["date"], row["kind"]) for row in rows] == [
        ("2026-09-28", "LAST_CUM_DIVIDEND"), ("2026-09-29", "EX_DIVIDEND"),
        ("2026-12-28", "LAST_CUM_DIVIDEND"), ("2026-12-29", "EX_DIVIDEND"),   # 12/31 closed
        ("2027-03-29", "LAST_CUM_DIVIDEND"), ("2027-03-30", "EX_DIVIDEND")]
    ex = next(row for row in rows if row["eventId"] == "jp-ex-dividend-2026-09")
    assert ex["importance"] == "high" and "ベアETF" in ex["soWhatJa"] and "配当" in ex["soWhatJa"]


def test_major_sq_and_holidays_are_named_in_japanese():
    events = {row["eventId"]: row for row in cal.equity_event_calendar(now=NOW, horizon_days=90)["events"]}
    assert events["jp-monthly-sq-2026-12"]["kind"] == "MAJOR_SQ"
    assert "メジャーSQ" in events["jp-monthly-sq-2026-12"]["soWhatJa"]
    assert events["us-market-closed-2026-11-26"]["titleJa"] == "米国市場 休場(感謝祭)"
    assert events["jp-market-closed-2026-11-03"]["titleJa"] == "東京市場 休場(文化の日)"


def test_unpublished_macro_dates_are_a_gap_not_an_empty_calendar():
    result = cal.equity_event_calendar(now=datetime(2026, 12, 20, 0, 0, tzinfo=timezone.utc), horizon_days=45)
    assert "jp_macro_schedule_not_published_beyond_2026-12-31" in result["gaps"]
    assert result["status"] == "PARTIAL"
    broken = cal.equity_event_calendar(now=NOW, macro_schedule={"schemaVersion": "x"})
    assert "jp_macro_schedule_unavailable" in broken["gaps"]
