"""ARGUS V12.1.5 — 一次ソース取得/SEAJ・業界予測resolver/因果関連度の恒久ガード。

未チェックカテゴリの「不在」主張禁止 / SEAJ公式=industry_forecast(捏造なし) /
製品発表=直接ニュースでも自動的に主因にしない / 2x=一次ソース強度or例外的
検証カバレッジ必須 / 曖昧な「原因未特定」を出さない結論。
"""
import os

import argus_osint_engine as oe
import scanner

WEB = os.path.join(os.path.dirname(__file__), "web", "src")
NOW = "2026-07-08T03:00:00Z"


def _read(*parts):
    return open(os.path.join(WEB, *parts), encoding="utf-8").read()


def _prof():
    return {"symbol": "6965", "nameJa": "浜松ホトニクス",
            "nameEn": "Hamamatsu Photonics", "sector": "光半導体",
            "themes": ["光半導体", "半導体製造装置"], "valueChain": [],
            "competitors": ["ソニー"], "queryExpansions": []}


def _runs(verified=True):
    return [{"provider": "gemini", "status": "ok",
             "claims": [{"titleJa": "g1", "verified": verified}]}]


# ── Phase 1: Primary Source Acquisition ─────────────────────────────────────

def test_primary_source_check_object_created():
    plan = {"all": ["浜松ホトニクス IR", "浜松ホトニクス ニュース",
                    "浜松ホトニクス 製品発表", "SEAJ 販売高 予測"]}
    checks = oe.primary_source_checks(_prof(), plan, [], {"official": 0})
    assert len(checks) == 12
    for c in checks:
        assert c["status"] in ("verified", "metadata_only", "unavailable",
                               "failed", "not_checked")
        assert c["ownerReadableJa"]


def test_unchecked_official_blocks_absence_claim():
    checks = oe.primary_source_checks(_prof(), {"all": []}, [], {},
                                      events_checked=False)
    guards = oe.primary_absence_guards(checks)
    assert any("直接材料なしとは言えない" in g for g in guards)
    assert any("業界材料なしとは言えない" in g for g in guards)


def test_verified_official_industry_increases_score():
    ver_ind = [{"titleJa": "SEAJ予測", "verificationStatus": "verified",
                "primaryEligible": True, "sourceType": "industry_forecast",
                "directness": "sector_theme", "freshness": "today"}]
    kw = dict(agent_runs=_runs(), gap_ledger=[],
              coverage={"totalCoverage": "medium"},
              context_advantages=[], learning_updated=False)
    r0 = oe.research_power_score(verified=[], contradiction={}, **kw)
    r1 = oe.research_power_score(verified=ver_ind,
                                 contradiction=oe.contradiction_report(ver_ind, _runs()), **kw)
    assert r1["argusScore"] > r0["argusScore"]
    assert r1["pillars"]["primarySourceStrength"] > 0


def test_unrelated_official_source_rejected():
    # 無関係な公式ソースはirrelevant(因果でも使えない)
    cr = oe.causal_relevance(
        {"titleJa": "全く無関係な官公庁の発表", "directness": "sector_theme",
         "verificationStatus": "verified", "sourceType": "official_gov"},
        theme_entities={"半導体"})
    assert cr["relevance"] == "irrelevant"


# ── Phase 2: SEAJ / Industry Forecast Resolver ──────────────────────────────

def test_seaj_resolver_generates_required_queries():
    q = oe.INDUSTRY_FORECAST_QUERIES
    joined = " ".join(q)
    for must in ("SEAJ 2026 販売高 予測", "日本半導体製造装置協会",
                 "book-to-bill Japan semiconductor equipment",
                 "Japan semiconductor equipment forecast 2026"):
        assert must in joined, must
    assert len(q) >= 11


def test_verified_seaj_official_becomes_industry_forecast():
    r = oe.resolve_industry_forecast(
        {"titleJa": "SEAJ、2026年度の販売高予測を大幅に上方修正",
         "url": "https://www.seaj.or.jp/statistics/x.html"})
    assert r["matched"] and r["sourceType"] == "industry_forecast"
    assert "SEAJ公式または業界予測ソースを確認" in r["ownerReadableJa"]


def test_metadata_only_seaj_cannot_overclaim():
    r = oe.resolve_industry_forecast(
        {"titleJa": "SEAJの販売高予測に言及した記事",
         "url": "https://news.example.com/a"})
    assert r["sourceType"] == "public_forecast_metadata"
    assert "公式一次は未確認" in r["ownerReadableJa"]


def test_seaj_no_url_no_fabrication():
    r = oe.resolve_industry_forecast(
        {"titleJa": "SEAJ、2026年度の販売高予測を大幅に上方修正"})
    assert r["sourceType"] is None
    assert "捏造しない" in r["ownerReadableJa"]


def test_seaj_theme_not_direct_company_for_6965():
    v = oe.verify_source({"titleJa": "SEAJ、半導体製造装置 販売高予測を上方修正",
                          "sourceName": "SEAJ", "publishedAt": NOW}, {}, NOW)
    assert v["directness"] != "direct_company"
    r = oe.resolve_industry_forecast({"titleJa": "SEAJ 販売高予測 上方修正",
                                      "url": "https://www.seaj.or.jp/a"})
    assert "直接材料ではなく" in r["ownerReadableJa"]


# ── Phase 3: Company Newsroom Resolver ──────────────────────────────────────

def test_product_claim_triggers_newsroom_queries():
    q = oe.company_newsroom_queries(
        {"titleJa": "先端半導体の故障解析向けカメラEmmi-Xを本日発売"}, _prof())
    assert any("ニュースルーム" in x for x in q)
    assert any("Emmi-X" in x for x in q)
    assert any("newsroom" in x for x in q)


def test_company_product_release_direct_but_not_primary_cause():
    cr = oe.causal_relevance(
        {"titleJa": "浜松ホトニクスがEmmi-Xカメラを発売",
         "directness": "direct_company", "freshness": "today",
         "verificationStatus": "verified"},
        theme_entities={"浜松ホトニクス"})
    assert cr["relevance"] in ("low", "medium")
    assert "主因にしない" in cr["ownerReadableReasonJa"]


def test_material_direct_news_is_high_relevance():
    cr = oe.causal_relevance(
        {"titleJa": "浜松ホトニクスが業績予想を上方修正",
         "directness": "direct_company", "freshness": "today",
         "verificationStatus": "verified"},
        theme_entities={"浜松ホトニクス"})
    assert cr["relevance"] == "high"


# ── Phase 4: Research Quality Score v3 ──────────────────────────────────────

def test_rps_v3_has_pillars():
    ver = [{"titleJa": "SEAJ予測", "verificationStatus": "verified",
            "primaryEligible": True, "sourceType": "industry_forecast",
            "directness": "sector_theme", "freshness": "today"}]
    rps = oe.research_power_score(
        verified=ver, agent_runs=_runs(), gap_ledger=[],
        coverage={"totalCoverage": "strong"},
        contradiction=oe.contradiction_report(ver, _runs()),
        context_advantages=["需給文脈"], learning_updated=True)
    for k in ("coverage", "precision", "reasoning", "agenticCompletion",
              "primarySourceStrength"):
        assert k in rps["pillars"], k


def test_2x_requires_primary_strength_or_exceptional_coverage():
    # 一次ソース弱+検証少では、他条件が揃ってもexceeds_gemini_2xにならない
    ver = [{"titleJa": f"一般記事{i}", "verificationStatus": "verified",
            "primaryEligible": True, "sourceType": "media",
            "directness": "sector_theme", "freshness": "today"} for i in range(3)]
    rps = oe.research_power_score(
        verified=ver, agent_runs=[{"provider": "gemini", "status": "ok",
                                   "claims": [{"titleJa": "g", "verified": True}]}],
        gap_ledger=[], coverage={"totalCoverage": "strong"},
        contradiction=oe.contradiction_report(ver, _runs()),
        context_advantages=["需給文脈"], learning_updated=True)
    assert rps["status"] != "exceeds_gemini_2x"


def test_weak_causal_prevents_overscoring_and_blocks():
    ver = [{"titleJa": "SEAJ予測", "verificationStatus": "verified",
            "primaryEligible": True, "sourceType": "industry_forecast",
            "directness": "sector_theme", "freshness": "today"}]
    kw = dict(verified=ver, agent_runs=_runs(), gap_ledger=[],
              coverage={"totalCoverage": "strong"},
              contradiction=oe.contradiction_report(ver, _runs()),
              context_advantages=["需給文脈"], learning_updated=True)
    r0 = oe.research_power_score(**kw)
    r1 = oe.research_power_score(causal_summary={"weakCausalOnly": True}, **kw)
    assert r1["argusScore"] < r0["argusScore"]
    assert "ソースはあるが株価因果の直接性が弱い" in r1["blockersJa"]


def test_hypothesis_alone_cannot_reach_2x():
    ledger = [{"resolutionStatus": "hypothesis_not_source"}] * 5
    rps = oe.research_power_score(
        verified=[], agent_runs=_runs(), gap_ledger=ledger,
        coverage={"totalCoverage": "weak"}, contradiction={},
        context_advantages=[], learning_updated=False)
    assert rps["status"] != "exceeds_gemini_2x"


# ── Phase 5: Causal Relevance ───────────────────────────────────────────────

def test_verified_irrelevant_source_low_relevance():
    cr = oe.causal_relevance(
        {"titleJa": "園芸の話題", "directness": "sector_theme",
         "verificationStatus": "verified"}, theme_entities={"半導体"})
    assert cr["relevance"] == "irrelevant"


def test_seaj_forecast_is_sector_relevance_not_direct():
    cr = oe.causal_relevance(
        {"titleJa": "SEAJが半導体製造装置の販売高予測を上方修正",
         "directness": "sector_theme", "freshness": "today",
         "verificationStatus": "verified"},
        theme_entities={"半導体製造装置", "SEAJ"})
    assert cr["relevance"] in ("medium", "low")
    assert not cr["components"]["directCompanyImpact"]


def test_unverified_source_is_background_for_causality():
    cr = oe.causal_relevance(
        {"titleJa": "未検証の話", "directness": "sector_theme",
         "verificationStatus": "metadata_only"}, theme_entities={"半導体"})
    assert cr["relevance"] == "background"


# ── Phase 6: Source Acquisition Report ──────────────────────────────────────

def test_acquisition_report_sections():
    checks = oe.primary_source_checks(_prof(), {"all": ["浜松ホトニクス IR"]},
                                      [], {}, events_checked=False)
    cov = oe.investigation_source_coverage({}, [], [], events_checked=False)
    rep = oe.source_acquisition_report(checks, cov,
                                       oe.primary_absence_guards(checks))
    for k in ("officialCompany", "industryAssociation", "newsAggregator",
              "globalValueChain", "metadataOnlyOrInaccessible",
              "uncheckedOrUnavailable", "guardsJa", "whyItMattersJa"):
        assert k in rep, k
    assert rep["uncheckedOrUnavailable"], "未チェックカテゴリも必ず可視"


# ── Phase 7: Owner Conclusion ───────────────────────────────────────────────

def test_conclusion_distinguishes_direct_industry():
    ver = [{"titleJa": "SEAJ販売高予測を上方修正", "verificationStatus": "verified",
            "sourceType": "industry_forecast", "directness": "sector_theme"}]
    rps = {"status": "below_gemini", "statusJa": "Gemini未満",
           "displayJa": "Research Power: Gemini 68 / ARGUS 91 / 1.34x",
           "ownerReadableVerdictJa": "x", "blockersJa": ["公式/業界一次情報が不足"]}
    oc = oe.owner_conclusion(verified=ver, relevances=[], rps=rps,
                             gap_summary={"unresolvedImportantItems": []},
                             context_advantages=["需給文脈"], agent_runs=_runs())
    assert "直接材料は未確認。ただし、業界/テーマ材料としては" in oc["directCompanyEvidenceJa"]
    assert "確認されています" in oc["directCompanyEvidenceJa"]


def test_conclusion_not_2x_has_exact_blockers():
    rps = {"status": "below_gemini", "statusJa": "Gemini未満", "displayJa": "d",
           "ownerReadableVerdictJa": "v",
           "blockersJa": ["具体ソース未回収", "公式/業界一次情報が不足"]}
    oc = oe.owner_conclusion(verified=[], relevances=[], rps=rps,
                             gap_summary={"unresolvedImportantItems": ["[重要だが未回収] X"]},
                             context_advantages=[], agent_runs=_runs())
    assert "具体ソース未回収" in oc["whyJa"]
    assert oc["nextActionJa"].startswith("[重要だが未回収]")


def test_conclusion_no_vague_bucket():
    oc = oe.owner_conclusion(verified=[], relevances=[],
                             rps={"status": "insufficient_data", "statusJa": "判定保留",
                                  "displayJa": "d", "ownerReadableVerdictJa": "v",
                                  "blockersJa": []},
                             gap_summary={"unresolvedImportantItems": []},
                             context_advantages=[], agent_runs=[])
    assert "原因未特定" not in str(oc)


# ── 統合(scanner)+非漏洩 ───────────────────────────────────────────────────

def test_osint_build_v12_1_5_integration():
    scanner._OSINT_AGENT_QUEUE.clear()
    scanner._OSINT_PROGRESS.clear()
    inv = scanner._osint_build(
        "6965", "JP", "war_room", "redacted", "owner_request",
        [{"provider": "gemini", "status": "ok", "claims": [
            {"titleJa": "SEAJ、2026年度の日本製半導体製造装置の販売高予測を大幅に上方修正"}]}],
        NOW)
    assert len(inv["primarySourceChecks"]) == 12
    assert isinstance(inv["causalRelevanceSummary"], dict)
    assert isinstance(inv["ownerConclusion"], dict)
    assert inv["ownerConclusion"]["whyJa"]
    assert isinstance(inv["sourceAcquisitionReport"], dict)
    # SEAJ resolver がクエリ学習(overlayに追撃語)
    terms = scanner._OSINT_TERM_OVERLAY.get("6965") or []
    assert any("SEAJ" in t for t in terms)


def test_dq_exposes_primary_strength_and_causal():
    with scanner.app.test_client() as c:
        r = c.get("/api/argus/data-quality")
        oh = (r.get_json() or {}).get("osintHealth") or {}
        assert "primarySourceStrengthLatest" in oh
        assert "causalRelevanceLatestJa" in oh


def test_fe_shows_conclusion_and_causal():
    src = _read("components", "dashboard", "OsintDeepDive.tsx")
    assert "ownerConclusion" in src
    assert "causalRelevanceSummary" in src
    assert "primarySourceChecks" in src


def test_pack_includes_conclusion():
    src = _read("lib", "reviewPack.ts")
    assert "conclusionJa" in src and "primarySourceJa" in src


def test_public_no_leak_after_v12_1_5():
    scanner._OSINT_AGENT_QUEUE.clear()
    scanner._OSINT_PROGRESS.clear()
    with scanner.app.test_client() as c:
        r = c.get("/api/argus/osint/investigation?symbol=6965")
        body = r.get_data(as_text=True)
        for banned in ("quantity", "avgCost", "acquisitionPrice", "passphrase",
                       "GEMINI_API_KEY", "OPENAI_API_KEY", "hmac"):
            assert banned not in body
