"""Tests for multidimensional posture scoring (argus_posture.py)."""
import argus_posture as P


def test_dimensions_exist():
    for d in ("equityRisk", "creditRisk", "volatility", "japanRisk", "safeHaven"):
        assert d in P.DIMENSIONS


def test_volatility_inverse_sign():
    # VIX UP must read as risk-OFF (negative volatility-dimension score)
    out = P.dimension_outcomes({"VIX": +5.0}, {"VIX": 8.0})
    assert out["volatility"]["score"] < 0


def test_equity_up_is_risk_on():
    out = P.dimension_outcomes({"SPY": 1.0, "QQQ": 1.0, "IWM": 1.0},
                               {"SPY": 1.0, "QQQ": 1.0, "IWM": 1.0})
    assert out["equityRisk"]["score"] > 0
    assert out["equityRisk"]["status"] == "ok"


def test_partial_dimension_reports_missing():
    out = P.dimension_outcomes({"SPY": 1.0}, {"SPY": 1.0})  # QQQ/IWM missing
    assert out["equityRisk"]["status"] == "partial"
    assert "QQQ" in out["equityRisk"]["missing"]


def test_credit_relative_hyg_vs_lqd():
    # HY up + IG down → risk-on credit (HYG +1, LQD -1)
    out = P.dimension_outcomes({"HYG": 1.0, "LQD": -1.0}, {"HYG": 1.0, "LQD": 1.0})
    assert out["creditRisk"]["score"] > 0


def test_posture_partial_when_too_few_dims():
    # only SPY available → fewer than MIN_DIMENSIONS risk-appetite dims
    out = P.posture_outcome({"SPY": 1.0}, {"SPY": 1.0})
    assert out["status"] == "partial"
    assert "risk-appetite dimensions" in out["reason"]


def test_posture_ok_with_enough_dims():
    rets = {"SPY": 1.0, "QQQ": 1.0, "IWM": 1.0, "HYG": 1.0, "LQD": 0.0, "BTC": 2.0, "SMH": 1.0}
    vols = {k: 1.0 for k in rets}
    out = P.posture_outcome(rets, vols)
    assert out["status"] == "ok"
    assert out["aggregateRiskAppetite"] > 0


def test_grade_risk_on_hit_and_miss():
    rets_up = {"SPY": 1.0, "QQQ": 1.0, "IWM": 1.0, "HYG": 1.0, "LQD": 0.0, "BTC": 2.0, "SMH": 1.0}
    vols = {k: 1.0 for k in rets_up}
    out = P.posture_outcome(rets_up, vols)
    g = P.grade_posture("RISK_ON", out)
    assert g["graded"] is True and g["hit"] is True

    rets_dn = {k: -v for k, v in rets_up.items()}
    out2 = P.posture_outcome(rets_dn, vols)
    assert P.grade_posture("RISK_ON", out2)["hit"] is False
    assert P.grade_posture("RISK_OFF", out2)["hit"] is True


def test_grade_no_strong_claim_not_graded():
    out = P.posture_outcome({"SPY": 1, "QQQ": 1, "IWM": 1, "HYG": 1, "BTC": 1}, None)
    assert P.grade_posture("CAUTIOUS", out)["graded"] is False
    assert P.grade_posture("MIXED", out)["graded"] is False


def test_grade_partial_not_scorable():
    out = P.posture_outcome({"SPY": 1.0}, {"SPY": 1.0})  # partial
    assert P.grade_posture("RISK_ON", out)["graded"] is False


def test_not_spy_only_fallback():
    # The whole point: with only SPY we must be PARTIAL, not a confident grade.
    out = P.posture_outcome({"SPY": 5.0}, {"SPY": 1.0})
    assert out["status"] == "partial"
    assert P.grade_posture("RISK_ON", out)["graded"] is False
