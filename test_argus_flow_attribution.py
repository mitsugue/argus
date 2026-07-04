"""V11.7.0 Big Money / Flow Attribution Engine — pure-module tests.

Discipline under test: never assert big-money presence without direct evidence,
missing evidence must lower confidence and be listed, deterministic output,
no trading actions.
"""
import argus_flow_attribution as fa

NOW = "2026-07-04T05:00:00+00:00"


def _c(ev, symbol="6146", market="JP"):
    return fa.classify(symbol, market, ev, NOW)


# ── schema / determinism ────────────────────────────────────────────────────
def test_schema_and_determinism():
    ev = {"changePct": 4.2, "volumeRatio": 2.1, "closeLocation": 0.85}
    a, b = _c(ev), _c(ev)
    assert a == b                                   # deterministic
    assert a["schemaVersion"] == "flow-attribution-v1"
    assert a["flowClass"] in fa.FLOW_CLASSES
    assert a["actionImplication"] in fa.ACTIONS
    assert 0.1 <= a["confidence"] <= 1.0
    assert set(a["evidence"].keys()) == set(fa.EVIDENCE_KEYS)
    assert a["asOf"] == NOW and a["reasonCodes"]


def test_all_classes_have_ja_labels():
    assert set(fa.CLASS_JA) == set(fa.FLOW_CLASSES)
    assert set(fa.ACTION_JA) == set(fa.ACTIONS)


# ── pattern A: accumulation candidate (no direct flow → capped, hedged) ────
def test_accumulation_without_flow_is_hedged_and_capped():
    r = _c({"changePct": 4.0, "volumeRatio": 2.2, "closeLocation": 0.9})
    assert r["flowClass"] == "institutional_accumulation"
    assert r["directness"] != "direct_evidence"
    assert r["confidence"] <= 0.6                    # inference cap
    assert "実測フロー(大口資金分布)" in r["missingEvidence"]
    assert "断定" in r["ownerReadableWhyJa"] or "可能性" in r["flowClassJa"]
    # NEVER the assertive phrase
    assert "大口が買っている" not in r["ownerReadableWhyJa"]


def test_accumulation_with_measured_flow_is_direct():
    r = _c({"changePct": 3.5, "volumeRatio": 2.0, "closeLocation": 0.8,
            "flowBigNetRatio": 0.25, "shortRatio": 0.30, "shortRatioAvg": 0.32,
            "marginShortHeavy": False, "sources": {"flow": True}})
    assert r["flowClass"] == "institutional_accumulation"
    assert r["directness"] == "direct_evidence"
    assert "MEASURED_BIG_INFLOW" in r["reasonCodes"]
    assert r["confidence"] > 0.6


# ── pattern B: short covering needs short/margin evidence ───────────────────
def test_short_covering_with_margin_evidence():
    r = _c({"changePct": 6.0, "volumeRatio": 2.5, "priorRunupPct": -12,
            "marginShortHeavy": True, "closeLocation": 0.6})
    assert r["flowClass"] == "short_covering"
    assert "買い戻し" in r["flowClassJa"]
    assert r["actionImplication"] == "wait_for_confirmation"


def test_short_covering_without_data_stays_low_confidence():
    r = _c({"changePct": 6.0, "volumeRatio": 2.5, "priorRunupPct": -12,
            "closeLocation": 0.5})
    assert r["confidence"] <= 0.45
    assert "空売り比率" in r["missingEvidence"]


# ── pattern C: retail chase → avoid_chase ───────────────────────────────────
def test_retail_chase_flags_avoid_chase():
    r = _c({"changePct": 9.0, "volumeRatio": 3.0, "priorRunupPct": 25,
            "closeLocation": 0.75, "shortRatio": 0.3, "shortRatioAvg": 0.31,
            "marginShortHeavy": False})
    assert r["flowClass"] == "retail_chase"
    assert r["actionImplication"] == "avoid_chase"
    assert "高値掴み" in r["checkNextJa"]


# ── pattern D: distribution (vol up, weak close / gap fade) ────────────────
def test_gap_fade_distribution():
    r = _c({"changePct": 0.5, "gapPct": 3.0, "volumeRatio": 2.4,
            "closeLocation": 0.15, "flowBigNetRatio": -0.2,
            "shortRatio": 0.3, "shortRatioAvg": 0.3, "marginShortHeavy": False})
    assert r["flowClass"] == "distribution"
    assert r["directness"] == "direct_evidence"
    assert "MEASURED_BIG_OUTFLOW" in r["reasonCodes"]
    assert r["actionImplication"] == "caution"


# ── pattern E: panic selling ────────────────────────────────────────────────
def test_panic_selling():
    r = _c({"changePct": -7.5, "volumeRatio": 3.2, "closeLocation": 0.05,
            "regimeRiskOff": True, "shortRatio": 0.4, "shortRatioAvg": 0.4,
            "marginShortHeavy": False})
    assert r["flowClass"] == "panic_selling"
    assert r["direction"] == "outflow"
    assert "狼狽" in r["flowClassJa"]


# ── pattern F: rotation needs theme-peer evidence ───────────────────────────
def test_rotation_in_requires_peers():
    base = {"changePct": 2.5, "volumeRatio": 1.4, "closeLocation": 0.8,
            "shortRatio": 0.3, "shortRatioAvg": 0.3, "marginShortHeavy": False}
    no_peers = _c(base)
    with_peers = _c({**base, "themePeersSame": 3, "themePeersTotal": 4})
    assert no_peers["flowClass"] != "rotation_in"
    assert "THEME_PEERS_UP" in with_peers["reasonCodes"]


# ── event overlay + unknown ─────────────────────────────────────────────────
def test_event_driven_overlay():
    r = _c({"changePct": -3.0, "volumeRatio": 1.1, "eventToday": True,
            "closeLocation": 0.4, "shortRatio": 0.3, "shortRatioAvg": 0.3,
            "marginShortHeavy": False})
    assert "EVENT_TODAY" in r["reasonCodes"]


def test_no_data_is_unknown_not_fabricated():
    r = _c({})
    assert r["flowClass"] == "unknown"
    assert r["directness"] == "insufficient"
    assert r["actionImplication"] == "no_action"
    assert "価格/出来高データ" in r["missingEvidence"]
    assert r["confidence"] <= 0.2
    # missing evidence explicitly listed, nothing fabricated
    assert all(v is None for v in r["evidence"].values())


def test_liquidity_noise():
    r = _c({"changePct": 3.0, "volumeRatio": 0.6, "liquidityLow": True})
    assert r["flowClass"] == "liquidity_noise"
    assert r["actionImplication"] == "no_action"


def test_stale_data_caps_confidence():
    r = _c({"changePct": 4.0, "volumeRatio": 2.2, "closeLocation": 0.9,
            "flowBigNetRatio": 0.3, "dataAgeMin": 300, "sources": {"flow": True},
            "shortRatio": 0.3, "shortRatioAvg": 0.3, "marginShortHeavy": False})
    assert r["confidence"] <= 0.4
    assert any("鮮度" in m for m in r["missingEvidence"])


def test_mixed_when_patterns_conflict():
    # up + big vol + strong-close accumulation AND heavy short base → close scores
    r = _c({"changePct": 5.5, "volumeRatio": 2.6, "closeLocation": 0.85,
            "priorRunupPct": -10, "marginShortHeavy": True})
    assert r["flowClass"] in ("mixed", "short_covering", "institutional_accumulation")
    if r["flowClass"] == "mixed":
        assert "CONFLICTING_PATTERNS" in r["reasonCodes"]


# ── compliance: vocabulary + no trading verbs ───────────────────────────────
def test_vocabulary_discipline_across_all_classes():
    cases = [
        {"changePct": 4.0, "volumeRatio": 2.2, "closeLocation": 0.9},
        {"changePct": 6.0, "volumeRatio": 2.5, "priorRunupPct": -12, "marginShortHeavy": True},
        {"changePct": 9.0, "volumeRatio": 3.0, "priorRunupPct": 25, "closeLocation": 0.75,
         "shortRatio": 0.3, "shortRatioAvg": 0.31, "marginShortHeavy": False},
        {"changePct": -7.5, "volumeRatio": 3.2, "closeLocation": 0.05,
         "shortRatio": 0.4, "shortRatioAvg": 0.4, "marginShortHeavy": False},
        {},
    ]
    banned = ("大口が買っている", "大口が売っている", "買え", "売れ", "全力", "確実に上がる")
    for ev in cases:
        r = _c(ev)
        text = r["ownerReadableWhyJa"] + r["flowClassJa"] + r["checkNextJa"]
        for phrase in banned:
            assert phrase not in text, (r["flowClass"], phrase)
        assert r["complianceNote"]
        if r["confidence"] < 0.65 and r["flowClass"] != "liquidity_noise":
            assert r["missingEvidence"] or r["flowClass"] == "mixed"


def test_actions_never_include_trading():
    for a in fa.ACTIONS:
        assert a in ("investigate", "wait_for_confirmation", "avoid_chase",
                     "monitor", "caution", "no_action")


# ── status + handoff ────────────────────────────────────────────────────────
def test_status_doc_counts_and_jp_note():
    recs = [_c({"changePct": 4.0, "volumeRatio": 2.2, "closeLocation": 0.9}), _c({})]
    st = fa.status_doc(recs, now_iso=NOW,
                       source_availability={"flow_us": True, "flow_jp": False})
    assert st["assetsScanned"] == 2 and st["unknownCount"] == 1
    assert "意図的に無効" in st["noteJa"]            # JP moomoo off is not an error
    assert st["sourceAvailability"]["flow_jp"] is False


def test_handoff_section_has_opposing_view():
    recs = [_c({"changePct": 4.0, "volumeRatio": 2.2, "closeLocation": 0.9})]
    h = fa.handoff_section(recs)
    assert h["likelyAccumulation"]
    assert "反対解釈" in h["opposingViewJa"]
    assert "断定しない" in h["opposingViewJa"]
    assert h["disclaimerJa"]
