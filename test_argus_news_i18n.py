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
