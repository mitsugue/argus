"""Unit tests for the deterministic Research Dossier engine (argus_research.py)."""
import argus_research as rs


def _sum1(items):
    return abs(sum(p for _, p in items) - 1.0) < 0.01


def test_probability_groups_sum_to_one():
    cause = rs.probable_cause("PRICE_SPIKE", "SHORT_COVERING", True, "company_specific")
    scen = rs.next_session_scenarios("PRICE_SPIKE", "DISTRIBUTION")
    assert abs(sum(cause.values()) - 1.0) < 0.01
    assert abs(sum(scen.values()) - 1.0) < 0.01


def test_market_scope_is_honest():
    assert rs.market_scope(8.0, 0.2) == "company_specific"     # stock up, index flat
    assert rs.market_scope(2.0, 1.8) == "market_wide"          # moves together
    assert rs.market_scope(8.0, None) == "unconfirmed"         # no index → honest unknown


def test_news_raises_official_cause():
    with_news = rs.probable_cause("PRICE_SPIKE", None, True, "company_specific")
    without = rs.probable_cause("PRICE_SPIKE", None, False, "company_specific")
    assert with_news["official_catalyst"] > without.get("official_catalyst", 0)


def test_trap_risks_flag_distribution_and_squeeze():
    assert "distribution_into_strength" in rs.trap_risks("PRICE_SPIKE", "DISTRIBUTION", 60)
    assert "squeeze_exhaustion" in rs.trap_risks("LIMIT_UP", "SHORT_COVERING", 60)
    assert "overbought_gap_and_fade" in rs.trap_risks("PRICE_SPIKE", None, 80)


def test_posture_never_emits_trade_instruction():
    for et in ("PRICE_SPIKE", "PRICE_CRASH", "LIMIT_UP", "LIMIT_DOWN", "LIMIT_UP_PROXIMITY"):
        for flow in (None, "SHORT_COVERING", "DISTRIBUTION", "NEW_LONG_ACCUMULATION"):
            p = rs.research_posture(et, 5, "company_specific", flow, 0.7, "CAUTION")
            assert p in rs.RESEARCH_POSTURES
            assert p not in ("BUY", "SELL", "EXECUTE", "BUY NOW", "SELL NOW")


def test_low_confidence_or_reject_downgrades():
    assert rs.research_posture("PRICE_SPIKE", 5, "company_specific", None, 0.2) == "OBSERVE"
    assert rs.research_posture("LIMIT_UP", 5, "company_specific", None, 0.8, "REJECT") == "OBSERVE"


def test_adversarial_review_can_reject_and_caution():
    assert rs.adversarial_review("unconfirmed", None, False, 0.2, [])["verdict"] == "REJECT"
    assert rs.adversarial_review("company_specific", "NEW_LONG_ACCUMULATION", True, 0.7, [])["verdict"] == "ACCEPT"
    mid = rs.adversarial_review("unconfirmed", None, False, 0.5, [])
    assert mid["verdict"] == "CAUTION" and mid["objectionsJa"]


def test_build_dossier_shape_and_evidence_and_disclaimer():
    event = {"eventId": "e1", "eventType": "LIMIT_UP", "severity": 5, "symbol": "9999",
             "session": "JP_MORNING", "lifecycleState": "HIGH_ALERT", "eventVersion": 1,
             "reasonJa": "S高到達"}
    flow_inf = {"classification": "SHORT_COVERING",
                "probabilities": {"newLongAccumulation": 0.2, "shortCovering": 0.5,
                                  "distribution": 0.1, "retailNoise": 0.1, "unconfirmed": 0.1},
                "reasonsJa": ["貸株残縮小"]}
    evidence = [{"evidenceId": "ev1", "claimType": "derived_metric"},
                {"evidenceId": "ev2", "claimType": "news_report"}]
    d = rs.build_dossier(event=event, flow_inf=flow_inf, rsi=72, sym_chg=18.0, index_chg=0.3,
                         has_news=True, news_items=["材料: 上方修正"], evidence=evidence, asset_name="テスト")
    assert d["schemaVersion"] == "dossier-v1"
    assert d["researchPosture"] == "LIMIT_UP_RISK"
    assert _sum1([(c["label"], c["probability"]) for c in d["probableCause"]])
    assert _sum1([(s["label"], s["probability"]) for s in d["nextSessionScenarios"]])
    assert d["marketScope"] == "company_specific"
    assert d["disclaimerJa"] and "自動売買" in d["disclaimerJa"]
    assert d["engine"] == "deterministic"
    # every confirmed fact carries an evidenceIds field (may be empty but present)
    assert all("evidenceIds" in f for f in d["confirmedFacts"])


def test_missing_data_is_honest():
    event = {"eventId": "e2", "eventType": "PRICE_SPIKE", "severity": 4, "symbol": "9999",
             "lifecycleState": "VERIFIED", "reasonJa": "急騰"}
    d = rs.build_dossier(event=event, flow_inf=None, rsi=None, sym_chg=6.0, index_chg=None,
                         has_news=False, news_items=[], evidence=[])
    # no news, no index, no metrics → all three honestly listed as missing
    assert any("ニュース" in m or "開示" in m for m in d["missingData"])
    assert any("指数" in m for m in d["missingData"])
    assert any("テクニカル" in m for m in d["missingData"])
