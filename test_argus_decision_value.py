"""Tests for Decision Value Ledger v1 Phase 1 (argus_decision_value.py).

Safety + math. RESEARCH SIMULATION ONLY — these also assert no execution surface.
"""
import argus_decision_value as DV


# ── safety ───────────────────────────────────────────────────────────────────
def test_no_execution_surface():
    names = dir(DV)
    for bad in ("execute", "place_order", "submit_order", "buy", "sell", "broker"):
        assert not any(bad in n.lower() for n in names), f"forbidden symbol: {bad}"


def test_disclaimer_present_in_outputs():
    e = DV.expectancy([0.5, -0.3, 1.0, -0.2, 0.4])
    assert DV.DISCLAIMER in (e.get("disclaimer") or "")


# ── costs ────────────────────────────────────────────────────────────────────
def test_costs_observed_vs_fallback():
    obs = DV.estimate_costs(notional=1e6, market="JP", spread_bps_observed=4.0)
    assert obs["spreadQuality"] == "observed" and obs["spreadBps"] == 4.0
    fb = DV.estimate_costs(notional=1e6, market="JP", liquidity_bucket="low")
    assert fb["spreadQuality"] == "conservative_fallback" and fb["spreadBps"] == 25.0


def test_total_cost_sums_components():
    c = DV.estimate_costs(notional=1e6, market="US", spread_bps_observed=2.0,
                          slippage_bps=1.0, commission_bps=0.5, fx_bps=10.0)
    assert abs(c["totalCostBps"] - 13.5) < 1e-9
    assert abs(c["totalCostAbs"] - 1e6 * 13.5 / 1e4) < 1e-6


# ── gross vs net (no double counting) ────────────────────────────────────────
def test_gross_vs_net_separate():
    g = DV.gross_return_pct(100, 105, "long")
    assert g == 5.0
    net = DV.net_return_pct(g, total_cost_bps=50)  # 50bps = 0.5%
    assert abs(net - 4.5) < 1e-9


def test_short_direction():
    assert DV.gross_return_pct(100, 95, "short") == 5.0


# ── R multiple ───────────────────────────────────────────────────────────────
def test_r_multiple_basic():
    r = DV.r_multiple(entry=100, exit_=110, invalidation=95, direction="long")
    assert r["plannedRiskPerUnit"] == 5.0
    assert r["grossR"] == 2.0   # +10 / 5


def test_r_null_without_invalidation():
    r = DV.r_multiple(entry=100, exit_=110, invalidation=None)
    assert r["grossR"] is None and r["reason"] == "no_entry_or_invalidation"


def test_r_net_below_gross_with_costs():
    r = DV.r_multiple(entry=100, exit_=110, invalidation=95, total_cost_bps=100)
    assert r["netR"] < r["grossR"]


# ── expectancy ───────────────────────────────────────────────────────────────
def test_expectancy_metrics():
    e = DV.expectancy([1.0, 1.0, -0.5, -0.5, 2.0])
    assert e["n"] == 5
    assert e["winRate"] == 0.6 and e["lossRate"] == 0.4
    assert e["averageWinR"] > 0 and e["averageLossR"] == 0.5
    assert e["netExpectancyR"] == round((1+1-0.5-0.5+2)/5, 4)
    assert e["profitFactor"] == round(4.0/1.0, 4)


def test_expectancy_small_sample_warning():
    e = DV.expectancy([0.5, -0.2])
    assert e["warning"] == "insufficient_sample" and e["sampleStage"] == "burn_in"


def test_expectancy_empty():
    assert DV.expectancy([])["status"] == "insufficient_sample"


def test_sample_stage_never_proven():
    assert DV._sample_stage(200) == "validation"  # not "proven"


# ── no-trade value (separate from P&L) ───────────────────────────────────────
def test_no_trade_value():
    obs = [{"mae_pct": -8.0, "mfe_pct": 1.0}, {"mae_pct": -1.0, "mfe_pct": 7.0},
           {"mae_pct": -2.0, "mfe_pct": 0.5}]
    nt = DV.no_trade_value(obs)
    assert nt["n"] == 3
    assert nt["severeLossAvoidanceRate"] == round(1/3, 4)   # one ≥5% MAE avoided
    assert nt["missedLargeGainRate"] == round(1/3, 4)       # one ≥5% MFE missed
    assert "opportunity cost" in nt["note"].lower()


# ── risk of ruin (deterministic with seed) ───────────────────────────────────
def test_risk_of_ruin_deterministic():
    rs = [1.0, -1.0, 0.8, -0.6, 1.2, -1.0, 0.5, -0.4, 2.0, -1.0, 0.3, -0.5]
    a = DV.risk_of_ruin(rs, trials=300, seed=42)
    b = DV.risk_of_ruin(rs, trials=300, seed=42)
    assert a["probExceedDrawdown"] == b["probExceedDrawdown"]  # reproducible
    assert a["status"] == "ok"
    assert "20%" in a["probExceedDrawdown"]


def test_risk_of_ruin_insufficient():
    assert DV.risk_of_ruin([0.1, -0.1])["status"] == "insufficient_sample"


def test_loss_recovery():
    assert DV.loss_recovery_pct(0.5) == 1.0      # 50% loss → 100% gain
    assert DV.loss_recovery_pct(0.2) == 0.25     # 20% → 25%


# ── kelly (disabled by default) ──────────────────────────────────────────────
def test_kelly_disabled_small_sample():
    e = DV.expectancy([1.0, -0.5, 1.0])
    assert DV.kelly_research(e)["kellyStatus"] == "disabled_insufficient_sample"


def test_kelly_negative_edge():
    e = {"n": 100, "netExpectancyR": -0.1, "payoffRatio": 1.0, "winRate": 0.4}
    assert DV.kelly_research(e)["kellyStatus"] == "negative_edge"


def test_kelly_requires_positive_lower_bound():
    e = {"n": 100, "netExpectancyR": 0.2, "payoffRatio": 2.0, "winRate": 0.5}
    assert DV.kelly_research(e)["kellyStatus"].startswith("unstable")
    ok = DV.kelly_research(e, lower_conf_bound_positive=True)
    assert ok["kellyStatus"] == "research_only" and ok["actionable"] is False
    assert ok["cappedResearchFraction"] <= 0.25  # capped


def test_kelly_never_actionable():
    e = {"n": 200, "netExpectancyR": 0.5, "payoffRatio": 3.0, "winRate": 0.6}
    assert DV.kelly_research(e, lower_conf_bound_positive=True)["actionable"] is False


# ── policy registry (Phase 2) ────────────────────────────────────────────────
def test_policy_registry_has_templates_and_baselines():
    reg = DV.list_policies()
    for p in ("daily_next_session_long_v1", "close_pin_long_v1",
              "event_next_open_long_v1", "no_trade_control_v1"):
        assert p in reg["policies"]
    assert "buy_and_hold" in reg["baselines"] and "no_trade" in reg["baselines"]


def test_policy_long_only_no_execution_words():
    for pid, p in DV.POLICIES.items():
        assert p["direction"] in ("long", "none")
        # entry rules describe research fills, never live execution verbs
        assert "broker" not in str(p).lower()


def test_no_hindsight_timing_guard():
    assert DV.validate_policy_timing(decision_ts=100, entry_ts=200, outcome_ts=300)["ok"] is True
    # entry before decision = hindsight
    assert DV.validate_policy_timing(decision_ts=200, entry_ts=100, outcome_ts=300)["ok"] is False
    # outcome at/before entry = hindsight
    bad = DV.validate_policy_timing(decision_ts=100, entry_ts=200, outcome_ts=150)
    assert bad["ok"] is False and "hindsight" in bad["reason"]


def test_build_shadow_decision_eligible_and_rejected():
    d = DV.build_shadow_decision(policy_id="daily_next_session_long_v1", symbol="7203",
                                 market="JP", decision_price=3900, decision_ts=1000)
    assert d["kind"] == "shadow_candidate" and d["fillStatus"] == "pending"
    assert d["policyRegistryVersion"] == DV.POLICY_REGISTRY_VERSION
    r = DV.build_shadow_decision(policy_id="daily_next_session_long_v1", symbol="7203",
                                 market="JP", decision_price=3900, decision_ts=1000,
                                 eligible=False, rejection_reason="stale_quote")
    assert r["kind"] == "shadow_no_trade" and r["eligibilityResult"] == "rejected"


def test_build_shadow_decision_unknown_policy():
    assert DV.build_shadow_decision(policy_id="nope", symbol="X", market="US",
                                    decision_price=1, decision_ts=1)["ok"] is False
