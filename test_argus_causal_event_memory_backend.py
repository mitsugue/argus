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


def test_live_normalized_event_appends_and_health_route_is_compact(memory_runtime):
    row = scanner._causal_memory_process_normalized_event(normalized())
    assert row["eventId"] == "nie-live-1"
    state = scanner._causal_memory_ensure_loaded()
    event = cem.event_view(state["events"]["nie-live-1"])
    assert event["origin"] == "FORWARD_LIVE"
    assert event["calibrationMode"] == "SHADOW"
    assert event["initialSeverity"] == "WATCH"
    assert event["sdaAuthority"] is False
    client = scanner.app.test_client()
    health = client.get("/api/argus/event-memory/health").get_json()
    assert health["status"] == "HEALTHY"
    assert health["eventCount"] == 1
    assert health["rawArticleBodiesStored"] is False
    assert health["ownerPortfolioFieldsStored"] is False
    assert health["automaticCalibrationEnabled"] is False
    assert "excerpt" not in json.dumps(health, ensure_ascii=False)
    # The unused browser list/detail views were retired on 2026-10-23.
    assert client.get("/api/argus/event-memory").status_code == 404
    assert client.get("/api/argus/event-memory/nie-live-1").status_code == 404


def test_backfill_is_retained_but_excluded_from_forward_maturity(memory_runtime):
    scanner._causal_memory_process_normalized_event(normalized(backfill=True))
    state = scanner._causal_memory_ensure_loaded()
    assert cem.event_view(state["events"]["nie-live-1"])["origin"] == "BACKFILL"
    assert cem.maturity(state, as_of=NOW)["forwardLiveIndependentEpisodes"] == 0


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


def test_low_value_setup_mail_is_counted_as_skip_not_event(memory_runtime):
    low = normalized(headline="Subscription Change Confirmation")
    assert scanner._causal_memory_process_normalized_event(low) is None
    state = scanner._causal_memory_ensure_loaded()
    assert state["events"] == {}
    assert scanner._CAUSAL_MEMORY["skippedLowValue"] == 1
