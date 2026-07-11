"""ARGUS V12.2.8 ADDENDUM — 測定意味論/台帳origin/信頼性式/版同一性の恒久ガード。"""
import argus_remote_durability as rd
import scanner


def test_latest_and_stable_and_formal_are_distinct():
    s = rd.research_measurement_summary(
        latest={"symbol": "6965", "ratio": 1.50},
        stability={"runCount": 6, "medianRatio": 1.265, "confidence": "low",
                   "currentRatioEligible": False},
        unresolved_important=3, primary_strength=0,
        fresh_pending=4, canary_misses=1)
    ja = s["ownerReadableJa"]
    assert "最新run: 1.5" in ja and "安定中央値: 1.265" in ja
    assert "安定信頼度: low" in ja and "正式倍率認定: 不可" in ja
    assert "一次情報不足" in ja and "未回収ソース3件" in ja
    assert s["evidenceGate"]["status"] == "blocked"
    assert s["twoXReadinessGate"]["eligible"] is False


def test_raw_ratio_cannot_override_evidence_blockers():
    s = rd.research_measurement_summary(
        latest={"symbol": "X", "ratio": 2.5},
        stability={"runCount": 6, "medianRatio": 2.4, "confidence": "high",
                   "currentRatioEligible": True},
        unresolved_important=1, primary_strength=0,
        fresh_pending=0, canary_misses=0)
    assert s["twoXReadinessGate"]["eligible"] is False
    assert s["evidenceGate"]["status"] == "blocked"


def test_low_confidence_not_formally_eligible():
    s = rd.research_measurement_summary(
        latest=None,
        stability={"runCount": 6, "medianRatio": 1.2, "confidence": "low",
                   "currentRatioEligible": True},
        unresolved_important=0, primary_strength=10,
        fresh_pending=0, canary_misses=0)
    assert s["stableMeasurement"]["formallyEligible"] is False


def test_origin_summary_separates_live_replay():
    fc = [{"id": "a", "origin": "historical_replay"},
          {"id": "b", "origin": "historical_replay"}]
    oc = [{"forecastId": "a", "origin": "historical_replay",
           "status": "resolved"},
          {"forecastId": "b", "origin": "historical_replay",
           "status": "resolved"}]
    s = rd.decision_ledger_origin_summary(fc, oc)
    assert s["forecastCounts"]["forward_live"] == 0
    assert s["forecastCounts"]["historical_replay"] == 2
    assert s["scoreEligibleOutcomeCount"] == 0     # replayは採点対象外
    assert "Forward-live予測: 0件" in s["ownerReadableJa"]
    assert s["forecastCounts"]["total"] ==         sum(v for k, v in s["forecastCounts"].items() if k != "total")


def test_reliability_formula_and_denominator():
    ms = ([{"status": "complete", "scheduledFor": "2026-07-11T08:00:00+09:00"}] * 6
          + [{"status": "recovered", "scheduledFor": "x"}] * 5
          + [{"status": "scheduled",
              "scheduledFor": "2099-01-01T00:00:00+09:00"}] * 3
          + [{"status": "skipped", "scheduledFor": "x"}] * 5)
    s = rd.agent_reliability_summary(ms, now_iso="2026-07-11T12:00:00+09:00")
    assert s["completionRate"]["denominator"] == 11    # 19-未来3-skip5
    assert s["completionRate"]["percent"] == 100
    assert "失敗に数えない" in s["completionRate"]["formulaJa"]
    empty = rd.agent_reliability_summary([], now_iso="x")
    assert empty["completionRate"]["percent"] is None  # 分母0≠100%


def test_build_identity_no_fabrication():
    b = rd.build_identity(app_version="", backend_sha="", frontend_version="")
    assert b["consistency"] == "incomplete"
    assert b["appVersion"] == "unknown"
    m = rd.build_identity(app_version="12.2.8", backend_sha="abc",
                          frontend_version="12.2.7")
    assert m["consistency"] == "mismatch"


def test_recovery_requires_entity_and_date():
    orig = {"titleJa": "浜松ホトニクスがEmmi-Xカメラを発売",
            "publishedAt": "2026-07-08"}
    good = {"titleJa": "Emmi-X 発売 浜松ホトニクス ニュースルーム",
            "publishedAt": "2026-07-08"}
    unrelated = {"titleJa": "園芸フェアが発売", "publishedAt": "2026-07-08"}
    wrong_date = {"titleJa": "浜松ホトニクス Emmi-X",
                  "publishedAt": "2025-01-01"}
    assert rd.recovery_candidate_compatible(orig, good) is True
    assert rd.recovery_candidate_compatible(orig, unrelated) is False
    assert rd.recovery_candidate_compatible(orig, wrong_date) is False


def test_dq_addendum_blocks_no_leak():
    with scanner.app.test_client() as c:
        d = c.get("/api/argus/data-quality").get_json() or {}
        for k in ("researchMeasurementSummary", "decisionLedgerOrigins",
                  "agentReliability", "buildIdentity"):
            assert k in d, k
        assert "4概念は別物" in d["researchMeasurementSummary"]["semanticsJa"]
        assert d["appVersion"] != ""                   # 空文字の根治
        body = str(d)
        for banned in ("passphrase", "hmac", "quantity", "avgCost"):
            assert banned not in body
