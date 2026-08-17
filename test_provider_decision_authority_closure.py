"""Final provider-boundary regressions for daily NAV and untimebound depth."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import argus_market_clock
import pytest

import scanner


NAV_CODE = "03311182"
NOW_DT = datetime(2026, 8, 16, 3, 0, tzinfo=timezone.utc)
NOW = NOW_DT.timestamp()


def _latest_jp_session() -> str:
    return argus_market_clock.latest_completed_session_date(
        argus_market_clock.JP_EQUITY, NOW_DT).isoformat()


def _nav_row(date: str, *, nav=20_000.0):
    return {
        "code": NAV_CODE,
        "name": "ignored-provider-name",
        "navYen": nav,
        "changePct": 1.25,
        "date": date,
        # An attempted provider-side LIVE label is intentionally ignored.
        "status": "live",
    }


def test_fund_nav_is_bounded_daily_evidence_never_live():
    result = scanner._fund_nav_decision_row(
        _nav_row(_latest_jp_session()), now_epoch=NOW)

    assert result is not None
    assert result["status"] == "delayed"
    assert result["freshness"] == "DELAYED"
    assert result["sourceTimeStatus"] == "DATE_ONLY_DAILY"
    assert result["sourceTimestamp"] == _latest_jp_session()
    assert result["decisionUsable"] is True


@pytest.mark.parametrize(
    "source_date",
    [
        "2024-01-05",
        "2026-08-16",  # Sunday and not a completed JP session.
        "2026-08-17",  # Future provider date.
        "2026-02-30",
        "2026-8-14",
        "not-a-date",
        None,
    ],
)
def test_fund_nav_rejects_old_future_non_session_and_malformed_dates(
        source_date):
    assert scanner._fund_nav_decision_row(
        _nav_row(source_date), now_epoch=NOW) is None


@pytest.mark.parametrize("nav", [True, "20000", float("nan"), float("inf"), 0])
def test_fund_nav_rejects_non_numeric_or_nonfinite_values(nav):
    assert scanner._fund_nav_decision_row(
        _nav_row(_latest_jp_session(), nav=nav), now_epoch=NOW) is None


def test_fund_nav_cache_hit_reages_provider_date(monkeypatch):
    monkeypatch.setattr(scanner.time, "time", lambda: NOW)
    scanner._FUND_NAV_CACHE.clear()
    scanner._FUND_NAV_CACHE[NAV_CODE] = {
        "data": _nav_row("2024-01-05"),
        "expires": NOW + 3_600,
    }

    assert scanner._toushin_nav(NAV_CODE) is None


def test_fund_nav_route_aggregate_is_delayed_and_provider_dated(monkeypatch):
    latest = _latest_jp_session()
    valid = scanner._fund_nav_decision_row(_nav_row(latest), now_epoch=NOW)
    monkeypatch.setattr(
        scanner, "_toushin_nav", lambda code: valid if code == NAV_CODE else None)
    monkeypatch.setattr(scanner, "_ai_now_iso", lambda: "2026-08-16T03:00:00Z")

    with scanner.app.test_request_context(
            f"/api/argus/fund-nav?codes={NAV_CODE},missing"):
        body = scanner.api_argus_fund_nav().get_json()

    assert body["status"] == "delayed"
    assert body["asOf"] == latest
    assert body["receivedAt"] == "2026-08-16T03:00:00Z"
    assert body["funds"] == [valid]


@pytest.mark.parametrize(
    "attempted_timestamp",
    [None, "not-a-time", NOW + 3_600, NOW - 3_600],
)
def test_order_book_without_settled_venue_time_remains_diagnostic(
        monkeypatch, attempted_timestamp):
    monkeypatch.setattr(scanner, "get_order_book", lambda _symbol: {
        "bids": [(100.0, 10_000), (99.0, 1)],
        "asks": [(101.0, 1), (102.0, 1)],
        "decisionUsable": True,
        "sourceTimestamp": attempted_timestamp,
    })

    result = scanner.analyze_order_book("AAPL")

    assert result["available"] is True
    assert result["authority"] == "diagnostic_only"
    assert result["decisionUsable"] is False
    assert result["sourceTimeStatus"] == "UNVALIDATED_CAPABILITY"


def test_diagnostic_order_book_cannot_change_phase4_score(monkeypatch):
    state = {"top5": [
        {"symbol": "AAPL", "combined_score": 60, "reason": "test"},
        {"symbol": "MSFT", "combined_score": 59, "reason": "test"},
    ]}
    saved = []
    monkeypatch.setattr(scanner, "load_state", lambda: state)
    monkeypatch.setattr(scanner, "save_state", lambda value: saved.append(value))
    monkeypatch.setattr(scanner, "analyze_order_book", lambda _symbol: {
        "available": True,
        "decisionUsable": False,
        "whale_detected": True,
        "downside_efficiency": 1.0,
    })
    monkeypatch.setattr(scanner, "get_account_info", lambda: None)
    monkeypatch.setattr(scanner, "get_positions", lambda: None)
    monkeypatch.setattr(scanner, "push_notify", lambda *_a, **_k: None)
    monkeypatch.setattr(scanner, "add_log", lambda *_a, **_k: None)
    monkeypatch.setattr(scanner, "DRY_RUN_MODE", True)

    scanner.phase4_final_top3()

    assert [row["final_score"] for row in state["top3_final"]] == [60, 59]
    assert all(row["order_book"]["decisionUsable"] is False
               for row in state["top3_final"])


def test_public_session_brief_uses_canonical_holiday_and_suppresses_add(
        monkeypatch):
    holiday = datetime(2026, 8, 11, 1, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(scanner, "_action_priority_items", lambda **_kwargs: [{
        "priorityRank": "P1", "symbol": "7203", "assetName": "Toyota",
        "isHeld": False, "category": "add_candidate",
        "blockingReason": "none", "ownerReadableWhyJa": "positive",
        "ownerReadableTitleJa": "candidate", "checkNextJa": "check",
        "actionLabelJa": "candidate",
    }])
    monkeypatch.setattr(scanner, "_MOVER_MACRO_VIEW", lambda: [])
    monkeypatch.setattr(scanner, "_supply_demand_list", lambda **_kwargs: [])
    monkeypatch.setattr(scanner, "_ai_now_iso",
                        lambda: "2026-08-11T10:00:00+09:00")

    brief = scanner._session_brief_public(holiday)

    assert brief["canonicalSessions"]["JP"] == "HOLIDAY_CLOSED"
    assert brief["sessionType"] == "holiday"
    assert brief["ownerMode"] == "review"
    assert brief["addCandidates"] == []
    assert "休場" in brief["headlineJa"]
