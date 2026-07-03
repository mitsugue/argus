"""ARGUS V11.5.3 — investment universe / source universe / discovery resolution /
watchtower plan + endpoints."""
import json
import argus_caos_source_universe as SRC
import argus_caos_watchtower_plan as PLAN
import argus_investment_universe as IU
import scanner

NOW = "2026-07-03T06:00:00Z"

REQUIRED = ["JP_EQUITY", "US_EQUITY", "GOLD_GLD", "BONDS_TLT", "REITS_XLRE",
            "CRYPTO_BTC_ETH", "FX_USDJPY", "CASH", "FUND_ACCUMULATION"]


class _Boom(BaseException):
    pass


def _forbid(monkeypatch):
    def boom(*a, **k):
        raise _Boom("FORBIDDEN fetch/LLM on public GET")
    for name in ("_fetch_public_text", "_translate_headlines_ja", "_openai_prose",
                 "_openai_research", "_google_news_jp_rss", "_google_news_us_rss",
                 "_finnhub_catalyst", "get_market_news", "collect_institutional_intel"):
        if hasattr(scanner, name):
            monkeypatch.setattr(scanner, name, boom)


# ── investment universe ──────────────────────────────────────────────────────

def test_universe_has_all_required_classes():
    u = IU.build_universe(NOW)
    classes = {c["assetClass"] for c in u["assetClasses"]}
    for ac in REQUIRED:
        assert ac in classes, ac
    # the three Core Portfolio accumulation funds
    codes = {f["fundCode"] for f in u["funds"]}
    assert {"EMAXIS-N225", "EMAXIS-SP500", "EMAXIS-ACWI"} <= codes
    for f in u["funds"]:
        assert f["decisionMode"] == "dca_policy"


def test_asset_class_of_symbol():
    assert IU.asset_class_of_symbol("GLD") == "GOLD_GLD"
    assert IU.asset_class_of_symbol("TLT") == "BONDS_TLT"
    assert IU.asset_class_of_symbol("XLRE") == "REITS_XLRE"
    assert IU.asset_class_of_symbol("BTC") == "CRYPTO_BTC_ETH"
    assert IU.asset_class_of_symbol("USDJPY") == "FX_USDJPY"
    assert IU.asset_class_of_symbol("7203", "JP") == "JP_EQUITY"
    assert IU.asset_class_of_symbol("NVDA", "US") == "US_EQUITY"
    assert IU.asset_class_of_symbol("EMAXIS-ACWI", "FUND") == "FUND_ACCUMULATION"


# ── source universe ──────────────────────────────────────────────────────────

def test_source_universe_covers_every_class():
    u = SRC.build_universe({}, NOW)
    for ac in REQUIRED:
        assert u["sourcesByAssetClass"].get(ac), f"no sources for {ac}"


def test_google_news_is_discovery_layer_only():
    u = SRC.build_universe({}, NOW)
    for sid in ("google_news_jp", "google_news_us"):
        s = next(x for x in u["sources"] if x["sourceId"] == sid)
        assert s["isDiscoveryLayer"] is True
        assert s["sourceTier"] == "aggregator_discovery"
        assert s["canConfirmCause"] is False
        assert s["canBePrimaryLead"] is False


def test_licensed_sources_marked_unavailable():
    u = SRC.build_universe({}, NOW)
    s = next(x for x in u["sources"] if x["sourceId"] == "wsj_ft_barrons")
    assert s["status"] == "requires_contract"
    assert s["rightsClass"] == "licensed_unavailable"
    assert s["collectionMethod"] == "disabled"          # never scraped


def test_nikkei_is_public_metadata_not_fulltext():
    u = SRC.build_universe({}, NOW)
    s = next(x for x in u["sources"] if x["sourceId"] == "nikkei_web")
    assert s["rightsClass"] == "public_metadata"
    assert any("本文" in l for l in s["limitationsJa"])


def test_api_source_status_follows_configuration():
    live = SRC.build_universe({"JQUANTS_API_KEY": True}, NOW)
    off = SRC.build_universe({}, NOW)
    assert next(x for x in live["sources"] if x["sourceId"] == "jquants_tdnet")["status"] == "live"
    assert next(x for x in off["sources"] if x["sourceId"] == "jquants_tdnet")["status"] == "not_configured"


# ── discovery resolution ─────────────────────────────────────────────────────

def test_google_news_nikkei_resolves_to_nikkei():
    r = SRC.resolve_publisher("ソフトバンクG株価下げ渋る - 日本経済新聞",
                              "google_news_jp", "https://news.google.com/x")
    assert r["sourceFamily"] == "nikkei"
    assert r["sourceTier"] == "reputable_financial_media"
    assert r["rightsClass"] == "public_metadata"
    assert r["isDiscoveryLayer"] is True
    assert r["canConfirmCause"] is False                # aggregator item ≠ confirmation
    assert r["canBePrimaryLead"] is True


def test_google_news_reuters_resolves_to_wire():
    r = SRC.resolve_publisher("SoftBank resumes talks - Reuters", "google_news_us", "")
    assert r["sourceFamily"] == "reuters"
    assert r["sourceTier"] == "wire_service"


def test_unknown_seo_site_is_weak_signal():
    r = SRC.resolve_publisher("【衝撃】この株が10倍になる理由 - 株プロ最強ナビ", "google_news_jp", "")
    assert r["weakSignal"] is True
    assert r["canBePrimaryLead"] is False
    assert r["canConfirmCause"] is False


def test_video_social_is_weak_signal():
    r = SRC.resolve_publisher("株の解説動画", "", "https://www.youtube.com/watch?v=x")
    assert r["weakSignal"] is True


def test_syndicated_copies_count_one_family():
    items = [{"title": "Fed holds - Reuters", "source": "google_news_us", "url": ""},
             {"title": "Fed holds rates steady", "source": "Reuters", "url": "https://reuters.com/x"},
             {"title": "Fed decision - 日本経済新聞", "source": "google_news_jp", "url": ""}]
    assert SRC.corroboration_family_count(items) == 2    # reuters(×2→1) + nikkei


# ── watchtower plan ──────────────────────────────────────────────────────────

def _plan(movers=None, wl_jp=None, wl_us=None, events=None):
    src = SRC.build_universe({"FINNHUB_API_KEY": True, "JQUANTS_API_KEY": True,
                              "FRED_API_KEY": True, "TWELVEDATA_API_KEY": True}, NOW)
    return PLAN.build_plan(watchlist_jp=wl_jp or [], watchlist_us=wl_us or [],
                           movers=movers or [], macro_events=events or [],
                           universe_sources=src["sources"], now_iso=NOW)


def test_plan_includes_core_portfolio_baseline():
    p = _plan()
    classes = {t["assetClass"] for t in p["targets"]}
    for ac in ("GOLD_GLD", "BONDS_TLT", "REITS_XLRE", "CRYPTO_BTC_ETH",
               "FX_USDJPY", "CASH", "FUND_ACCUMULATION"):
        assert ac in classes, ac
    # gold/bonds/fx/crypto exist WITHOUT being on any watchlist
    assert any(t["symbol"] == "GLD" for t in p["targets"])
    assert any(t["symbol"] == "USDJPY" for t in p["targets"])


def test_plan_movers_urgent_watchlist_high():
    p = _plan(movers=[{"symbol": "5803", "market": "JP", "changePct": -8.0,
                       "name": "フジクラ", "causeStatus": "no_lead_yet"}],
              wl_us=[{"symbol": "NVDA", "name": "NVIDIA"}])
    mover = next(t for t in p["targets"] if t["symbol"] == "5803")
    assert mover["priority"] == "urgent" and mover["reason"] == "active_mover"
    wl = next(t for t in p["targets"] if t["symbol"] == "NVDA")
    assert wl["priority"] == "high" and wl["reason"] == "watchlist"
    assert mover["refreshCadenceMin"] <= wl["refreshCadenceMin"]


def test_plan_cash_is_posture_not_news():
    p = _plan()
    cash = next(t for t in p["targets"] if t["assetClass"] == "CASH")
    assert any("姿勢クラス" in l for l in cash["limitationsJa"])


def test_plan_funds_inherit_no_direct_trading():
    p = _plan()
    fund = next(t for t in p["targets"] if t["assetClass"] == "FUND_ACCUMULATION")
    assert any("dca_policy" in l or "売買判断しない" in l for l in fund["limitationsJa"])


# ── endpoints (public cache-only, admin gated) ───────────────────────────────

def test_endpoints_public_no_fetch(monkeypatch):
    _forbid(monkeypatch)
    monkeypatch.setitem(scanner._NEWS_JA_STATE, "restored", True)
    monkeypatch.setitem(scanner._MOVER_CAUSES_STATE, "restored", True)
    with scanner.app.test_client() as c:
        for p in ("/api/argus/investment-universe", "/api/argus/caos/source-universe",
                  "/api/argus/caos/watchtower-plan", "/api/argus/caos-watchtower/status"):
            r = c.get(p)
            assert r.status_code == 200, p
    # universe endpoint carries every Core Portfolio class
    with scanner.app.test_client() as c:
        d = c.get("/api/argus/investment-universe").get_json()
    assert {x["assetClass"] for x in d["assetClasses"]} >= set(REQUIRED)


def test_watchtower_status_shape(monkeypatch):
    _forbid(monkeypatch)
    monkeypatch.setitem(scanner._NEWS_JA_STATE, "restored", True)
    with scanner.app.test_client() as c:
        d = c.get("/api/argus/caos-watchtower/status").get_json()
    assert d["schemaVersion"] == "caos-watchtower-status-v1"
    for ac in REQUIRED:
        assert ac in d["coverageByAssetClass"], ac
    assert isinstance(d["sources"], list) and isinstance(d["alerts"], list)
    assert "near-real-time" in d["noteJa"]              # no perfect-real-time claim


def test_admin_refresh_requires_token():
    with scanner.app.test_client() as c:
        assert c.post("/api/argus/admin/caos-watchtower/refresh").status_code in (401, 503)


def test_no_forbidden_keys(monkeypatch):
    _forbid(monkeypatch)
    monkeypatch.setitem(scanner._NEWS_JA_STATE, "restored", True)
    with scanner.app.test_client() as c:
        for p in ("/api/argus/investment-universe", "/api/argus/caos/source-universe",
                  "/api/argus/caos-watchtower/status"):
            blob = json.dumps(c.get(p).get_json(), ensure_ascii=False).lower()
            for bad in ('"prompt":', '"messages":', '"rawproviderbody":', '"holdings":',
                        '"apikey":', '"api_key":', '"pnl":', '"costbasis":'):
                assert bad not in blob, f"{bad} in {p}"
