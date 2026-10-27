"""N-07 (owner 2026-10-27): how a registered Japanese stock moved after its
earnings releases, from the disclosure time and its own daily bars."""
import argus_earnings_reaction as er


def obs(day, stamp, doc="FYFinancialStatements_Consolidated_JP"):
    return {"summary": {"DiscDate": day, "DiscTime": stamp, "DocType": doc, "CurPerType": "FY"}}


STOCK = {"dates": ["2026-08-05", "2026-08-06", "2026-08-07", "2026-08-10", "2026-08-11"],
         "opens": [1000, 1000, 1080, 1100, 1090],
         "closes": [1000, 1010, 1100, 1090, 1095]}
TOPIX = [{"date": "2026-08-06", "close": 3000}, {"date": "2026-08-07", "close": 3030}]


def test_after_close_release_reacts_the_next_session_against_topix():
    result = er.reactions([obs("2026-08-06", "15:30")], STOCK, TOPIX)
    [row] = result["rows"]
    assert row["session"] == "2026-08-07" and row["timing"] == "AFTER_CLOSE"
    assert row["gapPct"] == 6.93 and row["dayPct"] == 8.91      # 1080/1010, 1100/1010
    assert row["topixPct"] == 1.0 and row["excessPct"] == 7.91
    assert result["count"] == 1 and result["ups"] == 1 and result["predictiveProbability"] is None


def test_timing_buckets_and_what_is_left_out():
    assert er._timing("08:30") == "BEFORE_OPEN" and er._timing("13:00") == "INTRADAY"
    assert er._timing("15:30") == "AFTER_CLOSE" and er._timing("") == "AFTER_CLOSE"
    intraday = er.reactions([obs("2026-08-07", "13:00")], STOCK)["rows"][0]
    assert intraday["session"] == "2026-08-07" and intraday["timing"] == "INTRADAY" and intraday["topixPct"] is None
    # Forecast revisions are not earnings releases; an untraded release and one without a previous close are skipped.
    assert er.reactions([obs("2026-08-06", "15:30", doc="ForecastRevision")], STOCK)["rows"] == []
    assert er.reactions([obs("2026-08-11", "15:30")], STOCK)["rows"] == []
    assert er.reactions([obs("2026-08-04", "16:00")], {"dates": ["2026-08-05"], "opens": [1], "closes": [1]})["rows"] == []


def test_newest_first_and_bounded():
    many = [obs(f"2026-08-0{d}", "15:30") for d in (5, 6, 7)] + [obs("2026-08-06", "15:30")]
    rows = er.reactions(many, STOCK, limit=2)["rows"]
    assert [r["disclosedDate"] for r in rows] == ["2026-08-07", "2026-08-06"]
