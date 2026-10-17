"""Owner-fixed update times of the integrated view (2026-10-17)."""
from datetime import date, datetime, timedelta, timezone

import argus_brief_schedule as bs

JST = bs.JST


def at(text):
    return datetime.fromisoformat(text).replace(tzinfo=JST)


def weekdays(day):
    return day.weekday() < 5


def test_the_owner_times_on_trading_days_and_two_on_closed_days():
    assert bs.TRADING_DAY_SLOTS == ("07:00", "08:00", "09:15", "10:00", "12:00", "13:00",
                                    "15:45", "17:00", "20:00", "22:00", "24:00")
    assert bs.CLOSED_DAY_SLOTS == ("08:00", "20:00") and bs.EVENT_EDITIONS_PER_DAY == 3
    friday = bs.slots_for_day(date(2026, 10, 16), True)
    assert friday[-1][0] == at("2026-10-17T00:00")          # 24:00 is the next midnight
    assert [label for _, label in bs.slots_for_day(date(2026, 10, 17), False)] == ["08:00", "20:00"]


def test_latest_slot_reads_yesterdays_midnight_and_weekends():
    assert bs.latest_slot(at("2026-10-17T00:30"), weekdays)[1] == "2026-10-16 24:00"
    assert bs.latest_slot(at("2026-10-17T07:30"), weekdays)[1] == "2026-10-16 24:00"   # Saturday: no 07:00
    assert bs.latest_slot(at("2026-10-17T08:05"), weekdays)[1] == "2026-10-17 08:00"
    assert bs.latest_slot(at("2026-10-19T00:30"), weekdays)[1] == "2026-10-18 20:00"   # Sunday has no 24:00
    assert bs.latest_slot(at("2026-10-19T09:20"), weekdays)[1] == "2026-10-19 09:15"


def test_a_slot_is_due_once_after_it_passes():
    common = dict(is_trading_day=weekdays, covered_slot=None)
    assert not bs.decide(now=at("2026-10-19T09:10"), last_edition_at=at("2026-10-19T08:01"), **common)["due"]
    due = bs.decide(now=at("2026-10-19T09:16"), last_edition_at=at("2026-10-19T08:01"), **common)
    assert due["due"] and due["kind"] == "SCHEDULED" and due["slot"] == "2026-10-19 09:15"
    # Written after the slot, or already checked with unchanged inputs: not due.
    assert not bs.decide(now=at("2026-10-19T09:40"), last_edition_at=at("2026-10-19T09:17"), **common)["due"]
    assert not bs.decide(now=at("2026-10-19T09:40"), last_edition_at=at("2026-10-19T08:01"),
                         is_trading_day=weekdays, covered_slot="2026-10-19 09:15")["due"]
    # No saved edition at all: the latest slot is due.
    assert bs.decide(now=at("2026-10-19T09:40"), last_edition_at=None, **common)["due"]


def test_a_release_after_the_edition_adds_one_edition_up_to_three_a_day():
    release = [{"eventId": "cpi-2026-10", "sourceReceivedAt": "2026-10-15T12:31:00Z"}]   # 21:31 JST
    base = dict(now=at("2026-10-15T21:35"), last_edition_at=at("2026-10-15T20:01"),
                covered_slot="2026-10-15 20:00", is_trading_day=weekdays, released_events=release)
    due = bs.decide(**base)
    assert due["due"] and due["kind"] == "EVENT" and due["eventIds"] == ["cpi-2026-10"]
    assert not bs.decide(**base, handled_event_ids=["cpi-2026-10"])["due"]
    limited = bs.decide(**base, event_editions_today=3)
    assert not limited["due"] and limited["reason"] == "event_limit_reached"
    # A release received before the last edition is already in it.
    assert not bs.decide(**{**base, "last_edition_at": at("2026-10-15T21:33")})["due"]


def test_what_changed_between_two_editions():
    digest = lambda v: str(v)
    before = [{"source": "official_sensor", "text": "VIX 18"}, {"source": "trusted_mail", "text": "a"}]
    after = [{"source": "official_sensor", "text": "VIX 19"}, {"source": "trusted_mail", "text": "a"},
             {"source": "official_macro_result", "text": "CPI"}]
    assert bs.changed_groups(before, after, digest) == ["official_macro_result", "official_sensor"]
    assert bs.wording_change({"nowJa": "様子見", "whyJa": "x"}, {"nowJa": "様子見", "whyJa": "y"}) == \
        {"conclusion": False, "sections": ["whyJa"]}


def test_the_worker_composes_nothing_between_update_times(monkeypatch):
    import threading
    import scanner
    clock = [5000.0]
    due = [False]
    refreshed, outcomes = [], []
    monkeypatch.setattr(scanner, "_MARKET_BRIEF_WORKER", {"lastAttemptMonotonic": 1.0, "status": "GENERATED"})
    monkeypatch.setattr(scanner, "_MARKET_BRIEF_WORKER_LOCK", threading.Lock())
    monkeypatch.setattr(scanner, "_MARKET_BRIEF", {"historyRestoreAttempted": True, "lastSuccessful": {
        "unifiedStatus": "GENERATED", "presentationStatus": "GENERATED"}})
    monkeypatch.setattr(scanner.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(scanner._OWNER_DIALOGUE_RECOVERY, "tick", lambda: None)
    monkeypatch.setattr(scanner, "_market_brief_schedule_decision", lambda previous: {"due": due[0]})
    monkeypatch.setattr(scanner, "_market_brief_history_outcomes", lambda: outcomes.append(clock[0]))
    monkeypatch.setattr(scanner, "_market_brief_history_sync", lambda: None)
    monkeypatch.setattr(scanner, "_macro_analysis_restore_once", lambda: None)
    monkeypatch.setattr(scanner, "_market_brief_refresh",
                        lambda **kw: refreshed.append(clock[0]) or {"unifiedStatus": "GENERATED"})
    for _ in range(30):                                   # 30 minutes of scheduler passes
        assert scanner._market_brief_worker_tick()["status"] == "NOT_DUE"
        clock[0] += 60
    assert refreshed == [] and len(outcomes) == 3          # scoring keeps its ten-minute pace
    due[0] = True
    assert scanner._market_brief_worker_tick()["status"] == "GENERATED" and len(refreshed) == 1
