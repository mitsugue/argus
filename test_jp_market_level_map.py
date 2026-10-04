from datetime import date, timedelta

import pytest

import jp_market_level_map as m


def bars(closes, start=date(2026, 1, 5), spread=0.01):
    out, day = [], start
    for close in closes:
        while day.weekday() >= 5:
            day += timedelta(days=1)
        out.append({"date": day.isoformat(), "close": close, "high": close * (1 + spread), "low": close * (1 - spread)})
        day += timedelta(days=1)
    return out


def test_weighted_eps_is_market_cap_weighted_signed_and_counts_fills():
    rows = {
        "1111": {"MktCap": 1000.0, "FwdPER": 20.0},                      # income 50
        "2222": {"MktCap": 500.0, "FwdPER": -25.0},                      # loss -20, signed
        "3333": {"MktCap": 300.0, "FwdPER": None, "FwdEPS": None, "PER": 15.0},   # trailing 20
        "4444": {"MktCap": None, "FwdPER": 10.0},                        # no market cap
        "5555": {"MktCap": 200.0},                                       # no earnings at all
    }
    result = m.weighted_eps(rows, ["1111", "2222", "3333", "4444", "5555"], index_close=50000.0,
                            date="2026-10-02", constituents_as_of="2026-08-31")
    assert result["per"] == pytest.approx(1800.0 / 50.0)
    assert result["eps"] == pytest.approx(50000.0 / 36.0)
    cov = result["coverage"]
    assert (cov["forward"], cov["negativeForecast"], cov["filledFromTrailing"]) == (2, 1, 1)
    assert (cov["missingMarketCap"], cov["missingEarnings"], cov["members"]) == (1, 1, 5)
    assert result["officialValue"] is False and result["basis"] == m.EPS_BASIS
    assert "公式値ではありません" in result["labelJa"]


def test_forecast_without_per_uses_forward_eps_and_a_derived_price():
    rows = {"1111": {"MktCap": 1000.0, "FwdPER": None, "FwdEPS": -5.0, "PER": 10.0, "EPS": 10.0}}
    result = m.weighted_eps({**rows, "2222": {"MktCap": 1000.0, "FwdPER": 10.0}}, ["1111", "2222"],
                            index_close=1000.0, date="2026-10-02", constituents_as_of="2026-08-31")
    # price 100, forecast income 1000 * -5 / 100 = -50; other member 100.
    assert result["per"] == pytest.approx(2000.0 / 50.0)
    assert result["coverage"]["negativeForecast"] == 1


def test_atr_is_the_simple_mean_of_fourteen_true_ranges():
    series = bars([100 + i for i in range(20)], spread=0.0)
    for bar in series:
        bar["high"], bar["low"] = bar["close"] + 2, bar["close"] - 1
    # TR = max(H, prev C) - min(L, prev C) = (C+2) - (C-1) = 3 each day.
    assert m.atr(series) == pytest.approx(3.0)
    assert m.atr(series[:14]) is None


def test_zigzag_confirms_only_with_data_up_to_the_confirming_close():
    closes = [100, 101, 103, 102, 98.5, 97, 99, 101.5, 100]
    series = bars(closes, spread=0.0)
    series[2]["high"] = 104.0
    pivots = m.zigzag(series)
    assert pivots[0]["kind"] == "TOP" and pivots[0]["closeDate"] == series[2]["date"]
    assert pivots[0]["confirmedOn"] == series[4]["date"] and pivots[0]["price"] == 104.0
    assert pivots[1]["kind"] == "BOTTOM" and pivots[1]["confirmedOn"] == series[7]["date"]
    # Cut the data at the confirming session: the same pivots, nothing later.
    assert m.zigzag(series[:5]) == pivots[:1]


def test_morning_map_uses_only_sessions_and_estimates_before_the_morning():
    closes = [60000 * (1 + 0.006 * ((i % 20) - 10) / 10) for i in range(80)]
    series = bars(closes)
    day = "2026-04-27"
    eps = {b["date"]: 3500.0 for b in series}
    eps[day] = 9999.0                                            # the morning's own estimate is not used
    later = series + [{"date": "2026-05-01", "close": 1.0, "high": 1.0, "low": 1.0}]
    first = m.morning_map(day, series, eps, created_at="2026-04-26T21:00:00Z")
    again = m.morning_map(day, later, {**eps, "2026-04-28": 1.0}, created_at="2026-04-26T22:00:00Z")
    assert first["recordId"] == again["recordId"]                 # later rows change nothing
    assert first["eps"] == 3500.0 and first["epsDate"] < day
    assert first["previousSession"] < day
    lines = [r for r in first["rows"] if "PER_LINE" in r["kinds"]]
    assert all(r["price"] == pytest.approx(3500.0 * r["multiple"], rel=1e-6) for r in lines)
    for row in first["rows"]:
        assert (row["price"] > first["previousClose"]) == (row["side"] == "UP")
        assert row["bandJa"] in ("2割前後", "1〜2割", "1割未満") and row["pastFrequencyPct"] < 20
    assert sum(1 for r in first["rows"] if r["side"] == "UP") <= 3
    assert first["actionAuthority"] is False and first["pastFrequencyIsNotProbability"] is True
    assert any("確率ではありません" in note for note in first["fixedNotesJa"])


def test_frequency_bands_and_reach_tables_follow_the_versioned_tables():
    assert m.frequency("UP", 2.0) == {"bandJa": "2割前後", "pastFrequencyPct": 18.4, "table": m.FREQUENCY_TABLE_VERSION}
    assert m.frequency("DOWN", -1.2)["bandJa"] == "1〜2割"
    assert m.frequency("UP", 0.3)["bandJa"] == "1割未満"
    assert m.reach("UP", 2.0)["reachedWithin10SessionsPct"] == 38
    assert m.reach("DOWN", -1.2)["sessionsMedian"] == 3


def test_rows_within_half_a_percent_merge_into_one():
    rows = [m._row("UP", ["PER_LINE"], 70000.0, 68000.0, 1200.0, multiple=18),
            m._row("UP", ["SAME_MULTIPLE"], 70200.0, 68000.0, 1200.0, multiple=17.9)]
    merged = m._merge(rows)
    assert len(merged) == 1 and merged[0]["kinds"] == ["PER_LINE", "SAME_MULTIPLE"]
    assert merged[0]["price"] == 70000.0


def test_no_probability_words_or_actions_in_the_record():
    closes = [60000 + 300 * ((i % 9) - 4) for i in range(60)]
    record = m.morning_map("2026-03-30", bars(closes), {b["date"]: 3400.0 for b in bars(closes)},
                           created_at="2026-03-29T21:00:00Z")
    text = str(record)
    for word in ("BUY", "SELL", "買い", "売り", "必ず"):
        assert word not in text


def test_level_map_store_keeps_the_first_body_per_date(tmp_path):
    import argus_analysis_history as history
    path = tmp_path / "market_analysis_history.sqlite3"
    history.initialize(path)
    record = {"morningOf": "2026-10-05", "recordId": "lm-" + "a" * 32, "createdAt": "2026-10-04T21:00:00Z", "rows": [1]}
    assert history.append_level_map(path, record) == {"inserted": True, "conflict": False}
    assert history.append_level_map(path, record) == {"inserted": False, "conflict": False}
    changed = {**record, "recordId": "lm-" + "b" * 32, "rows": [2]}
    assert history.append_level_map(path, changed) == {"inserted": False, "conflict": True}
    eps = {"date": "2026-10-02", "eps": 3900.0, "recordedAt": "2026-10-04T20:00:00Z"}
    assert history.append_level_map_eps(path, eps)["inserted"] is True
    assert history.append_level_map_eps(path, {**eps, "eps": 1.0})["conflict"] is True
    state = history.read_level_map_state(path)
    assert state["mornings"] == [record] and state["eps"] == {"2026-10-02": eps}
    # The existing tables and their schema version are untouched.
    import sqlite3
    with sqlite3.connect(path) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM views").fetchone()[0] == 0
    with pytest.raises(ValueError):
        history.append_level_map(path, {**record, "recordId": "x"})


def test_reading_a_history_without_level_tables_is_empty(tmp_path):
    import argus_analysis_history as history
    path = tmp_path / "h.sqlite3"
    history.initialize(path)
    assert history.read_level_map_state(path) == {"eps": {}, "mornings": []}


def _glue(monkeypatch, tmp_path, now):
    import scanner
    path = tmp_path / "market_analysis_history.sqlite3"
    monkeypatch.setattr(scanner, "_market_brief_history_path", lambda: str(path))
    monkeypatch.setattr(scanner, "_LEVEL_MAP", {"status": "NOT_RUN", "loaded": False, "eps": {}, "mornings": [],
                                                "lastAttemptAt": None, "lastError": None, "lastErrorReason": None,
                                                "estimatesLastWarm": 0, "missedMornings": [], "conflicts": 0,
                                                "lastCreatedAt": None})
    monkeypatch.setattr(scanner, "_JP_INDEX_PROXY", {**scanner._JP_INDEX_PROXY,
                                                     "factors": {"factors": {"1111": 1.0, "2222": 1.0}},
                                                     "weightsAsOf": "2026-08-31"})
    monkeypatch.setattr(scanner, "_JQUANTS_API_KEY", "test-only")
    monkeypatch.setattr(scanner, "_ai_now_iso", lambda: now)
    calls = []
    def valuation(day, headers):
        calls.append(day)
        return {"1111": {"MktCap": 1000.0, "FwdPER": 20.0}, "2222": {"MktCap": 1000.0, "FwdPER": 16.0}}
    monkeypatch.setattr(scanner, "_jq_valuation_for_date", valuation)
    rows = []
    for bar in bars([60000 * (1 + 0.01 * ((i % 12) - 6) / 6) for i in range(200)], start=date(2026, 1, 5)):
        rows.append({**bar, "availableFrom": bar["date"] + "T07:00:00Z"})
    return scanner, path, rows, calls


def test_glue_stores_the_estimate_and_one_morning_map_before_the_open(monkeypatch, tmp_path):
    import argus_analysis_history as history
    scanner, path, rows, calls = _glue(monkeypatch, tmp_path, "2026-10-04T12:00:00Z")
    rows = [r for r in rows if r["date"] <= "2026-10-02"]
    scanner._level_map_warm(rows)
    state = history.read_level_map_state(path)
    assert "2026-10-02" in state["eps"] and calls[0] == "2026-10-02"
    assert [m["morningOf"] for m in state["mornings"]] == ["2026-10-05"]
    record = state["mornings"][0]
    assert record["previousSession"] == "2026-10-02" and record["epsDate"] == "2026-10-02"
    assert record["epsBasis"] == m.EPS_BASIS and record["constituentsAsOf"] == "2026-08-31"
    scanner._level_map_warm(rows)                                      # no second map, no rewrite
    assert history.read_level_map_state(path)["mornings"] == [record]
    public = scanner._level_map_public()
    assert public["latest"]["morningOf"] == "2026-10-05" and public["remoteBackup"] == "NOT_YET_INCLUDED"


def test_glue_never_backdates_a_missed_morning_or_uses_an_open_session(monkeypatch, tmp_path):
    import argus_analysis_history as history
    scanner, path, rows, _ = _glue(monkeypatch, tmp_path, "2026-10-05T01:00:00Z")   # 10:00 JST Monday
    rows = [r for r in rows if r["date"] <= "2026-10-05"]
    scanner._level_map_warm(rows)                  # Monday's bar is not final: latest = Friday
    assert history.read_level_map_state(path)["mornings"] == []
    assert scanner._LEVEL_MAP["missedMornings"] == ["2026-10-05"]
