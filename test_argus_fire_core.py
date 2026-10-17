"""V11.19.1 FIRE Core tests — spec §11."""
import json
import re

import argus_fire_core as fc
import argus_portfolio_strategy as ps

NOW = "2026-07-05T12:00:00+09:00"


def _pos(**kw):
    base = {"fundName": "eMAXIS Slim 全世界", "symbol": "EMAXIS-ACWI",
            "accountType": "nisa", "units": 100.0, "navPrice": 25000.0,
            "navDate": "2026-07-04", "monthlyContribution": 50000.0,
            "contributionFrequency": "monthly", "averageCost": 20000.0,
            "dataSource": "existing_argus", "lastUpdatedAt": "2026-07-04"}
    base.update(kw)
    return base


def _summary(**kw):
    base = {"positions": [_pos()], "tacticalTotal": 500000.0,
            "satelliteTotal": 300000.0, "hedgeTotal": 200000.0,
            "fireCoreEtfTotal": 0.0}
    base.update(kw)
    return fc.build_summary(base, NOW)


# ── position validation / math ───────────────────────────────────────────────

def test_units_x_nav_market_value():
    p = fc.normalize_position(_pos(), NOW)
    assert p["marketValue"] == 100.0 * 25000.0
    assert p["valueSource"] == "units_x_nav"
    assert p["totalCost"] == 100.0 * 20000.0
    assert p["unrealizedPnl"] == 500000.0
    assert p["unrealizedPnlPct"] == 25.0
    assert p["accountType"] == "nisa"
    assert p["privacyLevel"] == "private_local"


def test_manual_value_only():
    p = fc.normalize_position({"fundName": "F", "marketValue": 1234567.0,
                               "lastUpdatedAt": "2026-07-05"}, NOW)
    assert p["marketValue"] == 1234567.0
    assert p["valueSource"] == "manual_value"
    assert p["unrealizedPnl"] is None            # cost unknown → no PnL
    assert p["unrealizedPnlPct"] is None


def test_missing_value_honest():
    p = fc.normalize_position({"fundName": "F"}, NOW)
    assert p["marketValue"] is None
    assert p["valueSource"] == "missing"
    assert p["staleDataFlag"] is None            # no date → unknown, not fabricated


def test_cost_missing_no_pnl():
    p = fc.normalize_position(_pos(averageCost=None, totalCost=None), NOW)
    assert p["marketValue"] is not None
    assert p["unrealizedPnl"] is None


def test_stale_flag():
    fresh = fc.normalize_position(_pos(navDate="2026-07-03"), NOW)
    old = fc.normalize_position(_pos(navDate="2026-06-20"), NOW)
    assert fresh["staleDataFlag"] is False
    assert old["staleDataFlag"] is True


# ── summary ──────────────────────────────────────────────────────────────────

def test_fire_core_total_and_contribution():
    s = _summary(positions=[_pos(), _pos(fundName="B", symbol="B",
                                         units=10.0, navPrice=10000.0,
                                         monthlyContribution=10000.0)])
    assert s["mutualFundTotal"] == 2500000.0 + 100000.0
    assert s["fireCoreTotal"] == 2600000.0
    assert s["monthlyContributionTotal"] == 60000.0
    assert s["annualContributionEstimate"] == 720000.0
    assert s["contributionDataStatus"] == "complete"
    assert s["valuationDataStatus"] == "current"
    assert "本丸資産" in s["ownerRuleJa"]


def test_tactical_to_core_ratio_bands():
    ok = _summary(tacticalTotal=500000.0)         # 0.2 vs 2.5M
    assert ok["tacticalToCoreBand"] == "ok"
    stretched = _summary(tacticalTotal=2000000.0)  # 0.8
    assert stretched["tacticalToCoreBand"] == "stretched"
    assert any("戦術枠がFIRE Coreに対して大きく" in w for w in stretched["warningJa"])
    exceeded = _summary(tacticalTotal=3000000.0)   # 1.2
    assert exceeded["tacticalToCoreBand"] == "exceeded"


def test_transfer_gains_opportunity():
    s = _summary(tacticalTotal=2000000.0)
    assert any("FIRE Coreへ移す検討余地" in o for o in s["opportunityJa"])


def test_contribution_missing_note():
    s = _summary(positions=[_pos(monthlyContribution=None)])
    assert s["contributionDataStatus"] == "missing"
    assert any("毎月積立額が未入力" in w for w in s["warningJa"])


def test_stale_valuation_warning():
    s = _summary(positions=[_pos(navDate="2026-06-01")])
    assert s["valuationDataStatus"] == "stale"
    assert any("評価額が未更新" in w for w in s["warningJa"])


def test_missing_valuation():
    s = _summary(positions=[{"fundName": "F", "monthlyContribution": 10000.0}])
    assert s["fireCoreTotal"] is None
    assert s["valuationDataStatus"] == "missing"
    assert "未入力" in s["ownerReadableSummaryJa"]
    assert s["tacticalToCoreBand"] == "unknown"


def test_no_positions_unknown():
    s = _summary(positions=[], tacticalTotal=None, satelliteTotal=None,
                 hedgeTotal=None)
    assert s["fireCoreTotal"] is None
    assert s["contributionDataStatus"] == "unknown"


# ── strategy integration (v11.19.0 module consumes fire-core flags) ─────────

def test_strategy_gets_fire_core_context():
    roles = [ps.classify_role("EMAXIS", "JP", {"assetName": "eMAXIS", "theme": "index_core",
                                               "assetType": "fund", "isHeld": True,
                                               "weightPct": 40.0})]
    s = ps.build_strategy({"roles": roles, "byThemePct": {"index_core": 40.0},
                           "noHoldings": False, "knownCoverage": 0.9,
                           "fireCore": {"known": True, "tacticalToCoreBand": "stretched",
                                        "contributionKnown": False}}, NOW)
    assert any("戦術枠がFIRE Coreに対して大きく" in w for w in s["strategicWarningsJa"])
    assert any("FIRE Coreへ移す検討余地" in o for o in s["strategicOpportunitiesJa"])
    assert any("毎月積立額が未入力のため、長期入金整合は判定保留" in w
               for w in s["fireAlignment"]["warningJa"] + s["strategicWarningsJa"]) or \
        any("積立" in m for m in s["missingDataJa"])


def test_strategy_fire_core_unknown_limits_alignment():
    roles = [ps.classify_role("5803", "JP", {"assetName": "フジクラ", "theme": "ai_infrastructure",
                                             "assetType": "stock", "isHeld": True,
                                             "weightPct": 100.0})]
    s = ps.build_strategy({"roles": roles, "byThemePct": {"ai_infrastructure": 100.0},
                           "noHoldings": False, "knownCoverage": 0.9,
                           "fireCore": {"known": False, "tacticalToCoreBand": "unknown",
                                        "contributionKnown": False}}, NOW)
    assert any("FIRE Core" in m for m in s["missingDataJa"])


# ── no fabrication / privacy ─────────────────────────────────────────────────

def test_no_fire_probability():
    variants = [_summary(), _summary(tacticalTotal=3000000.0),
                _summary(positions=[])]
    pat = re.compile(r"\d{1,3}\s*[%％]の確率|達成確率|到達年")
    for s in variants:
        assert not pat.search(json.dumps(s, ensure_ascii=False))


def test_public_status_redacted():
    d = fc.public_status(now_iso=NOW)
    assert d["serverKnowsFundData"] is False
    assert d["storageMode"] == "public_redacted"
    assert d["publicLeakSafe"] is True
    assert d["realtimePricingRequired"] is False
    blob = json.dumps(d, ensure_ascii=False)
    for banned in ("units", "navPrice", "marketValue", "monthlyContribution",
                   "accountType", "fireCoreTotal", "quantity", "averageCost"):
        assert banned not in blob, banned


def test_deterministic():
    a = json.dumps(_summary(), ensure_ascii=False)
    b = json.dumps(_summary(), ensure_ascii=False)
    assert a == b
