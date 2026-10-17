"""V11.15.0 Learning Review — pure-module tests (sample discipline is the product)."""
import argus_learning_review as lr

NOW = "2026-07-06T10:00:00+09:00"


def _rec(r5=None, interp=None, dd5=None, ru5=None, sym="5803"):
    return {"symbol": sym, "asOf": NOW,
            "outcome": {"outcomeReturn1d": None, "outcomeReturn3d": None,
                        "outcomeReturn5d": r5, "outcomeReturn20d": None,
                        "maxDrawdown5d": dd5, "maxRunup5d": ru5,
                        "outcomeInterpretation": interp}}


# ── sample discipline ───────────────────────────────────────────────────────
def test_n_below_5_is_insufficient():
    m = lr.compute_metric("decision_context", "avoid_chase",
                          [_rec(r5=-2, interp="supported")] * 3, NOW)
    assert m["confidence"] == "insufficient"
    assert m["enoughSamples"] is False
    assert "履歴不足" in m["interpretationJa"]
    assert "成績としては扱わないで" in m["caveatJa"]
    assert m["winRate5d"] is None


def test_n_5_to_19_early_tendency_low():
    m = lr.compute_metric("decision_context", "avoid_chase",
                          [_rec(r5=-2, interp="supported", dd5=-4)] * 8, NOW)
    assert m["confidence"] == "low"
    assert "初期傾向" in m["interpretationJa"]
    assert m["winRate5d"] is None                     # 勝率はn>=20まで出さない


def test_n_20_plus_medium_and_winrate_allowed():
    m = lr.compute_metric("supply_demand_rank", "A",
                          [_rec(r5=2.5, interp="supported")] * 25, NOW)
    assert m["confidence"] == "medium"
    assert m["winRate5d"] == 1.0
    assert m["avgReturn5d"] == 2.5


def test_n_50_high_still_cautious():
    m = lr.compute_metric("decision_context", "wait", [_rec(r5=0)] * 55, NOW)
    assert m["confidence"] == "high"
    assert "保証" in m["caveatJa"]                    # 強めでも慎重


# ── interpretations ─────────────────────────────────────────────────────────
def test_avoid_chase_useful_vs_over_conservative():
    useful = lr.compute_metric("decision_context", "avoid_chase",
                               [_rec(r5=-1.5, interp="supported", dd5=-4)] * 8, NOW)
    assert "有効に見えます" in useful["interpretationJa"]
    over = lr.compute_metric("decision_context", "avoid_chase",
                             [_rec(r5=6, interp="contradicted", dd5=-0.5)] * 8, NOW)
    assert "保守的すぎる可能性" in over["interpretationJa"]
    assert "履歴数" in over["interpretationJa"]        # 断定しない


def test_pullback_supported_and_missed_opportunity():
    ok = lr.compute_metric("decision_context", "add_only_on_pullback",
                           [_rec(r5=1, interp="supported", dd5=-3)] * 6, NOW)
    assert "機能しています" in ok["interpretationJa"]
    missed = lr.compute_metric("decision_context", "add_only_on_pullback",
                               [_rec(r5=6, interp="contradicted", dd5=-0.5)] * 6, NOW)
    assert "機会を逃している可能性" in missed["interpretationJa"]


def test_sd_ab_continuation_and_de_caution():
    ab = lr.compute_metric("supply_demand_rank", "A",
                           [_rec(r5=2.4, interp="supported")] * 7, NOW)
    assert "補助材料として機能" in ab["interpretationJa"]
    de = lr.compute_metric("supply_demand_rank", "D",
                           [_rec(r5=-2.2, interp="supported")] * 7, NOW)
    assert "弱含みやすい" in de["interpretationJa"]


def test_improving_but_heavy_tracked_separately_never_good():
    fade = lr.compute_metric("supply_demand_condition", "improving_but_heavy",
                             [_rec(r5=0.3, ru5=4, interp="mixed")] * 6, NOW)
    assert "戻り売りで失速しやすい" in fade["interpretationJa"]
    assert "需給良好" not in fade["interpretationJa"]
    cont = lr.compute_metric("supply_demand_condition", "improving_but_heavy",
                             [_rec(r5=3.0, ru5=3.5, interp="mixed")] * 6, NOW)
    assert "続伸したケース" in cont["interpretationJa"]
    assert "需給良好" not in cont["interpretationJa"]


def test_squeeze_fade_review():
    m = lr.compute_metric("supply_demand_condition", "squeeze_prone",
                          [_rec(r5=0.5, ru5=5, interp="supported")] * 6, NOW)
    assert "失速しやすい" in m["interpretationJa"]


def test_p0_not_judged_wrong_when_price_flat():
    flat = lr.compute_metric("action_priority", "P0",
                             [_rec(r5=0.2, dd5=-1, ru5=1)] * 6, NOW)
    assert "妥当性は別途評価" in flat["interpretationJa"]
    moved = lr.compute_metric("action_priority", "P0",
                              [_rec(r5=-4, dd5=-6, ru5=1)] * 6, NOW)
    assert "妥当だった可能性" in moved["interpretationJa"]


# ── label review / insights / status ────────────────────────────────────────
def test_label_review_statuses():
    early = lr.label_review(lr.compute_metric("decision_context", "hold",
                                              [_rec()] * 2, NOW))
    assert early["status"] == "too_early"
    prom = lr.label_review(lr.compute_metric("decision_context", "avoid_chase",
                                             [_rec(r5=-2, interp="supported", dd5=-4)] * 8, NOW),
                           examples=[_rec(r5=-2, interp="supported")])
    assert prom["status"] == "promising"
    assert prom["caveatJa"]


def test_insights_insufficient_history_dominates():
    ms = [lr.compute_metric("decision_context", "hold", [_rec()] * 2, NOW),
          lr.compute_metric("decision_context", "wait", [_rec()] * 1, NOW)]
    ins = lr.build_insights(ms, NOW)
    assert any(i["insightType"] == "insufficient_history" for i in ins)
    assert all("売買" not in i.get("recommendationJa", "") or "指示" not in i["recommendationJa"]
               for i in ins)


def test_public_status_redacted():
    st = lr.public_status(now_iso=NOW, sources={"decisionQuality": False})
    assert st["serverStoresRecords"] is False and st["publicLeakSafe"] is True
    blob = str(st)
    for banned in ("quantity", "averageCost", "ownerAction", "weightPct", "Pnl"):
        assert banned not in blob, banned
    assert "成績として扱わない" in st["noteJa"]


def test_pure_and_no_trading():
    src = open("argus_learning_review.py", encoding="utf-8").read()
    for banned in ("place_order", "order(", "broker_login", "trd_env", "unlock_trade"):
        assert banned not in src, banned
    for banned_import in ("import requests", "import urllib", "import socket",
                          "import datetime"):
        assert banned_import not in src, banned_import
