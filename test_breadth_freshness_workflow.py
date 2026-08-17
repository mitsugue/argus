import datetime as dt
import json
from pathlib import Path
import tempfile

from scripts.run_breadth_freshness import (
    classify_terminal,
    ledger_summary,
    run,
    weekday_candidate,
)


ROOT = Path(__file__).resolve().parent


def _ledger(day: str):
    return {
        "observationCount": 20349,
        "stateHash": "abc123",
        "methodVersion": "breadth-v1",
        "table": [
            {"seriesId": "breadth.all.advancers", "periodEnd": day},
            {"seriesId": "breadth.all.decliners", "periodEnd": day},
            {"seriesId": "breadth.topixProxyClose", "periodEnd": day},
            {"seriesId": "breadth.all.ratio6", "periodEnd": day, "latestValue": 101.2},
        ],
        "turningPoints": [{"id": "turn-1"}],
    }


def test_weekend_candidate_rolls_back_to_friday():
    sunday = dt.datetime(2026, 7, 26, 9, tzinfo=dt.timezone.utc)
    assert weekday_candidate(sunday) == "2026-07-24"


def test_ledger_summary_records_required_read_back_fields():
    summary = ledger_summary(_ledger("2026-07-24"))
    assert summary == {
        "breadthNewestDate": "2026-07-24",
        "marketPriceNewestDate": "2026-07-24",
        "lagTradingDays": None,
        "ratios": {"6": 101.2, "10": None, "15": None, "25": None},
        "rowCount": 20349,
        "turningPointCount": 1,
        "stateHash": "abc123",
        "methodVersion": "breadth-v1",
    }


def test_terminal_classification_distinguishes_all_four_states():
    before = ledger_summary(_ledger("2026-07-23"))
    after = ledger_summary(_ledger("2026-07-24"))
    assert classify_terminal({"status": "completed", "result": {}},
                             before, after, "2026-07-24") == "success"
    assert classify_terminal({"status": "completed", "result": {}},
                             after, after, "2026-07-24") == "no_new_session"
    assert classify_terminal(
        {"status": "failed", "errorClass": "jquants_recent_confirmed_date_not_found"},
        before, before, "2026-07-24",
    ) == "provider_not_ready"
    assert classify_terminal({"status": "failed", "errorClass": "invalid_contract"},
                             before, before, "2026-07-24") == "failure"


def test_workflow_is_natural_single_flight_and_backend_safe():
    workflow = (ROOT / ".github/workflows/breadth-freshness.yml").read_text()
    runner = (ROOT / "scripts/run_breadth_freshness.py").read_text()
    assert "workflow_dispatch" not in workflow
    assert "17 8 * * 1-5" in workflow
    assert "cancel-in-progress: false" in workflow
    assert "ARGUS_ADMIN_TOKEN" in workflow
    assert "JQUANTS_BREADTH_INCREMENTAL" in runner
    assert '"triggerSource": "github_schedule"' in runner
    assert '"manualTick": False' in runner
    assert "/api/argus/admin/mission" not in runner
    assert "/api/argus/admin/heartbeat" not in runner
    assert "restart" not in workflow.lower()
    assert "deploy" not in workflow.lower()


def test_already_published_run_is_get_only_and_verifies_identity():
    calls = []

    def fake_request(url, **kwargs):
        calls.append((url, kwargs.get("payload")))
        if url.endswith("/healthz"):
            return {
                "backendVersion": "13.3.2", "buildSha": "e" * 40,
            }
        if url.endswith("/readyz"):
            return {"ready": True}
        if url.endswith("/api/argus/market-ledger"):
            return {**_ledger("2026-07-27"), "latestConfirmedTradingDate": "2026-07-27"}
        if url.endswith("/api/argus/admin/diagnostics/operational"):
            return {
                "schemaVersion": "argus-operational-diagnostics-v1",
                "service": {
                    "backendVersion": "13.3.2", "buildSha": "e" * 40,
                    "processBootedAt": "2026-07-27T09:05:36+09:00",
                },
                "features": {
                    "soakState": "running", "soakArmed": True,
                },
                "remoteJournal": {
                    "readBackVerified": True,
                    "walReadBackVerified": True,
                    "pendingCount": 0,
                },
            }
        raise AssertionError(url)

    with tempfile.TemporaryDirectory() as tmp:
        artifact = Path(tmp) / "evidence.json"
        result = run(
            base_url="https://example.test",
            token="redacted",
            artifact_path=artifact,
            attempts=3,
            retry_seconds=0,
            poll_seconds=1,
            max_wait_seconds=1,
            now=dt.datetime(2026, 7, 27, 9, tzinfo=dt.timezone.utc),
            request=fake_request,
            sleeper=lambda _: None,
        )
        evidence = json.loads(artifact.read_text())
    assert result == 0
    assert evidence["classification"] == "no_new_session"
    assert evidence["backendIdentityStable"] is True
    assert evidence["soakIdentityStable"] is True
    assert evidence["before"]["lagTradingDays"] == 0
    assert all(payload is None for _, payload in calls)
