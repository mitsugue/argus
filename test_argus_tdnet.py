"""Tests for the TDnet disclosure classifier (argus_tdnet.py)."""
import argus_tdnet as T


def test_downward_revision_negative():
    c = T.classify_disclosure("2026年3月期 業績予想の修正(下方修正)に関するお知らせ")
    assert c["category"] == "guidance_down" and c["sentiment"] == "negative"


def test_upward_revision_positive():
    assert T.classify_disclosure("通期業績予想の上方修正に関するお知らせ")["sentiment"] == "positive"


def test_dividend_cut_negative():
    assert T.is_negative("剰余金の配当(減配)に関するお知らせ")


def test_buyback_positive():
    assert T.classify_disclosure("自己株式の取得に係る事項の決定")["sentiment"] == "positive"


def test_dilution_negative():
    assert T.is_negative("第三者割当による新株式発行に関するお知らせ")


def test_earnings_neutral():
    assert T.classify_disclosure("2026年3月期 決算短信〔日本基準〕")["sentiment"] == "neutral"


def test_unknown_title_neutral():
    assert T.classify_disclosure("代表取締役の異動に関するお知らせ")["sentiment"] == "neutral"


def test_summarize_negative_when_any_bad():
    out = T.summarize_for_symbol([{"title": "決算短信"}, {"title": "業績予想の修正(下方修正)"}])
    assert out["confirmedNegative"] is True and out["source"] == "tdnet"
    assert "TDnet" in out["detail"]


def test_summarize_empty_none():
    assert T.summarize_for_symbol([]) is None
