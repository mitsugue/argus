"""ARGUS Pro — auditable status endpoints (Phases 4, 5, 8).

Calibration v4 / Decision Value / Market Depth Proof must be honestly inactive
when there is nothing to show, must never overclaim ("proven"/"full depth"), and
must never leak owner-private data (netR, prices, holdings).
"""
import json
import scanner


# ── Phase 5: Decision Value status ───────────────────────────────────────────
def test_decision_value_record_carries_visibility_context():
    import argus_decision_value as DV
    r = DV.build_shadow_decision(
        policy_id="daily_next_session_long_v1", symbol="NVDA", market="US",
        decision_price=195.0, decision_ts="2026-07-01T05:00:00Z", eligible=True,
        posture_before="ENTER", posture_after="WAIT",
        confidence_before=0.7, confidence_after=0.55,
        blocked_actions=["ENTER"], visibility_downgraded=True)
    assert r["postureBefore"] == "ENTER" and r["postureAfter"] == "WAIT"
    assert r["confidenceBefore"] == 0.7 and r["confidenceAfter"] == 0.55
    assert r["blockedActions"] == ["ENTER"] and r["visibilityDowngraded"] is True
    assert r["realizedOutcomeStatus"] == "pending"
    # a shadow record must never carry realized P&L
    assert "netR" not in r and "realizedPnl" not in r
    assert "No order" in r["disclaimer"]


# ── Phase 4: Calibration v4 status ───────────────────────────────────────────
# ── Phase 8: Market Depth proof ──────────────────────────────────────────────
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
