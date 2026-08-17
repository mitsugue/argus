"""ARGUS V11.5.4 — investigate-now / patrol-plan / deep-research endpoints.

Hard rules under test: the public POST performs a REAL bounded sweep (not just a
queue), never calls an LLM, never stores full text, rate-limits, and records
searched/blocked/alternative sources. Old-only news → no fresh lead. The deep-
research status detects old-news-as-primary violations (must be empty).
"""
import json
import scanner


class _Boom(BaseException):
    pass


def _no_llm(monkeypatch):
    def boom(*a, **k):
        raise _Boom("LLM forbidden on this path")
    for name in ("_translate_headlines_ja", "_openai_prose", "_openai_research",
                 "_cause_explain", "_mover_ai_explain"):
        if hasattr(scanner, name):
            monkeypatch.setattr(scanner, name, boom)


def _stub_sources(monkeypatch, google_rows=None, tdnet=None, probe=None):
    """Deterministic fetchers: no real network in tests."""
    monkeypatch.setattr(scanner, "_google_news_jp_rss", lambda q: list(google_rows or []))
    monkeypatch.setattr(scanner, "_google_news_us_rss", lambda q: list(google_rows or []))
    monkeypatch.setattr(scanner, "_tdnet_recent_cached_only", lambda: tdnet)
    monkeypatch.setattr(scanner, "get_tdnet_recent", lambda *a, **k: tdnet or {"items": []})
    monkeypatch.setattr(scanner, "_sec_filings", lambda s: ([], "unavailable"))
    monkeypatch.setattr(scanner, "_finnhub_catalyst", lambda s: ({"news": []}, "live"))
    if probe is not None:
        monkeypatch.setattr(scanner, "_probe_article", lambda url, timeout=6: probe)


def _reset(monkeypatch):
    monkeypatch.setitem(scanner._NEWS_JA_STATE, "restored", True)
    monkeypatch.setitem(scanner._MC_EXPLAIN_REQ_STATE, "restored", True)
    monkeypatch.setitem(scanner._MOVER_CAUSES_STATE, "restored", True)
    monkeypatch.setitem(scanner._SWEEP_STATE, "restored", True)
    monkeypatch.setitem(scanner._SWEEP_STATE, "bySymbol", {})
    monkeypatch.setattr(scanner, "_MOVER_CAUSES", {})
    monkeypatch.setattr(scanner, "_INTEL_STORE", [])
    scanner._INVESTIGATE_RL.clear()
    scanner._JP_STOCK_NEWS_CACHE.clear()
    scanner._US_STOCK_NEWS_CACHE.clear()


_FRESH_ROW = {"sourceId": "google_news_jp",
              "title": "フジクラ、増産投資を発表 - 日本経済新聞",
              "canonicalUrl": "https://news.google.com/rss/articles/x",
              "publishedAt": None,  # filled per-test
              "firstDetectedAt": None, "fetchedAt": None}


def _fresh_row(now_iso):
    r = dict(_FRESH_ROW)
    r["publishedAt"] = now_iso
    r["firstDetectedAt"] = now_iso
    return r


def test_investigate_now_sweeps_not_queues(monkeypatch):
    _reset(monkeypatch)
    _no_llm(monkeypatch)
    now = scanner._ai_now_iso()
    _stub_sources(monkeypatch, google_rows=[_fresh_row(now)],
                  probe=("ok", {"title": "フジクラ、増産投資を発表", "publishedAt": now,
                                "snippet": "増産投資を発表した。", "canonicalUrl": "https://nikkei.com/x",
                                "publisher": "日本経済新聞"}, "https://nikkei.com/x"))
    with scanner.app.test_client() as c:
        d = c.post("/api/argus/caos/investigate-now",
                   json={"symbol": "5803", "market": "JP", "context": "cause-stack"}).get_json()
    assert d["schemaVersion"] == "caos-investigate-now-v2"
    assert d["status"] in ("completed", "partial")
    assert d["sweep"]["searchedSources"], "must report what was searched"
    assert "tdnet" in d["sweep"]["searchedSources"]
    assert "google_news_jp" in d["sweep"]["searchedSources"]
    assert len(d["sweep"]["freshItems"]) >= 1              # real result, not a queue ticket
    assert d["moverCauseUpdated"] is True
    assert "次回自動生成で反映" not in (d["messageJa"] or "")   # never the primary result
    # AI explanation is a separate queued path
    assert d["aiExplanation"]["status"] in ("cached", "queued", "not_generated")


def test_investigate_now_no_full_text_stored(monkeypatch):
    _reset(monkeypatch)
    _no_llm(monkeypatch)
    now = scanner._ai_now_iso()
    long_body = "本文" * 100_000
    _stub_sources(monkeypatch, google_rows=[_fresh_row(now)],
                  probe=("ok", {"title": "T", "publishedAt": now,
                                "snippet": ("あ" * 500)[:240], "canonicalUrl": "https://x/",
                                "publisher": "P"}, "https://x/"))
    with scanner.app.test_client() as c:
        d = c.post("/api/argus/caos/investigate-now",
                   json={"symbol": "5803", "market": "JP"}).get_json()
    blob = json.dumps(d, ensure_ascii=False)
    assert long_body[:1000] not in blob
    for it in d["sweep"]["publicTextItems"]:
        assert len(it.get("snippet") or "") <= 240          # extracts only
    # the intel store carries metadata only (no body key at all)
    for it in scanner._INTEL_STORE:
        assert "body" not in it and "fullText" not in it


def test_investigate_now_blocked_triggers_alternatives(monkeypatch):
    _reset(monkeypatch)
    _no_llm(monkeypatch)
    now = scanner._ai_now_iso()
    _stub_sources(monkeypatch, google_rows=[_fresh_row(now)],
                  probe=("subscription_required", {}, "https://nikkei.com/x"))
    with scanner.app.test_client() as c:
        d = c.post("/api/argus/caos/investigate-now",
                   json={"symbol": "5803", "market": "JP"}).get_json()
    assert d["sweep"]["blockedSources"], "blocked source must be recorded"
    assert d["sweep"]["blockedSources"][0]["reason"] == "subscription_required"
    assert d["sweep"]["alternativeSourcesChecked"], "must chase alternatives"


def test_investigate_now_old_only_no_fresh_lead(monkeypatch):
    _reset(monkeypatch)
    _no_llm(monkeypatch)
    old = dict(_FRESH_ROW)
    old["publishedAt"] = "2026-06-19T09:00:00Z"
    old["firstDetectedAt"] = "2026-06-19T09:00:00Z"
    _stub_sources(monkeypatch, google_rows=[old], probe=None)
    monkeypatch.setattr(scanner, "_probe_article",
                        lambda url, timeout=6: ("ok", {}, url))
    with scanner.app.test_client() as c:
        d = c.post("/api/argus/caos/investigate-now",
                   json={"symbol": "5803", "market": "JP"}).get_json()
    assert d["sweep"]["freshItems"] == []
    assert any("新規材料は見つからなかった" in x for x in d["sweep"]["notFoundJa"])
    assert d["bestCurrentLeadJa"] == "最新材料は未確認"       # old never leads


def test_investigate_now_rate_limited(monkeypatch):
    _reset(monkeypatch)
    _no_llm(monkeypatch)
    now = scanner._ai_now_iso()
    _stub_sources(monkeypatch, google_rows=[_fresh_row(now)],
                  probe=("ok", {}, "https://x/"))
    with scanner.app.test_client() as c:
        first = c.post("/api/argus/caos/investigate-now", json={"symbol": "5803", "market": "JP"}).get_json()
        second = c.post("/api/argus/caos/investigate-now", json={"symbol": "5803", "market": "JP"}).get_json()
    assert first["status"] in ("completed", "partial")
    assert second["status"] == "rate_limited"
    assert "確認済み" in (second["messageJa"] or "")


def test_investigate_now_invalid_symbol():
    with scanner.app.test_client() as c:
        d = c.post("/api/argus/caos/investigate-now", json={"symbol": "", "market": "JP"}).get_json()
    assert d["status"] == "error" and d["ok"] is False


def test_patrol_plan_endpoint(monkeypatch):
    _reset(monkeypatch)
    _no_llm(monkeypatch)
    with scanner.app.test_client() as c:
        d = c.get("/api/argus/caos/patrol-plan").get_json()
    assert d["schemaVersion"] == "caos-patrol-plan-v1"
    classes = {t["assetClass"] for t in d["targets"]}
    for ac in ("GOLD_GLD", "BONDS_TLT", "CRYPTO_BTC_ETH", "FX_USDJPY", "CASH"):
        assert ac in classes, ac
    assert all(t["refreshCadenceSec"] >= 300 for t in d["targets"])


def test_deep_research_status_no_violations(monkeypatch):
    _reset(monkeypatch)
    _no_llm(monkeypatch)
    with scanner.app.test_client() as c:
        d = c.get("/api/argus/caos/deep-research/status").get_json()
    assert d["schemaVersion"] == "caos-deep-research-status-v1"
    assert d["violations"] == []                           # gate keeps this empty
    assert "symbolsWithOnlyOldNews" in d


def test_deep_research_detects_violation(monkeypatch):
    """If an old news title ever ends up in bestLeadJa, the audit must flag it."""
    _reset(monkeypatch)
    _no_llm(monkeypatch)
    today = scanner._ai_now_iso()[:10].replace("-", "")
    bad = {"moverCauseId": f"mc-JP-9999-{today}", "symbol": "9999", "market": "JP",
           "asOf": scanner._ai_now_iso(), "causeStatus": "candidate_catalyst",
           "causeStatusJa": "候補", "bestLeadJa": "直接ニュース: 古い記事タイトル",
           "causeCandidates": [{"titleJa": "古い記事タイトル", "category": "direct_news",
                                "role": "background_only", "confidence": 0.15,
                                "timingRelation": "unknown", "corroborationLevel": "single_source",
                                "linkType": "direct_mention", "marketConfirmed": False,
                                "sourceTier": "media", "candidateId": "cand-x",
                                "newsFreshness": {"freshness": "old", "ageHours": 340.0}}],
           "freshness": {}, "refreshPolicy": {}}
    monkeypatch.setattr(scanner, "_MOVER_CAUSES", {bad["moverCauseId"]: bad})
    with scanner.app.test_client() as c:
        d = c.get("/api/argus/caos/deep-research/status").get_json()
    assert any(v["type"] == "old_news_as_primary" for v in d["violations"])


def test_public_get_endpoints_no_fetch(monkeypatch):
    _reset(monkeypatch)
    _no_llm(monkeypatch)
    def boom(*a, **k):
        raise _Boom("no fetch on public GET")
    for name in ("_fetch_public_text", "_google_news_jp_rss", "_google_news_us_rss",
                 "get_tdnet_recent", "_finnhub_catalyst", "_probe_article"):
        monkeypatch.setattr(scanner, name, boom)
    with scanner.app.test_client() as c:
        assert c.get("/api/argus/caos/patrol-plan").status_code == 200
        assert c.get("/api/argus/caos/deep-research/status").status_code == 200


def test_no_forbidden_keys(monkeypatch):
    _reset(monkeypatch)
    _no_llm(monkeypatch)
    now = scanner._ai_now_iso()
    _stub_sources(monkeypatch, google_rows=[_fresh_row(now)], probe=("ok", {}, "https://x/"))
    with scanner.app.test_client() as c:
        d = c.post("/api/argus/caos/investigate-now", json={"symbol": "5803", "market": "JP"}).get_json()
        blob = json.dumps(d, ensure_ascii=False).lower()
    for bad in ('"prompt":', '"messages":', '"rawproviderbody":', '"holdings":',
                '"apikey":', '"api_key":', '"pnl":', '"costbasis":'):
        assert bad not in blob, bad
