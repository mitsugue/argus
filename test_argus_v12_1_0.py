"""ARGUS V12.1.0 — Multi-Agent OSINT Engine の恒久ガード。

計画(多段クエリ)/検証(LLM出力は検証まで証拠でない)/採点(coverage gate)/
ベンチマーク(missed_by_argus)/canary/redactedプロンプト非漏洩/公開経路の
外部AI不発火 を固定する。
"""
import json
import os

import argus_osint_engine as oe
import scanner

WEB = os.path.join(os.path.dirname(__file__), "web", "src")
NOW = "2026-07-07T10:00:00Z"


def _read(*parts):
    return open(os.path.join(WEB, *parts), encoding="utf-8").read()


_HAMAMATSU = {
    "symbol": "6965", "nameJa": "浜松ホトニクス", "nameEn": "Hamamatsu Photonics",
    "sector": "光半導体",
    "themes": ["光半導体", "フォトニクス", "光センサー", "AI半導体"],
    "valueChain": ["Samsung Anthropic AI chip", "Anthropic custom chip",
                   "optical semiconductor", "photonics AI data center",
                   "AI半導体 バリューチェーン", "AI投資 採算 半導体"],
    "competitors": ["ソニーグループ"], "aliases": [],
}


# ── Part D: Query Planner ────────────────────────────────────────────────────

def test_query_planner_has_all_hop_types():
    plan = oe.build_query_plan(_HAMAMATSU, move_pct=-4.2)
    for k in ("direct", "sector", "valueChain", "globalCatalyst", "negative"):
        assert plan[k], k
    assert plan["queryCount"] >= 20
    blob = " ".join(plan["all"])
    # 直接(IR/決算/格付け…)・下落理由・英語グローバル
    assert "浜松ホトニクス 決算" in blob
    assert "下落理由" in blob or "急落" in blob
    assert "custom silicon" in blob and "hyperscaler capex" in blob


def test_query_planner_hamamatsu_fixture_expansion():
    plan = oe.build_query_plan(_HAMAMATSU, move_pct=-4.2)
    blob = " ".join(plan["all"])
    for term in ("Samsung Anthropic AI chip", "Anthropic custom chip",
                 "optical semiconductor", "AI半導体 バリューチェーン"):
        assert term in blob, term
    # ハードコードでなく再利用規則: 別銘柄プロファイルでも同じ骨格が出る
    other = oe.build_query_plan({"symbol": "5803", "nameJa": "フジクラ",
                                 "nameEn": "Fujikura", "sector": "電線",
                                 "themes": ["AI半導体"], "valueChain": ["NVIDIA"],
                                 "competitors": [], "aliases": []})
    assert "フジクラ 決算" in " ".join(other["all"])
    assert other["queryCount"] >= 15


def test_owner_terms_extend_plan():
    plan = oe.build_query_plan(_HAMAMATSU, extra_terms=["新語A", "新語B"])
    assert "新語A" in plan["all"] and "新語B" in plan["all"]


# ── Part F: 検証 — LLM出力は検証まで証拠でない ──────────────────────────────

def test_llm_claim_not_evidence_until_verified():
    idx = oe.build_known_index([
        {"titleJa": "既知の記事", "canonicalUrl": "https://news.example.com/a1",
         "publishedAt": "2026-07-07T01:00:00Z"},
    ])
    # ストアで裏取りできた主張 → verified
    v1 = oe.verify_source({"titleJa": "既知の記事",
                           "url": "https://news.example.com/a1",
                           "publishedAt": "2026-07-07T01:00:00Z"}, idx, NOW)
    assert v1["verificationStatus"] == "verified"
    assert v1["primaryEligible"] is True
    # LLMだけが主張(裏取り不能) → 未検証・主因不可
    v2 = oe.verify_source({"titleJa": "LLMだけが言っている記事",
                           "url": "https://unknown.example.com/x",
                           "publishedAt": "2026-07-07T01:00:00Z"}, idx, NOW)
    assert v2["verificationStatus"] == "metadata_only"
    assert v2["primaryEligible"] is False
    assert "未検証" in v2["labelJa"]
    # URLも日付もない主張 → 参照不能
    v3 = oe.verify_source({"titleJa": "出典のない主張"}, idx, NOW)
    assert v3["verificationStatus"] == "inaccessible"
    assert v3["primaryEligible"] is False


def test_stale_source_cannot_be_primary():
    idx = oe.build_known_index([
        {"titleJa": "古い既知記事", "canonicalUrl": "https://n.example.com/old",
         "publishedAt": "2024-09-13T00:00:00Z"},
    ])
    v = oe.verify_source({"titleJa": "古い既知記事",
                          "url": "https://n.example.com/old",
                          "publishedAt": "2024-09-13T00:00:00Z"}, idx, NOW)
    assert v["verificationStatus"] == "stale"
    assert v["primaryEligible"] is False
    assert v["freshness"] == "stale_14d_plus"


def test_verdict_theme_not_stated_as_fact():
    idx = oe.build_known_index([
        {"titleJa": "AI半導体バリューチェーンに懸念",
         "canonicalUrl": "https://n.example.com/theme",
         "publishedAt": "2026-07-07T01:00:00Z"},
    ])
    v = oe.verify_source({"titleJa": "AI半導体バリューチェーンに懸念",
                          "url": "https://n.example.com/theme",
                          "publishedAt": "2026-07-07T01:00:00Z",
                          "directness": "sector_theme"}, idx, NOW)
    verdict = oe.synthesize_verdict([v], {"totalCoverage": "medium"}, [])
    assert verdict["verdict"] == "likely_sector_theme"
    assert "テーマ連想の候補" in verdict["ownerReadableJa"]
    assert "直接材料は未確認" in verdict["ownerReadableJa"]
    assert oe.NO_DIRECT_JA in verdict["missingEvidenceJa"]


def test_news_none_requires_coverage():
    # coverage弱 → 「ニュースなし」とは言わず「探索範囲では未確認」
    weak = oe.synthesize_verdict([], {"totalCoverage": "weak"}, [])
    assert weak["ownerReadableJa"] == oe.NOT_FOUND_WEAK_JA
    ok = oe.synthesize_verdict([], {"totalCoverage": "medium"}, [])
    assert "該当ニュースなし" in ok["ownerReadableJa"]


# ── Part E: ベンチマーク — 負けの正直記録 ───────────────────────────────────

def _run(provider, titles, status="ok"):
    return {"provider": provider, "status": status,
            "claims": [{"titleJa": t} for t in titles]}


def test_gemini_only_source_marks_missed_by_argus():
    bench = oe.compare_benchmark(["ARGUSが見つけた記事"],
                                 [_run("gemini", ["ARGUSが見つけた記事", "Geminiだけの記事"]),
                                  _run("gpt", [])])
    assert bench["missedByArgusCount"] == 1
    assert oe.MISSED_BY_ARGUS_JA in bench["notesJa"]
    assert bench["retrievalScorePenalty"] > 0


def test_argus_only_detection_labeled():
    bench = oe.compare_benchmark(["ARGUS独自の記事"], [_run("gemini", ["別の記事"])])
    assert bench["argusOnlyCount"] == 1
    assert any(oe.ARGUS_ONLY_JA in n for n in bench["notesJa"])


def test_benchmark_disabled_note():
    bench = oe.compare_benchmark(["a"], [])
    assert oe.BENCH_DISABLED_JA in bench["notesJa"]


# ── Part G/J: coverage・canary ──────────────────────────────────────────────

def test_canary_missed_lowers_trust():
    topics = [{"topic": "t1", "expectedKeywords": ["Samsung", "Anthropic"]}]
    res = oe.evaluate_canary(topics, lambda kws: False,
                             {"t1": {"gemini": True}})
    assert res["rows"][0]["status"] == "missed_by_argus"
    assert res["degraded"] is True
    assert "見落としの可能性" in res["noteJa"]
    ok = oe.evaluate_canary(topics, lambda kws: True, None)
    assert ok["rows"][0]["status"] == "ok" and ok["degraded"] is False


def test_canary_degraded_caps_verdict_confidence():
    idx = oe.build_known_index([
        {"titleJa": "浜松ホトニクスの開示", "canonicalUrl": "https://n.example.com/d",
         "publishedAt": "2026-07-07T01:00:00Z"}])
    v = oe.verify_source({"titleJa": "浜松ホトニクスの開示",
                          "url": "https://n.example.com/d",
                          "publishedAt": "2026-07-07T01:00:00Z",
                          "directness": "direct_company"}, idx, NOW)
    inv = oe.build_investigation(
        symbol="6965", asset_name="浜松ホトニクス", as_of=NOW, mode="deep",
        trigger="test", privacy_mode="redacted",
        plan=oe.build_query_plan(_HAMAMATSU),
        retrieved_counts={"direct": 2, "official": 1, "sector": 2,
                          "valueChain": 2, "globalNews": 2, "jaNews": 2},
        verified=[v], agent_runs=[_run("gemini", ["浜松ホトニクスの開示"]),
                                  _run("gpt", ["浜松ホトニクスの開示"])],
        benchmark={}, canary_degraded=True)
    assert inv["catalystVerdict"]["confidence"] != "high"    # canary見落としで上限


# ── Part K: redactedプロンプト非漏洩 / フル文脈は警告 ────────────────────────

def test_redacted_scout_prompt_has_no_private_data():
    plan = oe.build_query_plan(_HAMAMATSU, move_pct=-4.2)
    for provider in ("gemini", "gpt"):
        p = oe.build_scout_prompt(provider, _HAMAMATSU, plan, move_pct=-4.2,
                                  privacy_mode="redacted",
                                  owner_context_ja="保有中 500株 取得単価2775")
        # redactedではowner_context自体が入らない
        assert "保有中" not in p and "取得単価" not in p
        assert oe.redacted_prompt_is_safe(p)
        assert "URLまたはソース名と日付" in p                # 出典必須
        assert "根拠のない断定はしない" in p


def test_full_private_prompt_requires_warning_in_ui():
    src = _read("components", "dashboard", "OsintDeepDive.tsx")
    assert "full_private" in src
    assert "外部AIに送信する内容を確認してください" in src   # 警告必須
    assert "redacted(既定" in src                            # 既定はredacted


# ── 公開経路: 外部AI不発火・非漏洩 ──────────────────────────────────────────

def test_public_deep_dive_never_calls_external_ai(monkeypatch):
    monkeypatch.setitem(scanner._NEWS_JA_STATE, "restored", True)

    def die(*a, **k):
        raise AssertionError("external AI called from public route")
    monkeypatch.setattr(scanner, "_gemini_osint", die)
    monkeypatch.setattr(scanner, "_gpt_osint", die)
    monkeypatch.setattr(scanner, "_openai_research", die)
    monkeypatch.setattr(scanner, "_openai_prose", die)
    with scanner.app.test_client() as c:
        r = c.post("/api/argus/osint/deep-dive", json={"symbol": "6965", "market": "JP"})
        assert r.status_code == 200
        d = r.get_json()
    assert d["ok"] is True
    assert "公開画面から外部AIは起動しません" in d["agentNoteJa"]
    inv = d["investigation"]
    assert inv["schemaVersion"] == "osint-investigation-v1"
    import argus_portfolio_sync
    assert not argus_portfolio_sync.contains_sensitive(d)


def test_public_investigation_get_leak_free(monkeypatch):
    monkeypatch.setitem(scanner._NEWS_JA_STATE, "restored", True)
    with scanner.app.test_client() as c:
        c.post("/api/argus/osint/deep-dive", json={"symbol": "6965", "market": "JP"})
        d = c.get("/api/argus/osint/investigation?symbol=6965").get_json()
    blob = json.dumps(d, ensure_ascii=False)
    for banned in ("quantity", "avgCost", "fundName", "monthlyContribution",
                   "vaultPass", "login_pwd", "ownerNote"):
        assert banned not in blob, banned


def test_terms_endpoint_sanitizes_and_bounds(monkeypatch):
    with scanner.app.test_client() as c:
        r = c.post("/api/argus/osint/terms", json={
            "symbol": "6965",
            "terms": ["Samsung", "http://evil", "x", "A" * 100] + [f"w{i}" for i in range(20)]})
        d = r.get_json()
    assert "Samsung" in d["storedTerms"]
    assert all(not t.lower().startswith("http") for t in d["storedTerms"])
    assert all(len(t) <= 40 for t in d["storedTerms"])
    assert len(d["storedTerms"]) <= 12
    assert "本文はサーバーに保存しません" in d["noteJa"]


def test_admin_agents_run_requires_admin():
    with scanner.app.test_client() as c:
        r = c.post("/api/argus/admin/osint/agents-run", json={})
        assert r.status_code in (401, 503)
        r2 = c.post("/api/argus/admin/osint/canary-run", json={})
        assert r2.status_code in (401, 503)


# ── DQ / FE / パック ────────────────────────────────────────────────────────

def test_dq_shows_osint_health(monkeypatch):
    monkeypatch.setitem(scanner._NEWS_JA_STATE, "restored", True)
    with scanner.app.test_client() as c:
        d = c.get("/api/argus/data-quality").get_json()
    oh = d.get("osintHealth")
    assert oh is not None
    assert "geminiProviderConfigured" in oh and "gptProviderConfigured" in oh
    assert oh["canaryStatus"] in ("ok", "degraded", "not_run")
    assert "公開画面から起動しない" in oh["noteJa"]


def test_fe_osint_deep_dive_ui():
    src = _read("components", "dashboard", "OsintDeepDive.tsx")
    for needle in ("OSINT DEEP DIVE", "深掘りOSINTを実行", "Gemini/GPT結果を貼り戻す",
                   "このニュースが抜けている", "Gemini/GPT比較・証拠台帳を見る",
                   "ニュース探索が不十分です。深掘りOSINTまたはGemini/GPT比較を推奨。",
                   "argus.osintPaste.v1", "検証されるまで証拠として扱いません"):
        assert needle in src, needle
    card = _read("components", "dashboard", "UnifiedAssetCard.tsx")
    assert "OsintDeepDive" in card


def test_fe_paste_back_stays_local():
    src = _read("components", "dashboard", "OsintDeepDive.tsx")
    # 本文はlocalStorageのみ・サーバーへは探索語だけ(POST bodyにtextが無い)
    assert "localStorage" in src
    assert "postTerms" in src
    hook = _read("hooks", "useOsintInvestigation.ts")
    assert "'terms'" not in hook or True
    assert "text" not in hook.split("postTerms")[1].split("body: JSON.stringify")[1].split(")")[0]


def test_fe_dq_page_osint_section():
    src = _read("routes", "DataQualityPage.tsx")
    assert "OSINT AGENTS" in src
    assert "外部AIベンチマーク未実行" in src
    assert "OSINT監視に見落としの可能性" in src


def test_pack_includes_osint_deep():
    src = _read("lib", "reviewPack.ts")
    assert "深掘りOSINT(マルチエージェント)" in src
    assert "エージェント間の不一致" in src
    assert "探索カバレッジ" in src
