"""V11.10.0 Supply/Demand Intelligence — pure-module tests.

Discipline: never fabricate (missing feeds → Unknown + 暫定), squeeze rises are
never called new institutional buying, S rank needs BOTH direct feeds, raw
numbers live in evidence (not in the primary labels), no trade orders.
"""
import argus_supply_demand as sd

NOW = "2026-07-04T12:00:00+00:00"


def _c(ev, symbol="5803"):
    return sd.classify(symbol, "JP", ev, NOW)


# ── schema / determinism ────────────────────────────────────────────────────
def test_schema_and_determinism():
    ev = {"marginBuying": 1e6, "marginSelling": 2e6, "jsfLoan": 5e5, "jsfLending": 9e5,
          "avgDailyVolume": 4e5, "changePct": 3.0, "volumeRatio": 1.8,
          "sources": {"jqMargin": True, "jsf": True}}
    a, b = _c(ev), _c(ev)
    assert a == b
    assert a["schemaVersion"] == "supply-demand-v1"
    assert a["supplyDemandRank"] in sd.RANKS
    assert a["condition"] in sd.CONDITIONS
    assert a["actionImplication"] in sd.ACTIONS
    assert set(a["evidence"].keys()) == set(sd.EVIDENCE_KEYS)
    assert a["readabilityLabelJa"].startswith("需給ランク")


# ── B. squeeze-prone: 売り長 + rise → 買い戻し主導と明記・大口買いと断定しない ──
def test_squeeze_prone_classification_and_vocabulary():
    r = _c({"marginBuying": 1e6, "marginSelling": 2.5e6, "jsfLoan": 4e5, "jsfLending": 1.2e6,
            "avgDailyVolume": 5e5, "changePct": 6.0, "volumeRatio": 2.2,
            "priorRunupPct": 4.0})
    assert r["condition"] == "squeeze_prone"
    assert r["supplyDemandRank"] == "B"
    assert "踏み上げ注意" in r["chips"] and "買い戻し主導" in r["chips"]
    assert "買い戻し主導の可能性" in r["ownerReadableWhyJa"]
    assert "新規の大口買いとは未確定" in r["ownerReadableWhyJa"]
    assert r["actionImplication"] == "avoid_chase"
    assert r["flowHints"]["squeezeProne"] is True
    assert r["evidence"]["daysToCover"] == 5.0        # 2.5e6 / 5e5


# ── C. credit overhang ──────────────────────────────────────────────────────
def test_credit_overhang_classification():
    r = _c({"marginBuying": 6e6, "marginSelling": 1e6, "jsfLoan": 3e6, "jsfLending": 5e5,
            "avgDailyVolume": 5e5, "changePct": 0.5, "volumeRatio": 1.0})
    assert r["condition"] == "credit_overhang"
    assert r["supplyDemandRank"] == "D"
    assert "信用買い残重い" in r["chips"]
    assert "戻り売り" in r["ownerReadableWhyJa"]
    assert r["actionImplication"] == "avoid_chase"
    assert r["flowHints"]["creditOverhang"] is True


# ── A. good / S is direct-only and rare ─────────────────────────────────────
def test_good_supply_demand():
    r = _c({"marginBuying": 8e5, "marginSelling": 6e5, "marginBuyingPrev": 1e6,
            "jsfLoan": 6e5, "jsfLending": 4e5, "avgDailyVolume": 5e5,
            "changePct": 2.5, "volumeRatio": 1.6})
    assert r["condition"] in ("good", "slightly_good")
    assert r["supplyDemandRank"] in ("A", "B")
    assert r["direction"] == "improving"              # buying balance shrinking


def test_s_rank_requires_both_feeds_and_flow_support():
    base = {"marginBuying": 8e5, "marginSelling": 6e5, "marginBuyingPrev": 1e6,
            "avgDailyVolume": 5e5, "changePct": 2.5, "volumeRatio": 1.6,
            "flowClass": "institutional_accumulation"}
    only_margin = _c(base)                            # no JSF → S must not mint
    assert only_margin["supplyDemandRank"] != "S"
    both = _c({**base, "jsfLoan": 6e5, "jsfLending": 4e5})
    assert both["supplyDemandRank"] == "S"
    assert both["condition"] == "very_good"


# ── D. distribution / E. deteriorating-bad ─────────────────────────────────
def test_distribution_risk_via_gap_fade():
    r = _c({"marginBuying": 1e6, "marginSelling": 9e5, "jsfLoan": 5e5, "jsfLending": 4e5,
            "avgDailyVolume": 5e5, "changePct": 1.0, "volumeRatio": 2.0, "gapFade": True})
    assert r["condition"] == "distribution_risk"
    assert "上値で売り" in r["ownerReadableWhyJa"]


def test_bad_saisoku_pattern():
    # 下落しながら信用買い残が積み上がる=催促相場
    r = _c({"marginBuying": 2e6, "marginBuyingPrev": 1.6e6, "marginSelling": 8e5,
            "jsfLoan": 1e6, "jsfLending": 6e5, "avgDailyVolume": 5e5,
            "changePct": -4.0, "volumeRatio": 1.5})
    assert r["condition"] in ("bad", "deteriorating")
    assert r["supplyDemandRank"] in ("D", "E")
    assert "確認待ち" in r["ownerReadableWhyJa"] or "催促" in r["ownerReadableWhyJa"]
    assert r["actionImplication"] == "wait"


# ── F. missing data honesty ─────────────────────────────────────────────────
def test_no_feeds_is_unknown_and_provisional():
    r = _c({"changePct": 5.0, "volumeRatio": 2.0})
    assert r["supplyDemandRank"] == "Unknown"
    assert r["condition"] == "unknown"
    assert r["confidence"] <= 0.4
    assert "週次信用残(J-Quants)" in r["missingEvidence"]
    assert "日証金貸借残" in r["missingEvidence"]
    assert "暫定" in r["sourceLimitNote"]
    # raw evidence fields exist but are None — nothing invented
    assert r["evidence"]["marginBuyingBalance"] is None
    assert r["evidence"]["reverseStockLendingFee"] is None


def test_reverse_stock_lending_fee_never_fabricated():
    r = _c({"marginBuying": 1e6, "marginSelling": 2e6, "avgDailyVolume": 5e5,
            "changePct": 3.0})
    assert r["evidence"]["reverseStockLendingFee"] is None
    assert r["sourceAvailability"]["reverseStockLendingFee"] is False
    assert any("逆日歩" in m for m in r["missingEvidence"])


def test_single_feed_caps_confidence():
    r = _c({"marginBuying": 8e5, "marginSelling": 6e5, "marginBuyingPrev": 1e6,
            "avgDailyVolume": 5e5, "changePct": 2.0, "volumeRatio": 1.5})
    assert r["confidence"] <= 0.6                     # one of two feeds only


def test_stale_data_caps_confidence():
    r = _c({"marginBuying": 8e5, "marginSelling": 6e5, "jsfLoan": 5e5, "jsfLending": 4e5,
            "avgDailyVolume": 5e5, "changePct": 2.0, "staleData": True})
    assert r["confidence"] <= 0.4
    assert any("鮮度" in m for m in r["missingEvidence"])


# ── compliance ──────────────────────────────────────────────────────────────
def test_no_trading_orders_and_ja_everywhere():
    cases = [
        {"marginBuying": 1e6, "marginSelling": 2.5e6, "jsfLoan": 4e5, "jsfLending": 1.2e6,
         "avgDailyVolume": 5e5, "changePct": 6.0, "volumeRatio": 2.2},
        {"marginBuying": 6e6, "marginSelling": 1e6, "jsfLoan": 3e6, "jsfLending": 5e5,
         "avgDailyVolume": 5e5, "changePct": 0.5},
        {},
    ]
    for ev in cases:
        r = _c(ev)
        assert r["ownerReadableWhyJa"] and r["checkNextJa"] and r["conditionJa"]
        assert r["actionImplication"] in sd.ACTIONS   # no buy/sell verbs
        assert "売買指示ではない" in r["complianceNote"]
    src = open("argus_supply_demand.py", encoding="utf-8").read()
    for banned in ("place_order", "order(", "broker_login", "trd_env", "unlock_trade"):
        assert banned not in src, banned
    for banned_import in ("import requests", "import urllib", "import socket"):
        assert banned_import not in src, banned_import


# ── aggregation ─────────────────────────────────────────────────────────────
def _mix():
    return [
        _c({"marginBuying": 8e5, "marginSelling": 6e5, "marginBuyingPrev": 1e6,
            "jsfLoan": 6e5, "jsfLending": 4e5, "avgDailyVolume": 5e5,
            "changePct": 2.5, "volumeRatio": 1.6}, symbol="6146"),
        _c({"marginBuying": 1e6, "marginSelling": 2.5e6, "jsfLoan": 4e5,
            "jsfLending": 1.2e6, "avgDailyVolume": 5e5, "changePct": 6.0,
            "volumeRatio": 2.2}, symbol="5803"),
        _c({"marginBuying": 6e6, "marginSelling": 1e6, "jsfLoan": 3e6,
            "jsfLending": 5e5, "avgDailyVolume": 5e5, "changePct": 0.5}, symbol="9984"),
        _c({}, symbol="6584"),
    ]


def test_status_doc():
    st = sd.status_doc(_mix(), now_iso=NOW,
                       sources={"enabled": ["jquants-margin", "jsf-daily"],
                                "disabled": [{"source": "逆日歩", "reasonJa": "未取込"}],
                                "jsf": True, "jqMargin": True, "shortRatio": False})
    assert st["assetsScanned"] == 4 and st["unknownCount"] == 1
    assert st["directDataCount"] == 3
    assert st["rankDistribution"]["Unknown"] == 1
    assert "意図的" in st["noteJa"]


def test_handoff_and_snapshot_summary():
    sigs = _mix()
    h = sd.handoff_section(sigs)
    assert h["squeezeProne"] and h["creditOverhang"]
    assert "断定しない" in h["sourceLimitJa"]
    snap = sd.snapshot_summary(sigs)
    assert "5803" in snap["squeezeProne"]
    assert "9984" in snap["creditOverhang"]
    assert snap["missingSupplyDemandEvidence"]


# ── v11.11.0: US simplified supply/demand (owner: 「アメリカ株の需給は?」) ──
def test_us_measured_flow_is_direct_and_capped():
    r = sd.classify("NVDA", "US", {"measuredFlowNetRatio": 0.25, "changePct": 3.0,
                                   "volumeRatio": 1.8, "avgDailyVolume": 1e7}, NOW)
    assert r["condition"] in ("good", "slightly_good")
    assert r["directness"] == "direct_data"
    assert r["confidence"] <= 0.6                     # simplified read caps
    assert r["supplyDemandRank"] != "S"               # S needs JP dual feeds
    assert "実測" in r["ownerReadableWhyJa"]
    assert "簡易判定" in r["ownerReadableWhyJa"] or "簡易判定" in r["sourceLimitNote"]
    assert any("FINRA" in m for m in r["missingEvidence"])


def test_us_distribution_on_outflow_into_strength():
    r = sd.classify("TSLA", "US", {"measuredFlowNetRatio": -0.2, "changePct": 2.0,
                                   "avgDailyVolume": 1e7}, NOW)
    assert r["condition"] == "distribution_risk"
    assert "流出超" in r["ownerReadableWhyJa"]


def test_us_without_flow_is_unknown_never_squeeze():
    r = sd.classify("AAPL", "US", {"changePct": 5.0, "volumeRatio": 2.0}, NOW)
    assert r["supplyDemandRank"] == "Unknown"
    assert r["condition"] != "squeeze_prone"          # US can't detect squeeze
    assert any("実測大口フロー" in m for m in r["missingEvidence"])
    assert "暫定" in r["sourceLimitNote"]


def test_us_near_zero_flow_is_neutral_not_good():
    # production bug (2026-07-04): flow -0.00 read as 「流入超/やや良好」 because
    # the JP structure branch fired on the ABSENCE of margin data.
    r = sd.classify("NVDA", "US", {"measuredFlowNetRatio": -0.001, "changePct": 0.5,
                                   "avgDailyVolume": 1e7}, NOW)
    assert r["condition"] == "neutral"
    assert "流入超" not in r["ownerReadableWhyJa"]
    assert r["directnessJa"] == "実データ(実測フロー)あり"
    assert "純比率" in sd.classify("NVDA", "US",
        {"measuredFlowNetRatio": 0.3, "changePct": 2.0, "volumeRatio": 1.5,
         "avgDailyVolume": 1e7}, NOW)["ownerReadableWhyJa"]


# ── v11.14.0: direction ≠ level(フジクラA問題の根治) ──────────────────────
def test_fujikura_like_improving_but_heavy_never_A():
    # 買い残25.2M(前週比-14.6%)・売り残1.3M(倍率≈19=very_heavy)・出来高大
    r = _c({"marginBuying": 25.2e6, "marginBuyingPrev": 29.5e6,
            "marginSelling": 1.3e6, "marginSellingPrev": 1.43e6,
            "jsfLoan": 6e5, "jsfLending": 4e5,
            "avgDailyVolume": 26e6, "changePct": 1.5, "volumeRatio": 1.4})
    assert r["condition"] == "improving_but_heavy"
    assert r["supplyDemandRank"] != "A" and r["supplyDemandRank"] != "S"
    assert r["supplyDemandRank"] in ("B", "C")
    assert r["supplyDemandLevel"] == "very_heavy"
    assert r["direction"] == "improving"
    assert "改善方向" in r["ownerReadableWhyJa"]
    assert "まだ大きく" in r["ownerReadableWhyJa"]
    assert "上値吸収" in r["ownerReadableWhyJa"]
    assert "続けて減るか" in r["checkNextJa"]
    assert r["actionImplication"] == "add_only_on_pullback"
    assert r["flowHints"]["creditOverhang"] is True     # accumulation stays penalized
    assert "需給改善方向" in r["chips"] and "信用買い残重い" in r["chips"]


def test_heavy_level_caps_rank_even_with_all_positives():
    # 全ての加点が乗ってもheavy水準ならA/S不可(上限B)
    r = _c({"marginBuying": 8e6, "marginBuyingPrev": 9e6, "marginSelling": 1.2e6,
            "jsfLoan": 6e5, "jsfLending": 4e5, "avgDailyVolume": 1.2e6,
            "changePct": 2.5, "volumeRatio": 1.8,
            "flowClass": "institutional_accumulation"})
    # ratio 6.7=heavy, days 6.7=heavy
    assert r["supplyDemandLevel"] == "heavy"
    assert r["supplyDemandRank"] not in ("S", "A")


def test_true_A_still_works_when_level_light():
    r = _c({"marginBuying": 8e5, "marginSelling": 6e5, "marginBuyingPrev": 1e6,
            "jsfLoan": 6e5, "jsfLending": 4e5, "avgDailyVolume": 5e5,
            "changePct": 2.5, "volumeRatio": 1.6})
    assert r["supplyDemandLevel"] in ("light", "normal")
    assert r["supplyDemandRank"] in ("A", "B")
    assert r["rankCapReason"] is None


def test_us_flow_path_unaffected_by_jp_level_model():
    r = sd.classify("NVDA", "US", {"measuredFlowNetRatio": 0.25, "changePct": 3.0,
                                   "volumeRatio": 1.8, "avgDailyVolume": 1e7}, NOW)
    assert r["condition"] in ("good", "slightly_good")
    assert r["supplyDemandLevel"] == "unknown"          # no margin data for US


def test_level_displayed_separately_from_direction():
    r = _c({"marginBuying": 25e6, "marginBuyingPrev": 29e6, "marginSelling": 1.3e6,
            "avgDailyVolume": 26e6, "changePct": 1.0})
    assert r["direction"] == "improving"
    assert r["supplyDemandLevel"] in ("heavy", "very_heavy")
    assert r["levelJa"] in ("まだ重い", "かなり重い")
