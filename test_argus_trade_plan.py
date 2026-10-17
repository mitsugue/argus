"""V11.18.0 Entry/Exit Planning tests — spec §11."""
import json

import argus_trade_plan as tp

NOW = "2026-07-05T09:00:00+09:00"


def _inputs(**kw):
    base = {"isHeld": False, "assetName": "テスト", "sdRank": "C",
            "sdCondition": "", "sdLevel": "normal", "flowClass": "unknown",
            "scenarioDominant": "base", "apCategory": "", "apRank": None,
            "eventPending": False, "eventName": None, "regimeRiskOff": False,
            "weightPct": None, "concentrationRisk": None,
            "positionRiskLevel": None, "pnlPct": None,
            "priorRunupPct": 2.0, "changePct": 0.5, "marketOpen": True,
            "missing": []}
    base.update(kw)
    return base


def _build(**kw):
    return tp.build_plan("5803", "JP", _inputs(**kw), NOW)


ALL_VARIANTS = [
    dict(), dict(eventPending=True, eventName="米PCE"),
    dict(sdCondition="squeeze_prone", flowClass="short_covering"),
    dict(sdCondition="improving_but_heavy", sdLevel="very_heavy"),
    dict(sdRank="E", flowClass="panic_selling", isHeld=True,
         positionRiskLevel="high", scenarioDominant="bearish"),
    dict(sdRank="A", flowClass="institutional_accumulation",
         scenarioDominant="bullish"),
    dict(isHeld=True, weightPct=30.0, concentrationRisk="high"),
    dict(isHeld=True, pnlPct=35.0, priorRunupPct=20.0, flowClass="distribution"),
    dict(marketOpen=False, priorRunupPct=18.0),
    dict(sdRank=None, flowClass=None, scenarioDominant=None,
         missing=["需給", "フロー"]),
]


# ── validation ───────────────────────────────────────────────────────────────

def test_schema_and_enums():
    p = _build()
    assert p["planType"] in tp.PLAN_TYPES
    assert p["currentStance"] in tp.STANCES
    assert p["planningHorizon"] in tp.HORIZONS
    assert p["evidenceQuality"] in tp.EVIDENCE_QUALITY
    assert p["entryPlan"]["allowedMode"] in tp.ENTRY_MODES
    assert p["entryPlan"]["chaseRisk"] in tp.CHASE_RISKS
    assert p["entryPlan"]["sizeGuidance"] in tp.SIZE_GUIDANCE
    assert p["exitPlan"]["exitMode"] in tp.EXIT_MODES
    assert p["holdPlan"]["holdMode"] in tp.HOLD_MODES
    for k in ("invalidationJa", "nextChecksJa", "complianceNote",
              "priceLevelNoteJa", "sourceEvidence"):
        assert p[k], k


# ── forbidden execution wording (hard rule) ─────────────────────────────────

def test_no_execution_wording_anywhere():
    for kw in ALL_VARIANTS:
        blob = json.dumps(_build(**kw), ensure_ascii=False).lower()
        for bad in tp.FORBIDDEN_WORDING:
            assert bad.lower() not in blob, (bad, kw)


def test_no_fabricated_price_levels():
    for kw in ALL_VARIANTS:
        p = _build(**kw)
        text = " ".join([p["ownerReadableSummaryJa"]] + p["entryConditionsJa"]
                        + p["nextChecksJa"] + p["invalidationJa"])
        assert "円で" not in text and "$" not in text   # qualitative only
        assert "注文価格ではなく" in p["priceLevelNoteJa"]


# ── entry blocking ───────────────────────────────────────────────────────────

def test_entry_blocked_by_event():
    p = _build(eventPending=True, eventName="米PCE",
               sdRank="A", flowClass="institutional_accumulation",
               scenarioDominant="bullish")
    assert p["planType"] == "event_wait"
    assert p["entryPlan"]["allowedMode"] == "wait_event"
    assert p["entryPlan"]["sizeGuidance"] == "none"
    assert "event_pending" in p["blockingReasons"]
    assert "米PCE" in p["ownerReadableSummaryJa"]
    assert "発表後" in p["ownerReadableSummaryJa"]


def test_entry_blocked_by_supply_de():
    p = _build(sdRank="E")
    assert p["entryPlan"]["allowedMode"] == "not_allowed_now"
    assert "supply_demand_bad" in p["blockingReasons"]


def test_entry_blocked_by_flow_deterioration():
    p = _build(flowClass="distribution")
    assert p["entryPlan"]["allowedMode"] == "not_allowed_now"
    assert "flow_deterioration" in p["blockingReasons"]


def test_entry_blocked_by_avoid_chase():
    p = _build(apCategory="avoid_chase")
    assert p["planType"] == "avoid_chase"
    assert p["entryPlan"]["chaseRisk"] == "high"


# ── discipline cases ─────────────────────────────────────────────────────────

def test_improving_but_heavy_pullback_only():
    p = _build(sdCondition="improving_but_heavy", sdLevel="very_heavy")
    assert p["currentStance"] == "add_only_on_pullback"
    assert "A判定ではありません" in p["ownerReadableSummaryJa"]
    assert "吸収" in p["ownerReadableSummaryJa"]
    assert any("需給良好" in w for w in p["whatNotToDoJa"])


def test_squeeze_prone_avoid_chase():
    p = _build(sdCondition="squeeze_prone", flowClass="short_covering")
    assert p["planType"] == "avoid_chase"
    assert "失速" in p["ownerReadableSummaryJa"]
    assert "大口買いが確認できるまで" in p["ownerReadableSummaryJa"]


def test_strong_favorable_small_add_with_caveat():
    p = _build(sdRank="A", flowClass="institutional_accumulation",
               scenarioDominant="bullish")
    assert p["currentStance"] == "small_add_allowed"
    assert p["entryPlan"]["allowedMode"] == "small_trial_only"
    assert p["entryPlan"]["sizeGuidance"] == "small"
    assert "小さく" in p["entryPlan"]["sizeCaveatJa"]
    assert "見送り" in p["ownerReadableSummaryJa"]     # always revocable


def test_held_concentration_blocks_add():
    p = _build(isHeld=True, weightPct=30.0, concentrationRisk="high")
    assert p["currentStance"] == "add_only_on_pullback"
    assert "concentration_high" in p["blockingReasons"]
    assert "リスク確認が先" in p["ownerReadableSummaryJa"]
    assert "比率が高く" in p["ownerReadableSummaryJa"]


def test_held_bearish_risk_review():
    p = _build(isHeld=True, sdRank="E", flowClass="panic_selling",
               positionRiskLevel="high", scenarioDominant="bearish")
    assert p["planType"] == "exit_review"
    assert p["currentStance"] == "risk_review"
    assert p["exitPlan"]["exitMode"] == "risk_reduction_review"
    assert p["holdPlan"]["holdMode"] == "hold_with_risk_review"


def test_profit_protection_review():
    p = _build(isHeld=True, pnlPct=35.0, priorRunupPct=20.0,
               flowClass="distribution")
    assert p["planType"] == "trim_review"
    assert p["currentStance"] == "trim_consideration"
    assert p["exitPlan"]["exitMode"] in ("trim_review", "risk_reduction_review")
    assert "利益を守る" in p["ownerReadableSummaryJa"]
    assert "検討" in p["ownerReadableSummaryJa"]        # review, never an order


def test_hold_until_event():
    p = _build(isHeld=True, eventPending=True, eventName="FOMC")
    assert p["holdPlan"]["holdMode"] == "hold_until_event"
    assert "FOMC" in p["holdPlan"]["reviewTimingJa"]


def test_hold_ok_when_stable():
    p = _build(isHeld=True, sdRank="B")
    assert p["planType"] == "hold"
    assert p["holdPlan"]["holdMode"] in ("hold_ok", "hold_but_monitor")


def test_pts_after_hours_warning():
    p = _build(marketOpen=False, priorRunupPct=18.0)
    assert "market_closed_thin_liquidity" in p["riskFlags"]
    blob = json.dumps(p, ensure_ascii=False)
    assert "PTS/プレは流動性が薄く" in blob
    assert p["planType"] == "avoid_chase"               # overextended + closed


def test_insufficient_evidence_unknown():
    p = _build(sdRank=None, flowClass=None, scenarioDominant=None,
               missing=["需給", "フロー"])
    assert p["planType"] == "unknown"
    assert p["currentStance"] == "unknown"
    assert "捏造" in p["whyJa"]


def test_held_vs_watchlist_distinction():
    held = _build(isHeld=True, sdRank="B")
    watch = _build(isHeld=False, sdRank="B")
    assert held["privacyLevel"] == "private_local"
    assert watch["privacyLevel"] == "private_local"     # isHeld=False is still known
    unknown = tp.build_plan("NVDA", "US", _inputs(isHeld=None), NOW)
    assert unknown["isHeld"] == "unknown"
    assert unknown["privacyLevel"] == "public_safe"
    assert held["trimReviewConditionsJa"] is not None
    assert watch["exitReviewConditionsJa"] == []


# ── aggregates ───────────────────────────────────────────────────────────────

def test_portfolio_summary():
    plans = [_build(sdRank="A", flowClass="institutional_accumulation",
                    scenarioDominant="bullish"),
             _build(sdCondition="improving_but_heavy", sdLevel="very_heavy"),
             _build(sdCondition="squeeze_prone"),
             _build(isHeld=True, pnlPct=35.0, priorRunupPct=20.0,
                    flowClass="distribution"),
             _build(eventPending=True)]
    s = tp.portfolio_summary(plans)
    assert s["addAllowedSmall"] and s["pullbackOnly"] and s["avoidChase"]
    assert s["riskReview"] and s["eventWait"]
    assert "計画サマリ" in s["summaryJa"]


def test_handoff_section():
    plans = [_build(sdCondition="squeeze_prone"), _build(eventPending=True)]
    h = tp.handoff_section(plans)
    assert h["avoidChase"] and h["eventWaitBlocked"]
    assert "売買指示ではない" in h["disclaimerJa"]


def test_status_doc():
    plans = [_build(eventPending=True), _build(sdCondition="squeeze_prone"),
             _build(sdRank=None, flowClass=None, scenarioDominant=None)]
    d = tp.status_doc(plans, now_iso=NOW, sources={"scenarioEngine": True})
    assert d["eventWaitCount"] == 1 and d["avoidChaseCount"] == 1
    assert d["insufficientEvidenceCount"] == 1
    assert d["publicLeakSafe"] is True and d["storageMode"] == "public_redacted"
    blob = json.dumps(d, ensure_ascii=False)
    for banned in ("quantity", "averageCost", "weightPct", "ownerAction"):
        assert banned not in blob


def test_deterministic():
    a = json.dumps(_build(sdCondition="squeeze_prone"), ensure_ascii=False)
    b = json.dumps(_build(sdCondition="squeeze_prone"), ensure_ascii=False)
    assert a == b
