import copy
import unittest

from jp_market_source_adapters import normalize_jquants_margin_snapshot as normalize
from jp_market_dynamics import credit_dynamics


class MarginSourceTests(unittest.TestCase):
    def setUp(self):
        self.options = dict(instrument_id="1570", observed_at="2026-09-12T01:12:11Z",
                            response_sha256="a" * 64, volume_unit="UNITS")
        self.rows = [{"Date": "2026-08-28", "Code": "15700", "LongVol": 120, "ShrtVol": 20,
                      "LongStdVol": 80, "LongNegVol": 40, "ShrtStdVol": 18, "ShrtNegVol": 2},
                     {"Date": "2026-09-04", "Code": "15700", "LongVol": 150, "ShrtVol": 15}]

    def result(self, rows=None, **extra):
        return normalize({"data": self.rows if rows is None else rows, **extra}, **self.options)

    def test_balance_components_and_receipt_provenance(self):
        result = self.result()
        self.assertEqual(len(result["rows"]), 8)
        self.assertEqual(result["status"], "AVAILABLE")
        for row in result["rows"]:
            self.assertEqual(row["knownAt"], "2026-09-12T01:12:11+00:00")
            self.assertIsNone(row["publishedAt"])
            self.assertFalse(row["creditTermKnown"])
        self.assertEqual(self.rows[0]["LongVol"], 120)

    def test_current_dynamics_and_no_historical_backdating(self):
        rows = self.result()["rows"]
        args = dict(instrument_id="1570", balance_kind="WEEKLY_MARGIN",
                    long_series="margin.long_balance", short_series="margin.short_balance")
        before = credit_dynamics(rows, cutoff="2026-09-11T23:00:00Z", **args)
        self.assertIsNone(before["current"])
        current = credit_dynamics(rows, cutoff="2026-09-12T02:00:00Z", **args)
        self.assertEqual(current["current"]["ratio"], 10)
        self.assertEqual(current["change"]["ratioChange"], 4)
        self.assertAlmostEqual(current["change"]["longContribution"] + current["change"]["shortContribution"], 4)

    def test_wrong_code_and_invalid_totals(self):
        for patch in ({"Code": "72030"}, {"LongVol": None}, {"LongVol": True},
                      {"LongVol": -1}, {"LongVol": float("inf")}, {"LongVol": 1.5}):
            rows = [dict(self.rows[1], **patch)]
            self.assertEqual(self.result(rows)["rows"], [])

    def test_component_disagreement_not_silently_accepted(self):
        rows = copy.deepcopy(self.rows[:1]); rows[0]["LongNegVol"] = 41
        self.assertEqual(self.result(rows)["rejectedRows"][0]["reason"], "inconsistent_credit_components")

    def test_duplicate_period_invalidates_both(self):
        result = self.result([self.rows[1], dict(self.rows[1], LongVol=180)])
        self.assertEqual(result["rows"], [])
        self.assertEqual(result["status"], "PARTIAL")

    def test_future_period_rejected(self):
        self.assertEqual(self.result([dict(self.rows[1], Date="2026-09-18")])["rows"], [])

    def test_zero_balances_preserved_without_finite_ratio(self):
        result = self.result([dict(self.rows[1], LongVol=0, ShrtVol=0)])
        self.assertEqual(len(result["rows"]), 2)
        self.assertTrue(all(row["value"] == 0 for row in result["rows"]))

    def test_missing_unit_receipt_or_digest_cannot_be_invented(self):
        for key, value in (("volume_unit", "JPY"), ("observed_at", ""), ("observed_at", "2026-09-12"), ("response_sha256", "")):
            with self.assertRaises(ValueError):
                normalize({"data": self.rows}, **{**self.options, key: value})

    def test_pagination_is_explicitly_partial(self):
        result = self.result(pagination_key="opaque-cursor")
        self.assertEqual(result["status"], "PARTIAL")
        self.assertNotIn("opaque-cursor", str(result))

    def test_empty_data_is_unavailable(self):
        self.assertEqual(self.result([])["status"], "UNAVAILABLE")


if __name__ == "__main__":
    unittest.main()
