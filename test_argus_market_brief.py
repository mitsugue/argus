"""v13.5.32 — MARKET SITUATION BRIEF (NOW/WHY/NEXT) tests."""
import argus_market_brief as mb

import scanner


def _news(severity="HIGH", confirmed=False, direction=None, ja="米長期金利が上昇",
          family="US_TREASURY"):
    return {
        "severity": severity, "staleness": "FRESH_UPDATE",
        "confirmationState": "MARKET_CONFIRMED" if confirmed
        else "MARKET_CONFIRMATION_PENDING",
        "headlineJa": ja, "sourceFamily": family, "sourceLabelJa": "米財務省",
        "impactDirection": {
            "directionByTarget": direction or {"growth": "BEARISH"},
            "transmissionJa": "米長期金利↑→割引率上昇→高PER圧迫",
        },
    }


def test_compose_brief_orders_facts_and_tags_verification():
    brief = mb.compose_brief(
        now_iso="2026-08-26T00:00:00Z",
        market_view_summary={"label": "反転:混在・証拠評価5/7"},
        shock_events=[{"severity": "HIGH", "headlineJa": "米30年金利の急騰",
                       "whyJa": "財政懸念による債券売り"}],
        news_events=[_news(confirmed=True)],
        imminent_events=[{"title": "FOMC", "countdown": "D-1",
                          "displayImpact": "critical"}],
        next_events=[{"title": "米CPI", "countdown": "D-7"}])
    assert brief["schemaVersion"] == mb.BRIEF_SCHEMA
    assert brief["sdaAuthority"] is False
    assert brief["automaticAiCalls"] == 0
    priorities = [f["priority"] for f in brief["facts"]]
    assert priorities == sorted(priorities)          # P0 first, P3 last
    assert any(f["verification"] == "CORROBORATED" for f in brief["facts"])
    assert any(f["verification"] == "VERIFIED" for f in brief["facts"])
    assert brief["chips"]["nextEvent"].startswith("FOMC")
    assert "弱気材料が優勢" == brief["chips"]["news"]
    assert brief["now"] and brief["why"] and brief["next"]
    assert brief["hasCritical"] is False
    joined = str(brief)
    for banned in mb._FORBIDDEN_BRIEF_PATTERNS:
        assert banned not in joined


def test_compose_brief_is_honest_with_empty_inputs():
    brief = mb.compose_brief(now_iso="2026-08-26T00:00:00Z")
    assert "大きな新規材料は検知していません" in brief["now"]
    assert brief["chips"]["nextEvent"] == "直近の重要イベントなし"
    assert brief["chips"]["mainRisk"] == "特定の集中リスク検知なし"
    assert brief["aiText"] is None


def test_compose_brief_flags_critical_for_sol():
    brief = mb.compose_brief(
        now_iso="2026-08-26T00:00:00Z",
        news_events=[_news(severity="CRITICAL")])
    assert brief["hasCritical"] is True


def test_validate_ai_brief_rejects_invented_numbers_and_orders():
    facts = ["米長期金利が上昇（30年債 4.9%）", "FOMC D-1"]
    ok = mb.validate_ai_brief(
        {"nowJa": "金利上昇が重石。FOMC通過待ち。",
         "whyJa": "30年債 4.9%の高止まりが割引率を押し上げ。",
         "nextJa": "FOMC結果と金利の反応を確認。"}, facts)
    assert ok and "4.9" in ok["whyJa"]
    assert mb.validate_ai_brief(
        {"nowJa": "上昇確率72%とみられる。", "whyJa": "a", "nextJa": "b"},
        facts) is None
    assert mb.validate_ai_brief(
        {"nowJa": "今すぐ買いに行くべき局面。", "whyJa": "a", "nextJa": "b"},
        facts) is None
    assert mb.validate_ai_brief(
        {"nowJa": "指数は5.5%下落した。", "whyJa": "a", "nextJa": "b"},
        facts) is None                              # 5.5はfactに無い
    assert mb.validate_ai_brief({"nowJa": "x" * 300, "whyJa": "a",
                                 "nextJa": "b"}, facts) is None
    assert mb.validate_ai_brief(None, facts) is None


def test_market_brief_route_is_cached_only_and_public_safe(monkeypatch):
    monkeypatch.setattr(scanner, "_important_events_data", lambda: {
        "events": [{"title": "米CPI", "countdown": "D-7"}],
        "imminent": [{"title": "FOMC", "countdown": "D-1",
                      "displayImpact": "critical"}]})
    monkeypatch.setattr(scanner, "get_market_shock", lambda: {"events": []})
    monkeypatch.setattr(scanner, "_brief_market_view_summary",
                        lambda: {"label": "反転:混在"})
    monkeypatch.setattr(scanner, "_brief_news_events",
                        lambda: [_news(confirmed=True)])

    def _forbid_llm(*a, **k):
        raise AssertionError("public GET must never call the LLM")
    monkeypatch.setattr(scanner, "_openai_prose", _forbid_llm)
    scanner._MARKET_BRIEF["data"] = None
    scanner._MARKET_BRIEF["composedAt"] = 0.0
    scanner._MARKET_BRIEF["aiFactsHash"] = None
    try:
        response = scanner.app.test_client().get("/api/argus/market-brief")
        body = response.get_json()
        assert response.status_code == 200
        assert body["sdaAuthority"] is False
        assert body["aiText"] is None                # no LLM on public path
        assert body["chips"]["nextEvent"].startswith("FOMC")
        serialized = str(body).lower()
        for leak in ("holdings", "apikey", "x-api-key", "password"):
            assert leak not in serialized
    finally:
        scanner._MARKET_BRIEF["data"] = None
        scanner._MARKET_BRIEF["composedAt"] = 0.0


def test_market_brief_refresh_polishes_with_ai_and_caches_by_facts(monkeypatch):
    monkeypatch.setattr(scanner, "_important_events_data",
                        lambda: {"events": [], "imminent": []})
    monkeypatch.setattr(scanner, "get_market_shock", lambda: {"events": []})
    monkeypatch.setattr(scanner, "_brief_market_view_summary",
                        lambda: {"label": "反転:混在"})
    monkeypatch.setattr(scanner, "_brief_news_events",
                        lambda: [_news(confirmed=True)])
    calls = []

    def fake_prose(user, max_out=600, system=None, *, purpose="prose",
                   event_id="", event_phase="", model=None, diagnostic=None):
        calls.append((purpose, model))
        if isinstance(diagnostic, dict):
            diagnostic["requestedModel"] = model or scanner._OPENAI_MODEL
            diagnostic["returnedModel"] = "terra-served"
        return {"nowJa": "金利関連の弱気材料が重石。",
                "whyJa": "米財務省発の材料が市場確認済み。",
                "nextJa": "金利と指数の反応を確認。"}

    monkeypatch.setattr(scanner, "_openai_prose", fake_prose)
    scanner._MARKET_BRIEF["data"] = None
    scanner._MARKET_BRIEF["aiFactsHash"] = None
    try:
        brief = scanner._market_brief_refresh(allow_ai=True)
        assert brief["aiText"]["nowJa"].startswith("金利関連")
        assert brief["aiModel"] == "terra-served"
        assert calls == [("market_brief", None)]     # Terra, not Sol
        # unchanged facts → cached aiText, no second LLM call
        scanner._market_brief_refresh(allow_ai=True)
        assert len(calls) == 1
    finally:
        scanner._MARKET_BRIEF["data"] = None
        scanner._MARKET_BRIEF["aiFactsHash"] = None


def test_compose_brief_shows_placeholder_for_untranslated_material_news():
    ev = _news()
    ev["headlineJa"] = "翻訳処理中"
    brief = mb.compose_brief(now_iso="2026-08-26T00:00:00Z", news_events=[ev])
    p0 = [f["text"] for f in brief["facts"] if f["priority"] == "P0"]
    assert any("重要発表（日本語要約 処理中）" in t for t in p0)
    assert "翻訳処理中。" not in brief["now"]


def test_compose_brief_main_risk_uses_shock_headline():
    brief = mb.compose_brief(
        now_iso="2026-08-26T00:00:00Z",
        shock_events=[{"severity": "HIGH", "headlineJa": "米30年債利回り 4.98%",
                       "whyJa": "財政懸念"}])
    assert brief["chips"]["mainRisk"].startswith("米30年債利回り")
