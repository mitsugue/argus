"""ARGUS V12.2.8 FINAL AUDIT — 意味論欠陥修正の恒久ガード。"""
import argus_osint_engine as oe
import argus_remote_durability as rd
import scanner


def test_app_version_is_semantic_not_sha():
    v = scanner._semantic_app_version()
    assert v and v[0].isdigit() and "." in v        # 12.2.x形式
    with scanner.app.test_client() as c:
        d = c.get("/api/argus/data-quality").get_json() or {}
        assert d.get("appVersion") == v             # SHAではない
        b = d.get("buildIdentity") or {}
        assert b["appVersion"] == v
        assert b["frontendVersion"] == v
        # backendBuildShaはSHA枠(ローカルでは未設定=unknownでよい)
        assert b["appVersion"] != b["backendBuildSha"] or             b["backendBuildSha"] == "unknown"


def test_origin_unknown_legacy_not_fabricated():
    s = rd.decision_ledger_origin_summary(
        [{"id": "old1"}], [{"forecastId": "old1", "status": "resolved"}])
    assert s["forecastCounts"]["unknown_legacy"] == 1
    assert s["forecastCounts"]["forward_live"] == 0
    assert s["scoreEligibleOutcomeCount"] == 0      # legacyは採点対象外


def test_reliability_four_rates_with_supplied_numbers():
    r = rd.agent_reliability_rates(complete=6, recovered=5,
                                   scheduled_future=3, skipped_expected=5,
                                   total=19, missed_unrecovered=0,
                                   failed_safe=0)
    assert r["dueMissions"] == 11
    assert r["normalCompletionRate"]["percent"] == 55       # 6/11
    assert r["effectiveCompletionRate"]["percent"] == 100   # 11/11
    assert r["recoveryRate"]["percent"] == 100              # 5/5
    assert r["failureRate"]["percent"] == 0
    z = rd.agent_reliability_rates(complete=0, recovered=0,
                                   scheduled_future=1, skipped_expected=0,
                                   total=1, missed_unrecovered=0, failed_safe=0)
    assert z["normalCompletionRate"]["percent"] is None     # 分母0≠100%


def test_canary_diagnostic_stage():
    d = rd.canary_miss_diagnostic({"topic": "hamamatsu_optical_value_chain",
                                   "expectedKeywords": ["光半導体"],
                                   "foundByGemini": True, "foundByArgus": False})
    assert d["failureStage"] == "source_coverage"
    assert d["blocksConfidence"] is True
    ok = rd.canary_miss_diagnostic({"topic": "x", "foundByArgus": True})
    assert ok["failureStage"] is None


def test_gap_aggregate_traceable():
    ledger = [{"resolutionStatus": "still_unresolved_important",
               "resolutionReasonJa": "r1", "ownerReadableJa": "x"},
              {"resolutionStatus": "hypothesis_not_source"},
              {"resolutionStatus": "duplicate_existing"}]
    summ = oe.gap_ledger_summary(ledger)
    blocking = [g for g in ledger
                if g["resolutionStatus"] == "still_unresolved_important"]
    assert summ["unresolvedImportant"] == len(blocking) == 1


def test_holdout_contamination_flag():
    hold = [c for c in oe.GEMINI_BENCHMARK_SUITE if c.get("holdout")]
    tuned = [c for c in oe.GEMINI_BENCHMARK_SUITE if not c.get("holdout")]
    assert hold and tuned
    assert not any(c.get("holdout") and c.get("usedForTuning")
                   for c in oe.GEMINI_BENCHMARK_SUITE)
