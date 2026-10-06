from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import pytest

import argus_analysis_history as history
import argus_future_map_scoring as scoring

ROW = {"id": "forecast-a", "start": "2026-10-01", "end": "2026-10-09", "view": "水準の参考予測",
       "level": {"low": 100, "high": 100}, "tag": "売り時", "reason": None, "alt": None}
AT = "2026-10-01T00:00:00+09:00"
END = "2026-10-19T15:30:00+09:00"  # Sports Day is excluded; five sessions after 10/9.


def prices(row=ROW, price=120):
    return [{"date": day, "high": price+1, "low": price-1, "close": price} for day in scoring.window(row)]


def test_official_holiday_window_and_no_early_miss_or_future_intraday_bar():
    record = scoring.registration(ROW, received_at=AT)
    days = scoring.window(ROW)
    assert days[0] == "2026-10-02" and days[-1] == "2026-10-19" and len(days) == 11
    assert "2026-10-12" not in days
    assert scoring.score(record, prices(), now_iso="2026-10-09T16:00:00+09:00")["result"] is None
    assert scoring.score(record, prices(), now_iso="2026-10-19T15:29:59+09:00")["result"] is None
    assert scoring.score(record, prices(), now_iso=END)["result"] == "missed"


def test_exact_price_boundaries_and_missing_or_conflicting_days_do_not_mean_missed():
    record = scoring.registration(ROW, received_at=AT)
    bars = prices()
    bars[0].update(high=99, low=98, close=98.5)
    assert scoring.score(record, bars, now_iso=END)["result"] == "reached"
    assert scoring.score(record, bars[1:], now_iso=END)["status"] == "PRICES_INCOMPLETE"
    conflict = bars + [{**bars[0], "high": 140, "close": 130}]
    assert scoring.score(record, conflict, now_iso=END)["status"] == "PRICES_INCOMPLETE"
    delayed = deepcopy(bars); delayed[0]["availableFrom"] = "2026-10-20T00:00:00Z"
    assert scoring.score(record, delayed, now_iso=END)["status"] == "PRICES_INCOMPLETE"


def test_range_touch_is_not_turning_point_and_registration_cannot_be_backdated():
    record = scoring.registration(ROW, received_at="2026-10-02T09:00:00+09:00")
    assert scoring.score(record, prices(price=100), now_iso=END)["status"] == "LATE_REGISTRATION"
    record = scoring.registration(ROW, received_at=AT)
    result = scoring.score(record, prices(price=100), now_iso=END)
    assert result["result"] == "reached" and result["turningPointValidated"] is False
    assert result["probability"] is None and result["actionAuthority"] is False


def test_direction_uses_preperiod_close_not_period_open_and_requires_whole_window():
    row = {**ROW, "start": "2026-10-05", "end": "2026-10-09", "level": None, "tag": "下落"}
    record = scoring.registration(row, received_at=AT)
    bars = prices(row, 98) + [{"date": "2026-10-02", "high": 101, "low": 99, "close": 100}]
    result = scoring.score(record, bars, now_iso="2026-10-09T15:30:00+09:00")
    assert result["result"] == "reached" and result["baselineClose"] == 100
    assert scoring.score(record, bars[:-1], now_iso=END)["status"] == "PRICES_INCOMPLETE"
    undefined = scoring.registration({**row, "tag": "底"}, received_at=AT)
    assert scoring.score(undefined, bars, now_iso=END)["status"] == "DIRECTION_NOT_DEFINED"


def test_immutable_versions_duplicate_execution_restart_and_correction_history(tmp_path):
    path = tmp_path / "existing.sqlite3"
    history.initialize(path)
    original = scoring.registration(ROW, received_at=AT)
    changed = scoring.registration({**ROW, "level": {"low": 120, "high": 120}}, received_at=AT)
    assert history.append_future_map_version(path, original)["inserted"]
    assert not history.append_future_map_version(path, original)["inserted"]
    history.append_future_map_version(path, changed)
    miss = scoring.score(original, prices(), now_iso=END)
    history.append_future_map_outcome(path, miss)
    assert not history.append_future_map_outcome(path, miss)["inserted"]
    revised = scoring.score(original, prices(price=100), now_iso=END)
    history.append_future_map_outcome(path, revised)
    state = history.read_future_map_state(path)
    assert len(state["versions"]) == 2 and len(state["outcomes"]) == 2
    assert state["outcomes"][0]["result"] == "missed"
    outcomes = {r["recordId"]: r for r in state["outcomes"]}
    summary = scoring.summarize(state["versions"], outcomes)
    assert summary["scored"] == 1 and summary["reached"] == 1 and summary["firstVersionOnly"]
    assert summary["status"] == "INSUFFICIENT_SAMPLE"
    assert history.read_level_map_state(path) == {"eps": {}, "mornings": []}
    assert history.read_candidate_records(path) == []


def test_ten_records_do_not_automatically_validate_a_forecast():
    records = [scoring.registration({**ROW, "id": str(n)}, received_at=AT) for n in range(10)]
    outcomes = {r["recordId"]: scoring.score(r, prices(price=100), now_iso=END) for r in records}
    summary = scoring.summarize(records, outcomes)
    assert summary["scored"] == 10 and summary["status"] == "UNVALIDATED"


def test_unknown_official_calendar_and_tampered_saved_outcome_fail_closed(tmp_path):
    import sqlite3
    from argus_market_clock import CalendarUnavailableError
    with pytest.raises(CalendarUnavailableError):
        scoring.window({**ROW, "start": "2100-10-01", "end": "2100-10-09"})
    path = tmp_path / "existing.sqlite3"
    history.initialize(path)
    record = scoring.registration(ROW, received_at=AT)
    history.append_future_map_version(path, record)
    result = scoring.score(record, prices(), now_iso=END)
    history.append_future_map_outcome(path, result)
    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE future_map_outcomes SET body=replace(body, 'missed', 'reached')")
    with pytest.raises(ValueError, match="future_map_outcome_integrity"):
        history.read_future_map_state(path)


def test_product_scoring_is_cached_only_on_page_read_and_recovers_after_restart(monkeypatch, tmp_path):
    import scanner
    path = tmp_path / "existing.sqlite3"
    monkeypatch.setattr(scanner, "_level_map_history_path", lambda: str(path))
    monkeypatch.setattr(scanner, "_future_map_load_saved", lambda: None)
    monkeypatch.setattr(scanner, "_FUTURE_MAP_SCORING", {"status": "NOT_RUN", "lastError": None, "versions": [], "outcomes": {}, "record": None})
    public = {"rows": [ROW]}
    monkeypatch.setattr(scanner, "_FUTURE_MAP", {"public": public})
    scanner._future_map_register(public, AT)
    monkeypatch.setattr(scanner, "_ai_now_iso", lambda: END)
    scanner._future_map_scoring_tick(prices(price=100))
    body = scanner._future_map_scored_display(public)
    assert body["record"]["scored"] == 1 and body["rows"][0]["result"] == "reached"
    before = history.read_future_map_state(path)
    for _ in range(3):
        scanner._future_map_scored_display(public)
    assert history.read_future_map_state(path) == before
    scanner._future_map_register(public, END)
    assert scanner._future_map_scored_display(public)["record"]["scored"] == 1
