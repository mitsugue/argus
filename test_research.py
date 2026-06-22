"""Unit tests for the hardened Research Dossier engine (argus_research.py, v10.41.1)."""
import math

import argus_research as rs


def _sum1(group):
    return abs(sum(p for _, p in group) - 1.0) < 0.01


# ── #3 confidence: UNCONFIRMED flow must NOT count as a signal ────────────────
def test_unconfirmed_flow_is_not_a_signal():
    assert rs.has_confirmed_flow_signal("SHORT_COVERING")
    assert not rs.has_confirmed_flow_signal("UNCONFIRMED")
    assert not rs.has_confirmed_flow_signal(None)
    cov_with, _ = rs.evidence_coverage(True, "unknown", "unconfirmed", False)
    cov_unconf, _ = rs.evidence_coverage(False, "unknown", "unconfirmed", False)
    assert cov_with > cov_unconf       # a real flow adds coverage; UNCONFIRMED does not


# ── #2 source-tiered catalyst ────────────────────────────────────────────────
def test_generic_news_does_not_become_official_catalyst():
    c = rs.probable_cause("PRICE_SPIKE", None, "reputable_secondary_media", "company_specific")
    assert c.get("official_catalyst", 0) == 0          # a headline is NOT an official catalyst
    assert c.get("reported_catalyst", 0) > 0


def test_official_filing_raises_official_catalyst():
    c = rs.probable_cause("PRICE_SPIKE", None, "official_filing", "company_specific")
    assert c["official_catalyst"] > 0
    assert rs.is_official_catalyst("official_filing") and not rs.is_official_catalyst("aggregator")


# ── #4 probability validation ────────────────────────────────────────────────
def test_probability_groups_sum_to_one():
    assert abs(sum(rs.probable_cause("PRICE_SPIKE", "SHORT_COVERING", "unknown", "company_specific").values()) - 1) < 0.01
    assert abs(sum(rs.next_session_scenarios("PRICE_SPIKE", "DISTRIBUTION").values()) - 1) < 0.01


def test_malformed_probabilities_become_unknown():
    assert rs.validate_probs({"a": float("nan"), "b": float("inf"), "c": -1}) == {"unknown": 1.0}
    assert rs.validate_probs({}) == {"unknown": 1.0}
    assert rs.validate_probs("not a dict") == {"unknown": 1.0}
    out = rs.validate_probs({"x": 1, "y": 1})
    assert abs(sum(out.values()) - 1.0) < 0.001


# ── #8 market scope baseline ─────────────────────────────────────────────────
def test_market_scope_company_market_missing_stale():
    assert rs.market_scope(8.0, 0.2) == "company_specific"
    assert rs.market_scope(2.0, 1.8) == "market_wide"
    assert rs.market_scope(8.0, None) == "unconfirmed"            # missing benchmark
    assert rs.market_scope(8.0, 0.2, index_fresh=False) == "unconfirmed"  # stale benchmark


# ── #1 evidence taxonomy ─────────────────────────────────────────────────────
def test_confirmed_facts_exclude_flow_and_headlines_and_keep_own_ids():
    evidence = [
        {"evidenceId": "e1", "claimType": "market_observation", "normalizedClaim": "9999 +18%"},
        {"evidenceId": "e2", "claimType": "derived_metric", "normalizedClaim": "flow=SHORT_COVERING"},
        {"evidenceId": "e3", "claimType": "news_report", "normalizedClaim": "観測報道A", "reliability": 0.45},
        {"evidenceId": "e4", "claimType": "news_report", "normalizedClaim": "観測報道B", "reliability": 0.45},
        {"evidenceId": "e5", "claimType": "news_report", "normalizedClaim": "掲示板の噂", "reliability": 0.2},
    ]
    t = rs.classify_evidence(evidence)
    assert t["confirmedFacts"] == []                              # nothing official → empty
    assert t["derivedMetrics"][0]["evidenceIds"] == ["e2"]       # flow is a derived metric
    # each news claim references its OWN id (the shared-first-id bug is fixed)
    assert [c["evidenceIds"] for c in t["reportedClaims"]] == [["e3"], ["e4"]]
    assert t["unverifiedClaims"][0]["evidenceIds"] == ["e5"]     # low-reliability → unverified


# ── full dossier shape + temporal + calibration ──────────────────────────────
def test_build_dossier_v2_full():
    event = {"eventId": "e1", "eventType": "LIMIT_UP", "severity": 5, "symbol": "9999",
             "session": "JP_MORNING", "lifecycleState": "HIGH_ALERT", "eventVersion": 3,
             "reasonJa": "S高到達", "observedAt": "2026-06-22T01:00:00Z", "detectedAt": "2026-06-22T01:00:05Z"}
    flow_inf = {"classification": "SHORT_COVERING",
                "probabilities": {"newLongAccumulation": 0.2, "shortCovering": 0.5,
                                  "distribution": 0.1, "retailNoise": 0.1, "unconfirmed": 0.1}}
    ev = [{"evidenceId": "e1#ev1", "claimType": "market_observation", "normalizedClaim": "x"}]
    times = {"asOf": "2026-06-22T02:00:00Z", "dossierGeneratedAt": "2026-06-22T02:00:00Z",
             "eventObservedAt": "2026-06-22T01:00:00Z", "eventDetectedAt": "2026-06-22T01:00:05Z",
             "evidenceAsOf": "2026-06-22T01:00:00Z", "mode": "event_time_snapshot"}
    d = rs.build_dossier(event=event, flow_inf=flow_inf, rsi=72, sym_chg=18.0, index_chg=0.3,
                         index_fresh=True, catalyst_tier="reputable_secondary_media", evidence=ev,
                         times=times, evidence_hash="abc123", asset_name="テスト")
    assert d["schemaVersion"] == "dossier-v2" and d["researchPosture"] == "LIMIT_UP_RISK"
    assert d["eventVersion"] == 3 and d["evidenceHash"] == "abc123"
    assert d["dossierMode"] == "event_time_snapshot"
    assert d["confidenceCalibrationStatus"] == "uncalibrated_heuristic_v1"
    assert all(c.get("calibrationStatus") for c in d["probableCause"])      # per-group calibration tag
    assert _sum1([(k, v) for k, v in d["flowInference"].items()])           # flowInference sums to 1
    assert _sum1([(c["label"], c["probability"]) for c in d["probableCause"]])
    assert d["confirmedFacts"] == []                                        # honest: no official fact
    assert "自動売買" in d["disclaimerJa"]


def test_dossier_preserves_and_nulls_timestamps_honestly():
    event = {"eventId": "e2", "eventType": "PRICE_SPIKE", "severity": 4, "symbol": "9999",
             "lifecycleState": "VERIFIED", "reasonJa": "急騰", "eventVersion": 1,
             "observedAt": "2026-06-22T01:00:00Z", "detectedAt": "2026-06-22T01:00:05Z"}
    times = {"asOf": "2026-06-22T02:00:00Z", "dossierGeneratedAt": "2026-06-22T02:00:00Z",
             "eventObservedAt": event["observedAt"], "eventDetectedAt": event["detectedAt"],
             "evidenceAsOf": None, "mode": "event_time_snapshot"}
    d = rs.build_dossier(event=event, flow_inf=None, rsi=None, sym_chg=6.0, index_chg=None,
                         index_fresh=True, catalyst_tier="unknown", evidence=[], times=times, evidence_hash="h")
    assert d["eventObservedAt"] == "2026-06-22T01:00:00Z"      # true event time preserved
    assert d["evidenceAsOf"] is None                          # unavailable → null, not fabricated
    assert d["flowInference"] == {"unknown": 1.0}             # no flow → unknown=1
    assert any("指数" in m for m in d["missingData"])          # honest missing benchmark


def test_posture_never_a_trade_instruction():
    for et in ("PRICE_SPIKE", "PRICE_CRASH", "LIMIT_UP", "LIMIT_DOWN_PROXIMITY"):
        p = rs.research_posture(et, 5, "company_specific", "DISTRIBUTION", 0.7, "CAUTION")
        assert p in rs.RESEARCH_POSTURES and p not in ("BUY", "SELL", "EXECUTE")
    assert rs.research_posture("PRICE_SPIKE", 5, "company_specific", None, 0.2) == "OBSERVE"   # low coverage downgrades


# ── EDINET filing semantics (v10.50) ─────────────────────────────────────────
def test_classify_edinet_doc():
    assert rs.classify_edinet_doc("120", "有価証券報告書") == "periodic"
    assert rs.classify_edinet_doc("180", "臨時報告書") == "extraordinary"
    assert rs.classify_edinet_doc("350", "大量保有報告書") == "large_volume_holding"
    assert rs.classify_edinet_doc("", "訂正臨時報告書") == "amendment"   # 訂正 wins
    assert rs.classify_edinet_doc("999", "謎の書類") == "other"
    assert rs.classify_edinet_doc("180", "") == "extraordinary"          # falls back to code


def test_edinet_event_relationship():
    assert rs.edinet_event_relationship("2026-06-22 09:30", "2026-06-22") == "precedes_or_same_day"
    assert rs.edinet_event_relationship("2026-06-23 09:30", "2026-06-22") == "after_event_day"
    assert rs.edinet_event_relationship("", "2026-06-22") == "unknown"


def test_edinet_catalyst_decision():
    same_day_extra = [{"docClass": "extraordinary", "submitDateTime": "2026-06-22 14:00"}]
    ok, q = rs.edinet_catalyst_decision(same_day_extra, "2026-06-22")
    assert ok and len(q) == 1
    # periodic same-day is NOT a catalyst
    assert rs.edinet_catalyst_decision(
        [{"docClass": "periodic", "submitDateTime": "2026-06-22 09:00"}], "2026-06-22")[0] is False
    # extraordinary but filed the NEXT day cannot have caused today's move
    assert rs.edinet_catalyst_decision(
        [{"docClass": "extraordinary", "submitDateTime": "2026-06-23 09:00"}], "2026-06-22")[0] is False
