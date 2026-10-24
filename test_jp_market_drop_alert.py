"""急落警戒(案E)の事前記録と採点(2026-10-24)。"""
import math
import re
from datetime import date, timedelta
from pathlib import Path

import jp_market_drop_alert as a

ROOT = Path(__file__).resolve().parent
# 研究側の事前記録(alert-e-forward-2026-10-22)と同じ定義の指紋。変えたら版を上げて別に数える。
RESEARCH_RULES_SHA256 = "f0db00231f88d88ef2c6749467be25d1b7200ae9435e432ce8ddeab5d2a2705e"


def weekdays(start, n):
    out, day = [], date.fromisoformat(start)
    while len(out) < n:
        if day.weekday() < 5:
            out.append(day.isoformat())
        day += timedelta(days=1)
    return out


def trading(day):
    return date.fromisoformat(day).weekday() < 5


def rows_for(closes, start="2026-09-01"):
    return [{"date": d, "close": c, "high": c * 1.002, "low": c * 0.998} for d, c in zip(weekdays(start, len(closes)), closes)]


def test_definition_matches_the_research_record_and_the_screen():
    assert a.RULES_VERSION == "alert-e-forward-2026-10-22" and a.RULES_SHA256 == RESEARCH_RULES_SHA256
    screen = (ROOT / "web/src/lib/todayDecision.ts").read_text()
    assert float(re.search(r"ALERT_LOW_BELOW = ([0-9.]+)", screen).group(1)) == a.RULES["lowBelow"]
    assert float(re.search(r"ALERT_HIGH_FROM = ([0-9.]+)", screen).group(1)) == a.RULES["highFrom"]
    raise_rule = re.search(r"ALERT_RAISE = \{ dayPct: (-?\d+), fiveDayPct: (-?\d+) \}", screen)
    assert (int(raise_rule.group(1)), int(raise_rule.group(2))) == (a.RULES["raise"]["dayPct"], a.RULES["raise"]["fiveDayPct"])
    assert "(vix / 100 + rv) / 2" in screen and "Math.sqrt(250)" in screen and "(r.length - 1)" in screen
    # 画面の過去の固定値は研究の件数と同じ。
    past = a.RULES["pastRecord"]
    for level, shown in (("low", 2.9), ("normal", 8.5), ("high", 17.3)):
        assert round(past[level][0] / past[level][1] * 100, 1) == shown
        assert f"{past[level][0]}/{past[level][1]}" in screen


def test_level_steps_up_once_after_a_fall_and_never_past_high():
    assert a.level(0.2319, -2.65, -2.36) == {"base": "normal", "level": "high", "raised": True}  # 10/22
    assert a.level(0.10, -1.99, -4.99) == {"base": "low", "level": "low", "raised": False}
    assert a.level(0.10, 0.5, -5) == {"base": "low", "level": "normal", "raised": True}
    assert a.level(0.30, -4, -8) == {"base": "high", "level": "high", "raised": False}
    assert a.level(0.2608, 0, 0)["base"] == "high" and a.level(0.1473, 0, 0)["base"] == "normal"


def test_level_on_uses_twenty_returns_and_the_vix_before_the_tokyo_date():
    closes = [100 * (1 + 0.01 * math.sin(i)) for i in range(21)]
    rows = rows_for(closes)
    day = rows[-1]["date"]
    vix = [{"date": rows[-2]["date"], "close": 18.0}, {"date": day, "close": 40.0}]
    got = a.level_on(rows, vix, day, trading)
    r = [closes[k] / closes[k - 1] - 1 for k in range(1, 21)]
    m = sum(r) / 20
    rv = math.sqrt(sum((x - m) ** 2 for x in r) / 19) * math.sqrt(250)
    assert got["status"] == "AVAILABLE" and got["vix"] == 18.0 and got["vixDate"] == rows[-2]["date"]
    assert got["rv20"] == round(rv, 4) and got["sigma"] == round((0.18 + rv) / 2, 4)
    assert got["dayPct"] == round((closes[-1] / closes[-2] - 1) * 100, 2)
    assert a.level_on(rows[:-1], vix, rows[-2]["date"], trading)["status"] == "DATA_SHORT"
    assert a.level_on(rows, [{"date": day, "close": 18.0}], day, trading)["status"] == "NO_VIX"
    gap = rows[:10] + rows[11:]
    assert a.level_on(gap + rows_for([100], "2026-09-30"), vix, "2026-09-30", trading)["status"] == "DATA_GAP"


def test_record_identity_ignores_the_recording_time_and_is_kept_once(tmp_path):
    import argus_analysis_history as history
    rows = rows_for([100 + i for i in range(21)])
    row = a.level_on(rows, [{"date": "2026-08-31", "close": 15.0}], rows[-1]["date"], trading)
    first = a.pre_record(row, recorded_at="2026-09-29T08:00:00Z")
    again = a.pre_record(row, recorded_at="2026-09-29T09:00:00Z")
    assert first["recordId"] == again["recordId"] and first["recordId"].startswith("cr-")
    assert first["rulesSha256"] == RESEARCH_RULES_SHA256 and first["actionAuthority"] is False
    path = tmp_path / "h.sqlite3"
    history.initialize(path)
    assert history.append_candidate_record(path, first)["inserted"]
    assert history.append_candidate_record(path, again) == {"inserted": False, "conflict": True}
    assert history.read_candidate_records(path) == [first]


def test_score_waits_for_five_later_lows_and_counts_minus_five_percent_or_lower():
    rows = rows_for([100.0] * 21 + [99, 98, 97, 96, 95.5])
    record = {"signalDate": rows[20]["date"], "close": 100.0}
    assert a.score(record, rows[:25], trading) == {"status": "PENDING"}
    rows[23]["low"] = 95.0                       # exactly -5 %
    got = a.score(record, rows, trading)
    assert got["status"] == "MATURED" and got["fell"] is True and got["windowEnd"] == rows[25]["date"]
    rows[23]["low"] = 95.01
    assert a.score(record, rows, trading)["fell"] is False
    rows[24]["low"] = None                       # no intraday low: never filled in
    assert a.score(record, rows, trading)["status"] == "PENDING"


def test_summary_counts_levels_and_raised_days_apart():
    def rec(day, level, raised):
        return {"schema": a.SCHEMA, "rulesVersion": a.RULES_VERSION, "signalDate": day, "level": level,
                "raised": raised, "recordId": "cr-" + day}
    records = [rec("2026-10-26", "high", True), rec("2026-10-27", "high", False), rec("2026-10-28", "low", False),
               rec("2026-10-29", "normal", False), {"schema": "candidate_record.v1", "recordId": "cr-x"}]
    outcomes = {"cr-2026-10-26": {"status": "MATURED", "fell": True}, "cr-2026-10-27": {"status": "MATURED", "fell": False},
                "cr-2026-10-28": {"status": "MATURED", "fell": False}}
    s = a.summarize(records, outcomes)
    assert s["recordedDays"] == 4 and s["pending"] == 1 and s["firstDay"] == "2026-10-26"
    assert s["byLevel"]["high"] == {"matured": 2, "fell": 1} and s["byLevel"]["raisedHigh"] == {"matured": 1, "fell": 1}
    assert s["byLevel"]["low"] == {"matured": 1, "fell": 0} and s["byLevel"]["normal"] == {"matured": 0, "fell": 0}


def _glue(monkeypatch, tmp_path):
    import argus_analysis_history as history
    import scanner
    path = tmp_path / "h.sqlite3"
    history.initialize(path)
    monkeypatch.setattr(scanner, "_DROP_ALERT", {"loaded": False, "records": [], "summary": None, "missed": [],
                                                 "lastSkip": None, "lastError": None})
    monkeypatch.setattr(scanner, "_drop_alert_trading_day", trading)
    monkeypatch.setattr(scanner, "_level_map_next_session", lambda day: weekdays(day, 2)[1])
    monkeypatch.setattr(scanner, "_JP_MARKET_ENGINE_INDEX_OHLCV_CACHE",
                        {"^VIX": {"data": [{"date": "2026-08-31", "close": 15.0}]}})
    rows = [{**row, "availableFrom": row["date"] + "T06:30:00Z"} for row in rows_for([100.0 + i for i in range(21)]
                                                                                     + [90.0, 120, 120, 120, 120, 120])]
    return scanner, history, str(path), rows


def test_glue_records_after_the_close_before_the_next_open_and_scores_later(monkeypatch, tmp_path):
    scanner, history, path, rows = _glue(monkeypatch, tmp_path)
    day = rows[20]["date"]
    scanner._drop_alert_warm(path, rows[:21], day + "T06:45:00Z")      # 15:45 JST: not yet
    assert history.read_candidate_records(path) == []
    scanner._drop_alert_warm(path, rows[:21], day + "T08:00:00Z")
    stored = history.read_candidate_records(path)
    assert [r["signalDate"] for r in stored] == [day] and stored[0]["recordedAt"] == day + "T08:00:00Z"
    # Later runs never rewrite it; the day after (a -10 % close) is recorded on its own evening.
    scanner._drop_alert_warm(path, rows[:22], rows[21]["date"] + "T09:00:00Z")
    assert [r["signalDate"] for r in history.read_candidate_records(path)] == [day, rows[21]["date"]]
    assert history.read_candidate_records(path)[0] == stored[0]
    scanner._drop_alert_warm(path, rows, "2026-12-31T00:00:00Z")
    summary = scanner._DROP_ALERT["summary"]
    assert summary["recordedDays"] == 2 and summary["pending"] == 0 and scanner._DROP_ALERT["missed"] == [rows[-1]["date"]]
    levels = [summary["byLevel"][key] for key in ("low", "normal", "high")]
    assert sum(v["matured"] for v in levels) == 2 and sum(v["fell"] for v in levels) == 1   # the fall to 90
    public = scanner._level_map_public()["dropAlert"]
    assert public["byLevel"] == summary["byLevel"] and public["lastError"] is None


def test_candidate_board_ignores_drop_alert_records(monkeypatch, tmp_path):
    scanner, history, path, rows = _glue(monkeypatch, tmp_path)
    scanner._drop_alert_warm(path, rows[:21], rows[20]["date"] + "T08:00:00Z")
    monkeypatch.setattr(scanner, "_CANDIDATES", {"loaded": False, "records": [], "views": [], "missed": [],
                                                 "scoreboard": None, "breadthDays": 0, "lastError": None})
    scanner._candidates_warm(path, rows, {}, "2026-12-31T00:00:00Z")
    assert scanner._CANDIDATES["records"] == [] and scanner._CANDIDATES["lastError"] is None
