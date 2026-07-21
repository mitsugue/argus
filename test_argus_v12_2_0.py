"""ARGUS V12.2.0 — AI Integrity / 校正エポック / 一次ソース支配 / 不変予測台帳の恒久ガード。"""
import os
import re
import sys
import types

import argus_ai_gate as gate
import argus_decision_ledger as dl
import argus_osint_engine as oe
import scanner

NOW = "2026-07-10T06:00:00Z"
ROOT = os.path.dirname(__file__)


# ── Phase 1: AI Integrity ───────────────────────────────────────────────────

def test_no_unapproved_direct_provider_calls():
    src = open(os.path.join(ROOT, "scanner.py"), encoding="utf-8").read()
    # 呼び出しサイトを関数単位で抽出し、承認リスト外の直接呼び出しを禁止
    funcs = re.split(r"\ndef |\n@app.route", src)
    bad = []
    for f in funcs:
        name = f.split("(", 1)[0].strip().lstrip("_apirgus_ ") or f[:30]
        fname = f.split("(", 1)[0].strip()
        if ("responses.create" in f or "chat.completions.create" in f
                or "generate_content" in f):
            if not any(a in fname or a in f[:200] for a in gate.APPROVED_CALL_SITES):
                bad.append(fname[:40])
    assert not bad, f"未承認の直接プロバイダ呼び出し: {bad}"


def test_every_responses_create_has_store_false():
    src = open(os.path.join(ROOT, "scanner.py"), encoding="utf-8").read()
    for m in re.finditer(r"responses\.create\((.{0,400}?)\)", src, re.S):
        arg = m.group(1)
        if "**kw" in arg:
            # kw辞書構築側で "store": False が指定されていること
            window = src[max(0, m.start() - 800):m.start()]
            assert '"store": False' in window, "kw構築にstore=Falseなし"
        else:
            assert "store=False" in arg, arg[:120]


def test_model_only_cannot_be_evidence_or_benchmark():
    r = gate.ai_execution_result(provider="openai", model="m", role="standard",
                                 mode="research", status="model_only",
                                 started_at=NOW, completed_at=NOW)
    assert r["evidenceEligible"] is False
    assert r["benchmarkEligible"] is False
    assert "モデル記憶" in r["noteJa"]


def test_search_failed_and_degraded_ineligible():
    r = gate.ai_execution_result(provider="openai", model="m", role="standard",
                                 mode="research", status="search_failed",
                                 started_at=NOW, completed_at=NOW)
    assert r["evidenceEligible"] is False
    r2 = gate.ai_execution_result(provider="openai", model="m", role="standard",
                                  mode="research", status="ok",
                                  started_at=NOW, completed_at=NOW,
                                  fallback_used=True)
    assert r2["benchmarkEligible"] is False


def test_unknown_price_fails_closed():
    g = gate.can_execute_external("gpt-99-unknown", {"gpt-4o": {"in": 1, "out": 2}})
    assert g["allowed"] is False and "fail-closed" in g["reasonJa"]
    g2 = gate.can_execute_external("gpt-4o", {"gpt-4o": {"in": 1, "out": 2}})
    assert g2["allowed"] is True


def test_budget_reservation():
    r = gate.reserve_budget(day_spent=4.9, day_budget=5.0, estimated_max_cost=0.5)
    assert r["allowed"] is False
    r2 = gate.reserve_budget(day_spent=1.0, day_budget=5.0, estimated_max_cost=0.5)
    assert r2["allowed"] is True


# ── Phase 2: エポック/シャドウ ──────────────────────────────────────────────

def test_epoch_separation():
    e1 = gate.model_epoch_id(provider="gemini", model="a", prompt_version="p1",
                             tool_mode="grounding")
    e2 = gate.model_epoch_id(provider="gemini", model="a", prompt_version="p2",
                             tool_mode="grounding")
    assert e1 != e2
    runs = [{"score": 1, "epochId": e1}, {"score": 2, "epochId": e2},
            {"score": 3}]
    assert len(gate.filter_runs_to_epoch(runs, e1, legacy_epoch_id=e1)) == 2


def test_shadow_sampling_deterministic():
    assert gate.shadow_should_sample("k1", 0) is False
    assert gate.shadow_should_sample("k1", 100) is True
    assert gate.shadow_should_sample("k1", 50) == gate.shadow_should_sample("k1", 50)


def test_capability_probe_admin_only():
    with scanner.app.test_client() as c:
        r = c.post("/api/argus/admin/ai/capability-probe", json={})
        assert r.status_code in (401, 403, 503)


def test_openai_capability_probe_separates_response_from_exact_text(monkeypatch):
    authorized = []
    recorded = []
    response = types.SimpleNamespace(
        output_text="acknowledged",
        model="gpt-5.6-sol",
        usage=types.SimpleNamespace(input_tokens=5, output_tokens=3))
    client = types.SimpleNamespace(
        responses=types.SimpleNamespace(create=lambda **kwargs: response))
    monkeypatch.setitem(
        sys.modules, "openai",
        types.SimpleNamespace(OpenAI=lambda **kwargs: client))
    monkeypatch.setattr(scanner, "_OPENAI_API_KEY", "configured-test-key")
    monkeypatch.setattr(
        scanner, "_cost_policy_authorize",
        lambda provider, purpose, **kwargs: (
            authorized.append((provider, purpose)) or {"allowed": True}))
    monkeypatch.setattr(
        scanner, "_cost_policy_record",
        lambda provider, purpose, **kwargs: recorded.append((provider, purpose)))

    probe = scanner._ai_capability_probe(
        "gpt-5.6-sol", confirmation=True, expected_text="ARGUS_SOL_OK",
        purpose="research_benchmark")

    assert probe["accessible"] is True
    assert probe["responseTextPresent"] is True
    assert probe["matchedExpectedText"] is False
    assert probe["usageReturned"] is True
    assert probe["responseModel"] == "gpt-5.6-sol"
    assert authorized == [("openai", "research_benchmark")]
    assert recorded == [("openai", "research_benchmark")]


def test_v2_capability_probe_requires_response_usage_model_and_no_error():
    valid = {"accessible": True, "responseTextPresent": True,
             "usageReturned": True,
             "responseModel": "gpt-5.6-sol", "errorClass": None}
    assert scanner._v2_capability_probe_passed(valid) is True
    for missing in ("responseTextPresent", "usageReturned", "responseModel"):
        row = dict(valid)
        row[missing] = False if missing != "responseModel" else None
        assert scanner._v2_capability_probe_passed(row) is False
    assert scanner._v2_capability_probe_passed(
        {**valid, "errorClass": "PermissionDenied"}) is False

    gemini = {"apiEndpoint": "models.generateContent", "accessible": False,
              "matchedExpectedText": False, "nonEmptyTextPartExists": True,
              "candidates": [{"finishReason": "STOP"}],
              "promptFeedback": {"blockReason": None},
              "usageReturned": True,
              "responseModel": "gemini-3.1-pro-preview", "errorClass": None}
    assert scanner._v2_capability_probe_passed(gemini) is True
    assert scanner._v2_capability_probe_passed(
        {**gemini, "candidates": [{"finishReason": "MAX_TOKENS"}]}) is False


def test_v2_preflight_failure_does_not_consume_calibration_attempt():
    preflight_only = {"status": "v2_provider_preflight_failed",
                      "calibrationAttemptCount": 3, "calibrationRuns": [],
                      "frozenRun": None, "holdoutConsumedBy": None}
    assert scanner._v2_next_calibration_attempt(preflight_only) == 1
    calibration_failed = {**preflight_only,
                          "status": "v2_argus_transport_failed",
                          "calibrationAttemptCount": 1}
    assert scanner._v2_next_calibration_attempt(calibration_failed) == 2


def test_v2_remote_journal_gate_uses_verified_receipt_not_auxiliary_flag():
    verified = {"readBackVerified": True, "remoteCommitSha": "a" * 40,
                "expectedHash": "b" * 16, "actualHash": "b" * 16}
    assert scanner._v2_remote_journal_verified(verified) is True
    assert scanner._v2_remote_journal_verified(
        {**verified, "actualHash": "c" * 16}) is False
    assert scanner._v2_remote_journal_verified(
        {**verified, "readBackVerified": False}) is False


# ── Phase 5/10: 2xゲート(cold/budget/degraded/holdout) ──────────────────────

def _strong():
    runs = [{"provider": "gemini", "status": "ok",
             "claims": [{"titleJa": "g", "verified": True}]}]
    ver = [{"titleJa": "公式開示", "verificationStatus": "verified",
            "primaryEligible": True, "sourceType": "official_disclosure",
            "directness": "direct_company", "freshness": "today"}] * 8
    b = oe.baseline_from_runs([{"score": 68, "case": "a"}, {"score": 70, "case": "a"},
                               {"score": 66, "case": "b"}, {"score": 69, "case": "b"},
                               {"score": 71, "case": "a"}])
    return dict(verified=ver, agent_runs=runs, gap_ledger=[],
                coverage={"totalCoverage": "strong", "sectorCoverage": "medium",
                          "valueChainCoverage": "medium"},
                contradiction=oe.contradiction_report(ver, runs),
                context_advantages=["需給文脈", "Flow文脈"], learning_updated=True,
                kwargs_recovery={"attempted": 2, "recovered": 2},
                primary_checks=[{"sourceCategory": "company_newsroom",
                                 "verifiedResultCount": 2}],
                baseline_info=b)


def test_cold_store_blocks_2x():
    rps = oe.research_power_score(
        warmth={"storeWarmth": "cold"}, **_strong())
    assert rps["status"] != "exceeds_gemini_2x"
    assert any("cold-store" in b for b in rps["blockersJa"])


def test_budget_limited_and_degraded_block_2x():
    r1 = oe.research_power_score(budget_limited=True, **_strong())
    assert r1["status"] != "exceeds_gemini_2x"
    r2 = oe.research_power_score(degraded_fallback=True, **_strong())
    assert r2["status"] != "exceeds_gemini_2x"


def test_official_doc_metadata_partial_credit():
    kw = _strong()
    r0 = oe.research_power_score(**kw)
    r1 = oe.research_power_score(
        official_docs=[{"verificationStatus": "metadata_only"}] * 2,
        pairings=1, **kw)
    assert r1["pillars"]["primarySourceStrength"] > r0["pillars"]["primarySourceStrength"]


def test_holdout_cases_marked():
    hs = [c for c in oe.GEMINI_BENCHMARK_SUITE if c.get("holdout")]
    assert len(hs) == 3
    assert oe.RUBRIC_VERSION


# ── ADDENDUM Phase A: 不変予測台帳 ──────────────────────────────────────────

def _fc(**kw):
    d = dict(symbol="6965", market="JP", issued_at=NOW, horizon="next_session",
             target_type="catalyst_verdict", forecast_value="unknown",
             now_iso=NOW)
    d.update(kw)
    return dl.forecast_record(**d)


def test_forecast_integrity_hash_and_no_mutation():
    rec = _fc()
    assert rec and dl.verify_forecast_integrity(rec)
    rec2 = dict(rec)
    rec2["forecastValue"] = "改ざん"
    assert not dl.verify_forecast_integrity(rec2)


def test_forecast_rejects_outcome_fields_and_lookahead():
    assert _fc(endPrice=100.0) is None
    assert _fc(outcome="up") is None
    assert dl.forecast_record(symbol="6965", market="JP",
                              issued_at="2026-07-11T00:00:00Z",
                              horizon="1d", target_type="direction",
                              forecast_value="up", now_iso=NOW) is None


def test_forecast_update_creates_new_record():
    a = _fc()
    b = _fc(forecast_value="up", supersedes=a["id"])
    assert b["id"] != a["id"] and b["supersedesForecastId"] == a["id"]


# ── ADDENDUM Phase B/C: 成果解決+適正スコア ─────────────────────────────────

def test_missing_price_is_unresolved_not_zero():
    o = dl.outcome_record(forecast=_fc(), outcome_as_of=NOW,
                          start_price=None, end_price=None)
    assert o["status"] == "unresolved"
    assert "absoluteReturnPct" not in o


def test_relative_returns_separated():
    o = dl.outcome_record(forecast=_fc(), outcome_as_of=NOW,
                          start_price=100.0, end_price=103.0,
                          benchmark_return=1.0, sector_return=2.0)
    assert o["absoluteReturnPct"] == 3.0
    assert o["benchmarkRelativeReturnPct"] == 2.0
    assert o["sectorRelativeReturnPct"] == 1.0


def test_proper_scoring_families():
    assert dl.brier_score(0.8, True) == 0.04
    assert dl.interval_coverage(-1, 2, 1.5) is True
    assert dl.balanced_accuracy(8, 6, 4, 2) == 0.7
    assert dl.precision_at_k([True, False, True], 2) == 0.5
    sa = dl.selective_accuracy(8, 10, 5)
    assert sa["selectiveAccuracy"] == 0.8 and sa["coverage"] < 1.0


def test_calibration_shrinkage_no_one_sample_swing():
    c1 = dl.calibration_state(band="70-80", sample_count=1, observed_freq=0.0,
                              stated_prob=0.75)
    assert c1["confidenceLevel"] == "insufficient"
    assert c1["shrunkFrequency"] > 0.4        # 1件の失敗で0に振れない(縮約)
    assert c1["noteJa"] == "履歴不足"


# ── ADDENDUM Phase E/F: 誤り帰属+学習提案 ───────────────────────────────────

def test_error_attribution_taxonomy():
    e = dl.error_attribution(forecast_id="f", outcome_id="o",
                             error_types=["missed_news", "bogus_type"])
    assert e["errorTypes"] == ["missed_news"]
    assert "幸運な結果" in e["lucky_outcome_note"]


def test_one_sample_cannot_change_production():
    p = dl.learning_proposal(proposal_type="priority_threshold",
                             proposed_change="閾値を下げる", sample_count=1)
    assert p["status"] == "rejected"
    p2 = dl.learning_proposal(proposal_type="priority_threshold",
                              proposed_change="閾値を下げる", sample_count=30)
    assert p2["status"] == "proposed" and p2["ownerApprovalRequired"] is True
    assert dl.can_promote(p2, owner_approved=False, holdout_passed=True) is False
    assert dl.can_promote(p2, owner_approved=True, holdout_passed=True) is True


def test_query_expansion_auto_safe():
    p = dl.learning_proposal(proposal_type="query_expansion",
                             proposed_change="SEAJ 販売高", sample_count=1)
    assert p["canAutoPromote"] is True


# ── ADDENDUM Phase I: ジョブ台帳 ────────────────────────────────────────────

def test_job_idempotency_and_missed_detection():
    jobs = [dl.job_record(job_id="j1", mission_type="snapshot",
                          scheduled_at="2026-07-09T00:00:00Z",
                          idempotency_key="k1")]
    assert dl.is_duplicate_job(jobs, "k1") is True
    assert dl.detect_missed_jobs(jobs, NOW) == ["j1"]
    jobs[0]["status"] = "complete"
    assert dl.detect_missed_jobs(jobs, NOW) == []


# ── 統合: DQ+スナップショットルート+非漏洩 ─────────────────────────────────

def test_dq_exposes_integrity_cost_ledger():
    with scanner.app.test_client() as c:
        d = c.get("/api/argus/data-quality").get_json() or {}
        assert "aiIntegrity" in d and "providerCost" in d
        assert "decisionLedger" in d
        assert d["aiIntegrity"]["storeDisabledEnforced"] is True
        assert d["providerCost"]["modelEpoch"]
        body = str(d)
        for banned in ("passphrase", "hmac", "GEMINI_API_KEY", "OPENAI_API_KEY",
                       "quantity", "avgCost"):
            assert banned not in body


def test_dl_snapshot_admin_only():
    with scanner.app.test_client() as c:
        r = c.post("/api/argus/admin/decision-ledger/snapshot", json={})
        assert r.status_code in (401, 403, 503)


def test_osint_build_has_warmth_docs_disclosure():
    scanner._OSINT_AGENT_QUEUE.clear()
    scanner._OSINT_PROGRESS.clear()
    inv = scanner._osint_build(
        "6965", "JP", "deep", "redacted", "owner_request",
        [{"provider": "gemini", "status": "ok", "claims": [
            {"titleJa": "半導体・FPD製造装置需要予測",
             "url": "https://www.seaj.or.jp/file/forecastforpress2026.pdf",
             "publishedAt": NOW}]}], NOW)
    assert inv["storeWarmth"]["storeWarmth"] in oe.WARMTH_LEVELS
    assert isinstance(inv["officialDocuments"], list)
    assert inv["disclosureCheck"]["status"] in ("checked", "unavailable")
    assert inv["researchPower"]["status"] in oe.RPS_STATUSES
