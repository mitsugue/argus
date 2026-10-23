"""2026-10-22 (owner: moomoo is the primary US source): confirmed daily bars
come from moomoo through the bridge; Twelve Data is only the last resort."""
import importlib.util
import sys
import types
from datetime import date, datetime, timedelta, timezone

import pytest

import argus_market_clock
import argus_moomoo_us as mu
import scanner

# Thu 2026-10-22 23:00Z = 19:00 New York: the 10-22 session closed 3 h ago.
NOW = datetime(2026, 10, 22, 23, 0, tzinfo=timezone.utc)
END = date(2026, 10, 22)


def _sessions(end, count):
    days, day = [], end
    while len(days) < count:
        if argus_market_clock.is_trading_day(argus_market_clock.US_EQUITY, day):
            days.append(day)
        day -= timedelta(days=1)
    return sorted(days)


def _bars(end=END, count=30, base=100.0):
    return [[d.isoformat(), base + i, base + i + 1, base + i - 1, base + i + 0.5, 1000 + i]
            for i, d in enumerate(_sessions(end, count))]


# ── pure rules ──────────────────────────────────────────────────────────────

def test_rows_after_the_confirmed_day_or_on_holidays_are_refused():
    rows = _bars(count=3) + [
        ["2026-10-23", 1, 2, 0.5, 1.5, 10],      # not confirmed yet
        ["2026-10-24", 1, 2, 0.5, 1.5, 10],      # Saturday
        ["2026-10-19", 1, 0.5, 2, 1.5, 10],      # high < low
        ["bad", 1, 2, 0.5, 1.5, 10],
    ]
    kept, rejected = mu.normalize_daily_rows(
        rows, end=END, is_trading_day=lambda d: argus_market_clock.is_trading_day("US_EQUITY", d))
    assert [r[0] for r in kept] == [r[0] for r in _bars(count=3)]
    assert rejected == 4


def test_duplicate_dates_are_not_trusted():
    row = _bars(count=1)[0]
    kept, rejected = mu.normalize_daily_rows([row, list(row)], end=END)
    assert kept == [] and rejected == 2


def test_merge_appends_only_when_the_overlap_matches():
    stored = _bars(end=date(2026, 10, 20), count=20)
    incoming = _bars(count=22)[-5:]                      # overlaps 10-16..10-20, adds 10-21, 10-22
    incoming = [[r[0]] + [v for v in r[1:]] for r in incoming]
    for row in incoming:                                 # same prices on the same days
        same = next((s for s in stored if s[0] == row[0]), None)
        if same:
            row[1:] = same[1:]
    merged, status = mu.merge_daily_bars(stored, incoming, full=False)
    assert status == "appended" and merged[-1][0] == "2026-10-22" and len(merged) == 22
    changed = [list(r) for r in incoming]
    changed[0][4] = changed[0][4] * 0.99                 # a dividend re-adjusted the past
    kept, status = mu.merge_daily_bars(stored, changed, full=False)
    assert status == "overlap_mismatch" and kept == stored
    kept, status = mu.merge_daily_bars(stored, [["2026-10-22", 1, 2, 0.5, 1.5, 1]], full=False)
    assert status == "no_overlap" and kept == stored
    replaced, status = mu.merge_daily_bars(stored, incoming, full=True)
    assert status == "replaced" and replaced == incoming


def test_plan_requests_full_history_once_then_only_the_missing_days():
    index = {
        "SPY": mu.index_entry(_bars(), full_history=True, needs_refill=False, received_at="x"),
        "QQQ": mu.index_entry(_bars(end=date(2026, 10, 20)), full_history=True,
                              needs_refill=False, received_at="x"),
        "TLT": mu.index_entry(_bars(), full_history=True, needs_refill=True, received_at="x"),
    }
    plan = {item["symbol"]: item for item in mu.plan_daily_requests(
        ["SPY", "QQQ", "TLT", "NVDA", "nvda", "bad symbol"], index, end=END)}
    assert set(plan) == {"QQQ", "TLT", "NVDA"}
    assert plan["QQQ"]["full"] is False and plan["QQQ"]["start"] == "2026-10-06"
    assert plan["TLT"]["full"] is True and plan["NVDA"]["full"] is True
    assert plan["NVDA"]["start"] == (END - timedelta(days=mu.FULL_HISTORY_DAYS)).isoformat()
    assert plan["NVDA"]["code"] == "US.NVDA" and plan["NVDA"]["end"] == "2026-10-22"


# ── server ──────────────────────────────────────────────────────────────────

@pytest.fixture
def server(monkeypatch):
    monkeypatch.setattr(scanner.time, "time", lambda: NOW.timestamp())
    monkeypatch.setattr(scanner, "_require_admin", lambda: (True, None, 200))
    monkeypatch.setattr(scanner, "_verify_bridge_signature", lambda raw: (True, "test"))
    monkeypatch.setattr(scanner, "_MOOMOO_DAILY", {"index": {}, "mem": {}, "lastPushAt": None,
                                                    "lastStatus": None, "lastSaveError": None})
    monkeypatch.setattr(scanner, "_MOOMOO_DAILY_INTEREST", {})
    monkeypatch.setattr(scanner, "_moomoo_daily_dir", lambda: None)
    monkeypatch.setattr(scanner, "_TD_HISTORY_CACHE", {})
    monkeypatch.setattr(scanner, "_TD_TS_CACHE", {})
    monkeypatch.setattr(scanner, "_ETF_LAST_PRICE", {})
    monkeypatch.setattr(scanner, "_td_owner_us_members", lambda: ["NVDA"])
    td_calls = []
    monkeypatch.setattr(scanner, "_td_get", lambda kind, url, **kw: (
        td_calls.append((kind, (kw.get("params") or {}).get("symbol"))),
        (_ for _ in ()).throw(RuntimeError("no network in tests")))[1])
    return scanner.app.test_client(), td_calls


def _push(client, symbol, rows, full=True):
    return client.post("/api/argus/us-reference-push", json={
        "kind": "dailyBars", "symbol": symbol, "full": full, "rows": rows}).get_json()


def test_confirmed_end_waits_one_hour_after_the_close():
    at_close = datetime(2026, 10, 22, 20, 30, tzinfo=timezone.utc).timestamp()   # 16:30 New York
    assert scanner._moomoo_daily_end(at_close) == date(2026, 10, 21)
    assert scanner._moomoo_daily_end(NOW.timestamp()) == END


def test_received_bars_feed_the_etf_series_without_twelve_data(server):
    client, td_calls = server
    body = _push(client, "SPY", _bars())
    assert body["ok"] is True and body["status"] == "replaced" and body["accepted"] == 30
    series = scanner._td_timeseries(["SPY"])
    assert series["SPY"][0] == _bars()[-1][4] and len(series["SPY"]) == 22
    stash = scanner._ETF_LAST_PRICE["SPY"]
    assert stash["source"] == "moomoo" and stash["sourceTimestamp"] == "2026-10-22"
    assert stash["status"] == "delayed"
    assert td_calls == []


def test_history_and_chart_rows_say_moomoo(server):
    client, td_calls = server
    _push(client, "NVDA", _bars(count=40))
    history = scanner._td_price_history("NVDA")
    assert history["dates"][0] == "2026-10-22" and len(history["closes"]) == 40
    assert scanner._TD_HISTORY_CACHE["NVDA"]["provider"] == "moomoo"
    rows = scanner._chart_history("NVDA", "US")
    assert rows and {row["source"] for row in rows} == {"moomoo"}
    assert td_calls == []


def test_missing_bars_fall_back_to_twelve_data_and_ask_the_bridge(server, monkeypatch):
    client, td_calls = server
    monkeypatch.setattr(scanner, "_TWELVEDATA_API_KEY", "test-only")
    assert scanner._td_price_history("AMD") is None          # TD attempted (fails in tests)
    assert td_calls and td_calls[-1][1] == "AMD"
    assert "AMD" in scanner._MOOMOO_DAILY_INTEREST
    plan = client.get("/api/argus/us-universe?scope=reference").get_json()
    asked = {item["symbol"]: item for item in plan["daily"]}
    assert "AMD" in asked and asked["AMD"]["full"] is True
    assert {"SPY", "QQQ", "GLD", "XLRE", "SMH", "NVDA"} <= set(asked)
    assert plan["dailyEnd"] == "2026-10-22"


def test_stale_bars_are_not_used(server):
    client, td_calls = server
    _push(client, "SPY", _bars(end=date(2026, 10, 9)))       # 13 days old
    provider = []
    import pytest as _pytest
    mp = _pytest.MonkeyPatch()
    mp.setattr(scanner, "_td_timeseries_provider", lambda syms: provider.append(list(syms)) or {})
    try:
        assert scanner._td_timeseries(["SPY"]) == {}
    finally:
        mp.undo()
    assert provider == [["SPY"]]


def test_up_to_date_symbols_are_not_requested_and_a_mismatch_asks_for_a_refill(server):
    client, _ = server
    _push(client, "SPY", _bars())
    plan = client.get("/api/argus/us-universe?scope=reference").get_json()
    assert "SPY" not in {item["symbol"] for item in plan["daily"]}
    # An incremental push whose overlapping day differs (re-adjusted history)
    changed = [list(r) for r in _bars()[-3:]]
    changed[0][4] += 5
    body = _push(client, "SPY", changed, full=False)
    assert body["status"] == "overlap_mismatch"
    assert scanner._MOOMOO_DAILY["index"]["SPY"]["needsRefill"] is True
    plan = client.get("/api/argus/us-universe?scope=reference").get_json()
    spy = next(item for item in plan["daily"] if item["symbol"] == "SPY")
    assert spy["full"] is True


def test_provider_error_is_recorded_and_not_retried_the_same_day(server):
    client, _ = server
    body = client.post("/api/argus/us-reference-push", json={
        "kind": "dailyBars", "symbol": "XLRE", "error": "no_data"}).get_json()
    assert body["status"] == "provider_error"
    plan = client.get("/api/argus/us-universe?scope=reference").get_json()
    assert "XLRE" not in {item["symbol"] for item in plan["daily"]}
    bad = client.post("/api/argus/us-reference-push", json={
        "kind": "dailyBars", "symbol": "XLRE", "error": "Traceback: secret"})
    assert bad.status_code == 400


def test_reference_routes_require_admin(monkeypatch):
    monkeypatch.setattr(scanner, "_require_admin", lambda: (False, {"error": "auth_required"}, 401))
    client = scanner.app.test_client()
    assert client.get("/api/argus/us-universe?scope=reference").status_code == 401
    assert client.post("/api/argus/us-reference-push", json={"kind": "dailyBars"}).status_code == 401


def test_bars_survive_a_restart_on_the_persistent_disk(server, tmp_path, monkeypatch):
    client, _ = server
    monkeypatch.setattr(scanner, "_moomoo_daily_dir", lambda: str(tmp_path / "moomoo_us_daily"))
    _push(client, "QQQ", _bars())
    scanner._MOOMOO_DAILY["index"] = None                 # a new process
    assert scanner._td_timeseries(["QQQ"])["QQQ"][0] == _bars()[-1][4]


def test_realtime_price_is_put_in_front_of_a_confirmed_close(server, monkeypatch):
    client, _ = server
    _push(client, "SPY", _bars(end=date(2026, 10, 21)))
    in_session = datetime(2026, 10, 22, 15, 0, tzinfo=timezone.utc).timestamp()
    monkeypatch.setattr(scanner.time, "time", lambda: in_session)
    live = {"symbol": "SPY", "price": 999.0, "exchangeTs": in_session - 5, "realtimeEvidence": True}
    monkeypatch.setattr(scanner, "_PUSHED_QUOTES", {"JP": {}, "US": {"SPY": {"row": live, "ts": in_session - 5}}})
    series = scanner._etf_series_with_moomoo(["SPY"])
    assert series["SPY"][0] == 999.0 and series["SPY"][1] == _bars(end=date(2026, 10, 21))[-1][4]
    # An extended-hours row never becomes the regime's current value.
    monkeypatch.setattr(scanner, "_PUSHED_QUOTES", {"JP": {}, "US": {"SPY": {
        "row": {**live, "extendedHours": True, "priceSession": "PRE"}, "ts": in_session - 5}}})
    assert scanner._etf_series_with_moomoo(["SPY"])["SPY"][0] != 999.0


# ── bridge ──────────────────────────────────────────────────────────────────

def _bridge(monkeypatch):
    monkeypatch.setitem(sys.modules, "moomoo", types.SimpleNamespace(
        OpenQuoteContext=None, RET_OK=0,
        KLType=types.SimpleNamespace(K_DAY="K_DAY"), AuType=types.SimpleNamespace(QFQ="qfq")))
    spec = importlib.util.spec_from_file_location("moomoo_push_daily_test", "bridge/moomoo_push.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _DF:
    def __init__(self, rows):
        self._rows = rows

    def iterrows(self):
        for index, row in enumerate(self._rows):
            yield index, row


class _QC:
    def __init__(self, quota):
        self.quota = quota
        self.kline_calls = []

    def get_history_kl_quota(self, get_detail=False):
        return self.quota

    def request_history_kline(self, code, start=None, end=None, ktype=None, autype=None,
                              max_count=1000, page_req_key=None):
        self.kline_calls.append((code, start, end, ktype, autype, page_req_key))
        assert ktype == "K_DAY" and autype == "qfq"
        if page_req_key is None:
            return 0, _DF([{"time_key": "2026-10-21 00:00:00", "open": 1, "high": 2, "low": 0.5,
                            "close": 1.5, "volume": 10}]), b"next"
        return 0, _DF([{"time_key": "2026-10-22 00:00:00", "open": 1.5, "high": 2, "low": 1,
                        "close": 1.8, "volume": 12}]), None


def _plan(*symbols, full=True):
    return {"scope": "reference", "daily": [
        {"code": f"US.{s}", "symbol": s, "start": "2016-10-01", "end": "2026-10-22", "full": full}
        for s in symbols]}


def test_bridge_respects_the_quota_reserve_and_reports_it(monkeypatch):
    m = _bridge(monkeypatch)
    monkeypatch.setattr(m, "KLINE_QUOTA_RESERVE", 5)
    posted = []
    monkeypatch.setattr(m, "_post_reference", lambda payload: posted.append(payload) or True)
    # used 2, remain 6, SPY already pulled in the window (free to refresh)
    qc = _QC((0, (2, 6, [{"code": "US.SPY", "name": "SPY", "request_time": "2026-10-20 18:00:00"}])))
    state = {}
    sent = m.run_daily_reference_job(qc, _plan("SPY", "NVDA", "AMD"), state=state, sleep=lambda _: None)
    assert sent == 2
    assert [p["symbol"] for p in posted] == ["SPY", "NVDA"]          # AMD would cross the reserve
    assert posted[0]["rows"] == [["2026-10-21", 1.0, 2.0, 0.5, 1.5, 10.0],
                                 ["2026-10-22", 1.5, 2.0, 1.0, 1.8, 12.0]]
    assert posted[0]["full"] is True
    assert state["dailyKlineQuotaRemain"] == 5 and state["dailyKlineQuotaUsed"] == 3
    assert state["dailyKlineSkippedQuota"] == 1 and state["dailyKlineStatus"] == "quota_reserve_reached"
    heartbeat = m.build_heartbeat(state=state, disable_jp=True, now_iso="2026-10-22T23:00:00Z")
    assert heartbeat["dailyKlineQuotaRemain"] == 5
    assert "NVDA" not in str(heartbeat)


def test_bridge_does_not_fetch_when_the_quota_cannot_be_read(monkeypatch):
    m = _bridge(monkeypatch)
    monkeypatch.setattr(m, "_post_reference", lambda payload: (_ for _ in ()).throw(AssertionError()))
    qc = _QC((1, "quota service unavailable"))
    state = {}
    assert m.run_daily_reference_job(qc, _plan("SPY"), state=state, sleep=lambda _: None) == 0
    assert qc.kline_calls == [] and state["dailyKlineStatus"] == "quota_unknown"


def test_bridge_reports_a_provider_error_by_class_only(monkeypatch):
    m = _bridge(monkeypatch)
    posted = []
    monkeypatch.setattr(m, "_post_reference", lambda payload: posted.append(payload) or True)

    class Denied(_QC):
        def request_history_kline(self, code, **kw):
            return -1, "No permission for this market (account 12345)", None

    state = {}
    m.run_daily_reference_job(Denied((0, (0, 100, []))), _plan("SPY"), state=state, sleep=lambda _: None)
    assert posted == [{"kind": "dailyBars", "symbol": "SPY", "error": "permission"}]
    assert state["dailyKlineFailed"] == 1 and state["dailyKlineQuotaRemain"] == 100


def test_flat_quota_tuple_from_the_documented_example_is_understood(monkeypatch):
    m = _bridge(monkeypatch)
    used, remain, codes = m.read_kline_quota(_QC((0, (2, 98, {"code": "US.AAPL"}, {"code": "US.SPY"}))))
    assert (used, remain, codes) == (2, 98, {"US.AAPL", "US.SPY"})


def test_reference_worker_does_not_open_opend_without_work(monkeypatch):
    m = _bridge(monkeypatch)
    monkeypatch.setattr(m, "fetch_reference_plan", lambda: {"scope": "reference", "daily": []})
    monkeypatch.setattr(m, "OpenQuoteContext", lambda **kw: (_ for _ in ()).throw(AssertionError("opend")))
    m._reference_worker()
    assert m.STATE["dailyKlineStatus"] == "up_to_date"
