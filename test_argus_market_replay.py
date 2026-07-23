import copy
import math
import unittest
from datetime import date, timedelta

import argus_market_replay as replay


def bars(count=420):
    rows = []
    start = date(2024, 1, 1)
    for index in range(count):
        day = start + timedelta(days=index)
        close = 100 + index * .04 + math.sin(index / 7) * 4 + math.sin(index / 29) * 3
        rows.append({
            "date": day.isoformat(), "open": close - math.sin(index) * .5,
            "high": close + 1.2, "low": close - 1.1, "close": close,
            "volume": 1_000_000 + (index % 17) * 30_000,
            "availableFrom": day.isoformat(),
        })
    return rows


def ledger():
    start = date(2024, 1, 1)
    return {"table": [{
        "seriesId": "credit.short_balance", "labelJa": "信用売り残", "unit": "億円",
        "history": [{
            "periodEnd": (start + timedelta(days=index * 7)).isoformat(),
            "availableFrom": (start + timedelta(days=index * 7 + 3)).isoformat(),
            "value": 7000 + math.sin(index / 3) * 1200,
        } for index in range(55)],
    }, {
        "seriesId": "breadth.ratio_25", "labelJa": "25日騰落レシオ", "unit": "ratio",
        "history": [{
            "periodEnd": (start + timedelta(days=index)).isoformat(),
            "availableFrom": (start + timedelta(days=index)).isoformat(),
            "value": 100 + math.sin(index / 6) * 30,
        } for index in range(380)],
    }]}


def chart():
    return {
        "indicators": {"bars": bars()},
        "zones": [
            {"id": "support", "lower": 100, "upper": 102, "center": 101, "status": "active"},
            {"id": "resistance", "lower": 120, "upper": 122, "center": 121, "status": "active"},
        ],
        "eventMarkers": [{"id": "FOMC", "labelJa": "FOMC", "date": "2025-01-01"}],
    }


class MarketReplayTests(unittest.TestCase):
    def setUp(self):
        self.rows = bars()
        self.context = replay.build_context(
            self.rows, symbol="1321", market="JP", horizon=5,
            chart_report=chart(), ledger=ledger(), now_iso="2025-02-20T00:00:00Z")

    def test_similar_episode_search_is_deterministic_and_grouped(self):
        second = replay.build_context(
            self.rows, symbol="1321", market="JP", horizon=5,
            chart_report=chart(), ledger=ledger(), now_iso="2025-02-20T00:00:00Z")
        self.assertEqual(self.context["contextId"], second["contextId"])
        index = self.context["similarEpisodes"]
        self.assertGreater(index["rawOccurrenceCount"], index["effectiveSampleCount"])
        ordered = sorted(index["episodes"], key=lambda row: row["index"])
        self.assertTrue(all(right["index"] - left["index"] > replay.COOLDOWN_TRADING_DAYS
                            for left, right in zip(ordered, ordered[1:])))

    def test_no_future_leakage_and_all_outcomes(self):
        self.assertTrue(self.context["computation"]["noFutureLeakage"])
        self.assertTrue(self.context["eventStudy"]["noFutureLeakage"])
        self.assertTrue(self.context["calibrationCurve"]["walkForward"])
        episode = self.context["similarEpisodes"]["episodes"][0]
        self.assertEqual({"1", "5", "20", "mfe", "mae", "reactionClass",
                          "reactionDelayDays"}, set(episode["outcomes"]))
        self.assertLess(episode["date"], self.context["historyCoverage"]["end"])

    def test_reaction_classification_boundaries(self):
        self.assertEqual(("immediate_up", 1), replay._classify_reaction([1, 1.1], .5))
        self.assertEqual(("delayed_up", 2), replay._classify_reaction([.1, .7], .5))
        self.assertEqual(("reverse_then_up", 2), replay._classify_reaction([-.7, .8], .5))
        self.assertEqual(("immediate_down", 1), replay._classify_reaction([-.8, -.9], .5))
        self.assertEqual(("reverse_then_down", 2), replay._classify_reaction([.8, -.7], .5))
        self.assertEqual(("no_reaction", None), replay._classify_reaction([.1, -.1], .5))

    def test_event_study_and_distributions(self):
        points = self.context["eventStudy"]["points"]
        self.assertEqual(list(range(-20, 21)), [point["day"] for point in points])
        for key in ("1", "5", "20", "mfe", "mae", "reactionDelayDays"):
            distribution = self.context["outcomeDistributions"][key]
            self.assertIn("median", distribution)
            self.assertEqual(10, len(distribution["histogram"]))

    def test_extremes_respect_publication_time(self):
        extremes = self.context["extremes"]
        self.assertTrue(extremes["publicationTimeIntegrity"])
        self.assertEqual([1, 5, 10, 90, 95, 99], extremes["thresholds"])
        for event in extremes["events"]:
            self.assertLessEqual(event["availableFrom"], self.context["asOf"][:10])
        self.assertTrue(all(point["availableFrom"] <= self.context["asOf"][:10]
                            for series in extremes["series"]
                            for point in series["history"]))

    def test_change_conditions_capped_at_three(self):
        conditions = self.context["changeConditions"]
        self.assertLessEqual(len(conditions), 3)
        self.assertEqual(["upside_close_break", "downside_close_break", "event_passed"],
                         [row["triggerType"] for row in conditions])

    def test_instrument_and_horizon_isolation(self):
        spy = replay.build_context(
            self.rows, symbol="SPY", market="US", horizon=20, chart_report=chart())
        self.assertNotEqual(self.context["contextId"], spy["contextId"])
        self.assertEqual("JP:1321:ETF", self.context["instrumentId"])
        self.assertEqual("US:SPY:ETF", spy["instrumentId"])

    def test_append_restore_and_remote_readback(self):
        state = replay.merge_context(
            replay.empty_state(), self.context, "2025-02-20T00:00:00Z")
        duplicate = replay.merge_context(
            state, copy.deepcopy(self.context), "2025-02-20T00:01:00Z")
        self.assertEqual(1, len(duplicate["contexts"]))
        restored = replay.merge_state(replay.empty_state(), duplicate)
        self.assertTrue(replay.read_back_verified(duplicate, restored))
        self.assertEqual(replay.state_hash(duplicate), replay.state_hash(restored))

    def test_calibration_curve_has_sample_metadata(self):
        curve = self.context["calibrationCurve"]
        self.assertTrue(curve["noFutureLeakage"])
        self.assertTrue(all(point["sample"] > 0 for point in curve["points"]))

    def test_no_automatic_ai(self):
        self.assertEqual(0, self.context["automaticAiCalls"])
        self.assertEqual("deterministic_background_cache",
                         self.context["computation"]["mode"])


if __name__ == "__main__":
    unittest.main()
