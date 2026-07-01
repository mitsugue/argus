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


def test_no_malformed_double_slash_api_routes():
    # guard the whole /api/argus surface against '//' route typos
    for r in _rules():
        if r.startswith("/api/argus"):
            assert "//" not in r, r
