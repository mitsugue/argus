"""Tests for the Calibration Ledger v4 scorer (argus_ledger_v4.py)."""
import argus_ledger_v4 as V4


def _rec(symbol, market, cohort, scenarios, price, targets, scored=None):
    return {
        "symbol": symbol, "market": market, "cohortId": cohort,
        "scenarios": scenarios, "priceAtPrediction": price,
        "marketClock": {"targets": [{"horizon": h, "targetTradingDate": d} for h, d in targets.items()]},
        "scored": scored if scored is not None else {"1d": None, "3d": None, "5d": None},
    }


def test_scenarios_dict_accepts_both_shapes():
    assert V4._scenarios_dict([{"label": "rebound_attempt", "p": 70}])["rebound_attempt"] == 70
    assert V4._scenarios_dict({"rebound_attempt": 70})["rebound_attempt"] == 70


def test_horizon_due():
    assert V4.horizon_due("2026-06-23", "2026-06-23") is True
    assert V4.horizon_due("2026-06-24", "2026-06-23") is False
    assert V4.horizon_due(None, "2026-06-23") is False


def test_scores_jp_due_horizon_append_only():
    rec = _rec("7203", "JP", "tactical_benchmark_fixed",
               [{"label": "rebound_attempt", "p": 70}, {"label": "sideways_stabilization", "p": 30}],
               100.0, {"1d": "2026-06-23", "3d": "2026-06-25", "5d": "2026-06-27"})
    out = V4.score_records([rec], lambda s: 105.0, "2026-06-23")  # +5% → rebound
    assert out["scored"] == 1
    s1 = rec["scored"]["1d"]
    assert s1["realizedClass"] == "rebound_attempt" and s1["argmaxHit"] is True
    assert rec["scored"]["3d"] is None  # not due yet
    # append-only: re-running must NOT change an already-scored horizon
    rec_price_was = s1
    V4.score_records([rec], lambda s: 999.0, "2026-06-23")
    assert rec["scored"]["1d"] is rec_price_was


def test_us_crypto_held_invalid_clock():
    us = _rec("NVDA", "US", "tactical_benchmark_fixed", [{"label": "rebound_attempt", "p": 60}],
              100.0, {"1d": "2026-06-23"})
    out = V4.score_records([us], lambda s: 110.0, "2026-06-23")
    assert out["held"] == 1 and out["scored"] == 0
    assert us["scored"]["1d"]["status"] == "experimental_invalid_clock"


def test_pending_when_no_price():
    rec = _rec("7203", "JP", "tactical_benchmark_fixed", [{"label": "rebound_attempt", "p": 60}],
               100.0, {"1d": "2026-06-23"})
    V4.score_records([rec], lambda s: None, "2026-06-23")
    assert rec["scored"]["1d"] is None  # stays pending, retried later


def test_aggregate_by_cohort_excludes_held():
    recs = [
        _rec("7203", "JP", "tactical_benchmark_fixed", [{"label": "rebound_attempt", "p": 70}], 100.0, {"1d": "2026-06-23"}),
        _rec("1306", "JP", "regime_sensor_fixed", [{"label": "downside_continuation", "p": 70}], 100.0, {"1d": "2026-06-23"}),
        _rec("NVDA", "US", "tactical_benchmark_fixed", [{"label": "rebound_attempt", "p": 70}], 100.0, {"1d": "2026-06-23"}),
    ]
    # 7203 +5% rebound (hit), 1306 +5% but predicted downside (miss), NVDA held
    prices = {"7203": 105.0, "1306": 105.0}
    V4.score_records(recs, lambda s: prices.get(s), "2026-06-23")
    agg = V4.aggregate_by_cohort(recs)
    # tactical has only the JP 7203 numeric score (NVDA held, excluded)
    assert agg["cohorts"]["tactical_benchmark_fixed"]["1d"]["n"] == 1
    assert agg["cohorts"]["tactical_benchmark_fixed"]["1d"]["hitRate"] == 1.0
    assert agg["cohorts"]["regime_sensor_fixed"]["1d"]["hitRate"] == 0.0  # downside missed
    assert "rpsMean" in agg["cohorts"]["regime_sensor_fixed"]["1d"]


def test_band_default_by_market():
    assert V4._record_band({"market": "CRYPTO"}) == 3.0
    assert V4._record_band({"market": "JP", "bandPct": 4.5}) == 4.5   # explicit wins
    assert V4._record_band({"market": "ZZZ"}) == 2.0


def test_no_force_overwrite_surface():
    # the scorer must not expose a way to rewrite recorded scenarios/prices
    for bad in ("overwrite", "force", "rewrite", "delete"):
        assert not any(bad in n.lower() for n in dir(V4))
