"""Owner-fixed update times of the integrated view (2026-10-17, three a trading day from 2026-11-10,
the after-close time 16:10 from 2026-11-22)."""
from datetime import date, datetime, timedelta, timezone

import argus_brief_schedule as bs

JST = bs.JST


def at(text):
    return datetime.fromisoformat(text).replace(tzinfo=JST)


def weekdays(day):
    return day.weekday() < 5


def test_three_owner_times_on_trading_days_and_two_on_closed_days():
    assert bs.TRADING_DAY_SLOTS == ("08:00", "12:00", "16:10")
    assert bs.CLOSED_DAY_SLOTS == ("08:00", "20:00") and bs.EVENT_EDITIONS_PER_DAY == 3
    assert bs.SCHEDULE_VERSION == "brief-schedule-v3"
    assert [label for _, label in bs.slots_for_day(date(2026, 10, 16), True)] == ["08:00", "12:00", "16:10"]
    assert [label for _, label in bs.slots_for_day(date(2026, 10, 17), False)] == ["08:00", "20:00"]


def test_latest_slot_reads_yesterday_and_weekends():
    assert bs.latest_slot(at("2026-10-17T00:30"), weekdays)[1] == "2026-10-16 16:10"   # Friday close
    assert bs.latest_slot(at("2026-10-17T07:30"), weekdays)[1] == "2026-10-16 16:10"   # Saturday before 08:00
    assert bs.latest_slot(at("2026-10-17T08:05"), weekdays)[1] == "2026-10-17 08:00"
    assert bs.latest_slot(at("2026-10-19T00:30"), weekdays)[1] == "2026-10-18 20:00"   # Sunday evening
    assert bs.latest_slot(at("2026-10-19T09:20"), weekdays)[1] == "2026-10-19 08:00"   # no 09:15 any more
    assert bs.latest_slot(at("2026-10-19T23:59"), weekdays)[1] == "2026-10-19 16:10"   # no evening slot
    # 2026-11-22: the old 15:45 time is gone; until 16:10 the 12:00 edition is the latest.
    assert bs.latest_slot(at("2026-10-19T15:50"), weekdays)[1] == "2026-10-19 12:00"
    assert bs.latest_slot(at("2026-10-19T16:09"), weekdays)[1] == "2026-10-19 12:00"
    assert bs.latest_slot(at("2026-10-19T16:10"), weekdays)[1] == "2026-10-19 16:10"


def test_three_editions_on_a_trading_day():
    written, last = [], None
    minute = at("2026-10-19T00:00")
    while minute < at("2026-10-20T00:00"):
        decision = bs.decide(now=minute, last_edition_at=last, covered_slot=None, is_trading_day=weekdays)
        if decision["due"] and last is not None:
            written.append(decision["slot"])
        if decision["due"]:
            last = minute
        minute += timedelta(minutes=5)
    assert written == ["2026-10-19 08:00", "2026-10-19 12:00", "2026-10-19 16:10"]


def test_a_slot_is_due_once_after_it_passes():
    common = dict(is_trading_day=weekdays, covered_slot=None)
    assert not bs.decide(now=at("2026-10-19T11:59"), last_edition_at=at("2026-10-19T08:01"), **common)["due"]
    due = bs.decide(now=at("2026-10-19T12:01"), last_edition_at=at("2026-10-19T08:01"), **common)
    assert due["due"] and due["kind"] == "SCHEDULED" and due["slot"] == "2026-10-19 12:00"
    # Written after the slot, or already checked with unchanged inputs: not due.
    assert not bs.decide(now=at("2026-10-19T12:40"), last_edition_at=at("2026-10-19T12:02"), **common)["due"]
    assert not bs.decide(now=at("2026-10-19T12:40"), last_edition_at=at("2026-10-19T08:01"),
                         is_trading_day=weekdays, covered_slot="2026-10-19 12:00")["due"]
    # No saved edition at all: the latest slot is due.
    assert bs.decide(now=at("2026-10-19T12:40"), last_edition_at=None, **common)["due"]


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


# ── 2026-11-22 (owner 【見立ては変わった時だけ】): material change only ──

def _facts(*, news=("nie-1",), shock="5.41%", lit=5, sign_row=True):
    rows = [{"priority": "P0", "source": "trusted_mail", "text": f"Nikkei: 見出し {n}（市場確認待ち）",
             "provenance": {"eventId": n}} for n in news]
    if shock:
        rows.append({"priority": "P0", "source": "official_sensor", "text": f"市場ショック: 米30年債利回り {shock}",
                     "provenance": {"eventId": "long-end-rates"}})
    rows.append({"priority": "P1", "source": "market_view", "text": f"市場観: 反転:混在・下方:混在・6サイン成立{lit}/6"})
    if sign_row:
        names = ["信用売り残が少ない", "日経レバの制度信用倍率", "日本株の優位性低下",
                 "推計EPSの下方修正", "海外投資家の売り越し", "VIXのMACDが上向き"]
        parts = [f"{name}={'点灯' if i < lit else '消灯'}" for i, name in enumerate(names)]
        rows.append({"priority": "P1", "source": "market_view", "provenance": {"eventId": "six-signs"},
                     "text": f"6サインの内訳（点灯{lit}/6）: " + "、".join(parts) + "。"})
    rows.append({"priority": "P1", "source": "market_position", "text": "現在位置・毎回変わる文"})
    return rows


def _check(previous, current, *, now="2026-11-25T12:01", slot="2026-11-25 12:00",
           edition="2026-11-25T08:01", event_ids=()):
    return bs.material_change(previous_basis=previous, basis=current, slot=slot,
                              previous_edition_at=at(edition), now=at(now), event_ids=event_ids)


def test_an_unchanged_update_time_keeps_the_edition():
    base = bs.material_basis(facts=_facts(), nikkei_price=50000.0)
    same = bs.material_basis(facts=_facts(), nikkei_price=50000.0 * 1.0099)
    result = _check(base, same)
    assert result == {"material": False, "reasons": [], "nikkeiMovePct": 0.99}
    # Non-P0 text that moves on every collection is not a material change.
    moved = _facts(); moved[-1]["text"] = "現在位置・別の文"
    assert not _check(base, bs.material_basis(facts=moved, nikkei_price=50000.0))["material"]
    # The same shock sensor's value moving is not a change; its clearing is.
    assert not _check(base, bs.material_basis(facts=_facts(shock="5.40%"), nikkei_price=50000.0))["material"]
    assert _check(base, bs.material_basis(facts=_facts(shock=None), nikkei_price=50000.0))["reasons"] == ["p0_changed"]


def test_a_new_or_replaced_p0_fact_writes_a_new_edition():
    base = bs.material_basis(facts=_facts(), nikkei_price=50000.0)
    added = bs.material_basis(facts=_facts(news=("nie-1", "nie-2")), nikkei_price=50000.0)
    replaced = bs.material_basis(facts=_facts(news=("nie-3",)), nikkei_price=50000.0)
    assert _check(base, added)["reasons"] == ["p0_changed"]
    assert _check(base, replaced)["reasons"] == ["p0_changed"]
    confirmed = _facts(); confirmed[0]["text"] = confirmed[0]["text"].replace("確認待ち", "確認済み")
    assert _check(base, bs.material_basis(facts=confirmed, nikkei_price=50000.0))["material"]
    # A released official result arriving with the update time also writes.
    assert _check(base, base, event_ids=["macro-result-1"])["reasons"] == ["release_received"]


def test_six_signs_and_a_one_percent_nikkei_move_write_a_new_edition():
    base = bs.material_basis(facts=_facts(lit=5), nikkei_price=50000.0)
    assert _check(base, bs.material_basis(facts=_facts(lit=3), nikkei_price=50000.0))["reasons"] == ["six_signs_changed"]
    # Without the breakdown row the count in the market view is compared.
    old = bs.material_basis(facts=_facts(lit=5, sign_row=False), nikkei_price=50000.0)
    assert not _check(old, bs.material_basis(facts=_facts(lit=5, sign_row=False), nikkei_price=50000.0))["material"]
    assert _check(old, bs.material_basis(facts=_facts(lit=6, sign_row=False), nikkei_price=50000.0))["material"]
    for price in (50500.0, 49500.0, 47000.0):
        result = _check(base, bs.material_basis(facts=_facts(lit=5), nikkei_price=price))
        assert result["reasons"] == ["nikkei_moved"], price
    # A level that cannot be read is rewritten rather than assumed unchanged.
    assert _check(base, bs.material_basis(facts=_facts(lit=5)))["reasons"] == ["nikkei_unknown"]


def test_the_morning_edition_is_always_written_and_a_missed_morning_is_caught_up():
    assert bs.CLOSED_DAY_SLOTS[0] == bs.MORNING_SLOT == bs.TRADING_DAY_SLOTS[0] == "08:00"
    base = bs.material_basis(facts=_facts(), nikkei_price=50000.0)
    morning = _check(base, base, now="2026-11-25T08:01", slot="2026-11-25 08:00", edition="2026-11-25T05:03")
    assert morning["reasons"] == ["morning_edition"]
    # The morning edition failed: the 12:00 time still holds yesterday's edition.
    assert _check(base, base, edition="2026-11-24T15:46")["reasons"] == ["new_day"]
    # An edition written before this rule (no saved basis) is rewritten once.
    assert _check(None, base)["reasons"] == ["no_previous_basis"]
    assert _check({**base, "schemaVersion": "older"}, base)["reasons"] == ["no_previous_basis"]


def test_the_view_is_checked_well_inside_the_screens_24_hours():
    """Every JST day starts with a written edition, and consecutive update
    times are at most 15h50m apart (16:10 to 08:00), so the time the view was written or
    re-confirmed never reaches the screen's 24 hours (BRIEF_TONE_MAX_AGE_HOURS)."""
    base = bs.material_basis(facts=_facts(), nikkei_price=50000.0)
    instants = []
    for offset in range(28):
        day = date(2026, 11, 2) + timedelta(days=offset)
        for when, label in bs.slots_for_day(day, weekdays(day)):
            instants.append(when)
            check = bs.material_change(previous_basis=base, basis=base,
                                       slot=f"{day.isoformat()} {label}",
                                       previous_edition_at=when - timedelta(hours=4), now=when)
            assert check["material"] is (label == "08:00"), (day, label)
    gaps = [b - a for a, b in zip(instants, instants[1:])]
    assert max(gaps) == timedelta(hours=15, minutes=50) and max(gaps) < timedelta(hours=24)


def _material_scenario(monkeypatch):
    import copy
    from datetime import timezone
    import scanner
    current = [datetime(2026, 11, 25, 3, 1, tzinfo=timezone.utc)]          # Wednesday 12:01 JST
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None): return current[0] if tz is None else current[0].astimezone(tz)
    price = [50000.0]
    facts = [_facts()]
    brief = {"generatedAt": "2026-11-24T23:01:00Z", "facts": facts[0]}
    internals = {"informationCutoff": "2026-11-24T23:01:00Z", "status": "AVAILABLE"}
    previous = copy.deepcopy(brief)
    previous.update(unifiedStatus="GENERATED", presentationStatus="GENERATED",
                    unifiedSummary={"view": "morning"}, aiText={"nowJa": "朝の結論"},
                    aiDiagnostics={"completedAt": "2026-11-24T23:01:00Z"},               # 08:01 JST
                    generationTrigger={"kind": "SCHEDULED", "materialBasis": bs.material_basis(
                        facts=facts[0], nikkei_price=50000.0, nikkei_at="2026-11-24T06:00:00Z")})
    state = {"lastSuccessful": copy.deepcopy(previous), "generationInputDigest": "inputs-always-move"}
    monkeypatch.setattr(scanner, "datetime", Clock)
    monkeypatch.setattr(scanner, "_ai_now_iso", lambda: current[0].isoformat().replace("+00:00", "Z"))
    monkeypatch.setattr(scanner, "_MARKET_BRIEF", state)
    monkeypatch.setattr(scanner, "_MARKET_BRIEF_SCHEDULE", {"coveredSlot": None, "handledEventIds": [],
        "eventDay": None, "eventCount": 0, "editionsByKind": {}, "reusedNotScheduled": 0,
        "reusedNoMaterialChange": 0})
    monkeypatch.setattr(scanner, "_INDEX_RESEARCH_REPORTS", {})
    monkeypatch.setattr(scanner, "_backend_exact_sha", lambda: "a" * 40)
    monkeypatch.setattr(scanner, "_owner_overview_generation_policy", lambda: {"model": "test", "ruleVersion": "a" * 40})
    monkeypatch.setattr(scanner, "_JP_MARKET_ENGINE_INDEX_OHLCV_CACHE", {})
    monkeypatch.setattr(scanner, "_JP_MARKET_FEATURE_HISTORY", {"status": "AVAILABLE", "features": []})
    monkeypatch.setattr(scanner, "_macro_material_cached", lambda **kw: [])
    monkeypatch.setattr(scanner, "_compose_market_brief", lambda: copy.deepcopy({**brief, "facts": facts[0]}))
    monkeypatch.setattr(scanner, "_jp_market_internals_cached", lambda: copy.deepcopy(internals))
    monkeypatch.setattr(scanner.argus_index_live, "current_quote_safe", lambda: {
        "status": "AVAILABLE", "quote": {"price": price[0], "tradedAt": current[0].isoformat()}})
    calls, saved = [], []
    monkeypatch.setattr(scanner, "_jp_market_comparison_cached", lambda horizon: {})
    def polish(result):
        calls.append(current[0])
        return {**result, "unifiedStatus": "GENERATED", "presentationStatus": "GENERATED",
                "unifiedSummary": {"view": "new"}, "aiText": {"nowJa": "新しい結論"},
                "aiDiagnostics": {"completedAt": current[0].isoformat().replace("+00:00", "Z")}}
    monkeypatch.setattr(scanner, "_market_brief_ai_polish", polish)
    monkeypatch.setattr(scanner, "_market_brief_history_save", lambda result: saved.append(copy.deepcopy(result)))
    return scanner, current, price, facts, previous, calls, saved


def test_an_unchanged_update_time_calls_no_ai_and_moves_the_check_time(monkeypatch):
    scanner, current, price, facts, previous, calls, saved = _material_scenario(monkeypatch)
    price[0] = 50300.0                                                     # +0.6%: not material
    retained = scanner._market_brief_refresh(allow_ai=True)
    assert calls == [] and saved == []
    reuse = retained["generationReuse"]
    assert reuse["reason"] == "NO_MATERIAL_CHANGE" and reuse["newAiCalls"] == 0
    assert reuse["inputsCheckedAt"] == "2026-11-25T03:01:00Z"
    assert reuse["inputsCheckedAt"] > previous["aiDiagnostics"]["completedAt"]
    assert reuse["schedule"]["materialCheck"]["reasons"] == []
    assert retained["aiText"] == previous["aiText"] and retained["generatedAt"] == previous["generatedAt"]
    assert scanner._MARKET_BRIEF_SCHEDULE["coveredSlot"] == "2026-11-25 12:00"
    assert scanner._MARKET_BRIEF_SCHEDULE["reusedNoMaterialChange"] == 1
    # The same update time is not checked again; the next one is.
    current[0] = datetime(2026, 11, 25, 3, 30, tzinfo=current[0].tzinfo)
    assert scanner._market_brief_refresh(allow_ai=True)["generationReuse"]["reason"] == "NOT_SCHEDULED"
    assert calls == []


def test_a_new_p0_fact_at_the_next_update_time_writes_once(monkeypatch):
    scanner, current, price, facts, previous, calls, saved = _material_scenario(monkeypatch)
    facts[0] = _facts(news=("nie-1", "nie-2"))
    current[0] = datetime(2026, 11, 25, 7, 11, tzinfo=current[0].tzinfo)   # 16:11 JST
    written = scanner._market_brief_refresh(allow_ai=True)
    assert len(calls) == 1 and written["unifiedSummary"] == {"view": "new"}
    trigger = saved[0]["generationTrigger"]
    assert trigger["slot"] == "2026-11-25 16:10" and trigger["materialCheck"]["reasons"] == ["p0_changed"]
    assert trigger["materialBasis"]["p0"] == bs.material_basis(facts=facts[0])["p0"]
    assert trigger["materialBasis"]["nikkei"]["price"] == 50000.0


def test_the_next_morning_is_written_even_when_nothing_changed(monkeypatch):
    scanner, current, price, facts, previous, calls, saved = _material_scenario(monkeypatch)
    current[0] = datetime(2026, 11, 25, 23, 1, tzinfo=current[0].tzinfo)   # Thursday 08:01 JST
    scanner._market_brief_refresh(allow_ai=True)
    assert len(calls) == 1
    assert saved[0]["generationTrigger"]["materialCheck"]["reasons"] == ["morning_edition", "new_day"]


def test_a_saved_edition_without_a_basis_is_rewritten_once(monkeypatch):
    scanner, current, price, facts, previous, calls, saved = _material_scenario(monkeypatch)
    scanner._MARKET_BRIEF["lastSuccessful"].pop("generationTrigger")
    scanner._market_brief_refresh(allow_ai=True)
    assert len(calls) == 1
    assert saved[0]["generationTrigger"]["materialCheck"]["reasons"] == ["no_previous_basis"]


def _fiscal(cases="WATCH", market="WATCH", adverse=("JGB",)):
    return {"status": "AVAILABLE",
            "cases": {name: {"id": name, "warningLevel": cases, "currentReasons": ["r"]}
                      for name in ("baseline", "growth_1", "growth_2")},
            "market": {"id": "m", "status": "PARTIAL", "warningLevel": market, "adverseGroups": list(adverse)}}


def test_a_change_in_the_fiscal_warning_writes_a_new_edition():
    """Owner 【入れる】 2026-11-22: the Japanese fiscal warning state is a material
    input (it was in the earlier, unused urgent signature). Its levels are
    compared, not the fact texts that follow every acquisition."""
    base = bs.material_basis(facts=_facts(), nikkei_price=50000.0, fiscal=_fiscal())
    same = bs.material_basis(facts=_facts(), nikkei_price=50000.0,
                             fiscal={**_fiscal(), "status": "PARTIAL", "auctions": {"x": 1}})
    assert not _check(base, same)["material"]
    for changed in (_fiscal(cases="UNKNOWN"), _fiscal(market="UNKNOWN", adverse=()),
                    _fiscal(adverse=("FX", "JGB")), None):
        result = _check(base, bs.material_basis(facts=_facts(), nikkei_price=50000.0, fiscal=changed))
        assert result["reasons"] == ["fiscal_warning_changed"], changed
    # The acquisition fact text alone does not count.
    flapping = _facts() + [{"priority": "P1", "source": "jp_fiscal_environment",
                            "text": "日本の財政・金利環境は更新確認が未完了。保存した警戒を取得障害だけで解除しません。"}]
    assert not _check(base, bs.material_basis(facts=flapping, nikkei_price=50000.0, fiscal=_fiscal()))["material"]
    assert base["schemaVersion"] == "brief-material-basis-v2"
