"""ARGUS V12.1.6 ADDENDUM — Gemini基準校正の恒久ガード。

単発runは暫定(2x不可)/中央値基準/分散大=不安定/GeminiもARGUSと同一
ルーブリック(仮説は仮説・未検証は満点不可)/公開比と文脈強化比の分離/
2x=校正済み基準+confidence medium以上が必須。
"""
import os

import argus_osint_engine as oe
import scanner

WEB = os.path.join(os.path.dirname(__file__), "web", "src")
NOW = "2026-07-08T03:00:00Z"


def _read(*parts):
    return open(os.path.join(WEB, *parts), encoding="utf-8").read()


def _strong_kw():
    runs = [{"provider": "gemini", "status": "ok",
             "claims": [{"titleJa": "g1", "verified": True}]}]
    ver = [{"titleJa": "公式開示", "verificationStatus": "verified",
            "primaryEligible": True, "sourceType": "official_disclosure",
            "directness": "direct_company", "freshness": "today"}] * 8
    return dict(verified=ver, agent_runs=runs, gap_ledger=[],
                coverage={"totalCoverage": "strong", "sectorCoverage": "medium",
                          "valueChainCoverage": "medium"},
                contradiction=oe.contradiction_report(ver, runs),
                context_advantages=["需給文脈", "Flow文脈"], learning_updated=True,
                kwargs_recovery={"attempted": 2, "recovered": 2},
                primary_checks=[{"sourceCategory": "company_newsroom",
                                 "verifiedResultCount": 2}])


def _calibrated():
    return oe.baseline_from_runs([
        {"score": 68, "case": "a"}, {"score": 70, "case": "a"},
        {"score": 66, "case": "b"}, {"score": 69, "case": "b"},
        {"score": 71, "case": "a"}])


# ── Part A/F: 単発runは2x不可・暫定表示 ─────────────────────────────────────

def test_single_run_baseline_cannot_claim_2x():
    rps = oe.research_power_score(**_strong_kw())
    assert rps["argusVsGeminiRatio"] is not None
    assert rps["status"] != "exceeds_gemini_2x"
    assert rps["ratioConfidence"] == "provisional"
    assert "単発Gemini基準のため参考値" in rps["ratioLabelJa"]
    if rps["argusVsGeminiRatio"] >= 2.0:
        assert "Gemini基準が未校正" in rps["blockersJa"]


def test_calibrated_baseline_allows_2x():
    rps = oe.research_power_score(baseline_info=_calibrated(), **_strong_kw())
    assert rps["baselineType"] == "calibrated_baseline"
    if rps["argusVsGeminiRatio"] >= 2.0:
        assert rps["status"] == "exceeds_gemini_2x"
        assert "校正済み" in rps["ownerReadableVerdictJa"] or \
            rps["ratioConfidence"] in ("high", "medium")


def test_baseline_types_exist():
    for t in ("single_run", "median_of_runs", "fixed_benchmark_case",
              "rolling_case_average", "calibrated_baseline"):
        assert t in oe.BASELINE_TYPES
        assert t in oe.BASELINE_LABEL_JA


# ── Part B: 固定ベンチマークスイート ─────────────────────────────────────────

def test_benchmark_suite_has_10_cases_with_required_fields():
    assert len(oe.GEMINI_BENCHMARK_SUITE) == 10
    for c in oe.GEMINI_BENCHMARK_SUITE:
        for k in ("case", "investigationQuestion", "expectedSourceCategories",
                  "expectedClaimTypes", "expectedForbiddenBehavior",
                  "expectedPrimarySourceNeed", "scoringRubric"):
            assert k in c, (c.get("case"), k)
    cases = {c["case"] for c in oe.GEMINI_BENCHMARK_SUITE}
    for must in ("hamamatsu_seaj_optical", "samsung_anthropic_chip",
                 "pr_blocked_recovery", "no_news_unknown_cause"):
        assert must in cases


# ── Part C: 反復統計 ────────────────────────────────────────────────────────

def test_high_variance_lowers_confidence():
    stable = oe.baseline_stats([68, 70, 66, 69, 71])
    unstable = oe.baseline_stats([30, 90, 60, 20, 95])
    assert stable["baselineConfidence"] == "high"
    assert unstable["baselineConfidence"] in ("low", "unstable")


def test_median_used_over_single_run():
    b = _calibrated()
    assert b["medianGeminiScore"] == 69.0
    rps = oe.research_power_score(baseline_info=b, **_strong_kw())
    # 分母は中央値(displayに反映)
    assert "Gemini 69" in rps["displayJa"]


def test_zero_runs_unstable():
    b = oe.baseline_from_runs([])
    assert b["baselineType"] == "single_run"
    assert b["baselineConfidence"] == "unstable"


# ── Part E: 同一ルーブリック採点 ─────────────────────────────────────────────

def test_gemini_hypotheses_scored_as_hypotheses():
    concrete = [{"titleJa": f"記事{i}", "url": f"https://x.co/{i}",
                 "publishedAt": NOW} for i in range(3)]
    hyps = [{"titleJa": f"〜の可能性{i}"} for i in range(3)]
    assert oe.external_rubric_score(concrete) > oe.external_rubric_score(hyps)


def test_raw_count_does_not_dominate_gemini_score():
    few_verified = [{"titleJa": "g", "verified": True}] * 2
    many_hyps = [{"titleJa": f"〜の連想{i}"} for i in range(30)]
    assert oe.external_rubric_score(few_verified) > \
        oe.external_rubric_score(many_hyps)


def test_unverified_claim_not_full_credit():
    verified = [{"titleJa": "g", "verified": True}] * 3
    unverified_url = [{"titleJa": "g", "url": "https://x.co/a",
                       "publishedAt": NOW}] * 3
    assert oe.external_rubric_score(verified) > \
        oe.external_rubric_score(unverified_url)


# ── Part D: 公開比と文脈強化比の分離 ─────────────────────────────────────────

def test_public_ratio_separated_from_context_ratio():
    rps = oe.research_power_score(baseline_info=_calibrated(), **_strong_kw())
    assert rps["publicResearchRatio"] is not None
    assert rps["ownerContextEnhancedRatio"] is not None
    # 文脈成分(需給/Flow)が乗る分、文脈強化比 >= 公開比
    assert rps["ownerContextEnhancedRatio"] >= rps["publicResearchRatio"]


def test_prompt_version_recorded():
    b = oe.baseline_from_runs([{"score": 68, "case": "a"}])
    assert b["promptVersion"] == oe.SCOUT_PROMPT_VERSION
    assert b["inputContextVersion"]


# ── Part G: UI/DQ/Pack ──────────────────────────────────────────────────────

def test_ui_shows_provisional_label():
    src = _read("components", "dashboard", "OsintDeepDive.tsx")
    assert "ratioLabelJa" in src
    assert "publicResearchRatio" in src


def test_dq_shows_baseline_and_2x_allowance():
    with scanner.app.test_client() as c:
        r = c.get("/api/argus/data-quality")
        oh = (r.get_json() or {}).get("osintHealth") or {}
        gb = oh.get("geminiBaseline") or {}
        assert "baselineType" in gb
        assert "twoXClaimAllowed" in gb
        assert gb["twoXClaimAllowed"] in (True, False)


def test_pack_includes_baseline_method():
    src = _read("lib", "reviewPack.ts")
    assert "baselineJa" in src


def test_snapshot_carries_baseline_runs_public_safe():
    scanner._OSINT_BASELINE_RUNS.append(
        {"score": 68, "case": "6965", "symbol": "6965", "at": NOW,
         "promptVersion": oe.SCOUT_PROMPT_VERSION, "privacyMode": "redacted"})
    with scanner.app.test_client() as c:
        r = c.get("/api/argus/osint/memory-snapshot")
        d = r.get_json()
        assert any(x.get("case") == "6965" for x in (d.get("baselineRuns") or []))
        body = r.get_data(as_text=True)
        for banned in ("quantity", "avgCost", "passphrase", "hmac"):
            assert banned not in body
