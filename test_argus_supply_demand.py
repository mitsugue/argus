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
