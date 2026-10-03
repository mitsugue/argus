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
