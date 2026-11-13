"""2026-11-13 の点検: 遅延の値は約15分遅れなのに、引けと同時に取得をやめていた。

日本株の値段は 15:29 の読みが最後で、画面は 15:14 の約定を夜0時まで出していた。
業種の地図は引けの直後の1回(15:20 ごろの値)で止まり、日経平均は平日の祝日を
場の時間として扱っていた。
"""
from datetime import datetime, timedelta, timezone
import json

import argus_index_live as live
import argus_jp_delayed_quotes as q
from argus_market_clock import JP_EQUITY, market_session
from jp_sector_heatmap_runtime import Runtime

JST = q.JST


def jst(*parts):
    return datetime(*parts, tzinfo=JST).timestamp()


def session_at(epoch):
    return market_session(JP_EQUITY, datetime.fromtimestamp(epoch, timezone.utc))


# ── 日本株の遅延の値段 ─────────────────────────────────────────────────

def test_the_grace_is_the_45_minutes_after_the_close_of_a_trading_day():
    for clock, expected in (((15, 29, 59), False), ((15, 30, 0), True), ((16, 14, 59), True),
                            ((16, 15, 0), False), ((18, 0, 0), False), ((9, 30, 0), False)):
        now = jst(2026, 11, 13, *clock)                       # Friday, a trading day
        assert q.in_close_grace(session_at(now), now) is expected, clock
    saturday = jst(2026, 11, 14, 15, 40)
    assert not q.in_close_grace(session_at(saturday), saturday)
    holiday = jst(2026, 11, 23, 15, 40)                       # Monday, 勤労感謝の日
    assert session_at(holiday)["isTradingDay"] is False
    assert not q.in_close_grace(session_at(holiday), holiday)
    assert not q.in_close_grace(None, holiday) and not q.in_close_grace({}, holiday)


def test_only_todays_closing_trade_counts_as_held():
    now = jst(2026, 11, 13, 15, 50)
    iso = lambda *parts: datetime(*parts, tzinfo=JST).astimezone(timezone.utc).isoformat()
    assert q.holds_close({"sourceTimestamp": iso(2026, 11, 13, 15, 30)}, now)
    assert not q.holds_close({"sourceTimestamp": iso(2026, 11, 13, 15, 14)}, now)
    assert not q.holds_close({"sourceTimestamp": iso(2026, 11, 12, 15, 30)}, now)
    for broken in (None, {}, {"sourceTimestamp": None}, {"sourceTimestamp": "not a time"}):
        assert not q.holds_close(broken, now)


class _Response:
    def __init__(self, value):
        self.value, self.status_code, self.closed = value, 200, False

    def iter_content(self, **kwargs):
        yield json.dumps(self.value).encode()

    def close(self):
        self.closed = True


def test_after_the_close_the_closing_trade_is_collected_and_then_left_alone():
    members = [{"market": "JP", "symbol": "1001", "enabled": True},
               {"market": "JP", "symbol": "1002", "enabled": True}]
    feed = {"1001": jst(2026, 11, 13, 15, 14), "1002": jst(2026, 11, 13, 15, 14)}
    clock = [jst(2026, 11, 13, 15, 29)]
    calls = []

    def get(url, **kwargs):
        symbol = url.rsplit("/", 1)[1].removesuffix(".T")
        calls.append(symbol)
        return _Response({"chart": {"result": [{"meta": {
            "symbol": symbol + ".T", "currency": "JPY", "regularMarketPrice": 123.5,
            "chartPreviousClose": 120, "regularMarketTime": feed[symbol]}}]}})

    def tick():
        calls.clear()
        collector.tick(get, lambda: members, epoch=lambda: clock[0])
        return sorted(calls)

    def held():
        rows = collector.document(["1001", "1002"], now=clock[0])["symbols"]
        return {symbol: datetime.fromisoformat(row["sourceTimestamp"]).astimezone(JST).strftime("%H:%M")
                for symbol, row in rows.items()}

    collector = q.Collector()
    assert tick() == ["1001", "1002"]                         # last round of the session
    assert held() == {"1001": "15:14", "1002": "15:14"}        # 15 minutes behind: not the close

    clock[0] = jst(2026, 11, 13, 15, 46)                       # the feed now has 1001's closing auction
    feed["1001"] = jst(2026, 11, 13, 15, 30)
    assert tick() == ["1001", "1002"]
    assert held() == {"1001": "15:30", "1002": "15:14"}

    clock[0] = jst(2026, 11, 13, 15, 48)                       # two minutes later: five-minute pacing
    assert tick() == []
    clock[0] = jst(2026, 11, 13, 15, 52)                       # 1001 holds the close and is left alone
    assert tick() == ["1002"]
    clock[0] = jst(2026, 11, 13, 16, 20)                       # after the grace nothing is read
    assert tick() == []
    assert held() == {"1001": "15:30", "1002": "15:14"}        # the retained times are never rewritten


def test_a_weekend_or_holiday_afternoon_still_reads_nothing():
    members = [{"market": "JP", "symbol": "1001", "enabled": True}]
    calls = []
    for when in (jst(2026, 11, 14, 15, 40), jst(2026, 11, 23, 15, 40)):
        q.Collector().tick(lambda *a, **k: calls.append(a), lambda: members, epoch=lambda: when)
    assert calls == []


# ── 業種の地図 ─────────────────────────────────────────────────────────

def test_the_sector_map_reads_until_the_delayed_feed_has_reached_the_close():
    calls = []

    def unavailable(*args, **kwargs):
        calls.append(args)
        raise OSError("offline")

    at = lambda hour, minute: datetime(2026, 11, 13, hour, minute, tzinfo=JST).astimezone(timezone.utc)
    runtime = Runtime(unavailable)
    assert runtime.tick(at(15, 15))                            # in session
    one_round = len(calls)
    assert one_round > 0
    assert runtime.tick(at(15, 35)) and len(calls) == 2 * one_round     # still a pre-close value
    assert runtime.tick(at(15, 55)) and len(calls) == 3 * one_round     # the close itself
    assert not runtime.tick(at(16, 15)) and not runtime.tick(at(18, 0))
    assert len(calls) == 3 * one_round


# ── 日経平均の現在値 ───────────────────────────────────────────────────

def test_a_weekday_exchange_holiday_is_not_a_session_window():
    assert live.session_window(datetime(2026, 11, 13, 1, 0, tzinfo=timezone.utc))        # Fri 10:00 JST
    assert not live.session_window(datetime(2026, 11, 23, 1, 0, tzinfo=timezone.utc))    # Mon 10:00 JST, holiday
    assert not live.session_window(datetime(2026, 12, 31, 1, 0, tzinfo=timezone.utc))    # Thu 10:00 JST, year end
    assert not live.session_window(datetime(2026, 11, 14, 1, 0, tzinfo=timezone.utc))    # Saturday


def test_the_settled_close_is_due_from_16_05():
    assert not live.settled_close_due(datetime(2026, 11, 13, 7, 4, tzinfo=timezone.utc))     # 16:04 JST
    assert live.settled_close_due(datetime(2026, 11, 13, 7, 5, tzinfo=timezone.utc))         # 16:05 JST
    assert not live.settled_close_due(datetime(2026, 11, 12, 23, 30, tzinfo=timezone.utc))   # 08:30 JST


def test_the_index_is_read_once_more_after_the_feed_has_caught_up(monkeypatch):
    monkeypatch.setattr(live, "_state", {"quote": None, "error": None, "thread": None,
                                         "futures": None, "futuresError": None})
    monkeypatch.setattr(live, "_registered_tick", None)
    times = [datetime(2026, 11, 13, 6, 46, tzinfo=timezone.utc)]      # Fri 15:46 JST, just outside the window
    index_reads = []

    class Done(Exception):
        pass

    class Response:
        status_code = 200

        def json(self):
            return {"chart": {"result": [{"meta": {
                "regularMarketPrice": 61000.0, "chartPreviousClose": 60500.0,
                "regularMarketTime": times[0].timestamp() - 900}}]}}

    def get(url, **kwargs):
        if live.SYMBOL in url:
            index_reads.append(times[0].astimezone(JST).strftime("%H:%M"))
        return Response()

    def sleep(seconds):
        times[0] = times[0] + timedelta(minutes=5)
        if times[0] >= datetime(2026, 11, 13, 7, 40, tzinfo=timezone.utc):
            raise Done()

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return times[0]

    monkeypatch.setattr(live, "datetime", Clock)
    try:
        live._loop(get, sleep, clock=lambda: 0.0)
    except Done:
        pass
    assert index_reads == ["15:46", "16:06"]
