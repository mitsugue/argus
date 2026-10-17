"""Tests for argus_mission_trigger (mission gating). Pure, stdlib-only."""
import argus_mission_trigger as T


def test_held_high_downside_fires_owner_relevant():
    tr = T.plan_triggers(
        downside_incidents=[{"symbol": "5803", "severity": "high", "detectedAt": "2026-07-01T05:00:00Z"}],
        held_symbols=["5803"])
    assert len(tr) == 1 and tr[0]["symbol"] == "5803"
    assert tr[0]["ownerRelevant"] is True
    assert tr[0]["moveStartedAt"] == "2026-07-01T05:00:00Z"   # REAL, not fabricated

def test_unexplained_downside_fires_even_if_not_held():
    tr = T.plan_triggers(downside_incidents=[{"symbol": "9999", "severity": "medium"}], held_symbols=[])
    assert any(t["symbol"] == "9999" and "原因未確認" in t["reason"] for t in tr)

def test_imminent_high_event_on_watched_symbol():
    tr = T.plan_triggers(
        important_events=[{"eventCode": "FOMC", "displayImpact": "high", "daysUntil": 1, "linkedAssets": ["NVDA"]}],
        watch_symbols=["NVDA"])
    assert any(t["symbol"] == "NVDA" and t["kind"] == "event" for t in tr)

def test_far_event_does_not_fire():
    tr = T.plan_triggers(
        important_events=[{"eventCode": "FOMC", "displayImpact": "high", "daysUntil": 20, "linkedAssets": ["NVDA"]}],
        watch_symbols=["NVDA"])
    assert tr == []

def test_institutional_action_on_watch_fires():
    tr = T.plan_triggers(
        new_intel=[{"category": "ANALYST_ACTION", "linkedAssets": ["7203"], "institutionId": "goldman_sachs"}],
        watch_symbols=["7203"])
    assert any(t["symbol"] == "7203" and t["kind"] == "institutional" for t in tr)

def test_intel_on_unwatched_symbol_ignored():
    tr = T.plan_triggers(
        new_intel=[{"category": "ANALYST_ACTION", "linkedAssets": ["ZZZZ"], "institutionId": "goldman_sachs"}],
        watch_symbols=["7203"])
    assert tr == []

def test_dedup_keeps_highest_severity():
    tr = T.plan_triggers(
        downside_incidents=[{"symbol": "5803", "severity": "critical"}, {"symbol": "5803", "severity": "low"}],
        held_symbols=["5803"])
    syms = [t["symbol"] for t in tr]
    assert syms.count("5803") == 1
    assert tr[0]["severity"] == "critical"

def test_to_event_never_fabricates_move():
    tr = T.plan_triggers(new_intel=[{"category": "ANALYST_ACTION", "linkedAssets": ["7203"], "institutionId": "goldman_sachs"}],
                         watch_symbols=["7203"])
    ev = T.to_event(tr[0])
    assert ev["linkedAssets"] == ["7203"]
    # publishedAt was absent → moveStartedAt stays None, not a fake "now"
    assert ev["moveStartedAt"] is None

def test_deterministic():
    kw = dict(downside_incidents=[{"symbol": "A", "severity": "high"}], held_symbols=["A"])
    assert T.plan_triggers(**kw) == T.plan_triggers(**kw)
