"""V11.11.0 Decision Quality foundation — pure-module tests."""
import argus_decision_quality as dq

NOW = "2026-07-04T12:00:00+00:00"

# ascending trading days around the decision (Fri 6/26 base)
DATES = ["2026-07-03", "2026-07-02", "2026-07-01", "2026-06-30", "2026-06-29",
         "2026-06-26"]                      # newest-first (like JQ history)
def closes(seq):                            # newest-first to match dates
    return list(seq)


def _rec(**kw):
    base = {"schemaVersion": dq.SCHEMA_VERSION, "id": "dq-1", "symbol": "5803",
            "market": "JP", "asOf": NOW, "createdAt": NOW, "appVersion": "11.11.0",
            "decisionContext": "avoid_chase", "decisionSource": "supply_demand",
            "privacyLevel": "local_only", "ownerAction": None,
            "reviewStatus": "pending", "evidenceAtDecision": {"price": 6000}}
    base.update(kw)
    return base


# ── model validation ────────────────────────────────────────────────────────
def test_record_validation():
    ok, errs = dq.validate_record(_rec())
    assert ok, errs
    bad, errs2 = dq.validate_record(_rec(decisionContext="buy_now"))
    assert not bad and any("decisionContext" in e for e in errs2)
    bad2, _ = dq.validate_record(_rec(evidenceAtDecision=None))
    assert not bad2


def test_outcome_validation_and_dedupe():
    o = dq.compute_outcome("dq-1", "5803", "JP", 6000, "2026-06-26",
                           DATES, closes([6300, 6250, 6100, 5900, 5800, 6000]), "2026-07-04")
    ok, errs = dq.validate_outcome(o)
    assert ok, errs
    k1 = dq.dedupe_key("5803", "avoid_chase", "2026-06-26", ["SD_RANK_B"])
    k2 = dq.dedupe_key("5803", "avoid_chase", "2026-06-26", ["SD_RANK_B", "other"])
    assert k1 == k2                                    # major reason only


# ── outcome math (trading-day windows; weekends skipped by construction) ────
def test_outcome_forward_returns():
    # base 6/26 @6000. forward closes asc: 6/29=5800, 6/30=5900, 7/1=6100, 7/2=6250, 7/3=6300
    o = dq.compute_outcome("d", "5803", "JP", 6000, "2026-06-26",
                           DATES, closes([6300, 6250, 6100, 5900, 5800, 6000]), "2026-07-04")
    assert o["outcomeReturn1d"] == round((5800 - 6000) / 6000 * 100, 2)
    assert o["outcomeReturn3d"] == round((6100 - 6000) / 6000 * 100, 2)
    assert o["outcomeReturn5d"] == round((6300 - 6000) / 6000 * 100, 2)
    assert o["outcomeReturn20d"] is None
    assert o["maxDrawdown5d"] == round((5800 - 6000) / 6000 * 100, 2)
    assert o["maxRunup5d"] == round((6300 - 6000) / 6000 * 100, 2)
    assert o["outcomeStatus"] == "partial"             # 20d window not elapsed


def test_outcome_missing_prices_never_fabricated():
    o = dq.compute_outcome("d", "X", "US", 100, "2026-06-26", [], [], "2026-07-04")
    assert o["outcomeStatus"] == "insufficient_price_data"
    assert o["outcomeReturn1d"] is None
    o2 = dq.compute_outcome("d", "X", "US", None, "2026-06-26", DATES,
                            closes([1, 1, 1, 1, 1, 1]), "2026-07-04")
    assert o2["outcomeStatus"] == "unknown"


def test_outcome_pending_when_windows_not_elapsed():
    o = dq.compute_outcome("d", "5803", "JP", 6000, "2026-07-03",
                           DATES, closes([6300, 6250, 6100, 5900, 5800, 6000]), "2026-07-04")
    assert o["outcomeStatus"] == "pending"


# ── interpretation (cautious) ───────────────────────────────────────────────
def _oc(r1=None, r3=None, r5=None, r20=None, dd5=None, ru5=None):
    return {"outcomeReturn1d": r1, "outcomeReturn3d": r3, "outcomeReturn5d": r5,
            "outcomeReturn20d": r20, "maxDrawdown5d": dd5, "maxRunup5d": ru5}


def test_avoid_chase_supported():
    it, ja = dq.interpret("avoid_chase", {}, _oc(r3=-2, r5=-3, dd5=-4))
    assert it == "supported" and "支持" in ja


def test_avoid_chase_contradicted():
    it, ja = dq.interpret("avoid_chase", {}, _oc(r3=4, r5=7, dd5=-0.5))
    assert it == "contradicted" and "外れた可能性" in ja


def test_add_only_on_pullback_supported_and_mixed():
    it, _ = dq.interpret("add_only_on_pullback", {}, _oc(r5=1, dd5=-3))
    assert it == "supported"
    it2, ja2 = dq.interpret("add_only_on_pullback", {}, _oc(r5=2, dd5=-0.5))
    assert it2 == "mixed" and "一長一短" in ja2


def test_supply_demand_ab_supported():
    it, ja = dq.interpret("monitor", {"supplyDemandRank": "A"}, _oc(r5=3, dd5=-1))
    assert it == "supported" and "需給良好" in ja


def test_supply_demand_de_supported_and_contradicted():
    it, ja = dq.interpret("wait", {"supplyDemandRank": "D"}, _oc(r5=-3, ru5=1))
    assert it == "supported" and "重い" in ja
    it2, _ = dq.interpret("wait", {"supplyDemandRank": "D"}, _oc(r5=6, ru5=7))
    assert it2 == "contradicted"


def test_short_covering_fade_supported():
    ev = {"supplyDemandRank": "B", "supplyDemandCondition": "squeeze_prone"}
    it, ja = dq.interpret("monitor", ev, _oc(r5=0.5, ru5=5))
    assert it == "supported" and "失速" in ja
    it2, _ = dq.interpret("monitor", ev, _oc(r5=6, r20=10, ru5=8))
    assert it2 == "contradicted"


def test_inconclusive_and_event_override():
    it, ja = dq.interpret("avoid_chase", {}, _oc())
    assert it == "inconclusive" and "判定保留" in ja
    it2, ja2 = dq.interpret("avoid_chase", {"eventChanged": True}, _oc(r5=-5))
    assert it2 == "mixed" and "材料変化" in ja2


def test_headline_only_institutional_not_judged():
    it, ja = dq.interpret("monitor", {"institutionalSignals": True,
                                      "institutionalDirect": False}, _oc(r5=4))
    assert it == "not_applicable" and "見出しのみ" in ja


# ── summary honesty ─────────────────────────────────────────────────────────
def _judged(ctx, interp, n):
    return [{"decisionContext": ctx, "decisionSource": "supply_demand", "market": "JP",
             "reviewStatus": "pending",
             "outcome": {"outcomeStatus": "complete", "outcomeInterpretation": interp}}
            for _ in range(n)]


def test_summary_not_enough_history():
    s = dq.summary(_judged("avoid_chase", "supported", 3), NOW)
    assert s["bestPerformingLabels"] == [] and s["noisyLabels"] == []
    assert "成績としては扱わないで" in s["notEnoughHistoryNote"]


def test_summary_ranks_labels_only_with_sample():
    recs = _judged("avoid_chase", "supported", 5) + _judged("caution", "contradicted", 5)
    s = dq.summary(recs, NOW)
    assert any(b["label"] == "avoid_chase" for b in s["bestPerformingLabels"])
    assert any(b["label"] == "caution" for b in s["noisyLabels"])
    assert s["supportedCount"] == 5 and s["contradictedCount"] == 5


# ── privacy ─────────────────────────────────────────────────────────────────
def test_public_status_redacted():
    doc = dq.public_status(enabled=True, storage_mode="encrypted_vault", now_iso=NOW)
    assert doc["serverStoresRecords"] is False and doc["publicLeakSafe"] is True
    blob = str(doc)
    for banned in dq.PUBLIC_FORBIDDEN:
        assert banned not in blob, banned
    assert "端末内" in doc["noteJa"]


def test_no_trading_and_pure():
    src = open("argus_decision_quality.py", encoding="utf-8").read()
    for banned in ("place_order", "order(", "broker_login", "trd_env", "unlock_trade"):
        assert banned not in src, banned
    for banned_import in ("import requests", "import urllib", "import socket"):
        assert banned_import not in src, banned_import
