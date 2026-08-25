"""v13.5.14 — SHO-conditioned forecast engine (owner spec 2026-08-22).

The chart forecast is SHO's thinking routine: the analog search conditions on
the point-in-time credit / VIX / relative-strength state, with explicit
knowledge lags (a JP close cannot see that same evening's US prints) and the
rule that absence of a state dimension is a DIFFERENT situation, never a zero.
"""
import datetime as dt
import math

import argus_today_intelligence as ti


def _bars(count=900, seed_phase=0.0):
    rows = []
    day = dt.date(2019, 1, 7)
    value = 100.0
    index = 0
    while len(rows) < count:
        if day.weekday() < 5:
            drift = 0.0003 + math.sin(index / 13.0 + seed_phase) * 0.009
            open_ = value * (1 + math.sin(index / 5.0) * 0.002)
            close = value * (1 + drift)
            high = max(open_, close) * 1.008
            low = min(open_, close) * 0.992
            rows.append({"date": day.isoformat(), "open": open_, "high": high,
                         "low": low, "close": close,
                         "volume": 900_000 + (index % 17) * 30_000,
                         "availableFrom": day.isoformat(), "adjusted": True})
            value = close
            index += 1
        day += dt.timedelta(days=1)
    return rows


def _credit_rows(bars, heavy_from_index=0):
    """Weekly two-market balances; ratio flips heavy at heavy_from_index."""
    out = []
    for position in range(0, len(bars), 5):
        date = bars[position]["date"]
        available = (dt.date.fromisoformat(date)
                     + dt.timedelta(days=7)).isoformat()
        heavy = position >= heavy_from_index
        short = 8.0e11
        long_ = short * (6.0 if heavy else 2.0)
        for series, value in (("credit.short_balance", short),
                              ("credit.long_balance", long_)):
            out.append({"seriesId": series, "periodEnd": date,
                        "availableFrom": available,
                        "observedAt": available + "T00:00:00Z",
                        "value": value})
    return out


def _vix_rows(bars, level=15.0):
    out = []
    for index, bar in enumerate(bars):
        value = level + math.sin(index / 9.0) * 4.0
        available = (dt.date.fromisoformat(bar["date"])
                     + dt.timedelta(days=1)).isoformat()
        out.append({"date": bar["date"], "value": value,
                    "availableFrom": available})
    return out


def _context(bars):
    return {"creditRows": _credit_rows(bars),
            "vixRows": _vix_rows(bars),
            "usRows": _bars(len(bars), seed_phase=1.7)}


def test_sho_context_conditions_the_forecast():
    bars = _bars()
    plain = ti.calibrate_forecast(bars)
    conditioned = ti.calibrate_forecast(bars, sho_context=_context(bars),
                                        market="JP")
    meta = conditioned["shoConditioning"]
    assert meta["requested"] is True
    assert set(meta["currentFeatureKeys"]) >= {"creditRatio", "creditShortTn",
                                               "vixLevel", "vixChange10"}
    assert meta["coverageDays"] > 400
    assert plain["shoConditioning"]["requested"] is False
    # Same bars, different conditioning → the analog pool genuinely changes.
    plain_h5 = plain["horizons"]["5"]
    cond_h5 = conditioned["horizons"]["5"]
    assert cond_h5["signalFamily"] != plain_h5["signalFamily"] or \
        cond_h5["unroundedProbabilities"] != plain_h5["unroundedProbabilities"]
    assert "|credit_" in cond_h5["signalFamily"]


def test_jp_close_cannot_see_same_evening_us_prints():
    bars = _bars(120)
    vix = _vix_rows(bars)
    # Poison the same-date VIX value: if the JP path reads it, the level jumps.
    vix[-1]["value"] = 99.0
    context = {"creditRows": _credit_rows(bars), "vixRows": vix, "usRows": []}
    jp = ti._sho_daily_features(ti.normalize_bars(bars), context, "JP")
    us = ti._sho_daily_features(ti.normalize_bars(bars), context, "US")
    assert jp[-1]["vixLevel"] != 99.0, "JP must use strictly earlier VIX"
    assert us[-1]["vixLevel"] == 99.0, "US closes with the same-date print"


def test_absent_state_is_a_different_situation_not_zero():
    bars = _bars()
    # Credit exists only for the OLD half of the corpus; today has none.
    old_half = _credit_rows(bars[: len(bars) // 2])
    context = {"creditRows": old_half, "vixRows": [], "usRows": []}
    conditioned = ti.calibrate_forecast(bars, sho_context=context, market="JP")
    meta = conditioned["shoConditioning"]
    # Today's day knows no credit value → no credit key is fabricated as 0.
    assert "creditRatio" not in meta["currentFeatureKeys"]
    h5 = conditioned["horizons"]["5"]
    assert "|credit_" not in h5["signalFamily"]


def test_analyze_pit_filters_sho_context_and_stays_verified():
    bars = _bars(400)
    as_of = bars[-1]["date"] + "T23:59:59Z"
    clean = ti.analyze(bars, symbol="1321", market="JP",
                       sho_context=_context(bars), as_of=as_of)
    # A context row first known AFTER the cutoff must change NOTHING.
    poisoned_context = _context(bars)
    future = dict(poisoned_context["creditRows"][-1])
    future["availableFrom"] = "2099-01-01"
    future["value"] = 1.0
    poisoned_context["creditRows"] = poisoned_context["creditRows"] + [future]
    poisoned = ti.analyze(bars, symbol="1321", market="JP",
                          sho_context=poisoned_context, as_of=as_of)
    assert clean["pointInTime"]["verified"] is True
    assert set(clean["pointInTime"]["proofs"]) == {
        "bars", "shortSelling", "comparison"}
    assert clean["calibration"]["shoConditioning"]["requested"] is True
    assert poisoned["calibration"] == clean["calibration"]


def test_stale_credit_never_impersonates_todays_regime():
    bars = _bars()
    # The only credit prints are from the OLD half of the corpus.
    context = {"creditRows": _credit_rows(bars[: len(bars) // 2]),
               "vixRows": [], "usRows": []}
    conditioned = ti.calibrate_forecast(bars, sho_context=context, market="JP")
    meta = conditioned["shoConditioning"]
    assert "creditRatio" not in meta["currentFeatureKeys"]
    assert "|credit_" not in conditioned["horizons"]["5"]["signalFamily"]


def test_conditioned_forecast_is_deterministic():
    bars = _bars()
    context = _context(bars)
    left = ti.calibrate_forecast(bars, sho_context=context, market="JP")
    right = ti.calibrate_forecast(bars, sho_context=context, market="JP")
    assert left == right


def test_source_misconfiguration_is_reported_not_silent(monkeypatch):
    """v13.5.32 (external review item 6): a missing provider KEY must be
    distinguishable from an honest data gap — the conditioning metadata
    names the broken source instead of the vix dimension just vanishing."""
    bars = _bars(120)
    context = {"creditRows": [], "vixRows": [], "usRows": [],
               "sourceIssues": ["vix_provider_key_missing"]}
    result = ti.calibrate_forecast(
        bars, sho_context=context, market="JP")
    meta = result["shoConditioning"]
    assert meta["sourceIssues"] == ["vix_provider_key_missing"]
    clean = ti.calibrate_forecast(
        bars, sho_context={"creditRows": [], "vixRows": [], "usRows": []},
        market="JP")
    assert clean["shoConditioning"]["sourceIssues"] == []
