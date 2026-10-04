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


def test_nikkei_periodic_review_is_the_first_trading_day_of_april_and_october():
    """Nikkei's selection rule: April and October, first trading day (confirmed against the 2023-2026 history)."""
    rows = cal.nikkei_review_events(date(2026, 10, 2), date(2027, 4, 30))
    assert [(row["date"], row["kind"]) for row in rows] == [("2027-04-01", "NIKKEI_PERIODIC_REVIEW")]
    # October 2026's first trading day (Thursday 10/1) is already past; before it, it is listed.
    before = cal.nikkei_review_events(date(2026, 9, 20), date(2026, 10, 31))
    assert [row["date"] for row in before] == ["2026-10-01"]
    # A first business day behind a holiday moves forward (2023-10-02 and 2023-04-03 in the history).
    assert [row["date"] for row in cal.nikkei_review_events(date(2023, 3, 20), date(2023, 4, 30))] == ["2023-04-03"]
    assert [row["date"] for row in cal.nikkei_review_events(date(2023, 9, 20), date(2023, 10, 31))] == ["2023-10-02"]
    row = rows[0]
    assert "最大3銘柄" in row["whatJa"] and "約1か月前" in row["whatJa"] and "未確認" in row["whatJa"]
    assert "除数" in row["soWhatJa"] and "20260709J_3.pdf" in row["source"]


def test_msci_review_dates_come_from_the_published_schedule_with_the_close_before_the_effective_day():
    import json
    schedule = json.loads(cal.MSCI_SCHEDULE.read_text())
    assert schedule["sourceRef"].endswith("/ir_dates.pdf") and len(schedule["sourceCsvSha256"]) == 64
    rows, gaps = cal.msci_events(date(2026, 10, 3), date(2026, 12, 15), schedule)
    assert [(row["date"], row["kind"]) for row in rows] == [
        ("2026-11-11", "MSCI_REVIEW_ANNOUNCEMENT"), ("2026-11-30", "MSCI_REVIEW_REBALANCE")]   # effective 12/01
    assert gaps == []
    assert "2026-12-01" in rows[1]["whatJa"] and "大引け" in rows[1]["soWhatJa"]
    # The effective day after a weekend moves the rebalance to the previous trading day (2027-05-28 is a Friday).
    may = cal.msci_events(date(2027, 5, 1), date(2027, 5, 31), schedule)[0]
    assert [(row["date"], row["kind"]) for row in may] == [
        ("2027-05-10", "MSCI_REVIEW_ANNOUNCEMENT"), ("2027-05-27", "MSCI_REVIEW_REBALANCE")]
    # Beyond the published schedule it is a gap, never an extrapolation.
    far = cal.msci_events(date(2028, 8, 1), date(2028, 11, 1), schedule)
    assert "msci_schedule_not_published_beyond_2028-09-01" in far[1]
    try:
        cal.msci_events(date(2026, 10, 3), date(2026, 12, 15), {"schemaVersion": "x"})
        raise AssertionError("an unknown schema must not be accepted")
    except ValueError as exc:
        assert str(exc) == "msci_schedule_invalid"


def test_the_calendar_lists_the_review_events_inside_the_horizon():
    result = cal.equity_event_calendar(now=NOW, horizon_days=90)
    kinds = {row["kind"] for row in result["events"]}
    assert {"MSCI_REVIEW_ANNOUNCEMENT", "MSCI_REVIEW_REBALANCE"} <= kinds
    assert "NIKKEI_PERIODIC_REVIEW" not in kinds            # 2027-04-01 is beyond 90 days
    for row in result["events"]:
        assert row["whatJa"] and row["soWhatJa"] and row["watchJa"] and row["actionAuthority"] is False


def test_us_election_day_is_the_tuesday_after_the_first_monday_of_november():
    """Confirmed for 2026-11-03 (midterms; all 435 House seats and 35 Senate seats)."""
    rows = cal.us_election_events(date(2026, 10, 3), date(2026, 12, 31))
    assert [(row["date"], row["kind"]) for row in rows] == [("2026-11-03", "US_ELECTION_DAY")]
    row = rows[0]
    assert "中間選挙" in row["titleJa"] and row["importance"] == "high"
    assert "435議席" in row["whatJa"] and "休場" in row["whatJa"]            # 11/3 is the Japanese Culture Day
    assert "標本が少なく" in row["soWhatJa"] and row["actionAuthority"] is False
    assert [r["date"] for r in cal.us_election_events(date(2027, 1, 1), date(2028, 12, 31))] == ["2028-11-07"]
    assert "大統領選" in cal.us_election_events(date(2028, 10, 1), date(2028, 12, 31))[0]["titleJa"]
    assert cal.us_election_events(date(2026, 11, 4), date(2027, 10, 31)) == []      # odd year, none
    # Inside the 90-day calendar it appears among the events, sorted by date.
    events = cal.equity_event_calendar(now=NOW, horizon_days=90)["events"]
    assert any(e["eventId"] == "us-election-day-2026-11-03" for e in events)


def test_us_funding_deadline_comes_from_a_quoted_public_source():
    """CRS R49353: the FY2027 continuing appropriations run through 2026-12-11."""
    import json
    document = json.loads(cal.US_POLICY_DATES.read_text())
    row = document["rows"][0]
    assert row["date"] == "2026-12-11" and "through December 11, 2026" in row["sourceQuote"]
    events = cal.us_policy_events(date(2026, 10, 3), date(2026, 12, 31), document)
    assert [(e["date"], e["kind"]) for e in events] == [("2026-12-11", "US_FUNDING_DEADLINE")]
    assert "翌日から政府機関の一部が閉鎖" in events[0]["whatJa"] and "雇用統計" in events[0]["soWhatJa"]
    assert events[0]["importance"] == "high" and events[0]["source"].endswith("R49353")
    # A row without a quoted source or a known kind is never shown.
    bare = {"schemaVersion": "us-policy-dates-v1", "rows": [{**row, "sourceQuote": ""}, {**row, "kind": "UNKNOWN"}]}
    assert cal.us_policy_events(date(2026, 10, 3), date(2026, 12, 31), bare) == []
    assert cal.us_policy_events(date(2026, 12, 12), date(2027, 1, 31), document) == []
    try:
        cal.us_policy_events(date(2026, 10, 3), date(2026, 12, 31), {"schemaVersion": "x"})
        raise AssertionError("an unknown schema must not be accepted")
    except ValueError as exc:
        assert str(exc) == "us_policy_dates_invalid"
    listed = {e["eventId"] for e in cal.equity_event_calendar(now=NOW, horizon_days=90)["events"]}
    assert "us-funding-deadline-2026-12-11" in listed


def test_calendar_effects_carry_the_measured_past_without_a_direction():
    """2026-10-04: SQ, ex-dividend, holidays and the Nikkei review carry one line
    of what the past shows; claims that did not survive the re-check are gone."""
    from datetime import datetime
    out = cal.equity_event_calendar(now=datetime.fromisoformat("2026-09-20T09:00:00+09:00"), horizon_days=90)
    by_kind = {}
    for event in out["events"]:
        by_kind.setdefault(event["kind"], event)
    assert "差はありません" in by_kind["SQ"]["pastTendencyJa"] or "差はありません" in by_kind["MAJOR_SQ"]["pastTendencyJa"]
    assert "機械的" in by_kind["EX_DIVIDEND"]["pastTendencyJa"]
    assert "+2.7%" in by_kind["NIKKEI_PERIODIC_REVIEW"]["pastTendencyJa"]
    assert "見られません" in by_kind["JP_MARKET_CLOSED"]["pastTendencyJa"]
    for event in out["events"]:
        assert "底堅くなりやすい" not in event["soWhatJa"]
        assert "持ち高を調整する動きも出やすい" not in event["soWhatJa"]
        text = event.get("pastTendencyJa") or ""
        for word in ("確率", "買い時", "売り時", "必ず"):
            assert word not in text
