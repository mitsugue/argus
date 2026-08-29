"""Production-shaped regressions for the Important Events ranking hotfix.

The fixture mirrors the 2026-08-28 production failure: result-created macro
records have official facts but lack their schedule/ranking metadata, while old
Treasury PRE rows and one upcoming NFP share the bounded dashboard response.
"""
from copy import deepcopy

import argus_dashboard_event_summary as DS
import argus_macro_event_analysis as MA
import scanner


NOW = "2026-08-28T23:56:21Z"


def _result_skeleton(event_id, event_code, *, complete=False):
    """Old result-created shape: deliberately missing date/time/impact/source."""
    rec = {
        "schemaVersion": MA.SCHEMA_VERSION,
        "analysisId": f"ma-{event_id}",
        "eventId": event_id,
        "eventCode": event_code,
        "phase": "post_result",
        "pre": {},
        "actual": {
            "available": True,
            "headline": f"{event_code} official result",
            "metrics": {},
            "source": "official",
            "releasedAt": NOW,
        },
        "post": {},
        "marketReaction": {
            "riskTone": "mixed",
            "summaryJa": "市場反応を観測済み",
        },
        "firstSeenAt": NOW,
        "updatedAt": NOW,
    }
    if complete:
        rec["pre"] = {
            "summaryJa": "保存済みの事前見通し",
            "argusScenarioJa": "金利と株価の反応を確認",
            "generatedAt": "2026-07-13T12:00:00Z",
        }
        rec["post"] = {
            "verdict": "hit",
            "answerCheckJa": "答え合わせ済み",
            "generatedAt": "2026-07-14T13:00:00Z",
        }
    return rec


def _production_records():
    rows = [
        _result_skeleton("us-cpi-2026-07-14", "CPI", complete=True),
        _result_skeleton("us-fomc-2026-07-29", "FOMC"),
        _result_skeleton("us-pce-2026-07-30", "PCE"),
        _result_skeleton("us-gdp-2026-07-30", "GDP"),
        _result_skeleton("us-nfp-2026-08-07", "NFP"),
        _result_skeleton("us-cpi-2026-08-12", "CPI"),
        # Production hero candidate: official result + reaction, but no pre/post AI.
        _result_skeleton("us-pce-2026-08-26", "PCE"),
        _result_skeleton("us-gdp-2026-08-26", "GDP"),
    ]
    for date in ("2026-07-08", "2026-07-09", "2026-07-22"):
        rows.append({
            "eventId": f"us-treasury-auction-{date}",
            "eventCode": "TREASURY_AUCTION",
            "displayImpact": "high",
            "phase": "pre_watch",
            "pre": {"summaryJa": "古い入札監視"},
            "actual": {"available": False},
            "post": {},
        })
    return rows


def _upcoming_nfp():
    # ImportantEvent's production field is `date`, not `eventDate`.
    return {
        "eventId": "us-nfp-2026-09-04",
        "eventCode": "NFP",
        "title": "US Employment Situation",
        "eventTimeUtc": "2026-09-04T12:30:00Z",
        "date": "2026-09-04",
        "displayImpact": "high",
        "source": "Bureau of Labor Statistics",
        "daysUntil": 7,
        "countdown": "D-7",
    }


def _seed_production_shape(monkeypatch):
    records = _production_records()
    monkeypatch.setattr(scanner, "_MACRO_ANALYSIS",
                        {row["eventId"]: row for row in records})
    monkeypatch.setitem(scanner._MACRO_ANALYSIS_STATE, "restored", True)
    monkeypatch.setattr(scanner, "_ai_now_iso", lambda: NOW)
    monkeypatch.setattr(scanner, "_macro_important_events",
                        lambda limit=8: [_upcoming_nfp()][:limit])


def test_result_created_lifecycle_preserves_schedule_ranking_metadata():
    event = {
        "id": "us-pce-2026-08-26",
        "eventCode": "PCE",
        "category": "inflation",
        "title": "US PCE / Personal Income & Outlays",
        "eventTimeUtc": "2026-08-26T12:30:00Z",
        "date": "2026-08-26",
        "localTimeJst": "2026-08-26 21:30 JST",
        "displayImpact": "high",
        "source": "Bureau of Economic Analysis",
        "linkedAssets": ["US10Y", "USDJPY", "QQQ"],
        "daysUntil": 0,
        "countdown": "D",
    }
    rec = MA.new_record(event, now_iso=NOW)
    rec["actual"] = {"available": True, "headline": "PCE official result"}
    rec["marketReaction"] = {"summaryJa": "市場反応を観測済み"}
    fixed = MA.rehydrate_schedule_metadata(rec, event)

    assert fixed["eventId"] == event["id"]
    assert fixed["eventCode"] == "PCE"
    assert fixed["eventFamily"] == "inflation"
    assert fixed["eventTimeUtc"] == "2026-08-26T12:30:00Z"
    assert fixed["eventDate"] == "2026-08-26"
    assert fixed["displayImpact"] == "high"
    assert fixed["source"] == "Bureau of Economic Analysis"
    assert fixed["linkedAssets"] == ["US10Y", "USDJPY", "QQQ"]
    assert fixed["actual"]["available"] is True
    assert fixed["marketReaction"]["summaryJa"]


def test_generic_rehydration_repairs_catalog_rows_and_canonical_dates():
    pce = scanner._rehydrate_macro_record(
        _result_skeleton("us-pce-2026-08-26", "PCE"))
    cpi = scanner._rehydrate_macro_record(
        _result_skeleton("us-cpi-2026-08-12", "CPI"))
    auction = scanner._rehydrate_macro_record({
        "eventId": "us-treasury-auction-2026-07-22",
        "eventCode": "TREASURY_AUCTION",
        "displayImpact": "high",
    })

    assert (pce["eventDate"], pce["eventTimeUtc"], pce["displayImpact"], pce["source"]) == (
        "2026-08-26", "2026-08-26T12:30:00Z", "high",
        "Bureau of Economic Analysis")
    assert (cpi["eventDate"], cpi["eventTimeUtc"], cpi["displayImpact"], cpi["source"]) == (
        "2026-08-12", "2026-08-12T12:30:00Z", "high",
        "Bureau of Labor Statistics")
    assert auction["eventDate"] == "2026-07-22"
    assert MA.canonical_date_from_event_id("event-2026-02-30") is None


def test_production_shaped_ordering_is_correct_before_limit(monkeypatch):
    _seed_production_shape(monkeypatch)

    _, full, _ = scanner._build_dashboard_events(limit=20)
    _, bounded, _ = scanner._build_dashboard_events(limit=8)
    full_ids = [item["eventId"] for item in full]
    bounded_ids = [item["eventId"] for item in bounded]

    expected = [
        "us-pce-2026-08-26",
        "us-gdp-2026-08-26",
        "us-nfp-2026-09-04",
        "us-cpi-2026-08-12",
        "us-nfp-2026-08-07",
        "us-pce-2026-07-30",
        "us-gdp-2026-07-30",
        "us-fomc-2026-07-29",
    ]
    assert full_ids[:8] == expected
    assert bounded_ids == full_ids[:8] == expected
    assert bounded[0]["importance"] == "high"
    assert bounded[0]["eventTimeUtc"] == "2026-08-26T12:30:00Z"
    assert bounded[0]["state"] == "post_result"
    assert bounded[0]["officialResult"]["available"] is True
    assert bounded[0]["caos"]["verdict"] == "not_scoreable"
    assert "us-cpi-2026-07-14" not in bounded_ids
    assert not any("treasury-auction" in event_id for event_id in bounded_ids)

    completed_times = [item["eventTimeUtc"] or item["eventDate"]
                       for item in full if item["state"] != "pre"]
    assert completed_times == sorted(completed_times, reverse=True)


def test_optional_ai_analysis_cannot_change_importance_or_order(monkeypatch):
    _seed_production_shape(monkeypatch)
    _, before, _ = scanner._build_dashboard_events(limit=20)
    before_ids = [item["eventId"] for item in before]

    pce = deepcopy(scanner._MACRO_ANALYSIS["us-pce-2026-08-26"])
    pce["displayImpact"] = "medium"  # legacy/AI-side fallback must be raised.
    pce["post"] = {
        "verdict": "partial",
        "answerCheckJa": "optional answer check",
        "generatedAt": NOW,
    }
    scanner._MACRO_ANALYSIS["us-pce-2026-08-26"] = pce
    _, after, _ = scanner._build_dashboard_events(limit=20)

    assert [item["eventId"] for item in after] == before_ids
    assert after[0]["importance"] == "high"
    assert after[0]["state"] == "post_answer_checked"


def test_high_pending_result_is_fail_visible_ahead_of_old_complete_event():
    pending = {
        "eventId": "us-cpi-2026-08-28",
        "eventCode": "CPI",
        "title": "US CPI",
        "eventTimeUtc": "2026-08-28T23:30:00Z",
        "eventDate": "2026-08-28",
        "displayImpact": "high",
        "actual": {"available": False},
        "post": {},
    }
    old_complete = MA.rehydrate_schedule_metadata(
        _result_skeleton("us-cpi-2026-07-14", "CPI", complete=True),
        scanner._canonical_schedule_metadata("us-cpi-2026-07-14"))

    out = DS.build_summary(important_events=[], macro_records=[old_complete, pending],
                           now_iso=NOW, limit=1)
    assert out["items"][0]["eventId"] == "us-cpi-2026-08-28"
    assert out["items"][0]["state"] == "released_pending_result"
    assert out["items"][0]["display"]["showPendingResult"] is True


def test_undated_stale_pre_cannot_crow_a_bounded_response():
    valid = []
    for day in range(20, 28):
        valid.append({
            "eventId": f"us-valid-2026-08-{day}",
            "eventCode": f"V{day}",
            "eventDate": f"2026-08-{day}",
            "displayImpact": "high",
            "actual": {"available": True},
            "post": {},
        })
    undated = {
        "eventId": "legacy-treasury-row",
        "eventCode": "TREASURY_AUCTION",
        "displayImpact": "high",
        "phase": "pre_watch",
        "actual": {"available": False},
    }

    out = DS.build_summary(important_events=[], macro_records=[undated, *valid],
                           now_iso=NOW, limit=8)
    assert len(out["items"]) == 8
    assert "legacy-treasury-row" not in [item["eventId"] for item in out["items"]]
