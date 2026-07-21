import copy
import unittest
from datetime import date, timedelta
from unittest import mock

import argus_market_ledger as ml


NOW = "2026-07-20T12:00:00Z"


def add(state, series, day, value, unit=None, available=None, source="fixture"):
    candidate = {"seriesId": series, "periodEnd": day,
                 "availableFrom": available or f"{day}T09:00:00Z",
                 "publishedAt": f"{day}T08:00:00Z", "value": value,
                 "unit": unit or ml.SERIES[series][0], "source": source,
                 "sourceKind": ml.SERIES[series][3]}
    return ml.append_observation(state, candidate, now_iso=NOW)[0]


class MarketLedgerTests(unittest.TestCase):
    def test_append_only_revision_duplicate_and_unit_validation(self):
        st = add(ml.empty_state(), "credit.short_balance", "2026-07-10", 700_000_000_000)
        with self.assertRaisesRegex(ValueError, "duplicate_observation"):
            add(st, "credit.short_balance", "2026-07-10", 700_000_000_000)
        revised = add(st, "credit.short_balance", "2026-07-10", 710_000_000_000)
        self.assertEqual(len(revised["observations"]), 2)
        self.assertEqual(revised["observations"][0]["revision"], 0)
        self.assertEqual(revised["observations"][1]["revision"], 1)
        with self.assertRaisesRegex(ValueError, "unit_mismatch"):
            add(revised, "credit.short_balance", "2026-07-11", 1, "million_JPY")

    def test_available_from_and_missing_are_not_zero(self):
        st = add(ml.empty_state(), "valuation.nikkei", "2026-07-20", None,
                 available="2026-07-21T00:00:00Z")
        self.assertEqual(ml.effective_observations(st, NOW), [])
        self.assertIsNone(st["observations"][0]["value"])
        self.assertEqual(st["observations"][0]["status"], "missing")

    def test_required_formulas(self):
        self.assertEqual(ml.advance_decline_ratio([6_732_228], [795_524]), 846.26)
        st = ml.empty_state()
        st = add(st, "valuation.nikkei", "2026-07-18", 68_751.51)
        st = add(st, "valuation.per", "2026-07-18", 18.34)
        st = add(st, "valuation.pbr", "2026-07-18", 1.94)
        values = {x["metricId"]: x["value"] for x in ml.derive_metrics(st, NOW)}
        self.assertAlmostEqual(values["valuation.eps"], 3748.72, places=2)
        self.assertAlmostEqual(values["valuation.bps"], 35438.92, places=2)
        self.assertEqual(values["valuation.per18_level"], 67477)
        self.assertEqual(values["valuation.per21_level"], 78723)

    def test_credit_ratio_and_zero_denominator(self):
        st = ml.empty_state()
        st = add(st, "credit.short_balance", "2026-07-11", 795_524)
        st = add(st, "credit.long_balance", "2026-07-11", 6_732_228)
        vals = {x["metricId"]: x["value"] for x in ml.derive_metrics(st, NOW)}
        self.assertEqual(vals["credit.ratio"], 8.46)
        zero = ml.empty_state()
        zero = add(zero, "credit.short_balance", "2026-07-11", 0)
        zero = add(zero, "credit.long_balance", "2026-07-11", 100)
        vals = {x["metricId"]: x["value"] for x in ml.derive_metrics(zero, NOW)}
        self.assertIsNone(vals["credit.ratio"])

    def test_credit_cross_up_down_and_input_order_independence(self):
        st = ml.empty_state()
        for day, value in (("2026-07-01", 790_000_000_000),
                           ("2026-07-08", 810_000_000_000),
                           ("2026-07-15", 780_000_000_000)):
            st = add(st, "credit.short_balance", day, value)
        points = ml.detect_turning_points(st, NOW, NOW)
        crosses = [x for x in points if x["ruleId"] == "CREDIT_THRESHOLD_CROSS"]
        self.assertEqual([x["direction"] for x in crosses], ["up", "down"])
        shuffled = copy.deepcopy(st)
        shuffled["observations"].reverse()
        self.assertEqual([x["id"] for x in points],
                         [x["id"] for x in ml.detect_turning_points(shuffled, NOW, NOW)])

    def test_positioning_shift(self):
        st = ml.empty_state()
        base = date(2026, 6, 1)
        for i in range(5):
            day = str(base + timedelta(days=i * 7))
            st = add(st, "credit.short_balance", day, 900 - i * 20)
            st = add(st, "credit.long_balance", day, 3000 + i * 100)
        points = ml.detect_turning_points(st, NOW, NOW)
        self.assertTrue(any(x["ruleId"] == "POSITIONING_SHIFT" for x in points))

    def test_breadth_correct_rolling_formula_and_cross(self):
        st = ml.empty_state(); base = date(2026, 6, 1)
        for i in range(32):
            day = str(base + timedelta(days=i))
            # First half broad, then sharply narrow: short ratio crosses below 25d.
            adv = 1800 if i < 25 else 300
            dec = 300 if i < 25 else 1800
            st = add(st, "breadth.advancers", day, adv)
            st = add(st, "breadth.decliners", day, dec)
        history = ml.derived_history(st, NOW)
        self.assertGreaterEqual(len(history["breadth.ratio6"]), 27)
        points = ml.detect_turning_points(st, NOW, NOW)
        self.assertTrue(any(x["ruleId"] == "BREADTH_TURN" and
                            x["direction"] == "short_below_medium" for x in points))

    def test_valuation_rollover(self):
        st = ml.empty_state(); base = date(2026, 6, 1)
        eps_values = list(range(100, 121)) + [110]
        for i, eps in enumerate(eps_values):
            day = str(base + timedelta(days=i))
            st = add(st, "valuation.per", day, 20)
            st = add(st, "valuation.nikkei", day, eps * 20)
        points = ml.detect_turning_points(st, NOW, NOW)
        self.assertTrue(any(x["ruleId"] == "VALUATION_CEILING_ROLLOVER"
                            for x in points))

    def test_rebuild_idempotent_restore_and_readback(self):
        st = add(ml.empty_state(), "credit.short_balance", "2026-07-01", 790_000_000_000)
        st = add(st, "credit.short_balance", "2026-07-08", 810_000_000_000)
        once = ml.rebuild(st, NOW)
        twice = ml.rebuild(once, NOW)
        self.assertEqual(ml.state_hash(once), ml.state_hash(twice))
        restored = ml.normalize_state(copy.deepcopy(twice))
        self.assertTrue(ml.read_back_verified(twice, restored))

    def test_csv_dry_run_commit_and_append_only_rollback(self):
        csv_text = ("seriesId,periodEnd,availableFrom,value,unit,source\n"
                    "flow.foreign,2026-07-11,2026-07-18T07:00:00Z,1000000,JPY,JPX\n")
        rows = ml.parse_csv(csv_text)
        dry = ml.import_rows(ml.empty_state(), rows, now_iso=NOW, dry_run=True)
        self.assertTrue(dry["ok"]); self.assertEqual(dry["state"]["observations"], [])
        committed = ml.import_rows(ml.empty_state(), rows, now_iso=NOW, dry_run=False)
        st = committed["state"]; count = len(st["observations"])
        rolled = ml.rollback_import(st, committed["importId"], NOW)
        self.assertEqual(len(rolled["observations"]), count)
        self.assertEqual(ml.effective_observations(rolled, NOW), [])

    def test_import_can_defer_rebuild_without_losing_append_receipt(self):
        rows = [{"seriesId": "breadth.all.advancers",
                 "periodEnd": "2026-07-17",
                 "publishedAt": "2026-07-17T17:00:00+09:00",
                 "availableFrom": "2026-07-17T17:00:00+09:00",
                 "value": 1000, "unit": "count", "source": "J-Quants",
                 "sourceKind": "official", "status": "live"}]
        deferred = ml.import_rows(
            ml.empty_state(), rows, now_iso=NOW, dry_run=False,
            rebuild_after_commit=False)
        self.assertTrue(deferred["ok"])
        self.assertEqual(len(deferred["state"]["observations"]), 1)
        self.assertEqual(len(deferred["state"]["imports"]), 1)
        self.assertEqual(deferred["state"]["derivedMetrics"], [])
        self.assertTrue(deferred["state"]["derivedStateDirty"])
        restored = ml.normalize_state(copy.deepcopy(deferred["state"]))
        self.assertTrue(ml.rebuild_required(restored))
        rebuilt = ml.rebuild(restored, NOW)
        self.assertEqual(len(rebuilt["observations"]), 1)
        self.assertEqual(len(rebuilt["imports"]), 1)
        self.assertFalse(rebuilt["derivedStateDirty"])
        self.assertEqual(rebuilt["lastRebuiltObservationCount"], 1)

    def test_clean_public_view_skips_full_derived_rebuild(self):
        state = add(ml.empty_state(), "breadth.all.advancers",
                    "2026-07-17", 1000)
        rebuilt = ml.rebuild(state, NOW)
        restored = ml.normalize_state(copy.deepcopy(rebuilt))
        with mock.patch.object(ml, "rebuild", wraps=ml.rebuild) as rebuild_call:
            view = ml.public_view(restored, NOW)
        rebuild_call.assert_not_called()
        self.assertEqual(view["stateHash"], ml.state_hash(restored))

    def test_new_observation_invalidates_rebuild_receipt(self):
        clean = ml.rebuild(ml.empty_state(), NOW)
        changed = add(clean, "breadth.all.advancers", "2026-07-17", 1000)
        self.assertTrue(ml.rebuild_required(changed))
        with mock.patch.object(ml, "rebuild", wraps=ml.rebuild) as rebuild_call:
            ml.public_view(changed, NOW)
        rebuild_call.assert_called_once()

    def test_public_view_does_not_expose_licensed_raw_value(self):
        st = add(ml.empty_state(), "credit.valuation_loss_pct", "2026-07-11", -10.5)
        row = next(x for x in ml.public_view(st, NOW)["table"]
                   if x["seriesId"] == "credit.valuation_loss_pct")
        self.assertIsNone(row["latestValue"])
        self.assertEqual(row["history"], [])
        self.assertEqual(row["status"], "licensed_redacted")

    def test_public_view_credit_and_flow_comparison_details(self):
        st = ml.empty_state()
        for i, value in enumerate((790_000_000_000, 805_000_000_000,
                                   810_000_000_000, 815_000_000_000)):
            day = str(date(2026, 6, 1) + timedelta(days=i * 7))
            st = add(st, "credit.short_balance", day, value)
            st = add(st, "flow.foreign", day, 10_000_000_000 + i)
        rows = {x["seriesId"]: x for x in ml.public_view(st, NOW)["table"]}
        self.assertEqual(rows["credit.short_balance"]["thresholdDistance"], 15_000_000_000)
        self.assertEqual(rows["credit.short_balance"]["thresholdStreak"], 3)
        self.assertEqual(rows["flow.foreign"]["fourPeriodTotal"], 40_000_000_006)
        self.assertEqual(rows["flow.foreign"]["consecutiveDirectionCount"], 4)

    def test_missing_valuation_metrics_remain_missing_in_public_summary(self):
        st = add(ml.empty_state(), "valuation.nikkei", "2026-07-18", None)
        st = add(st, "valuation.per", "2026-07-18", 18.0)
        view = ml.public_view(st, NOW)
        self.assertIsNone(view["valuationSummary"]["epsPreviousChange"])
        self.assertIsNone(view["valuationSummary"]["per21Level"])


if __name__ == "__main__":
    unittest.main()
