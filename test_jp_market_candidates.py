from datetime import date, timedelta

import jp_market_candidates as c


def sessions_from(start, n):
    out, day = [], date.fromisoformat(start)
    while len(out) < n:
        if day.weekday() < 5:
            out.append(day.isoformat())
        day += timedelta(days=1)
    return out


def bar(day, o, h, l, cl):
    return {"date": day, "open": o, "high": h, "low": l, "close": cl}


def test_r1_target_and_break_level_follow_the_written_example():
    # trough close 63,484 -> peak close 68,957 (intraday high 68,995) -> close 66,100 (-4.1 %) confirms the top.
    days = sessions_from("2026-09-21", 12)
    closes = [64500, 63484, 64800, 66500, 68000, 68957, 68500, 67900, 66100, 65800, 65400, 65000]
    bars = [bar(d, cl, cl * 1.002, cl * 0.998, cl) for d, cl in zip(days, closes)]
    bars[5]["high"] = 68995.0
    signals = [s for s in c.detect_r1(bars) if s["direction"] == "down"]
    assert signals and signals[-1]["signalDate"] == days[8]
    s = signals[-1]
    assert round(s["fixedTarget"]) == 65575 and s["stop"] == 68995.0
    record = c.pre_record(s, entry_date=days[9], recorded_at="2026-10-02T07:00:00Z")
    assert record["entryDate"] == days[9] and record["instrument"] == "1360" and "entry" not in record
    full = c.materialize(record, bars=bars, eps_series={}, etf_bars_by_code={})
    assert full["entry"]["nikkeiAtEntry"] == 65800 and full["target"]["nikkei"] == s["fixedTarget"]
    assert c.score(full, bars, {})["outcome"] == "reached"


def test_gap_signals_are_decided_and_entered_at_the_same_open():
    days = sessions_from("2026-10-01", 3)
    etf = [bar(days[0], 800, 805, 795, 800.5), bar(days[1], 832.6, 840, 830, 835), bar(days[2], 768.0, 770, 760, 765)]
    got = c.detect_gap(etf, days)
    assert [(g["candidate"], g["signalDate"]) for g in got] == [("S1", days[1]), ("S2", days[2])]
    assert all(g["sameSessionEntry"] for g in got)


def test_per_line_target_moves_with_the_eps_and_same_session_both_is_ambiguous():
    days = sessions_from("2026-10-05", 4)
    bars = [bar(days[0], 68000, 68400, 67900, 68200), bar(days[1], 68200, 69100, 68100, 69000),
            bar(days[2], 69000, 71000, 64000, 70000), bar(days[3], 70000, 70500, 69800, 70200)]
    eps = {"2026-10-02": 4000.0, days[0]: 4000.0, days[1]: 3800.0}
    record = c.pre_record({"candidate": "S3", "signalDate": days[0]}, entry_date=days[1], recorded_at="x")
    full = c.materialize(record, bars=bars, eps_series=eps, etf_bars_by_code={})
    assert full["target"]["multiple"] == 18                    # floor(68200/4000)+1 with the EPS before the entry
    # Day 1 (EPS 4000): 72,000 not reached. Day 2 uses the EPS before it (3800): 68,400 reached,
    # but the low 64,000 also breaks 64,790 (−5 %): both on one session = ambiguous.
    out = c.score(full, bars, eps)
    assert out["outcome"] == "ambiguous" and out["outcomeDate"] == days[2]


def test_episode_rule_and_the_combination_window():
    days = sessions_from("2026-01-05", 30)
    assert c._episodes([days[3], days[5], days[12]], days) == [days[3], days[12]]
    assert c.detect_combo([days[2]], [days[5]], days) == [days[5]]
    assert c.detect_combo([days[2]], [days[9]], days) == []


def test_drop25_and_breadth_need_their_history():
    days = sessions_from("2026-01-05", 40)
    closes = [100.0] * 30 + [94.0] * 10
    bars = [bar(d, cl, cl, cl, cl) for d, cl in zip(days, closes)]
    assert c.detect_drop25(bars) == [days[30]]
    longer = sessions_from("2026-01-05", 60)
    breadth = {d: {"advancers": 50, "decliners": 100} for d in longer[20:]}
    assert c.detect_breadth80(breadth, longer) == [longer[44]]          # the first day with 25 complete days
    assert c.detect_breadth80({}, longer) == []


def test_scoreboard_marks_thin_candidates_and_the_two_without_data():
    rows = {r["candidate"]: r for r in c.summarize([], {})}
    assert rows["S6"]["dataStatus"] == "NOT_IN_PRODUCT" and rows["S7"]["dataStatus"] == "NOT_IN_PRODUCT"
    assert rows["R1"]["enoughRecords"] is False and rows["R1"]["records"] == 0


def _glue(monkeypatch, tmp_path, now):
    import argus_analysis_history as history
    import scanner
    path = tmp_path / "h.sqlite3"
    history.initialize(path)
    monkeypatch.setattr(scanner, "_CANDIDATES", {"loaded": False, "records": [], "views": [], "missed": [],
                                                 "scoreboard": None, "breadthDays": 0, "lastError": None})
    days = sessions_from("2026-08-03", 60)
    closes = [66000 + 40 * i for i in range(45)] + [67800, 66000, 64500, 63000, 62000] + [62000] * 10
    rows = [{"date": d, "open": cl, "high": cl * 1.003, "low": cl * 0.997, "close": cl,
             "availableFrom": d + "T07:00:00Z"} for d, cl in zip(days, closes)]
    etf_dates = list(reversed(days))
    monkeypatch.setattr(scanner, "_jq_price_history", lambda code: {"dates": etf_dates, "opens": [800.0] * 60,
                        "highs": [810.0] * 60, "lows": [790.0] * 60, "closes": [800.0] * 60})
    monkeypatch.setattr(scanner, "_MARKET_LEDGER", {"observations": []})
    return scanner, history, path, rows, days


def test_glue_records_before_the_entry_open_and_never_after(monkeypatch, tmp_path):
    scanner, history, path, rows, days = _glue(monkeypatch, tmp_path, None)
    # S4 fires when the close falls 5 % below the close 25 sessions earlier.
    s4 = [d for d in c.detect_drop25(c._bars_with_open(rows))]
    assert s4, "fixture must contain an S4 day"
    signal_day = s4[0]
    cut = [r for r in rows if r["date"] <= signal_day]
    before_open = signal_day + "T10:00:00Z"
    monkeypatch.setattr(scanner, "_CANDIDATE_START", days[0])
    scanner._candidates_warm(str(path), cut, {}, before_open)
    stored = history.read_candidate_records(path)
    assert [(r["candidate"], r["signalDate"]) for r in stored if r["candidate"] == "S4"] == [("S4", signal_day)]
    assert stored[-1]["recordedAt"] == before_open and "entry" not in stored[-1]
    # A later run after the entry open adds nothing and rewrites nothing.
    scanner._candidates_warm(str(path), rows, {}, "2026-12-31T00:00:00Z")
    assert history.read_candidate_records(path) == stored
    view = next(v for v in scanner._CANDIDATES["views"] if v["candidate"] == "S4")
    assert view["entry"]["date"] == scanner._level_map_next_session(signal_day)
    assert view["result"]["outcome"] in ("reached", "broken", "ambiguous", "expired", "open")


def test_glue_never_backdates_a_signal_found_after_the_entry_open(monkeypatch, tmp_path):
    scanner, history, path, rows, days = _glue(monkeypatch, tmp_path, None)
    signal_day = c.detect_drop25(c._bars_with_open(rows))[0]
    monkeypatch.setattr(scanner, "_CANDIDATE_START", days[0])
    scanner._candidates_warm(str(path), rows, {}, "2026-12-31T00:00:00Z")
    assert not [r for r in history.read_candidate_records(path) if r["candidate"] == "S4"]
    assert {"candidate": "S4", "signalDate": signal_day} in scanner._CANDIDATES["missed"]
