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


def test_deterministic_market_summary_is_japanese_and_fail_closed():
    title = "Wall St rises on the day but falls for the week; bond yields and Iran in focus"
    summary = NI.deterministic_market_summary_ja(title)
    assert summary == "米国株は反発、週間では下落、債券利回りとイラン情勢が焦点"
    assert NI.deterministic_market_summary_ja(
        "Celebrity shares ten weekend habits") is None


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


# ━━━ v13.5.34 — translation retry-loop and alignment guards (live finding) ━━━

def test_validate_translation_batch_rejects_count_mismatch():
    ok = NI.validate_translation_batch(
        {"translations": ["A訳", "B訳"]}, 2)
    assert ok == {0: "A訳", 1: "B訳"}
    assert NI.validate_translation_batch({"translations": ["A訳"]}, 2) == {}
    assert NI.validate_translation_batch(
        {"translations": ["A訳", "B訳", "C訳"]}, 2) == {}
    assert NI.validate_translation_batch(None, 2) == {}
    assert NI.validate_translation_batch({"translations": "A訳"}, 1) == {}
    partial = NI.validate_translation_batch(
        {"translations": ["A訳", "", "C訳"]}, 3)
    assert partial == {0: "A訳", 2: "C訳"}


def test_collect_pending_skips_exhausted_attempts_and_recovers():
    title = "Stubborn English headline that never translates"
    h = NI.text_hash(title)
    cache = {}
    failed = {}
    for expected in (1, 2, 3):
        assert NI.collect_pending([title], cache, failed=failed) == [title] \
            if expected <= NI.TRANSLATE_MAX_ATTEMPTS else True
        failed = NI.note_translation_attempts(failed, [title], cache)
        assert failed[h] == expected
    # at max attempts the title leaves the pending pool entirely
    assert NI.collect_pending([title], cache, failed=failed) == []
    # a later successful cache entry clears the failure state
    cache[h] = {"ja": "頑固な見出し", "at": "2026-08-25T00:00:00Z"}
    failed = NI.note_translation_attempts(failed, [title], cache)
    assert h not in failed
    assert NI.collect_pending([title], cache, failed=failed) == []  # cached


def test_note_translation_attempts_is_bounded():
    failed = {}
    cache = {}
    titles = [f"English headline number {i} stays" for i in range(260)]
    failed = NI.note_translation_attempts(failed, titles, cache)
    assert len(failed) <= 200
