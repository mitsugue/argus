"""V13.6.0 decision-evidence route — canonical artifact references for the
device-side SDA.

Contract under test (owner spec 2026-08-22):
  * a FRESH live quote yields AVAILABLE marketTruth + predictionLedger + sho
    references with quality COMPLETE/FRESH — the reviewed backend half of the
    frontend's canonical_artifact_resolver_unavailable boundary;
  * a merely DELAYED/stale selection degrades to an honest STALE reference
    (identity kept, authority withheld) — never a fabricated AVAILABLE;
  * absent inputs fail closed to MISSING with reasons, HTTP 200, no network;
  * SHO stays UNVALIDATED / shoBuyEligible False (BUY remains locked).
"""
from datetime import datetime, timedelta, timezone

import scanner
import argus_single_decision


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _fresh_jp_row(now):
    return {
        "symbol": "1321", "name": "日経225連動型上場投資信託",
        "status": "live", "price": 68330.0, "changePct": -1.2,
        "volume": 123456.0,
        "receivedAt": _iso(now - timedelta(seconds=30)),
        "sourceTimestamp": _iso(now - timedelta(seconds=60)),
        "source": "jquants",
    }


def _client():
    scanner._DECISION_EVIDENCE_CACHE.clear()
    return scanner.app.test_client()


def test_fresh_live_quote_yields_full_available_chain(monkeypatch):
    now = datetime.now(timezone.utc)
    monkeypatch.setenv("RENDER_GIT_COMMIT", "a" * 40)
    monkeypatch.setattr(scanner, "get_japan_watchlist_snapshot",
                        lambda: {"provider": "jquants",
                                 "stocks": [_fresh_jp_row(now)]})
    body = _client().get(
        "/api/argus/decision-evidence?symbols=1321").get_json()
    entry = body["subjects"]["1321"]
    assert entry["marketTruth"]["status"] == "AVAILABLE"
    assert entry["predictionLedger"]["status"] == "AVAILABLE"
    assert entry["predictionLedger"]["mode"] == "FORWARD_LIVE"
    assert entry["sho"]["status"] == "AVAILABLE"
    # BUY stays locked: nothing here may claim a validated SHO state.
    assert entry["sho"]["validationStatus"] in ("UNVALIDATED", "DATA_GATED")
    assert entry["shoBuyEligible"] is False
    assert entry["quality"] == {"status": "COMPLETE", "freshness": "FRESH",
                                "missingReasonCodes": [],
                                "conflictReasonCodes": []}
    # The references must be byte-reproducible by the canonical wrapper —
    # AVAILABLE identity fields are complete.
    for key in ("schemaVersion", "snapshotId", "observationId",
                "observedAt", "knownAt", "policyId", "policySha256"):
        assert entry["marketTruth"][key], key
    assert body["sdaAuthority"] is False
    assert body["actionAuthority"] is False


def test_delayed_close_degrades_to_stale_reference_not_available(monkeypatch):
    now = datetime.now(timezone.utc)
    row = dict(_fresh_jp_row(now), status="delayed",
               sourceTimestamp=_iso(now - timedelta(hours=20)))
    monkeypatch.setenv("RENDER_GIT_COMMIT", "a" * 40)
    monkeypatch.setattr(scanner, "get_japan_watchlist_snapshot",
                        lambda: {"provider": "jquants", "stocks": [row]})
    body = _client().get(
        "/api/argus/decision-evidence?symbols=1321").get_json()
    entry = body["subjects"]["1321"]
    assert entry["marketTruth"]["status"] == "STALE"
    # identity survives, authority does not
    assert entry["marketTruth"]["snapshotId"]
    assert entry["predictionLedger"]["status"] == "MISSING"
    assert entry["quality"]["status"] == "PARTIAL"
    assert entry["quality"]["freshness"] == "STALE"
    assert "market_truth_stale" in entry["quality"]["missingReasonCodes"]
    assert entry["verificationFailures"]["marketTruth"] == \
        "subject_selection_not_fresh"


def test_absent_inputs_fail_closed_to_missing_http_200(monkeypatch):
    monkeypatch.setenv("RENDER_GIT_COMMIT", "a" * 40)
    monkeypatch.setattr(scanner, "get_japan_watchlist_snapshot",
                        lambda: {"provider": "jquants", "stocks": []})
    response = _client().get("/api/argus/decision-evidence?symbols=1321")
    assert response.status_code == 200
    entry = response.get_json()["subjects"]["1321"]
    assert entry["marketTruth"]["status"] == "MISSING"
    assert entry["marketTruth"]["snapshotId"] is None
    assert entry["verificationFailures"]["marketTruth"] == \
        "quote_row_unavailable"
    assert entry["quality"]["status"] in ("PARTIAL", "MISSING")


def test_references_match_python_authority_resolver(monkeypatch):
    """The published references must be exactly what verify_decision_evidence
    accepts — same builders, same seals, no drift."""
    now = datetime.now(timezone.utc)
    monkeypatch.setenv("RENDER_GIT_COMMIT", "a" * 40)
    monkeypatch.setattr(scanner, "get_japan_watchlist_snapshot",
                        lambda: {"provider": "jquants",
                                 "stocks": [_fresh_jp_row(now)]})
    scanner._DECISION_EVIDENCE_CACHE.clear()
    cutoff = scanner._ai_now_iso()
    build_identity = "a" * 40
    artifact, reason = scanner._decision_evidence_market_artifact(
        "1321", "JP", cutoff, build_identity)
    assert artifact is not None and reason is None
    prediction, p_reason = scanner._decision_evidence_prediction_artifact(
        "1321", "JP", cutoff, artifact, build_identity)
    assert prediction is not None and p_reason is None
    sho_artifact, s_reason = scanner._decision_evidence_sho_artifact(
        "1321", cutoff)
    assert sho_artifact is not None and s_reason is None
    references = argus_single_decision.canonical_artifact_references(
        subject={"kind": "ASSET", "instrumentId": "1321", "market": "JP"},
        cutoff=cutoff,
        market_truth_artifact=artifact,
        prediction_ledger_artifact=prediction,
        sho_artifact=sho_artifact)
    assert references["marketTruth"]["status"] == "AVAILABLE"
    assert references["predictionLedger"]["contextId"] == prediction["id"]
    assert references["sho"]["artifactId"] == sho_artifact["artifactId"]
    assert references["verificationFailures"] == {}
