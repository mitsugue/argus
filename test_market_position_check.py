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
    assert row["measured"] == {"unknown": False, "nextEventDate": "2026-10-29"}


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
