"""The published calendar remains usable without pricing, AI or monetary gates."""
from datetime import datetime
import copy
import json

import requests

import jp_market_events
import scanner


def test_actual_public_calendar_does_not_fetch_charge_or_write(monkeypatch):
    monkeypatch.setattr(scanner, "_ai_now_iso", lambda: "2026-09-12T10:00:00Z")
    def forbidden(*args, **kwargs):
        raise AssertionError("published schedule must not depend on external services")
    monkeypatch.setattr(requests.sessions.Session, "request", forbidden)
    for name in ("_openai_prose", "_openai_judge", "_cost_policy_persist_durable", "get_events_snapshot"):
        monkeypatch.setattr(scanner, name, forbidden)
    before = copy.deepcopy(scanner._COST_POLICY)
    with scanner.app.test_client() as client:
        response = client.get("/api/argus/jp-sq-calendar")
    assert response.status_code == 200
    body = response.get_json()
    assert body["status"] == "AVAILABLE"
    assert [(e["sqDate"], e["lastTradingDate"]) for e in body["events"]] == [("2026-10-09", "2026-10-08")]
    assert body["automaticAiCalls"] == 0 and body["actionAuthority"] is False
    assert body["lastSuccessfulAcquisitionAt"] == body["events"][0]["knownAt"]
    assert scanner._COST_POLICY == before


def test_missing_and_corrupt_calendar_are_visible_and_not_created(tmp_path):
    path = tmp_path / "calendar.json"
    now = datetime.fromisoformat("2026-09-12T19:00:00+09:00")
    for content in (None, b"{", b"x" * 65537, b"{}", b"[]"):
        if content is not None:
            path.write_bytes(content)
        result = jp_market_events.published_sq_calendar(now=now, schedule_path=path)
        assert result["status"] == "UNAVAILABLE"
        assert result["events"] == []
        assert result["gaps"] == ["official_schedule_unavailable"]
        assert result["lastSuccessfulAcquisitionAt"] is None
        assert (path.read_bytes() if path.exists() else None) == content


def test_uncovered_next_year_is_partial_and_never_synthesized():
    result = jp_market_events.published_sq_calendar(now=datetime.fromisoformat("2026-12-20T10:00:00+09:00"))
    assert result["status"] == "PARTIAL"
    assert result["events"] == []
    assert "official_schedule_does_not_cover_full_horizon" in result["gaps"]


def test_previous_session_and_sq_date_do_not_become_economic_result_wait(monkeypatch):
    monkeypatch.setattr(scanner, "_ai_now_iso", lambda: "2026-10-08T00:00:00Z")
    with scanner.app.test_client() as client:
        row = client.get("/api/argus/jp-sq-calendar").get_json()["events"][0]
    assert row["stage"] == "LAST_TRADING_DAY"
    assert row["fixedPublicationTime"] is None and row["requiresAiResult"] is False
    assert row["directionalSignal"] is None
