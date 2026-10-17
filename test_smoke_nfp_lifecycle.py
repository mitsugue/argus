import copy
import pytest
import smoke_test


def _payloads(at="2026-09-08T12:30:00Z"):
    record = {"eventId": "nfp-1", "eventCode": "NFP", "eventTimeUtc": at,
              "actual": {"available": True}}
    card = {"eventId": "nfp-1", "eventCode": "NFP", "state": "post_result",
            "display": {"showActualFirst": True},
            "officialResult": {"headlineJa": "公式結果"}, "caos": {"impactCommentJa": "市場反応"}}
    return {"items": [record]}, {"asOf": "2026-09-09T00:00:00Z", "items": [card]}


def _probe(monkeypatch, macro, dashboard):
    monkeypatch.setattr(smoke_test, "_get", lambda path: (200, copy.deepcopy(
        macro if "macro-event-analysis" in path else dashboard)))
    return smoke_test.v_dashboard_events_nfp()


def test_old_actual_does_not_require_an_archived_card_on_current_surface(monkeypatch):
    macro, dashboard = _payloads("2026-08-07T12:30:00Z")
    dashboard["items"] = []
    ok, note = _probe(monkeypatch, macro, dashboard)
    assert ok and "archived outside 72h=1" in note


@pytest.mark.parametrize("fault", ["missing", "wrong_event", "pre", "no_actual_first", "no_facts", "no_impact"])
def test_recent_actual_still_requires_same_event_with_complete_post_state(monkeypatch, fault):
    macro, dashboard = _payloads()
    card = dashboard["items"][0]
    if fault == "missing": dashboard["items"] = []
    elif fault == "wrong_event": card["eventId"] = "nfp-next-month"
    elif fault == "pre": card["state"] = "pre"
    elif fault == "no_actual_first": card["display"] = {}
    elif fault == "no_facts": card["officialResult"] = {}
    elif fault == "no_impact": card["caos"] = {}
    assert _probe(monkeypatch, macro, dashboard)[0] is False


def test_recent_valid_post_passes_and_undated_actual_does_not(monkeypatch):
    macro, dashboard = _payloads()
    assert _probe(monkeypatch, macro, dashboard)[0] is True
    macro["items"][0]["eventTimeUtc"] = None
    assert _probe(monkeypatch, macro, dashboard)[0] is False
