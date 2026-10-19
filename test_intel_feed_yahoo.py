"""2026-10-19: the Yahoo Finance news feed answered 404 in every collection."""
import scanner


def test_yahoo_feed_is_the_live_per_symbol_headline_feed():
    feeds = {label: (sid, url, kind) for sid, label, url, kind in scanner._INTEL_FEEDS}
    sid, url, kind = feeds["yahoo:finance"]
    assert sid == "yahoo_finance_public" and kind == "rss"
    assert url.startswith("https://feeds.finance.yahoo.com/rss/2.0/headline?s=")
    assert "rssindex" not in url


def test_the_headline_feed_shape_is_parsed():
    xml = ('<?xml version="1.0"?><rss version="2.0"><channel><title>Yahoo</title>'
           '<item><title>Stocks rise</title><link>https://finance.yahoo.com/news/a.html</link>'
           '<pubDate>Mon, 19 Oct 2026 11:00:00 +0000</pubDate></item></channel></rss>')
    rows = scanner._parse_rss(xml, "yahoo_finance_public", "2026-10-19T12:00:00Z")
    assert [r["title"] for r in rows] == ["Stocks rise"]
