"""V11.19.0 Portfolio Strategy / FIRE Alignment tests — spec §11."""
import json
import re

import argus_portfolio_strategy as ps
import argus_trade_plan as tp

NOW = "2026-07-05T10:00:00+09:00"


def _role(sym, **kw):
    base = {"assetName": sym, "theme": "other", "assetType": "stock",
            "isHeld": True, "weightPct": 5.0, "eventPending": False,
            "concentrationRisk": None}
    base.update(kw)
    return ps.classify_role(sym, "JP", base)


def _strategy(**kw):
    roles = kw.pop("roles", [
        _role("EMAXIS", theme="index_core", assetType="fund", weightPct=35.0),
        _role("GLDM", theme="gold", weightPct=10.0),
        _role("5803", theme="ai_infrastructure", weightPct=10.0),
        _role("BTC", theme="crypto", assetType="crypto", weightPct=5.0),
    ])
    base = {"roles": roles,
            "byThemePct": {"index_core": 35.0, "gold": 10.0,
                           "ai_infrastructure": 10.0, "crypto": 5.0},
            "jpyPct": 55.0, "usdPct": 45.0,
            "top1Symbol": "EMAXIS", "top1Pct": 35.0, "singleNameRisk": "medium",
            "knownCoverage": 0.9, "unpricedCount": 0, "noHoldings": False,
            "eventPending": False, "regimeRiskOff": False,
            "recurringAccumulationKnown": None}
    base.update(kw)
    return ps.build_strategy(base, NOW)


# ── validation ───────────────────────────────────────────────────────────────

def test_schema_and_enums():
    s = _strategy()
    assert s["strategyMode"] in ps.STRATEGY_MODES
    assert s["ownerGoal"] in ps.OWNER_GOALS
    assert s["fireAlignment"]["status"] in ps.FIRE_STATUSES
    assert s["fireAlignment"]["scoreBand"] in ps.SCORE_BANDS
    rb = s["riskBudgetSummary"]
    assert rb["totalRiskLevel"] in ps.RISK_LEVELS
    assert rb["tacticalRiskBudget"] in ps.TACTICAL_BUDGETS
    for r in s["assetRoles"]:
        assert r["role"] in ps.ROLES
        assert r["strategyFit"] in ps.STRATEGY_FITS
        assert r["addPolicy"] in ps.ADD_POLICIES
        assert r["trimReviewPolicy"] in ps.TRIM_POLICIES
    assert "助言ではない" in s["complianceNote"]


# ── role classification ──────────────────────────────────────────────────────

def test_index_fund_is_core():
    r = _role("EMAXIS", theme="index_core", assetType="fund")
    assert r["role"] == "core" and r["timeHorizon"] == "long_term"
    assert r["addPolicy"] == "systematic_accumulation"


def test_gold_is_hedge():
    r = _role("GLDM", theme="gold")
    assert r["role"] == "hedge"
    assert "ヘッジ" in r["roleReasonJa"]
    assert r["addPolicy"] == "monitor_only"


def test_crypto_role_depends_on_size():
    small = _role("XRP", theme="crypto", assetType="crypto", weightPct=4.0)
    big = _role("BTC", theme="crypto", assetType="crypto", weightPct=14.0)
    assert small["role"] == "satellite"
    assert big["role"] == "tactical" and big["timeHorizon"] == "short_term"


def test_high_beta_big_weight_is_tactical():
    r = _role("5803", theme="ai_infrastructure", weightPct=20.0)
    assert r["role"] == "tactical"
    assert r["strategyFit"] == "stretched"
    assert r["addPolicy"] == "no_add_until_risk_reduces"
    assert r["trimReviewPolicy"] == "if_overweight"


def test_watchlist_only_role():
    r = _role("NVDA", isHeld=False)
    assert r["role"] == "watch_only" and r["weightPct"] is None


def test_satellite_note_wording():
    r = _role("8058", theme="trading_commodity", weightPct=8.0)
    assert r["role"] == "satellite"
    assert "全体比率" in r["roleReasonJa"]      # spec example E


# ── strategy rules ───────────────────────────────────────────────────────────

def test_tactical_budget_bands():
    def tac(pct):
        roles = [_role("A", theme="ai_infrastructure", weightPct=pct),
                 _role("EMAXIS", theme="index_core", assetType="fund",
                       weightPct=100 - pct)]
        return _strategy(roles=roles, byThemePct={"ai_infrastructure": pct,
                                                  "index_core": 100 - pct}
                         )["riskBudgetSummary"]["tacticalRiskBudget"]
    assert tac(50.0) == "exceeded"       # weight>=15 → tactical role
    assert tac(30.0) == "stretched"
    assert tac(20.0) == "appropriate"
    assert _strategy()["riskBudgetSummary"]["tacticalRiskBudget"] == "underused"


def test_tactical_stretched_owner_text():
    roles = [_role("A", theme="ai_infrastructure", weightPct=35.0),
             _role("EMAXIS", theme="index_core", assetType="fund", weightPct=65.0)]
    s = _strategy(roles=roles, byThemePct={"ai_infrastructure": 35.0, "index_core": 65.0})
    assert "短期勝負枠が大きくなっている" in s["riskBudgetSummary"]["ownerReadableRiskJa"]
    assert s["strategyMode"] == "tactical_aggressive"


def test_theme_concentration_warning():
    s = _strategy(byThemePct={"ai_infrastructure": 30.0,
                              "physical_ai_robotics": 15.0,
                              "semiconductor_photonics": 10.0, "index_core": 45.0})
    assert s["riskBudgetSummary"]["themeRisk"] in ("high", "critical")
    assert any("AI" in w and "弱くなります" in w for w in s["strategicWarningsJa"])
    assert any("AI調整局面" in n for n in s["portfolioStressNotesJa"])


def test_single_name_concentration_warning():
    s = _strategy(singleNameRisk="critical", top1Symbol="5803", top1Pct=45.0)
    assert s["riskBudgetSummary"]["singleNameRisk"] == "critical"
    assert s["fireAlignment"]["status"] == "misaligned"
    assert any("5803" in w for w in s["strategicWarningsJa"])


def test_core_underweight_warning():
    roles = [_role("A", theme="ai_infrastructure", weightPct=12.0),
             _role("B", theme="trading_commodity", weightPct=70.0),
             _role("C", theme="crypto", assetType="crypto", weightPct=18.0)]
    s = _strategy(roles=roles, byThemePct={"ai_infrastructure": 12.0,
                                           "trading_commodity": 70.0, "crypto": 18.0})
    assert any("コア資産の比率が不足" in w for w in s["fireAlignment"]["warningJa"])
    assert s["fireAlignment"]["status"] in ("stretched", "misaligned")


def test_aligned_when_core_strong():
    s = _strategy()
    assert s["fireAlignment"]["status"] in ("aligned", "mostly_aligned")
    assert s["strategyMode"] == "fire_growth"
    assert any("金の比率" in o for o in s["strategicOpportunitiesJa"])   # gold hedge note


def test_missing_data_honest():
    s = _strategy()
    assert any("積立" in m for m in s["missingDataJa"])
    assert any("ローン" in m for m in s["missingDataJa"])
    assert s["cashAllocation"] is None                       # never fabricated
    assert "捏造しません" in s["fireAlignment"]["cashFlowFitJa"]


def test_no_holdings_unknown():
    s = _strategy(noHoldings=True, roles=[], byThemePct={})
    assert s["strategyMode"] == "unknown"
    assert s["fireAlignment"]["status"] == "unknown"
    assert s["fireAlignment"]["scoreBand"] == "insufficient_data"
    assert s["riskBudgetSummary"]["tacticalRiskBudget"] == "unknown"


# ── no retirement-probability overclaiming ───────────────────────────────────

def test_no_fire_probability_or_precision():
    variants = [_strategy(), _strategy(noHoldings=True, roles=[], byThemePct={}),
                _strategy(singleNameRisk="critical", top1Symbol="X", top1Pct=50.0)]
    pat = re.compile(r"\d{1,3}\s*[%％]の確率|リタイア確率|到達年|達成確率")
    for s in variants:
        blob = json.dumps(s, ensure_ascii=False)
        assert not pat.search(blob)
        assert "帯のみ" in s["precisionNote"]


# ── entry/exit plan constrained by portfolio risk ────────────────────────────

def test_plan_downgraded_by_tactical_stretch():
    good = {"isHeld": False, "assetName": "T", "sdRank": "A",
            "flowClass": "institutional_accumulation", "scenarioDominant": "bullish",
            "marketOpen": True, "priorRunupPct": 2.0}
    free = tp.build_plan("9999", "JP", dict(good), NOW)
    constrained = tp.build_plan("9999", "JP",
                                dict(good, portfolioTacticalStretched=True), NOW)
    assert free["currentStance"] == "small_add_allowed"
    assert constrained["currentStance"] == "add_only_on_pullback"
    assert "portfolio_tactical_stretched" in constrained["blockingReasons"]
    assert any("整理が先" in w for w in constrained["whatNotToDoJa"])


def test_plan_downgraded_by_theme_concentration():
    good = {"isHeld": False, "assetName": "T", "sdRank": "A",
            "flowClass": "institutional_accumulation", "scenarioDominant": "bullish",
            "marketOpen": True, "priorRunupPct": 2.0}
    constrained = tp.build_plan("9999", "JP",
                                dict(good, themeConcentrationHigh=True), NOW)
    assert constrained["currentStance"] == "add_only_on_pullback"
    assert "theme_concentration_high" in constrained["blockingReasons"]


# ── aggregates ───────────────────────────────────────────────────────────────

def test_handoff_section():
    h = ps.handoff_section(_strategy(singleNameRisk="critical",
                                     top1Symbol="5803", top1Pct=45.0))
    assert h["balanceJa"] and h["concentrationJa"]
    assert "反対view" in h["opposingJa"]
    assert "助言ではない" in h["disclaimerJa"]
    assert h["missingDataJa"]


def test_public_status_redacted():
    d = ps.public_status(now_iso=NOW, sources={"positionExposure": False})
    assert d["serverKnowsHoldings"] is False
    assert d["serverKnowsStrategyDetails"] is False
    assert d["storageMode"] == "public_redacted"
    assert d["publicLeakSafe"] is True
    blob = json.dumps(d, ensure_ascii=False)
    for banned in ("quantity", "averageCost", "weightPct", "ownerAction",
                   "mortgage", "income", "top1"):
        assert banned not in blob


def test_deterministic():
    a = json.dumps(_strategy(), ensure_ascii=False)
    b = json.dumps(_strategy(), ensure_ascii=False)
    assert a == b
