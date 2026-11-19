"""2026-11-19 (owner, N31「円の欄に1行」): the dollar-denominated Nikkei."""
import hashlib
import json
import sqlite3

import pytest

import jp_market_acquisition
import jp_market_positioning as positioning


def _days(n):
    import datetime
    day, out = datetime.date(2026, 10, 1), []
    while len(out) < n:
        if day.weekday() < 5:
            out.append(day.isoformat())
        day += datetime.timedelta(days=1)
    return out


def _nikkei(days, start=60000.0):
    return [{"date": d, "instrumentId": "NIKKEI_225_INDEX", "close": start + i * 10,
             "availableFrom": d + "T07:00:00Z"} for i, d in enumerate(days)]


def _fx(days, start=150.0, **override):
    return [{"date": d, "instrumentId": "USDJPY", "unit": "JPY_PER_USD", "value": start + i * 0.1,
             "observationJst": "15:30", "offsetSeconds": 10.0, "sourceTimestamp": d + "T06:30:10Z",
             "availableFrom": d + "T06:30:11Z", **override} for i, d in enumerate(days)]


def test_twenty_sessions_same_moment():
    days = _days(21)
    view = positioning.usd_nikkei(_nikkei(days), _fx(days), cutoff=days[-1] + "T08:00:00Z")
    assert view["status"] == "AVAILABLE" and view["actionAuthority"] is False
    assert (view["date"], view["baseDate"], view["sessions"]) == (days[-1], days[0], 20)
    assert view["usdNikkei"] == round(60200 / 152.0, 2)
    assert view["baseUsdNikkei"] == round(60000 / 150.0, 2)
    assert view["usdChangePct"] == round((60200 / 152.0 / (60000 / 150.0) - 1) * 100, 2)
    assert view["yenChangePct"] == round((60200 / 60000 - 1) * 100, 2)


def test_not_enough_sessions_or_missing_end_is_not_borrowed():
    days = _days(21)
    assert positioning.usd_nikkei(_nikkei(days[:20]), _fx(days[:20]),
                                  cutoff=days[-1] + "T08:00:00Z")["status"] == "INSUFFICIENT"
    # no rate on the base day: never borrowed from the next day
    assert positioning.usd_nikkei(_nikkei(days), _fx(days[1:]),
                                  cutoff=days[-1] + "T08:00:00Z")["status"] == "INSUFFICIENT"
    # no rate on the latest day: never an older rate for today's close
    assert positioning.usd_nikkei(_nikkei(days), _fx(days[:-1]),
                                  cutoff=days[-1] + "T08:00:00Z")["status"] == "INSUFFICIENT"


def test_cutoff_and_time_tolerance():
    days = _days(21)
    # before today's close is available, the window ends a day earlier and lacks its base
    early = positioning.usd_nikkei(_nikkei(days), _fx(days), cutoff=days[-1] + "T06:40:00Z")
    assert early["status"] == "INSUFFICIENT"
    late = positioning.usd_nikkei(_nikkei(days), _fx(days, offsetSeconds=120.0),
                                  cutoff=days[-1] + "T08:00:00Z")
    assert late["status"] == "INSUFFICIENT" and late["keptSessions"] == 0
    with pytest.raises(ValueError):
        positioning.usd_nikkei([], [], cutoff="2026-11-19T08:00:00")


def test_selected_rows_reads_kept_receipts_and_checks_integrity(tmp_path):
    path = str(tmp_path / "history.sqlite3")
    days = _days(3)
    jp_market_acquisition.retain_first_receipts(_fx(days), path=path, source_id="usdjpy_tokyo_1530",
                                                received_at=days[-1] + "T07:00:00Z")
    rows = jp_market_acquisition.selected_rows(path, "usdjpy_tokyo_1530")
    assert [r["date"] for r in rows] == days and rows[0]["value"] == 150.0
    assert jp_market_acquisition.selected_rows(str(tmp_path / "none.sqlite3"), "usdjpy_tokyo_1530") == []
    with pytest.raises(ValueError):
        jp_market_acquisition.selected_rows(path, "unknown")
    db = sqlite3.connect(path)
    with db:
        db.execute("UPDATE selected_feature_inputs SET body=replace(body,'150.0','151.0') WHERE session=?",
                   (days[0],))
    db.close()
    with pytest.raises(ValueError, match="selected_source_integrity"):
        jp_market_acquisition.selected_rows(path, "usdjpy_tokyo_1530")


def test_market_view_carries_usd_nikkei(monkeypatch, tmp_path):
    import scanner
    days = _days(21)
    monkeypatch.setattr(scanner, "_cost_policy_durable_enabled", lambda: True)
    monkeypatch.setitem(scanner._DURABILITY_PATHS, "root", str(tmp_path))
    jp_market_acquisition.retain_first_receipts(
        _fx(days), path=str(tmp_path / "jp_market_source_history.sqlite3"),
        source_id="usdjpy_tokyo_1530", received_at=days[-1] + "T07:00:00Z")
    monkeypatch.setattr(scanner, "_N225_ANALOG_HISTORY", {"data": _nikkei(days)})
    view = scanner._usd_nikkei_document(cutoff=days[-1] + "T08:00:00Z")
    assert view["status"] == "AVAILABLE" and view["date"] == days[-1]
    monkeypatch.setattr(scanner, "_cost_policy_durable_enabled", lambda: False)
    assert scanner._usd_nikkei_document(cutoff=days[-1] + "T08:00:00Z")["status"] == "INSUFFICIENT"
