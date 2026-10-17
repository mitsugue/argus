"""Server wiring: per-company reads in bounded batches, durable rows, estimate on the calendar."""
import json
from datetime import date, datetime, timezone

import scanner
import jp_equity_event_calendar as cal


def _row(code, fdiv2q="40.0", fdivfy="50.0", disc="2026-08-07"):
    return {"Code": code + "0", "DiscDate": disc, "DocType": "1QFinancialStatements_Consolidated_JP", "CurPerType": "1Q",
            "CurFYEn": "2027-03-31", "FDiv1Q": "", "FDiv2Q": fdiv2q, "FDiv3Q": "", "FDivFY": fdivfy, "FDivAnn": "90.0", "Secret": "x"}


def _reset(monkeypatch, tmp_path):
    monkeypatch.setattr(scanner, "_JP_EARNINGS_BACKFILL_ATTEMPTS", {})
    scanner._JP_DIVIDEND_STORE.update(rows={}, fetchedAt={}, closes=None, restoreAttempted=False, lastError=None, requestsLastWarm=0)
    path = str(tmp_path / "jp_dividend_forecasts.json")
    monkeypatch.setattr(scanner, "_jp_dividend_path", lambda: path)
    monkeypatch.setattr(scanner, "_JQUANTS_API_KEY", "k")
    return path


def test_warm_reads_a_bounded_batch_keeps_only_the_newest_row_and_persists(monkeypatch, tmp_path):
    path = _reset(monkeypatch, tmp_path)
    calls = []
    def paginated(route, params, **kwargs):
        calls.append((route, params["code"]))
        code = params["code"]
        return [_row(code, "30.0", disc="2026-05-13"), _row(code, "40.0")]
    monkeypatch.setattr(scanner, "_jquants_paginated", paginated)
    codes = [f"{n:04d}" for n in range(1000, 1050)]
    scanner._jp_dividend_warm(codes)
    assert len(calls) == scanner._JP_DIVIDEND_PER_WARM == 20 and all(r == "/fins/summary" for r, _ in calls)
    stored = scanner._JP_DIVIDEND_STORE["rows"]["1000"]
    assert stored["FDiv2Q"] == "40.0" and "Secret" not in stored and scanner._JP_DIVIDEND_STORE["requestsLastWarm"] == 20
    # The next warm takes the companies not yet read; a fresh read is not repeated for a week.
    scanner._jp_dividend_warm(codes)
    assert len(calls) == 40 and len({c for _, c in calls}) == 40
    scanner._jp_dividend_warm(codes[:20])
    assert len(calls) == 40
    saved = json.load(open(path))
    assert saved["schemaVersion"] == "argus-jp-dividend-forecasts-v1" and len(saved["rows"]) == 40
    # A restart reads the file back.
    scanner._JP_DIVIDEND_STORE.update(rows={}, fetchedAt={}, restoreAttempted=False)
    scanner._jp_dividend_restore()
    assert len(scanner._JP_DIVIDEND_STORE["rows"]) == 40 and len(scanner._JP_DIVIDEND_STORE["fetchedAt"]) == 40


def test_a_failed_company_read_is_reported_not_fatal(monkeypatch, tmp_path):
    _reset(monkeypatch, tmp_path)
    def paginated(route, params, **kwargs):
        if params["code"] == "1001":
            raise RuntimeError("jquants_http_429")
        return [_row(params["code"])]
    monkeypatch.setattr(scanner, "_jquants_paginated", paginated)
    scanner._jp_dividend_warm(["1000", "1001", "1002"])
    assert scanner._JP_DIVIDEND_STORE["lastError"] == "RuntimeError" and set(scanner._JP_DIVIDEND_STORE["rows"]) == {"1000", "1002"}
    assert "1001" not in scanner._JP_DIVIDEND_STORE["fetchedAt"]            # retried at the next warm


def test_shared_lane_backfills_former_members_without_refreshing_completed_current_members(monkeypatch, tmp_path):
    import argus_earnings_history
    _reset(monkeypatch, tmp_path)
    current=[str(1000+i) for i in range(225)]
    former=[str(9000+i) for i in range(25)]
    monkeypatch.setattr(scanner,'_cost_policy_durable_enabled',lambda:True)
    monkeypatch.setattr(scanner,'_DURABILITY_PATHS',{'root':str(tmp_path)})
    monkeypatch.setattr(scanner,'_nikkei225_constituent_changes',lambda:{
        'schemaVersion':'nikkei225-constituent-changes-v1',
        'rows':[{'effective':'2026-10-01','removed':former,'added':current[:25]}]})
    monkeypatch.setattr(argus_earnings_history,'completed_codes',lambda *a,**k:set(current))
    monkeypatch.setattr(scanner,'_jp_earnings_history_retain',lambda *a,**k:None)
    scanner._JP_DIVIDEND_STORE['fetchedAt']={c:scanner.time.time() for c in current}
    calls=[]
    monkeypatch.setattr(scanner,'_jquants_paginated',lambda path,params,**kwargs:(calls.append(params['code']) or []))
    scanner._jp_dividend_warm(current)
    assert calls == former[:20]
    # Completed company proof is independent of date-cohort completeness.
    # The same five-minute retry gate applies to former constituents.
    scanner._jp_dividend_warm(current)
    assert calls == former


def test_the_calendar_shows_the_yen_estimate_with_coverage_on_the_ex_dividend_day(monkeypatch, tmp_path):
    _reset(monkeypatch, tmp_path)
    factors = {f"{n:04d}": 1.0 for n in range(1000, 1010)}
    monkeypatch.setitem(scanner._JP_INDEX_PROXY, "factors", {"factors": factors})
    scanner._JP_DIVIDEND_STORE.update(restoreAttempted=True, closes={"date": "2026-10-02", "values": {c: 1000.0 for c in factors}},
                                       rows={c: _row(c, "20.0", "30.0") for c in factors})
    monkeypatch.setitem(scanner._JP_MARKET_ENGINE_INDEX_OHLCV_CACHE, "^N225", {"data": [{"date": "2026-10-02", "close": 68309.46}]})
    estimates = scanner._jp_ex_dividend_estimates(date(2026, 10, 3))
    assert set(estimates) == {"2026-12", "2027-03", "2027-06", "2027-09", "2027-12"}
    march = estimates["2027-03"]                       # year-end 30 yen on 1,000 yen = 3%
    assert march["dropPct"] == 3.0 and march["dropYen"] == 2049.3 and march["membersCovered"] == 10
    assert estimates["2026-12"]["dropYen"] is None     # no third-quarter forecasts: not shown
    events = {row["eventId"]: row for row in cal.equity_event_calendar(
        now=datetime(2027, 3, 1, 3, 0, tzinfo=timezone.utc), horizon_days=45, ex_dividend=estimates)["events"]}
    text = events["jp-ex-dividend-2027-03"]["whatJa"]
    assert "約2,049円" in text and "約3.00%" in text and "10社" in text and "概算" in text
    assert "約2,049円" not in events["jp-last-cum-2027-03"]["whatJa"]
    # No estimates: the event reads as before.
    plain = {row["eventId"]: row for row in cal.equity_event_calendar(now=datetime(2027, 3, 1, 3, 0, tzinfo=timezone.utc), horizon_days=45)["events"]}
    assert "概算" not in plain["jp-ex-dividend-2027-03"]["whatJa"] and "目安" not in plain["jp-ex-dividend-2027-03"]["whatJa"]
