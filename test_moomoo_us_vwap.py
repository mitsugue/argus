"""2026-10-23 (owner approval): the session VWAP comes from moomoo's same-day
5-minute bars (regular hours only), pushed by the bridge. Twelve Data is not used;
missing or stale bars leave VWAP uncomputed."""
import importlib.util
import sys
import types
from datetime import datetime, timezone

import pytest

import scanner

# Thu 2026-10-22 15:00Z = 11:00 New York (regular session).
NOW = datetime(2026, 10, 22, 15, 0, tzinfo=timezone.utc).timestamp()
DAY = "2026-10-22"


def _bars(count=12, day=DAY):
    rows = []
    for i in range(count):
        minute = 30 + 5 * i
        key = f"{day} {9 + minute // 60:02d}:{minute % 60:02d}:00"
        rows.append([key, 101.0 + i, 99.0 + i, 100.0 + i, 1000 + 10 * i])
    return rows


@pytest.fixture
def server(monkeypatch):
    monkeypatch.setattr(scanner.time, "time", lambda: NOW)
    monkeypatch.setattr(scanner, "_require_admin", lambda: (True, None, 200))
    monkeypatch.setattr(scanner, "_verify_bridge_signature", lambda raw: (True, "test"))
    monkeypatch.setattr(scanner, "_MOOMOO_INTRADAY5M", {})
    monkeypatch.setattr(scanner, "_VWAP_CACHE", {"data": None, "expires": 0.0})
    monkeypatch.setattr(scanner, "_US_WATCHLIST", [{"symbol": "AAPL"}, {"symbol": "NVDA"}])
    td_calls = []
    monkeypatch.setattr(scanner, "_td_get", lambda *a, **kw: td_calls.append(a) or None)
    return scanner.app.test_client(), td_calls


def _push(client, symbol, bars, day=DAY):
    return client.post("/api/argus/us-reference-push", json={
        "kind": "intraday5m", "symbol": symbol, "sessionDate": day, "bars": bars})


def test_plan_asks_for_todays_bars_only_in_the_regular_session(server, monkeypatch):
    client, _ = server
    plan = client.get("/api/argus/us-universe?scope=reference").get_json()
    assert plan["vwap"] == ["US.AAPL", "US.NVDA"] and plan["vwapSessionDate"] == DAY
    monkeypatch.setattr(scanner, "_us_market_open", lambda now_et=None: False)
    plan = client.get("/api/argus/us-universe?scope=reference").get_json()
    assert plan["vwap"] == [] and plan["vwapSessionDate"] is None


def test_pushed_bars_compute_the_session_vwap_without_twelve_data(server):
    client, td_calls = server
    assert _push(client, "AAPL", _bars()).status_code == 200
    probe = scanner._vwap_probe()
    assert probe["computed"] is True and set(probe["values"]) == {"AAPL"}
    import argus_market_depth
    expected = argus_market_depth.compute_vwap(
        [{"high": b[1], "low": b[2], "close": b[3], "volume": b[4]} for b in _bars()])
    assert probe["values"]["AAPL"] == expected
    assert td_calls == []


def test_missing_or_stale_bars_leave_vwap_uncomputed(server, monkeypatch):
    client, td_calls = server
    assert scanner._vwap_probe()["computed"] is False
    _push(client, "AAPL", _bars())
    monkeypatch.setattr(scanner, "_VWAP_CACHE", {"data": None, "expires": 0.0})
    monkeypatch.setattr(scanner.time, "time", lambda: NOW + scanner._VWAP_BARS_MAX_AGE_SEC + 1)
    assert scanner._vwap_probe()["computed"] is False
    assert td_calls == []


@pytest.mark.parametrize("bars,day", [
    (_bars(day="2026-10-21"), "2026-10-21"),                      # not today's session
    ([["2026-10-22 09:35:00", 99.0, 101.0, 100.0, 10]], DAY),     # high < low
    ([["2026-10-22 09:40:00", 101.0, 99.0, 100.0, 10],
      ["2026-10-22 09:35:00", 101.0, 99.0, 100.0, 10]], DAY),     # out of order
    ([["2026-10-21 15:55:00", 101.0, 99.0, 100.0, 10]], DAY),     # yesterday's bar
    ([], DAY),
])
def test_bad_bars_are_refused(server, bars, day):
    client, _ = server
    assert _push(client, "AAPL", bars, day).status_code == 400
    assert scanner._MOOMOO_INTRADAY5M == {}


# ── bridge side ─────────────────────────────────────────────────────────────

def _bridge():
    spec = importlib.util.spec_from_file_location("bridge_vwap_test", "bridge/moomoo_push.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("moomoo", types.ModuleType("moomoo"))
    spec.loader.exec_module(module)
    return module


class _Frame:
    def __init__(self, rows):
        self.rows = rows

    def iterrows(self):
        return enumerate(self.rows)


class _Quote:
    def __init__(self, remain=50, pulled=()):
        self.remain, self.pulled, self.asked = remain, list(pulled), []

    def get_history_kl_quota(self, get_detail=True):
        return 0, [100 - self.remain, self.remain, [{"code": c} for c in self.pulled]]

    def request_history_kline(self, code, **kw):
        self.asked.append((code, kw.get("start"), kw.get("end"), kw.get("ktype")))
        rows = [{"time_key": b[0], "high": b[1], "low": b[2], "close": b[3], "volume": b[4]}
                for b in _bars(3)] + [{"time_key": "2026-10-21 15:55:00", "high": 1,
                                       "low": 1, "close": 1, "volume": 1}]
        return 0, _Frame(rows), None


def test_bridge_sends_only_todays_bars_and_respects_the_quota_reserve(monkeypatch):
    bridge = _bridge()
    monkeypatch.setattr(bridge, "RET_OK", 0)
    monkeypatch.setattr(bridge.time, "sleep", lambda s: None)
    posted = []
    monkeypatch.setattr(bridge, "_post_reference", lambda payload: posted.append(payload) or True)
    state = {}
    qc = _Quote(remain=bridge.KLINE_QUOTA_RESERVE + 1, pulled=["US.AAPL"])
    sent = bridge.run_vwap_job(qc, {"vwap": ["US.AAPL", "US.NVDA", "US.TSLA"],
                                    "vwapSessionDate": DAY}, state=state)
    # AAPL is already in the quota window; one new symbol fits above the reserve.
    assert sent == 2 and [p["symbol"] for p in posted] == ["AAPL", "NVDA"]
    assert state["vwapSkipped"] == 1
    assert all(len(p["bars"]) == 3 and all(b[0].startswith(DAY) for b in p["bars"]) for p in posted)
    assert all(start == DAY and end == DAY for _, start, end, _ in qc.asked)


def test_bridge_does_not_fetch_without_a_known_quota(monkeypatch):
    bridge = _bridge()
    monkeypatch.setattr(bridge, "RET_OK", 0)

    class _NoQuota(_Quote):
        def get_history_kl_quota(self, get_detail=True):
            return 1, "error"

    qc = _NoQuota()
    state = {}
    assert bridge.run_vwap_job(qc, {"vwap": ["US.AAPL"], "vwapSessionDate": DAY}, state=state) == 0
    assert qc.asked == [] and state["vwapStatus"] == "quota_unknown"


def test_bridge_vwap_job_runs_only_in_the_regular_session(monkeypatch):
    bridge = _bridge()
    monkeypatch.setattr(bridge, "us_quote_session", lambda now=None: "REGULAR")
    assert bridge.vwap_job_due(10_000, 0) is True
    assert bridge.vwap_job_due(10, 0) is False
    monkeypatch.setattr(bridge, "us_quote_session", lambda now=None: "POST")
    assert bridge.vwap_job_due(10_000, 0) is False


def test_bridge_status_counts_received_and_computed_vwap(server):
    client, _ = server
    _push(client, "AAPL", _bars())
    status = scanner._moomoo_vwap_status()
    assert status == {"sessionDate": DAY, "requestedSymbols": 2, "receivedSymbols": 1, "freshSymbols": 1,
                      "computedSymbols": 1, "bars": 12, "lastReceivedAt": "2026-10-22T15:00:00Z"}
    later = scanner._moomoo_vwap_status(now_epoch=NOW + scanner._VWAP_BARS_MAX_AGE_SEC + 1)
    assert later["receivedSymbols"] == 1 and later["computedSymbols"] == 0


def test_heartbeat_carries_the_vwap_counts():
    bridge = _bridge()
    state = {"vwapStatus": "ok", "vwapSent": 4, "vwapSkipped": 0, "vwapFailed": 0, "vwapCheckedAt": "x"}
    hb = bridge.build_heartbeat(state=state, disable_jp=True, now_iso="2026-10-22T15:00:00Z")
    assert hb["vwapStatus"] == "ok" and hb["vwapSent"] == 4
    assert all(key in scanner._HB_ALLOWED_KEYS for key in ("vwapStatus", "vwapSent", "vwapSkipped", "vwapFailed", "vwapCheckedAt"))
