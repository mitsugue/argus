import datetime as dt
import math

import argus_today_intelligence as ti


def market_bars(count=1400):
    rows = []
    day = dt.date(2021, 1, 4)
    value = 100.0
    index = 0
    while len(rows) < count:
        if day.weekday() < 5:
            cycle = math.sin(index / 17.0) * 0.008
            drift = 0.00025 + cycle
            open_ = value * (1 + math.sin(index / 7.0) * 0.002)
            close = value * (1 + drift)
            high = max(open_, close) * 1.009
            low = min(open_, close) * 0.991
            rows.append({"date": day.isoformat(), "open": open_, "high": high,
                         "low": low, "close": close,
                         "volume": 1_000_000 + (index % 23) * 40_000,
                         "availableFrom": day.isoformat(), "adjusted": True})
            value = close
            index += 1
        day += dt.timedelta(days=1)
    return rows


def short_rows(count=100):
    start = dt.date(2025, 1, 6)
    out = []
    day = start
    index = 0
    while len(out) < count:
        if day.weekday() < 5:
            sell = 6_000_000_000 + index * 1_000_000
            regulated = 3_000_000_000 + (index % 7) * 10_000_000
            non_regulated = 1_000_000_000 + (index % 5) * 5_000_000
            out.append({"Date": day.isoformat(), "S33": "0050",
                        "SellExShortVa": sell, "ShrtWithResVa": regulated,
                        "ShrtNoResVa": non_regulated})
            index += 1
        day += dt.timedelta(days=1)
    return out


def test_probability_calibration_uses_effective_episodes_and_sums_to_100():
    result = ti.calibrate_forecast(market_bars())
    assert result["historyCount"] == 1400
    for horizon in ("1", "5", "20"):
        row = result["horizons"][horizon]
        assert row["rawOccurrenceCount"] >= row["episodeCount"]
        assert row["episodeCount"] == row["effectiveSampleCount"]
        assert row["cooldownTradingDays"] == int(horizon)
        assert row["walkForward"] is True
        assert row["noFutureLeakage"] is True
        assert row["brierScore"] is not None
        if row["calibrationStatus"] == "calibrated":
            assert sum(row["probabilities"].values()) == 100
            assert row["confidenceInterval"]
            assert row["targetProbabilities"]["upperTargetTouch"] is not None


def test_small_sample_never_displays_percentages():
    row = ti.calibrate_horizon(market_bars(70), 20)
    assert row["calibrationStatus"] in {"insufficient_history", "insufficient_sample"}
    assert row["probabilities"] is None


def test_daily_short_schema_is_distinct_and_has_rollups():
    normalized = ti.normalize_short_history(short_rows())
    summary = ti.short_selling_summary(normalized)
    latest = summary["latest"]
    assert summary["schemaVersion"] == "argus-daily-short-selling-v1"
    assert summary["seriesType"] == "daily_short_selling_turnover"
    assert summary["weeklyCreditShortIsSeparate"] is True
    assert summary["institutionalShortIsSeparate"] is True
    assert latest["totalShortRatio"] > 0
    assert latest["average5"] is not None
    assert latest["average20"] is not None
    assert 0 <= latest["rollingPercentile"] <= 100


def test_failed_rally_fixture_is_confirmed_without_forcing_probability():
    previous = {"open": 100, "high": 101, "low": 99, "close": 100, "volume": 1000}
    current = {"open": 102, "high": 105, "low": 98.5, "close": 99,
               "volume": 2200, "volumeRatio20": 1.8}
    result = ti.failed_rally_state(previous, current, short_change=-2.6,
                                   breadth_divergence=True)
    assert result["state"] == "CONFIRMED"
    assert result["conditions"]["gapUp"] is True
    assert result["conditions"]["closeBelowPrevious"] is True
    assert result["conditions"]["shortRatioFell"] is True


def test_failed_rally_does_not_promote_plain_up_day():
    previous = {"open": 100, "high": 101, "low": 99, "close": 100}
    current = {"open": 101, "high": 104, "low": 100, "close": 103}
    assert ti.failed_rally_state(previous, current)["state"] == "NONE"


def test_analysis_and_durable_restore_are_duplicate_safe():
    bars = market_bars()
    shorts = short_rows(200)
    result = ti.analyze(bars, symbol="1321", market="JP",
                        short_history=shorts, comparison_rows=bars)
    state = ti.merge_analysis(ti.empty_state(), result, bars[-1], shorts,
                              "2026-07-23T10:00:00+09:00")
    again = ti.merge_analysis(state, result, bars[-1], shorts,
                              "2026-07-23T10:01:00+09:00")
    assert len(again["snapshots"]) == 1
    assert len(again["shortSellingHistory"]) == 200
    restored = ti.merge_state(ti.empty_state(), again)
    assert ti.read_back_verified(again, restored)
    assert ti.state_hash(again) == ti.state_hash(restored)
    assert "holdings" not in str(restored).lower()


def test_missing_short_data_is_honest_not_zero():
    summary = ti.short_selling_summary([])
    assert summary["status"] == "missing"
    assert summary["latest"] is None
    assert summary["missingReason"] == "daily_short_ratio_unavailable"


def test_episode_cooldown_is_scoped_to_signal_family():
    rows = [
        {"index": 10, "distance": .2, "family": "trend_up"},
        {"index": 11, "distance": .1, "family": "trend_down"},
        {"index": 12, "distance": .3, "family": "trend_up"},
    ]
    grouped = ti._episodes(rows, 5)
    assert len(grouped) == 2
    assert {row["family"] for row in grouped} == {"trend_up", "trend_down"}


def test_restore_keeps_highest_short_revision_without_duplicates():
    base = ti.empty_state()
    old = ti.normalize_short_history(short_rows(1))[0]
    old["revision"] = 0
    newer = {**old, "revision": 2, "observedAt": "2026-07-23T00:00:00Z"}
    base["shortSellingHistory"] = [old]
    remote = ti.empty_state()
    remote["shortSellingHistory"] = [newer]
    merged = ti.merge_state(base, remote)
    assert len(merged["shortSellingHistory"]) == 1
    assert merged["shortSellingHistory"][0]["revision"] == 2
