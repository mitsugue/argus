"""The headline store is newest-first everywhere (2026-11-15).

Per-symbol Google News used to be appended and trimmed from the head, which
threw away the newest general RSS headline whenever the store was full, while
the market-position memory and the Japan news list read the store reversed —
i.e. its oldest end.
"""
import pathlib
import re

import scanner


def _row(title):
    return {"title": title, "canonicalUrl": "https://example.invalid/" + title,
            "publishedAt": "2026-11-15T00:00:00Z"}


def test_symbol_news_goes_to_the_front_and_keeps_the_newest_headline(monkeypatch):
    store = [{"title": f"rss-{i}", "intelligenceId": f"r{i}"}
             for i in range(scanner._INTEL_STORE_MAX)]          # rss-0 is newest
    monkeypatch.setattr(scanner, "_INTEL_STORE", store)
    monkeypatch.setattr(scanner, "_JP_STOCK_NEWS_CACHE", {})
    monkeypatch.setattr(scanner, "_google_news_jp_rss", lambda q: [_row("jp-a"), _row("jp-b")])
    assert scanner._jp_stock_news_intel([("7203", "トヨタ")]) == 2
    titles = [it["title"] for it in scanner._INTEL_STORE]
    assert len(titles) == scanner._INTEL_STORE_MAX
    assert set(titles[:2]) == {"jp-a", "jp-b"}
    assert "rss-0" in titles                                   # the freshest RSS stays
    assert f"rss-{scanner._INTEL_STORE_MAX - 1}" not in titles  # the oldest goes


def test_us_symbol_news_goes_to_the_front(monkeypatch):
    store = [{"title": f"rss-{i}"} for i in range(scanner._INTEL_STORE_MAX)]
    monkeypatch.setattr(scanner, "_INTEL_STORE", store)
    monkeypatch.setattr(scanner, "_US_STOCK_NEWS_CACHE", {})
    monkeypatch.setattr(scanner, "_google_news_us_rss", lambda q: [_row("us-a")])
    assert scanner._us_stock_news_intel([("AAPL", "Apple")]) == 1
    titles = [it["title"] for it in scanner._INTEL_STORE]
    assert titles[0] == "us-a" and "rss-0" in titles


def test_no_reader_or_writer_treats_the_store_as_oldest_first():
    src = pathlib.Path(scanner.__file__).read_text(encoding="utf-8")
    assert "_INTEL_STORE.append(" not in src
    assert not re.search(r"del _INTEL_STORE\[:", src)
    assert not re.search(r"reversed\(list\(_INTEL_STORE\)\)", src)
