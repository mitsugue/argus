"""ARGUS V12.1.4 — 仮説クレーム規律/代替回収/新鮮ニュース加速の恒久ガード。

仮説はソース欠落と混同しない(優位性をブロックするのは具体未回収のみ)/
参照不能ソースは合法的な代替経路で回収を試みる/検証前の新鮮候補は
決定的原因になれない/公式・業界クエリ強化。
"""
import os

import argus_osint_engine as oe
import scanner

WEB = os.path.join(os.path.dirname(__file__), "web", "src")
NOW = "2026-07-08T03:00:00Z"


def _read(*parts):
    return open(os.path.join(WEB, *parts), encoding="utf-8").read()


# ── Phase 1: Agent Claim Taxonomy ───────────────────────────────────────────

def test_hypothesis_without_url_is_not_unresolved_important():
    g = oe.resolve_gap(
        {"titleJa": "国内株式メディアで6965固有ニュースとして取り上げられた可能性"},
        "gpt", [], symbol="6965", investigation_id="i", now_iso=NOW,
        theme_entities={"浜松ホトニクス", "半導体"})
    assert g["resolutionStatus"] == "hypothesis_not_source"
    assert g["claimType"] == "hypothesis"
    assert "未検証仮説" in g["resolutionStatusJa"]


def test_sympathy_without_source_is_direction_or_inference():
    t = oe.classify_agent_claim(
        {"titleJa": "AI optical interconnect sympathy trade",
         "directness": "value_chain"})
    assert t in ("search_direction", "value_chain_inference")


def test_concrete_title_source_no_url_still_missing_url():
    g = oe.resolve_gap(
        {"titleJa": "先端半導体の故障解析向けカメラを本日発売",
         "sourceName": "PR TIMES", "publishedAt": NOW},
        "gemini", [], symbol="6965", investigation_id="i", now_iso=NOW,
        theme_entities={"半導体"})
    assert g["resolutionStatus"] == "missing_url"
    assert g["claimType"] == "concrete_source_claim"


def test_unsupported_narrative_cannot_become_evidence():
    t = oe.classify_agent_claim({"titleJa": "何かが起きているようだ"})
    assert t in ("unsupported_narrative", "hypothesis")
    g = oe.resolve_gap({"titleJa": "株価が上昇した"}, "gpt", [],
                       symbol="6965", investigation_id="i", now_iso=NOW)
    assert g["resolutionStatus"] in ("unsupported_rejected", "hypothesis_not_source",
                                     "irrelevant", "low_value_background")
    assert g["resolutionStatus"] != "verified_integrated"


def test_url_and_date_claim_is_concrete_despite_hedging_words():
    t = oe.classify_agent_claim(
        {"titleJa": "半導体関連の可能性に言及した記事",
         "url": "https://example.com/a", "publishedAt": NOW})
    assert t in ("concrete_source_claim", "official_disclosure_claim")


# ── Phase 2: Gap Ledger v3 ──────────────────────────────────────────────────

def test_ledger_v3_statuses_exist():
    for st in ("hypothesis_not_source", "search_direction_only", "inference_only"):
        assert st in oe.RESOLUTION_STATUSES
        assert st in oe.RESOLUTION_JA


def _runs(verified=True):
    return [{"provider": "gemini", "status": "ok",
             "claims": [{"titleJa": "g1", "verified": verified}]}]


def _ver_industry():
    return [{"titleJa": "SEAJ予測", "verificationStatus": "verified",
             "primaryEligible": True, "sourceType": "industry_forecast",
             "directness": "sector_theme", "freshness": "today"}]


def test_hypothesis_not_source_does_not_force_below():
    ledger = [{"resolutionStatus": "hypothesis_not_source"},
              {"resolutionStatus": "search_direction_only"},
              {"resolutionStatus": "inference_only"}]
    ver = _ver_industry()
    rps = oe.research_power_score(
        verified=ver, agent_runs=_runs(), gap_ledger=ledger,
        coverage={"totalCoverage": "strong"},
        contradiction=oe.contradiction_report(ver, _runs()),
        context_advantages=["需給文脈"], learning_updated=True)
    assert rps["status"] != "below_gemini"


def test_concrete_unresolved_still_forces_below():
    ledger = [{"resolutionStatus": "still_unresolved_important"}]
    ver = _ver_industry()
    rps = oe.research_power_score(
        verified=ver, agent_runs=_runs(), gap_ledger=ledger,
        coverage={"totalCoverage": "strong"},
        contradiction=oe.contradiction_report(ver, _runs()),
        context_advantages=["需給文脈"], learning_updated=True)
    assert rps["status"] == "below_gemini"
    assert "具体ソース未回収" in rps["blockersJa"]


def test_rejected_unsupported_raises_hallucination_resistance_not_source():
    ver = _ver_industry()
    ledger = [{"resolutionStatus": "unsupported_rejected"}] * 2
    kw = dict(agent_runs=_runs(), coverage={"totalCoverage": "medium"},
              context_advantages=[], learning_updated=False)
    r0 = oe.research_power_score(verified=ver, gap_ledger=[],
                                 contradiction=oe.contradiction_report(ver, _runs()), **kw)
    r1 = oe.research_power_score(verified=ver, gap_ledger=ledger,
                                 contradiction=oe.contradiction_report(ver, _runs()), **kw)
    assert r1["components"]["hallucinationResistanceScore"] > \
        r0["components"]["hallucinationResistanceScore"]
    assert r1["components"]["verifiedUsefulSourceScore"] == \
        r0["components"]["verifiedUsefulSourceScore"]


# ── Phase 3: Blocked Source Recovery ────────────────────────────────────────

def test_inaccessible_source_triggers_alternate_queries():
    q = oe.blocked_source_recovery_queries(
        {"sourceTitle": "先端半導体の故障解析向けカメラEmmi-Xを本日発売"},
        company_ja="浜松ホトニクス", company_en="Hamamatsu Photonics")
    assert any("ニュースルーム" in x for x in q)
    assert any("Emmi" in x or "浜松ホトニクス" in x for x in q)


def test_press_aggregator_category_detected():
    assert oe.press_source_category("https://prtimes.jp/main/html/rd/p/1.html") == \
        "press_release_aggregator"
    assert oe.press_source_category("https://www.hamamatsu.com/jp/ja/news/x.html") == \
        "company_newsroom"


def test_metadata_only_does_not_become_full_evidence():
    v = oe.verify_source({"titleJa": "新製品発売", "url": "https://x.co/a",
                          "publishedAt": NOW}, {}, NOW)
    assert v["verificationStatus"] == "metadata_only"
    assert v["primaryEligible"] is False


def test_blocked_recovery_no_fabrication():
    # 回収クエリはタイトル/企業名の再検索のみ — 本文や日付を作らない
    q = oe.blocked_source_recovery_queries({"sourceTitle": ""}, company_ja="")
    assert q == []


# ── Phase 4: Fresh News Acceleration ────────────────────────────────────────

def test_fresh_candidate_is_preliminary_not_verified():
    st = oe.preliminary_status({"verificationStatus": "metadata_only",
                                "freshness": "today"})
    assert st == "fresh_candidate"
    st2 = oe.preliminary_status({"verificationStatus": "verified",
                                 "freshness": "today"})
    assert st2 == "verified"
    st3 = oe.preliminary_status({"verificationStatus": "stale"})
    assert st3 == "rejected"


def test_preliminary_cannot_create_direct_cause():
    v = oe.verify_source({"titleJa": "本日発売の新製品", "url": "https://x.co/a",
                          "publishedAt": NOW}, {}, NOW)
    assert oe.preliminary_status(v) == "fresh_candidate"
    assert v["primaryEligible"] is False   # 検証されるまで主因不可


def test_fresh_candidate_alert_wording():
    assert "検証中" in oe.FRESH_CANDIDATE_ALERT_JA


# ── Phase 5: 公式/業界クエリ強化 ─────────────────────────────────────────────

def test_company_newsroom_query_generated():
    prof = scanner._osint_profile("6965", "JP")
    plan = oe.build_query_plan(prof)
    joined = " ".join(plan["direct"])
    assert "ニュース" in joined
    assert "製品発表" in joined


def test_industry_association_query_generated():
    prof = scanner._osint_profile("6965", "JP")
    plan = oe.build_query_plan(prof)
    joined = " ".join(plan["all"])
    assert "SEAJ" in joined


def test_official_absence_blocker_wording():
    rps = oe.research_power_score(
        verified=[], agent_runs=_runs(), gap_ledger=[],
        coverage={"totalCoverage": "weak"},
        contradiction={}, context_advantages=[])
    assert "公式一次情報不足" in rps["blockersJa"]


def test_official_unrelated_source_not_inflating():
    # 無関係(irrelevant判定)のclaimはverifiedに入らずスコア外
    g = oe.resolve_gap({"titleJa": "無関係な官公庁発表", "sourceName": "官公庁"},
                       "gemini", [], symbol="6965", investigation_id="i",
                       now_iso=NOW, theme_entities={"半導体"})
    assert g["resolutionStatus"] in ("irrelevant", "missing_url",
                                     "hypothesis_not_source")


# ── Phase 6: RPS v2 ─────────────────────────────────────────────────────────

def test_rps_v2_has_19_components():
    ver = _ver_industry()
    rps = oe.research_power_score(
        verified=ver, agent_runs=_runs(), gap_ledger=[],
        coverage={"totalCoverage": "strong"},
        contradiction=oe.contradiction_report(ver, _runs()),
        context_advantages=["需給文脈"], learning_updated=True,
        kwargs_recovery={"attempted": 1, "recovered": 1, "freshCandidates": 0})
    assert len(rps["components"]) == 19
    for k in ("hypothesisDisciplineScore", "blockedSourceRecoveryScore",
              "freshNewsLatencyScore", "alternateSourceRecoveryScore"):
        assert k in rps["components"]


def test_preliminary_fresh_candidate_does_not_inflate_score():
    ver = _ver_industry()
    kw = dict(agent_runs=_runs(), gap_ledger=[],
              coverage={"totalCoverage": "strong"},
              contradiction=oe.contradiction_report(ver, _runs()),
              context_advantages=["需給文脈"], learning_updated=True)
    r0 = oe.research_power_score(verified=ver, **kw)
    r1 = oe.research_power_score(verified=ver,
                                 kwargs_recovery={"freshCandidates": 3}, **kw)
    assert r1["argusScore"] <= r0["argusScore"]
    assert "新鮮候補が未検証" in r1["blockersJa"]


def test_alternate_verified_source_improves_score():
    ver = _ver_industry()
    kw = dict(agent_runs=_runs(), gap_ledger=[],
              coverage={"totalCoverage": "strong"},
              contradiction=oe.contradiction_report(ver, _runs()),
              context_advantages=["需給文脈"], learning_updated=True)
    r0 = oe.research_power_score(verified=ver, **kw)
    r1 = oe.research_power_score(verified=ver,
                                 kwargs_recovery={"attempted": 2, "recovered": 2}, **kw)
    assert r1["argusScore"] > r0["argusScore"]


# ── Phase 7: UI/DQ/Pack 統合 ────────────────────────────────────────────────

def test_osint_build_separates_hypotheses(monkeypatch):
    scanner._OSINT_AGENT_QUEUE.clear()
    scanner._OSINT_PROGRESS.clear()
    inv = scanner._osint_build(
        "6965", "JP", "deep", "redacted", "owner_request",
        [{"provider": "gpt", "status": "ok", "claims": [
            {"titleJa": "国内メディアで取り上げられた可能性"},
            {"titleJa": "英語圏AI半導体ニュースからの連想"}]}], NOW)
    by = {}
    for g in inv["gapLedger"]:
        by[g["resolutionStatus"]] = by.get(g["resolutionStatus"], 0) + 1
    assert by.get("still_unresolved_important", 0) == 0
    assert by.get("hypothesis_not_source", 0) + by.get("search_direction_only", 0) >= 2
    assert inv["superiority"]["argusMissedImportantCount"] == 0
    assert "freshCandidateCount" in inv


def test_fe_shows_hypothesis_separation():
    src = _read("components", "dashboard", "OsintDeepDive.tsx")
    assert "未検証仮説" in src
    assert "探索方向" in src
    assert "freshCandidateAlertJa" in src


def test_dq_exposes_recovery_and_hypothesis_counts():
    with scanner.app.test_client() as c:
        r = c.get("/api/argus/data-quality")
        oh = (r.get_json() or {}).get("osintHealth") or {}
        for k in ("blockedRecoveryAttempted", "blockedRecoveryRecovered",
                  "hypothesisNotSourceCount", "metadataOnlyCount",
                  "freshCandidateCount"):
            assert k in oh, k


def test_pack_includes_gap_groups():
    src = _read("lib", "reviewPack.ts")
    assert "gapGroupsJa" in src


def test_public_investigation_no_leak_after_v12_1_4():
    scanner._OSINT_AGENT_QUEUE.clear()
    scanner._OSINT_PROGRESS.clear()
    with scanner.app.test_client() as c:
        r = c.get("/api/argus/osint/investigation?symbol=6965")
        body = r.get_data(as_text=True)
        for banned in ("quantity", "avgCost", "acquisitionPrice", "passphrase",
                       "GEMINI_API_KEY", "OPENAI_API_KEY", "hmac"):
            assert banned not in body
