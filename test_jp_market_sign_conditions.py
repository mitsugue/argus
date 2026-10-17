"""Seven Sign state flips as condition events for the analog order (2026-09-30)."""
from datetime import date, timedelta
import unittest

import jp_market_features as features


def weekly(series, start, values, instrument="MARKET", lag=7):
    rows, day = [], date.fromisoformat(start)
    for value in values:
        available = (day + timedelta(days=lag)).isoformat() + "T06:00:00Z"
        rows.append({"instrumentId": instrument, "seriesId": series, "periodEnd": day.isoformat(),
                     "value": value, "unit": "JPY", "availableFrom": available})
        day += timedelta(days=7)
    return rows


def daily(instrument, start, closes):
    rows, day = [], date.fromisoformat(start)
    for close in closes:
        while day.weekday() >= 5:
            day += timedelta(days=1)
        rows.append({"instrumentId": instrument, "date": day.isoformat(), "open": close, "high": close, "low": close,
                     "close": close, "volume": 1, "availableFrom": day.isoformat() + "T07:00:00Z"})
        day += timedelta(days=1)
    return rows


class SignConditionTest(unittest.TestCase):
    cutoff = "2026-09-25T23:00:00Z"

    def conditions(self, **inputs):
        snap = features.build_market_features(cutoff=self.cutoff, price_series=inputs.pop("price_series", {}), **inputs)
        return [c for c in snap["conditions"] if c["seriesId"] != "vix_macd_cross"]

    def test_d01_short_balance_crossing_the_threshold_both_ways(self):
        shorts = weekly("credit.short_balance", "2026-06-05", [900e9, 850e9, 790e9, 780e9, 810e9, 820e9])
        rows = self.conditions(two_market_credit=shorts)
        self.assertEqual([(c["date"], c["value"]) for c in rows], [("2026-06-19", 1), ("2026-07-03", -1)])
        self.assertTrue(all(c["seriesId"] == features.SIGN_CONDITION_IDS["D01"] for c in rows))
        self.assertEqual(rows[0]["availableFrom"], "2026-06-26T06:00:00+00:00")
        self.assertEqual(rows[0]["unit"], "DIRECTION")

    def test_nothing_after_the_cutoff_and_nothing_older_than_the_lookback(self):
        shorts = weekly("credit.short_balance", "2025-10-03", [700e9, 900e9] + [900e9] * 48)
        self.assertEqual(self.conditions(two_market_credit=shorts), [])  # flip is 51 weeks back
        late = weekly("credit.short_balance", "2026-09-11", [900e9, 700e9])  # second row available 2026-09-25 06:00
        early_cutoff = features.build_market_features(cutoff="2026-09-24T23:00:00Z", price_series={},
                                                      two_market_credit=late)
        self.assertEqual([c for c in early_cutoff["conditions"] if c["seriesId"].startswith("d01")], [])

    def test_d02_d05_and_d04_from_their_own_series(self):
        # D02 reads the standardized-margin (制度信用) balances; the totals are ignored (2026-10-04).
        longs = weekly("margin.standardized.long_balance", "2026-07-03", [100, 100, 100, 100], instrument="1570")
        shorts = weekly("margin.standardized.short_balance", "2026-07-03", [120, 110, 90, 95], instrument="1570")
        longs += weekly("margin.long_balance", "2026-07-03", [500, 500, 500, 500], instrument="1570")
        longs += weekly("margin.short_balance", "2026-07-03", [100, 100, 100, 100], instrument="1570")
        flows = weekly("flow.foreign", "2026-07-03", [-1e9, 2e9, 3e9, -4e9])
        per = [{**row, "instrumentId": "NIKKEI_225_PER", "seriesId": "close"} for row in
               daily("NIKKEI_225_PER", "2026-09-01", [18.5, 18.9, 19.1, 19.3, 18.8])]
        rows = self.conditions(margin_1570=longs + shorts, foreign_flow=flows, price_series={"index_per": per})
        got = sorted((c["seriesId"], c["date"], c["value"]) for c in rows)
        self.assertEqual(got, sorted([
            (features.SIGN_CONDITION_IDS["D02"], "2026-07-17", 1),
            (features.SIGN_CONDITION_IDS["D05"], "2026-07-10", 1), (features.SIGN_CONDITION_IDS["D05"], "2026-07-24", -1),
            (features.SIGN_CONDITION_IDS["D04"], "2026-09-03", 1), (features.SIGN_CONDITION_IDS["D04"], "2026-09-07", -1)]))

    def test_d03_relative_strength_sign_change(self):
        n = daily("NIKKEI_225_INDEX", "2026-07-01", [100 + i for i in range(30)] + [129 - 3 * i for i in range(20)])
        s = daily("SP500_INDEX", "2026-07-01", [100 + 0.5 * i for i in range(50)])
        rows = self.conditions(price_series={"nikkei": n, "sp500": s})
        d03 = [c for c in rows if c["seriesId"] == features.SIGN_CONDITION_IDS["D03"]]
        self.assertTrue(d03 and d03[0]["value"] == -1)  # JP outperformance turns negative
        self.assertTrue(all(c["availableFrom"].endswith("07:00:00+00:00") for c in d03))

    def test_no_personal_name_in_condition_ids(self):
        for value in features.SIGN_CONDITION_IDS.values():
            self.assertRegex(value, r"^[a-z0-9_]+$")


if __name__ == "__main__":
    unittest.main()


class InputWindowTest(unittest.TestCase):
    def test_price_rows_older_than_the_window_do_not_change_any_value(self):
        n = daily("NIKKEI_225_INDEX", "2026-06-01", [100 + (i % 7) for i in range(80)])
        s = daily("SP500_INDEX", "2026-06-01", [50 + (i % 5) for i in range(80)])
        old = daily("NIKKEI_225_INDEX", "2024-01-01", [999.0] * 30)
        cutoff = "2026-09-18T23:00:00Z"
        base = features.build_market_features(cutoff=cutoff, price_series={"nikkei": n, "sp500": s})
        padded = features.build_market_features(cutoff=cutoff, price_series={"nikkei": old + n, "sp500": s})
        self.assertEqual(base["features"], padded["features"])
        self.assertEqual(base["conditions"], padded["conditions"])
        self.assertGreaterEqual(features.FEATURE_INPUT_WINDOW_DAYS, 26 * 7 + features.SIGN_CONDITION_LOOKBACK_DAYS // 2)
