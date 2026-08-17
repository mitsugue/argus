"""Tests for the Downside Incident Response layer (argus_downside.py)."""
import argus_downside as D


def _top(inc):
    return inc["causeBuckets"][0]["cause"]


# 1. large drop with no news -> CAUSE_UNKNOWN_DOWNSIDE + REVIEW_REQUIRED
def test_large_drop_no_news_is_unknown_review():
    a = {"symbol": "5803", "market": "JP", "name": "フジクラ", "changePct": -6.2,
         "newsChecked": True, "catalyst": None, "tdnetConnected": False}
    inc = D.classify_incident(a, {"globalRegime": "RISK_ON"})
    assert inc is not None
    assert _top(inc) == "CAUSE_UNKNOWN_DOWNSIDE"
    assert inc["actionOverride"] == "REVIEW_REQUIRED"


# 2. market-wide drop -> MARKET_WIDE_SELL_OFF
def test_market_wide_selloff():
    a = {"symbol": "7203", "market": "JP", "changePct": -3.4, "newsChecked": True, "catalyst": None}
    m = {"globalRegime": "RISK_ON", "nikkeiProxyPct": -2.7, "jpBreadth": -2.0,
         "jpDecliners": 6, "jpTotal": 7, "vixStress": True}
    inc = D.classify_incident(a, m)
    assert _top(inc) == "MARKET_WIDE_SELL_OFF"
    assert inc["actionOverride"] in ("WAIT", "HOLD_CAUTION")
    assert "買い増し" in inc["doNotDoJa"]


# 3. theme group down (after a rally) -> THEME_PROFIT_TAKING
def test_theme_profit_taking():
    a = {"symbol": "5801", "market": "JP", "changePct": -4.5, "themePeersDown": True,
         "ret3d": 9.0, "ret5d": 14.0, "ret20d": 28.0, "newsChecked": True, "catalyst": None}
    inc = D.classify_incident(a, {"globalRegime": "RISK_ON"})
    assert _top(inc) == "THEME_PROFIT_TAKING"


# 4. stock-specific bad catalyst -> STOCK_SPECIFIC_BAD_NEWS
def test_stock_specific_bad_news():
    a = {"symbol": "285A", "market": "JP", "changePct": -7.0, "newsChecked": True,
         "catalyst": {"type": "edinet", "title": "業績下方修正"}, "vsIndexPct": -5.0}
    inc = D.classify_incident(a, {"globalRegime": "RISK_ON"})
    assert _top(inc) == "STOCK_SPECIFIC_BAD_NEWS"
    assert inc["actionOverride"] in ("TRIM_WATCH", "EXIT_WATCH", "REVIEW_REQUIRED")


# 5. negative big-money flow + weak close -> FLOW_DISTRIBUTION
def test_flow_distribution():
    a = {"symbol": "9984", "market": "JP", "changePct": -5.2, "flowRatio": -0.25,
         "volRatio": 1.6, "weakClose": True, "failedRecovery": True,
         "newsChecked": True, "catalyst": None}
    inc = D.classify_incident(a, {"globalRegime": "RISK_ON"})
    assert _top(inc) == "FLOW_DISTRIBUTION"
    assert inc["actionOverride"] in ("TRIM_WATCH", "REVIEW_REQUIRED")


# 6. plain HOLD is overridden on a large unexplained drop
def test_large_unexplained_drop_never_plain_hold():
    a = {"symbol": "6584", "market": "JP", "changePct": -6.0, "currentAction": "HOLD",
         "newsChecked": True, "catalyst": None}
    inc = D.classify_incident(a, {})
    assert inc["currentAction"] == "HOLD"
    assert inc["actionOverride"] != "HOLD"
    assert inc["actionOverride"] in D.ACTION_OVERRIDES


# 7. owner-held asset increases severity by one level vs watch-only
def test_owner_held_increases_severity():
    base = {"symbol": "5803", "market": "JP", "changePct": -3.5, "newsChecked": True, "catalyst": None}
    watch = D.classify_incident(dict(base, isHeld=False), {})
    held = D.classify_incident(dict(base, isHeld=True), {})
    assert D.SEVERITY_ORDER.index(held["severity"]) > D.SEVERITY_ORDER.index(watch["severity"])


# 8. no-news does not suppress the alert (still triggers, raises caution)
def test_no_news_does_not_suppress():
    a = {"symbol": "5803", "market": "JP", "changePct": -5.5, "newsChecked": True, "catalyst": None}
    inc = D.classify_incident(a, {})
    assert inc is not None
    assert any("安全の証明ではない" in x for x in inc["missingData"])


# 9. JP intraday breadth can override a global RISK_ON
def test_jp_overlay_overrides_global_risk_on():
    ov = D.jp_intraday_overlay({"globalRegime": "RISK_ON", "nikkeiProxyPct": -2.0,
                                "jpDecliners": 6, "jpTotal": 7, "highBetaDown": True})
    assert ov["globalRegime"] == "RISK_ON"
    assert ov["jpIntradayOverlay"] in ("CAUTION", "RISK_OFF_WATCH")
    assert "JP_BREADTH_RISK" in ov["flags"]


def test_jp_overlay_escalates_on_severe_incidents_despite_flat_breadth():
    # A few names crashing must not be hidden by a near-zero average breadth.
    ov = D.jp_intraday_overlay({"globalRegime": "RISK_ON", "jpBreadth": -0.3,
                                "jpDecliners": 3, "jpTotal": 7,
                                "jpSevereIncidents": 3, "jpCriticalIncidents": 3,
                                "ownerSevereAffected": True})
    assert ov["jpIntradayOverlay"] == "RISK_OFF_WATCH"
    assert ov["holderRiskOverlay"] == "REVIEW_REQUIRED"
    assert "JP_HIGH_BETA_SELL_OFF" in ov["flags"]


def test_jp_overlay_one_severe_is_caution():
    ov = D.jp_intraday_overlay({"globalRegime": "RISK_ON", "jpBreadth": 0.2,
                                "jpDecliners": 1, "jpTotal": 7, "jpSevereIncidents": 1})
    assert ov["jpIntradayOverlay"] == "CAUTION"


def test_jp_overlay_calm_stays_normal():
    ov = D.jp_intraday_overlay({"globalRegime": "RISK_ON", "nikkeiProxyPct": 0.3,
                                "jpDecliners": 2, "jpTotal": 7})
    assert ov["jpIntradayOverlay"] == "NORMAL"


# 10. notification contains cause + action override + next condition
def test_notification_actionable():
    a = {"symbol": "5803", "market": "JP", "name": "フジクラ", "changePct": -6.2,
         "isHeld": True, "newsChecked": True, "catalyst": None}
    inc = D.classify_incident(a, {})
    note = D.build_notification(inc)
    assert "5803" in note["title"] and "-6.2%" in note["title"]
    assert "アクション" in note["message"] and "/7" in note["message"]   # Action Level format
    assert "新規購入: 禁止" in note["message"] and "買い増し: 禁止" in note["message"]
    assert note["actionLevel"] in (1, 2, 3, 4, 5)
    assert "急落しています" != note["message"]
    # English locale variant
    en = D.build_notification(inc, locale="en")
    assert "ACTION" in en["message"] and "NEW ENTRY: BLOCKED" in en["message"]


# 11. no duplicate notification without a material change
def test_dedup_stable_without_change():
    a = {"symbol": "5803", "market": "JP", "changePct": -6.2, "newsChecked": True, "catalyst": None}
    k1 = D.classify_incident(a, {})["dedupKey"]
    k2 = D.classify_incident(dict(a, changePct=-6.4), {})["dedupKey"]   # same sev/cause/override
    assert k1 == k2
    assert not D.is_material_change(k1, k2)


def test_dedup_changes_on_material_shift():
    a = {"symbol": "5803", "market": "JP", "changePct": -3.2, "newsChecked": True, "catalyst": None}
    k1 = D.classify_incident(a, {})["dedupKey"]
    # severity jumps (drop deepens past serious) → new key
    k2 = D.classify_incident(dict(a, changePct=-6.5), {})["dedupKey"]
    assert D.is_material_change(k1, k2)


# 12. probabilities sum to 1
def test_probabilities_sum_to_one():
    for a in [
        {"symbol": "X", "market": "JP", "changePct": -6.0, "newsChecked": True, "catalyst": None},
        {"symbol": "Y", "market": "JP", "changePct": -4.0, "themePeersDown": True, "ret5d": 12.0},
        {"symbol": "Z", "market": "JP", "changePct": -5.0, "flowRatio": -0.2, "volRatio": 1.5},
    ]:
        inc = D.classify_incident(a, {"nikkeiProxyPct": -1.0})
        total = round(sum(b["probability"] for b in inc["causeBuckets"]), 2)
        assert total == 1.0, (a["symbol"], total)


# 13. missing TDnet is disclosed for JP names
def test_missing_tdnet_disclosed():
    a = {"symbol": "5803", "market": "JP", "changePct": -5.0, "tdnetConnected": False,
         "newsChecked": True, "catalyst": None}
    inc = D.classify_incident(a, {})
    assert any("TDnet" in x for x in inc["missingData"])


# 17. data-quality short-circuit when evidence is too thin
def test_data_quality_limited_when_blind():
    a = {"symbol": "5803", "market": "JP", "changePct": -4.0, "newsChecked": False,
         "flowRatio": None, "dataFreshnessOk": True}
    inc = D.classify_incident(a, {})
    assert inc["incidentType"] == "DATA_QUALITY_LIMITED"
    assert inc["status"] in ("live", "partial")


# below-threshold drops do not trigger
def test_small_drop_no_incident():
    a = {"symbol": "5803", "market": "JP", "changePct": -1.2, "newsChecked": True}
    assert D.classify_incident(a, {}) is None


# classify_incidents sorts most-urgent first
def test_classify_incidents_sorted():
    assets = [
        {"symbol": "A", "market": "JP", "changePct": -3.1, "newsChecked": True, "catalyst": None},
        {"symbol": "B", "market": "JP", "changePct": -9.0, "isHeld": True, "newsChecked": True,
         "catalyst": {"type": "news"}, "vsIndexPct": -6.0},
    ]
    out = D.classify_incidents(assets, {})
    assert out[0]["symbol"] == "B"   # critical/held first
    assert len(out) == 2


# 16. no automatic trading: module exposes no order/execute surface
def test_no_order_surface():
    for bad in ("place_order", "execute", "submit_order", "buy", "sell", "broker"):
        assert not hasattr(D, bad)


# ── scanner integration: catalyst detector + index proxy (v10.99) ──
def test_scanner_catalyst_detector_recent_vs_stale():
    import scanner
    from datetime import datetime, timezone, timedelta
    today = datetime.now(timezone.utc).date()
    fresh = (today - timedelta(days=1)).isoformat()
    stale = (today - timedelta(days=30)).isoformat()
    # recent filing → catalyst present, but never asserted negative
    c = scanner._downside_catalyst_for({"symbol": "X", "filings": [{"form": "8-K", "filingDate": fresh}]})
    assert c and c["recent"] is True and c["confirmedNegative"] is False
    # stale filing only → no catalyst
    assert scanner._downside_catalyst_for({"symbol": "X", "filings": [{"form": "8-K", "filingDate": stale}]}) is None
    # earnings just passed → catalyst
    assert scanner._downside_catalyst_for({"symbol": "X", "earnings": {"daysUntil": 0}}) is not None
    # nothing → None
    assert scanner._downside_catalyst_for({"symbol": "X"}) is None


def test_scanner_downside_endpoint_shape():
    import scanner
    d = scanner.get_downside_incidents()
    assert d["engineVersion"] == "downside-v1"
    assert isinstance(d["incidents"], list)
    assert "jpIntradayOverlay" in d and "holderRiskOverlay" in d
    for inc in d["incidents"]:
        total = round(sum(b["probability"] for b in inc["causeBuckets"]), 2)
        assert total == 1.0
        assert inc["actionOverride"] != "HOLD"


# ── owner-state escalation (v10.100) ──
def test_owner_state_held_escalates_vs_watch():
    base = {"symbol": "5803", "market": "JP", "changePct": -3.4, "newsChecked": True, "catalyst": None}
    watch = D.classify_incident(dict(base, ownerState="watch"), {})
    held = D.classify_incident(dict(base, ownerState="held"), {})
    assert D.SEVERITY_ORDER.index(held["severity"]) > D.SEVERITY_ORDER.index(watch["severity"])
    assert held["isHeld"] is True


def test_owner_state_protected_strictest():
    a = {"symbol": "5803", "market": "JP", "changePct": -3.2, "ownerState": "protected",
         "newsChecked": True, "catalyst": None}
    inc = D.classify_incident(a, {})
    assert inc["actionOverride"] != "HOLD"
    assert inc["actionOverride"] in D.ACTION_OVERRIDES
    assert inc["ownerState"] == "protected"


def test_strict_strictness_escalates_override():
    a = {"symbol": "7203", "market": "JP", "changePct": -3.1, "downsideStrictness": "strict",
         "newsChecked": True, "catalyst": None}
    inc = D.classify_incident(a, {})
    # a held/strict name on a real drop cannot sit at the mildest HOLD_CAUTION
    assert inc["actionOverride"] != "HOLD_CAUTION"
    assert inc["actionOverride"] != "HOLD"
