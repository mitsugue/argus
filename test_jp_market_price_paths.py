import unittest

from jp_market_price_paths import (VALUATION_BASIS, convert_shape_to_yen,
                                   index_valuation_scale, reference_ensemble, comparison_document)


def scale(**patch):
    valuation = {"instrumentId": "NIKKEI_225_INDEX", "basis": VALUATION_BASIS,
                 "currency": "JPY", "date": "2026-09-11", "indexClose": 40000,
                 "per": 20, "sourceRef": "test:index-valuation",
                 "knownAt": "2026-09-11T08:00:00Z", **patch}
    return index_valuation_scale(valuation, cutoff="2026-09-11T09:00:00Z",
                                 anchor_date="2026-09-11", anchor_price=40000)


def path(identifier, final):
    return {"snapshotId": identifier, "scale": "ANCHOR_100", "status": "AVAILABLE",
            "horizonSessions": 5, "displayCutoff": "2026-09-11T00:00:00Z", "subsequentReference": [
                {"offsetSessions": i, "value": 100 + (final - 100) * i / 5} for i in range(6)]}


class PriceScaleTest(unittest.TestCase):
    def test_index_definition_and_formula_are_preserved_without_per_clipping(self):
        value = scale(per=25)
        self.assertEqual(value["eps"], 1600)
        converted = convert_shape_to_yen([{"value": 100}, {"value": 120}], scale=value)
        self.assertEqual([row["value"] for row in converted], [40000, 48000])
        self.assertEqual(value["per"], 25)
        self.assertFalse(value["perClippingApplied"])

    def test_wrong_definition_future_or_mismatched_valuation_is_not_used(self):
        for patch in ({"basis": "CAP_WEIGHTED_PER"}, {"instrumentId": "1321"},
                      {"knownAt": "2026-09-12T08:00:00Z"}, {"date": "2026-09-10"},
                      {"indexClose": 39900}, {"per": 0}, {"sourceRef": None}):
            value = scale(**patch)
            self.assertEqual(value["status"], "UNAVAILABLE")
            self.assertEqual(convert_shape_to_yen([{"value": 100}], scale=value), [])


class ReferenceEnsembleTest(unittest.TestCase):
    def test_frequency_band_and_probability_have_distinct_semantics(self):
        selected = {"informationCutoff": "2026-09-11T00:00:00Z", "selectionId": "selection-test", "selected": [{"snapshotId": value} for value in "abc"]}
        result = reference_ensemble(selected, [path("a", 102), path("b", 100.5), path("c", 98)])
        self.assertEqual(result["frequency"]["counts"], {"up": 1, "flat": 1, "down": 1})
        self.assertEqual(result["forecastLine"][-1]["value"], 100.5)
        self.assertIsNone(result["predictiveProbabilities"])
        self.assertFalse(result["baselineAdditionalBenefitVerified"])
        self.assertFalse(result["actionAuthority"])

    def test_reference_from_after_selection_cutoff_is_not_used(self):
        selected = {"informationCutoff": "2026-09-10T00:00:00Z", "selected": [{"snapshotId": "a"}]}
        self.assertEqual(reference_ensemble(selected, [path("a", 120)])["frequency"]["sampleCount"], 0)

    def test_unselected_duplicate_and_partial_paths_do_not_inflate_counts(self):
        selected = {"informationCutoff": "2026-09-11T00:00:00Z", "selected": [{"snapshotId": "a"}, {"snapshotId": "b"}]}
        partial = path("b", 105)
        partial["subsequentReference"].pop()
        result = reference_ensemble(selected, [path("a", 102), path("a", 102), path("x", 120), partial])
        self.assertEqual(result["frequency"]["sampleCount"], 1)
        self.assertEqual(result["forecastLine"], [])
        self.assertEqual(result["status"], "INSUFFICIENT_COMPLETE_ANALOGS")


class ChartContractTest(unittest.TestCase):
    def test_calculation_ids_and_anchor_are_shared_by_all_chart_layers(self):
        from test_jp_market_analogs import DAYS, POLICY, bars, episode
        from jp_market_analogs import select_episodes, reference_path
        current, past = episode(83), [episode(11), episode(23)]
        selected = select_episodes(current, past, session_dates=DAYS, policy=POLICY)
        paths = [reference_path(item, later_bars=bars(0, 84), display_cutoff=current["cutoff"],
                                session_dates=DAYS, policy=POLICY) for item in past]
        ensemble = reference_ensemble(selected, paths)
        document = comparison_document(current, selected, paths, ensemble)
        self.assertEqual(document["actual"][-1]["value"], 100)
        self.assertEqual(document["forecast"]["line"][0]["value"], 100)
        self.assertEqual(len(document["candidates"]), 2)
        self.assertEqual(document["unit"], "ANCHOR_100")
        self.assertEqual(document["forecast"]["validationStatus"], "UNVALIDATED")
        with self.assertRaisesRegex(ValueError, "chart_calculation_identity_mismatch"):
            comparison_document(current, dict(selected, currentSnapshotId="other"), paths, ensemble)


if __name__ == "__main__":
    unittest.main()
