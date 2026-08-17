"""ARGUS V11.5.2 — explanation request queue + visible translation request queue.

Hard rules under test:
  * public explain-request / translation-request ENQUEUE only — never call an LLM or a
    provider; deduped; rate-limited.
  * admin explain/run + translate-visible are token-gated; drain their queues first.
  * cause-attribution IONQ-like fixture: pending English news carries displayTitleJa
    (JP fallback) + translationQueueEligible; after a fake translate-visible it becomes
    the real Japanese title.
  * translation-status exposes visibleQueue; queues store no article body/prompt/secret.
"""
import json
import re
import argus_news_i18n as NI
import scanner

_EN = re.compile(r"[A-Za-z]")
_JP = re.compile(r"[぀-ヿ㐀-䶵一-鿋]")


class _Boom(BaseException):
    pass


def _forbid(monkeypatch):
    def boom(*a, **k):
        raise _Boom("FORBIDDEN external call on public path")
    for name in ("_translate_headlines_ja", "_openai_prose", "_openai_research",
                 "_cause_explain", "_mover_ai_explain"):
        if hasattr(scanner, name):
            monkeypatch.setattr(scanner, name, boom)


def _restore(monkeypatch):
    monkeypatch.setitem(scanner._NEWS_JA_STATE, "restored", True)
    monkeypatch.setitem(scanner._MC_EXPLAIN_REQ_STATE, "restored", True)
    # isolate the mover-cause store so a persisted (/tmp) IONQ record from another test
    # can't make explain-request read cached_available instead of queued.
    monkeypatch.setitem(scanner._MOVER_CAUSES_STATE, "restored", True)
    monkeypatch.setattr(scanner, "_MOVER_CAUSES", {})


# ── explanation request queue ────────────────────────────────────────────────

def test_explain_request_queues_without_llm(monkeypatch):
    _forbid(monkeypatch)
    _restore(monkeypatch)
    with scanner.app.test_client() as c:
        d = c.post("/api/argus/mover-causes/explain-request",
                   json={"symbol": "IONQ", "market": "US", "context": "cause-stack"}).get_json()
    assert d["schemaVersion"] == "mover-explain-request-v1"
    assert d["status"] == "queued" and d["ok"] is True and d["symbol"] == "IONQ"
    assert scanner._mc_has_explain_request("IONQ", "US")


def test_explain_request_dedupes(monkeypatch):
    _forbid(monkeypatch)
    _restore(monkeypatch)
    with scanner.app.test_client() as c:
        a = c.post("/api/argus/mover-causes/explain-request", json={"symbol": "IONQ", "market": "US"}).get_json()
        b = c.post("/api/argus/mover-causes/explain-request", json={"symbol": "IONQ", "market": "US"}).get_json()
    assert a["status"] == "queued"
    assert b["status"] == "already_queued"          # dedupe, not a second queue entry
    assert len(scanner._MC_EXPLAIN_REQUESTS) == 1


def test_explain_request_rate_limits_new_symbol(monkeypatch):
    _forbid(monkeypatch)
    _restore(monkeypatch)
    with scanner.app.test_client() as c:
        c.post("/api/argus/mover-causes/explain-request", json={"symbol": "AAPL", "market": "US"})
        # simulate the request having been drained, so it's no longer a dedupe hit
        scanner._MC_EXPLAIN_REQUESTS.clear()
        d = c.post("/api/argus/mover-causes/explain-request", json={"symbol": "AAPL", "market": "US"}).get_json()
    assert d["status"] == "rate_limited"


def test_explain_request_invalid(monkeypatch):
    _forbid(monkeypatch)
    _restore(monkeypatch)
    with scanner.app.test_client() as c:
        d = c.post("/api/argus/mover-causes/explain-request", json={"symbol": "", "market": "US"}).get_json()
    assert d["status"] == "invalid" and d["ok"] is False


def test_explain_request_cached_available(monkeypatch):
    _forbid(monkeypatch)
    _restore(monkeypatch)
    today = scanner._ai_now_iso()[:10].replace("-", "")
    monkeypatch.setitem(scanner._MOVER_CAUSES, f"mc-US-NVDA-{today}",
                        {"moverCauseId": f"mc-US-NVDA-{today}", "symbol": "NVDA",
                         "market": "US", "explanationJa": "既にある解説"})
    with scanner.app.test_client() as c:
        d = c.post("/api/argus/mover-causes/explain-request", json={"symbol": "NVDA", "market": "US"}).get_json()
    assert d["status"] == "cached_available"
    assert not scanner._mc_has_explain_request("NVDA", "US")   # nothing queued


def test_admin_explain_run_requires_token():
    with scanner.app.test_client() as c:
        assert c.post("/api/argus/admin/mover-causes/explain/run").status_code in (401, 503)


def test_admin_explain_run_drains_requests_first(monkeypatch):
    _restore(monkeypatch)
    monkeypatch.setattr(scanner, "_scheduled_ai_skip", lambda *args: None)
    monkeypatch.setattr(scanner, "_ARGUS_ADMIN_TOKEN", "tok")
    monkeypatch.setattr(scanner, "_MC_AI_ENABLED", True)
    seen = []

    def fake_explain(sym, mkt, now_iso, force=False):
        seen.append(sym)
        today = now_iso[:10].replace("-", "")
        scanner._MOVER_CAUSES[f"mc-{mkt}-{sym}-{today}"] = {"symbol": sym, "market": mkt,
                                                            "explanationJa": "生成済み"}
        return True
    monkeypatch.setattr(scanner, "_mover_ai_explain", fake_explain)
    monkeypatch.setattr(scanner, "_mover_causes_today", lambda: [])
    scanner._mc_explain_req_add("IONQ", "US", "cause-stack", scanner._ai_now_iso())
    with scanner.app.test_client() as c:
        d = c.post("/api/argus/admin/mover-causes/explain/run",
                   headers={"X-ARGUS-ADMIN-TOKEN": "tok"}, json={}).get_json()
    assert d["ok"] is True and "IONQ" in d["generated"]
    assert "IONQ" in d["drainedRequests"]
    assert not scanner._mc_has_explain_request("IONQ", "US")   # drained after generation


# ── visible translation request queue ────────────────────────────────────────

def test_translation_request_queues_english(monkeypatch):
    _forbid(monkeypatch)
    _restore(monkeypatch)
    monkeypatch.setattr(scanner, "_NEWS_JA_CACHE", {})
    with scanner.app.test_client() as c:
        d = c.post("/api/argus/news/translation-request",
                   json={"context": "cause-stack", "symbol": "IONQ", "market": "US",
                         "items": [{"titleOriginal": "IonQ stock jumps on quantum deal",
                                    "source": "ChartMill"}]}).get_json()
    assert d["schemaVersion"] == "news-translation-request-v1"
    assert d["queued"] == 1 and d["rateLimited"] is False
    assert len(scanner._NEWS_JA_VQUEUE) == 1


def test_translation_request_ignores_japanese(monkeypatch):
    _forbid(monkeypatch)
    _restore(monkeypatch)
    with scanner.app.test_client() as c:
        d = c.post("/api/argus/news/translation-request",
                   json={"context": "x", "items": [{"titleOriginal": "日銀が金利据え置き", "source": "Nikkei"}]}).get_json()
    assert d["queued"] == 0 and d["ignored"] == 1
    assert len(scanner._NEWS_JA_VQUEUE) == 0


def test_translation_request_dedupes(monkeypatch):
    _forbid(monkeypatch)
    _restore(monkeypatch)
    monkeypatch.setattr(scanner, "_NEWS_JA_CACHE", {})
    monkeypatch.setattr(scanner, "_NEWS_JA_VQUEUE_RL_SEC", 0)   # disable throttle for the 2nd POST
    item = {"titleOriginal": "Fed signals a pause on hikes", "source": "AP"}
    with scanner.app.test_client() as c:
        c.post("/api/argus/news/translation-request", json={"context": "a", "items": [item]})
        d = c.post("/api/argus/news/translation-request", json={"context": "a", "items": [item]}).get_json()
    assert d["alreadyQueued"] == 1 and len(scanner._NEWS_JA_VQUEUE) == 1


def test_admin_translate_visible_requires_token():
    with scanner.app.test_client() as c:
        assert c.post("/api/argus/admin/news/translate-visible").status_code in (401, 503)


def test_translate_visible_drains_queue_first(monkeypatch):
    _restore(monkeypatch)
    monkeypatch.setattr(scanner, "_scheduled_ai_skip", lambda *args: None)
    monkeypatch.setattr(scanner, "_ARGUS_ADMIN_TOKEN", "tok")
    monkeypatch.setattr(scanner, "_NEWS_JA_CACHE", {})
    monkeypatch.setattr(scanner, "_translate_headlines_ja",
                        lambda pending: {i: "翻訳:" + t[:12] for i, t in enumerate(pending)})
    title = "IonQ stock jumps on quantum deal"
    NI.visible_queue_add(scanner._NEWS_JA_VQUEUE, [{"titleOriginal": title, "source": "ChartMill"}],
                         scanner._NEWS_JA_CACHE, now_iso=scanner._ai_now_iso())
    with scanner.app.test_client() as c:
        d = c.post("/api/argus/admin/news/translate-visible",
                   headers={"X-ARGUS-ADMIN-TOKEN": "tok"}, json={"max": 10}).get_json()
    assert d["fromQueue"] >= 1 and d["translated"] >= 1
    assert NI.is_translated(title, scanner._NEWS_JA_CACHE)     # now cached
    assert len(scanner._NEWS_JA_VQUEUE) == 0                   # pruned after translate


def test_translation_status_includes_visible_queue(monkeypatch):
    _forbid(monkeypatch)
    _restore(monkeypatch)
    NI.visible_queue_add(scanner._NEWS_JA_VQUEUE,
                         [{"titleOriginal": "CPI runs hotter than expected", "source": "Reuters"}],
                         scanner._NEWS_JA_CACHE, now_iso=scanner._ai_now_iso())
    with scanner.app.test_client() as c:
        d = c.get("/api/argus/news/translation-status").get_json()
    vq = d["visibleQueue"]
    assert vq["queuedCount"] >= 1 and vq["durable"] is False
    assert "visibleQueuedPct" in d["coverage"]
    assert "pendingVisible" in d["samples"] and "translatedRecent" in d["samples"]


# ── IONQ-like cause-attribution regression ───────────────────────────────────

def test_cause_attribution_ionq_pending_then_translated(monkeypatch):
    _restore(monkeypatch)
    monkeypatch.setattr(scanner, "_scheduled_ai_skip", lambda *args: None)
    monkeypatch.setattr(scanner, "_NEWS_JA_CACHE", {})
    monkeypatch.setattr(scanner, "get_company_news",
                        lambda *a, **k: [{"headline": "IonQ shares soar on quantum computing milestone",
                                          "datetime": 1_770_000_000, "source": "ChartMill"}])
    # public GET must not translate
    monkeypatch.setattr(scanner, "_translate_headlines_ja",
                        lambda *a, **k: (_ for _ in ()).throw(_Boom("no LLM on public GET")))
    with scanner.app.test_client() as c:
        d = c.get("/api/argus/cause-attribution?symbol=IONQ&market=US").get_json()
    news = [n for n in (d.get("news") or []) if n.get("titleOriginal", "").startswith("IonQ shares soar")]
    assert news, "expected the IonQ English headline"
    n = news[0]
    assert n["translationStatus"] == "pending"
    assert n.get("translationQueueEligible") is True
    assert _EN.search(n["displayTitleJa"]) is None or _JP.search(n["displayTitleJa"])   # JP fallback, not raw EN
    # now the admin translate-visible fills the cache with a real Japanese title
    monkeypatch.setattr(scanner, "_ARGUS_ADMIN_TOKEN", "tok")
    monkeypatch.setattr(scanner, "_translate_headlines_ja",
                        lambda pending: {i: "アイオンキュー株、量子計算の節目で急騰" for i, _ in enumerate(pending)})
    # enqueue what the UI would auto-queue, then drain
    NI.visible_queue_add(scanner._NEWS_JA_VQUEUE,
                         [{"titleOriginal": n["titleOriginal"], "source": "ChartMill"}],
                         scanner._NEWS_JA_CACHE, now_iso=scanner._ai_now_iso())
    with scanner.app.test_client() as c:
        c.post("/api/argus/admin/news/translate-visible",
               headers={"X-ARGUS-ADMIN-TOKEN": "tok"}, json={"max": 10})
        d2 = c.get("/api/argus/cause-attribution?symbol=IONQ&market=US").get_json()
    n2 = [x for x in (d2.get("news") or []) if x.get("titleOriginal", "").startswith("IonQ shares soar")][0]
    assert n2["translationStatus"] == "translated"
    assert "アイオンキュー" in n2["displayTitleJa"]           # real JA replaces the fallback


def test_no_forbidden_keys_and_no_bodies(monkeypatch):
    _forbid(monkeypatch)
    _restore(monkeypatch)
    NI.visible_queue_add(scanner._NEWS_JA_VQUEUE, [{"titleOriginal": "Tesla cuts prices again", "source": "AP"}],
                         scanner._NEWS_JA_CACHE, now_iso=scanner._ai_now_iso())
    scanner._mc_explain_req_add("IONQ", "US", "cause-stack", scanner._ai_now_iso())
    with scanner.app.test_client() as c:
        for path in ("/api/argus/news/translation-status",):
            blob = json.dumps(c.get(path).get_json(), ensure_ascii=False).lower()
            for bad in ('"prompt":', '"messages":', '"rawproviderbody":', '"holdings":',
                        '"apikey":', '"api_key":', '"pnl":', '"costbasis":'):
                assert bad not in blob, f"{bad} in {path}"
    # queue entries themselves carry only minimal, public-safe fields
    for e in scanner._NEWS_JA_VQUEUE.values():
        assert set(e) <= {"hash", "titleOriginal", "source", "publishedAt", "context",
                          "symbol", "market", "queuedAt", "lastSeenAt"}
