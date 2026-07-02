"""ARGUS V11.5 — macro coverage + reaction + news-translation backend tests."""
import json
import scanner


class _Forbidden(BaseException):
    pass


def _forbid(monkeypatch):
    def boom(*a, **k):
        raise _Forbidden("FORBIDDEN external call from public GET")
    for name in ("_openai_prose", "_openai_research", "_cause_explain", "_bls_nfp_result",
                 "_bls_fetch", "_fred_raw", "get_tdnet_recent", "get_company_news",
                 "get_market_news", "_translate_headlines_ja", "get_rates_snapshot",
                 "get_market_regime_snapshot", "get_catalysts_snapshot"):
        if hasattr(scanner, name):
            monkeypatch.setattr(scanner, name, boom)


def test_result_status_includes_all_codes(monkeypatch):
    _forbid(monkeypatch)
    with scanner.app.test_client() as c:
        d = c.get("/api/argus/macro-events/result-status").get_json()
    assert d["schemaVersion"] == "macro-result-status-v1"
    codes = {s["eventCode"]: s for s in d["sources"]}
    for code in ("NFP", "CPI", "PPI", "FOMC", "PCE", "GDP", "JOLTS", "BOJ", "TREASURY_AUCTION"):
        assert code in codes, code
        assert codes[code]["status"] in ("live", "partial", "not_implemented", "unavailable",
                                         "parse_error", "source_unreachable", "not_run", "rate_limited")
        assert "metricsAvailable" in codes[code]
    assert codes["BOJ"]["status"] == "partial"
    assert codes["TREASURY_AUCTION"]["status"] == "not_implemented"


def test_result_status_public_no_provider(monkeypatch):
    _forbid(monkeypatch)
    with scanner.app.test_client() as c:
        assert c.get("/api/argus/macro-events/result-status").status_code == 200


def test_refresh_market_reaction_requires_token():
    with scanner.app.test_client() as c:
        assert c.post("/api/argus/admin/macro-event-analysis/refresh-market-reaction").status_code in (401, 503)


def test_news_translate_requires_token():
    with scanner.app.test_client() as c:
        assert c.post("/api/argus/admin/news/translate").status_code in (401, 503)


def test_translation_status_public_no_llm(monkeypatch):
    _forbid(monkeypatch)
    monkeypatch.setitem(scanner._NEWS_JA_STATE, "restored", True)
    with scanner.app.test_client() as c:
        d = c.get("/api/argus/news/translation-status").get_json()
    assert d["schemaVersion"] == "news-translation-status-v1"
    assert isinstance(d["cachedCount"], int)


def test_headline_ja_cached_only(monkeypatch):
    # JP passes through; cached English → JA; untranslated English returns English
    # and queues (never calls the LLM on this path).
    import argus_news_i18n as NI
    monkeypatch.setitem(scanner._NEWS_JA_STATE, "restored", True)
    def boom(*a, **k):
        raise _Forbidden("no LLM on headline_ja")
    monkeypatch.setattr(scanner, "_translate_headlines_ja", boom)
    monkeypatch.setattr(scanner, "_NEWS_JA_CACHE",
                        {NI.text_hash("Fed holds rates steady"): {"ja": "FRBが金利を据え置き", "at": "x"}})
    assert scanner._headline_ja("日銀は金利据え置き") == "日銀は金利据え置き"
    assert scanner._headline_ja("Fed holds rates steady") == "FRBが金利を据え置き"
    assert scanner._headline_ja("Apple beats earnings") == "Apple beats earnings"   # not cached → EN


def test_dashboard_reaction_fields_and_missing_data(monkeypatch):
    # released NFP with actual but NO reaction → 市場反応データ未取得 limitation.
    monkeypatch.setitem(scanner._MACRO_ANALYSIS_STATE, "restored", True)
    now = scanner._ai_now_iso()
    rec = {"eventId": "us-nfp-x", "eventCode": "NFP", "eventTimeUtc": "2026-07-02T12:30:00Z",
           "eventDate": "2026-07-02", "displayImpact": "critical", "title": "NFP",
           "pre": {"argusScenarioJa": "x", "generatedAt": "2026-07-02T08:00:00Z"},
           "actual": {"available": True, "headline": "NFP +57K", "metrics": {"nfpChangeK": 57}},
           "post": {"verdict": "not_available", "generatedAt": None},
           "marketReaction": {}}
    monkeypatch.setattr(scanner, "_MACRO_ANALYSIS", {"us-nfp-x": rec})
    _forbid(monkeypatch)
    with scanner.app.test_client() as c:
        d = c.get("/api/argus/dashboard-events?eventCode=NFP").get_json()
    nfp = next(it for it in d["items"] if it["eventCode"] == "NFP")
    assert "marketReaction" in nfp
    assert any("市場反応データ未取得" in x for x in nfp["caos"]["limitationsJa"])


def test_dashboard_reaction_numeric_when_present(monkeypatch):
    monkeypatch.setitem(scanner._MACRO_ANALYSIS_STATE, "restored", True)
    rec = {"eventId": "cpi-x", "eventCode": "CPI", "eventTimeUtc": "2026-07-02T12:30:00Z",
           "eventDate": "2026-07-02", "displayImpact": "high", "title": "CPI",
           "pre": {"argusScenarioJa": "x", "generatedAt": "2026-07-02T08:00:00Z"},
           "actual": {"available": True, "headline": "CPI +0.2%", "metrics": {"headlineCpiMoM": 0.2}},
           "post": {"verdict": "not_available", "generatedAt": None},
           "marketReaction": {"us10yMoveBp": 5.0, "usdJpyMovePct": 0.3, "spyMovePct": -0.8,
                              "riskTone": "risk_off", "window": "same_day", "summaryJa": "same_day反応: 米10年金利+5bp"}}
    monkeypatch.setattr(scanner, "_MACRO_ANALYSIS", {"cpi-x": rec})
    _forbid(monkeypatch)
    with scanner.app.test_client() as c:
        d = c.get("/api/argus/dashboard-events?eventCode=CPI").get_json()
    cpi = next(it for it in d["items"] if it["eventCode"] == "CPI")
    assert cpi["marketReaction"]["us10yMoveBp"] == 5.0
    assert cpi["marketReaction"]["riskTone"] == "risk_off"
    assert cpi["caos"]["marketReactionJa"]                       # summary flows through
    # event-specific impact fallback (CPI cool → 支援)
    assert "支援" in cpi["caos"]["impactCommentJa"] or "限定的" in cpi["caos"]["impactCommentJa"]


def test_no_forbidden_keys(monkeypatch):
    _forbid(monkeypatch)
    with scanner.app.test_client() as c:
        for path in ("/api/argus/dashboard-events", "/api/argus/macro-events/result-status",
                     "/api/argus/news/translation-status"):
            blob = json.dumps(c.get(path).get_json(), ensure_ascii=False).lower()
            for bad in ('"prompt":', '"messages":', '"rawproviderbody":', '"holdings":',
                        '"apikey":', '"api_key":'):
                assert bad not in blob, f"{bad} in {path}"
