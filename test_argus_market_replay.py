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

    def test_dataset_hash_is_stable_and_changes_with_price_data(self):
        self.assertEqual(replay.dataset_hash(self.rows),
                         replay.dataset_hash(copy.deepcopy(self.rows)))
        changed = copy.deepcopy(self.rows)
        changed[-1]["close"] += 0.01
        self.assertNotEqual(replay.dataset_hash(self.rows),
                            replay.dataset_hash(changed))
        changed_low = copy.deepcopy(self.rows)
        changed_low[-1]["low"] -= 0.01
        self.assertNotEqual(replay.dataset_hash(self.rows),
                            replay.dataset_hash(changed_low))

    def test_no_future_leakage_and_all_outcomes(self):
        self.assertTrue(self.context["computation"]["noFutureLeakage"])
        self.assertTrue(self.context["eventStudy"]["noFutureLeakage"])
        self.assertTrue(self.context["calibrationCurve"]["walkForward"])
        episode = self.context["similarEpisodes"]["episodes"][0]
        self.assertEqual({"1", "5", "20", "mfe", "mae", "reactionClass",
                          "reactionDelayDays"}, set(episode["outcomes"]))
        self.assertLess(episode["date"], self.context["historyCoverage"]["end"])
        migration = self.context["derivedMetricMigration"]
        self.assertEqual(replay.OLD_METHOD_VERSION, migration["oldMethodVersion"])
        self.assertEqual(replay.METHOD_VERSION, migration["newMethodVersion"])
        self.assertEqual(self.context["datasetHash"],
                         migration["sourceDatasetHash"])
        self.assertFalse(migration["rawObservationsModified"])

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
        mae = self.context["outcomeDistributions"]["mae"]
        self.assertLessEqual(mae["q90"], 0)
        self.assertLessEqual(mae["median"], 0)
        self.assertTrue(all(row["to"] <= 0 for row in mae["histogram"]))

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

    def test_standard_mae_all_up_is_zero_and_mfe_positive(self):
        rows = [{"date": "2026-01-01", "open": 100, "high": 100,
                 "low": 100, "close": 100, "volume": 1}]
        for day in range(1, 21):
            rows.append({"date": f"2026-01-{day + 1:02d}", "open": 100 + day,
                         "high": 101 + day, "low": 100.5 + day,
                         "close": 101 + day, "volume": 1})
        outcome = replay._outcome(rows, 0, 20)
        self.assertEqual(0.0, outcome["mae"])
        self.assertGreater(outcome["mfe"], 0)

    def test_standard_mae_records_worst_drop_then_recovery(self):
        rows = [{"date": "2026-01-01", "open": 100, "high": 100,
                 "low": 100, "close": 100, "volume": 1}]
        for day in range(1, 21):
            low = 97 if day == 3 else 100 + day * .1
            rows.append({"date": f"2026-01-{day + 1:02d}", "open": 100,
                         "high": 101 + day * .1, "low": low,
                         "close": 100 + day * .2, "volume": 1})
        self.assertEqual(-3.0, replay._outcome(rows, 0, 20)["mae"])

    def test_standard_mae_first_day_drop_is_minimum(self):
        rows = [{"date": "2026-01-01", "open": 100, "high": 100,
                 "low": 100, "close": 100, "volume": 1}]
        for day in range(1, 21):
            rows.append({"date": f"2026-01-{day + 1:02d}", "open": 100,
                         "high": 101, "low": 94 if day == 1 else 98,
                         "close": 100, "volume": 1})
        self.assertEqual(-6.0, replay._outcome(rows, 0, 20)["mae"])

    def test_missing_low_and_zero_start_are_not_scored(self):
        rows = [{"date": "2026-01-01", "open": 100, "high": 100,
                 "low": 100, "close": 100, "volume": 1}]
        for day in range(1, 21):
            rows.append({"date": f"2026-01-{day + 1:02d}", "open": 100,
                         "high": 101, "low": 99, "close": 100, "volume": 1})
        rows[3]["low"] = None
        self.assertIsNone(replay._outcome(rows, 0, 5)["mae"])
        zero = copy.deepcopy(rows)
        zero[0]["close"] = 0
        outcome = replay._outcome(zero, 0, 5)
        self.assertIsNone(outcome["mae"])
        self.assertIsNone(outcome["mfe"])
        self.assertIsNone(outcome["1"])

    def test_excursions_are_independent_by_horizon(self):
        rows = [{"date": "2026-01-01", "open": 100, "high": 100,
                 "low": 100, "close": 100, "volume": 1}]
        for day in range(1, 21):
            low = 99 if day == 1 else 97 if day == 4 else 90 if day == 10 else 100
            high = 102 if day <= 5 else 108 if day == 10 else 101
            rows.append({"date": f"2026-01-{day + 1:02d}", "open": 100,
                         "high": high, "low": low, "close": 100, "volume": 1})
        self.assertEqual(-1.0, replay._outcome(rows, 0, 1)["mae"])
        self.assertEqual(-3.0, replay._outcome(rows, 0, 5)["mae"])
        self.assertEqual(-10.0, replay._outcome(rows, 0, 20)["mae"])
        self.assertEqual(2.0, replay._outcome(rows, 0, 1)["mfe"])
        self.assertEqual(2.0, replay._outcome(rows, 0, 5)["mfe"])
        self.assertEqual(8.0, replay._outcome(rows, 0, 20)["mfe"])

    def test_legacy_context_is_preserved_but_current_prefers_new_method(self):
        old = copy.deepcopy(self.context)
        old["methodVersion"] = replay.OLD_METHOD_VERSION
        old["contextId"] = "legacy-v1-context"
        old["asOf"] = "2025-02-21T00:00:00Z"
        old.pop("derivedMetricMigration", None)
        state = replay.merge_context(replay.empty_state(), old,
                                     "2025-02-20T00:00:00Z")
        state = replay.merge_context(state, self.context,
                                     "2025-02-20T00:01:00Z")
        self.assertEqual(2, len(state["contexts"]))
        latest = replay.latest_contexts(state, self.context["instrumentId"])
        self.assertEqual(replay.METHOD_VERSION,
                         latest["5"]["methodVersion"])
        self.assertIn("legacy-v1-context",
                      {row["contextId"] for row in state["contextHistory"]})


if __name__ == "__main__":
    unittest.main()
