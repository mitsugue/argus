"""V11.8.0 Position / Exposure Engine — pure-module tests.

Discipline: unknown totals never classify as high, no fabricated P&L/weights,
trim_consideration is a review label not a sell order, watch-only ≠ held,
Japanese owner-readable why everywhere.
"""
import argus_position_exposure as px

NOW = "2026-07-04T09:00:00+00:00"


def _pos(**kw):
    base = {"symbol": "5803", "market": "JP", "name": "フジクラ",
            "quantity": 100, "averageCost": 5000, "currentPrice": 6000}
    base.update(kw)
    return px.normalize_position(base, NOW)


# ── model validation ────────────────────────────────────────────────────────
def test_normalize_computes_value_and_pnl_only_with_full_data():
    p = _pos()
    assert p["marketValue"] == 600000 and p["costBasis"] == 500000
    assert p["unrealizedPnl"] == 100000 and p["unrealizedPnlPct"] == 20.0
    assert p["held"] and p["assetClass"] == "jp_stock" and p["currency"] == "JPY"


def test_normalize_never_fabricates():
    no_qty = _pos(quantity=None)
    assert no_qty["marketValue"] is None and no_qty["unrealizedPnl"] is None
    assert not no_qty["held"]
    no_cost = _pos(averageCost=None)
    assert no_cost["marketValue"] is not None      # value OK (qty×price)
    assert no_cost["unrealizedPnl"] is None        # but NO P&L without cost
    zero_qty = _pos(quantity=0)
    assert not zero_qty["held"]


def test_stale_flag_caps_confidence():
    p = _pos(staleDataFlag=True)
    assert p["staleDataFlag"] and p["confidence"] <= 0.4


def test_theme_classification_conservative():
    assert px.classify_theme("NVDA") == "ai_infrastructure"
    assert px.classify_theme("5803") == "ai_infrastructure"
    assert px.classify_theme("6965") == "semiconductor_photonics"
    assert px.classify_theme("6584") == "physical_ai_robotics"
    assert px.classify_theme("8058") == "trading_commodity"
    assert px.classify_theme("314A") == "gold"
    assert px.classify_theme("BTC", market="CRYPTO") == "crypto"
    assert px.classify_theme("XXXX9") == "other"          # unknown → other, never guessed
    assert px.classify_theme("EMAXIS", asset_type="core_fund") == "index_core"


# ── exposure ────────────────────────────────────────────────────────────────
def _book(usd_jpy=150.0):
    ps = [
        _pos(),                                                        # 600k JPY fujikura(ai)
        _pos(symbol="9984", name="SBG", quantity=100, averageCost=8000, currentPrice=9000),   # 900k ai
        _pos(symbol="NVDA", market="US", quantity=10, averageCost=100, currentPrice=150),     # 1500USD ai
        _pos(symbol="314A", name="ゴールドETF", quantity=100, averageCost=2000, currentPrice=2100),  # 210k gold
    ]
    return ps, px.compute_exposure(ps, usd_jpy=usd_jpy)


def test_exposure_aggregation_and_concentration():
    ps, ex = _book()
    assert ex["totalMarketValue"] == 600000 + 900000 + 1500 * 150 + 210000
    assert ex["concentrationTop1"] is not None and 0 < ex["concentrationTop1"] < 1
    assert abs(sum(ex["byTheme"].values()) - 1.0) < 0.01
    assert ex["AIThemeExposure"] > 0.8              # 3 of 4 are AI-complex
    assert ex["themeConcentrationRisk"] == "high"
    assert ex["goldExposure"] > 0
    assert ex["JapanEquityExposure"] and ex["USDExposure"]
    assert ex["unknownExposureShare"] == 0.0


def test_unknown_total_is_unknown_not_high():
    ps = [_pos(quantity=None), _pos(symbol="NVDA", market="US", quantity=None)]
    ex = px.compute_exposure(ps, usd_jpy=150.0)
    assert ex["totalMarketValue"] is None
    assert ex["singleNameRisk"] is None and ex["themeConcentrationRisk"] is None
    assert ex["noteJa"] and "未入力" in ex["noteJa"]


def test_usd_without_rate_counts_unknown_not_fabricated():
    ps = [_pos(), _pos(symbol="NVDA", market="US", quantity=10, averageCost=100, currentPrice=150)]
    ex = px.compute_exposure(ps, usd_jpy=None)
    assert ex["totalMarketValue"] == 600000          # only the JPY leg
    assert ex["unknownExposureShare"] == 0.5


def test_single_name_critical_threshold():
    ps = [_pos(symbol="9984", quantity=1000, averageCost=8000, currentPrice=9000),
          _pos(symbol="314A", quantity=100, averageCost=2000, currentPrice=2100)]
    ex = px.compute_exposure(ps, usd_jpy=150.0)
    assert ex["concentrationTop1"] > 0.9
    assert ex["singleNameRisk"] == "critical"


# ── risk signals ────────────────────────────────────────────────────────────
def test_concentration_and_theme_signals_japanese():
    ps, ex = _book()
    sigs = px.position_risk_signals(ps, ex)
    assert sigs
    for s in sigs:
        assert s["ownerReadableWhyJa"] and s["checkNextJa"]
        assert s["actionImplication"] in px.ACTIONS
        assert "売買指示ではない" in s["complianceNote"]
    types = {s["riskType"] for s in sigs}
    assert "theme_overcrowding" in types or "concentration" in types


def test_held_vs_watchlist_flow_overlay():
    ps, ex = _book()
    held_sigs = px.position_risk_signals(
        ps, ex, ctx={"flowBySymbol": {"5803": {"flowClass": "panic_selling"}}})
    assert any(s["riskType"] in ("regime_mismatch", "event_risk") and s["symbol"] == "5803"
               and "保有中" in s["ownerReadableWhyJa"] for s in held_sigs)
    # watch-only TSLA (not in positions) must NOT create a held-position risk
    watch_sigs = px.position_risk_signals(
        ps, ex, ctx={"flowBySymbol": {"TSLA": {"flowClass": "panic_selling"}}})
    assert not any(s["symbol"] == "TSLA" for s in watch_sigs)


def test_drawdown_and_event_and_stale_signals():
    ps = [_pos(currentPrice=3500),                       # -30% drawdown
          _pos(symbol="9984", staleDataFlag=True)]
    ex = px.compute_exposure(ps, usd_jpy=150.0)
    sigs = px.position_risk_signals(ps, ex, ctx={"eventSymbols": {"9984"}})
    types = {(s["symbol"], s["riskType"]) for s in sigs}
    assert ("5803", "drawdown") in types
    assert ("9984", "event_risk") in types
    assert ("9984", "data_stale") in types


def test_no_positions_yields_honest_placeholder():
    sigs = px.position_risk_signals([], px.compute_exposure([]))
    assert len(sigs) == 1 and sigs[0]["riskLevel"] == "unknown"
    assert "未入力" in sigs[0]["ownerReadableWhyJa"]


# ── add-more readiness ──────────────────────────────────────────────────────
def test_add_more_ladder():
    ps, ex = _book()
    p5803 = ps[0]
    # chase blocker wins
    r = px.add_more_readiness(p5803, ex, {"priorRunupPct": 20})
    assert r["readiness"] == "avoid_chase" and "追う" in r["whyJa"] or "高値掴み" in r["whyJa"]
    # event blocker
    r2 = px.add_more_readiness(p5803, ex, {"eventSymbols": {"5803"}})
    assert r2["readiness"] == "wait"
    # theme concentration → pullback-only (AI theme is >40% in _book)
    r3 = px.add_more_readiness(p5803, ex, {})
    assert r3["readiness"] in ("add_only_on_pullback", "wait")
    # gold position with no blockers → small add allowed
    r4 = px.add_more_readiness(ps[3], ex, {})
    assert r4["readiness"] == "add_allowed_small"
    assert "小さく" in r4["whyJa"]


def test_add_more_riskoff_regime_blocks_growth():
    ps, ex = _book()
    r = px.add_more_readiness(ps[1], ex, {"regimeRiskOff": True})
    assert r["readiness"] in ("add_only_on_pullback", "wait")


def test_add_more_unknown_without_quantity():
    p = _pos(quantity=None)
    p["held"] = True    # held per owner state but size unknown
    ex = px.compute_exposure([p])
    r = px.add_more_readiness(p, ex, {})
    assert r["readiness"] == "unknown" and "未入力" in r["whyJa"]


def test_watch_only_readiness_is_monitor():
    ps, ex = _book()
    watch = px.normalize_position({"symbol": "TSLA", "market": "US"}, NOW)
    r = px.add_more_readiness(watch, ex, {})
    assert r["readiness"] == "monitor" and "保有なし" in r["whyJa"]


# ── regime sensitivity + watchlist level + handoff ─────────────────────────
def test_regime_sensitivity_ai_heavy_headwind():
    ps, ex = _book()
    sens = px.regime_sensitivity(ex, "RISK_OFF")
    assert sens["headwinds"]
    assert "AI" in sens["summaryJa"]
    assert any("金" in t for t in sens["tailwinds"])


def test_regime_sensitivity_no_data_is_provisional():
    sens = px.regime_sensitivity(px.compute_exposure([]), "RISK_ON")
    assert "未入力" in sens["summaryJa"] or "参考値" in sens["summaryJa"]


def test_watchlist_theme_exposure_has_no_value_fields():
    wl = px.watchlist_theme_exposure([
        {"symbol": "NVDA", "market": "US"}, {"symbol": "5803", "market": "JP"},
        {"symbol": "9984", "market": "JP"}, {"symbol": "8058", "market": "JP"},
        {"symbol": "BTC", "market": "CRYPTO"}])
    blob = str(wl)
    for banned in ("quantity", "averageCost", "marketValue", "totalMarketValue", "Pnl"):
        assert banned not in blob
    assert wl["totalSymbols"] == 5
    assert wl["byTheme"]["ai_infrastructure"] == 3
    assert "保有数量ではありません" in wl["noteJa"]


def test_handoff_section_watchlist_only_with_privacy_note():
    wl = px.watchlist_theme_exposure([{"symbol": "NVDA", "market": "US"}])
    h = px.handoff_section(wl)
    assert "サーバーは保有を一切知りません" in h["privacyNoteJa"]
    assert "反対解釈" in h["opposingViewJa"]


# ── compliance ──────────────────────────────────────────────────────────────
def test_no_trading_vocabulary():
    src = open("argus_position_exposure.py", encoding="utf-8").read()
    for banned in ("place_order", "order(", "broker_login", "brokerage", "trd_env",
                   "unlock_trade", "全力買い", "売却しろ"):
        assert banned not in src, banned
    # pure module: no network/persistence imports at all
    for banned_import in ("import requests", "import urllib", "import socket",
                          "import http", "open("):
        assert banned_import not in src, banned_import
    # trim is labeled as review, not an instruction
    assert "売り指示ではない" in px.ACTION_JA["trim_consideration"]
