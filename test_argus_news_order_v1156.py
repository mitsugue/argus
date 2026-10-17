"""ARGUS V11.5.6 — owner rule: every displayed news list is newest-first
(newest at the top, older as you go down; undated items sink to the bottom)."""
import argus_caos_source_sweep as SW
import scanner

NOW = "2026-07-03T06:00:00Z"


def _ages(items, key):
    return [i.get(key) for i in items]


# ── sweep result lists ───────────────────────────────────────────────────────

def test_sweep_items_newest_first():
    found = [
        {"title": "3日前の記事", "publishedAt": "2026-06-30T06:00:00Z", "source": "google_news_jp"},
        {"title": "1時間前の記事", "publishedAt": "2026-07-03T05:00:00Z", "source": "google_news_jp"},
        {"title": "時刻不明の記事", "publishedAt": None, "source": "google_news_jp"},
        {"title": "10時間前の記事", "publishedAt": "2026-07-02T20:00:00Z", "source": "google_news_jp"},
    ]
    r = SW.build_sweep_result(symbol="5803", market="JP", asset_class="JP_EQUITY",
                              now_iso=NOW, searched_sources=["google_news_jp"],
                              found_items=found, blocked_sources=[],
                              alternative_sources_checked=[])
    titles = [i["title"] for i in r["foundItems"]]
    assert titles == ["1時間前の記事", "10時間前の記事", "3日前の記事", "時刻不明の記事"]
    ages = [i["ageHours"] for i in r["freshItems"]]
    assert ages == sorted(ages)                     # fresh list newest-first too


# ── market news (CaosHub feed) ───────────────────────────────────────────────

def test_market_news_sorted_newest_first(monkeypatch):
    import time as _t
    now = _t.time()
    monkeypatch.setitem(scanner._NEWS_JA_STATE, "restored", True)
    monkeypatch.setattr(scanner, "FINNHUB_API_KEY", "x")
    monkeypatch.setitem(scanner._MARKET_NEWS_CACHE, "data", None)
    monkeypatch.setitem(scanner._MARKET_NEWS_CACHE, "expires", 0.0)

    class _Resp:
        status_code = 200
        def raise_for_status(self):  # noqa: D401
            pass
        def json(self):
            return [
                {"headline": "Old US story", "source": "CNBC", "url": "u1",
                 "datetime": int(now - 20 * 3600)},
                {"headline": "Fresh US story", "source": "Reuters", "url": "u2",
                 "datetime": int(now - 600)},
                {"headline": "Mid US story", "source": "MarketWatch", "url": "u3",
                 "datetime": int(now - 5 * 3600)},
            ]
    monkeypatch.setattr(scanner.requests, "get", lambda *a, **k: _Resp())
    monkeypatch.setattr(scanner, "_translate_headlines_ja", lambda hs: {})
    monkeypatch.setattr(scanner, "_annotate_news_corroboration", lambda items: None)
    # one JP intel item WITH a real timestamp — must interleave by time, not pin to top
    monkeypatch.setattr(scanner, "_INTEL_STORE", [
        {"sourceId": "nhk_business", "lang": "ja", "title": "2時間前の日本のニュース",
         "publishedAt": scanner.datetime.fromtimestamp(now - 2 * 3600, scanner.pytz.utc)
             .strftime("%Y-%m-%dT%H:%M:%SZ"),
         "firstDetectedAt": NOW, "canonicalUrl": "u4"}])
    out = scanner.get_market_news()
    dts = [i.get("datetime") for i in out["items"]]
    dated = [d for d in dts if d is not None]
    assert dated == sorted(dated, reverse=True), f"not newest-first: {dts}"
    # the JP item sits between fresh(10min) and mid(5h) — time order, not source order
    headlines = [i["headline"] for i in out["items"]]
    assert headlines.index("Fresh US story") < headlines.index("2時間前の日本のニュース") \
        < headlines.index("Mid US story") < headlines.index("Old US story")


# ── cause-attribution news ───────────────────────────────────────────────────

def test_cause_attribution_news_newest_first(monkeypatch):
    monkeypatch.setitem(scanner._NEWS_JA_STATE, "restored", True)
    monkeypatch.setattr(scanner, "_NEWS_JA_CACHE", {})
    monkeypatch.setattr(scanner, "get_company_news",
                        lambda *a, **k: [
                            {"headline": "Oldest story about the co", "datetime": 1_751_400_000,
                             "source": "AP"},
                            {"headline": "Newest story about the co", "datetime": int(__import__("time").time()) - 300,
                             "source": "Reuters"},
                        ])
    with scanner.app.test_client() as c:
        d = c.get("/api/argus/cause-attribution?symbol=AAPL&market=US").get_json()
    news = d.get("news") or []
    ages = [(n.get("newsFreshness") or {}).get("ageHours") for n in news]
    dated = [a for a in ages if a is not None]
    assert dated == sorted(dated), f"not newest-first: {ages}"
    # undated items (if any) must be at the tail
    if None in ages:
        assert all(a is None for a in ages[ages.index(None):])
