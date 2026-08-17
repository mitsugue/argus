"""ARGUS V12.1.2 — Gap Closure / War Room完成の恒久ガード。

全未回収に理由必須 / still_unresolved_importantのみ超過ブロック / 重複クラスタは
ブロックしない / War Room予算(URL20)+上限到達の明示 / 生件数では超過不可。
"""
import json
import os

import argus_osint_engine as oe
import scanner

WEB = os.path.join(os.path.dirname(__file__), "web", "src")
NOW = "2026-07-08T03:00:00Z"


def _read(*parts):
    return open(os.path.join(WEB, *parts), encoding="utf-8").read()


# ── Part C: 正規化・重複クラスタ ────────────────────────────────────────────

def test_canonical_url_strips_tracking():
    a = oe.canonicalize_url("https://www.reuters.com/tech/a-1?utm_source=x&utm_campaign=y&id=5")
    b = oe.canonicalize_url("https://jp.reuters.com/tech/a-1?id=5")
    assert a == b == "reuters.com/tech/a-1?id=5"


def test_same_utm_url_is_duplicate():
    clusters = oe.cluster_sources([
        {"titleJa": "ARGUSが持つ記事", "url": "https://news.example.com/a?utm_source=rss"}])
    g = oe.resolve_gap({"titleJa": "見出し違いでも同じURLの記事",
                        "url": "https://news.example.com/a"},
                       "gemini", clusters, symbol="6965",
                       investigation_id="inv1", now_iso=NOW)
    assert g["resolutionStatus"] == "duplicate_existing"
    assert oe.DUP_NOTE_JA in g["resolutionReasonJa"]


def test_syndicated_headline_clusters_and_not_blocking():
    clusters = oe.cluster_sources([
        {"titleJa": "浜松ホトニクスが新型光半導体センサーを発表",
         "url": "https://jp.reuters.com/x1", "publishedAt": "2026-07-07"}])
    g = oe.resolve_gap({"titleJa": "浜松ホトニクス、新型光半導体センサー発表",
                        "url": "https://finance.yahoo.com/syndicated?utm_campaign=z"},
                       "gemini", clusters, symbol="6965",
                       investigation_id="inv1", now_iso=NOW)
    assert g["resolutionStatus"] == "duplicate_existing"
    sup = oe.superiority_v2([g], agents_ok=True, argus_only_verified=1,
                            verified_overlap=1, context_advantages=["公式/直接ソース"],
                            coverage_total="medium", verification_rate=0.8)
    assert sup["superiorityStatus"] == "exceeds_gemini"     # 重複はブロックしない


# ── Part A: ギャップ台帳 — 全件に理由 ───────────────────────────────────────

def test_every_gap_has_reason_and_taxonomy():
    clusters = []
    cases = [
        ({"titleJa": "URLのない主張"}, "missing_url"),
        ({"titleJa": "2024年の古い記事", "url": "https://n.example.com/old",
          "publishedAt": "2024-09-13"}, "stale_rejected"),
        ({"titleJa": "検証済みの記事", "url": "https://n.example.com/v",
          "publishedAt": "2026-07-08", "verified": True}, "verified_integrated"),
    ]
    for claim, expected in cases:
        g = oe.resolve_gap(claim, "gemini", clusters, symbol="6965",
                           investigation_id="i", now_iso=NOW)
        assert g["resolutionStatus"] == expected, (claim, g["resolutionStatus"])
        assert g["resolutionReasonJa"]                       # 理由必須
        assert g["ownerReadableJa"]
        assert g["resolutionStatusJa"] == oe.RESOLUTION_JA[expected]


def test_irrelevant_when_no_entity_overlap():
    g = oe.resolve_gap({"titleJa": "全く無関係な農業ニュースの話題",
                        "url": "https://n.example.com/farm", "publishedAt": "2026-07-08"},
                       "gpt", [], symbol="6965", investigation_id="i", now_iso=NOW,
                       theme_entities={"浜松ホトニクス", "光半導体", "フォトニクス"})
    assert g["resolutionStatus"] == "irrelevant"


def test_inaccessible_with_live_meta():
    g = oe.resolve_gap({"titleJa": "浜松ホトニクス関連のペイウォール記事",
                        "url": "https://paywall.example.com/p", "publishedAt": "2026-07-08"},
                       "gemini", [], symbol="6965", investigation_id="i", now_iso=NOW,
                       live_meta={"status": "inaccessible"},
                       theme_entities={"浜松ホトニクス"})
    assert g["resolutionStatus"] == "inaccessible"
    assert "証拠にできない" in g["resolutionReasonJa"]


def test_cap_reached_explicit_reason():
    g = oe.resolve_gap({"titleJa": "浜松ホトニクスの未検証重要記事",
                        "url": "https://n.example.com/imp", "publishedAt": "2026-07-08"},
                       "gemini", [], symbol="6965", investigation_id="i", now_iso=NOW,
                       cap_reached=True, theme_entities={"浜松ホトニクス"})
    assert g["resolutionStatus"] == "still_unresolved_important"
    assert oe.CAP_REACHED_JA in g["resolutionReasonJa"]      # 曖昧な「未回収」でなく明示


def test_gap_summary_breakdown_lines():
    gaps = [
        oe.resolve_gap({"titleJa": "重複記事", "url": "https://a.example.com/1"},
                       "gemini",
                       oe.cluster_sources([{"titleJa": "重複記事", "url": "https://a.example.com/1"}]),
                       symbol="6965", investigation_id="i", now_iso=NOW),
        oe.resolve_gap({"titleJa": "古い話", "url": "https://a.example.com/2",
                        "publishedAt": "2024-01-01"}, "gemini", [],
                       symbol="6965", investigation_id="i", now_iso=NOW),
        oe.resolve_gap({"titleJa": "浜松ホトニクス重要未検証", "url": "https://a.example.com/3",
                        "publishedAt": "2026-07-08"}, "gpt", [],
                       symbol="6965", investigation_id="i", now_iso=NOW,
                       theme_entities={"浜松ホトニクス"}),
    ]
    summ = oe.gap_ledger_summary(gaps)
    assert summ["unresolvedImportant"] == 1
    assert summ["byStatus"]["duplicate_existing"] == 1
    assert summ["byStatus"]["stale_rejected"] == 1
    lines = " / ".join(summ["progressLinesJa"])
    assert "追跡中" in lines and "残存" in lines


# ── Part G: 優位性v2 — 生件数では超過不可 ───────────────────────────────────

def test_raw_count_alone_cannot_exceed():
    # ギャップゼロでも文脈/独自検証の優位が無ければ同等止まり
    sup = oe.superiority_v2([], agents_ok=True, argus_only_verified=0,
                            verified_overlap=0, context_advantages=[],
                            coverage_total="medium", verification_rate=0.9)
    assert sup["superiorityStatus"] == "matches_gemini"


def test_unresolved_important_forces_below():
    g = oe.resolve_gap({"titleJa": "浜松ホトニクス重要未検証", "url": "https://a.example.com/3",
                        "publishedAt": "2026-07-08"}, "gemini", [],
                       symbol="6965", investigation_id="i", now_iso=NOW,
                       theme_entities={"浜松ホトニクス"})
    sup = oe.superiority_v2([g], agents_ok=True, argus_only_verified=5,
                            verified_overlap=3, context_advantages=["公式/直接ソース", "Flow文脈"],
                            coverage_total="strong", verification_rate=0.9)
    assert sup["superiorityStatus"] == "below_gemini"        # どれだけ優位でも未回収が勝つ
    assert oe.GAP_JA in sup["ownerReadableVerdictJa"]
    assert sup["unresolvedItemsJa"]                          # 正確な内訳つき


def test_exceeds_requires_context_advantage():
    dup = oe.resolve_gap({"titleJa": "重複", "url": "https://a.example.com/1"},
                         "gemini",
                         oe.cluster_sources([{"titleJa": "重複", "url": "https://a.example.com/1"}]),
                         symbol="6965", investigation_id="i", now_iso=NOW)
    sup = oe.superiority_v2([dup], agents_ok=True, argus_only_verified=0,
                            verified_overlap=1, context_advantages=["需給文脈"],
                            coverage_total="medium", verification_rate=0.7)
    assert sup["superiorityStatus"] == "exceeds_gemini"
    assert "需給文脈" in sup["ownerReadableVerdictJa"]


# ── Part B: War Room予算 ────────────────────────────────────────────────────

def test_war_room_budget_higher_than_four():
    assert oe.OSINT_BUDGETS["war_room"]["maxUrls"] >= 20
    assert oe.OSINT_BUDGETS["war_room"]["maxLoops"] == 3
    assert oe.OSINT_BUDGETS["deep"]["maxUrls"] > 4
    assert oe.OSINT_BUDGETS["balanced"]["maxUrls"] <= 4
    for m, b in oe.OSINT_BUDGETS.items():
        assert b.get("maxCostLabel"), m                      # 予算はオーナー可視


def test_worker_uses_budget_and_cap_note():
    src = open("scanner.py", encoding="utf-8").read()
    assert "OSINT_BUDGETS.get(meta.get(\"mode\")" in src or "OSINT_BUDGETS.get(meta.get('mode')" in src
    assert "検証上限到達: 残り" in src
    assert "_capReached" in src


# ── Part D: パーサ(markdown表/契約) ─────────────────────────────────────────

def test_markdown_table_parsed():
    tbl = ("| タイトル | URL | 日付 |\n|---|---|---|\n"
           "| 浜松ホトニクスが新製品 | https://n.example.com/a | 2026-07-07 |\n"
           "| Samsung Anthropic chip deal | https://t.example.com/b | 2026-07-06 |\n")
    out, w = oe.parse_scout_output(tbl)
    assert len(out["claims"]) == 2
    assert "markdown_table_extraction" in w
    assert out["claims"][1]["url"] == "https://t.example.com/b"


def test_prompt_contract_fields():
    prof = {"symbol": "6965", "nameJa": "浜松ホトニクス", "nameEn": "", "sector": "",
            "themes": [], "valueChain": [], "competitors": [], "aliases": []}
    p = oe.build_scout_prompt("gemini", prof, oe.build_query_plan(prof),
                              move_pct=None, privacy_mode="redacted")
    for needle in ("whyRelevantJa", "quoteOrParaphraseJa", "whatWouldDisproveJa",
                   "confidence", "unknown", "捏造URL禁止"):
        assert needle in p, needle


def test_no_url_claim_not_evidence_but_targeted():
    # v12.1.4で「噂」はソース欠落でなく未検証仮説に分類(優位性は非ブロック)。
    # 事実主張型(ヘッジ語なし)は従来どおりmissing_urlで標的再探索。
    g = oe.resolve_gap({"titleJa": "URLの無い浜松ホトニクスの噂"}, "gemini", [],
                       symbol="6965", investigation_id="i", now_iso=NOW,
                       theme_entities={"浜松ホトニクス"})
    assert g["resolutionStatus"] == "hypothesis_not_source"
    g2 = oe.resolve_gap({"titleJa": "浜松ホトニクスが新型光半導体を発表"}, "gemini", [],
                        symbol="6965", investigation_id="i", now_iso=NOW,
                        theme_entities={"浜松ホトニクス"})
    assert g2["resolutionStatus"] == "missing_url"
    assert g["followUpQueries"]                              # 標的再探索クエリは生成される


# ── Part E: 標的再探索 ──────────────────────────────────────────────────────

def test_targeted_queries_shapes():
    qs = oe.gap_targeted_queries(
        {"titleJa": "SamsungとAnthropicがカスタムAIチップで提携",
         "url": "https://techcrunch.com/2026/07/07/samsung-anthropic"},
        symbol="6965", name_ja="浜松ホトニクス")
    joined = " / ".join(qs)
    assert "SamsungとAnthropicがカスタムAIチップで提携"[:30] in joined
    assert "techcrunch" in joined
    assert any("6965" in q or "浜松ホトニクス" in q for q in qs)


# ── ルート: verify-gaps / url-verify ────────────────────────────────────────

def test_verify_gaps_route_deterministic_only(monkeypatch):
    monkeypatch.setitem(scanner._NEWS_JA_STATE, "restored", True)
    monkeypatch.setitem(scanner._OSINT_PERSIST_STATE, "restored", True)
    scanner._OSINT_AGENT_QUEUE.clear()
    scanner._OSINT_PROGRESS.clear()

    def die(*a, **k):
        raise AssertionError("external call from verify-gaps")
    monkeypatch.setattr(scanner, "_gemini_osint", die)
    monkeypatch.setattr(scanner, "_gpt_osint", die)
    monkeypatch.setattr(scanner, "_osint_fetch_url_meta", die)   # URL fetchも公開経路から不可
    with scanner.app.test_client() as c:
        c.post("/api/argus/osint/deep-dive", json={"symbol": "6965", "market": "JP"})
        r = c.post("/api/argus/osint/verify-gaps", json={"symbol": "6965"})
        d = r.get_json()
    assert d["ok"] is True
    assert "gapLedger" in d["investigation"]


def test_url_verify_is_enqueue_only(monkeypatch):
    def die(*a, **k):
        raise AssertionError("fetch from public route")
    monkeypatch.setattr(scanner, "_osint_fetch_url_meta", die)
    with scanner.app.test_client() as c:
        r = c.post("/api/argus/osint/url-verify", json={"url": "https://news.example.com/x"})
        d = r.get_json()
        assert d["ok"] is True and d["queued"] >= 1
        bad = c.post("/api/argus/osint/url-verify", json={"url": "javascript:alert(1)"})
        assert bad.status_code == 400


# ── DQ/FE ───────────────────────────────────────────────────────────────────

def test_dq_benchmark_verdict_below(monkeypatch):
    monkeypatch.setitem(scanner._NEWS_JA_STATE, "restored", True)
    monkeypatch.setattr(scanner, "_OSINT_STORE", {
        "6965": {"superiority": {"superiorityStatus": "below_gemini",
                                 "argusMissedImportantCount": 3}}})
    with scanner.app.test_client() as c:
        d = c.get("/api/argus/data-quality").get_json()
    assert d["osintHealth"]["benchmarkVerdictJa"] == \
        "OSINTはGemini基準に未達です。未回収ソースがあります。"


def test_fe_gap_workflow_ui():
    src = _read("components", "dashboard", "OsintDeepDive.tsx")
    for needle in ("ギャップ台帳を見る", "未回収を再探索", "このURLを検証",
                   "重要でないとして除外", "argus.osintGapDismiss.v1",
                   "サーバー判定は不変"):
        assert needle in src, needle
    dq = _read("routes", "DataQualityPage.tsx")
    assert "benchmarkVerdictJa" in dq and "検証上限到達" in dq
