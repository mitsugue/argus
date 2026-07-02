"""ARGUS V11.5.1 — news i18n display-field helpers (pure)."""
import argus_news_i18n as NI

EN = "Nvidia jumps on strong AI demand"
JA = "日銀が金利を据え置き"


def _cache(*pairs):
    return {NI.text_hash(o): {"ja": ja, "at": "x"} for o, ja in pairs}


def test_translation_status():
    c = _cache((EN, "エヌビディアがAI需要で急伸"))
    assert NI.translation_status(EN, c) == "translated"
    assert NI.translation_status("Apple beats earnings", c) == "pending"
    assert NI.translation_status(JA, c) == "not_needed"
    assert NI.translation_status("", c) == "not_needed"


def test_display_title_ja_never_raw_english():
    c = _cache((EN, "エヌビディアがAI需要で急伸"))
    # translated → cached JA
    assert NI.display_title_ja(EN, c, "Finnhub") == "エヌビディアがAI需要で急伸"
    # untranslated English → JP fallback, NEVER the raw English
    d = NI.display_title_ja("Apple beats earnings", c, "Finnhub")
    assert "Apple" not in d and "翻訳待ち" in d and "Finnhub" in d
    # Japanese passes through
    assert NI.display_title_ja(JA, c) == JA


def test_decorate_fields():
    c = _cache((EN, "エヌビディアがAI需要で急伸"))
    d = NI.decorate(EN, c, "Finnhub")
    assert d["titleOriginal"] == EN
    assert d["displayTitleJa"] == "エヌビディアがAI需要で急伸"
    assert d["translationStatus"] == "translated"
    # untranslated
    d2 = NI.decorate("Tesla recalls cars", c, "Reuters")
    assert d2["titleOriginal"] == "Tesla recalls cars"
    assert "Tesla" not in d2["displayTitleJa"] and d2["translationStatus"] == "pending"


def test_decorate_news_item_prefers_english_original():
    c = _cache((EN, "エヌビディアがAI需要で急伸"))
    # a projection stored titleJa=cached-JA AND titleEn=original
    item = {"titleJa": "エヌビディアがAI需要で急伸", "titleEn": EN, "source": "Finnhub"}
    out = NI.decorate_news_item(item, c)
    assert out["titleOriginal"] == EN
    assert out["displayTitleJa"] == "エヌビディアがAI需要で急伸"
    assert out["translationStatus"] == "translated"


def test_decorate_news_item_untranslated_no_english_primary():
    item = {"titleJa": "SoFi loan originations rise", "source": "Finnhub"}   # English in titleJa
    out = NI.decorate_news_item(item, {})
    assert out["translationStatus"] == "pending"
    assert "SoFi" not in out["displayTitleJa"]
    assert out["titleOriginal"] == "SoFi loan originations rise"    # original kept for details


def test_collect_visible_pending_priority_order():
    c = _cache(("already done", "翻訳済み"))
    pool = ["Fed holds rates steady", "already done", JA, "CPI comes in hot"]
    out = NI.collect_visible_pending(pool, c, cap=10)
    assert out == ["Fed holds rates steady", "CPI comes in hot"]   # JA + cached excluded, order kept


# ── V11.5.2: translationQueueEligible + visible translation queue ──

def test_decorate_marks_queue_eligible():
    c = _cache((EN, "エヌビディアがAI需要で急伸"))
    assert NI.decorate(EN, c)["translationQueueEligible"] is False        # translated
    assert NI.decorate("Apple beats earnings", c)["translationQueueEligible"] is True
    assert NI.decorate(JA, c)["translationQueueEligible"] is False        # not_needed


def test_visible_queue_add_skips_japanese_and_translated():
    c = _cache((EN, "エヌビディアがAI需要で急伸"))
    q = {}
    items = [
        {"titleOriginal": EN, "source": "Finnhub"},                # already translated → skip
        {"titleOriginal": "Tesla recalls cars", "source": "Reuters", "publishedAt": "2026-07-03"},
        {"titleOriginal": JA, "source": "Nikkei"},                 # Japanese → ignore
        {"titleOriginal": "Tesla recalls cars", "source": "Reuters"},  # dupe
    ]
    stats = NI.visible_queue_add(q, items, c, context="mover-card", symbol="tsla",
                                 market="us", now_iso="2026-07-03T00:00:00Z")
    assert stats == {"queued": 1, "alreadyTranslated": 1, "alreadyQueued": 1, "ignored": 1}
    assert len(q) == 1
    entry = next(iter(q.values()))
    assert entry["titleOriginal"] == "Tesla recalls cars"
    assert entry["symbol"] == "TSLA" and entry["market"] == "US" and entry["context"] == "mover-card"
    # queue stores ONLY minimal fields — never an article body / prompt
    assert set(entry) <= {"hash", "titleOriginal", "source", "publishedAt", "context",
                          "symbol", "market", "queuedAt", "lastSeenAt"}


def test_visible_queue_drain_and_prune():
    q = {}
    NI.visible_queue_add(q, ["Fed holds rates steady", "CPI comes in hot"], {},
                         now_iso="2026-07-03T00:00:00Z")
    drained = NI.visible_queue_drain(q, {}, max_items=10)
    assert drained == ["Fed holds rates steady", "CPI comes in hot"]      # oldest-first
    # after translation lands in the cache, prune drops the finished entry
    c = _cache(("Fed holds rates steady", "FRBが金利を据え置き"))
    assert NI.visible_queue_prune(q, c) == 1
    assert NI.visible_queue_drain(q, c, 10) == ["CPI comes in hot"]


def test_visible_queue_bounded():
    q = {}
    for i in range(210):
        NI.visible_queue_add(q, [f"Headline number {i} about markets"], {},
                             now_iso="2026-07-03T00:%02d:00Z" % (i % 60))
    assert len(q) <= 200


def test_translation_queue_status_and_samples():
    q = {}
    NI.visible_queue_add(q, [{"titleOriginal": "Fed holds rates steady", "source": "AP"}], {},
                         now_iso="2026-07-03T00:00:00Z")
    NI.visible_queue_add(q, [{"titleOriginal": "CPI comes in hot", "source": "Reuters"}], {},
                         now_iso="2026-07-03T00:05:00Z")
    st = NI.translation_queue_status(q)
    assert st["queuedCount"] == 2
    assert st["oldestQueuedAt"] == "2026-07-03T00:00:00Z"
    assert st["lastQueuedAt"] == "2026-07-03T00:05:00Z"
    s = NI.queue_samples(q, cap=5)
    assert s[0]["source"] == "AP" and "hash" in s[0]
