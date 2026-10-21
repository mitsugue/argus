"""2026-10-21 (owner): the USD/JPY at the Tokyo close is kept each trading day, only at the same moment."""
import json
import sqlite3
from datetime import datetime

import pytz
import pytest

import scanner

CLOSE = datetime(2026, 10, 21, 6, 30, tzinfo=pytz.utc)        # 15:30 JST, a Wednesday


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(scanner, "_cost_policy_durable_enabled", lambda: True)
    monkeypatch.setitem(scanner._DURABILITY_PATHS, "root", str(tmp_path))
    monkeypatch.setattr(scanner, "_USDJPY_TOKYO_CLOSE", {"status": "NOT_RUN", "lastDate": None,
                                                         "lastAttemptMonotonic": None})
    return tmp_path


def rows(path):
    conn = sqlite3.connect(path / "jp_market_source_history.sqlite3")
    try:
        return [json.loads(b) for (b,) in conn.execute(
            "SELECT body FROM selected_feature_inputs WHERE source_id='usdjpy_tokyo_1530'")]
    finally:
        conn.close()


def at(seconds):
    return CLOSE.replace(second=0) + __import__('datetime').timedelta(seconds=seconds)


def test_a_rate_timed_at_the_close_is_kept_once(store, monkeypatch):
    monkeypatch.setattr(scanner, "_yf_quote", lambda sym: (151.234, 151.0, CLOSE.timestamp() + 12))
    row = scanner._usdjpy_tokyo_close_tick(at(20))
    assert row["value"] == 151.234 and row["offsetSeconds"] == 12.0 and row["date"] == "2026-10-21"
    assert scanner._usdjpy_tokyo_close_tick(at(50)) is None          # once a day
    assert len(rows(store)) == 1 and scanner._USDJPY_TOKYO_CLOSE["status"] == "RETAINED"


def test_a_rate_from_another_moment_is_not_kept(store, monkeypatch):
    monkeypatch.setattr(scanner, "_yf_quote", lambda sym: (151.2, 151.0, CLOSE.timestamp() - 600))
    assert scanner._usdjpy_tokyo_close_tick(at(30)) is None
    assert scanner._USDJPY_TOKYO_CLOSE["reason"] == "source_time_outside_tolerance"
    assert scanner._usdjpy_tokyo_close_tick(at(400)) is None
    assert scanner._USDJPY_TOKYO_CLOSE["status"] == "MISSED"
    assert not (store / "jp_market_source_history.sqlite3").exists() or rows(store) == []


def test_nothing_before_the_close_or_on_a_holiday(store, monkeypatch):
    called = []
    monkeypatch.setattr(scanner, "_yf_quote", lambda sym: called.append(sym))
    assert scanner._usdjpy_tokyo_close_tick(at(-60)) is None
    holiday = datetime(2026, 11, 3, 6, 30, 20, tzinfo=pytz.utc)  # 文化の日
    assert scanner._usdjpy_tokyo_close_tick(holiday) is None
    assert called == []


def test_a_restart_after_the_close_keeps_what_was_kept(store, monkeypatch):
    # 2026-10-21: the 13.8.152 restart at 16:50 reported the day as missed
    # although the earlier process had read the window; the store decides.
    monkeypatch.setattr(scanner, "_yf_quote", lambda sym: (151.234, 151.0, CLOSE.timestamp() + 12))
    assert scanner._usdjpy_tokyo_close_tick(at(20))["date"] == "2026-10-21"
    monkeypatch.setattr(scanner, "_USDJPY_TOKYO_CLOSE", {"status": "NOT_RUN", "lastDate": None,
                                                         "lastAttemptMonotonic": None})
    called = []
    monkeypatch.setattr(scanner, "_yf_quote", lambda sym: called.append(sym))
    assert scanner._usdjpy_tokyo_close_tick(at(4800)) is None         # 16:50 JST, after the window
    state = scanner._USDJPY_TOKYO_CLOSE
    assert state["status"] == "RETAINED" and state["lastDate"] == "2026-10-21" and state["keptSessions"] == 1
    assert state.get("missedDate") is None and called == [] and len(rows(store)) == 1


def test_a_day_not_kept_is_still_reported_missed_after_a_restart(store, monkeypatch):
    monkeypatch.setattr(scanner, "_yf_quote", lambda sym: None)
    assert scanner._usdjpy_tokyo_close_tick(at(4800)) is None
    state = scanner._USDJPY_TOKYO_CLOSE
    assert state["status"] == "MISSED" and state["keptSessions"] == 0 and state["lastDate"] is None
