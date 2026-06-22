"""Tests for Calibration Ledger v4 foundation (argus_calibration.py).

Pure-logic tests — no network, no ledger branch, no side effects.
"""
import math

import argus_calibration as C


# ── cohorts ─────────────────────────────────────────────────────────────────
def test_regime_sensors_cohort():
    for s in ("1306", "SPY", "BTC", "USDJPY", "VIX", "8058"):
        assert C.classify_cohort(s) == C.COHORT_REGIME_SENSOR


def test_tactical_benchmark_cohort():
    for s in ("9984", "5801", "NVDA", "AAPL", "META"):
        assert C.classify_cohort(s) == C.COHORT_TACTICAL_FIXED


def test_6584_is_experimental_not_layer3():
    # the whole point: 6584 is no longer a hardcoded "Layer 3" — it's an
    # experimental-cohort member carrying flags.
    assert C.classify_cohort("6584") == C.COHORT_EXPERIMENTAL
    flags = {f["flag"] for f in C.experimental_flags("6584")}
    assert "small_cap" in flags and "high_volatility" in flags


def test_unknown_symbol_defaults_experimental():
    assert C.classify_cohort("ZZZZ") == C.COHORT_EXPERIMENTAL


def test_experimental_flags_data_driven_and_no_fabrication():
    # nothing supplied → only manual seeds (here: none for a fresh symbol)
    assert C.experimental_flags("7777") == []
    # data-driven high_volatility only fires with evidence
    fl = C.experimental_flags("7777", realized_vol_pct=5.0, vol_segment_p80=3.0)
    assert any(f["flag"] == "high_volatility" and f["flagSource"] == "automatic" for f in fl)
    # low turnover → low_liquidity
    fl = C.experimental_flags("7777", turnover_yen=1e6, turnover_floor_yen=1e7)
    assert any(f["flag"] == "low_liquidity" for f in fl)


def test_experimental_flags_dedup_manual_and_auto():
    fl = C.experimental_flags("6584", realized_vol_pct=9.0, vol_segment_p80=3.0)
    names = [f["flag"] for f in fl]
    assert names.count("high_volatility") == 1  # not duplicated


# ── factor groups ────────────────────────────────────────────────────────────
def test_factor_group_mapping():
    assert C.factor_group_of("SPY") == "us_broad_growth_semis"
    assert C.factor_group_of("TLT") == "duration_credit"
    assert C.factor_group_of("VIX") == "volatility"
    assert C.factor_group_of("NVDA") is None  # not a sensor


def test_factor_group_aggregate_equal_group_weight():
    # 3 US-equity sensors all 0.0, one safe-haven 1.0 → group weighting must NOT
    # let the 3 correlated US names dominate.
    scores = {"SPY": 0.0, "QQQ": 0.0, "SMH": 0.0, "GLD": 1.0}
    agg = C.factor_group_aggregate(scores)
    assert agg["factorGroupScores"]["us_broad_growth_semis"] == 0.0
    assert agg["factorGroupScores"]["safe_haven"] == 1.0
    # equal group weight → (0.0 + 1.0)/2 = 0.5, NOT (0+0+0+1)/4 = 0.25
    assert agg["overallEqualGroupWeighted"] == 0.5


# ── volatility bands (no lookahead, sqrt-h) ──────────────────────────────────
def test_realized_vol_insufficient_history():
    assert C.realized_vol_pct([100.0, 101.0]) is None


def test_realized_vol_basic():
    v = C.realized_vol_pct([100, 101, 100, 101, 100, 101])
    assert v is not None and v > 0


def test_band_sqrt_horizon_scaling():
    closes = [100, 102, 99, 101, 103, 98, 100, 102, 101, 99,
              100, 101, 102, 100, 99, 101, 100, 102, 98, 101, 100]
    b1 = C.volatility_band("9984", closes, horizon_days=1)
    b4 = C.volatility_band("9984", closes, horizon_days=4)
    assert b1["fallbackUsed"] is False
    # sqrt(4)=2 → 4-day band ≈ 2× 1-day band (unless clamped); allow clamp
    assert b4["bandPctUsed"] >= b1["bandPctUsed"]


def test_band_fallback_when_no_history():
    b = C.volatility_band("9984", [100.0], horizon_days=1)
    assert b["fallbackUsed"] is True and b["fallbackReason"] == "insufficient_history"
    assert b["bandPctUsed"] > 0  # clamp midpoint, never zero


def test_band_clamped_to_asset_class():
    # extreme vol → clamped to equity max 6.0
    closes = [100, 200, 50, 300, 25, 400, 10, 500, 100, 300, 50]
    b = C.volatility_band("9984", closes, horizon_days=5)
    assert b["bandPctUsed"] <= 6.0


def test_classify_realized():
    assert C.classify_realized(-3.0, 2.0) == "downside_continuation"
    assert C.classify_realized(3.0, 2.0) == "rebound_attempt"
    assert C.classify_realized(1.0, 2.0) == "sideways_stabilization"


# ── scoring ──────────────────────────────────────────────────────────────────
PERFECT = {"downside_continuation": 0, "sideways_stabilization": 0, "rebound_attempt": 1}
WRONG = {"downside_continuation": 1, "sideways_stabilization": 0, "rebound_attempt": 0}


def test_brier_perfect_and_wrong():
    assert C.brier_multiclass(PERFECT, "rebound_attempt")["brierRawSum"] == 0.0
    # wrong-confident: predicted downside, realized rebound → raw = 1+0+1 = 2
    assert C.brier_multiclass(WRONG, "rebound_attempt")["brierRawSum"] == 2.0


def test_rps_orders_matter():
    # predicting adjacent class should score better than the far class
    near = {"downside_continuation": 0, "sideways_stabilization": 1, "rebound_attempt": 0}
    far = {"downside_continuation": 1, "sideways_stabilization": 0, "rebound_attempt": 0}
    realized = "rebound_attempt"
    assert C.rps(near, realized)["rpsRaw"] < C.rps(far, realized)["rpsRaw"]


def test_rps_perfect_zero():
    assert C.rps(PERFECT, "rebound_attempt")["rpsRaw"] == 0.0


def test_argmax_and_directional():
    assert C.argmax_hit(PERFECT, "rebound_attempt") is True
    assert C.argmax_hit(WRONG, "rebound_attempt") is False
    assert C.directional_hit(PERFECT, "rebound_attempt") is True
    flat = {"downside_continuation": 0, "sideways_stabilization": 1, "rebound_attempt": 0}
    assert C.directional_hit(flat, "rebound_attempt") is None  # no directional call


def test_skill_score():
    assert C.skill_score(0.5, 1.0) == 0.5     # model half the baseline error
    assert C.skill_score(1.0, 1.0) == 0.0     # no skill
    assert C.skill_score(0.5, 0.0) is None    # undefined baseline


def test_dist_normalization_handles_unnormalized_and_empty():
    d = C._as_dist({"downside_continuation": 2, "sideways_stabilization": 2, "rebound_attempt": 0})
    assert abs(sum(d) - 1.0) < 1e-9
    d0 = C._as_dist({})
    assert abs(sum(d0) - 1.0) < 1e-9 and d0[0] == 1 / 3


# ── baselines (no leakage) ───────────────────────────────────────────────────
def test_baseline_naive_sideways():
    assert C.baseline_naive_sideways()["sideways_stabilization"] == 1.0


def test_baseline_climatology_uses_priors_only():
    prior = ["downside_continuation", "downside_continuation", "rebound_attempt"]
    out = C.baseline_climatology(prior)
    assert out["sampleCount"] == 3
    assert abs(out["dist"]["downside_continuation"] - 2 / 3) < 1e-9
    empty = C.baseline_climatology([])
    assert empty["fallback"] == "no_history"


def test_baseline_prev_day_momentum():
    up = C.baseline_prev_day_momentum(5.0, 2.0)
    assert up["rebound_attempt"] > up["downside_continuation"]
    none = C.baseline_prev_day_momentum(None, 2.0)
    assert abs(sum(none.values()) - 1.0) < 1e-9


# ── epochs + readiness ───────────────────────────────────────────────────────
def test_burn_in_epoch_excluded_from_headline():
    rec = C.burn_in_epoch_record(("2026-06-11", "2026-06-22"), 133)
    assert rec["includeInHeadlineMetrics"] is False
    assert rec["recordCount"] == 133
    assert rec["epochId"] == "burn_in_legacy_v3"


def test_reliability_stage_never_proven():
    assert C.reliability_stage(10) == "burn_in"
    assert C.reliability_stage(45) == "early_signal"
    assert C.reliability_stage(90) == "provisional"
    assert C.reliability_stage(200) == "regime_level"


def test_readiness_gate_strict_essentials_tolerant_of_one_provider():
    # 15/16 coverage (one optional provider down forever) still passes coverage
    ok = C.readiness_check(
        required_sensor_coverage=1.0, layer1_session_coverage=15 / 16,
        rolling_per_sensor_coverage=0.95, unresolved_write_failures=0,
        stale_price_forecasts=0, cohorts_finalized=True, scoring_tests_pass=True,
    )
    assert ok["ready"] is True
    # a stale-price forecast must block activation
    bad = C.readiness_check(
        required_sensor_coverage=1.0, layer1_session_coverage=1.0,
        rolling_per_sensor_coverage=1.0, unresolved_write_failures=0,
        stale_price_forecasts=3, cohorts_finalized=True, scoring_tests_pass=True,
    )
    assert bad["ready"] is False and bad["checks"]["no_stale_price_forecasts"] is False


def test_no_cohort_metric_mixing_helpers_exist():
    # the four cohorts must be distinct constants (no silent merge)
    ids = {C.COHORT_REGIME_SENSOR, C.COHORT_TACTICAL_FIXED,
           C.COHORT_OWNER_WATCHLIST, C.COHORT_EXPERIMENTAL}
    assert len(ids) == 4
