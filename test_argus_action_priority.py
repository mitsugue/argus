"""V11.12.0 Action Priority Engine — pure-module tests."""
import argus_action_priority as ap

NOW = "2026-07-04T12:00:00+00:00"


def _b(inputs, symbol="5803", market="JP"):
    return ap.build_item(symbol, market, inputs, NOW)


# ── P0: held × compounded adverse only (rare) ──────────────────────────────
def test_p0_held_multi_adverse():
    r = _b({"isHeld": True, "assetName": "TSLA", "changePct": -7.5,
            "flowClass": "panic_selling", "sdRank": "E",
            "positionRiskLevel": "high", "regimeRiskOff": True}, symbol="TSLA", market="US")
    assert r["priorityRank"] == "P0"
    assert r["actionLabel"] == "CHECK_NOW"
    assert r["category"] == "held_risk"
    assert "最優先確認" in r["ownerReadableTitleJa"]
    assert r["checkNextJa"] and r["whatWouldChangeJa"]
    assert r["privacyLevel"] == "private_local"


def test_p0_is_rare_single_adverse_is_not_p0():
    r = _b({"isHeld": True, "sdRank": "D"})
    assert r["priorityRank"] != "P0"


def test_watchlist_only_never_p0():
    r = _b({"isHeld": False, "changePct": -8, "flowClass": "panic_selling",
            "sdRank": "E", "positionRiskLevel": "high"})
    assert r["priorityRank"] != "P0"


# ── P1 avoid-chase / held boost ─────────────────────────────────────────────
def test_p1_avoid_chase_held():
    r = _b({"isHeld": True, "readiness": "avoid_chase", "priorRunupPct": 20,
            "sdCondition": "squeeze_prone", "sdRank": "B", "assetName": "三櫻工業"})
    assert r["priorityRank"] in ("P1", "P0")
    assert r["actionLabel"] == "AVOID_CHASE"
    assert "買い戻し主導の可能性" in r["ownerReadableWhyJa"]
    assert "新規の大口買いとは未確定" in r["ownerReadableWhyJa"]


def test_held_ranks_above_watchlist_same_signals():
    held = _b({"isHeld": True, "flowClass": "distribution"})
    watch = _b({"isHeld": False, "flowClass": "distribution"})
    assert held["priorityScore"] > watch["priorityScore"]


def test_concentration_boost():
    base = _b({"isHeld": True, "sdRank": "D"})
    conc = _b({"isHeld": True, "sdRank": "D", "concentrationRisk": "critical",
               "weightPct": 40})
    assert conc["priorityScore"] > base["priorityScore"]
    assert "CONCENTRATION" in conc["reasonCodes"]


# ── event gate blocks aggressive labels ─────────────────────────────────────
def test_event_wait_blocks_add():
    r = _b({"isHeld": True, "readiness": "add_allowed_small",
            "eventPending": True, "eventName": "PCE", "assetName": "NVDA"},
           symbol="NVDA", market="US")
    assert r["actionLabel"] == "WAIT_EVENT"
    assert r["blockingReason"] == "event_pending"
    assert "PCE" in r["ownerReadableWhyJa"]
    assert "発表" in r["checkNextJa"] or "結果" in r["checkNextJa"]


# ── pullback-add / small-add / short-covering never auto-buy ───────────────
def test_add_only_on_pullback_p2():
    r = _b({"isHeld": True, "readiness": "add_only_on_pullback", "sdRank": "A",
            "assetName": "フジクラ"})
    assert r["category"] == "add_only_on_pullback"
    assert r["actionLabel"] == "ADD_ONLY_ON_PULLBACK"
    assert "押し目" in r["ownerReadableWhyJa"]


def test_squeeze_never_becomes_buy_label():
    r = _b({"isHeld": False, "sdRank": "B", "sdCondition": "squeeze_prone",
            "changePct": 6.0})
    assert r["actionLabel"] == "AVOID_CHASE"
    assert r["actionLabel"] not in ("SMALL_ADD_ALLOWED", "ADD_ONLY_ON_PULLBACK")


def test_sd_unknown_is_not_positive():
    r = _b({"isHeld": False, "sdRank": "Unknown"})
    assert r["category"] not in ("add_candidate", "add_only_on_pullback")


# ── institutional / dq modifiers ────────────────────────────────────────────
def test_institutional_headline_only_low_confidence():
    direct = _b({"isHeld": False, "instStance": "bullish", "instDirect": True})
    headline = _b({"isHeld": False, "instStance": "bullish", "instDirect": False})
    assert direct["priorityScore"] > headline["priorityScore"]


def test_dq_modifier_is_modest():
    base = _b({"isHeld": True, "readiness": "avoid_chase"})
    adj = _b({"isHeld": True, "readiness": "avoid_chase",
              "dqContradictedAvoidChase": True})
    assert abs(adj["confidence"] - base["confidence"]) <= 0.06   # never dominant
    assert adj["priorityRank"] == base["priorityRank"]           # rank unchanged


# ── data-missing / ignore / held never hidden ───────────────────────────────
def test_held_missing_data_is_warning_item():
    r = _b({"isHeld": True, "dataMissing": ["保有数量", "取得単価"]})
    assert r["category"] == "data_missing"
    assert r["actionLabel"] == "INVESTIGATE"
    assert r["blockingReason"] == "missing_position_data"
    assert "不足" in r["ownerReadableWhyJa"]


def test_quiet_watchlist_is_ignore_with_explanation():
    r = _b({"isHeld": False})
    assert r["priorityRank"] == "Ignore"
    assert r["actionLabel"] == "IGNORE_TODAY"
    assert "重要度低" in r["ownerReadableTitleJa"]
    assert "材料" in r["ownerReadableWhyJa"]


def test_held_never_ignored():
    r = _b({"isHeld": True})
    assert r["priorityRank"] != "Ignore"


def test_public_caller_without_held_is_public_safe():
    r = _b({"isHeld": None, "sdRank": "B"})
    assert r["privacyLevel"] == "public_safe"
    assert r["isHeld"] == "unknown"


# ── ranking / summary / handoff ─────────────────────────────────────────────
def _mix():
    return [
        _b({"isHeld": True, "changePct": -7.5, "flowClass": "panic_selling",
            "sdRank": "E", "positionRiskLevel": "high"}, symbol="TSLA", market="US"),
        _b({"isHeld": True, "readiness": "avoid_chase", "sdCondition": "squeeze_prone",
            "sdRank": "B"}, symbol="6584"),
        _b({"isHeld": True, "readiness": "add_only_on_pullback", "sdRank": "A"},
           symbol="5803"),
        _b({"isHeld": False, "eventPending": True, "eventName": "PCE"}, symbol="NVDA",
           market="US"),
        _b({"isHeld": False}, symbol="9501"),
    ]


def test_rank_items_order_and_summary():
    ranked = ap.rank_items(_mix())
    assert ranked[0]["symbol"] == "TSLA"                 # P0 first
    assert ranked[-1]["priorityRank"] in ("Ignore", "Watch")
    s = ap.summary(ranked, NOW)
    assert s["p0Count"] == 1
    assert s["topPriorityJa"] and "TSLA" in s["topPriorityJa"]
    assert "P0 1件" in s["ownerBriefJa"]
    assert s["complianceNote"] == ap.COMPLIANCE


def test_quiet_day_brief():
    s = ap.summary([_b({"isHeld": False})], NOW)
    assert "最優先の確認事項はありません" in s["ownerBriefJa"]


def test_handoff_and_status():
    items = ap.rank_items(_mix())
    h = ap.handoff_section(items)
    assert h["top"] and h["avoidChase"] and h["pullbackAdds"]
    st = ap.status_doc(items, now_iso=NOW,
                       sources={"positionExposure": False, "flowAttribution": True,
                                "supplyDemand": True, "eventRadar": True,
                                "institutionalIntelligence": True,
                                "marketRegime": True, "decisionQuality": False})
    assert st["publicLeakSafe"] is True
    assert st["heldRiskCount"] == 0                      # held context never public
    assert "意図的" in st["noteJa"]


# ── compliance ──────────────────────────────────────────────────────────────
def test_every_item_has_why_and_next_and_no_trade_verbs():
    for r in _mix():
        assert r["ownerReadableWhyJa"] and r["checkNextJa"] and r["whatWouldChangeJa"]
        assert r["actionLabel"] in ap.ACTION_LABELS
        assert "売買指示ではない" in r["complianceNote"]
    src = open("argus_action_priority.py", encoding="utf-8").read()
    for banned in ("place_order", "order(", "broker_login", "trd_env", "unlock_trade",
                   "全力買い", "今すぐ買"):
        assert banned not in src, banned
    for banned_import in ("import requests", "import urllib", "import socket"):
        assert banned_import not in src, banned_import


def test_sd_watch_label_is_monitor_not_no_action():
    # production polish (2026-07-04): 需給D注意なのにラベル「対応不要」は矛盾
    r = _b({"isHeld": False, "sdRank": "D"})
    assert r["category"] == "supply_demand_watch"
    assert r["actionLabel"] == "MONITOR"
