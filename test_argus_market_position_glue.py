"""The brief carries the market position memory as evidence and persists it on disk."""
import json

import scanner
import argus_market_position_memory as mpm
from test_argus_market_position_memory import NEWS, RECORD, CALENDAR


def _fresh(monkeypatch, tmp_path, durable=True):
    scanner._MARKET_POSITION.update(memory=None, loadedAt=None, persistence=None)
    path = str(tmp_path / "market_position_memory.json")
    monkeypatch.setattr(scanner, "_market_position_path", lambda: path if durable else None)
    scanner._MACRO_ANALYSIS.clear(); scanner._MACRO_ANALYSIS_STATE["restored"] = True
    scanner._MACRO_ANALYSIS[RECORD["eventId"]] = json.loads(json.dumps(RECORD))
    monkeypatch.setattr(scanner, "_ai_now_iso", lambda: "2026-10-03T02:00:00Z")
    # Public headline and radar stores are read-only inputs; keep them empty here.
    monkeypatch.setattr(scanner, "_INTEL_STORE", [])
    monkeypatch.setattr(scanner, "_NEWS_CACHE", {"data": None, "expires": 0.0})
    monkeypatch.setattr(scanner.argus_index_live, "current_quote_safe", lambda: {"status": "UNAVAILABLE"})
    return path


def test_update_accumulates_persists_and_reloads_after_restart(monkeypatch, tmp_path):
    path = _fresh(monkeypatch, tmp_path)
    view = scanner._market_position_update(NEWS, CALENDAR)
    assert view["entryCount"] == 4 and view["persistence"]["status"] == "saved"
    saved = json.load(open(path))
    assert saved["schemaVersion"] == mpm.SCHEMA and len(saved["entries"]) == 4
    # Same inputs again: nothing appended, nothing rewritten.
    stamp = open(path).read()
    again = scanner._market_position_update(NEWS, CALENDAR)
    assert again["entryCount"] == 4 and open(path).read() == stamp
    # A restart reloads the file instead of starting empty.
    scanner._MARKET_POSITION.update(memory=None, loadedAt=None, persistence=None)
    reloaded = scanner._market_position_update([], CALENDAR)
    assert reloaded["entryCount"] == 4
    us = next(t for t in reloaded["themes"] if t["themeId"] == "US_POLICY_RATE")
    assert us["lastReaction"]["readingCode"] == "RATE_RELIEF_RISK_ON" and us["nextEvent"]["title"] == "米CPI"
    assert reloaded["automaticAiCalls"] == 0


def test_memory_only_without_durable_disk(monkeypatch, tmp_path):
    _fresh(monkeypatch, tmp_path, durable=False)
    view = scanner._market_position_update(NEWS, CALENDAR)
    assert view["entryCount"] == 4 and view["persistence"] == {"status": "memory_only"}


def test_brief_puts_the_position_facts_into_the_shared_evidence(monkeypatch, tmp_path):
    _fresh(monkeypatch, tmp_path)
    monkeypatch.setattr(scanner, "_brief_news_events", lambda: json.loads(json.dumps(NEWS)))
    monkeypatch.setattr(scanner, "_important_events_data", lambda: {"events": CALENDAR, "imminent": []})
    brief = scanner._compose_market_brief()
    position = [f for f in brief["facts"] if f["source"] == "market_position"]
    assert [f["provenance"]["eventId"] for f in position] == ["market-position-US_POLICY_RATE", "market-position-MIDDLE_EAST"]
    assert position[0]["text"].startswith("現在位置・米国の利上げ・利下げ観測")
    assert brief["marketPosition"]["entryCount"] == 4
    # The unified context binds these facts like any other evidence.
    import argus_market_brief
    context = argus_market_brief.unified_context(brief)
    assert any(r["source"] == "market_position" and r["evidenceId"].startswith("brief-fact-") for r in context["facts"])
    # The integrated explanation is told to read the position first.
    import inspect
    assert "source=market_position" in inspect.getsource(scanner._market_brief_ai_polish)


def test_ai_theme_views_are_checked_stored_and_never_reject_the_six_sections(monkeypatch, tmp_path):
    """Stage two: the integrated AI's per-theme views go through the shared rules into the memory."""
    import argus_market_brief as mb
    from test_argus_unified_brief import brief as base_brief, model_response
    path = _fresh(monkeypatch, tmp_path)
    position = scanner._market_position_update(NEWS, CALENDAR)
    def build():
        b = base_brief()
        b["marketPosition"] = json.loads(json.dumps(position))
        b["facts"].extend(mpm.explanation_facts(position))
        b["unifiedContext"] = mb.unified_context(b)
        return b
    def provider_with(position_value):
        def provider(user, **kwargs):
            context, raw = model_response(user)
            us = next(r for r in context["facts"] if r["source"] == "market_position"
                      and r["provenance"]["eventId"] == "market-position-US_POLICY_RATE")
            raw["position"] = position_value(us["evidenceId"])
            kwargs["diagnostic"].update(outcome="ok", completedAt="2026-10-03T02:05:00Z", returnedModel="gpt-6-astra", estUsd=.01)
            return raw
        return provider
    good = lambda ref: [{"themeId": "US_POLICY_RATE", "expectationJa": "弱い雇用で追加利上げは見送られるとの見方",
                         "fearJa": "次の物価指標が強ければ利上げ観測が戻る", "triggerJa": "次の物価指標と次回会合の示唆",
                         "evidenceIds": [ref], "kind": "INFERENCE"}]
    monkeypatch.setattr(scanner, "_openai_prose", provider_with(good))
    result = scanner._market_brief_ai_polish(build())
    assert result["unifiedStatus"] == "GENERATED"
    assert result["positionViews"] == {"status": "ACCEPTED", "reason": None, "themeId": None, "count": 1}
    us = next(t for t in result["marketPosition"]["themes"] if t["themeId"] == "US_POLICY_RATE")
    assert us["view"]["fearJa"].startswith("次の物価指標") and us["view"]["kind"] == "INFERENCE"
    saved = json.load(open(path))
    assert [r["kind"] for r in saved["entries"]].count("AI_VIEW") == 1
    # The same view again is not appended.
    scanner._market_brief_ai_polish(build())
    assert [r["kind"] for r in json.load(open(path))["entries"]].count("AI_VIEW") == 1
    # An invalid position is reported and dropped; the six sections stay accepted.
    bad = lambda ref: [{**good(ref)[0], "expectationJa": "上がる確率は高い"}]
    monkeypatch.setattr(scanner, "_openai_prose", provider_with(bad))
    rejected = scanner._market_brief_ai_polish(build())
    assert rejected["unifiedStatus"] == "GENERATED"
    assert rejected["positionViews"]["status"] == "REJECTED" and rejected["positionViews"]["count"] == 0
    assert [r["kind"] for r in json.load(open(path))["entries"]].count("AI_VIEW") == 1
