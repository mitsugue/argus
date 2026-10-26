"""N-19 (owner 2026-10-23): the market position is checked against public
sources at fixed times; answers without an allowed source are dropped, the
accepted ones become PUBLIC_CHECK entries of the same memory, and during the
shadow week they are kept and counted but not shown."""
import json
from datetime import date, datetime, timedelta, timezone

import pytest

import argus_market_position_check as check
import argus_market_position_memory as mpm
import scanner

NOW = datetime(2026, 10, 26, 2, 31, tzinfo=timezone.utc)   # Mon 11:31 JST
NOW_ISO = "2026-10-26T02:31:00Z"


def trading(day):
    return day.weekday() < 5


def _news(theme_family="FED", severity="HIGH", hours=2, confirmed=None, event_id="e1"):
    at = (NOW - timedelta(hours=hours)).isoformat().replace("+00:00", "Z")
    return {"eventId": event_id, "severity": severity, "eventType": theme_family,
            "sourceReceivedAt": at, "headlineJa": "FRBが利下げを示唆", "sourceLabelJa": "公式",
            "confirmationState": confirmed}


def _view(memory):
    return mpm.snapshot(memory, now_iso=NOW_ISO)


# ── when ────────────────────────────────────────────────────────────────────

def test_slots_follow_the_owner_times():
    assert check.latest_slot(NOW, trading) == "2026-10-26 11:30"
    early = datetime(2026, 10, 25, 22, 0, tzinfo=timezone.utc)      # Mon 07:00 JST
    assert check.latest_slot(early, trading) == "2026-10-25 08:30"   # Sunday's one slot
    sunday = datetime(2026, 10, 25, 3, 0, tzinfo=timezone.utc)       # Sun 12:00 JST
    assert check.latest_slot(sunday, trading) == "2026-10-25 08:30"
    assert check.due(NOW, "2026-10-26 11:30", trading) is None
    assert check.due(NOW, "2026-10-26 07:30", trading) == "2026-10-26 11:30"


# ── what to ask ─────────────────────────────────────────────────────────────

def test_questions_lead_with_an_unconfirmed_important_report():
    memory = mpm.empty()
    mpm.ingest_news(memory, [_news()])
    questions = check.select_questions(_view(memory), now=NOW)
    assert questions[0]["type"] == "CONFIRM" and questions[0]["themeId"] == "US_POLICY_RATE"
    assert "FRBが利下げを示唆" in questions[0]["aboutJa"]
    assert {q["type"] for q in questions} >= {"CONFIRM", "PRICING"}
    assert len(questions) <= check.MAX_QUESTIONS
    assert [q["id"] for q in questions] == [f"q{i + 1}" for i in range(len(questions))]


def test_a_confirmed_or_old_report_is_not_asked_again():
    memory = mpm.empty()
    mpm.ingest_news(memory, [_news(confirmed="CONFIRMED", event_id="a"),
                             _news(hours=100, event_id="b")])
    assert "CONFIRM" not in {q["type"] for q in check.select_questions(_view(memory), now=NOW)}


def test_no_active_theme_means_no_question():
    assert check.select_questions(_view(mpm.empty()), now=NOW) == []


def test_prompt_lists_the_allowed_sources_and_asks_for_json():
    memory = mpm.empty()
    mpm.ingest_news(memory, [_news()])
    prompt = check.build_prompt(check.select_questions(_view(memory), now=NOW), now=NOW)
    assert "boj.or.jp" in prompt and "federalreserve.gov" in prompt
    assert '"answers"' in prompt and "unknown" in prompt
    assert "q1:" in prompt


# ── what to keep ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("url,ok", [
    ("https://www.federalreserve.gov/newsevents/x.htm", True),
    ("https://jp.reuters.com/markets/x", True),
    ("http://www.boj.or.jp/x", False),                 # not https
    ("https://reuters.com.example.net/x", False),      # look-alike host
    ("https://evilreuters.com/x", False),
    ("https://example.com/x", False),
    ("not a url", False),
])
def test_only_allowed_public_sources_count(url, ok):
    assert check.allowed_url(url) is ok


def test_answers_without_an_allowed_source_are_dropped():
    questions = [{"id": "q1", "themeId": "US_POLICY_RATE", "type": "PRICING", "questionJa": "織り込みは"},
                 {"id": "q2", "themeId": "BOJ", "type": "NEXT_EVENT", "questionJa": "次の会合は"},
                 {"id": "q3", "themeId": "JPY", "type": "STALE", "questionJa": "新しい事実は"}]
    text = "結果です\n" + json.dumps({"answers": [
        {"id": "q1", "answerJa": "12月の利下げ確率は約60%", "unknown": False,
         "sources": [{"url": "https://www.cmegroup.com/fedwatch", "title": "FedWatch", "publishedAt": "2026-10-25"}]},
        {"id": "q2", "answerJa": "10/30に決定会合", "unknown": False,
         "sources": [{"url": "https://example.com/boj"}]},
        {"id": "q3", "answerJa": "", "unknown": True, "sources": []},
        {"id": "q9", "answerJa": "x", "sources": []},
    ]}, ensure_ascii=False)
    parsed = check.parse_answers(text, questions)
    assert [a["question"]["id"] for a in parsed["accepted"]] == ["q1", "q3"]
    assert parsed["accepted"][1]["unknown"] is True
    assert parsed["rejected"] == {"no_allowed_source": 1, "unknown_question": 1}
    assert check.parse_answers("答えられません", questions)["rejected"] == {"not_json": 1}


def test_accepted_answers_become_public_check_entries():
    questions = [{"id": "q1", "themeId": "US_POLICY_RATE", "type": "PRICING", "questionJa": "織り込みは"}]
    parsed = check.parse_answers(json.dumps({"answers": [
        {"id": "q1", "answerJa": "利下げ確率は約60%", "nextEventDate": "2026-10-29",
         "sources": [{"url": "https://www.cmegroup.com/fedwatch"}]}]}), questions)
    [row] = check.entries(parsed["accepted"], checked_at=NOW_ISO, slot="2026-10-26 11:30")
    assert row["kind"] == "PUBLIC_CHECK" and row["themeId"] == "US_POLICY_RATE"
    assert row["ref"]["sources"][0]["url"].startswith("https://www.cmegroup.com/")
    assert row["ref"]["slot"] == "2026-10-26 11:30"
    assert row["measured"] == {"unknown": False, "nextEventDate": "2026-10-29", "confirmation": "CONFIRMED"}


def test_shadow_entries_are_kept_but_not_shown():
    memory = mpm.empty()
    questions = [{"id": "q1", "themeId": "BOJ", "type": "STALE", "questionJa": "新しい事実は"}]
    parsed = check.parse_answers(json.dumps({"answers": [
        {"id": "q1", "answerJa": "日銀は据え置き", "sources": [{"url": "https://www.boj.or.jp/x"}]}]}), questions)
    for row in check.entries(parsed["accepted"], checked_at=NOW_ISO, slot="s"):
        mpm.append(memory, row)
    assert len(memory["entries"]) == 1
    boj = next(t for t in _view(memory)["themes"] if t["themeId"] == "BOJ")
    assert boj["status"] == "EMPTY" and boj["recent"] == []      # not shown, not kept ACTIVE
    assert check.summary(memory, now=NOW)["recent"] == 1


# ── the scheduled run inside the brief worker ───────────────────────────────

@pytest.fixture
def server(monkeypatch):
    memory = mpm.empty()
    mpm.ingest_news(memory, [_news()])
    monkeypatch.setitem(scanner._MARKET_POSITION, "memory", memory)
    monkeypatch.setattr(scanner, "_market_position_path", lambda: None)
    monkeypatch.setattr(scanner, "_ai_now_iso", lambda: NOW_ISO)
    monkeypatch.setattr(scanner, "_important_events_data", lambda: {"events": []})
    monkeypatch.setattr(scanner, "_scheduled_ai_skip", lambda provider, purpose: None)
    monkeypatch.setattr(scanner.argus_market_clock, "is_trading_day", lambda market, day: trading(day))
    state = {"lastSlot": None, "status": "NOT_RUN", "lastRunAt": None, "asked": 0, "accepted": 0,
             "unknown": 0, "rejected": {}, "errorClass": None, "runs": 0}
    monkeypatch.setattr(scanner, "_MARKET_POSITION_CHECK", state)
    monkeypatch.delenv("ARGUS_POSITION_CHECK", raising=False)
    calls = []

    def fake_research(prompt, role="standard", benchmark=False, purpose=None, max_output=None):
        calls.append(purpose)
        assert max_output == scanner._MARKET_POSITION_CHECK_MAX_OUTPUT
        return json.dumps({"answers": [
            {"id": "q1", "answerJa": "FRBの議長が会見で示唆", "sources": [
                {"url": "https://www.federalreserve.gov/newsevents/speech/x.htm"}]}]}), {"status": "ok"}

    monkeypatch.setattr(scanner, "_openai_research_ex", fake_research)
    return memory, state, calls


def test_run_asks_once_per_slot_and_stores_shadow_entries(server):
    memory, state, calls = server
    scanner._market_position_check_run()
    assert calls == ["market_position_check"]
    assert state["status"] == "OK" and state["accepted"] == 1 and state["lastSlot"] == "2026-10-26 11:30"
    assert sum(1 for r in memory["entries"] if r["kind"] == "PUBLIC_CHECK") == 1
    scanner._market_position_check_run()                      # same slot: no second call
    assert calls == ["market_position_check"]
    state["lastSlot"] = None                                  # restart: the stored slot is found
    scanner._market_position_check_run()
    assert calls == ["market_position_check"] and state["lastSlot"] == "2026-10-26 11:30"


def test_run_can_be_turned_off_and_respects_the_ai_policy(server, monkeypatch):
    _, state, calls = server
    monkeypatch.setenv("ARGUS_POSITION_CHECK", "off")
    scanner._market_position_check_run()
    assert state["status"] == "OFF" and calls == []
    monkeypatch.delenv("ARGUS_POSITION_CHECK")
    monkeypatch.setattr(scanner, "_scheduled_ai_skip",
                        lambda provider, purpose: {"reason": "scheduled_daily_budget_exhausted"})
    scanner._market_position_check_run()
    assert state["status"] == "SKIPPED" and calls == []


def test_health_shows_counts_only_and_the_admin_audit_shows_the_answers(server, monkeypatch):
    scanner._market_position_check_run()
    client = scanner.app.test_client()
    health = client.get("/api/argus/news-intake/health").get_json()
    assert health["positionCheck"]["mode"] == "shadow"
    assert health["positionCheck"]["recent"] == 1
    assert "FRBの議長" not in json.dumps(health, ensure_ascii=False)
    monkeypatch.setattr(scanner, "_require_admin", lambda: (True, None, 200))
    audit = client.get("/api/argus/admin/news-intake/audit").get_json()
    assert audit["positionChecks"][0]["textJa"] == "FRBの議長が会見で示唆"
    assert audit["positionChecks"][0]["ref"]["sources"][0]["url"].startswith("https://www.federalreserve.gov/")


# ── 2026-10-25: what the first week showed ─────────────────────────────────

def test_a_partly_confirmed_answer_is_not_counted_unknown():
    questions = [{"id": "q1", "themeId": "BOJ", "type": "CONFIRM", "questionJa": "確認できますか"},
                 {"id": "q2", "themeId": "BOJ", "type": "STALE", "questionJa": "新しい事実は"}]
    parsed = check.parse_answers(json.dumps({"answers": [
        {"id": "q1", "answerJa": "確認：9月の全国CPIは公表済み。未確認：主因は確認できない。",
         "confirmation": "PARTIAL", "unknown": True,
         "sources": [{"url": "https://www.stat.go.jp/data/cpi/"}]},
        {"id": "q2", "answerJa": "", "confirmation": "NONE", "sources": []}]}), questions)
    partial, none = parsed["accepted"]
    assert partial["confirmation"] == "PARTIAL" and partial["unknown"] is False
    assert none["confirmation"] == "NONE" and none["unknown"] is True
    memory = mpm.empty()
    for row in check.entries(parsed["accepted"], checked_at=NOW_ISO, slot="s"):
        mpm.append(memory, row)
    counts = check.summary(memory, now=NOW)
    assert counts["recentUnknown"] == 1 and counts["recentPartial"] == 1
    assert "PARTIAL" in check.build_prompt(questions, now=NOW)


def test_japanese_releases_and_non_middle_east_geopolitics_find_their_theme():
    memory = mpm.empty()
    mpm.ingest_news(memory, [
        {**_news(theme_family="INFLATION", event_id="jp-cpi"), "headlineJa": "9月の全国消費者物価、2.1%上昇 総務省"},
        {**_news(theme_family="INFLATION", event_id="us-cpi"), "headlineJa": "米CPI、9月は前年比3.1%上昇"},
        {**_news(theme_family="GEOPOLITICS", event_id="nk"), "headlineJa": "北朝鮮の金正恩総書記が中国訪問"},
        {**_news(theme_family="GEOPOLITICS", event_id="me"), "headlineJa": "イラン、ホルムズ海峡で演習"}])
    placed = {r["ref"]["eventId"]: r["themeId"] for r in memory["entries"]}
    assert placed == {"jp-cpi": "BOJ", "us-cpi": "US_POLICY_RATE",
                      "nk": "EMERGING_GEOPOLITICS_OTHER", "me": "MIDDLE_EAST"}
    assert mpm.THEMES["EMERGING_GEOPOLITICS_OTHER"]["labelJa"] == "地政学(中東以外)"


def test_an_answered_question_is_not_asked_again_inside_its_window():
    # 2026-10-27: the shadow week asked the same report three or four times.
    memory = mpm.empty()
    mpm.ingest_news(memory, [_news()])
    first = check.select_questions(_view(memory), now=NOW)
    answers = [{"id": q["id"], "answerJa": "確認済み", "confirmation": "CONFIRMED", "unknown": False,
                "nextEventDate": None, "sources": [{"url": "https://www.federalreserve.gov/x"}]} for q in first]
    parsed = check.parse_answers(json.dumps({"answers": answers}), first)
    rows = check.entries(parsed["accepted"], checked_at=NOW_ISO, slot="2026-10-26 11:30")
    confirm = next(r for r in rows if r["ref"]["questionType"] == "CONFIRM")
    assert confirm["ref"]["aboutKey"] == check.about_key(first[0]["aboutJa"])
    # Four hours later: the same report and the same pricing are not asked again.
    later = check.select_questions(_view(memory), now=NOW + timedelta(hours=4), recent_checks=rows)
    asked = {(q["themeId"], q["type"]) for q in later}
    assert ("US_POLICY_RATE", "CONFIRM") not in asked and ("US_POLICY_RATE", "PRICING") not in asked
    # After each window the question comes back; a different report is asked at once.
    assert ("US_POLICY_RATE", "PRICING") in {(q["themeId"], q["type"]) for q in check.select_questions(
        _view(memory), now=NOW + timedelta(hours=9), recent_checks=rows)}
    mpm.ingest_news(memory, [{**_news(event_id="e2", hours=1), "headlineJa": "FRB議長が追加の利下げを否定"}])
    fresh = check.select_questions(_view(memory), now=NOW + timedelta(hours=4), recent_checks=rows)
    assert any(q["type"] == "CONFIRM" and "否定" in q["aboutJa"] for q in fresh)


def test_a_contradicted_report_is_marked_for_the_integrated_view_but_not_the_screen():
    # 2026-10-27 (owner, plan A): off the screen; the integrated view reads the finding first.
    memory = mpm.empty()
    mpm.ingest_news(memory, [_news()])
    [question] = [q for q in check.select_questions(_view(memory), now=NOW) if q["type"] == "CONFIRM"]
    answer = {"id": question["id"], "answerJa": "米9月CPIは前年比3.7%(BLS)。2.1%は日本のCPI。",
              "confirmation": "CONFIRMED", "unknown": False, "claim": "CONTRADICTED", "nextEventDate": None,
              "sources": [{"url": "https://www.bls.gov/news.release/cpi.htm"}]}
    parsed = check.parse_answers(json.dumps({"answers": [answer]}), [question])
    assert parsed["accepted"][0]["claim"] == "CONTRADICTED"
    for row in check.entries(parsed["accepted"], checked_at=NOW_ISO, slot="2026-10-26 11:30"):
        mpm.append(memory, row)
    view = _view(memory)
    us = next(t for t in view["themes"] if t["themeId"] == "US_POLICY_RATE")
    news = next(r for r in us["externalRecent"] if r["kind"] == "NEWS")
    assert news["publicCheck"]["claim"] == "CONTRADICTED" and news["publicCheck"]["sourceDomains"] == ["www.bls.gov"]
    fact = next(f for f in mpm.explanation_facts(view) if "米国" in f["text"] or "金利" in f["text"])
    assert "【公開情報と食い違い】米9月CPIは前年比3.7%" in fact["text"]
    assert "publicCheck" in json.dumps(mpm.generation_inputs(view), ensure_ascii=False)
    assert "publicCheck" not in json.dumps(mpm.public_snapshot(view), ensure_ascii=False), "画面には出さない"
    assert not any(r["kind"] == "PUBLIC_CHECK" for t in view["themes"] for r in t["recent"]), "確認そのものは出さない"


def test_claim_is_only_for_reports_and_needs_a_source():
    confirm = {"id": "q1", "themeId": "US_POLICY_RATE", "type": "CONFIRM", "questionJa": "確認", "aboutKey": "k"}
    pricing = {"id": "q2", "themeId": "US_POLICY_RATE", "type": "PRICING", "questionJa": "織り込み"}
    parsed = check.parse_answers(json.dumps({"answers": [
        {"id": "q1", "answerJa": "", "confirmation": "NONE", "unknown": True, "claim": "CONTRADICTED", "sources": []},
        {"id": "q2", "answerJa": "60%", "claim": "SUPPORTED", "sources": [{"url": "https://www.cmegroup.com/x"}]}]}),
        [confirm, pricing])
    claims = {a["question"]["id"]: a["claim"] for a in parsed["accepted"]}
    assert claims == {"q1": "UNVERIFIED", "q2": None}
    # Older checks without a claim: nothing found means unverified; a found answer stays unmarked.
    memory = mpm.empty()
    mpm.ingest_news(memory, [_news()])
    text = next(r for t in _view(memory)["themes"] for r in t["externalRecent"] if r["kind"] == "NEWS")["textJa"]
    old = mpm._entry("US_POLICY_RATE", "PUBLIC_CHECK", NOW_ISO, "確かめられませんでした",
                     ref={"questionType": "CONFIRM", "aboutKey": mpm.about_key(text), "sources": []},
                     measured={"unknown": True, "confirmation": "NONE"})
    mpm.append(memory, old)
    news = next(r for t in _view(memory)["themes"] for r in t["externalRecent"] if r["kind"] == "NEWS")
    assert news["publicCheck"]["claim"] == "UNVERIFIED"
    later = (NOW + timedelta(days=15)).isoformat().replace("+00:00", "Z")
    assert mpm.public_check_marks(memory, NOW + timedelta(days=15)) == {}, f"{later}: 古い印は使わない"
