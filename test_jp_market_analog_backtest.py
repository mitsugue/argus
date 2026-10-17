"""Walk-forward validation of the analog forecast (2026-09-30)."""
from datetime import date, timedelta
import math
import unittest

import jp_market_analog_backtest as backtest
from jp_market_price_paths import cached_index_comparison


def sessions(n, start="2016-10-03"):
    out, day = [], date.fromisoformat(start)
    while len(out) < n:
        if day.weekday() < 5:
            out.append(day.isoformat())
        day += timedelta(days=1)
    return out


def bars(days, closes):
    return [{"instrumentId": "NIKKEI_225_INDEX", "date": d, "open": c, "high": c, "low": c, "close": c,
             "volume": 1, "availableFrom": d + "T07:00:00Z"} for d, c in zip(days, closes)]


class WalkForwardTest(unittest.TestCase):
    def test_wilson_bound(self):
        self.assertIsNone(backtest.wilson_lower_bound(0, 0))
        self.assertAlmostEqual(backtest.wilson_lower_bound(60, 100), 0.502, places=3)
        self.assertLess(backtest.wilson_lower_bound(6, 10), 0.6)

    def test_pure_noise_is_not_validated_and_no_future_is_used(self):
        days = sessions(900)
        closes, value, seed = [], 30000.0, 7
        for _ in days:
            seed = (seed * 1103515245 + 12345) % 2**31
            value *= 1 + ((seed / 2**31) - 0.5) * 0.02
            closes.append(round(value, 2))
        rows = bars(days, closes)
        cache = {}
        doc = cached_index_comparison(rows, cutoff=days[-1] + "T08:00:00Z", session_dates=days,
                                      horizon_sessions=5, backtest_cache=cache)
        validation = doc["comparison"]["forecast"]["validation"]
        self.assertEqual(validation["method"], backtest.METHOD)
        self.assertGreater(validation["evaluations"], 20)
        self.assertEqual(doc["comparison"]["forecast"]["validationStatus"], "UNVALIDATED")
        self.assertIn("too_few_independent_evaluations", validation["reasons"])
        self.assertIsNone(validation["predictiveProbabilities"])
        # Reused for the other horizons without recomputation.
        key = cache["key"]
        doc20 = cached_index_comparison(rows, cutoff=days[-1] + "T08:00:00Z", session_dates=days,
                                        horizon_sessions=20, backtest_cache=cache)
        self.assertEqual(cache["key"], key)
        self.assertLessEqual(doc20["comparison"]["forecast"]["validation"]["evaluations"],
                             validation["evaluations"])
        self.assertNotIn("records", doc["comparison"]["forecast"]["validation"])  # the document carries metrics only

    def test_no_information_after_an_evaluated_date_is_used(self):
        # Evaluating on a history that ends early and on the full history gives
        # identical records for every date whose horizon closed before the
        # early end: later closes cannot reach an earlier evaluation.
        days = sessions(1600)
        closes = [30000 * (1 + 0.05 * math.sin(2 * math.pi * i / 37) + 0.0001 * i) for i in range(len(days))]
        full, early = {}, {}
        cached_index_comparison(bars(days, closes), cutoff=days[-1] + "T08:00:00Z", session_dates=days,
                                backtest_cache=full)
        cut = 1200
        altered = closes[:cut] + [c * 1.3 for c in closes[cut:]]
        cached_index_comparison(bars(days, altered), cutoff=days[-1] + "T08:00:00Z", session_dates=days,
                                backtest_cache=early)
        boundary = days[cut - 21]
        a = {r["anchorDate"]: r for r in full["result"]["records"] if r["anchorDate"] < boundary}
        b = {r["anchorDate"]: r for r in early["result"]["records"] if r["anchorDate"] < boundary}
        self.assertTrue(a)
        self.assertEqual(a, b)

    def test_a_learnable_pattern_can_validate(self):
        # A deterministic cycle: the shape of the last twenty sessions fixes
        # the next move, so past analogs predict it and the rule validates.
        days = sessions(2400)
        closes = [30000 * (1 + 0.05 * math.sin(2 * math.pi * i / 40)) for i in range(len(days))]
        rows = bars(days, closes)
        cache = {}
        doc = cached_index_comparison(rows, cutoff=days[-1] + "T08:00:00Z", session_dates=days,
                                      horizon_sessions=5, backtest_cache=cache)
        v = doc["comparison"]["forecast"]["validation"]
        self.assertGreaterEqual(v["directionalEvaluations"], backtest.MINIMUM_DIRECTIONAL_EVALUATIONS)
        self.assertGreater(v["hitRateWilsonLower95"], v["naiveMajorityRate"])
        self.assertNotIn("direction_not_better_than_naive_majority", v["reasons"])


if __name__ == "__main__":
    unittest.main()


class WeightSearchTest(unittest.TestCase):
    def test_noise_keeps_equal_weights_and_halves_do_not_overlap(self):
        days = sessions(900)
        closes, value, seed = [], 30000.0, 11
        for _ in days:
            seed = (seed * 1103515245 + 12345) % 2**31
            value *= 1 + ((seed / 2**31) - 0.5) * 0.02
            closes.append(round(value, 2))
        cache = {}
        doc = cached_index_comparison(bars(days, closes), cutoff=days[-1] + "T08:00:00Z", session_dates=days,
                                      backtest_cache=cache)
        search = cache["search"]
        self.assertEqual(search["status"], "AVAILABLE")
        self.assertEqual(search["gridSize"], len(backtest.WEIGHT_GRID))
        self.assertLess(search["trainEnd"], search["confirmStart"])
        self.assertLess(search["confirmEnd"], search["testStart"])
        self.assertFalse(search["adopted"])
        ws = doc["comparison"]["forecast"]["weightSearch"]
        self.assertFalse(ws["adopted"])
        self.assertIsNone(ws["predictiveProbabilities"])
        self.assertIsNone(doc["comparison"]["selectionPolicy"]["componentWeights"])

    def test_equal_weights_reproduce_the_plain_mean(self):
        from jp_market_analogs import AnalogPolicy, weighted_distance
        parts = {"priceShape": 0.4, "marketState": 0.8, "conditionOrder": None, "materialReaction": None}
        plain = weighted_distance(parts, AnalogPolicy())
        equal = weighted_distance(parts, AnalogPolicy(component_weights=(("priceShape", 1.0), ("marketState", 1.0))))
        self.assertAlmostEqual(plain, 0.6)
        self.assertAlmostEqual(equal, 0.6)
        heavy = weighted_distance(parts, AnalogPolicy(component_weights=(("priceShape", 1.0), ("marketState", 2.0))))
        self.assertAlmostEqual(heavy, (0.4 + 1.6) / 3)
        with self.assertRaises(ValueError):
            AnalogPolicy(component_weights=(("priceShape", 0.0),))
        with self.assertRaises(ValueError):
            AnalogPolicy(component_weights=(("unknown", 1.0),))
