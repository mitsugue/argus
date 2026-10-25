"""2026-10-25 (cost, measured): an edition whose text was accepted but whose
layout was not counted as "no saved edition" and the whole view was rewritten
every ten minutes until a layout passed (2-10 extra editions a day). The text
now stands until the next update time; the layout is retried once."""
import copy
import threading

import scanner

TEXT_ONLY = {"unifiedStatus": "GENERATED", "presentationStatus": "UNAVAILABLE",
             "unifiedSummary": {"view": "fixture"}, "generatedAt": "2026-10-26T01:00:00Z",
             "aiDiagnostics": {"completedAt": "2026-10-26T01:00:00Z"}}
COMPLETE = {**TEXT_ONLY, "presentationStatus": "GENERATED", "generatedAt": "2026-10-26T00:00:00Z",
            "aiDiagnostics": {"completedAt": "2026-10-26T00:00:00Z"}}
NOT_DUE = {"due": False, "kind": None, "slot": "10:00", "eventIds": [], "reason": "not_due"}


def _state(monkeypatch, previous, due=NOT_DUE):
    monkeypatch.setattr(scanner, "_MARKET_BRIEF_SCHEDULE", {})
    monkeypatch.setattr(scanner, "_market_brief_schedule_decision", lambda prev: dict(due))
    state = {"historyRestoreAttempted": True, "lastSuccessful": copy.deepcopy(previous),
             "lastPresentation": copy.deepcopy(COMPLETE)}
    monkeypatch.setattr(scanner, "_MARKET_BRIEF", state)
    return state


def test_a_text_only_edition_gets_one_layout_retry_then_waits(monkeypatch):
    _state(monkeypatch, TEXT_ONLY)
    first = scanner._market_brief_due(TEXT_ONLY)
    assert first["due"] and first["kind"] == "PRESENTATION_RETRY"
    second = scanner._market_brief_due(TEXT_ONLY)
    assert not second["due"] and second["reason"] == "presentation_retry_used"
    newer = {**TEXT_ONLY, "aiDiagnostics": {"completedAt": "2026-10-26T02:00:00Z"}}
    assert scanner._market_brief_due(newer)["kind"] == "PRESENTATION_RETRY"   # once per edition


def test_a_complete_edition_follows_the_schedule_only(monkeypatch):
    _state(monkeypatch, COMPLETE)
    assert scanner._market_brief_due(COMPLETE) == NOT_DUE
    due = {"due": True, "kind": "SCHEDULED", "slot": "10:00", "eventIds": [], "reason": "slot_due"}
    _state(monkeypatch, TEXT_ONLY, due)
    assert scanner._market_brief_due(TEXT_ONLY)["kind"] == "SCHEDULED"        # the update time wins


def test_after_the_retry_the_text_stands_without_a_model_call(monkeypatch):
    state = _state(monkeypatch, TEXT_ONLY)
    scanner._MARKET_BRIEF_SCHEDULE["presentationRetryFor"] = TEXT_ONLY["aiDiagnostics"]["completedAt"]
    monkeypatch.setattr(scanner, "_compose_market_brief", lambda: {"facts": []})

    def forbidden(*args, **kwargs):
        raise AssertionError("no model call between update times")
    for name in ("_market_brief_ai_polish", "_jp_market_comparison_cached", "_market_brief_history_save"):
        monkeypatch.setattr(scanner, name, forbidden)
    monkeypatch.setattr(scanner, "_jp_market_internals_cached", lambda: {})
    result = scanner._market_brief_refresh(allow_ai=True)
    assert result["generationReuse"]["newAiCalls"] == 0
    assert result["unifiedSummary"] == TEXT_ONLY["unifiedSummary"]
    assert result["retainedPresentation"]["presentationStatus"] == "GENERATED"   # the screen keeps a complete edition
    assert state["lastSuccessful"]["presentationStatus"] == "UNAVAILABLE"


def test_the_worker_waits_instead_of_rewriting_every_ten_minutes(monkeypatch):
    clock = [5000.0]
    refreshed = []
    _state(monkeypatch, TEXT_ONLY)
    scanner._MARKET_BRIEF_SCHEDULE["presentationRetryFor"] = TEXT_ONLY["aiDiagnostics"]["completedAt"]
    monkeypatch.setattr(scanner, "_MARKET_BRIEF_WORKER", {"lastAttemptMonotonic": 1.0, "status": "GENERATED"})
    monkeypatch.setattr(scanner, "_MARKET_BRIEF_WORKER_LOCK", threading.Lock())
    monkeypatch.setattr(scanner.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(scanner._OWNER_DIALOGUE_RECOVERY, "tick", lambda: None)
    monkeypatch.setattr(scanner, "_market_brief_history_outcomes", lambda: None)
    monkeypatch.setattr(scanner, "_market_brief_refresh",
                        lambda **kw: refreshed.append(clock[0]) or {"unifiedStatus": "GENERATED"})
    for _ in range(60):                                   # an hour of scheduler passes
        assert scanner._market_brief_worker_tick()["status"] == "NOT_DUE"
        clock[0] += 60
    assert refreshed == []


def test_a_failing_update_time_is_tried_twice_then_waits(monkeypatch):
    # 2026-10-25: a failed generation kept its update time due and was retried
    # every 2-30 minutes without end.
    due = {"due": True, "kind": "SCHEDULED", "slot": "2026-10-26 10:00", "eventIds": [], "reason": "slot_due"}
    state = _state(monkeypatch, COMPLETE, due)
    monkeypatch.setattr(scanner, "_compose_market_brief", lambda: {"facts": []})
    monkeypatch.setattr(scanner, "_jp_market_internals_cached", lambda: {})
    monkeypatch.setattr(scanner, "_market_brief_generation_input_digest", lambda brief, internals: "changed")
    monkeypatch.setattr(scanner.argus_index_research_cache, "comparison_availability_improved", lambda *a, **k: False)
    monkeypatch.setattr(scanner, "_jp_market_comparison_cached", lambda horizon: {})
    monkeypatch.setattr(scanner.argus_market_brief, "calculation_facts", lambda calculations: [])
    monkeypatch.setattr(scanner.jp_market_internals, "explanation_facts", lambda internals: [])
    monkeypatch.setattr(scanner.argus_market_brief, "bound_facts", lambda facts: facts)
    monkeypatch.setattr(scanner.argus_market_brief, "unified_context", lambda brief, previous=None: {})
    calls = []

    def failing(brief):
        calls.append(1)
        return {**brief, "unifiedStatus": "REJECTED"}
    monkeypatch.setattr(scanner, "_market_brief_ai_polish", failing)
    for _ in range(4):
        scanner._market_brief_refresh(allow_ai=True)
    assert len(calls) == scanner._MARKET_BRIEF_ATTEMPTS_PER_DUE == 2
    assert scanner._market_brief_due(COMPLETE)["reason"] == "attempts_exhausted"
    later = {**due, "slot": "2026-10-26 11:00"}                 # the next update time is tried again
    monkeypatch.setattr(scanner, "_market_brief_schedule_decision", lambda prev: dict(later))
    assert scanner._market_brief_due(COMPLETE)["due"] is True
    assert state["lastSuccessful"] == COMPLETE
