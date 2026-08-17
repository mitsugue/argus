"""Tests for the v4 dry-run normalization (argus_v4_dryrun.py)."""
import argus_v4_dryrun as DR


def test_normalize_prediction_row():
    p = {"symbol": "NVDA", "market": "US", "cohortId": "tactical_benchmark_fixed",
         "scenarios": [{"label": "rebound_attempt", "p": 60}], "price": 200.0,
         "marketClock": {"targets": [{"horizon": "1d", "targetTradingDate": "2026-06-24"}]}}
    n = DR._normalize(p)
    assert n["symbol"] == "NVDA" and n["market"] == "US"
    assert n["scored"] == {"1d": None, "3d": None, "5d": None}


def test_normalize_sensor_row_uses_sensor_and_kind():
    s = {"sensor": "1306", "kind": "equity_jp", "cohortId": "regime_sensor_fixed",
         "scenarios": [{"label": "sideways_stabilization", "p": 50}], "price": 723.0,
         "bandPct": 2.0, "marketClock": {"targets": []}}
    n = DR._normalize(s)
    assert n["symbol"] == "1306" and n["market"] == "JP"   # kind→market mapping
    assert n["bandPct"] == 2.0


def test_normalize_skips_without_scenarios_or_symbol():
    assert DR._normalize({"symbol": "X", "market": "US"}) is None       # no scenarios
    assert DR._normalize({"scenarios": [{"label": "x", "p": 1}]}) is None  # no symbol


def test_rows_from_snapshot_combines_both():
    snap = {"predictions": [{"symbol": "A"}], "sensors": [{"sensor": "1"}]}
    assert len(DR._rows_from_snapshot(snap)) == 2
