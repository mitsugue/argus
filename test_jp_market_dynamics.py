import copy
import math
import random
import unittest

from jp_market_dynamics import credit_dynamics, decompose_margin_ratio, normalize_valuation_loss


def snapshot(long_value=200, short_value=100, period="2026-09-04", **extra):
    return {"instrumentId": "1570", "balanceKind": "WEEKLY_MARGIN",
            "unit": "SHARES", "periodEnd": period,
            "longBalance": long_value, "shortBalance": short_value, **extra}


def rows(period, long_value, short_value, available=None):
    return [{"instrumentId": "1570", "seriesId": "margin." + side,
             "periodEnd": period, "availableFrom": available or period + "T16:00:00Z",
             "value": value, "unit": "SHARES", "revision": 0}
            for side, value in (("long", long_value), ("short", short_value))]


def dynamics(data, cutoff="2026-09-12T00:00:00Z"):
    return credit_dynamics(data, cutoff=cutoff, instrument_id="1570",
                           balance_kind="WEEKLY_MARGIN",
                           long_series="margin.long", short_series="margin.short")


class RatioDecompositionTest(unittest.TestCase):
    def test_pure_long_and_short_changes_have_distinct_explanations(self):
        before = snapshot()
        buy = decompose_margin_ratio(before, snapshot(300, period="2026-09-11"))
        sell = decompose_margin_ratio(before, snapshot(200, 50, "2026-09-11"))
        self.assertEqual((buy["longContribution"], buy["shortContribution"]), (1, 0))
        self.assertEqual((sell["longContribution"], sell["shortContribution"]), (0, 2))
        self.assertTrue(sell["isOneWeekChange"])
        self.assertFalse(sell["observedCoveringOrders"])
        self.assertFalse(sell["actionAuthority"])

    def test_symmetric_contributions_reconstruct_ratio_change(self):
        rng = random.Random(136)
        for _ in range(500):
            scale = 10 ** rng.uniform(1, 13)
            b0, s0, b1, s1 = [scale * rng.uniform(.1, 20) for _ in range(4)]
            value = decompose_margin_ratio(snapshot(b0, s0), snapshot(b1, s1, "2026-09-11"))
            self.assertTrue(math.isclose(value["longContribution"] + value["shortContribution"],
                                        b1 / s1 - b0 / s0, rel_tol=1e-9, abs_tol=1e-9))
            reverse = decompose_margin_ratio(snapshot(b1, s1), snapshot(b0, s0, "2026-09-11"))
            self.assertAlmostEqual(value["longContribution"], -reverse["longContribution"])
            self.assertAlmostEqual(value["shortContribution"], -reverse["shortContribution"])

    def test_missing_invalid_and_incompatible_inputs_remain_unknown(self):
        before = snapshot()
        for patch in ({"unit": "JPY"}, {"instrumentId": "1321"},
                      {"balanceKind": "SECURITIES_FINANCE"}, {"shortBalance": 0},
                      {"longBalance": -1}, {"longBalance": float("nan")},
                      {"shortBalance": True}, {"periodEnd": "2026-09-01"}):
            value = decompose_margin_ratio(before, snapshot(period="2026-09-11", **patch))
            self.assertEqual(value["status"], "UNAVAILABLE")
            self.assertIsNone(value["ratioChange"])

    def test_zero_long_is_valid_and_missing_week_not_called_weekly(self):
        value = decompose_margin_ratio(snapshot(0), snapshot(200, period="2026-09-18"))
        self.assertEqual(value["ratioChange"], 2)
        self.assertIsNone(value["longBalanceChangePct"])
        self.assertEqual(value["periodDays"], 14)
        self.assertFalse(value["isOneWeekChange"])


class CreditJoinTest(unittest.TestCase):
    def test_future_revision_does_not_change_old_view(self):
        data = rows("2026-09-04", 200, 100) + rows("2026-09-11", 300, 100)
        expected = dynamics(data)
        correction = dict(data[-2], value=500, revision=1,
                          knownAt="2026-09-15T00:00:00Z")
        actual = dynamics(data + [correction])
        self.assertEqual(expected["current"], actual["current"])
        self.assertEqual(actual["change"]["ratioChange"], 1)
        self.assertEqual(actual["pointInTimeProof"]["excludedFutureCount"], 1)
        later = dynamics(data + [correction], "2026-09-16T00:00:00Z")
        self.assertEqual(later["current"]["ratio"], 5)
        self.assertFalse(later["historicalVintageVerified"])

    def test_missing_latest_side_does_not_borrow_previous_week(self):
        data = rows("2026-09-04", 200, 100) + rows("2026-09-11", 300, 100)[:1]
        actual = dynamics(data)
        self.assertEqual(actual["status"], "INCOMPLETE_OR_INVALID")
        self.assertIsNone(actual["current"]["shortBalance"])
        self.assertIsNone(actual["current"]["ratio"])
        self.assertEqual(actual["change"]["status"], "UNAVAILABLE")

    def test_other_series_and_instruments_do_not_mix(self):
        data = rows("2026-09-04", 200, 100) + rows("2026-09-11", 300, 100)
        expected = dynamics(data)
        unrelated = [dict(r, instrumentId="1321", value=99999) for r in data]
        unrelated += [dict(r, seriesId="finance." + r["seriesId"], value=88888) for r in data]
        self.assertEqual(dynamics(data + unrelated), expected)

    def test_provenance_and_original_rows_are_preserved(self):
        data = rows("2026-09-04", 200, 100) + rows("2026-09-11", 300, 100)
        data[-1]["sourceRef"] = "reference:margin-weekly"
        before = copy.deepcopy(data)
        actual = dynamics(data)
        self.assertEqual(actual["current"]["sourceRows"]["short"], data[-1])
        self.assertEqual(data, before)


class LossSemanticsTest(unittest.TestCase):
    def test_sign_and_units_are_explicit(self):
        self.assertEqual(normalize_valuation_loss(-.15, sign_convention="negative_is_loss",
                                                 unit="FRACTION")["lossPct"], 15)
        self.assertEqual(normalize_valuation_loss(15, sign_convention="positive_is_loss",
                                                 unit="PERCENT")["lossPct"], 15)
        self.assertIsNone(normalize_valuation_loss(-15, sign_convention="unknown",
                                                  unit="PERCENT")["lossPct"])


if __name__ == "__main__":
    unittest.main()
