"""ARGUS Pro — route regression tests.

Phase 1 of the ARGUS Pro Free-First build. These lock in the fix for the
symbol-parameterised routes so they can never regress to the malformed
'/events//research-mission' or trailing-'/positioning/' patterns (which would
500 on a route/signature mismatch). A controlled JSON error is acceptable; a
raw Flask 500 from a routing/arg mismatch is not.
"""
import scanner


def _rules():
    return sorted(str(r) for r in scanner.app.url_map.iter_rules())


def test_research_mission_route_is_symbol_parameterised():
    rules = _rules()
    assert "/api/argus/events/<symbol>/research-mission" in rules
    # the malformed empty-segment form must never exist
    assert not any("events//research-mission" in r for r in rules)


def test_positioning_route_is_symbol_parameterised():
    rules = _rules()
    assert "/api/argus/institutional-intelligence/positioning/<symbol>" in rules
    # a trailing-slash form with no converter would 404/500 for a real symbol
    assert "/api/argus/institutional-intelligence/positioning/" not in rules


def test_research_mission_returns_controlled_response_not_500():
    with scanner.app.test_client() as c:
        for sym in ("NVDA", "8058"):
            r = c.get(f"/api/argus/events/{sym}/research-mission")
            # 200 (ok) or a controlled 4xx/503 — never a 500 from route/signature mismatch
            assert r.status_code != 500, (sym, r.get_data(as_text=True)[:200])
            assert r.is_json


def test_positioning_returns_controlled_response_not_500():
    with scanner.app.test_client() as c:
        for sym in ("NVDA", "8058"):
            r = c.get(f"/api/argus/institutional-intelligence/positioning/{sym}")
            assert r.status_code != 500, (sym, r.get_data(as_text=True)[:200])
            assert r.is_json


def test_event_institutional_intelligence_route_is_symbol_parameterised():
    rules = _rules()
    assert "/api/argus/events/<symbol>/institutional-intelligence" in rules
    assert not any("events//institutional-intelligence" in r for r in rules)


def test_event_institutional_intelligence_returns_controlled_not_500():
    with scanner.app.test_client() as c:
        for sym in ("MU", "8058"):
            r = c.get(f"/api/argus/events/{sym}/institutional-intelligence")
            assert r.status_code not in (404, 500), (sym, r.get_data(as_text=True)[:200])
            assert r.is_json


def test_whitespace_symbol_rejected_not_200():
    # a whitespace-only symbol must be a controlled 400, never a spurious 200
    with scanner.app.test_client() as c:
        r1 = c.get("/api/argus/events/%20/research-mission")
        r2 = c.get("/api/argus/institutional-intelligence/positioning/%20")
        r3 = c.get("/api/argus/events/%20/institutional-intelligence")
    for r in (r1, r2, r3):
        assert r.status_code == 400 and r.get_json().get("error") == "symbol_required"


def test_research_mission_is_deterministic_no_llm():
    with scanner.app.test_client() as c:
        d = c.get("/api/argus/events/MU/research-mission").get_json()
    cost = d.get("cost") or {}
    assert cost.get("llmCalls") == 0            # public GET must never call an LLM
    assert cost.get("deterministic") is True


def test_positioning_probabilities_sum_to_one():
    with scanner.app.test_client() as c:
        d = c.get("/api/argus/institutional-intelligence/positioning/MU").get_json()
    probs = d.get("probabilities")
    if probs:                                    # present → must be a proper distribution
        assert abs(sum(v for v in probs.values() if isinstance(v, (int, float))) - 1.0) < 1e-6


def test_public_intel_gets_never_fetch(monkeypatch):
    # public read paths must serve from the already-collected store, never fetch.
    called = {"n": 0}
    monkeypatch.setattr(scanner, "_fetch_public_text",
                        lambda *a, **k: called.__setitem__("n", called["n"] + 1) or None)
    with scanner.app.test_client() as c:
        c.get("/api/argus/institutional-intelligence/brief")
        c.get("/api/argus/institutional-intelligence/relationship-graph")
        c.get("/api/argus/events/MU/research-mission")
        c.get("/api/argus/events/MU/institutional-intelligence")
        c.get("/api/argus/institutional-intelligence/positioning/MU")
    assert called["n"] == 0


def test_no_malformed_double_slash_api_routes():
    # guard the whole /api/argus surface against '//' route typos
    for r in _rules():
        if r.startswith("/api/argus"):
            assert "//" not in r, r
