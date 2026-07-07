"""ARGUS V12.1.3 — 2x Research Power Engineの恒久ガード。

SEAJ/業界統計ギャップ閉鎖 / ResearchPowerScore(生件数で2x不可・未回収は即未達) /
ソースユニバース可視化(沈黙省略の禁止) / 価値連鎖規則(テーマ→direct昇格禁止) /
Autopilot 14段階+failed_safe / 矛盾規律 / 学習v2(useCase必須)。
"""
import os

import argus_osint_engine as oe
import scanner

WEB = os.path.join(os.path.dirname(__file__), "web", "src")
NOW = "2026-07-08T03:00:00Z"


def _read(*parts):
    return open(os.path.join(WEB, *parts), encoding="utf-8").read()


# ── Phase 1: SEAJ/業界統計ギャップ閉鎖 ──────────────────────────────────────

def test_seaj_query_expansion_generated():
    prof = scanner._osint_profile("6965", "JP")
    plan = oe.build_query_plan(prof)
    joined = " ".join(plan.get("all", []))
    assert "SEAJ" in joined
    assert "半導体製造装置" in joined


def test_industry_association_source_type_supported():
    assert "industry_association" in oe.SOURCE_TYPES
    assert "industry_forecast" in oe.SOURCE_TYPES
    assert oe.industry_source_type("SEAJ") == "industry_association"
    assert oe.industry_source_type("SEAJ", "半導体製造装置 販売高予測") == "industry_forecast"
    assert oe.industry_source_type("日本半導体製造装置協会", "2026年度予測") == "industry_forecast"
    assert oe.industry_source_type("Reuters") is None


def test_verify_source_tags_industry_source():
    v = oe.verify_source({"titleJa": "SEAJ 半導体製造装置 販売高予測 2026",
                          "sourceName": "SEAJ", "publishedAt": NOW},
                         {}, NOW)
    assert v["sourceType"] == "industry_forecast"


def test_theme_only_no_pointer_is_low_value_background():
    g = oe.resolve_gap({"titleJa": "半導体製造装置サイクルは中期的に拡大するとの見方",
                        "directness": "sector_theme"},
                       "gemini", [], symbol="6965",
                       investigation_id="inv1", now_iso=NOW)
    assert g["resolutionStatus"] == "low_value_background"
    assert g["resolutionReasonJa"]


def test_unresolved_gap_must_have_exact_reason():
    # どの経路でもresolutionReasonJa空のギャップは作れない
    for claim in (
        {"titleJa": "SEAJ予測", "url": "https://seaj.example.org/f", "publishedAt": NOW},
        {"titleJa": "何かのテーマ話", "directness": "sector_theme"},
        {"titleJa": "古い記事", "publishedAt": "2026-01-01T00:00:00Z"},
    ):
        g = oe.resolve_gap(claim, "gemini", [], symbol="6965",
                           investigation_id="inv1", now_iso=NOW)
        assert g["resolutionStatus"] in oe.RESOLUTION_STATUSES
        assert str(g["resolutionReasonJa"]).strip()


# ── Phase 4/6: 価値連鎖規則+テーマはdirect_companyに昇格しない ──────────────

def test_value_chain_rule_semiconductor_equipment():
    vc = oe.value_chain_context("SEAJ 半導体製造装置 販売高予測")
    assert vc and vc["theme"] == "semiconductor_equipment"
    assert "direct_company" in vc["cautionJa"] or "個社" in vc["cautionJa"]


def test_value_chain_context_never_fabricates():
    assert oe.value_chain_context("全く関係ない園芸の話") is None


def test_broad_equipment_theme_cannot_become_direct_company():
    # 業界予測(directness未主張)がdirect_companyに昇格しないこと
    v = oe.verify_source({"titleJa": "半導体製造装置の需要は2026年も拡大へ 業界予測",
                          "sourceName": "SEAJ", "publishedAt": NOW}, {}, NOW)
    assert v["directness"] != "direct_company"
    # sector_theme主張はsector_themeのまま(勝手に格上げしない)
    v2 = oe.verify_source({"titleJa": "半導体製造装置サイクル拡大", "sourceName": "SEAJ",
                           "publishedAt": NOW, "directness": "sector_theme"}, {}, NOW)
    assert v2["directness"] == "sector_theme"


# ── Phase 2: Research Power Score ───────────────────────────────────────────

def _runs(n_gem=3, verified=False):
    return [{"provider": "gemini", "status": "ok",
             "claims": [{"titleJa": f"g{i}", "verified": verified} for i in range(n_gem)]}]


def test_rps_raw_count_cannot_reach_2x():
    # 未検証50件を積んでも2xにならない(生件数で2x不可)
    raw = [{"titleJa": f"x{i}", "verificationStatus": "metadata_only",
            "primaryEligible": False} for i in range(50)]
    cr = oe.contradiction_report(raw, _runs())
    rps = oe.research_power_score(
        verified=raw, agent_runs=_runs(), gap_ledger=[],
        coverage={"totalCoverage": "strong"}, contradiction=cr,
        context_advantages=[], learning_updated=False)
    assert rps["status"] != "exceeds_gemini_2x"
    assert rps["blockersJa"]


def test_rps_unresolved_important_forces_below():
    ledger = [{"resolutionStatus": "still_unresolved_important",
               "resolutionReasonJa": "追撃3回でも公開ソース到達不可"}]
    ver = [{"titleJa": "公式開示", "verificationStatus": "verified",
            "primaryEligible": True, "directness": "direct_company",
            "sourceType": "official_disclosure"}] * 6
    cr = oe.contradiction_report(ver, _runs(verified=True))
    rps = oe.research_power_score(
        verified=ver, agent_runs=_runs(verified=True), gap_ledger=ledger,
        coverage={"totalCoverage": "strong"}, contradiction=cr,
        context_advantages=["需給文脈", "Flow文脈"], learning_updated=True)
    assert rps["status"] == "below_gemini"


def test_rps_insufficient_data_without_agents():
    rps = oe.research_power_score(
        verified=[], agent_runs=[{"provider": "deterministic", "status": "ok"}],
        gap_ledger=[], coverage={}, contradiction={}, context_advantages=[])
    assert rps["status"] == "insufficient_data"
    assert rps["statusJa"] == "判定保留"


def test_rps_has_14_components_and_display():
    ver = [{"titleJa": "公式開示", "verificationStatus": "verified",
            "primaryEligible": True, "directness": "direct_company",
            "sourceType": "official_disclosure", "freshness": "today"}] * 4
    cr = oe.contradiction_report(ver, _runs(verified=True))
    rps = oe.research_power_score(
        verified=ver, agent_runs=_runs(verified=True), gap_ledger=[],
        coverage={"totalCoverage": "strong", "sectorCoverage": "medium",
                  "valueChainCoverage": "medium"},
        contradiction=cr, context_advantages=["需給文脈"], learning_updated=True)
    assert len(rps["components"]) == 14
    assert "Gemini" in rps["displayJa"] and "ARGUS" in rps["displayJa"]
    assert rps["status"] in oe.RPS_STATUSES
    assert rps["argusVsGeminiRatio"] is None or rps["argusVsGeminiRatio"] > 0


# ── Phase 3: ソースユニバース(沈黙省略の禁止) ───────────────────────────────

def test_source_universe_has_18_categories_and_unavailable_visible():
    u = oe.source_universe_status(agents_configured=True)
    assert len(u) == 18
    unavail = [x for x in u if x["availability"] == "unavailable"]
    assert unavail, "unavailableカテゴリも必ず可視化"
    for x in unavail:
        assert x["noteJa"], "unavailableには理由必須(沈黙省略の禁止)"


def test_source_universe_agents_not_configured_visible():
    u = oe.source_universe_status(agents_configured=False)
    assert any(x["availability"] == "agents_not_configured" for x in u)


# ── Phase 5: Autopilot 14段階+failed_safe ───────────────────────────────────

def test_autopilot_has_14_stages():
    assert len(oe.AUTOPILOT_STAGES) == 14


def test_autopilot_completed_only_when_all_done():
    ap = oe.autopilot_progress([k for k, _ in oe.AUTOPILOT_STAGES])
    assert ap["status"] == "completed"
    ap2 = oe.autopilot_progress(["profile"])
    assert ap2["status"] == "running" and ap2["currentStageJa"]


def test_autopilot_failed_safe_never_claims_completion():
    ap = oe.autopilot_progress(["profile", "query_plan"],
                               failed_stage="scout_gemini",
                               fail_reason_ja="provider timeout")
    assert ap["status"] == "failed_safe"
    assert ap["failReasonJa"]
    assert any(s["state"] == "failed" for s in ap["stages"])


# ── Phase 6: 矛盾・因果規律 ─────────────────────────────────────────────────

def test_contradiction_theme_only_warns():
    ver = [{"titleJa": "テーマ話", "verificationStatus": "verified",
            "primaryEligible": True, "directness": "sector_theme"}]
    cr = oe.contradiction_report(ver, [])
    assert cr["themeInferenceOnly"] is True
    assert cr["directEvidenceAbsent"] is True
    assert any("事実として扱わない" in w for w in cr["ownerReadableWarningsJa"])


def test_contradiction_price_only_narrative_risk():
    cr = oe.contradiction_report([], [], flow_only=True)
    assert cr["priceOnlyNarrativeRisk"] is True
    assert any("価格変動それ自体は原因ではない" in w for w in cr["ownerReadableWarningsJa"])


# ── Phase 7: 学習v2(useCase必須) ────────────────────────────────────────────

def test_memory_v2_requires_valid_use_case():
    assert oe.memory_record_v2(symbol="6965", use_case="invalid",
                               now_iso=NOW) is None
    m = oe.memory_record_v2(symbol="6965", use_case="theme_rule",
                            theme="半導体製造装置", learned_from="deterministic",
                            verified=True, now_iso=NOW)
    assert m and m["useCase"] == "theme_rule" and m["v"] == 2
    assert m["privacyLevel"] == "public_safe"


# ── Phase 8/9: 統合(scanner/FE)+非漏洩 ─────────────────────────────────────

def test_osint_build_includes_research_power(monkeypatch):
    scanner._OSINT_AGENT_QUEUE.clear()
    scanner._OSINT_PROGRESS.clear()
    inv = scanner._osint_build(
        "6965", "JP", "deep", "redacted", "owner_request",
        [{"provider": "gemini", "status": "ok", "claims": [
            {"titleJa": "SEAJ 半導体製造装置 販売高予測", "sourceName": "SEAJ",
             "publishedAt": NOW}]}], NOW)
    rp = inv.get("researchPower")
    assert rp and rp["status"] in oe.RPS_STATUSES
    # 旧contradictionReport(string[])はFE互換のためそのまま・V2は別キー
    assert isinstance(inv.get("contradictionReport"), list)
    assert isinstance(inv.get("contradictionReportV2"), dict)
    assert isinstance(inv.get("sourceUniverse"), list) and len(inv["sourceUniverse"]) == 18
    # 価値連鎖規則(6965は半導体製造装置テーマを持つ)
    assert (inv.get("valueChainContext") or {}).get("theme") == "semiconductor_equipment"


def test_investigation_get_exposes_research_power_without_leak():
    scanner._OSINT_AGENT_QUEUE.clear()
    scanner._OSINT_PROGRESS.clear()
    with scanner.app.test_client() as c:
        r = c.get("/api/argus/osint/investigation?symbol=6965")
        assert r.status_code == 200
        body = r.get_data(as_text=True)
        for banned in ("quantity", "avgCost", "acquisitionPrice", "passphrase",
                       "GEMINI_API_KEY", "OPENAI_API_KEY", "hmac"):
            assert banned not in body


def test_dq_osint_health_has_universe_and_rps():
    with scanner.app.test_client() as c:
        r = c.get("/api/argus/data-quality")
        assert r.status_code == 200
        oh = (r.get_json() or {}).get("osintHealth") or {}
        su = oh.get("sourceUniverse") or {}
        assert su.get("total") == 18
        assert su.get("unavailable", 0) >= 1
        assert "researchPowerLatest" in oh


def test_autopilot_wired_in_worker_progress():
    src = open(os.path.join(os.path.dirname(__file__), "scanner.py"),
               encoding="utf-8").read()
    assert "_osint_autopilot_mark" in src
    assert "_osint_autopilot_fail" in src
    assert 'use_case="source_discovery"' in src
    assert 'use_case="query_expansion"' in src
    assert 'use_case="theme_rule"' in src


# ── Phase 8: FE(Research Powerチップ+比率表示) ─────────────────────────────

def test_fe_shows_research_power_ratio():
    src = _read("components", "dashboard", "OsintDeepDive.tsx")
    assert "researchPower" in src
    assert "displayJa" in src


def test_fe_dq_shows_source_universe():
    src = _read("routes", "DataQualityPage.tsx")
    assert "sourceUniverse" in src


def test_review_pack_includes_research_power():
    src = _read("lib", "reviewPack.ts")
    assert "researchPower" in src
