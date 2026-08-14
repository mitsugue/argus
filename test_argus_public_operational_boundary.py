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
    assert len(catalog.ROUTE_CATALOG) == len(actual) == 244
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


def test_public_cache_only_consumer_manifest_is_exact_and_pinned():
    assert catalog.PUBLIC_CACHE_ONLY_VALIDATION_ERRORS == ()
    expected = {
        "/api/argus/action-labels",
        "/api/argus/ai-judgment",
        "/api/argus/calibration/v4/status",
        "/api/argus/decision-value/status",
        "/api/argus/event-backbone-status",
        "/api/argus/events-active",
        "/api/argus/integrations",
        "/api/argus/japan-watchlist",
        "/api/argus/learning-memory/status",
        "/api/argus/market-depth",
        "/api/argus/market-depth/proof",
        "/api/argus/provider-diagnostics/public",
        "/api/argus/runtime-manifest",
        "/api/argus/source-coverage",
        "/api/argus/source-registry",
        "/api/argus/system-health",
        "/api/argus/us-watchlist",
        "/api/argus/visibility-guard",
    }
    assert {row.route for row in catalog.PUBLIC_CACHE_ONLY_CONSUMERS} == expected
    for row in catalog.PUBLIC_CACHE_ONLY_CONSUMERS:
        for consumer in row.consumers:
            source = Path(consumer).read_text(encoding="utf-8")
            assert row.route in source, (row.route, consumer)

def test_public_diagnostics_canonical_route_is_bounded_and_alias_is_retired():
    client = scanner.app.test_client()
    retired = client.get("/api/argus/data-quality")
    canonical = client.get("/api/argus/data-quality/status")
    assert retired.status_code == 404
    assert canonical.status_code == 200
    _assert_public_contract(canonical.get_json())


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
    for path in ("/healthz", "/readyz", "/api/argus/data-quality/status"):
        response = client.get(path)
        assert sentinel not in response.get_data(as_text=True)


class _OutboundForbidden(BaseException):
    pass


def test_named_public_status_routes_are_cache_only_even_when_cold(monkeypatch):
    """Cold public reads must not invoke any live provider/ledger refresh path."""
    def forbidden(*_args, **_kwargs):
        raise _OutboundForbidden("public GET attempted outbound refresh")

    protected_caches = (
            scanner._PROVIDER_DIAG_CACHE, scanner._MARKET_DEPTH_CACHE, scanner._VWAP_CACHE,
            scanner._VISIBILITY_CACHE, scanner._INTEGRATIONS_CACHE,
            scanner._REGIME_CACHE, scanner._LEDGER_SUMMARY_CACHE,
            scanner._RATES_CACHE, scanner._JP_CACHE, scanner._US_CACHE,
            scanner._DOWNSIDE_CACHE, scanner._TDNET_OFFICIAL_CACHE,
            scanner._TDNET_FEED_CACHE, scanner._AI_RESULT_CACHE,
            scanner._CALIB_V4_CACHE, scanner._DV_STATUS_CACHE,
            scanner._EVENT_SNAP_META)
    for cache in protected_caches:
        monkeypatch.setitem(cache, "data", None)
        if "expires" in cache:
            monkeypatch.setitem(cache, "expires", 0.0)
    monkeypatch.setitem(scanner._LEARNING_MEMORY, "doc", None)
    monkeypatch.setitem(scanner._LEARNING_MEMORY_STATE, "pathType", "ephemeral_tmp")
    monkeypatch.setattr(scanner.requests, "get", forbidden)
    monkeypatch.setattr(scanner.requests, "post", forbidden)
    for name in (
            "get_rates_snapshot", "_ai_cached_result", "_ai_try_restore",
            "_gh_private_get", "get_downside_incidents", "get_tdnet_recent",
            "_dv_shadow_public_summary", "_ai_cost_roll", "_finnhub_quote_row",
            "_edinet_filings",
            "_jquants_tdnet_fetch", "_provider_diagnostics", "_vwap_probe",
            "get_market_regime_snapshot", "_ledger_summary",
            "_learning_memory_restore_once", "_dv_shadow_phase"):
        monkeypatch.setattr(scanner, name, forbidden)
    for name in ("_dv_shadow_public_summary", "_events_restore_once",
                 "_event_snapshot_meta"):
        monkeypatch.setattr(scanner, name, forbidden)

    client = scanner.app.test_client()
    for path in (
            "/api/argus/action-labels?jp=8058&us=NVDA",
            "/api/argus/ai-judgment",
            "/api/argus/calibration/v4/status",
            "/api/argus/decision-value/status",
            "/api/argus/event-backbone-status",
            "/api/argus/events-active",
            "/api/argus/integrations",
            "/api/argus/japan-watchlist?symbols=8058",
            "/api/argus/learning-memory/status",
            "/api/argus/market-depth",
            "/api/argus/market-depth/proof",
            "/api/argus/provider-diagnostics/public",
            "/api/argus/source-coverage",
            "/api/argus/source-registry",
            "/api/argus/system-health",
            "/api/argus/us-watchlist?symbols=NVDA",
            "/api/argus/runtime-manifest",
            "/api/argus/visibility-guard"):
        response = client.get(path)
        assert response.status_code == 200, path
        if path == "/api/argus/runtime-manifest":
            assert response.get_json()["activeRoutes"] == [
                "Today", "Holdings / Watchlist", "Notifications", "Settings"]
    assert all(cache.get("data") is None for cache in protected_caches)


def test_public_jp_watchlist_is_read_only_and_provider_cache_only(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise _OutboundForbidden("JP public GET attempted provider work")

    seen_before = copy.deepcopy(scanner._JP_SEEN_SYMBOLS)
    monkeypatch.setitem(scanner._JP_CACHE, "data", None)
    monkeypatch.setitem(scanner._JP_CACHE, "expires", 0.0)
    monkeypatch.setattr(scanner, "_JP_DYN_CACHE", {})
    monkeypatch.setattr(scanner, "_jq_fetch_bar_row", forbidden)
    monkeypatch.setattr(scanner, "_jquants_fetch_quote", forbidden)
    before_cache = copy.deepcopy(scanner._JP_DYN_CACHE)

    response = scanner.app.test_client().get(
        "/api/argus/japan-watchlist?symbols=8058")
    assert response.status_code == 200
    assert scanner._JP_DYN_CACHE == before_cache
    assert scanner._JP_SEEN_SYMBOLS == seen_before


def test_jp_bridge_dynamic_membership_remains_owner_synced_and_admin_gated(
        monkeypatch):
    monkeypatch.setattr(scanner, "_ARGUS_ADMIN_TOKEN", "boundary-test-admin")
    monkeypatch.setattr(scanner, "_JP_SEEN_SYMBOLS", {})
    monkeypatch.setattr(scanner, "_layer2b_read_latest", lambda: {
        "members": [
            {"market": "JP", "symbol": "6965"},
            {"market": "US", "symbol": "AAPL"},
        ]
    })
    client = scanner.app.test_client()

    assert client.get("/api/argus/jp-watchlist-codes").status_code == 401
    before = client.get(
        "/api/argus/jp-watchlist-codes", headers=ADMIN_HEADER)
    assert before.status_code == 200
    assert before.get_json()["codes"] == ["JP.6965"]

    public = client.get("/api/argus/japan-watchlist?symbols=8058")
    assert public.status_code == 200
    after = client.get(
        "/api/argus/jp-watchlist-codes", headers=ADMIN_HEADER)
    assert after.get_json()["codes"] == ["JP.6965"]


def test_public_action_labels_does_not_record_symbol_interest_or_refresh(
        monkeypatch):
    seen_before = copy.deepcopy(scanner._JP_SEEN_SYMBOLS)
    calls = []
    original_jp = scanner.get_japan_watchlist_snapshot
    original_us = scanner.get_us_watchlist_snapshot

    def jp(*args, **kwargs):
        calls.append(("jp", kwargs))
        return original_jp(*args, **kwargs)

    def us(*args, **kwargs):
        calls.append(("us", kwargs))
        return original_us(*args, **kwargs)

    monkeypatch.setattr(scanner, "get_japan_watchlist_snapshot", jp)
    monkeypatch.setattr(scanner, "get_us_watchlist_snapshot", us)
    response = scanner.app.test_client().get(
        "/api/argus/action-labels?jp=8058&us=NVDA")
    assert response.status_code == 200
    assert calls == [
        ("jp", {"allow_provider_fetch": False,
                "record_requested_symbols": False}),
        ("us", {"allow_provider_fetch": False}),
    ]
    assert scanner._JP_SEEN_SYMBOLS == seen_before


def test_public_us_watchlist_does_not_fill_from_provider_when_cache_is_cold(
        monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise _OutboundForbidden("public GET attempted provider fill")

    monkeypatch.setitem(scanner._US_CACHE, "data", None)
    monkeypatch.setitem(scanner._US_CACHE, "expires", 0.0)
    monkeypatch.setattr(scanner, "_US_DYN_CACHE", {})
    monkeypatch.setattr(scanner, "_finnhub_quote_row", forbidden)
    response = scanner.app.test_client().get(
        "/api/argus/us-watchlist?symbols=NVDA")
    assert response.status_code == 200
    assert scanner._US_CACHE.get("data") is None


def test_public_ai_judgment_does_not_restore_on_get(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise _OutboundForbidden("public GET attempted AI restore")

    monkeypatch.setattr(scanner, "_AI_JUDGE_ENABLED", True)
    monkeypatch.setattr(scanner, "_OPENAI_API_KEY", "configured-for-test")
    monkeypatch.setitem(scanner._AI_RESULT_CACHE, "data", None)
    monkeypatch.setitem(scanner._AI_RESULT_CACHE, "expires", 0.0)
    for name in ("_ai_cached_result", "_ai_restore_local", "_ai_try_restore"):
        monkeypatch.setattr(scanner, name, forbidden)
    response = scanner.app.test_client().get("/api/argus/ai-judgment")
    assert response.status_code == 200
    assert response.get_json()["status"] == "not_run_yet"


def test_event_and_ai_product_cache_restore_runs_once_in_process_bootstrap(
        monkeypatch):
    calls = []
    startup_before = copy.deepcopy(scanner._STARTUP)
    runtime_before = copy.deepcopy(scanner._RUNTIME)
    durable_before = copy.deepcopy(scanner._DURABLE_STATE)
    try:
        monkeypatch.setattr(scanner, "_DURABILITY_PRODUCTION", False)
        monkeypatch.setattr(scanner, "_AI_JUDGE_ENABLED", True)
        monkeypatch.setattr(scanner, "_OPENAI_API_KEY", "configured-for-test")
        monkeypatch.setattr(scanner, "_validate_durable_storage", lambda: True)
        monkeypatch.setattr(
            scanner, "_osint_restore_once", lambda: calls.append("osint"))
        monkeypatch.setattr(
            scanner, "_events_restore_once", lambda: calls.append("events"))
        monkeypatch.setattr(
            scanner, "_ai_cached_result", lambda: calls.append("ai"))
        scanner._STARTUP.update({
            "state": "bootstrapping",
            "restoreStartedAt": None,
            "restoreCompletedAt": None,
            "restoreOutcome": None,
        })
        scanner._DURABLE_STATE.update({
            "lastRestoreAt": None,
            "integrityStatus": "unknown",
        })

        scanner._startup_bootstrap()
        scanner._startup_bootstrap()
        assert calls == ["osint", "events", "ai"]
        assert scanner._STARTUP["state"] == "ready"
    finally:
        scanner._STARTUP.clear()
        scanner._STARTUP.update(startup_before)
        scanner._RUNTIME.clear()
        scanner._RUNTIME.update(runtime_before)
        scanner._DURABLE_STATE.clear()
        scanner._DURABLE_STATE.update(durable_before)


def test_expired_component_evidence_is_not_restamped_live(monkeypatch):
    old = "2026-01-01T00:00:00Z"
    monkeypatch.setitem(scanner._INTEGRATIONS_CACHE, "data", None)
    monkeypatch.setitem(scanner._INTEGRATIONS_CACHE, "expires", 0.0)
    for cache in (scanner._RATES_CACHE, scanner._JP_CACHE, scanner._US_CACHE):
        monkeypatch.setitem(cache, "data", {
            "status": "live", "asOf": old, "stocks": []})
        monkeypatch.setitem(cache, "expires", 0.0)
    snapshot = scanner.get_integrations_snapshot(allow_provider_fetch=False)
    statuses = {row["id"]: row["runtimeStatus"]
                for row in snapshot["providers"]}
    assert statuses["fred"] != "live"
    assert statuses["jquants"] != "live"
    assert statuses["twelvedata"] != "live"

    monkeypatch.setitem(scanner._INTEGRATIONS_CACHE, "data", {
        "status": "live", "asOf": old, "providers": [],
        "aiJudgment": {}, "nextRecommendedApis": []})
    monkeypatch.setitem(scanner._INTEGRATIONS_CACHE, "expires", 0.0)
    assert (scanner.get_integrations_snapshot(
        allow_provider_fetch=False)["asOf"] != old)

    monkeypatch.setitem(scanner._CALIB_V4_CACHE, "data", {
        "nPredictions": 99, "updated": old})
    monkeypatch.setitem(scanner._CALIB_V4_CACHE, "expires", 0.0)
    assert scanner._calibration_v4_summary(allow_ledger_fetch=False) is None

    monkeypatch.setitem(scanner._DV_STATUS_CACHE, "data", {
        "phase": "scoring_active", "lastShadowRunAt": old})
    monkeypatch.setitem(scanner._DV_STATUS_CACHE, "expires", 0.0)
    stale_dv = scanner._dv_status_public_dict(allow_private_fetch=False)
    assert stale_dv["phase"] != "scoring_active"
    assert stale_dv["cacheFreshness"] == "stale"

    monkeypatch.setitem(scanner._MARKET_DEPTH_CACHE, "data", {
        "asOf": old,
        "capabilities": {"L2": {"status": "live", "probed": True}},
    })
    monkeypatch.setitem(scanner._MARKET_DEPTH_CACHE, "expires", 0.0)
    assert scanner._market_depth_report(allow_provider_fetch=False) is None

    monkeypatch.setitem(scanner._VISIBILITY_CACHE, "data", {
        "asOf": old, "visibilityLevel": "FULL_SENTINEL"})
    monkeypatch.setitem(scanner._VISIBILITY_CACHE, "expires", 0.0)
    assert scanner._visibility_guard(
        allow_provider_fetch=False).get("visibilityLevel") != "FULL_SENTINEL"

    monkeypatch.setitem(scanner._PROVIDER_DIAG_CACHE, "data", {
        "asOf": old,
        "items": [{"provider": "sentinel", "configured": True,
                   "runtimeStatus": "live"}],
    })
    monkeypatch.setitem(scanner._PROVIDER_DIAG_CACHE, "expires", 0.0)
    stale = scanner._provider_diagnostics_cached_only()
    assert stale["asOf"] == old
    assert stale["items"][0]["runtimeStatus"] == "stale"


def test_expired_status_and_evidence_components_fail_conservatively(monkeypatch):
    old = "2000-01-01T00:00:00Z"
    monkeypatch.setattr(scanner, "_JQUANTS_API_KEY", "configured-for-test")
    monkeypatch.setitem(scanner._TDNET_OFFICIAL_CACHE, "data", {
        "status": "official_tdnet_live", "official": True,
        "asOf": old, "items": [{"id": "stale-tdnet"}]})
    monkeypatch.setitem(scanner._TDNET_OFFICIAL_CACHE, "expires", 0.0)
    monkeypatch.setitem(scanner._TDNET_FEED_CACHE, "data", None)
    monkeypatch.setitem(scanner._TDNET_FEED_CACHE, "expires", 0.0)
    monkeypatch.setitem(scanner._DOWNSIDE_CACHE, "data", {
        "asOf": old, "activeCount": 77})
    monkeypatch.setitem(scanner._DOWNSIDE_CACHE, "expires", 0.0)
    monkeypatch.setitem(scanner._LEDGER_SUMMARY_CACHE, "data", {
        "overall": {"days": 999, "n": 999}})
    monkeypatch.setitem(scanner._LEDGER_SUMMARY_CACHE, "expires", 0.0)
    monkeypatch.setitem(scanner._CALIB_V4_CACHE, "data", {
        "nPredictions": 99, "updated": old})
    monkeypatch.setitem(scanner._CALIB_V4_CACHE, "expires", 0.0)

    client = scanner.app.test_client()
    calibration = client.get("/api/argus/calibration/v4/status").get_json()
    assert calibration["artifactFound"] is False
    assert calibration["v3HeadlineDays"] == 0
    runtime = client.get("/api/argus/runtime-manifest").get_json()
    assert runtime["downside"]["activeIncidents"] == 0
    assert runtime["tdnet"]["count"] == 0
    registry = scanner._source_registry(allow_provider_fetch=False)
    tdnet = next(row for row in registry["sources"]
                 if row["capability"] == "企業開示(TDnet 公式)")
    assert tdnet["status"] != "confirmed_live"

    monkeypatch.setitem(scanner._PUSHED_QUOTES, "US", {
        "ZZZZ": {"ts": 0.0, "row": {
            "symbol": "ZZZZ", "price": 999, "date": old,
            "status": "live"}}})
    monkeypatch.setattr(scanner, "_US_DYN_CACHE", {})
    monkeypatch.setitem(scanner._US_CACHE, "data", None)
    monkeypatch.setitem(scanner._US_CACHE, "expires", 0.0)
    monkeypatch.setitem(scanner._VISIBILITY_CACHE, "data", {
        "asOf": old, "visibilityLevel": "FULL_SENTINEL"})
    monkeypatch.setitem(scanner._VISIBILITY_CACHE, "expires", 0.0)
    monkeypatch.setitem(scanner._MARKET_DEPTH_CACHE, "data", {
        "asOf": old,
        "capabilities": {"L2": {"status": "live", "probed": True}}})
    monkeypatch.setitem(scanner._MARKET_DEPTH_CACHE, "expires", 0.0)
    monkeypatch.setitem(scanner._DV_STATUS_CACHE, "data", {
        "phase": "scoring_active", "lastShadowRunAt": old})
    monkeypatch.setitem(scanner._DV_STATUS_CACHE, "expires", 0.0)
    pack = scanner._build_evidence_pack("ZZZZ", "US")
    serialized = json.dumps(pack, ensure_ascii=False)
    assert "FULL_SENTINEL" not in serialized
    assert '"price": 999' not in serialized
    markers = set(pack["missingConfirmations"])
    assert "cache:quote" in markers
    assert "cache:visibility_guard" in markers
    assert "cache:market_depth" in markers
    assert "cache:calibration:stale" in markers
    assert "cache:calibration-ledger:stale" in markers
    assert "cache:decision-value:stale" in markers


def test_learning_memory_cache_only_change_is_status_scoped(monkeypatch):
    restore_calls = []
    monkeypatch.setitem(scanner._LEARNING_MEMORY, "doc", None)
    monkeypatch.setattr(
        scanner, "_learning_memory_restore_once",
        lambda: restore_calls.append("restore"))
    client = scanner.app.test_client()
    assert client.get("/api/argus/learning-memory/status").status_code == 200
    assert restore_calls == []
    assert client.get("/api/argus/learning-memory").status_code == 200
    assert restore_calls == ["restore"]


def test_authenticated_and_internal_refresh_paths_remain_live_capable(monkeypatch):
    provider_calls = []
    monkeypatch.setattr(scanner, "_ARGUS_ADMIN_TOKEN", "boundary-test-admin")
    monkeypatch.setattr(
        scanner, "_provider_diagnostics",
        lambda: provider_calls.append("admin") or {
            "schemaVersion": "provider-diagnostics-v1", "items": []})
    response = scanner.app.test_client().get(
        "/api/argus/admin/provider-diagnostics", headers=ADMIN_HEADER)
    assert response.status_code == 200
    assert provider_calls == ["admin"]

    integration_calls = []
    monkeypatch.setitem(scanner._INTEGRATIONS_CACHE, "data", None)
    monkeypatch.setitem(scanner._INTEGRATIONS_CACHE, "expires", 0.0)
    monkeypatch.setattr(
        scanner, "get_rates_snapshot",
        lambda: integration_calls.append("rates") or {"status": "live"})
    monkeypatch.setattr(
        scanner, "get_japan_watchlist_snapshot",
        lambda: integration_calls.append("jp") or {"status": "live"})
    monkeypatch.setattr(
        scanner, "get_us_watchlist_snapshot",
        lambda: integration_calls.append("us") or {"status": "live"})
    scanner.get_integrations_snapshot()
    assert integration_calls == ["rates", "jp", "us"]

    refresh_calls = []
    monkeypatch.setitem(scanner._MARKET_DEPTH_CACHE, "data", None)
    monkeypatch.setitem(scanner._MARKET_DEPTH_CACHE, "expires", 0.0)
    monkeypatch.setattr(
        scanner, "_source_registry",
        lambda *, allow_provider_fetch=True: refresh_calls.append(
            ("source", allow_provider_fetch)) or {"sources": []})
    monkeypatch.setattr(
        scanner, "_vwap_probe",
        lambda: refresh_calls.append(("vwap", True)) or {
            "computed": False, "probed": True, "values": {}})
    assert scanner._market_depth_report() is not None
    assert ("source", True) in refresh_calls
    assert ("vwap", True) in refresh_calls


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
        scanner.healthz, scanner.readyz, scanner.api_argus_data_quality_status,
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
    public = client.get("/api/argus/data-quality/status").get_json()
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
