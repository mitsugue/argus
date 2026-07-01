"""ARGUS Pro — auditable status endpoints (Phases 4, 5, 8).

Calibration v4 / Decision Value / Market Depth Proof must be honestly inactive
when there is nothing to show, must never overclaim ("proven"/"full depth"), and
must never leak owner-private data (netR, prices, holdings).
"""
import json
import scanner


# ── Phase 5: Decision Value status ───────────────────────────────────────────
def test_decision_value_status_shape_and_disclaimer():
    with scanner.app.test_client() as c:
        d = c.get("/api/argus/decision-value/status").get_json()
    assert d["schemaVersion"] == "decision-value-v1"
    assert d["phase"] in ("not_configured", "engine_ready_no_records_yet",
                          "shadow_recording_active", "scoring_active")
    assert "No order" in d["disclaimer"]


def test_decision_value_status_never_leaks_private_pnl():
    with scanner.app.test_client() as c:
        blob = json.dumps(c.get("/api/argus/decision-value/status").get_json()).lower()
    for leak in ("netr", "grossreturn", "costbasis", "pnl", "realizedpnl", "holdings", "quantity"):
        assert leak not in blob, leak


def test_decision_value_phase_honest_when_unconfigured(monkeypatch):
    monkeypatch.setattr(scanner, "_layer2b_store_configured", lambda: False)
    with scanner.app.test_client() as c:
        d = c.get("/api/argus/decision-value/status").get_json()
    assert d["phase"] == "not_configured"
    assert d["privateStoreConfigured"] is False
    assert d["reasonJa"]


# ── Phase 4: Calibration v4 status ───────────────────────────────────────────
def test_calibration_v4_status_shape():
    with scanner.app.test_client() as c:
        d = c.get("/api/argus/calibration/v4/status").get_json()
    assert d["schemaVersion"] == "calibration-v4"
    assert d["reliabilityStage"] in ("burn_in", "early_signal", "provisional", "regime_level")
    assert isinstance(d["isActive"], bool)
    # never claim the English word "proven" anywhere
    assert "proven" not in json.dumps(d).lower()


def test_calibration_v4_inactive_when_no_artifact(monkeypatch):
    monkeypatch.setattr(scanner, "_calibration_v4_summary", lambda: None)
    with scanner.app.test_client() as c:
        d = c.get("/api/argus/calibration/v4/status").get_json()
    assert d["artifactFound"] is False
    assert d["isActive"] is False
    assert d["reasonJa"]


def test_calibration_v4_inactive_when_empty_artifact(monkeypatch):
    monkeypatch.setattr(scanner, "_calibration_v4_summary", lambda: {})
    with scanner.app.test_client() as c:
        d = c.get("/api/argus/calibration/v4/status").get_json()
    assert d["isActive"] is False


def test_calibration_v4_active_requires_records(monkeypatch):
    monkeypatch.setattr(scanner, "_calibration_v4_summary",
                        lambda: {"nPredictions": 12, "nScored": 0, "updated": "2026-07-01T00:00:00Z"})
    with scanner.app.test_client() as c:
        d = c.get("/api/argus/calibration/v4/status").get_json()
    assert d["artifactFound"] is True and d["isActive"] is True and d["nPredictions"] == 12


# ── Phase 8: Market Depth proof ──────────────────────────────────────────────
def test_market_depth_proof_shape():
    with scanner.app.test_client() as c:
        d = c.get("/api/argus/market-depth/proof").get_json()
    assert d["schemaVersion"] == "market-depth-proof-v1"
    assert set(d["summary"]) >= {"trueDepthLiveCount", "computedIndicatorsLiveCount",
                                 "requiresContractCount", "unavailableCount"}


def test_market_depth_proof_downgrades_unprobed_live():
    caps = {
        "VWAP": {"status": "live", "probed": True, "sample": 40, "affectsActionLevel": True},
        "JP_CASH": {"status": "live", "probed": False, "sample": None, "affectsActionLevel": True},
        "L2": {"status": "unavailable", "probed": False},
        "TAPE": {"status": "requires_contract", "probed": False},
    }
    items = {i["capability"]: i for i in scanner._market_depth_proof_items(caps)}
    assert items["VWAP"]["status"] == "live" and items["VWAP"]["proofType"] == "computed_from_bars"
    # live but not probed → honest downgrade, cadence is not proof
    assert items["JP_CASH"]["status"] == "unverified_live"
    assert items["L2"]["status"] == "unavailable" and items["L2"]["isTrueDepth"] is True
    assert items["TAPE"]["status"] == "requires_contract"


def test_market_depth_proof_true_depth_stays_unavailable():
    # L2/TAPE/OPTIONS_IV/BORROW_FEE must never be 'live' without a real feed.
    caps = {k: {"status": "unavailable", "probed": False} for k in
            ("L2", "TAPE", "OPTIONS_IV", "BORROW_FEE")}
    items = scanner._market_depth_proof_items(caps)
    assert all(i["status"] in ("unavailable", "requires_contract") for i in items)
    assert all(i["isTrueDepth"] for i in items)
