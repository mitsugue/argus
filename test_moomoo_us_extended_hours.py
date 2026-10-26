"""2026-10-22 (owner: moomoo is the primary US source): the bridge also sends
pre-market / after-hours / overnight prices, each with its own in-session
time, and the server uses them in place of the Twelve Data extended value."""
import importlib.util
import sys
import types
from datetime import datetime, timezone

import pytest
import pytz

import scanner

# 2026-10-22 (Thu): 09:00Z = 05:00 New York (PRE), 21:30Z = 17:30 (POST),
# 2026-10-23 05:00Z = 01:00 New York (OVERNIGHT, Thursday night session).
PRE_NOW = datetime(2026, 10, 22, 9, 0, tzinfo=timezone.utc)
POST_NOW = datetime(2026, 10, 22, 21, 30, tzinfo=timezone.utc)
NIGHT_NOW = datetime(2026, 10, 23, 5, 0, tzinfo=timezone.utc)


def _bridge(monkeypatch):
    monkeypatch.setitem(sys.modules, "moomoo", types.SimpleNamespace(OpenQuoteContext=None, RET_OK=0))
    spec = importlib.util.spec_from_file_location("moomoo_push_extended_test", "bridge/moomoo_push.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _DF:
    def __init__(self, rows):
        self._rows = rows

    def iterrows(self):
        for index, row in enumerate(self._rows):
            yield index, row


def _snap(code, **fields):
    row = {"code": code, "name": code.split(".")[1], "last_price": 100.0,
           "prev_close_price": 99.0, "volume": 1000}
    row.update(fields)
    return row


# ── bridge ──────────────────────────────────────────────────────────────────

def test_session_labels_follow_the_exchange_calendar(monkeypatch):
    m = _bridge(monkeypatch)
    assert m.us_quote_session(PRE_NOW) == "PRE"
    assert m.us_quote_session(POST_NOW) == "POST"
    assert m.us_quote_session(NIGHT_NOW) == "OVERNIGHT"
    assert m.us_quote_session(datetime(2026, 10, 22, 15, 0, tzinfo=timezone.utc)) == "REGULAR"
    assert m.us_quote_session(datetime(2026, 10, 24, 15, 0, tzinfo=timezone.utc)) is None  # Saturday


def test_extended_rows_carry_session_and_their_own_in_session_time(monkeypatch):
    m = _bridge(monkeypatch)
    df = _DF([
        _snap("US.NVDA", pre_price=101.5, pre_change_val=1.5, pre_change_rate=1.5,
              pre_high_price=102.0, pre_low_price=100.5, pre_volume=5000,
              update_time="2026-10-22 04:55:10"),
        # A pre-market value whose time is still yesterday's close is not a
        # pre-market observation: counted as unpriced, never re-stamped.
        _snap("US.AAPL", pre_price=230.0, pre_change_val=1.0, pre_change_rate=0.4,
              update_time="2026-10-21 16:00:00"),
        _snap("US.MU", pre_price=float("nan"), update_time="2026-10-22 04:59:00"),
    ])
    rows, unpriced = m.extended_rows_from_snapshot(df, "PRE", now=PRE_NOW)
    assert [r["symbol"] for r in rows] == ["NVDA"]
    assert sorted(unpriced) == ["AAPL", "MU"]
    row = rows[0]
    assert row["session"] == "PRE" and row["price"] == 101.5
    assert row["exchangeTs"] == row["extendedTs"] == "2026-10-22T08:55:10Z"
    assert row["changeAbs"] == 1.5 and row["changePct"] == 1.5
    assert row["high"] == 102.0 and row["volume"] == 5000 and row["regularClose"] == 100.0


def test_the_closing_print_at_the_boundary_is_not_an_after_hours_time(monkeypatch):
    m = _bridge(monkeypatch)
    df = _DF([_snap("US.NVDA", after_price=100.2, after_change_val=0.2, after_change_rate=0.2,
                    update_time="2026-10-22 16:00:00")])
    rows, unpriced = m.extended_rows_from_snapshot(df, "POST", now=POST_NOW)
    assert rows == [] and unpriced == ["NVDA"]


def test_post_cycle_pushes_only_after_hours_rows_and_reports_counts(monkeypatch):
    m = _bridge(monkeypatch)
    monkeypatch.setattr(m, "registered_us_codes", lambda: ["US.SPY", "US.NVDA"])
    posted = []

    class Ok:
        ok = True

        def json(self):
            return {"accepted": len(posted)}

    monkeypatch.setattr(m, "_push_quotes", lambda rows: (posted.extend(rows), Ok())[1])
    monkeypatch.setattr(m, "fetch_market_quotes",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("regular fetch")))

    class QC:
        def get_market_snapshot(self, codes):
            return 0, _DF([
                _snap("US.SPY", after_price=580.1, after_change_val=0.3, after_change_rate=0.05,
                      update_time="2026-10-22 17:29:50"),
                _snap("US.NVDA", after_price=None, update_time="2026-10-22 16:00:00"),
            ])

    state = {}
    monkeypatch.setattr(m, "STATE", state)
    assert m.shared_quote_cycle(QC(), now=POST_NOW) == 1
    assert [(r["symbol"], r["session"]) for r in posted] == [("SPY", "POST")]
    assert state["usExtendedPriced"] == 1 and state["usExtendedUnpriced"] == 1
    assert state["usExtendedStatus"] == "ok"
    heartbeat = m.build_heartbeat(state=state, disable_jp=True, now_iso="2026-10-22T21:30:00Z")
    assert heartbeat["usExtendedSession"] == "POST" and heartbeat["usExtendedPriced"] == 1
    assert "NVDA" not in str(heartbeat) and "SPY" not in str(heartbeat)


def test_overnight_without_any_price_is_reported_and_nothing_is_pushed(monkeypatch):
    m = _bridge(monkeypatch)
    monkeypatch.setattr(m, "registered_us_codes", lambda: ["US.SPY"])
    monkeypatch.setattr(m, "_push_quotes", lambda rows: (_ for _ in ()).throw(AssertionError("push")))

    class QC:
        def get_market_snapshot(self, codes):
            return 0, _DF([_snap("US.SPY", overnight_price=float("nan"),
                                 update_time="2026-10-22 16:00:00")])

    state = {}
    monkeypatch.setattr(m, "STATE", state)
    assert m.shared_quote_cycle(QC(), now=NIGHT_NOW) == 0
    assert state["usExtendedStatus"] == "no_price_in_session"
    assert state["usExtendedSession"] == "OVERNIGHT" and state["usExtendedUnpriced"] == 1


def test_main_starts_the_price_worker_in_extended_sessions(monkeypatch):
    m = _bridge(monkeypatch)
    events = []
    ticks = iter([0, 301])

    class Worker:
        def __init__(self, **kw):
            pass

        def start(self):
            events.append("worker")

        def is_alive(self):
            return False

    monkeypatch.setattr(m, "TOKEN", "test-only")
    monkeypatch.setattr(m, "OpenQuoteContext", object)
    monkeypatch.setattr(m, "quote_session_active", lambda now=None: True)
    monkeypatch.setattr(m, "shared_session_open", lambda now=None: False)
    monkeypatch.setattr(m, "reference_job_due", lambda clock, last: False)
    # The minute-bar job follows the real clock; keep it out of this test.
    monkeypatch.setattr(m, "vwap_job_due", lambda clock, last: False)
    monkeypatch.setattr(m, "Thread", Worker)
    monkeypatch.setattr(m.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(m, "send_heartbeat", lambda **kw: 200)

    def stop(_):
        if events:
            raise KeyboardInterrupt()

    monkeypatch.setattr(m.time, "sleep", stop)
    with pytest.raises(KeyboardInterrupt):
        m.main()
    assert events == ["worker"]


# ── server ──────────────────────────────────────────────────────────────────

def _admin(monkeypatch):
    monkeypatch.setattr(scanner, "_require_admin", lambda: (True, None, 200))
    monkeypatch.setattr(scanner, "_verify_bridge_signature", lambda raw: (True, "test"))
    monkeypatch.setattr(scanner, "_PUSHED_QUOTES", {"JP": {}, "US": {}})
    monkeypatch.setattr(scanner, "_PUSH_HISTORY", {"JP": {}, "US": {}})


def _push(monkeypatch, now, rows):
    monkeypatch.setattr(scanner.time, "time", lambda: now.timestamp())
    return scanner.app.test_client().post("/api/argus/quote-push",
                                          json={"stocks": rows, "source": "moomoo"}).get_json()


def test_server_accepts_an_in_session_extended_row_without_inventing_a_change(monkeypatch):
    _admin(monkeypatch)
    body = _push(monkeypatch, PRE_NOW, [
        {"market": "US", "symbol": "NVDA", "price": 101.5, "session": "PRE",
         "exchangeTs": "2026-10-22T08:55:10Z", "regularClose": 100.0},
        # time outside the current session → refused
        {"market": "US", "symbol": "AAPL", "price": 230.0, "session": "PRE",
         "exchangeTs": "2026-10-21T20:00:00Z"},
        # a session label that does not match now → refused
        {"market": "US", "symbol": "MU", "price": 120.0, "session": "POST",
         "exchangeTs": "2026-10-22T08:58:00Z"},
    ])
    assert body["accepted"] == 1
    row = scanner._PUSHED_QUOTES["US"]["NVDA"]["row"]
    assert row["priceSession"] == "PRE" and row["extendedHours"] is True
    assert row["extendedTs"] == "2026-10-22T08:55:10Z" and row["regularClose"] == 100.0
    assert row["changeAbs"] is None and row["changePct"] is None
    assert row["realtimeEvidence"] is True            # 5 minutes old, own source time
    # ...but an extended-hours price never becomes a decision consumer's current quote.
    assert scanner._decision_usable_quote_row(row, now_epoch=PRE_NOW.timestamp()) is None
    assert scanner._decision_usable_quote_row(
        row, now_epoch=PRE_NOW.timestamp(), allow_extended=True) is not None
    cached = scanner._quote_cached_only("NVDA", "US")
    assert cached["extendedHours"] is True and cached["decisionUsable"] is False
    assert "AAPL" not in scanner._PUSHED_QUOTES["US"] and "MU" not in scanner._PUSHED_QUOTES["US"]
    # Extended rows never feed acceleration history / event detection.
    assert scanner._PUSH_HISTORY["US"] == {}


def test_extended_bridge_rows_replace_the_twelve_data_extended_value(monkeypatch):
    now = POST_NOW.timestamp()
    post_row = {"symbol": "NVDA", "price": 100.4, "source": "moomoo-rt", "entitlement": "unknown",
                "exchangeTs": now - 30, "sourceTimestamp": now - 30, "status": "live",
                "realtimeEvidence": True, "priceSession": "POST", "extendedHours": True}
    regular_row = {**post_row, "symbol": "AAPL"}
    regular_row.pop("priceSession"); regular_row.pop("extendedHours")
    monkeypatch.setattr(scanner, "_PUSHED_QUOTES", {"JP": {}, "US": {
        "NVDA": {"row": post_row, "ts": now - 10}, "AAPL": {"row": regular_row, "ts": now - 10}}})
    covered = scanner._td_bridge_covered_rows(["NVDA", "AAPL"], now, "AFTER_HOURS")
    assert set(covered) == {"NVDA"}                      # a regular row is not an after-hours value
    assert scanner._td_bridge_covered_rows(["NVDA"], now, "PRE_MARKET") == {}
    assert set(scanner._td_bridge_covered_rows(["AAPL"], now, "REGULAR")) == {"AAPL"}
    assert scanner._td_bridge_covered_rows(["NVDA"], now, "REGULAR") == {}
    assert scanner._td_bridge_covered_rows(["NVDA"], now, "WEEKEND_CLOSED") == {}


def test_warm_tick_in_after_hours_does_not_fetch_bridge_covered_symbols(monkeypatch):
    now = POST_NOW.timestamp()
    row = {"symbol": "NVDA", "price": 100.4, "source": "moomoo-rt", "entitlement": "unknown",
           "exchangeTs": now - 30, "sourceTimestamp": now - 30, "status": "live",
           "realtimeEvidence": True, "priceSession": "POST", "extendedHours": True}
    monkeypatch.setattr(scanner, "_PUSHED_QUOTES", {"JP": {}, "US": {"NVDA": {"row": row, "ts": now - 5}}})
    monkeypatch.setattr(scanner, "_TWELVEDATA_API_KEY", "test-only")
    monkeypatch.setattr(scanner, "_td_us_session", lambda now_utc=None: "AFTER_HOURS")
    monkeypatch.setattr(scanner, "_td_warm_universe",
                        lambda now=None: {"symbols": ["NVDA", "MU"], "cadenceFit": {}})
    monkeypatch.setattr(scanner, "_US_WARM_ROWS", {})
    import argus_td_warm
    monkeypatch.setattr(scanner, "_TD_WARM_STATE", argus_td_warm.new_state())
    asked = []
    monkeypatch.setattr(scanner, "_us_fallback_fetch",
                        lambda batch: (asked.append(list(batch)) or ([], True, False, None)))
    scanner._td_warm_tick(POST_NOW)
    assert all("NVDA" not in batch for batch in asked)
    assert scanner._US_WARM_ROWS["NVDA"]["row"]["priceSession"] == "POST"
    assert scanner._TD_WARM_STATE["bridgeCovered"] == 1


def test_overlay_marks_an_overnight_price_as_overnight_not_as_the_close(monkeypatch):
    now = NIGHT_NOW.timestamp()
    monkeypatch.setattr(scanner.time, "time", lambda: now)
    row = {"symbol": "NVDA", "price": 101.0, "source": "moomoo-rt", "entitlement": "unknown",
           "exchangeTs": now - 40, "sourceTimestamp": now - 40, "status": "live",
           "realtimeEvidence": True, "priceSession": "OVERNIGHT", "extendedHours": True}
    monkeypatch.setattr(scanner, "_PUSHED_QUOTES", {"JP": {}, "US": {"NVDA": {"row": row, "ts": now - 5}}})
    import argus_market_clock

    real = argus_market_clock.market_session
    monkeypatch.setattr(argus_market_clock, "market_session",
                        lambda market, now_utc=None, **kw: real(market, NIGHT_NOW, **kw))
    out = scanner._overlay_pushed({"status": "mock", "stocks": []}, "US", ["NVDA"])
    stamped = out["stocks"][0]
    assert stamped["session"] == "OVERNIGHT" and stamped["extendedHours"] is True
    assert stamped["delayClass"] != "EOD"


def test_heartbeat_keeps_the_extended_counts(monkeypatch):
    _admin(monkeypatch)
    client = scanner.app.test_client()
    response = client.post("/api/argus/bridge/heartbeat", json={"heartbeat": {
        "bridgeVersion": "13.8.160", "usExtendedSession": "OVERNIGHT", "usExtendedPriced": 0,
        "usExtendedUnpriced": 9, "usExtendedStatus": "no_price_in_session", "secret": "x"}})
    assert response.status_code == 200
    stored = scanner._BRIDGE_HB["data"]
    assert stored["usExtendedStatus"] == "no_price_in_session" and stored["usExtendedUnpriced"] == 9
    assert "secret" not in stored
