"""V11.17.0 Scenario Engine tests — spec §12."""
import json
import re

import argus_scenario as sc

NOW = "2026-07-04T09:00:00+09:00"


def _inputs(**kw):
    base = {"isHeld": False, "assetName": "テスト", "sdRank": "C",
            "sdCondition": "", "sdLevel": "normal", "sdDirection": "flat",
            "flowClass": "unknown", "instStance": None, "instDirect": False,
            "eventPending": False, "eventName": None, "regimeRiskOff": False,
            "changePct": 0.5, "priorRunupPct": 2.0, "concentrationRisk": None,
            "positionRiskLevel": None, "missing": []}
    base.update(kw)
    return base


def _build(**kw):
    return sc.build_scenario_set("5803", "JP", _inputs(**kw), NOW)


# ── generation basics ────────────────────────────────────────────────────────

def test_base_bullish_bearish_always_present():
    s = _build()
    labels = [c["label"] for c in s["cases"]]
    assert "base" in labels and "bullish" in labels and "bearish" in labels


def test_schema_fields_present():
    s = _build()
    for k in ("schemaVersion", "cases", "dominantScenario", "evidenceQuality",
              "ownerReadableSummaryJa", "nextChecksJa", "whatWouldChangeJa",
              "invalidationJa", "triggers", "complianceNote"):
        assert k in s, k
    assert s["dominantScenario"] in sc.DOMINANTS
    assert s["evidenceQuality"] in sc.EVIDENCE_QUALITY


def test_every_case_has_required_discipline_fields():
    s = _build(eventPending=True, sdCondition="squeeze_prone")
    for c in s["cases"]:
        assert c["probabilityBand"] in sc.BANDS
        assert c["conditionsJa"], c["label"]
        assert c["actionImplication"] in sc.ACTIONS
        assert c["caveatJa"]
    assert s["invalidationJa"] and s["nextChecksJa"] and s["whatWouldChangeJa"]


# ── NO exact probability percentages (hard rule) ────────────────────────────

def test_no_exact_probability_percentages_anywhere():
    variants = [
        _build(), _build(eventPending=True, eventName="米雇用統計"),
        _build(sdCondition="squeeze_prone", flowClass="short_covering"),
        _build(sdCondition="improving_but_heavy", sdLevel="very_heavy"),
        _build(sdRank="E", flowClass="panic_selling", isHeld=True,
               positionRiskLevel="high"),
        _build(sdRank="A", flowClass="institutional_accumulation",
               instStance="bullish", instDirect=True),
    ]
    pat = re.compile(r"\d{1,3}\s*[%％]")
    for s in variants:
        text = json.dumps(s, ensure_ascii=False)
        assert not pat.search(text), pat.search(text).group(0)
        for bad in ("の確率で", "%で上がる", "％の確率"):
            assert bad not in text


# ── squeeze_then_fade ────────────────────────────────────────────────────────

def test_squeeze_generates_fade_case_and_avoid_chase():
    s = _build(sdCondition="squeeze_prone", flowClass="short_covering")
    labels = [c["label"] for c in s["cases"]]
    assert "squeeze_then_fade" in labels
    fade = next(c for c in s["cases"] if c["label"] == "squeeze_then_fade")
    assert "失速" in fade["narrativeJa"]
    bull = next(c for c in s["cases"] if c["label"] == "bullish")
    assert "買い戻し" in bull["narrativeJa"]           # squeeze caveat mandatory
    assert bull["actionImplication"] == "avoid_chase"  # never chase a squeeze


# ── improving_but_heavy ──────────────────────────────────────────────────────

def test_improving_but_heavy_never_upgraded():
    s = _build(sdCondition="improving_but_heavy", sdLevel="very_heavy",
               sdDirection="improving", sdRank="C")
    base = next(c for c in s["cases"] if c["label"] == "base")
    assert "まだ重い" in base["narrativeJa"] or "重い" in base["narrativeJa"]
    assert "A扱いしません" in base["narrativeJa"]
    assert base["actionImplication"] == "add_only_on_pullback"
    assert any("上値吸収" in c for c in s["nextChecksJa"])


# ── event-wait ───────────────────────────────────────────────────────────────

def test_event_pending_forces_wait_event_dominant():
    s = _build(eventPending=True, eventName="米雇用統計",
               sdRank="A", flowClass="institutional_accumulation",
               instStance="bullish", instDirect=True)
    assert s["dominantScenario"] == "wait_event"    # never attack before events
    labels = [c["label"] for c in s["cases"]]
    assert "wait_event" in labels
    we = next(c for c in s["cases"] if c["label"] == "wait_event")
    assert "米雇用統計" in we["titleJa"]
    assert we["actionImplication"] == "wait"
    assert any(t["triggerType"] == "event_result" for t in s["triggers"])


# ── dominant ladder ──────────────────────────────────────────────────────────

def test_compounded_adverse_gives_bearish_dominant():
    s = _build(sdRank="E", flowClass="panic_selling", isHeld=True,
               positionRiskLevel="high")
    assert s["dominantScenario"] == "bearish"
    bear = next(c for c in s["cases"] if c["label"] == "bearish")
    assert bear["actionImplication"] == "review_position"  # held → review


def test_strong_aligned_support_gives_bullish_dominant():
    s = _build(sdRank="A", flowClass="institutional_accumulation",
               instStance="bullish", instDirect=True, priorRunupPct=3.0)
    assert s["dominantScenario"] == "bullish"
    assert "条件" in s["ownerReadableSummaryJa"]  # still conditional, not certain


def test_overextended_blocks_bullish_dominant_and_chase():
    s = _build(sdRank="A", flowClass="institutional_accumulation",
               instStance="bullish", instDirect=True, priorRunupPct=25.0)
    assert s["dominantScenario"] != "bullish"
    bull = next(c for c in s["cases"] if c["label"] == "bullish")
    assert bull["actionImplication"] == "avoid_chase"


def test_conflict_gives_mixed():
    s = _build(sdRank="D", flowClass="institutional_accumulation")
    assert s["dominantScenario"] == "mixed"


# ── held vs watchlist ────────────────────────────────────────────────────────

def test_held_and_watchlist_differ():
    held = _build(isHeld=True, sdRank="D", flowClass="distribution")
    watch = _build(isHeld=False, sdRank="D", flowClass="distribution")
    assert held["isHeld"] is True and watch["isHeld"] is False
    hb = next(c for c in held["cases"] if c["label"] == "bearish")
    wb = next(c for c in watch["cases"] if c["label"] == "bearish")
    assert hb["actionImplication"] == "review_position"
    assert wb["actionImplication"] == "wait"
    assert "保有中" in held["ownerReadableSummaryJa"]
    assert "保有中" not in watch["ownerReadableSummaryJa"]


def test_held_unknown_stays_unknown():
    s = sc.build_scenario_set("NVDA", "US", _inputs(isHeld=None), NOW)
    assert s["isHeld"] == "unknown"
    assert s["privacyLevel"] == "public_safe"


# ── missing evidence ─────────────────────────────────────────────────────────

def test_insufficient_evidence_goes_unknown():
    s = _build(sdRank=None, flowClass=None, changePct=None,
               missing=["supply_demand", "flow"])
    assert s["evidenceQuality"] == "insufficient"
    assert s["dominantScenario"] == "unknown"
    assert "判定保留" in s["ownerReadableSummaryJa"]
    assert s["missingEvidence"]


def test_missing_never_fabricated_into_support():
    s = _build(sdRank=None, flowClass=None, missing=["supply_demand"])
    bull = next(c for c in s["cases"] if c["label"] == "bullish")
    assert not bull["supportingEvidence"]


# ── JP display / language ────────────────────────────────────────────────────

def test_jp_title_uses_code_plus_name():
    s = sc.build_scenario_set("5803", "JP", _inputs(assetName="フジクラ"), NOW)
    base = next(c for c in s["cases"] if c["label"] == "base")
    assert "5803 フジクラ" in base["titleJa"]


def test_compliance_note_everywhere():
    s = _build()
    assert "売買指示" in s["complianceNote"]
    for c in s["cases"]:
        assert "売買指示" in c["caveatJa"]


# ── market / handoff / status ────────────────────────────────────────────────

def test_market_scenario_event_wait():
    m = sc.market_scenario("RISK_ON", False, ["FOMC"], NOW)
    assert m["dominantScenario"] == "wait_event"
    assert "FOMC" in m["ownerReadableSummaryJa"]


def test_market_scenario_risk_off():
    m = sc.market_scenario("RISK_OFF", True, [], NOW)
    assert m["dominantScenario"] == "bearish"


def test_handoff_section_has_opposing_view():
    sets = [_build(), _build(sdRank="E", flowClass="panic_selling")]
    h = sc.handoff_section(sets)
    assert h["top"] and "反対シナリオ" in h["opposingJa"]


def test_status_doc_public_safe():
    sets = [_build(eventPending=True), _build(sdRank=None, flowClass=None,
                                              changePct=None)]
    d = sc.status_doc(sets, now_iso=NOW, sources={"supply_demand": True})
    assert d["publicLeakSafe"] is True
    assert d["eventWaitCount"] == 1
    assert d["insufficientEvidenceCount"] == 1
    text = json.dumps(d, ensure_ascii=False)
    for bad in ("quantity", "averageCost", "weightPct", "ownerAction"):
        assert bad not in text


def test_deterministic():
    a = json.dumps(_build(sdCondition="squeeze_prone"), ensure_ascii=False)
    b = json.dumps(_build(sdCondition="squeeze_prone"), ensure_ascii=False)
    assert a == b
