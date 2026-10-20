"""2026-10-20 (owner decision): each day's JSF balances are kept (the public file holds one day)."""
import json
import sqlite3

import jp_market_acquisition as sources
import scanner


def table():
    return {"7203": {"loan": 1000, "short": 400, "loanNew": 10, "loanRepay": 5, "shortNew": 3, "shortRepay": 1},
            "9984": {"loan": 2000, "short": 900, "loanNew": 20, "loanRepay": 8, "shortNew": 6, "shortRepay": 2},
            "1301": {"loan": 7, "short": 7, "loanNew": 0, "loanRepay": 0, "shortNew": 0, "shortRepay": 0}}


def test_a_day_row_holds_totals_and_the_nikkei_members():
    row = scanner._jsf_daily_row(table(), "2026/10/19", {"確報"}, "2026-10-20T03:00:00Z", {"7203", "9984", "6758"})
    assert row["date"] == "2026-10-19" and row["availableFrom"] == "2026-10-20T03:00:00Z"
    assert row["totals"]["loan"] == 3007 and row["totals"]["short"] == 1307 and row["stocks"] == 3
    assert set(row["nikkei225"]) == {"7203", "9984"}          # 6758 is not in the file: no value invented
    assert row["publicationKinds"] == ["確報"]


def test_each_day_is_kept_once_and_a_revision_is_added(tmp_path, monkeypatch):
    monkeypatch.setattr(scanner, "_cost_policy_durable_enabled", lambda: True)
    monkeypatch.setitem(scanner._DURABILITY_PATHS, "root", str(tmp_path))
    monkeypatch.setattr(scanner, "_nikkei225_members_on", lambda day: {"7203", "9984"})
    monkeypatch.setattr(scanner, "_ai_now_iso", lambda: "2026-10-19T12:00:00Z")
    scanner._jsf_daily_retain(table(), "2026/10/19", {"速報"})
    monkeypatch.setattr(scanner, "_ai_now_iso", lambda: "2026-10-19T18:00:00Z")
    scanner._jsf_daily_retain(table(), "2026/10/19", {"速報"})             # the same values again: kept once
    revised = table(); revised["7203"]["loan"] = 1100
    monkeypatch.setattr(scanner, "_ai_now_iso", lambda: "2026-10-20T03:00:00Z")
    scanner._jsf_daily_retain(revised, "2026/10/19", {"確報"})             # the final figures: a new row
    conn = sqlite3.connect(tmp_path / "jp_market_source_history.sqlite3")
    rows = conn.execute("SELECT session, body, received_at FROM selected_feature_inputs "
                        "WHERE source_id='jsf_daily' ORDER BY seq").fetchall()
    assert [(r[0], r[2]) for r in rows] == [("2026-10-19", "2026-10-19T12:00:00Z"), ("2026-10-19", "2026-10-20T03:00:00Z")]
    assert json.loads(rows[1][1])["nikkei225"]["7203"]["loan"] == 1100
    assert scanner._JSF_DAILY_STATUS["status"] == "RETAINED" and scanner._JSF_DAILY_STATUS["lastDate"] == "2026-10-19"


def test_the_series_is_a_known_kept_source():
    assert "jsf_daily" in sources.STABLE_FEATURE_SOURCES
