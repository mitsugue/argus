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
    # Members with a forecast PER only (1111 and 2222): cap 1500 / income 30.
    assert result["forwardOnly"]["per"] == pytest.approx(1500.0 / 30.0)
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
    monkeypatch.setattr(scanner, "_level_map_history_path", lambda: str(path))
    monkeypatch.setattr(scanner, "_LEVEL_MAP", {"status": "NOT_RUN", "loaded": False, "eps": {}, "mornings": [],
                                                "lastAttemptAt": None, "lastError": None, "lastErrorReason": None,
                                                "estimatesLastWarm": 0, "missedMornings": [], "conflicts": 0,
                                                "lastCreatedAt": None})
    monkeypatch.setattr(scanner, "_JP_INDEX_PROXY", {**scanner._JP_INDEX_PROXY,
                                                     "factors": {"factors": {"1111": 1.0, "2222": 1.0}},
                                                     "weightsAsOf": "2026-08-31"})
    monkeypatch.setattr(scanner, "_JQUANTS_API_KEY", "test-only")
    # This fixture contains two synthetic members, not the production 225.
    # Keep its dated membership equally synthetic when checking completeness.
    monkeypatch.setattr(scanner, '_nikkei225_constituent_changes', lambda:{'rows':[
        {'effective':'2026-10-01','added':[],'removed':[]}]})
    monkeypatch.setattr(scanner, "_ai_now_iso", lambda: now)
    monkeypatch.setattr(scanner, "_level_map_remote", lambda: None)
    calls = []
    def valuation(day, headers):
        calls.append(day)
        return {"1111": {"MktCap": 1000.0, "FwdPER": 20.0}, "2222": {"MktCap": 1000.0, "FwdPER": 16.0}}
    monkeypatch.setattr(scanner, "_jq_valuation_for_date", valuation)
    rows = []
    for bar in bars([60000 * (1 + 0.01 * ((i % 12) - 6) / 6) for i in range(200)], start=date(2026, 1, 5)):
        rows.append({**bar, "availableFrom": bar["date"] + "T07:00:00Z"})
    return scanner, path, rows, calls


def test_partial_current_day_cannot_freeze_eps_and_complete_receipt_corrects_originals(monkeypatch,tmp_path):
    import argus_analysis_history as history
    import argus_level_map_backup as backup
    scanner,path,rows,_=_glue(monkeypatch,tmp_path,'2026-10-07T07:35:00Z')
    rows=[r for r in rows if r['date']<='2026-10-07']
    partial=lambda day,headers:{'1111':{'MktCap':1000,'FwdPER':20}}
    monkeypatch.setattr(scanner,'_jq_valuation_for_date',partial)
    monkeypatch.setattr(scanner,'_candidates_warm',lambda *a:None)
    monkeypatch.setattr(scanner,'_JQ_VALUATION_DAY_CACHE',{'2026-10-07':partial(None,None)})
    scanner._level_map_warm(rows,current_only=True)
    assert history.read_level_map_state(path)['eps']=={}
    assert scanner._LEVEL_MAP['status']=='WAITING_FOR_CURRENT_ESTIMATE'
    assert '2026-10-07' not in scanner._JQ_VALUATION_DAY_CACHE
    # Simulate the preserved legacy 25-of-225 receipt and its future map.
    bad={'date':'2026-10-07','eps':4549.812,'basis':m.EPS_BASIS,'recordedAt':'2026-10-07T06:51:26Z',
         'coverage':{'members':225,'missingMarketCap':200}}
    history.append_level_map_eps(path,bad)
    bad_morning=m.morning_map('2026-10-08',rows,{'2026-10-07':bad['eps']},
                             eps_records={'2026-10-07':bad},created_at='2026-10-07T06:51:27Z')
    history.append_level_map(path,bad_morning)
    scanner._LEVEL_MAP['loaded']=False
    complete=lambda day,headers:{'1111':{'MktCap':1000,'FwdPER':20},'2222':{'MktCap':1000,'FwdPER':16}}
    monkeypatch.setattr(scanner,'_jq_valuation_for_date',complete)
    scanner._level_map_warm(rows,current_only=True)
    state=history.read_level_map_state(path)
    assert state['eps']['2026-10-07']['coverage']['missingMarketCap']==0
    assert state['mornings'][0]['epsCoverage']['missingMarketCap']==0
    originals,corrections=history.read_level_map_eps_originals(path)
    assert originals['2026-10-07']==bad and len(corrections)==1
    original_mornings,corrections=history.read_level_map_eps_originals(path,morning=True)
    assert original_mornings['2026-10-08']==bad_morning and len(corrections)==1
    # The old objects and later corrected receipts both survive remote restore.
    remote=_FakeRemote();assert backup.synchronize(path,remote)['status']=='VERIFIED'
    fresh=tmp_path/'restored.sqlite3';history.initialize(fresh)
    assert backup.restore(fresh,remote)['restored']==4
    assert history.read_level_map_state(fresh)==state
    assert history.read_level_map_eps_originals(fresh)[0]['2026-10-07']==bad
    puts=remote.puts;assert backup.synchronize(path,remote)['written']==0 and remote.puts==puts


def test_valid_first_eps_and_opened_morning_cannot_be_rewritten(tmp_path):
    import argus_analysis_history as history
    path=tmp_path/'history.sqlite3';history.initialize(path)
    complete={'date':'2026-10-07','eps':4000,'basis':m.EPS_BASIS,'recordedAt':'2026-10-07T07:35:00Z',
              'coverage':{'members':225,'missingMarketCap':0}}
    history.append_level_map_eps(path,complete)
    with pytest.raises(ValueError,match='incomplete_original'):
        history.append_level_map_eps_correction(path,{**complete,'eps':4100,'recordedAt':'2026-10-07T08:05:00Z'})
    bad={'morningOf':'2026-10-08','recordId':'lm-'+'a'*32,'createdAt':'2026-10-07T07:00:00Z',
         'epsBasis':m.EPS_BASIS,'epsCoverage':{'members':225,'missingMarketCap':200}}
    history.append_level_map(path,bad)
    with pytest.raises(ValueError,match='preopen'):
        history.append_level_map_morning_correction(path,{**bad,'recordId':'lm-'+'b'*32,
            'epsCoverage':complete['coverage'],'createdAt':'2026-10-08T00:00:00Z'})
    assert history.read_level_map_state(path)=={'eps':{'2026-10-07':complete},'mornings':[bad]}


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
    assert record["epsBasis"] == m.EPS_BASIS and record["constituentsAsOf"] == "2026-08-31+入れ替え2026-10-01"
    scanner._level_map_warm(rows)                                      # no second map, no rewrite
    assert history.read_level_map_state(path)["mornings"] == [record]
    public = scanner._level_map_public()
    assert public["latest"]["morningOf"] == "2026-10-05" and public["remoteBackup"]["status"] == "NOT_CONFIGURED"
    assert public["score"]["preRegisteredOnly"] is True and public["score"]["mornings"] == 1
    assert public["retrospective"]["preRegisteredOnly"] is False
    assert public["retrospective"]["firstMorning"] >= "2026-06-01"


def test_glue_never_backdates_a_missed_morning_or_uses_an_open_session(monkeypatch, tmp_path):
    import argus_analysis_history as history
    scanner, path, rows, _ = _glue(monkeypatch, tmp_path, "2026-10-05T01:00:00Z")   # 10:00 JST Monday
    rows = [r for r in rows if r["date"] <= "2026-10-05"]
    scanner._level_map_warm(rows)                  # Monday's bar is not final: latest = Friday
    assert history.read_level_map_state(path)["mornings"] == []
    assert scanner._LEVEL_MAP["missedMornings"] == ["2026-10-05"]


def _session(day, close, high=None, low=None):
    return {"date": day, "close": close, "high": high or close, "low": low or close}


def test_touch_outcome_moving_line_stop_break_and_touch_day_close_rule():
    eps = {"2026-10-02": 100.0, "2026-10-05": 102.0}
    row = {"side": "UP", "kinds": ["PER_LINE"], "multiple": 10, "moving": True, "price": 1000.0}
    # Day 0 line 1000 (EPS of 10/2); day 1 line 1020 (EPS of 10/5): moving.
    sessions = [_session("2026-10-05", 985, high=990), _session("2026-10-06", 1010, high=1016, low=1005),
                _session("2026-10-07", 995, high=1000, low=995)]
    out = m.touch_outcome(row, sessions, eps)
    assert out["reachedOn"] == "2026-10-06" and out["lineAtReach"] == 1020.0
    assert out["state"] == "STOPPED"              # 2 % below 1020 = 999.6 reached on the next session
    # Touching session: an intraday dip 2 % back does not count, only the close.
    touch_day = [_session("2026-10-05", 1001, high=1002, low=975)]
    assert m.touch_outcome({**row, "moving": False}, touch_day, eps)["state"] == "OPEN"
    broke = [_session("2026-10-05", 1015, high=1025)]
    assert m.touch_outcome({**row, "moving": False}, broke, eps)["state"] == "BROKE"
    assert m.touch_outcome({**row, "moving": False}, [_session("2026-10-05", 900)], eps)["state"] == "PENDING"


def test_scores_count_phases_once_and_turning_points_against_any_whole_line():
    days = [f"2026-10-{d:02d}" for d in (5, 6, 7, 8, 9, 13, 14, 15, 16, 19, 20, 21, 22, 23, 26)]
    eps = {"2026-10-02": 100.0, **{d: 100.0 for d in days}}
    closes = [1700, 1750, 1790, 1798, 1760, 1720, 1690, 1650, 1700, 1720, 1700, 1690, 1680, 1690, 1700]
    prices = [_session("2026-10-02", 1700)] + [_session(d, c, high=c + 5, low=c - 5) for d, c in zip(days, closes)]
    record = lambda day: {"morningOf": day, "recordId": "lm-" + day, "rows": [
        {"side": "UP", "kinds": ["PER_LINE"], "multiple": 18, "moving": True, "price": 1800.0, "tier": "MAP"}],
        "atrGuides": {"UP": [1730, 1760, 1790], "DOWN": [1670, 1640, 1610]}}
    score = m.score_records([record("2026-10-05"), record("2026-10-06")], prices, eps)
    assert score["phases"] == 1                     # the same line touched from two mornings = one phase
    assert score["phaseOutcomes"]["STOPPED"] == 1
    turning = score["turningPoints"]
    top = next(a for a in turning["answers"] if a["kind"] == "TOP")
    assert top["date"] == "2026-10-08" and top["perLineHit"] is True     # 1803 vs 18 x 100
    assert turning["evaluated"] == len(turning["answers"])                # each turning point once
    assert turning["chanceExpected"] == pytest.approx(
        sum(0.02 * a["price"] / 100.0 for a in turning["answers"]), abs=1e-3)
    assert score["preRegisteredOnly"] is True and score["actionAuthority"] is False


class _FakeRemote:
    def __init__(self):
        self.files, self.versions, self.puts = {}, {}, 0
    def get(self, path):
        return (self.files.get(path), self.versions.get(path))
    def put(self, path, raw, *, expected_version):
        if self.versions.get(path) != expected_version:
            raise ValueError("conflict")
        self.files[path] = raw; self.versions[path] = f"v{self.puts}"; self.puts += 1


def test_level_map_remote_copy_is_immutable_and_restores_into_empty_tables(tmp_path):
    import argus_analysis_history as history
    import argus_level_map_backup as backup
    path = tmp_path / "h.sqlite3"
    history.initialize(path)
    record = {"morningOf": "2026-10-05", "recordId": "lm-" + "a" * 32, "createdAt": "2026-10-04T09:35:39Z", "rows": [1]}
    history.append_level_map(path, record)
    history.append_level_map_eps(path, {"date": "2026-10-02", "eps": 3987.78, "recordedAt": "2026-10-04T09:35:00Z"})
    remote = _FakeRemote()
    first = backup.synchronize(path, remote)
    assert first == {"status": "VERIFIED", "remoteCount": 2, "localCount": 2, "written": 2, "pending": 0}
    puts = remote.puts
    assert backup.synchronize(path, remote)["written"] == 0 and remote.puts == puts      # nothing rewritten
    # A disk loss: a new empty file restores every record, digest-checked.
    fresh = tmp_path / "fresh.sqlite3"
    history.initialize(fresh)
    assert backup.synchronize(fresh, remote)["status"] == "RESTORE_REQUIRED"
    assert backup.restore(fresh, remote) == {"status": "RESTORED", "restored": 2, "remoteCount": 2}
    assert history.read_level_map_state(fresh) == history.read_level_map_state(path)
    assert backup.restore(fresh, remote)["status"] == "LOCAL_NOT_EMPTY"
    # A tampered object is refused.
    other = tmp_path / "other.sqlite3"
    history.initialize(other)
    key = backup.PREFIX + "/mornings/2026-10-05.json"
    remote.files[key] = remote.files[key].replace(b"9:35:39", b"9:35:40")
    with pytest.raises(ValueError):
        backup.restore(other, remote)


def test_constituents_follow_published_changes_after_the_weight_table():
    import json, pathlib
    changes = json.loads((pathlib.Path(__file__).parent / "ops/calendar/nikkei225_constituent_changes.json").read_text())
    base = ["1332", "4902", "543A", "7004", "9984"]
    before, label_before = m.constituents_on("2026-09-30", base, "2026-08-31", changes)
    after, label_after = m.constituents_on("2026-10-01", base, "2026-08-31", changes)
    assert before == sorted(base) and label_before == "2026-08-31"
    assert after == sorted(["1332", "9984", "5016", "6525", "9697"]) and label_after == "2026-08-31+入れ替え2026-10-01"
    # A weight table already after the change is not changed again.
    assert m.constituents_on("2026-11-02", after, "2026-10-30", changes)[0] == after
    assert changes["sourceRef"].startswith("https://indexes.nikkei.co.jp/") and len(changes["sourceSha256"]) == 64
    # Before the table's date the later changes are undone: on 2026-03-31 the
    # April 2026 additions were not members yet and its removals still were.
    april = next(r for r in changes["rows"] if r["effective"] == "2026-04-01")
    march, label_march = m.constituents_on("2026-03-31", list(after) + april["added"], "2026-08-31", changes)
    assert set(april["removed"]) <= set(march) and not set(april["added"]) & set(march)
    assert label_march == "2026-08-31−逆算2026-04-01"
    assert len(changes["rows"]) == 31 and changes["rows"][0]["effective"] == "2016-10-03"


def test_a_valuation_day_is_all_pages_or_nothing(monkeypatch):
    import scanner
    pages = [
        (200, {"data": [{"Code": "72030", "Date": "2026-10-02", "MktCap": 1.0, "FwdPER": 10.0}], "pagination_key": "k"}),
        (429, {"message": "rate limited"}),
    ]
    class R:
        def __init__(self, code, body): self.status_code, self._body = code, body
        def json(self): return self._body
    monkeypatch.setattr(scanner.requests, "get", lambda *a, **k: R(*pages.pop(0)))
    monkeypatch.setattr(scanner, "_JQ_VALUATION_DAY_CACHE", {})
    assert scanner._jq_valuation_for_date("2026-10-02", {}) == {}
    assert "2026-10-02" not in scanner._JQ_VALUATION_DAY_CACHE


def test_collection_crossing_the_open_uses_completion_time_and_never_backdates_morning(monkeypatch, tmp_path):
    import argus_analysis_history as history
    scanner, path, rows, _ = _glue(monkeypatch, tmp_path, "2026-10-04T23:59:50Z")
    rows = [r for r in rows if r["date"] <= "2026-10-02"]
    original_fetch = scanner._jq_valuation_for_date
    clock = ["2026-10-04T23:59:50Z"]
    monkeypatch.setattr(scanner, "_ai_now_iso", lambda: clock[0])
    def arriving_after_open(day, headers):
        payload = original_fetch(day, headers)
        clock[0] = "2026-10-05T00:00:10Z"
        return payload
    monkeypatch.setattr(scanner, "_jq_valuation_for_date", arriving_after_open)
    scanner._level_map_warm(rows)
    state = history.read_level_map_state(path)
    assert state["eps"]["2026-10-02"]["recordedAt"] == "2026-10-05T00:00:10Z"
    assert state["mornings"] == []
    assert "2026-10-05" in scanner._LEVEL_MAP["missedMornings"]
