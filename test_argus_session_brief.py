"""V11.13.0 Session Brief — pure-module tests."""
import argus_session_brief as sb

NOW = "2026-07-06T08:00:00+09:00"


def _p0(sym="TSLA", name="Tesla"):
    return {"priorityRank": "P0", "symbol": sym, "assetName": name, "isHeld": True,
            "category": "held_risk", "blockingReason": "none",
            "ownerReadableTitleJa": f"最優先確認：{sym}",
            "ownerReadableWhyJa": "急落と需給悪化が重なっています",
            "checkNextJa": "下落理由と大口フローの継続を確認", "actionLabelJa": "いま確認"}


def _item(rank="P2", cat="add_only_on_pullback", sym="5803", name="フジクラ",
          held=True, blocking="none", **kw):
    d = {"priorityRank": rank, "symbol": sym, "assetName": name, "isHeld": held,
         "category": cat, "blockingReason": blocking,
         "ownerReadableTitleJa": f"{cat}:{sym}", "ownerReadableWhyJa": "需給は悪くありません",
         "checkNextJa": "押し目の深さと出来高を確認", "actionLabelJa": "買うなら押し目限定"}
    d.update(kw)
    return d


# ── session resolution ──────────────────────────────────────────────────────
def test_resolve_session_types():
    assert sb.resolve_session(7, 0, False, False)["sessionType"] == "morning"
    assert sb.resolve_session(10, 1, True, False)["sessionType"] == "intraday"
    assert sb.resolve_session(17, 2, False, False)["sessionType"] == "after_close"
    assert sb.resolve_session(23, 3, False, True)["sessionType"] == "intraday"
    assert sb.resolve_session(10, 5, False, False) == {"sessionType": "weekend",
                                                       "marketStatus": "weekend"}


# ── P0 in headline / quiet day ──────────────────────────────────────────────
def test_p0_appears_in_headline_and_mode_protect():
    b = sb.build_brief({"sessionType": "morning", "marketStatus": "pre_market",
                        "priorityItems": [_p0()]}, NOW)
    assert "TSLA" in b["headlineJa"] and "最優先" in b["headlineJa"]
    assert b["ownerMode"] == "protect"
    assert b["topPriorities"][0]["symbol"] == "TSLA"


def test_quiet_day_says_no_p0():
    b = sb.build_brief({"sessionType": "morning", "marketStatus": "pre_market",
                        "priorityItems": []}, NOW)
    assert "P0(最優先)はありません" in b["headlineJa"]
    assert b["ownerMode"] == "no_action"


# ── event gate / held-first / avoid-chase ───────────────────────────────────
def test_event_pending_forces_wait():
    b = sb.build_brief({"sessionType": "morning", "marketStatus": "pre_market",
                        "eventNames": ["PCE"],
                        "priorityItems": [_item(cat="event_wait", blocking="event_pending",
                                                sym="NVDA", name="NVIDIA", held=False)]}, NOW)
    assert b["ownerMode"] in ("wait", "monitor")
    assert "PCE" in b["headlineJa"] or "PCE" in b["summaryJa"]
    assert any("イベント結果" in w for w in b["whatNotToDoJa"])


def test_held_risk_before_opportunity_in_summary():
    items = [_item(rank="P2", cat="add_only_on_pullback", sym="5803", held=True),
             _item(rank="P1", cat="supply_demand_watch", sym="9984",
                   name="ソフトバンクグループ", held=True,
                   ownerReadableWhyJa="需給ランクDで戻り売りが出やすい状態")]
    b = sb.build_brief({"sessionType": "morning", "marketStatus": "pre_market",
                        "priorityItems": items}, NOW)
    s = b["summaryJa"]
    assert s.index("9984") < s.index("5803")          # risk first, opportunity later
    assert "9984 ソフトバンク" in s                    # code+name rule


def test_avoid_chase_in_what_not_to_do():
    b = sb.build_brief({"sessionType": "intraday", "marketStatus": "jp_open",
                        "priorityItems": [_item(cat="avoid_chase", sym="6584",
                                                name="三櫻工業", rank="P1")]}, NOW)
    assert any("追いかけて買わない" in w for w in b["whatNotToDoJa"])
    assert b["avoidChaseList"]


# ── weekend / conflict / missing ────────────────────────────────────────────
def test_weekend_is_review_mode_no_intraday_wording():
    b = sb.build_brief({"sessionType": "weekend", "marketStatus": "weekend",
                        "priorityItems": [_item()]}, NOW)
    assert b["ownerMode"] == "review"
    assert "休場" in b["headlineJa"]
    assert "ザラ場" not in b["summaryJa"]
    assert any("休場中の値動き予想" in w for w in b["whatNotToDoJa"])
    assert any("スナップショット" in c or "保有数量" in c for c in b["nextChecksJa"])


def test_conflicting_signals_say_hold():
    b = sb.build_brief({"sessionType": "morning", "marketStatus": "pre_market",
                        "conflictingSignals": True,
                        "priorityItems": [_item()]}, NOW)
    assert b["ownerMode"] == "monitor"
    assert "判断保留" in b["summaryJa"] or "要確認" in b["summaryJa"]


def test_missing_data_noted_and_confidence_down():
    base = sb.build_brief({"sessionType": "morning", "priorityItems": [_item()]}, NOW)
    miss = sb.build_brief({"sessionType": "morning", "priorityItems": [_item()],
                           "missingDataJa": ["保有数量未入力(9984)"]}, NOW)
    assert miss["missingDataNote"]
    assert miss["confidence"] < base["confidence"]


def test_after_close_has_review_items():
    b = sb.build_brief({"sessionType": "after_close", "marketStatus": "after_hours",
                        "priorityItems": [_item(cat="avoid_chase", sym="6584",
                                                name="三櫻工業")]}, NOW)
    assert b["afterCloseReviewJa"]
    assert any("終値位置" in x for x in b["afterCloseReviewJa"])


# ── aggregation / privacy / compliance ──────────────────────────────────────
def test_status_handoff_snapshot():
    b = sb.build_brief({"sessionType": "morning", "priorityItems": [_p0()]}, NOW)
    st = sb.status_doc(b, now_iso=NOW, sources={"actionPriority": True})
    assert st["publicLeakSafe"] is True
    assert st["privateComposition"] == "public_redacted"
    assert "意図的" in st["noteJa"]
    h = sb.handoff_section(b)
    assert h["modeJa"] and h["whatNotToDo"]
    snap = sb.snapshot_summary(b)
    assert snap["ownerMode"] == "protect" and snap["topPrioritySymbols"] == ["TSLA"]


def test_public_brief_is_public_safe_and_no_trading_verbs():
    b = sb.build_brief({"sessionType": "morning", "priorityItems": [_item(held=False)],
                        "isPrivate": False}, NOW)
    assert b["privacyLevel"] == "public_safe"
    assert "売買指示ではない" in b["complianceNote"]
    src = open("argus_session_brief.py", encoding="utf-8").read()
    for banned in ("place_order", "order(", "broker_login", "trd_env", "unlock_trade",
                   "今すぐ買", "全力"):
        assert banned not in src, banned
    for banned_import in ("import requests", "import urllib", "import socket",
                          "import datetime"):
        assert banned_import not in src, banned_import   # clock is caller-supplied
