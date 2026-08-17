"""ARGUS V12.1.1 — OSINT優位性ハードニングの恒久ガード。

優位性判定(未回収Gemini-onlyがあればexceeds不可)/恒久メモリ(sanitize)/
URLライブ検証(捏造なし)/反復再探索/頑健パーサ/進捗・二重防止 を固定する。
"""
import json
import os

import argus_osint_engine as oe
import scanner

WEB = os.path.join(os.path.dirname(__file__), "web", "src")
NOW = "2026-07-08T01:00:00Z"


def _read(*parts):
    return open(os.path.join(WEB, *parts), encoding="utf-8").read()


def _run(provider, claims, status="ok"):
    return {"provider": provider, "status": status, "claims": claims}


# ── Part A: 優位性判定 ──────────────────────────────────────────────────────

def _vs(title, status="verified", directness="sector_theme", fresh="today"):
    return {"titleJa": title, "verificationStatus": status, "directness": directness,
            "freshness": fresh, "primaryEligible": status == "verified",
            "sourceName": "src", "labelJa": "検証済み" if status == "verified" else "未検証"}


def test_superiority_below_if_gemini_only_unresolved():
    runs = [_run("gemini", [{"titleJa": "Geminiだけの重要記事", "_freshness": "today",
                             "verified": False}])]
    m = oe.superiority_metrics([_vs("ARGUSの記事")], runs,
                               {"geminiCount": 1, "gptCount": 0, "missedByArgusCount": 1},
                               {"totalCoverage": "medium"}, argus_titles=["ARGUSの記事"])
    assert m["superiorityStatus"] == "below_gemini"
    assert oe.GAP_JA in m["ownerReadableVerdictJa"]
    assert m["argusMissedImportantCount"] == 1


def test_superiority_exceeds_requires_verified_overlap_plus_extra():
    shared = "共通の記事"
    runs = [_run("gemini", [{"titleJa": shared, "_freshness": "today", "verified": True}])]
    m = oe.superiority_metrics(
        [_vs(shared), _vs("ARGUS独自の検証済み記事")], runs,
        {"geminiCount": 1, "gptCount": 0, "missedByArgusCount": 0},
        {"totalCoverage": "medium"},
        argus_titles=[shared, "ARGUS独自の検証済み記事"])
    assert m["superiorityStatus"] == "exceeds_gemini"
    assert m["verifiedOverlapCount"] == 1
    assert m["argusOnlyVerifiedCount"] == 1
    # 文脈統合の差分表示
    m2 = oe.superiority_metrics(
        [_vs(shared)], runs,
        {"geminiCount": 1, "gptCount": 0, "missedByArgusCount": 0},
        {"totalCoverage": "medium"}, argus_titles=[shared], context_added=True)
    assert m2["superiorityStatus"] == "exceeds_gemini"
    assert m2["contextEdgeJa"] == oe.CONTEXT_EDGE_JA


def test_superiority_insufficient_without_agents():
    m = oe.superiority_metrics([_vs("a")], [], {"geminiCount": 0, "gptCount": 0},
                               {"totalCoverage": "weak"}, argus_titles=["a"])
    assert m["superiorityStatus"] == "insufficient_data"
    assert m["superiorityJa"] == "判定保留"


# ── Part B: 恒久メモリ ──────────────────────────────────────────────────────

def test_memory_record_sanitizes_terms():
    ok = oe.memory_record(symbol="6965", query_term="シリコンフォトニクス",
                          learned_from="gemini", verified=False, now_iso=NOW)
    assert ok and ok["queryTerm"] == "シリコンフォトニクス"
    assert ok["privacyLevel"] == "public_safe"
    bad = oe.memory_record(symbol="6965", query_term="https://evil.example.com",
                           learned_from="gemini", verified=False, now_iso=NOW)
    assert bad is None                                   # URL語は保存しない
    priv = oe.memory_record(symbol="6965", query_term="保有中500株のメモ",
                            learned_from="owner_feedback", verified=False, now_iso=NOW)
    assert priv is None                                  # 私的断片は保存しない


def test_memory_snapshot_public_safe(monkeypatch):
    monkeypatch.setitem(scanner._OSINT_PERSIST_STATE, "restored", True)
    monkeypatch.setattr(scanner, "_OSINT_MEMORY", [
        {"id": "om-1", "symbol": "6965", "queryTerm": "フォトニクス",
         "privacyLevel": "public_safe", "verified": True},
        {"id": "om-2", "symbol": "6965", "queryTerm": "x",
         "privacyLevel": "private_local", "verified": False},
    ])
    with scanner.app.test_client() as c:
        d = c.get("/api/argus/osint/memory-snapshot").get_json()
    ids = [m["id"] for m in d["memory"]]
    assert "om-1" in ids and "om-2" not in ids           # private_localは公開に出ない
    import argus_portfolio_sync
    assert not argus_portfolio_sync.contains_sensitive(d)


# ── Part C: URLライブ検証 ───────────────────────────────────────────────────

def test_live_upgrade_verifies_matching_title(monkeypatch):
    monkeypatch.setattr(scanner, "_osint_fetch_url_meta", lambda url: {
        "status": "metadata_only", "title": "浜松ホトニクスが新型光半導体センサーを発表",
        "publishedAt": "2026-07-08T00:00:00Z", "domain": "news.example.com"})
    claim = {"titleJa": "浜松ホトニクス 新型光半導体センサー発表",
             "url": "https://news.example.com/x"}
    vs = oe.verify_source(claim, {}, NOW)
    assert vs["verificationStatus"] in ("metadata_only", "unknown")
    v2 = scanner._osint_live_upgrade(vs, claim, NOW, sym="6965")
    assert v2["verificationStatus"] == "verified"
    assert v2["labelJa"] == "検証済み(ライブ取得)"
    assert v2["fetchedTitle"].startswith("浜松ホトニクス")


def test_live_upgrade_mismatch_stays_unverified(monkeypatch):
    monkeypatch.setattr(scanner, "_osint_fetch_url_meta", lambda url: {
        "status": "metadata_only", "title": "全く関係ないページのタイトルです",
        "publishedAt": None, "domain": "x.example.com"})
    claim = {"titleJa": "浜松ホトニクスの重要ニュース", "url": "https://x.example.com/y"}
    vs = oe.verify_source(claim, {}, NOW)
    v2 = scanner._osint_live_upgrade(vs, claim, NOW, sym="6965")
    assert v2["verificationStatus"] == "metadata_only"   # 不一致は昇格しない(捏造なし)
    assert v2["primaryEligible"] is False


def test_live_upgrade_inaccessible_not_evidence(monkeypatch):
    monkeypatch.setattr(scanner, "_osint_fetch_url_meta", lambda url: {
        "status": "inaccessible", "title": None, "publishedAt": None, "domain": None})
    claim = {"titleJa": "ペイウォール記事", "url": "https://paywall.example.com/z"}
    vs = oe.verify_source(claim, {}, NOW)
    v2 = scanner._osint_live_upgrade(vs, claim, NOW, sym="6965")
    assert v2["verificationStatus"] != "verified"
    assert "参照不能" in v2["labelJa"] or "未検証" in v2["labelJa"]


# ── Part D: 反復再探索 ──────────────────────────────────────────────────────

def test_unresolved_claims_and_followup_queries():
    runs = [_run("gemini", [
        {"titleJa": "SamsungとAnthropicのカスタムAIチップ提携", "_freshness": "today",
         "verified": False, "url": "https://tech.example.com/samsung-anthropic"}])]
    unresolved = oe.unresolved_agent_claims(runs, ["ARGUSが持っている別の記事"])
    assert len(unresolved) == 1
    follow = oe.followup_queries(unresolved)
    assert follow                                          # 追撃語が生成される
    assert any("Samsung" in w or "Anthropic" in w or "カスタム" in w for w in follow)


def test_followup_can_resolve_to_overlap():
    shared = "SamsungとAnthropicのカスタムAIチップ提携"
    runs = [_run("gemini", [{"titleJa": shared, "_freshness": "today", "verified": True}])]
    # 再探索後: ARGUS titlesに同記事が入った状態 → 未回収ゼロ・overlap検証済み
    m = oe.superiority_metrics([_vs(shared)], runs,
                               {"geminiCount": 1, "gptCount": 0, "missedByArgusCount": 0},
                               {"totalCoverage": "medium"}, argus_titles=[shared],
                               context_added=True)
    assert m["argusMissedImportantCount"] == 0
    assert m["superiorityStatus"] in ("exceeds_gemini", "matches_gemini")


def test_worker_has_research_loop_and_progress():
    src = open("scanner.py", encoding="utf-8").read()
    assert "_OSINT_LOOP_BUDGET" in src
    assert '"deep": 2' in src and '"war_room": 3' in src
    assert "再探索{loop_i}/{max_loops}: Gemini-onlyニュースを回収中" in src
    assert "検証済みに昇格: {promoted}件" in src


# ── Part E: 即時実行UX(進捗/二重防止/ETA) ───────────────────────────────────

def test_deep_dive_duplicate_guard(monkeypatch):
    monkeypatch.setitem(scanner._NEWS_JA_STATE, "restored", True)
    monkeypatch.setitem(scanner._OSINT_PERSIST_STATE, "restored", True)
    # 前のテスト(v12.1.0系のdeep-dive)が残したキュー/進捗を必ずクリア
    scanner._OSINT_AGENT_QUEUE.clear()
    scanner._OSINT_PROGRESS.clear()
    with scanner.app.test_client() as c:
        r1 = c.post("/api/argus/osint/deep-dive", json={"symbol": "6965", "market": "JP"}).get_json()
        assert r1["ok"] and not r1.get("duplicate")
        assert r1.get("queuePosition") == 1
        assert isinstance(r1.get("nextCronEtaMin"), int)
        r2 = c.post("/api/argus/osint/deep-dive", json={"symbol": "6965", "market": "JP"}).get_json()
        assert r2.get("duplicate") is True               # 連打しても新規jobを作らない
        assert "二重実行" in r2["agentNoteJa"]
        g = c.get("/api/argus/osint/investigation?symbol=6965").get_json()
        assert g.get("progress") is not None             # 進捗が見える(黙って待たない)
        assert g["progress"]["stage"] == "queued_for_agents"


# ── Part F: 頑健パーサ ──────────────────────────────────────────────────────

def test_parser_handles_fences_and_prose():
    out, w = oe.parse_scout_output(
        '調査しました。以下が結果です。\n```json\n{"claims":[{"titleJa":"記事A","url":"https://a.example.com/1"}]}\n```')
    assert len(out["claims"]) == 1 and not w


def test_parser_fallback_extracts_from_prose():
    out, w = oe.parse_scout_output(
        "- 浜松ホトニクス関連の材料が報道 https://news.example.com/hp\n"
        "- AI半導体の採算懸念が広がるという解説記事")
    assert len(out["claims"]) == 2
    assert "fallback_extraction" in w
    assert out["claims"][0]["url"] == "https://news.example.com/hp"


def test_parser_empty_or_garbage_no_fabrication():
    out, w = oe.parse_scout_output("")
    assert out["claims"] == [] and "empty_output" in w
    out2, w2 = oe.parse_scout_output("了解しました。")
    assert out2["claims"] == []                           # 捏造claimを作らない
    assert "no_claims_extracted" in w2


# ── Part G: ベンチ8種 ───────────────────────────────────────────────────────

def test_canary_topics_expanded_to_eight():
    topics = {t["topic"] for t in scanner._OSINT_CANARY_TOPICS}
    for t in ("samsung_anthropic_ai_chip", "hamamatsu_optical_value_chain",
              "direct_company_disclosure", "global_ai_capex",
              "cpi_official_schedule", "nfp_release", "fomc", "jp_semis_theme"):
        assert t in topics, t
    assert len(scanner._OSINT_CANARY_TOPICS) >= 8


def test_dq_benchmark_warn_when_samsung_missed(monkeypatch):
    monkeypatch.setitem(scanner._NEWS_JA_STATE, "restored", True)
    monkeypatch.setitem(scanner._OSINT_CANARY_LAST, "data", {
        "degraded": True, "missedByArgusCount": 1,
        "noteJa": "OSINT監視に見落としの可能性",
        "rows": [{"topic": "samsung_anthropic_ai_chip", "status": "missed_by_argus"}]})
    with scanner.app.test_client() as c:
        d = c.get("/api/argus/data-quality").get_json()
    assert d["osintHealth"]["benchmarkWarnJa"] == "Gemini級OSINTベンチマーク未達"


# ── FE/DQ/Pack 検査 ─────────────────────────────────────────────────────────

def test_fe_superiority_and_progress_ui():
    src = _read("components", "dashboard", "OsintDeepDive.tsx")
    for needle in ("再探索する", "このニュースをARGUSに学習させる", "進捗:",
                   "キュー", "次回実行まで約", "二重実行しません",
                   "検証率", "未回収", "ARGUS独自検証済み"):
        assert needle in src, needle
    hook = _read("hooks", "useOsintInvestigation.ts")
    assert "superiority" in hook and "OsintProgress" in hook


def test_fe_dq_superiority_fields():
    src = _read("routes", "DataQualityPage.tsx")
    for needle in ("Gemini超過", "Gemini未満", "未回収Gemini-only合計",
                   "恒久メモリ", "パーサ警告", "benchmarkWarnJa"):
        assert needle in src, needle


def test_pack_superiority_lines():
    src = _read("lib", "reviewPack.ts")
    assert "OSINT優位性" in src
    assert "未回収のOSINTギャップ" in src
    assert "ソース検証率" in src


def test_ledger_workflow_persists_osint_memory():
    src = open(".github/workflows/caos-watchtower.yml", encoding="utf-8").read()
    assert "osint/memory-snapshot" in src
    assert "ledger/osint/memory.json" in src


# ── 回帰: redacted安全・公開経路外部AI不発火(v12.1.0のガードが生きている) ────

def test_redacted_prompt_still_safe_after_hardening():
    prof = {"symbol": "6965", "nameJa": "浜松ホトニクス", "nameEn": "Hamamatsu Photonics",
            "sector": "光半導体", "themes": ["AI半導体"], "valueChain": ["Samsung Anthropic AI chip"],
            "competitors": [], "aliases": []}
    plan = oe.build_query_plan(prof)
    for prov in ("gemini", "gpt"):
        p = oe.build_scout_prompt(prov, prof, plan, move_pct=-3.0,
                                  privacy_mode="redacted",
                                  owner_context_ja="保有中500株 取得単価2775")
        assert oe.redacted_prompt_is_safe(p)
        assert "英語の海外テック" in p                      # Part F強化文言
    gp = oe.build_scout_prompt("gpt", prof, plan, move_pct=None, privacy_mode="redacted")
    assert "反証(negative evidence)" in gp
    assert "古い記事の再掲に警告" in gp
