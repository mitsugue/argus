"""ARGUS V11.5.1 — Japanese-first news display + AI-explanation-state backend tests.

Hard rules under test:
  * cause-attribution US media headlines never expose raw English as the primary
    display title — displayTitleJa is Japanese (from cache) or a JP fallback.
  * translation-status exposes visible-pending + coverage so the UI can explain
    "why is this still English".
  * admin translate stays token-gated; public GET never calls the LLM.
"""
import json
import re
import argus_news_i18n as NI
import scanner

_EN_ONLY = re.compile(r"[A-Za-z]")
_JP = re.compile(r"[぀-ヿ㐀-䶵一-鿋]")


class _Forbidden(BaseException):
    pass


def _forbid_llm(monkeypatch):
    def boom(*a, **k):
        raise _Forbidden("no LLM / no external fetch on public GET")
    for name in ("_translate_headlines_ja", "_openai_prose", "_openai_research",
                 "_cause_explain"):
        if hasattr(scanner, name):
            monkeypatch.setattr(scanner, name, boom)


def _looks_raw_english(s):
    return bool(_EN_ONLY.search(s or "")) and not _JP.search(s or "")


def test_cause_attribution_us_news_never_raw_english(monkeypatch):
    """US Finnhub headline is English + no translation cache → the primary
    display title must be a JP fallback, and the original preserved separately."""
    _forbid_llm(monkeypatch)
    monkeypatch.setitem(scanner._NEWS_JA_STATE, "restored", True)
    monkeypatch.setattr(scanner, "_NEWS_JA_CACHE", {})   # nothing translated yet
    monkeypatch.setattr(scanner, "get_company_news",
                        lambda *a, **k: [{"headline": "Nvidia shares tumble on China export curbs",
                                          "datetime": 1_770_000_000, "source": "Reuters"}])
    with scanner.app.test_client() as c:
        d = c.get("/api/argus/cause-attribution?symbol=NVDA&market=US").get_json()
    news = d.get("news") or []
    assert news, "expected at least one US media headline"
    for n in news:
        assert not _looks_raw_english(n.get("displayTitleJa")), n
        # original English is preserved for the 原文を見る disclosure
        assert _EN_ONLY.search(n.get("titleOriginal") or n.get("titleEn") or "")
        assert n.get("translationStatus") in ("pending", "translated", "not_needed", "failed")


def test_cause_attribution_us_news_uses_cache_when_present(monkeypatch):
    """When the headline IS in the JA cache, displayTitleJa is the Japanese text."""
    _forbid_llm(monkeypatch)
    monkeypatch.setitem(scanner._NEWS_JA_STATE, "restored", True)
    hl = "Nvidia shares tumble on China export curbs"
    monkeypatch.setattr(scanner, "_NEWS_JA_CACHE",
                        {NI.text_hash(hl[:120]): {"ja": "エヌビディア株、中国輸出規制で急落", "at": "x"}})
    monkeypatch.setattr(scanner, "get_company_news",
                        lambda *a, **k: [{"headline": hl, "datetime": 1_770_000_000, "source": "Reuters"}])
    with scanner.app.test_client() as c:
        d = c.get("/api/argus/cause-attribution?symbol=NVDA&market=US").get_json()
    news = d.get("news") or []
    hit = [n for n in news if "エヌビディア" in (n.get("displayTitleJa") or "")]
    assert hit, news
    assert hit[0]["translationStatus"] == "translated"


def test_cause_attribution_public_no_llm(monkeypatch):
    _forbid_llm(monkeypatch)
    monkeypatch.setitem(scanner._NEWS_JA_STATE, "restored", True)
    monkeypatch.setattr(scanner, "get_company_news",
                        lambda *a, **k: [{"headline": "Apple beats earnings", "datetime": 1_770_000_000,
                                          "source": "Bloomberg"}])
    with scanner.app.test_client() as c:
        # explain=1 must NOT trigger a live LLM call on the public route
        assert c.get("/api/argus/cause-attribution?symbol=AAPL&market=US&explain=1").status_code == 200


def test_translation_status_coverage_fields(monkeypatch):
    _forbid_llm(monkeypatch)
    monkeypatch.setitem(scanner._NEWS_JA_STATE, "restored", True)
    with scanner.app.test_client() as c:
        d = c.get("/api/argus/news/translation-status").get_json()
    assert d["schemaVersion"] == "news-translation-status-v1"
    assert isinstance(d["visiblePendingCount"], int)
    assert isinstance(d["translatedToday"], int)
    assert "visibleTranslatedPct" in d["coverage"]
    assert "allTranslatedPct" in d["coverage"]
    assert isinstance(d["nextTranslateHintJa"], str) and d["nextTranslateHintJa"]


def test_admin_translate_token_gated():
    with scanner.app.test_client() as c:
        assert c.post("/api/argus/admin/news/translate").status_code in (401, 503)
        assert c.post("/api/argus/admin/news/translate", json={"max": 5}).status_code in (401, 503)


def test_no_forbidden_keys_cause_attribution(monkeypatch):
    _forbid_llm(monkeypatch)
    monkeypatch.setitem(scanner._NEWS_JA_STATE, "restored", True)
    monkeypatch.setattr(scanner, "get_company_news",
                        lambda *a, **k: [{"headline": "Tesla recalls", "datetime": 1_770_000_000,
                                          "source": "AP"}])
    with scanner.app.test_client() as c:
        blob = json.dumps(c.get("/api/argus/cause-attribution?symbol=TSLA&market=US").get_json(),
                          ensure_ascii=False).lower()
    for bad in ('"prompt":', '"messages":', '"rawproviderbody":', '"apikey":', '"api_key":'):
        assert bad not in blob, bad
