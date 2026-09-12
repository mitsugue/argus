import copy
import math
import unittest
from datetime import date, timedelta

from jp_market_analogs import (AnalogPolicy, FEATURE_DEFINITIONS, INSTRUMENT,
                               build_episode, reference_path, select_episodes)

POLICY = AnalogPolicy(lookback_sessions=5, minimum_separation_sessions=6)
DAYS = [(date(2026, 1, 1) + timedelta(days=i)).isoformat() for i in range(120)]


def bars(start, end, scale=1):
    return [{"instrumentId": INSTRUMENT, "field": "OHLCV_BAR", "date": DAYS[i],
             "availableFrom": DAYS[i] + "T07:00:00Z", "close": scale * (100 + i % 6),
             "sourceRef": "test:daily-index", "revision": 0} for i in range(start, end)]


def fact(field, value, index, unit, **extra):
    return {"instrumentId": INSTRUMENT, "field": field, "date": DAYS[index],
            "availableFrom": DAYS[index] + "T08:00:00Z", "value": value,
            "unit": unit, "revision": 0, **extra}


def episode(index, *, full=False, changes=None, price_rows=None):
    states = [fact(key, 1, index, definition[0]) for key, definition in FEATURE_DEFINITIONS.items()] if full else []
    conditions = [fact("vix_cross", 1, index - 3, "DIRECTION"),
                  fact("price_recovery", 1, index - 1, "DIRECTION")] if full else []
    reactions = [fact("policy_reaction", 1, index, "PERCENT", eventId="test-event-" + str(index),
                      eventType="MONETARY_POLICY", reactionWindowSessions=1)] if full else []
    args = {"cutoff": DAYS[index] + "T23:00:00Z", "bars": price_rows if price_rows is not None else bars(0, index + 1),
            "state_rows": states, "condition_rows": conditions, "reaction_rows": reactions, "policy": POLICY}
    args.update(changes or {})
    return build_episode(**args)


class AnalogSelectionTest(unittest.TestCase):
    def test_past_outcome_changes_do_not_change_selection(self):
        before = bars(0, 18)
        after = copy.deepcopy(before)
        for row in after[12:]:
            row["close"] *= 7
        first = episode(11, full=True, price_rows=before)
        changed = episode(11, full=True, price_rows=after)
        self.assertEqual(first, changed)
        current = episode(83, full=True)
        result = select_episodes(current, [first], session_dates=DAYS, policy=POLICY)
        self.assertEqual(result, select_episodes(current, [changed], session_dates=DAYS, policy=POLICY))
        original_path = reference_path(first, later_bars=before, display_cutoff=DAYS[18] + "T00:00:00Z", session_dates=DAYS, policy=POLICY)
        changed_path = reference_path(changed, later_bars=after, display_cutoff=DAYS[18] + "T00:00:00Z", session_dates=DAYS, policy=POLICY)
        self.assertNotEqual(original_path["subsequentReference"], changed_path["subsequentReference"])
        self.assertFalse(result["outcomesUsedForSelection"])

    def test_partial_price_comparison_is_not_full_market_analog(self):
        result = select_episodes(episode(83), [episode(11), episode(23)], session_dates=DAYS, policy=POLICY)
        self.assertEqual(result["status"], "PARTIAL_COMPARISONS_ONLY")
        self.assertEqual(len(result["selected"]), 2)
        self.assertEqual(result["selected"][0]["similarityReasons"], ["priceShape"])
        self.assertIn("materialReaction", result["selected"][0]["missingGroups"])
        self.assertIsNone(result["predictiveProbability"])
        self.assertFalse(result["actionAuthority"])

    def test_full_comparison_reports_independent_components_and_differences(self):
        result = select_episodes(episode(83, full=True), [episode(11, full=True)], session_dates=DAYS, policy=POLICY)
        self.assertEqual(result["status"], "MARKET_ANALOGS_AVAILABLE")
        row = result["selected"][0]
        self.assertEqual(set(row["componentDistances"]), {"priceShape", "marketState", "conditionOrder", "materialReaction"})
        self.assertEqual(row["missingFeatures"], [])
        self.assertFalse(row["historicalVintageVerified"])
        self.assertEqual(result["validationStatus"], "UNVALIDATED")

    def test_sequence_order_changes_distance_but_same_day_is_simultaneous(self):
        current, past = episode(83, full=True), episode(11, full=True)
        reversed_order = episode(11, full=True, changes={"condition_rows": [
            fact("price_recovery", 1, 8, "DIRECTION"), fact("vix_cross", 1, 10, "DIRECTION")]})
        left = select_episodes(current, [past], session_dates=DAYS, policy=POLICY)
        right = select_episodes(current, [reversed_order], session_dates=DAYS, policy=POLICY)
        self.assertLess(left["selected"][0]["componentDistances"]["conditionOrder"],
                        right["selected"][0]["componentDistances"]["conditionOrder"])
        simultaneous = [fact("price_recovery", 1, 10, "DIRECTION"), fact("vix_cross", 1, 10, "DIRECTION")]
        a = episode(11, full=True, changes={"condition_rows": simultaneous})
        b = episode(11, full=True, changes={"condition_rows": simultaneous[::-1]})
        self.assertEqual(a, b)

    def test_future_revision_and_wrong_instrument_do_not_enter_features(self):
        base = episode(11, full=True)
        future = fact("vix.level", 500, 11, "INDEX_POINTS", knownAt=DAYS[20] + "T00:00:00Z", revision=1)
        states = [fact(key, 1, 11, definition[0]) for key, definition in FEATURE_DEFINITIONS.items()]
        wrong = fact("vix.level", 999, 11, "INDEX_POINTS", instrumentId="1321")
        changed = episode(11, full=True, changes={"state_rows": states + [future, wrong]})
        self.assertEqual(base, changed)

    def test_nearby_episodes_are_not_independent_samples(self):
        result = select_episodes(episode(83), [episode(11), episode(12), episode(23)], session_dates=DAYS, policy=POLICY)
        anchors = [row["anchorDate"] for row in result["selected"]]
        self.assertIn(DAYS[11], anchors)
        self.assertNotIn(DAYS[12], anchors)
        self.assertIn(DAYS[23], anchors)

    def test_no_strong_analog_and_stale_snapshot_are_explicit(self):
        extreme = bars(0, 12)
        extreme[-6]["close"] = 10000
        result = select_episodes(episode(83), [episode(11, price_rows=extreme)], session_dates=DAYS, policy=POLICY)
        self.assertEqual(result["status"], "NO_STRONG_ANALOG")
        late = episode(11, changes={"cutoff": DAYS[30] + "T23:00:00Z"})
        self.assertEqual(select_episodes(episode(83), [late], session_dates=DAYS, policy=POLICY)["selected"], [])

    def test_tampered_snapshot_and_missing_exchange_session_rejected(self):
        tampered = episode(11)
        tampered["window"][-1]["close"] = 500
        with self.assertRaisesRegex(ValueError, "episode_content_changed"):
            select_episodes(episode(83), [tampered], session_dates=DAYS, policy=POLICY)
        incomplete = episode(11, price_rows=[r for r in bars(0, 12) if r["date"] != DAYS[8]])
        self.assertEqual(select_episodes(episode(83), [incomplete], session_dates=DAYS, policy=POLICY)["selected"], [])

    def test_unit_mismatch_is_missing_not_silently_scaled(self):
        current = episode(83, full=True)
        states = [fact(key, 1, 11, definition[0]) for key, definition in FEATURE_DEFINITIONS.items()]
        states[0]["unit"] = "JPY"
        past = episode(11, full=True, changes={"state_rows": states})
        result = select_episodes(current, [past], session_dates=DAYS, policy=POLICY)
        self.assertEqual(result["status"], "PARTIAL_COMPARISONS_ONLY")
        self.assertIn("credit.ratio", result["selected"][0]["missingFeatures"])

    def test_existing_ohlcv_shape_without_explicit_field_is_supported(self):
        values = bars(0, 12)
        for row in values:
            row.pop("field")
            row.update(open=row["close"], high=row["close"], low=row["close"], volume=0)
        self.assertEqual(episode(11, price_rows=values)["status"], "AVAILABLE")

    def test_stale_daily_feature_is_excluded_and_missing_price_is_not_bridged(self):
        current = episode(83, full=True)
        states = [fact(key, 1, 11, definition[0]) for key, definition in FEATURE_DEFINITIONS.items()]
        next(row for row in states if row["field"] == "vix.level")["date"] = DAYS[0]
        past = episode(11, full=True, changes={"state_rows": states})
        result = select_episodes(current, [past], session_dates=DAYS, policy=POLICY)
        self.assertIn("vix.level", result["selected"][0]["missingFeatures"])
        incomplete = bars(0, 18)
        incomplete = [row for row in incomplete if row["date"] != DAYS[14]]
        path = reference_path(episode(11), later_bars=incomplete, display_cutoff=DAYS[18] + "T00:00:00Z",
                              session_dates=DAYS, policy=POLICY)
        self.assertEqual(path["status"], "PARTIAL")
        self.assertEqual(path["subsequentReference"][-1]["date"], DAYS[13])

    def test_actual_past_and_subsequent_paths_share_anchor_without_becoming_forecast(self):
        past = episode(11)
        path = reference_path(past, later_bars=bars(0, 18), display_cutoff=DAYS[18] + "T00:00:00Z", session_dates=DAYS, policy=POLICY)
        self.assertEqual(path["status"], "AVAILABLE")
        self.assertEqual(path["comparison"][-1]["value"], 100)
        self.assertEqual(path["subsequentReference"][0]["value"], 100)
        self.assertFalse(path["subsequentReferenceIsPrediction"])
        partial = reference_path(past, later_bars=bars(0, 14), display_cutoff=DAYS[18] + "T00:00:00Z", session_dates=DAYS, policy=POLICY)
        self.assertEqual(partial["status"], "PARTIAL")


if __name__ == "__main__":
    unittest.main()
