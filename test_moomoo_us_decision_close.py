"""2026-10-23 (owner direction, relayed): outside the US regular session the
decision close for a US name comes from moomoo's confirmed daily bars, dated
the latest confirmed session. Extended-hours prices never enter decisions."""
from datetime import date, datetime, timedelta, timezone

import pytest

import argus_market_clock
import argus_td_warm
import scanner

# Fri 2026-10-23 09:00Z = 05:00 New York (pre-market); 10-22 closed 13 h ago.
PRE = datetime(2026, 10, 23, 9, 0, tzinfo=timezone.utc)
CONFIRMED = date(2026, 10, 22)


def _sessions(end, count):
    days, day = [], end
    while len(days) < count:
        if argus_market_clock.is_trading_day(argus_market_clock.US_EQUITY, day):
            days.append(day)
        day -= timedelta(days=1)
    return sorted(days)


def _bars(end=CONFIRMED, count=25):
    return [[d.isoformat(), 100 + i, 101 + i, 99 + i, 100.5 + i, 1000 + i]
            for i, d in enumerate(_sessions(end, count))]


@pytest.fixture
def store(monkeypatch):
    monkeypatch.setattr(scanner.time, "time", lambda: PRE.timestamp())
    monkeypatch.setattr(scanner, "_MOOMOO_DAILY", {"index": {}, "mem": {}, "lastPushAt": None,
                                                    "lastStatus": None, "lastSaveError": None})
    monkeypatch.setattr(scanner, "_moomoo_daily_dir", lambda: None)
    monkeypatch.setattr(scanner, "_td_us_session", lambda now_utc=None: "PRE_MARKET")
    monkeypatch.setattr(scanner, "_TWELVEDATA_API_KEY", None)
    monkeypatch.setattr(scanner, "_td_get", lambda *a, **k: (_ for _ in ()).throw(AssertionError("Twelve Data")))

    def put(sym, bars):
        scanner._moomoo_daily_receive(sym, bars, full=True, now_epoch=PRE.timestamp())
    return put


def test_offhours_decision_close_comes_from_the_confirmed_moomoo_bar(store):
    store("NVDA", _bars())
    extended = {"symbol": "NVDA", "price": 130.0, "source": "moomoo-rt", "status": "live",
                "realtimeEvidence": True, "extendedHours": True, "priceSession": "PRE",
                "sourceTimestamp": PRE.timestamp() - 30, "exchangeTs": PRE.timestamp() - 30,
                "entitlement": "unknown", "changePct": 2.0}
    usable = scanner._decision_usable_watch_quote_row(
        extended, "US", now_epoch=PRE.timestamp(), require_latest_completed=True)
    assert usable is not None
    assert usable["source"] == "moomoo" and usable["date"] == "2026-10-22"
    assert usable["price"] == _bars()[-1][4] != 130.0            # never the pre-market price
    assert usable["decisionSourceKind"] == "bounded_daily_close"
    assert usable["realtimeEvidence"] is False and usable["status"] == "delayed"


def test_yahoo_delayed_row_offhours_is_replaced_by_the_moomoo_close(store):
    store("MU", _bars())
    yahoo = {"symbol": "MU", "price": 99.0, "source": "yahoo-delayed", "status": "delayed",
             "date": "2026-10-22", "sourceTimestamp": "2026-10-22"}
    usable = scanner._decision_usable_watch_quote_row(yahoo, "US", now_epoch=PRE.timestamp())
    assert usable["source"] == "moomoo" and usable["price"] == _bars()[-1][4]


def test_old_or_unconfirmed_bars_do_not_pass(store, monkeypatch):
    store("AMD", _bars(end=date(2026, 10, 9)))                      # two weeks old
    row = {"symbol": "AMD", "price": 1.0, "source": "yahoo-delayed", "status": "delayed"}
    assert scanner._decision_usable_watch_quote_row(row, "US", now_epoch=PRE.timestamp()) is None
    # A "moomoo" row that was not built from a confirmed bar is refused.
    forged = {"symbol": "AMD", "price": 1.0, "source": "moomoo", "status": "delayed",
              "date": "2026-10-22", "sourceTimestamp": "2026-10-22"}
    assert scanner._decision_usable_watch_quote_row(forged, "US", now_epoch=PRE.timestamp()) is None
    # A bar dated after the confirmed day (close + 1 h) is refused.
    tooearly = {"symbol": "AMD", "date": "2026-10-23", "sourceTimestamp": "2026-10-23",
                "moomooDailyBar": True, "source": "moomoo", "status": "delayed", "price": 1.0}
    assert scanner._decision_usable_watch_quote_row(tooearly, "US", now_epoch=PRE.timestamp()) is None


def test_regular_session_decisions_are_unchanged(store, monkeypatch):
    store("NVDA", _bars(end=date(2026, 10, 21)))
    in_session = datetime(2026, 10, 22, 15, 0, tzinfo=timezone.utc).timestamp()
    monkeypatch.setattr(scanner, "_td_us_session", lambda now_utc=None: "REGULAR")
    yahoo = {"symbol": "NVDA", "price": 99.0, "source": "yahoo-delayed", "status": "delayed"}
    assert scanner._decision_usable_watch_quote_row(yahoo, "US", now_epoch=in_session) is None


def test_offhours_warm_tick_uses_the_moomoo_close_before_yahoo(store, monkeypatch):
    store("NVDA", _bars())
    monkeypatch.setattr(scanner, "_PUSHED_QUOTES", {"JP": {}, "US": {}})
    monkeypatch.setattr(scanner, "_US_WARM_ROWS", {})
    monkeypatch.setattr(scanner, "_TD_WARM_STATE", argus_td_warm.new_state())
    monkeypatch.setattr(scanner, "FINNHUB_API_KEY", "")
    monkeypatch.setattr(scanner, "_td_warm_universe",
                        lambda now=None: {"symbols": ["NVDA", "MU"], "cadenceFit": {}})
    asked = []
    monkeypatch.setattr(scanner, "_us_fallback_fetch",
                        lambda batch: (asked.append(list(batch)) or ([], True, False, None)))
    scanner._td_warm_tick(PRE)
    assert all("NVDA" not in batch for batch in asked)
    warm = scanner._US_WARM_ROWS["NVDA"]["row"]
    assert warm["source"] == "moomoo" and warm["date"] == "2026-10-22" and warm["delayClass"] == "EOD"
    assert scanner._TD_WARM_STATE["moomooDailyCloses"] == 1
    cached = scanner._quote_cached_only("NVDA", "US")
    assert scanner._decision_usable_watch_quote_row(
        cached, "US", now_epoch=PRE.timestamp())["source"] == "moomoo"
