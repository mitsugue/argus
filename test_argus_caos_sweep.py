"""ARGUS V11.5.4 — source sweep (pure): block detection / metadata extraction /
sweep assembly / patrol schedule."""
import argus_caos_patrol as PAT
import argus_caos_source_sweep as SW

NOW = "2026-07-03T06:00:00Z"


# ── block detection ──────────────────────────────────────────────────────────

def test_detect_block_http_codes():
    assert SW.detect_block(200, "<html>ok article body</html>") == "ok"
    assert SW.detect_block(403) == "forbidden"
    assert SW.detect_block(401) == "login_required"
    assert SW.detect_block(404) == "not_found"
    assert SW.detect_block(402) == "subscription_required"
    assert SW.detect_block(None) == "unreachable"
    assert SW.detect_block(503) == "unreachable"


def test_detect_block_paywall_markers():
    assert SW.detect_block(200, "この記事は有料会員限定です。続きを読むには…") == "subscription_required"
    assert SW.detect_block(200, "Subscribe to read the full story") == "subscription_required"
    assert SW.detect_block(200, "", is_accessible_flag=False) == "subscription_required"
    assert SW.detect_block(200, "normal public article", is_accessible_flag=True) == "ok"


# ── metadata extraction (no full text ever) ──────────────────────────────────

_HTML = """
<html><head>
<title>Fallback title | Site</title>
<meta property="og:title" content="フジクラ、AIデータセンター向け光部品の増産を発表" />
<meta property="og:description" content="フジクラは3日、AIデータセンター向け光関連部品の増産投資を発表した。" />
<meta property="article:published_time" content="2026-07-03T04:30:00+09:00" />
<meta property="og:site_name" content="日本経済新聞" />
<link rel="canonical" href="https://www.nikkei.com/article/XYZ/" />
<link rel="amphtml" href="https://www.nikkei.com/amp/XYZ/" />
<script type="application/ld+json">
{"@type":"NewsArticle","headline":"ignored (og wins)","isAccessibleForFree":false}
</script>
</head><body>""" + ("本文" * 5000) + "</body></html>"


def test_extract_article_metadata():
    m = SW.extract_article_metadata(_HTML, "https://example.com/x")
    assert m["title"].startswith("フジクラ、AIデータセンター")
    assert m["publishedAt"].startswith("2026-07-03T04:30")
    assert m["snippet"].startswith("フジクラは3日")
    assert len(m["snippet"]) <= SW.SNIPPET_MAX          # never the body
    assert m["canonicalUrl"] == "https://www.nikkei.com/article/XYZ/"
    assert m["ampUrl"] == "https://www.nikkei.com/amp/XYZ/"
    assert m["publisher"] == "日本経済新聞"
    assert m["isAccessibleForFree"] is False            # publisher's own signal


def test_extract_jsonld_fallback():
    html = """<script type="application/ld+json">
    {"@type":"NewsArticle","headline":"SEC charges crypto exchange",
     "datePublished":"2026-07-03T01:00:00Z","description":"The SEC announced…",
     "publisher":{"@type":"Organization","name":"Reuters"}}</script>"""
    m = SW.extract_article_metadata(html)
    assert m["title"] == "SEC charges crypto exchange"
    assert m["publishedAt"].startswith("2026-07-03")
    assert m["publisher"] == "Reuters"


def test_headline_keywords():
    kws = SW.headline_keywords("フジクラ、データセンター向け光配線で新工場 - 日本経済新聞")
    assert "フジクラ" in kws
    assert not any("日本経済新聞" in k for k in kws)     # publisher suffix stripped


# ── sweep result assembly ────────────────────────────────────────────────────

def _items():
    return [
        {"title": "フジクラ、増産投資を発表 - 日本経済新聞", "publishedAt": "2026-07-03T04:30:00Z",
         "url": "https://news.google.com/x", "source": "google_news_jp",
         "snippet": "増産投資を発表した。"},
        {"title": "適時開示: 生産設備の増強について", "publishedAt": "2026-07-03T04:00:00Z",
         "url": "https://www.release.tdnet.info/x", "source": "tdnet"},
        {"title": "古い解説記事", "publishedAt": "2026-06-19T09:00:00Z",
         "url": "https://example-blog.com/x", "source": "unknown-blog"},
        {"title": "フジクラ、増産投資を発表 - 日本経済新聞", "publishedAt": "2026-07-03T04:30:00Z",
         "url": "https://other.com/dup", "source": "yahoo"},      # dup title → collapsed
    ]


def test_build_sweep_result_classifies_and_dedups():
    r = SW.build_sweep_result(symbol="5803", market="JP", asset_class="JP_EQUITY",
                              now_iso=NOW, searched_sources=["tdnet", "google_news_jp"],
                              found_items=_items(), blocked_sources=[],
                              alternative_sources_checked=[], elapsed_ms=1200)
    assert r["schemaVersion"] == "caos-source-sweep-v1"
    assert len(r["foundItems"]) == 3                     # dup collapsed
    assert len(r["freshItems"]) == 2                     # old article excluded
    assert any(i["sourceTier"] == "official_regulatory" for i in r["officialItems"])
    assert r["latestFreshLeadJa"].startswith("フジクラ、増産投資")
    assert "突破しない" in " ".join(r["limitationsJa"])


def test_sweep_old_only_says_no_fresh_lead():
    r = SW.build_sweep_result(symbol="5803", market="JP", asset_class="JP_EQUITY",
                              now_iso=NOW, searched_sources=["google_news_jp"],
                              found_items=[{"title": "古い記事だけ",
                                            "publishedAt": "2026-06-19T09:00:00Z",
                                            "source": "google_news_jp"}],
                              blocked_sources=[], alternative_sources_checked=[])
    assert r["latestFreshLeadJa"] == ""                  # old can never be the lead
    assert any("新規材料は見つからなかった" in x for x in r["notFoundJa"])


def test_sweep_weak_signal_cannot_lead():
    r = SW.build_sweep_result(symbol="5803", market="JP", asset_class="JP_EQUITY",
                              now_iso=NOW, searched_sources=["google_news_jp"],
                              found_items=[{"title": "【衝撃】株価10倍か - 謎の株ブログ",
                                            "publishedAt": NOW, "source": "google_news_jp"}],
                              blocked_sources=[], alternative_sources_checked=[])
    assert r["latestFreshLeadJa"] == ""                  # weak signal never leads
    assert r["freshItems"] and r["freshItems"][0]["weakSignal"] is True


def test_sweep_records_blocked_sources():
    r = SW.build_sweep_result(symbol="9984", market="JP", asset_class="JP_EQUITY",
                              now_iso=NOW, searched_sources=["nikkei_web"],
                              found_items=[],
                              blocked_sources=[{"source": "nikkei_web",
                                                "reason": "subscription_required",
                                                "title": "ソフトバンクGの記事タイトル"}],
                              alternative_sources_checked=["tdnet", "google_news_jp"])
    assert r["blockedSources"][0]["reason"] == "subscription_required"
    assert "tdnet" in r["alternativeSourcesChecked"]


# ── patrol schedule ──────────────────────────────────────────────────────────

def _wt_targets():
    return [
        {"targetId": "wt-JP_EQUITY-5803", "assetClass": "JP_EQUITY", "symbol": "5803",
         "name": "フジクラ", "priority": "urgent", "reason": "active_mover", "sources": ["tdnet"]},
        {"targetId": "wt-US_EQUITY-NVDA", "assetClass": "US_EQUITY", "symbol": "NVDA",
         "name": "NVIDIA", "priority": "high", "reason": "watchlist", "sources": []},
        {"targetId": "wt-CRYPTO_BTC_ETH-BTC", "assetClass": "CRYPTO_BTC_ETH", "symbol": "BTC",
         "name": "Bitcoin", "priority": "normal", "reason": "core_portfolio", "sources": []},
    ]


def test_patrol_plan_cadence_and_escalation():
    p = PAT.build_patrol_plan(_wt_targets(), {}, NOW)
    mover = next(t for t in p["targets"] if t["symbol"] == "5803")
    assert mover["priority"] == "critical"               # active mover escalates
    assert mover["refreshCadenceSec"] == 300
    wl = next(t for t in p["targets"] if t["symbol"] == "NVDA")
    assert wl["refreshCadenceSec"] == 900
    base = next(t for t in p["targets"] if t["symbol"] == "BTC")
    assert base["refreshCadenceSec"] == 1800
    assert all(t["stale"] for t in p["targets"])          # never swept → all due


def test_patrol_respects_recent_sweep():
    state = {"JP_EQUITY:5803": {"lastSweepAt": "2026-07-03T05:58:00Z"}}   # 2 min ago
    p = PAT.build_patrol_plan(_wt_targets(), state, NOW)
    mover = next(t for t in p["targets"] if t["symbol"] == "5803")
    assert mover["stale"] is False                        # within 300s cadence
    assert mover["nextSweepAt"] == "2026-07-03T06:03:00Z"


def test_pick_due_targets_split():
    p = PAT.build_patrol_plan(_wt_targets(), {}, NOW)
    picked = PAT.pick_due_targets(p, max_deep=5, max_light=10)
    assert any(t["symbol"] == "5803" for t in picked["deep"])
    assert any(t["symbol"] == "NVDA" for t in picked["light"])
