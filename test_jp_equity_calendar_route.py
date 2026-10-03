import requests

import scanner


def test_equity_calendar_route_serves_meaning_without_fetching(monkeypatch):
    monkeypatch.setattr(scanner, "_ai_now_iso", lambda: "2026-10-02T13:00:00Z")
    def forbidden(*args, **kwargs):
        raise AssertionError("the calendar must not call external services")
    monkeypatch.setattr(requests.sessions.Session, "request", forbidden)
    body = scanner.app.test_client().get("/api/argus/jp-equity-calendar").get_json()
    assert body["schemaVersion"] == "jp-equity-event-calendar-v1"
    assert body["automaticAiCalls"] == 0 and body["actionAuthority"] is False
    assert all(row["soWhatJa"] for row in body["events"])
    assert any(row["kind"] == "JP_CPI" for row in body["events"])
