"""ARGUS V12.1.7 — Benchmark Runner / 校正加速 / 2x Readinessの恒久ガード。

ベンチ実行はadmin/cron限定(公開不可)/外部AI不在=insufficient_data(偽passなし)/
校正計画(2ケース5run)/ケース別採点で弱い柱を特定/準備レポートは未校正を明示/
単発・不安定基準からの2x主張は構造不可。
"""
import os

import argus_osint_engine as oe
import scanner

WEB = os.path.join(os.path.dirname(__file__), "web", "src")
NOW = "2026-07-08T03:00:00Z"


def _read(*parts):
    return open(os.path.join(WEB, *parts), encoding="utf-8").read()


# ── Phase 6: ベンチケースの完全メタデータ ────────────────────────────────────

def test_all_10_cases_have_complete_metadata():
    assert len(oe.GEMINI_BENCHMARK_SUITE) == 10
    for c in oe.GEMINI_BENCHMARK_SUITE:
        for k in ("id", "name", "category", "investigationQuestionJa",
                  "expectedSourceCategories", "expectedClaimTypes",
                  "expectedForbiddenBehaviors", "primarySourceRequired",
                  "valueChainRequired", "officialCalendarRequired",
                  "scoringRubric", "ownerReadablePurposeJa",
                  "knownCaveats", "passFailConditions"):
            assert k in c, (c.get("case"), k)
        assert isinstance(c["expectedForbiddenBehaviors"], list)
        assert c["expectedForbiddenBehaviors"]


def test_benchmark_prompt_fixed_and_safe():
    for c in oe.GEMINI_BENCHMARK_SUITE:
        pr = oe.benchmark_prompt(c)
        assert "捏造禁止" in pr
        assert "売買指示はしない" in pr
        for banned in ("保有", "数量", "取得単価"):
            assert banned not in pr


# ── Phase 1/5: Runner安全性 ─────────────────────────────────────────────────

def test_public_route_cannot_trigger_benchmark():
    with scanner.app.test_client() as c:
        r = c.post("/api/argus/admin/osint/benchmark-run", json={})
        assert r.status_code in (401, 403, 503)


def test_benchmark_route_is_admin_only_in_source():
    src = open(os.path.join(os.path.dirname(__file__), "scanner.py"),
               encoding="utf-8").read()
    i = src.index("def api_argus_admin_osint_benchmark_run")
    body = src[i:i + 800]
    assert "_require_admin()" in body


def test_unavailable_gemini_gives_skipped_not_false_pass(monkeypatch):
    monkeypatch.setattr(scanner, "google_genai", None)
    scanner._OSINT_BENCHMARK_RUNS.clear()
    scanner._OSINT_BENCH_STATE["running"] = True
    try:
        scanner._osint_benchmark_worker(["cpi_official_schedule"])
    finally:
        scanner._OSINT_BENCH_STATE["running"] = False
    assert scanner._OSINT_BENCHMARK_RUNS
    rec = scanner._OSINT_BENCHMARK_RUNS[-1]
    assert rec["status"] == "skipped"
    assert "insufficient_data" in rec["ownerReadableJa"]


def test_duplicate_run_reuses_existing_job(monkeypatch):
    monkeypatch.setattr(scanner, "_require_admin", lambda: (True, None, 200))
    scanner._OSINT_BENCH_STATE["running"] = True
    try:
        with scanner.app.test_client() as c:
            r = c.post("/api/argus/admin/osint/benchmark-run", json={})
            assert r.status_code == 202
            assert r.get_json().get("duplicate") is True
    finally:
        scanner._OSINT_BENCH_STATE["running"] = False


def test_budget_visible():
    assert scanner._OSINT_BENCH_BUDGET["maxCasesPerInvocation"] == 2
    assert "Gemini" in scanner._OSINT_BENCH_BUDGET["maxCostLabel"]


# ── Phase 2: 校正計画 ───────────────────────────────────────────────────────

def test_5_runs_2_cases_can_calibrate_if_stable():
    runs = [{"score": 68, "case": "a"}, {"score": 70, "case": "a"},
            {"score": 66, "case": "b"}, {"score": 69, "case": "b"},
            {"score": 71, "case": "a"}]
    pl = oe.calibration_plan(runs)
    assert pl["currentRuns"] == 5 and pl["currentCasesCovered"] == 2
    assert pl["canClaim2x"] is True
    assert pl["remainingRuns"] == 0


def test_high_variance_blocks_confidence():
    runs = [{"score": 20, "case": "a"}, {"score": 95, "case": "a"},
            {"score": 30, "case": "b"}, {"score": 90, "case": "b"},
            {"score": 55, "case": "a"}]
    pl = oe.calibration_plan(runs)
    assert pl["canClaim2x"] is False
    assert pl["baselineConfidence"] in ("low", "unstable")


def test_progress_visible():
    pl = oe.calibration_plan([{"score": 72, "case": "6965"}])
    assert pl["progressPct"] == 20
    assert "あとGemini run" in pl["estimatedCompletionJa"]


# ── Phase 3: ケース別採点 ───────────────────────────────────────────────────

def _rps_like(score=92, pillars=None, blockers=None):
    return {"argusScore": score,
            "components": {"portfolioContextScore": 0,
                           "flowSupplyDemandContextScore": 5,
                           "eventContextScore": 0},
            "pillars": pillars or {"coverage": 15, "precision": 20, "reasoning": 6,
                                   "agenticCompletion": 8,
                                   "primarySourceStrength": 20},
            "blockersJa": blockers or []}


def test_case_with_blockers_cannot_be_2x():
    cs = oe.benchmark_case_score(
        oe.GEMINI_BENCHMARK_SUITE[0], [{"titleJa": "g"}],
        _rps_like(score=200, blockers=["具体ソース未回収"]))
    assert cs["status"] != "argus_2x"


def test_case_with_weak_pillar_cannot_be_2x():
    weak = {"coverage": 15, "precision": 20, "reasoning": 1,
            "agenticCompletion": 8, "primarySourceStrength": 20}
    cs = oe.benchmark_case_score(
        oe.GEMINI_BENCHMARK_SUITE[0], [{"titleJa": "g"}],
        _rps_like(score=200, pillars=weak))
    assert cs["status"] != "argus_2x"
    assert "reasoning" in cs["weakPillars"]


def test_case_owner_context_ratio_separated():
    cs = oe.benchmark_case_score(
        oe.GEMINI_BENCHMARK_SUITE[0], [{"titleJa": "g", "verified": True}],
        _rps_like())
    assert cs["publicRatio"] is not None and cs["contextRatio"] is not None
    assert cs["contextRatio"] >= cs["publicRatio"]


def test_case_insufficient_without_gemini():
    cs = oe.benchmark_case_score(oe.GEMINI_BENCHMARK_SUITE[0], [], _rps_like())
    assert cs["status"] == "insufficient_data"


# ── Phase 4: 2x Readiness Report ────────────────────────────────────────────

def test_readiness_not_calibrated_when_incomplete():
    rr = oe.two_x_readiness([{"score": 72, "case": "6965"}], [],
                            {"argusVsGeminiRatio": 1.28, "status": "below_gemini",
                             "blockersJa": [], "pillars": {}})
    assert rr["overallStatus"] == "not_calibrated"
    assert "未校正: Gemini runが不足" in rr["topBlockersJa"]


def test_readiness_gives_engineering_tasks():
    rr = oe.two_x_readiness(
        [{"score": 68, "case": "a"}, {"score": 70, "case": "a"},
         {"score": 66, "case": "b"}, {"score": 69, "case": "b"},
         {"score": 71, "case": "a"}], [],
        {"argusVsGeminiRatio": 1.3, "status": "below_gemini",
         "blockersJa": ["公式/業界一次情報が不足"],
         "pillars": {"coverage": 15, "precision": 20, "reasoning": 6,
                     "agenticCompletion": 8, "primarySourceStrength": 3}})
    assert rr["overallStatus"] == "calibrated_exceeds_but_not_2x"
    assert any("SEAJ公式PDF" in t for t in rr["recommendedNextEngineeringTasks"])


def test_readiness_no_fake_2x():
    # 校正済みでもRPSステータスがexceeds_gemini_2xでない限りcalibrated_2xにしない
    rr = oe.two_x_readiness(
        [{"score": 68, "case": "a"}, {"score": 70, "case": "a"},
         {"score": 66, "case": "b"}, {"score": 69, "case": "b"},
         {"score": 71, "case": "a"}], [],
        {"argusVsGeminiRatio": 2.5, "status": "exceeds_gemini",
         "blockersJa": ["Gemini基準が未校正"], "pillars": {}})
    assert rr["overallStatus"] != "calibrated_2x"


def test_readiness_insufficient_without_runs():
    rr = oe.two_x_readiness([], [], None)
    assert rr["overallStatus"] == "insufficient_data"


# ── Phase 7: UI/DQ/Pack ─────────────────────────────────────────────────────

def test_dq_shows_plan_readiness_benchmark():
    with scanner.app.test_client() as c:
        r = c.get("/api/argus/data-quality")
        oh = (r.get_json() or {}).get("osintHealth") or {}
        assert "calibrationPlan" in oh
        assert "twoXReadiness" in oh
        assert "benchmarkRunsSummary" in oh
        assert oh["benchmarkRunsSummary"]["budget"]["maxCasesPerInvocation"] == 2


def test_fe_dq_shows_progress():
    src = _read("routes", "DataQualityPage.tsx")
    assert "calibrationPlan" in src
    assert "twoXReadiness" in src
    assert "progressPct" in src


def test_pack_includes_readiness():
    src = _read("lib", "reviewPack.ts")
    assert "twoXReadinessJa" in src


def test_dq_no_leak_with_benchmark_fields():
    with scanner.app.test_client() as c:
        r = c.get("/api/argus/data-quality")
        body = r.get_data(as_text=True)
        for banned in ("quantity", "avgCost", "passphrase", "hmac",
                       "GEMINI_API_KEY", "OPENAI_API_KEY"):
            assert banned not in body
