"""Important received news reaches the integrated view and the market position (2026-10-15).

Production 13.8.108: Nikkei mail arrived and was read, yet the CPI story
(fuel prices lifting CPI, rate-hike worry, falling stocks) never reached the
view. The view read only the twelve most recently processed mails and two
headlines from them; the store held 40 rows (about six hours); themed WATCH
reporting never entered the durable memory; explanatory pieces skipped the
analysis; a digest body was cut at 1800 characters before its split.
"""
import json
import time
from datetime import datetime, timedelta, timezone

import argus_gmail_intake as gi
import argus_market_brief as mb
import argus_news_intelligence as ni
import scanner
from test_argus_news_pipeline import mail, news_env, run_cycle  # noqa: F401  (fixture)


def _iso(hours_ago):
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _event(eid, severity, hours_ago, *, family="INFLATION", headline=None, facts=(), staleness="FRESH"):
    return {"eventId": eid, "severity": severity, "eventType": family, "staleness": staleness,
            "headlineJa": headline or f"見出し {eid}", "sourceReceivedAt": _iso(hours_ago),
            "sourceFamily": "NIKKEI", "facts": list(facts)}


# ── 1. the view reads the important news of the last days, not the last mails ──

def test_selection_keeps_an_older_release_story_ahead_of_later_routine_mail():
    story = _event("cpi", "HIGH", 9, headline="米CPI上振れ、利上げ警戒で株安")
    routine = [_event(f"r{i}", "WATCH", 1 + i * 0.1, family="OTHER_MARKET_RELEVANT") for i in range(20)]
    noise = [_event("info", "INFO", 0.5), _event("old", "HIGH", 80), _event("stale", "HIGH", 1, staleness="STALE")]
    chosen = ni.select_brief_news(routine + [story] + noise, time.time())
    assert chosen[0]["eventId"] == "cpi"
    assert len(chosen) == ni.BRIEF_NEWS_LIMIT
    assert not {"info", "old", "stale"} & {e["eventId"] for e in chosen}
    # Same severity: a themed article before an unthemed one, then newest first.
    themed = _event("themed", "WATCH", 5)
    assert ni.select_brief_news([routine[0], themed], time.time())[0]["eventId"] == "themed"


def test_brief_news_events_reads_the_story_behind_twenty_later_mails(monkeypatch):
    events = {"cpi": _event("cpi", "HIGH", 9, headline="米CPI上振れ、利上げ警戒で株安")}
    order = ["cpi"]
    for i in range(20):
        events[f"r{i}"] = _event(f"r{i}", "WATCH", 1, family="OTHER_MARKET_RELEVANT")
        order.append(f"r{i}")
    monkeypatch.setitem(scanner._NEWS_INTEL, "events", events)
    monkeypatch.setitem(scanner._NEWS_INTEL, "order", order)
    selected = scanner._brief_news_events()
    assert selected[0]["eventId"] == "cpi" and len(selected) == ni.BRIEF_NEWS_LIMIT
    assert len(scanner._brief_news_events(all_stored=True)) == 21


def test_the_event_news_context_is_reused_only_while_its_inputs_are_unchanged(monkeypatch):
    import argus_macro_material
    calls = []
    monkeypatch.setattr(argus_macro_material, "news_context", lambda record, news, **k: calls.append(len(news)) or {"articles": [], "n": len(news)})
    monkeypatch.setitem(scanner._NEWS_INTEL, "events", {"a": _event("a", "HIGH", 1)})
    monkeypatch.setitem(scanner._NEWS_INTEL, "order", ["a"])
    record = {"eventId": "cpi", "eventCode": "CPI"}
    now = "2026-10-15T02:30:10Z"
    first = scanner._event_news_context_cached(record, now_iso=now)
    first["n"] = 99                                          # a caller's change stays its own
    assert scanner._event_news_context_cached(record, now_iso="2026-10-15T02:30:50Z")["n"] == 1
    assert calls == [1]
    scanner._NEWS_INTEL["events"]["b"] = _event("b", "HIGH", 1); scanner._NEWS_INTEL["order"].append("b")
    assert scanner._event_news_context_cached(record, now_iso=now)["n"] == 2
    scanner._event_news_context_cached({**record, "actual": {"available": True}}, now_iso=now)
    scanner._event_news_context_cached(record, now_iso="2026-10-15T02:31:10Z")
    assert len(calls) == 4


# ── 2. the article's extracted points reach the evidence, bounded for the page ──

def test_news_detail_facts_carry_the_points_with_the_brief_provenance():
    story = {**_event("cpi", "HIGH", 2, headline="米CPI、市場予想上回る"),
             "facts": ["ガソリン高が総合指数を押し上げたとの報道", "利上げ警戒から株安との報道"],
             "sourceLabelJa": "日本経済新聞"}
    watch = {**_event("w", "WATCH", 3, headline="NY株反落"), "sourceLabelJa": "日本経済新聞"}
    rows = mb.news_detail_facts([story, watch])
    assert rows[0]["text"].startswith("日本経済新聞の報道: 米CPI、市場予想上回る（要点: ガソリン高")
    assert "利上げ警戒から株安" in rows[0]["text"] and len(rows[0]["text"]) <= 400
    assert rows[0]["priority"] == "P1" and rows[0]["source"] == "trusted_mail"
    assert rows[0]["verification"] == "UNCONFIRMED" and rows[0]["provenance"]["eventId"] == "cpi"
    assert rows[1]["text"] == "日本経済新聞の報道: NY株反落"
    assert len(mb.news_detail_facts([watch] * 20)) == mb.NEWS_DETAIL_FACT_LIMIT


def test_bound_facts_never_drops_a_p0_and_keeps_the_order():
    facts = [{"priority": "P0", "text": "a"}] + [{"priority": "P2", "text": str(i)} for i in range(70)] \
        + [{"priority": "P1", "text": "b"}]
    kept = mb.bound_facts(facts)
    assert len(kept) == mb.PAGE_FACT_LIMIT == 64
    assert kept[0]["text"] == "a" and kept[-1]["text"] == "b"
    assert [f["text"] for f in kept[1:-1]] == [str(i) for i in range(62)]
    assert mb.bound_facts(facts[:10]) == facts[:10]


# ── 3. intake: every digest article, and explanatory pieces are analysed ──

def test_a_long_digest_mail_yields_every_article(monkeypatch, news_env):
    items = "".join(f"◆米国株、CPI関連の記事その{i}で相場が動く\n" + "本文" * 200 + "保存されない末尾\n" for i in range(1, 13))
    body = "日経ニュースメール 夕版\n" + items
    assert len(body) > gi.MAX_EXCERPT_CHARS * 2
    run_cycle(monkeypatch, {"d1": mail("d1", "日経ニュースメール 夕版 10/14", body=body)})
    titles = sorted(e.get("titleOriginal") or "" for e in news_env["events"].values())
    assert len(titles) == 12 and any("その12" in t for t in titles)
    # The longer body is split input only; nothing of it is stored.
    assert "保存されない末尾" not in json.dumps(news_env, ensure_ascii=False, default=str)


def test_normalized_mail_keeps_the_classification_excerpt_bounded():
    raw = mail("n1", "日経ニュースメール", body="◆" + "あ" * 5000 + "◆い")
    message = gi.normalize_message(raw)
    assert len(message["excerpt"]) == gi.MAX_EXCERPT_CHARS
    assert message["digestBody"].endswith("◆い")
    short = gi.normalize_message(mail("n2", "速報", body="短い本文"))
    assert short["digestBody"] is None
    assert "digestBody" not in ni.split_digest_message(short)[0]


def test_an_explanatory_piece_on_a_market_theme_is_analysed(monkeypatch, news_env):
    calls = []

    def analyze(subject, excerpt, fingerprint, taxonomy=None, diagnostic=None):
        calls.append(subject)
        return {"facts": ["ガソリン高が物価を押し上げたとの報道"]}, "ANALYZED"

    monkeypatch.setattr(scanner, "_news_analyze_ai", analyze)
    run_cycle(monkeypatch, {
        "e1": mail("e1", "【解説】米CPI上振れ、ガソリン高が押し上げ"),
        "e2": mail("e2", "コラム:今週の読まれた記事まとめ"),
    })
    assert calls == ["【解説】米CPI上振れ、ガソリン高が押し上げ"]


# ── 4. storage: more hours of news, inside the existing persistence bound ──

def test_the_store_holds_100_rows_within_the_persistence_bound(monkeypatch, tmp_path):
    assert scanner._NEWS_EVENT_CAP == 100 and scanner._NEWS_PUBLIC_CAP == 40
    subject = "米CPI、9月は前年比3.1%上昇 市場予想上回る ガソリン高が押し上げ 利上げ警戒で株安"
    facts = ["ガソリン価格の上昇が総合指数を押し上げたと報じられた。" * 2] * 5
    big = {**_event("x", "HIGH", 1, headline=subject[:160], facts=facts),
           "titleOriginal": subject, "whyJa": "物価の上振れは利上げ観測を通じて株価の重荷になりうる。" * 3,
           "japanImpactJa": "米金利上昇は円安と日本株のバリュエーションに影響。" * 3,
           "entities": ["FRB", "BLS", "米国", "CPI", "ガソリン", "S&P500", "ナスダック", "ダウ"],
           "marketReadings": [{"symbol": "^TNX", "changePct": 1.2, "labelJa": "米10年債利回り"}] * 6}
    size = len(json.dumps(big, ensure_ascii=False).encode())
    assert size * scanner._NEWS_EVENT_CAP < 512 * 1024 - 100 * 1024   # room for audit and status
