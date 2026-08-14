"""Recovery Phase A PR B trust-boundary contract tests."""
from __future__ import annotations

import copy
import inspect
import json
from pathlib import Path
import re

import pytest
import requests as http_requests

import argus_diagnostics_contract as diagnostics
import argus_route_catalog as catalog
import scanner


FIXED_NOW = "2026-08-14T04:00:00Z"
ADMIN_HEADER = {"X-ARGUS-ADMIN-TOKEN": "boundary-test-admin"}


PUBLIC_KEYS = {
    "schemaVersion", "generatedAt", "service", "freshness", "recovery",
}
SERVICE_KEYS = {
    "liveness", "readiness", "overall", "backendVersion", "buildSha",
}
FRESHNESS_KEYS = {"overall", "sourceCounts", "expectedDisabledCount"}
SOURCE_COUNT_KEYS = {"fresh", "aging", "stale", "unknown"}
RECOVERY_KEYS = {
    "mode", "measurement", "exactColdRecovery", "hardRpoClaimPermitted",
}
OPERATIONAL_KEYS = {
    "schemaVersion", "generatedAt", "service", "freshness", "storage",
    "durability", "remoteJournal", "features", "scheduler", "registry",
    "osint", "costPolicy",
}


def _serialized(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")


def _assert_public_contract(body):
    assert set(body) == PUBLIC_KEYS
    assert set(body["service"]) == SERVICE_KEYS
    assert set(body["freshness"]) == FRESHNESS_KEYS
    assert set(body["freshness"]["sourceCounts"]) == SOURCE_COUNT_KEYS
    assert set(body["recovery"]) == RECOVERY_KEYS
    assert body["schemaVersion"] == diagnostics.PUBLIC_SCHEMA
    assert body["recovery"] == {
        "mode": "LEGACY_ONLY",
        "measurement": "SHADOW_INCOMPLETE",
        "exactColdRecovery": "NOT_PROVEN",
        "hardRpoClaimPermitted": False,
    }
    assert len(_serialized(body)) <= diagnostics.PUBLIC_MAX_BYTES


def test_route_catalog_matches_every_flask_rule_and_is_fail_closed():
    actual = frozenset(
        (rule.rule,
         tuple(sorted(set(rule.methods) - {"HEAD", "OPTIONS"})),
         rule.endpoint)
        for rule in scanner.app.url_map.iter_rules()
        if set(rule.methods) - {"HEAD", "OPTIONS"}
    )
    assert catalog.ROUTE_CATALOG_VALIDATION_ERRORS == ()
    assert catalog.route_contract_keys() == actual
    assert len(catalog.ROUTE_CATALOG) == len(actual)
    assert not [
        row for row in catalog.ROUTE_CATALOG
        if row.trustDomain == "PUBLIC" and row.mutatesState
    ]
    moved = {
        "/api/argus/caos/investigate-now",
        "/api/argus/news/translation-request",
        "/api/argus/osint/deep-dive",
        "/api/argus/osint/terms",
        "/api/argus/osint/verify-gaps",
        "/api/argus/osint/url-verify",
        "/api/argus/mover-causes/explain-request",
        "/api/argus/vault-push",
    }
    by_route = {row.route: row for row in catalog.ROUTE_CATALOG}
    assert all(by_route[path].trustDomain == "AUTH_OPERATIONAL"
               for path in moved)
    assert all(by_route[path].authenticationPolicy == "ADMIN_TOKEN"
               for path in moved)


def test_public_diagnostics_aliases_are_exact_bounded_and_not_proof():
    client = scanner.app.test_client()
    first = client.get("/api/argus/data-quality")
    second = client.get("/api/argus/data-quality/status")
    assert first.status_code == second.status_code == 200
    for response in (first, second):
        _assert_public_contract(response.get_json())


def test_public_liveness_and_readiness_are_minimal_and_preserve_truth(
        monkeypatch):
    monkeypatch.setattr(scanner, "_ai_now_iso", lambda: FIXED_NOW)
    monkeypatch.setitem(scanner._STARTUP, "state", "ready")
    client = scanner.app.test_client()
    health = client.get("/healthz")
    ready = client.get("/readyz")
    assert health.status_code == ready.status_code == 200
    assert set(health.get_json()) == {
        "schemaVersion", "generatedAt", "status", "backendVersion",
        "buildSha",
    }
    assert set(ready.get_json()) == {
        "schemaVersion", "generatedAt", "ready", "status", "reasonCode",
        "backendVersion", "buildSha",
    }
    monkeypatch.setitem(scanner._STARTUP, "state", "bootstrapping")
    monkeypatch.setattr(scanner, "_startup_bootstrap", lambda: None)
    blocked = client.get("/readyz")
    assert blocked.status_code == 503
    assert blocked.get_json()["ready"] is False
    assert blocked.get_json()["reasonCode"] == "BOOTSTRAPPING"


def test_operational_diagnostics_requires_auth_is_fixed_and_not_cors(
        monkeypatch):
    monkeypatch.setattr(scanner, "_ARGUS_ADMIN_TOKEN", "boundary-test-admin")
    client = scanner.app.test_client()
    denied = client.get("/api/argus/admin/diagnostics/operational")
    assert denied.status_code == 401
    assert denied.get_json() == {"error": "unauthorized"}
    response = client.get(
        "/api/argus/admin/diagnostics/operational",
        headers={**ADMIN_HEADER, "Origin": "https://mitsugue.github.io"},
    )
    assert response.status_code == 200
    body = response.get_json()
    assert set(body) == OPERATIONAL_KEYS
    assert body["schemaVersion"] == diagnostics.OPERATIONAL_SCHEMA
    assert body["features"]["exactColdRecovery"] == "NOT_PROVEN"
    assert body["features"]["hardRpoClaimPermitted"] is False
    assert len(_serialized(body)) <= diagnostics.OPERATIONAL_MAX_BYTES
    assert "Access-Control-Allow-Origin" not in response.headers
    assert "no-store" in response.headers["Cache-Control"]


@pytest.mark.parametrize("path,payload", [
    ("/api/argus/caos/investigate-now", {"symbol": "5803", "market": "JP"}),
    ("/api/argus/news/translation-request", {"context": "x", "items": []}),
    ("/api/argus/osint/deep-dive", {"symbol": "5803", "market": "JP"}),
    ("/api/argus/osint/terms", {"terms": ["semiconductor"]}),
    ("/api/argus/osint/verify-gaps", {"symbol": "5803"}),
    ("/api/argus/osint/url-verify", {"url": "https://example.com/news"}),
    ("/api/argus/mover-causes/explain-request", {"symbol": "NVDA", "market": "US"}),
    ("/api/argus/vault-push", {"vaultId": "v" * 64, "blob": "ciphertext"}),
])
def test_moved_posts_reject_unauthenticated_before_handler_and_auth_reaches_it(
        monkeypatch, path, payload):
    monkeypatch.setattr(scanner, "_ARGUS_ADMIN_TOKEN", "boundary-test-admin")
    client = scanner.app.test_client()
    denied = client.post(path, json=payload)
    assert denied.status_code == 401
    assert denied.get_json() == {"error": "unauthorized"}
    allowed = client.post(path, json=payload, headers=ADMIN_HEADER)
    assert allowed.status_code != 401
    assert allowed.get_json() != {"error": "unauthorized"}


def test_hostile_internal_and_future_fields_never_reach_public_diagnostics(
        monkeypatch):
    sentinel = "BOUNDARY-SENTINEL-7c443ca5"
    monkeypatch.setattr(scanner, "_ai_now_iso", lambda: FIXED_NOW)
    targets = (
        scanner._REMOTE_CYCLE,
        scanner._DURABLE_STATE,
        scanner._CHECKPOINT_V2_STATUS,
        scanner._AI_INTEGRITY,
        scanner._OSINT_STORE,
    )
    for target in targets:
        if isinstance(target, dict):
            monkeypatch.setitem(target, "futureSecurityField", sentinel)
    if scanner._INCIDENTS:
        monkeypatch.setitem(scanner._INCIDENTS[0], "futureOwnerImpact", sentinel)
    else:
        monkeypatch.setattr(
            scanner, "_INCIDENTS", [{"futureOwnerImpact": sentinel}])
    for name in ("_MISSIONS", "_PERIODIC_REPORTS", "_CHALLENGER_RUNS",
                 "_POSTMORTEMS"):
        value = getattr(scanner, name)
        replacement = copy.deepcopy(value)
        if isinstance(replacement, list):
            replacement.append({"futureSecurityField": sentinel})
        elif isinstance(replacement, dict):
            replacement["futureSecurityField"] = sentinel
        monkeypatch.setattr(scanner, name, replacement)
    client = scanner.app.test_client()
    for path in ("/healthz", "/readyz", "/api/argus/data-quality",
                 "/api/argus/data-quality/status"):
        response = client.get(path)
        assert sentinel not in response.get_data(as_text=True)


def _public_probe_path(rule):
    values = {
        "symbol": "SENTINELSYM", "market": "JP",
        "card_id": "missing-card", "lesson_id": "missing-lesson",
        "eid": "missing-event", "oid": "missing-official",
        "filename": "missing-static.js",
    }
    return re.sub(
        r"<(?:(?:string|path|int):)?([^>]+)>",
        lambda match: values.get(match.group(1), "missing"), rule,
    )


def test_every_catalogued_public_route_rejects_private_domain_sentinels(
        monkeypatch):
    """Bounded route-wide hostile test required by the public-boundary RFC."""
    sentinels = {
        "remote": "REMOTE_CYCLE_PRIVATE_SENTINEL",
        "durable": "DURABLE_STATE_PRIVATE_SENTINEL",
        "incident": "INCIDENT_PRIVATE_SENTINEL",
        "osint": "OSINT_PRIVATE_SENTINEL",
        "mission": "MISSION_PRIVATE_SENTINEL",
        "v2": "V2_SECURITY_SENTINEL",
        "owner": "OWNER_DECISION_SENTINEL",
        "report": "PRIVATE_REPORT_SENTINEL",
        "postmortem": "PRIVATE_POSTMORTEM_SENTINEL",
        "model": "MODEL_OUTPUT_SENTINEL",
        "owner_data": "OWNER_DATA_SENTINEL",
    }

    def offline(*_args, **_kwargs):
        raise http_requests.exceptions.ConnectionError("public-route-test-offline")

    monkeypatch.setattr(scanner.requests, "get", offline)
    monkeypatch.setattr(scanner.requests, "post", offline)
    monkeypatch.setitem(scanner._STARTUP, "state", "ready")
    monkeypatch.setitem(scanner._NEWS_JA_STATE, "restored", True)
    monkeypatch.setitem(scanner._REMOTE_CYCLE, "errorClass", sentinels["remote"])
    monkeypatch.setitem(
        scanner._REMOTE_CYCLE, "futureSecurityField", sentinels["remote"])
    monkeypatch.setitem(
        scanner._DURABLE_STATE, "lastFailureMessage", sentinels["durable"])
    monkeypatch.setitem(
        scanner._DURABLE_STATE, "futureSecurityField", sentinels["durable"])
    monkeypatch.setitem(
        scanner._CHECKPOINT_V2_STATUS, "futureSecurityField", sentinels["v2"])
    monkeypatch.setitem(scanner._AI_INTEGRITY, "futureModelOutput", sentinels["model"])

    monkeypatch.setitem(scanner._OSINT_STORE, "SENTINELSYM", {
        "schemaVersion": "osint-investigation-v1",
        "symbol": "SENTINELSYM",
        "futureSecurityField": sentinels["osint"],
        "agentRuns": [{"provider": "gpt", "status": "ok",
                       "rawModelOutput": sentinels["model"]}],
        "queryPlan": {"queryCount": 0, "futureOwnerTerms": sentinels["owner_data"]},
        "researchPower": {"futureModelOutput": sentinels["model"]},
    })
    monkeypatch.setitem(scanner._OSINT_PROGRESS, "SENTINELSYM", {
        "stage": "complete", "futureOwnerField": sentinels["owner_data"],
    })
    monkeypatch.setattr(scanner, "_INCIDENTS", copy.deepcopy(scanner._INCIDENTS) + [{
        "id": "sentinel-incident", "component": sentinels["incident"],
        "ownerImpactJa": sentinels["owner_data"],
    }])
    monkeypatch.setattr(scanner, "_MISSIONS", copy.deepcopy(scanner._MISSIONS) + [{
        "missionId": "sentinel-mission",
        "futureSecurityField": sentinels["mission"],
    }])
    monkeypatch.setattr(
        scanner, "_CHALLENGER_RUNS", copy.deepcopy(scanner._CHALLENGER_RUNS) + [{
            "state": "done", "ownerDecision": sentinels["owner"],
        }])
    monkeypatch.setattr(
        scanner, "_PERIODIC_REPORTS", copy.deepcopy(scanner._PERIODIC_REPORTS) + [{
            "futureSecurityField": sentinels["report"],
        }])
    monkeypatch.setattr(
        scanner, "_POSTMORTEMS", copy.deepcopy(scanner._POSTMORTEMS) + [{
            "futureSecurityField": sentinels["postmortem"],
        }])
    monkeypatch.setitem(scanner._MISSION_STORE, "sentinel-event", {
        "trigger": {"eventId": "sentinel-event", "symbol": "SENTINELSYM",
                    "ownerRelevant": sentinels["owner_data"]},
        "argusView": {"synthesis": sentinels["model"]},
        "at": FIXED_NOW,
    })

    query = {
        "/api/argus/osint/investigation": "?symbol=SENTINELSYM",
        "/api/argus/chart-intelligence": "?symbol=SENTINELSYM&market=JP",
        "/api/argus/price-history": "?symbol=SENTINELSYM&market=JP",
    }
    visited = []
    client = scanner.app.test_client()
    for row in catalog.ROUTE_CATALOG:
        if row.trustDomain != "PUBLIC" or "GET" not in row.methods:
            continue
        path = _public_probe_path(row.route) + query.get(row.route, "")
        response = client.get(path)
        visited.append((row.route, response.status_code))
        assert response.status_code < 500, (path, response.status_code)
        body = response.get_data(as_text=True)
        for sentinel in sentinels.values():
            assert sentinel not in body, (path, sentinel)
    assert len(visited) == sum(
        1 for row in catalog.ROUTE_CATALOG
        if row.trustDomain == "PUBLIC" and "GET" in row.methods)


def test_public_projection_is_unchanged_by_unknown_internal_fields(monkeypatch):
    monkeypatch.setattr(scanner, "_ai_now_iso", lambda: FIXED_NOW)
    client = scanner.app.test_client()
    before = client.get("/api/argus/data-quality/status").get_json()
    monkeypatch.setitem(scanner._REMOTE_CYCLE, "futureNested", {
        "credential": "must-never-serialize",
    })
    monkeypatch.setitem(scanner._DURABLE_STATE, "futureNested", {
        "owner": "must-never-serialize",
    })
    after = client.get("/api/argus/data-quality/status").get_json()
    assert after == before


def test_public_diagnostic_serializers_have_no_raw_state_copy_path():
    """Targeted structural guard; deliberately not a repository-wide linter."""
    builders = "\n".join(inspect.getsource(fn) for fn in (
        diagnostics.build_public_diagnostics,
        diagnostics.build_public_liveness,
        diagnostics.build_public_readiness,
        diagnostics.public_diagnostics_fallback,
    ))
    assert "**" not in builders
    for forbidden in (
            "_REMOTE_CYCLE", "_DURABLE_STATE", "_INCIDENTS", "_OSINT_STORE",
            "_MISSIONS", "_CHECKPOINT_V2_STATUS", "ownerDecision",
            "periodicReports", "postmortems"):
        assert forbidden not in builders

    routes = "\n".join(inspect.getsource(fn) for fn in (
        scanner.healthz, scanner.readyz, scanner.api_argus_data_quality,
        scanner.api_argus_data_quality_status,
    ))
    for forbidden in (
            "_data_quality_console", "_REMOTE_CYCLE", "_DURABLE_STATE",
            "_INCIDENTS", "_OSINT_STORE", "_MISSIONS",
            "_CHECKPOINT_V2_STATUS"):
        assert forbidden not in routes
    assert "jsonify(_public_diagnostics_snapshot())" in routes


def test_builder_failures_return_fixed_content_free_fallbacks(monkeypatch):
    client = scanner.app.test_client()
    monkeypatch.setattr(
        diagnostics, "build_public_diagnostics",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("PRIVATE-SENTINEL")),
    )
    public = client.get("/api/argus/data-quality").get_json()
    _assert_public_contract(public)
    assert "PRIVATE-SENTINEL" not in json.dumps(public)

    monkeypatch.setattr(scanner, "_ARGUS_ADMIN_TOKEN", "boundary-test-admin")
    monkeypatch.setattr(
        scanner, "_operational_diagnostics_snapshot",
        lambda: (_ for _ in ()).throw(RuntimeError("PRIVATE-SENTINEL")),
    )
    operational = client.get(
        "/api/argus/admin/diagnostics/operational", headers=ADMIN_HEADER)
    assert operational.status_code == 503
    assert operational.get_json()["errorCode"] == \
        "OPERATIONAL_DIAGNOSTICS_UNAVAILABLE"
    assert "PRIVATE-SENTINEL" not in operational.get_data(as_text=True)


def test_frontend_has_no_admin_secret_or_moved_public_posts():
    web = Path("web")
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (web / "src").rglob("*")
        if path.suffix in {".ts", ".tsx", ".js", ".jsx"}
    )
    assert "ARGUS_ADMIN_TOKEN" not in source
    assert "X-ARGUS-ADMIN-TOKEN" not in source
    active_consumers = "\n".join(
        (web / path).read_text(encoding="utf-8")
        for path in (
            "src/hooks/useOsintInvestigation.ts",
            "src/lib/queueRequests.ts",
            "src/lib/vault.ts",
            "src/routes/CommandCenter.tsx",
            "src/routes/DataQualityPage.tsx",
        )
    )
    for path in scanner._AUTH_OPERATIONAL_MUTATION_ROUTES:
        assert path not in active_consumers
