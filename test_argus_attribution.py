"""Tests for Cause Attribution Integrity (argus_attribution.py)."""
import argus_attribution as A


def _ev(**kw):
    base = {"id": "e1", "kind": "news", "publishedAt": "2026-06-23T00:00:00Z",
            "sourceReliability": 0.6, "supports": ["COMPANY_SPECIFIC_CATALYST"]}
    base.update(kw)
    return base


# evidence timestamp precedes claimed trigger
def test_role_trigger_requires_publish_before_move():
    ev = _ev(publishedAt="2026-06-23T00:05:00Z")
    r = A.causal_role(ev, "2026-06-23T00:30:00Z")     # published before move
    assert r["role"] == "trigger"


def test_evidence_after_move_is_not_trigger():
    ev = _ev(publishedAt="2026-06-23T02:00:00Z")
    r = A.causal_role(ev, "2026-06-23T00:30:00Z")     # published AFTER the move
    assert r["role"] in ("amplifier", "background_only")
    assert r["role"] != "trigger"


# stale report cannot become immediate trigger
def test_stale_report_not_immediate_trigger():
    ev = _ev(kind="report", publishedAt="2026-06-19T00:00:00Z")  # 4 days stale
    r = A.causal_role(ev, "2026-06-23T00:30:00Z")
    assert r["role"] == "background_only"


def test_stale_report_with_recirculation_can_be_amplifier():
    ev = _ev(kind="report", publishedAt="2026-06-19T00:00:00Z", sameDayRecirculation=True)
    r = A.causal_role(ev, "2026-06-23T00:30:00Z")
    assert r["role"] != "background_only"


# earnings not yet released cannot be earnings-result cause
def test_future_earnings_not_trigger():
    ev = _ev(kind="earnings", isFutureEvent=True)
    r = A.causal_role(ev, "2026-06-23T00:30:00Z")
    assert r["role"] == "background_only"


def test_attribute_pre_earnings_not_result_shock():
    ctx = {"moveStartedAt": "2026-06-23T00:30:00Z", "daysToEarnings": 1,
           "earningsResultReleased": False, "priorRunupPct": 22, "peersDown": True,
           "shortWindowDownAccel": True}
    out = A.attribute_cause(ctx, [_ev(kind="earnings", isFutureEvent=True, supports=[])])
    top = max(out["causeProbabilities"], key=out["causeProbabilities"].get)
    assert top == "PRE_EARNINGS_DE_RISKING"
    assert "EARNINGS_RESULT_SHOCK" not in out["causeProbabilities"]
    assert out["preEvent"]["badResultConfirmed"] is False


# pre-event detector
def test_pre_event_derisking_probability():
    out = A.pre_event_derisking({"daysToEarnings": 2, "earningsResultReleased": False,
                                 "priorRunupPct": 18, "peersDown": True, "shortWindowDownAccel": True})
    assert out["preEventDeRiskingProbability"] >= 0.5
    assert out["badResultConfirmed"] is False
    assert out["actionOverride"] in ("DO_NOT_ADD", "REVIEW_REQUIRED", "HOLD_CAUTION")


# short sale volume is not short interest
def test_short_volume_semantics():
    sv = A.POSITIONING_SOURCES["finra_daily_short_volume"]
    si = A.POSITIONING_SOURCES["finra_short_interest"]
    assert sv["isTransactionVolume"] is True and sv["isPositionData"] is False
    assert si["isPositionData"] is True and si["isTransactionVolume"] is False


# delayed positioning sources cannot identify intraday whale action
def test_positioning_no_intraday_identity():
    # The error-prevention contract: the daily short-VOLUME source must NOT be
    # treated as position data or as identity, and every source carries an
    # explicit publication-delay note (none is real-time intraday flow).
    sv = A.POSITIONING_SOURCES["finra_daily_short_volume"]
    assert sv["identityAvailable"] is False and sv["isPositionData"] is False
    for s in A.POSITIONING_SOURCES.values():
        assert s.get("publicationDelayJa")          # every source states its delay
        assert "isPositionData" in s and "isTransactionVolume" in s


def test_positioning_probabilities_sum_to_one_no_identity():
    out = A.positioning_probabilities({"flowRatio": -0.2, "changePct": -4.0, "volRatio": 1.5,
                                       "priorFlowRatio": 0.1})
    assert round(sum(out["probabilities"].values()), 2) == 1.0
    assert out["identityClaim"] is None


def test_positioning_unknown_nonzero_when_thin():
    out = A.positioning_probabilities({})   # no fast evidence
    assert out["probabilities"]["unknown"] > 0


# no named institution without official evidence
def test_narrative_rejects_named_institution():
    v = A.narrative_violations("JPモルガンがクジラを売らせた")
    assert any(x["type"] == "named_entity_without_evidence" for x in v)
    # with official identity evidence it's allowed
    v2 = A.narrative_violations("13Dでブラックロックの保有減を確認", has_official_identity=True)
    assert not any(x["type"] == "named_entity_without_evidence" for x in v2)


def test_narrative_rejects_overclaim():
    v = A.narrative_violations("これが完全に原因。機関投資家が完全に売りへ転換。")
    assert any(x["type"] == "overclaim" for x in v)


def test_narrative_rejects_short_vol_vs_interest():
    v = A.narrative_violations("空売り出来高の増加=空売り残高の急増")
    assert any(x["type"] == "short_volume_vs_interest" for x in v)


def test_narrative_rejects_future_earnings_as_cause():
    v = A.narrative_violations("決算が引き金", evidence=[{"kind": "earnings", "isFutureEvent": True}])
    assert any(x["type"] == "future_event_as_cause" for x in v)


# sector-wide peers override stock-specific narrative
def test_contagion_sector_wide():
    peers = [{"changePct": -4, "theme": "memory"}, {"changePct": -3, "theme": "memory"},
             {"changePct": -5, "theme": "memory"}, {"changePct": -0.2, "theme": "memory"}]
    out = A.classify_contagion("285A", peers)
    assert out["scope"] in ("sector_wide", "subsector_wide")


def test_contagion_company_specific():
    peers = [{"changePct": 0.5}, {"changePct": 0.3}, {"changePct": -0.1}, {"changePct": 0.8}]
    out = A.classify_contagion("285A", peers)
    assert out["scope"] == "company_specific"


def test_contagion_unconfirmed_without_peers():
    assert A.classify_contagion("285A", [])["scope"] == "unconfirmed"


# unknown probability remains when evidence is incomplete + sums to 1
def test_cause_probs_sum_to_one_unknown_nonzero():
    out = A.attribute_cause({"moveStartedAt": "2026-06-23T00:30:00Z"}, [])  # no evidence
    assert round(sum(out["causeProbabilities"].values()), 2) == 1.0
    assert out["unknownShare"] > 0
    assert out["immediateTrigger"] is None   # no valid trigger


# balanced report preserves bullish AND bearish claims (not monocausal)
def test_report_preserves_both_sides():
    text = ("足元の半導体決算は好調で恩恵が大きい。"
            "一方でAI設備投資のROIに懸念があり、catch-downのリスクもある。")
    out = A.analyze_report(text, source="JPM", title="AI capex", published_at="2026-06-20T00:00:00Z",
                           move_started_at="2026-06-23T00:30:00Z")
    assert out["bullishClaims"] and out["bearishClaims"]    # both preserved
    assert out["balanced"] is True
    assert out["dominantKeywordScoreRejected"] is True


def test_report_stale_is_background_not_trigger():
    out = A.analyze_report("懸念がある。", source="x", published_at="2026-06-18T00:00:00Z",
                           move_started_at="2026-06-23T00:30:00Z")
    assert out["backgroundVsTrigger"] == "background"


# no automatic trading surface
def test_no_order_surface():
    for bad in ("place_order", "execute", "submit_order", "buy", "sell", "broker"):
        assert not hasattr(A, bad)


def test_classify_news_buckets():
    import argus_attribution as A
    move = "2026-06-25T05:00:00Z"
    # non-official → UNCONFIRMED
    assert A.classify_news({"official": False}, move) == "UNCONFIRMED"
    # official, published right at the move, reliable → CONFIRMED (trigger)
    assert A.classify_news({"official": True, "publishedAt": "2026-06-25T05:00:00Z", "sourceReliability": 0.7}, move) == "CONFIRMED"
    # official, published AFTER the move → LIKELY_RELATED (amplifier)
    assert A.classify_news({"official": True, "publishedAt": "2026-06-25T06:00:00Z", "sourceReliability": 0.7}, move) == "LIKELY_RELATED"
    # official but stale (days before) w/o recirculation → BACKGROUND
    assert A.classify_news({"official": True, "publishedAt": "2026-06-20T00:00:00Z", "sourceReliability": 0.7}, move) == "BACKGROUND"
