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
        self.assertEqual(document["reviewConditionsJa"], [
            "基準日や比較に使う市場条件が更新されたら、候補を選び直します。"])
        yen_scale = {"status": "AVAILABLE", "date": current["anchorDate"],
                     "anchorPrice": current["window"][-1]["close"], "eps": 2000,
                     "per": current["window"][-1]["close"] / 2000,
                     "basis": VALUATION_BASIS}
        yen = comparison_document(current, selected, paths, ensemble, scale=yen_scale)
        self.assertEqual(len(yen["reviewConditionsJa"]), 2)
        self.assertIn("EPS", yen["reviewConditionsJa"][1])
        # The explanation must not change paths, candidate identity or frequencies.
        for layer in ("actual",):
            self.assertEqual([p["value"] for p in yen[layer]],
                             [p["value"] * yen_scale["anchorPrice"] / 100 for p in document[layer]])
        self.assertEqual(yen["forecast"]["counts"], document["forecast"]["counts"])
        self.assertEqual([c["snapshotId"] for c in yen["candidates"]],
                         [c["snapshotId"] for c in document["candidates"]])
        self.assertEqual(document["forecast"]["validationStatus"], "UNVALIDATED")
        # 2026-09-30: the chart says how many market-condition series were
        # actually compared; a price-shape-only candidate reports zero.
        from jp_market_analogs import FEATURE_DEFINITIONS
        for candidate in document["candidates"]:
            self.assertEqual(candidate["stateFeatureDefinitionCount"], len(FEATURE_DEFINITIONS))
            self.assertEqual(candidate["comparedFeatureCount"], len(candidate["comparedFeatures"]))
            self.assertLessEqual(candidate["comparedFeatureCount"], len(FEATURE_DEFINITIONS))
            if "marketState" in candidate["missingGroups"]:
                self.assertEqual(candidate["comparedFeatures"], [])
            else:
                self.assertEqual(candidate["comparedFeatureCount"],
                                 len(FEATURE_DEFINITIONS) - len(candidate["missingFeatures"]))
        with self.assertRaisesRegex(ValueError, "chart_calculation_identity_mismatch"):
            comparison_document(current, dict(selected, currentSnapshotId="other"), paths, ensemble)


if __name__ == "__main__":
    unittest.main()


class ProxyScaleTest(unittest.TestCase):
    def test_the_proxy_basis_is_accepted_and_never_relabelled_as_official(self):
        from jp_market_price_paths import PROXY_BASIS
        proxy = scale(basis=PROXY_BASIS, officialErrorPct=-0.8,
                      coverage={"priced": 224, "members": 225})
        self.assertEqual(proxy["status"], "AVAILABLE")
        self.assertEqual(proxy["basis"], PROXY_BASIS)
        self.assertTrue(proxy["isProxy"])
        self.assertEqual(proxy["proxyErrorPct"], -0.8)
        self.assertIn("代理値", proxy["basisLabelJa"])
        official = scale()
        self.assertFalse(official["isProxy"])
        self.assertIsNone(official["proxyErrorPct"])
        converted = convert_shape_to_yen([{"offsetSessions": 0, "value": 100}], scale=proxy)
        self.assertEqual(converted[0]["scaleBasis"], PROXY_BASIS)
        self.assertEqual(converted[0]["value"], 40000)

    def test_any_other_basis_is_still_refused(self):
        self.assertEqual(scale(basis="CAP_WEIGHTED_PER")["reason"],
                         "incompatible_index_valuation_definition")


class SelectionPolicyDocumentTest(unittest.TestCase):
    def test_robust_scales_and_bounds_are_documented(self):
        from jp_market_analogs import FEATURE_DEFINITIONS, robust_feature_scales, AnalogPolicy
        rows = [{"instrumentId": "NIKKEI_225_INDEX", "seriesId": "credit.ratio", "date": f"2025-{m:02d}-{d:02d}",
                 "value": 4 + (d % 5) * .5, "unit": "RATIO"} for m in range(1, 13) for d in range(1, 29)]
        scales = robust_feature_scales(rows)
        self.assertEqual(scales["credit.ratio"]["basis"], "ROBUST_MAD_HISTORY")
        self.assertGreater(scales["credit.ratio"]["scale"], 0)
        self.assertEqual(scales["vix.level"]["basis"], "FIXED_DEFINITION")
        self.assertEqual(scales["vix.level"]["scale"], FEATURE_DEFINITIONS["vix.level"][1])
        policy = AnalogPolicy.with_scales(scales)
        self.assertEqual(policy.scale_for("credit.ratio"), scales["credit.ratio"]["scale"])
        self.assertEqual(policy.scale_for("vix.level"), FEATURE_DEFINITIONS["vix.level"][1])
        self.assertEqual(policy.maximum_candidates, 10)
        with self.assertRaisesRegex(ValueError, "invalid_analog_policy_state_scales"):
            AnalogPolicy(state_scales=(("credit.ratio", 0),))
        with self.assertRaisesRegex(ValueError, "invalid_analog_policy_state_scales"):
            AnalogPolicy(state_scales=(("not.a.feature", 1.0),))
        # A constant series has no spread: the fixed definition stays.
        flat = robust_feature_scales([{**r, "value": 5.0} for r in rows])
        self.assertEqual(flat["credit.ratio"]["basis"], "FIXED_DEFINITION")
