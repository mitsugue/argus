import argus_target_price_news as t


def test_headlines_with_a_named_firm_direction_and_prices():
    got = t.parse_headline("東レの株価、一時2%高 岡三証券が目標株価引き上げ - 日本経済新聞", company="東レ", code="3402")
    assert got["firm"] == "岡三証券" and got["direction"] == "RAISED" and got["after"] is None
    got = t.parse_headline("【注目】モルガンMUFG、トヨタの目標株価を3,600円→4,300円に引き上げ", company="トヨタ", code="7203")
    assert (got["firm"], got["before"], got["after"], got["direction"]) == ("モルガンMUFG", 3600, 4300, "RAISED")
    got = t.parse_headline("フジクラ－みずほが目標株価引き上げ 28.3期以降は不透明", company="フジクラ", code="5803")
    assert got["firm"] == "みずほ"


def test_unnamed_firms_are_not_guessed_and_unrelated_headlines_are_dropped():
    got = t.parse_headline("【アナリスト評価】アルバック、レーティングやや強気、目標株価8,200円（日系中堅証券）",
                           company="アルバック", code="6728")
    assert got["firm"] is None and got["after"] == 8200
    assert t.parse_headline("トヨタ(7203)決算通過で株価下落｜上方修正", company="トヨタ", code="7203") is None
    assert t.parse_headline("キオクシア株が9%高 目標株価引き上げ", company="トヨタ", code="7203") is None
    # The company's own name is not read as the firm.
    got = t.parse_headline("みずほFG、大和が目標株価引き上げ", company="みずほフィナンシャルグループ", code="8411")
    assert got is None or got["firm"] == "大和"


def test_reprints_count_once_newest_first():
    items = [{"title": "東レ 岡三証券が目標株価引き上げ", "link": "a", "published": "2026-09-28T03:00:00Z", "source": "日経"},
             {"title": "東レ、岡三証券が目標株価を引き上げ", "link": "b", "published": "2026-09-28T05:00:00Z", "source": "株探"},
             {"title": "東レ 野村が目標株価引き下げ", "link": "c", "published": "2026-09-30T01:00:00Z", "source": "日経"}]
    rows = t.collect(items, company="東レ", code="3402")
    assert [r["firm"] for r in rows] == ["野村", "岡三証券"]
    assert all(r["coverage"] == "HEADLINES_ONLY" and r["actionAuthority"] is False for r in rows)
