"""ARGUS Pro — retained symbol-parameterized route regression tests.

These lock in the retained institutional-intelligence route so it cannot
regress to a malformed double-slash or trailing-slash form.

⚠ IMPORTANT for reviewers (incl. LLM reviewers): the correct Flask routes contain
the converter <symbol>, e.g. "/api/argus/events/<symbol>/institutional-intelligence". If you
view this file (or scanner.py) through anything that renders "<symbol>" as an HTML
tag, the angle-bracketed segment is STRIPPED and the path COLLAPSES to look like
"/api/argus/events//institutional-intelligence". That is a rendering artifact, NOT a real
double-slash route. Verify against the RAW bytes or the Flask url_map:
    python -c "import scanner; print([str(r) for r in scanner.app.url_map.iter_rules() if 'institutional-intelligence' in str(r)])"
Do NOT 'fix' these by writing literal "//" routes — that would break them.
"""
import scanner


def _rules():
    return sorted(str(r) for r in scanner.app.url_map.iter_rules())


def test_event_institutional_intelligence_route_is_symbol_parameterised():
    rules = _rules()
    assert "/api/argus/events/<symbol>/institutional-intelligence" in rules
    assert not any("events//institutional-intelligence" in r for r in rules)


def test_event_institutional_intelligence_MU_returns_200_symbol_items():
    with scanner.app.test_client() as c:
        r = c.get("/api/argus/events/MU/institutional-intelligence")
    assert r.status_code == 200 and r.is_json
    d = r.get_json()
    assert d.get("symbol") == "MU"
    assert isinstance(d.get("items"), list)


def test_event_institutional_intelligence_returns_controlled_not_500():
    with scanner.app.test_client() as c:
        for sym in ("MU", "8058"):
            r = c.get(f"/api/argus/events/{sym}/institutional-intelligence")
            assert r.status_code not in (404, 500), (sym, r.get_data(as_text=True)[:200])
            assert r.is_json


def test_no_malformed_double_slash_api_routes():
    # guard the whole /api/argus surface against '//' route typos
    for r in _rules():
        if r.startswith("/api/argus"):
            assert "//" not in r, r
