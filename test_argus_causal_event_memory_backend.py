import json

import pytest

import argus_causal_event_memory as cem
import scanner


NOW = "2026-08-20T10:00:00Z"


@pytest.fixture()
def memory_runtime(monkeypatch, tmp_path):
    monkeypatch.setattr(scanner, "_ai_now_iso", lambda: NOW)
    monkeypatch.setattr(scanner, "_causal_memory_file",
                        lambda: str(tmp_path / "causal_events.jsonl"))
    monkeypatch.setattr(scanner, "_CAUSAL_MEMORY", {
        "loaded": False, "state": cem.empty_state(), "loadStatus": "NOT_LOADED",
        "lastAppendAt": None, "lastRefreshAt": None, "lastRefreshEpoch": 0.0,
        "skippedLowValue": 0, "appendFailures": 0, "lastErrorClass": None,
    })
    monkeypatch.setattr(scanner, "_causal_memory_code_identity", lambda: "b" * 40)
    return tmp_path


def normalized(event_id="nie-live-1", *, headline="ホルムズ海峡の緊張が上昇",
               event_type="HORMUZ", severity="WATCH", backfill=False):
    return {
        "schemaVersion": "argus-news-event-v1", "eventId": event_id,
        "source": "Nikkei", "sourceFamily": "NIKKEI",
        "sourceTier": "trusted_subscription", "sourceFingerprint": "fp-" + event_id,
        "sourceReceivedAt": "2026-08-20T09:59:00Z", "sourcePublishedAt": None,
        "processedAt": NOW, "headlineJa": headline, "eventType": event_type,
        "themeTags": ["ENERGY", "LONG_DURATION_GROWTH"],
        "facts": ["海峡の緊張が上昇"], "entities": ["IRAN"], "sourceUrl": None,
        "severity": severity, "severityReasons": ["family_hormuz"],
        "dataInput": False,
        "marketReadings": [{"key": "oil", "value": 92.0, "change": 2.5,
                            "unit": "USD", "asOf": "2026-08-20"}],
        "authority": "NEWS_RISK_EVIDENCE", "sdaAuthority": False,
        "backfill": backfill,
    }


def test_live_normalized_event_appends_and_public_routes_are_compact(memory_runtime):
    row = scanner._causal_memory_process_normalized_event(normalized())
    assert row["eventId"] == "nie-live-1"
    client = scanner.app.test_client()
    view = client.get("/api/argus/event-memory").get_json()
    assert view["eventCount"] == 1
    assert view["events"][0]["origin"] == "FORWARD_LIVE"
    assert view["events"][0]["calibrationMode"] == "SHADOW"
    assert "causalHypotheses" not in view["events"][0]  # compact browser DTO
    detail = client.get("/api/argus/event-memory/nie-live-1").get_json()
    assert detail["event"]["initialSeverity"] == "WATCH"
    assert detail["event"]["sdaAuthority"] is False
    assert detail["analogs"]["insufficientEvidence"] is True
    health = client.get("/api/argus/event-memory/health").get_json()
    assert health["status"] == "HEALTHY"
    assert health["rawArticleBodiesStored"] is False
    assert health["ownerPortfolioFieldsStored"] is False
    assert health["automaticCalibrationEnabled"] is False
    assert "excerpt" not in json.dumps(detail, ensure_ascii=False)


def test_backfill_is_retained_but_excluded_from_forward_maturity(memory_runtime):
    scanner._causal_memory_process_normalized_event(normalized(backfill=True))
    body = scanner.app.test_client().get("/api/argus/event-memory").get_json()
    assert body["events"][0]["origin"] == "BACKFILL"
    assert body["maturity"]["forwardLiveIndependentEpisodes"] == 0


def test_market_shock_creates_real_structured_rates_event(memory_runtime):
    scanner._causal_memory_process_market_shock({
        "generatedAt": NOW,
        "events": [{
            "eventId": "long-end-rates:2026-08-20", "eventClass": "LONG_END_RATES",
            "severity": "HIGH", "headlineJa": "米30年債利回り 5.30%",
            "evidence": {"level": 5.30, "change5dBp": 8.0,
                         "latestDate": "2026-08-20", "reasons": ["level_above_5pct"]},
        }],
    })
    state = scanner._causal_memory_ensure_loaded()
    event = cem.event_view(state["events"]["long-end-rates:2026-08-20"])
    assert event["eventType"] == "RATES"
    assert event["initialSeverity"] == "HIGH"
    assert event["marketContextRef"].startswith("cmc-")


def test_admin_review_is_append_only_and_auth_gated(memory_runtime, monkeypatch):
    scanner._causal_memory_process_normalized_event(normalized())
    client = scanner.app.test_client()
    denied = client.post("/api/argus/admin/event-memory/review", json={})
    assert denied.status_code in (401, 403, 503)
    monkeypatch.setattr(scanner, "_ARGUS_ADMIN_TOKEN", "event-memory-test")
    allowed = client.post(
        "/api/argus/admin/event-memory/review",
        headers={"X-ARGUS-ADMIN-TOKEN": "event-memory-test"},
        json={"eventId": "nie-live-1", "reviewType": "FALSE_ALERT_REVIEW",
              "reasonCodes": ["NO_INTERMEDIATE_CONFIRMATION"],
              "policyChangeWarranted": False, "findingAt": NOW})
    assert allowed.status_code == 200
    assert allowed.get_json()["historyMutated"] is False
    raw = scanner._causal_memory_ensure_loaded()["events"]["nie-live-1"]
    assert len(raw["revisions"]) == 1
    assert len(raw["reviews"]) == 1


def test_admin_outcome_appends_unscorable_window_without_decision_rescore(
        memory_runtime, monkeypatch):
    created = scanner._causal_memory_process_normalized_event(normalized())
    hypothesis_id = created["causalHypotheses"][0]["hypothesisId"]
    client = scanner.app.test_client()
    assert client.post("/api/argus/admin/event-memory/outcome", json={}).status_code \
        in (401, 403, 503)
    monkeypatch.setattr(scanner, "_ARGUS_ADMIN_TOKEN", "event-memory-test")
    response = client.post(
        "/api/argus/admin/event-memory/outcome",
        headers={"X-ARGUS-ADMIN-TOKEN": "event-memory-test"},
        json={"eventId": "nie-live-1", "hypothesisId": hypothesis_id,
              "horizon": "1H", "targetAt": NOW, "observedAt": NOW,
              "knownAt": NOW, "missingReasons": ["official_close_unavailable"]})
    assert response.status_code == 200
    body = response.get_json()
    assert body["ok"] is True and body["status"] == "UNSCORABLE"
    assert body["horizon"] == "1H" and body["policyInfluence"] is False
    assert body["predictionLedgerScoringReused"] is True
    assert body["recordId"].startswith("cemr-")
    raw = scanner._causal_memory_ensure_loaded()["events"]["nie-live-1"]
    assert len(raw["revisions"]) == 1
    assert len(raw["outcomes"]) == 1
    assert raw["outcomes"][0]["metrics"] == []


def test_low_value_setup_mail_is_counted_as_skip_not_event(memory_runtime):
    low = normalized(headline="Subscription Change Confirmation")
    assert scanner._causal_memory_process_normalized_event(low) is None
    state = scanner._causal_memory_ensure_loaded()
    assert state["events"] == {}
    assert scanner._CAUSAL_MEMORY["skippedLowValue"] == 1
