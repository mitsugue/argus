"""Market shock fixtures — the six mandated regression classes (v13.5.1)."""
from datetime import datetime, timezone

import argus_market_shock as shock

NOW = datetime(2026, 8, 19, 12, 0, tzinfo=timezone.utc)
NOW_EPOCH = NOW.timestamp()


def _series(levels, end_day=19):
    """Ascending daily observations ending 2026-08-<end_day>."""
    rows = []
    day = end_day
    month = 8
    for value in reversed(levels):
        rows.append({"date": f"2026-{month:02d}-{day:02d}", "value": value})
        day -= 1
        if day == 0:
            month -= 1
            day = 28
    return list(reversed(rows))


def _flat_history(level, count):
    return [level] * count


def test_fixture1_long_end_treasury_shock_detected():
    """US30Y pushes above 5% to a window high → CRITICAL, evidence explicit."""
    levels = _flat_history(4.6, 250) + [4.75, 4.85, 4.92, 4.97, 5.03]
    result = shock.evaluate_long_end_rates(_series(levels), now=NOW)
    assert result["status"] == "EVALUATED"
    assert result["severity"] == "CRITICAL"
    assert result["level"] == 5.03
    assert result["isWindowHigh"] is True
    assert result["change5dBp"] >= 25
    assert "level_above_5pct_at_extreme" in result["reasons"]


def test_fixture1b_velocity_shock_without_5pct_level():
    """A 30bp+/5d long-end surge is HIGH even below the 5% level line."""
    levels = _flat_history(4.2, 250) + [4.25, 4.32, 4.41, 4.48, 4.55]
    result = shock.evaluate_long_end_rates(_series(levels), now=NOW)
    assert result["severity"] == "HIGH"
    assert "velocity_5d_extreme" in result["reasons"]


def test_fixture2_hormuz_escalation_detected():
    """Multi-outlet Strait of Hormuz escalation → HIGH with corroboration."""
    hits = [{"title": f"Iran threatens Strait of Hormuz closure after strikes ({i})",
             "domain": f"outlet{i}.example", "sourceEpoch": NOW_EPOCH - 1200}
            for i in range(5)]
    result = shock.evaluate_news_theme(hits, theme_key="energy_geopolitics",
                                       now_epoch=NOW_EPOCH)
    assert result["severity"] == "HIGH"
    assert result["outletCount"] == 5
    assert "critical_phrases_broadly_corroborated" in result["reasons"]


def test_fixture3_ordinary_headline_never_high():
    """Broad but non-critical coverage caps at MEDIUM; thin coverage at LOW."""
    ordinary = [{"title": f"Markets steady as investors await data ({i})",
                 "domain": f"outlet{i}.example", "sourceEpoch": NOW_EPOCH - 600}
                for i in range(6)]
    result = shock.evaluate_news_theme(ordinary, theme_key="geopolitics",
                                       now_epoch=NOW_EPOCH)
    assert result["severity"] in ("LOW", "MEDIUM")
    assert result["severity"] != "HIGH"
    thin = ordinary[:2]
    result_thin = shock.evaluate_news_theme(thin, theme_key="geopolitics",
                                            now_epoch=NOW_EPOCH)
    assert result_thin["severity"] in ("LOW", "MEDIUM")


def test_fixture4_stale_evidence_never_current():
    """Stale headlines and stale series must not produce a current alert."""
    stale_hits = [{"title": "Strait of Hormuz attack shakes markets",
                   "domain": f"outlet{i}.example",
                   "sourceEpoch": NOW_EPOCH - 8 * 3600} for i in range(5)]
    result = shock.evaluate_news_theme(stale_hits, theme_key="energy_geopolitics",
                                       now_epoch=NOW_EPOCH)
    assert result["severity"] is None
    assert "no_fresh_hits" in result["reasons"]

    rates = shock.evaluate_long_end_rates(
        [{"date": f"2026-05-{d:02d}", "value": 4.5} for d in range(1, 29)]
        + [{"date": f"2026-06-{d:02d}", "value": 4.6} for d in range(1, 29)]
        + [{"date": "2026-07-01", "value": 5.1}], now=NOW)
    assert rates["status"] == "DATA_GATED"
    assert rates["reason"] == "series_stale"


def test_fixture5_conflicting_reports_stay_conservative():
    """Simultaneous escalation + ceasefire reports → conservative MEDIUM."""
    hits = ([{"title": "Missile attack near Strait of Hormuz reported",
              "domain": f"a{i}.example", "sourceEpoch": NOW_EPOCH - 900}
             for i in range(3)]
            + [{"title": "Ceasefire announced in Gulf conflict",
                "domain": f"b{i}.example", "sourceEpoch": NOW_EPOCH - 800}
               for i in range(3)])
    result = shock.evaluate_news_theme(hits, theme_key="energy_geopolitics",
                                       now_epoch=NOW_EPOCH)
    assert result["conflicting"] is True
    assert result["severity"] == "MEDIUM"
    assert "conflicting_reports_conservative" in result["reasons"]


def test_fixture6_cross_market_confirmation_policy():
    """Two+ confirming market signals raise severity exactly one notch; one
    signal raises nothing; confirmation can never create an event."""
    upgraded = shock.apply_cross_market_confirmation(
        "MEDIUM", vix_change=3.1, usd_jpy_change=-2.0, us10y_change_bp=4.0)
    assert upgraded["confirmed"] is True
    assert upgraded["severity"] == "HIGH"
    single = shock.apply_cross_market_confirmation(
        "MEDIUM", vix_change=3.1, usd_jpy_change=0.2, us10y_change_bp=1.0)
    assert single["confirmed"] is False
    assert single["severity"] == "MEDIUM"
    nothing = shock.apply_cross_market_confirmation(
        None, vix_change=9.9, usd_jpy_change=9.9, us10y_change_bp=99.0)
    assert nothing["severity"] is None


def test_view_assembly_orders_by_severity_and_stays_truthful():
    levels = _flat_history(4.6, 250) + [4.75, 4.85, 4.92, 4.97, 5.03]
    long_end = shock.evaluate_long_end_rates(_series(levels), now=NOW)
    theme = shock.evaluate_news_theme(
        [{"title": "Strait of Hormuz closure threatened",
          "domain": f"o{i}.example", "sourceEpoch": NOW_EPOCH - 600}
         for i in range(5)],
        theme_key="energy_geopolitics", now_epoch=NOW_EPOCH)
    view = shock.build_market_shock_view(
        long_end=long_end, themes=[theme],
        cross_market={"vixChange": 0.5, "usdJpyChange": 0.1,
                      "us10yChangeBp": 2.0},
        now_iso="2026-08-19T12:00:00Z")
    assert view["schemaVersion"] == shock.MARKET_SHOCK_SCHEMA
    assert view["eventCount"] == 2
    assert view["events"][0]["severity"] == "CRITICAL"
    assert view["events"][0]["eventClass"] == "LONG_END_RATES"
    assert view["events"][0]["eventId"] == "long-end-rates"
    assert view["automaticAiCalls"] == 0
    # no confirmation signals → severities unchanged
    assert view["events"][0]["crossMarket"]["confirmed"] is False


def test_low_single_outlet_stays_off_shock_surface():
    theme = shock.evaluate_news_theme(
        [{"title": "Minor refinery outage", "domain": "one.example",
          "sourceEpoch": NOW_EPOCH - 600}],
        theme_key="energy_geopolitics", now_epoch=NOW_EPOCH)
    assert theme["severity"] == "LOW"
    view = shock.build_market_shock_view(
        long_end={"status": "DATA_GATED", "reason": "series_stale"},
        themes=[theme], cross_market={}, now_iso="2026-08-19T12:00:00Z")
    assert view["eventCount"] == 0


# ━━━ v13.5.32 — official sensor lane carries the direction vocabulary ━━━

def test_long_end_rates_shock_carries_rates_up_direction():
    """Review item 3: the US30Y spike sensor must speak the SAME direction
    language as mail news — its trigger condition IS the 'up' polarity."""
    long_end = {"status": "EVALUATED", "severity": "HIGH", "level": 5.02,
                "isWindowHigh": True, "latestDate": "2026-08-22"}
    doc = shock.build_market_shock_view(
        long_end=long_end, themes=[],
        cross_market={"vixChange": 2.0, "usdJpyChange": None,
                      "us10yChangeBp": 9.0},
        now_iso="2026-08-23T00:00:00Z")
    event = next(e for e in doc["events"]
                 if e["eventClass"] == "LONG_END_RATES")
    direction = event["impactDirection"]
    assert direction["polarity"] == "up"
    assert direction["directionByTarget"]["growth"] == "BEARISH"
    assert direction["directionByTarget"]["banks"] == "BULLISH"
    assert direction["directionAuthority"] is False


def test_theme_shock_direction_from_headline_polarity():
    theme = {"status": "EVALUATED", "severity": "MEDIUM", "themeKey":
             "geopolitics", "outletCount": 2, "headlineCount": 3,
             "conflicting": False, "reasons": ["multi_outlet"],
             "sample": [{"title": "ミサイル攻撃が拡大", "domain": "nikkei.com",
                         "epoch": 1787200000}]}
    doc = shock.build_market_shock_view(
        long_end={"status": "DATA_GATED"}, themes=[theme],
        cross_market={}, now_iso="2026-08-23T00:00:00Z")
    event = doc["events"][0]
    assert event["impactDirection"]["polarity"] == "escalate"
    assert event["impactDirection"]["directionByTarget"]["broadMarket"] == "BEARISH"
