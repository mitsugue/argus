import copy
import json
import unittest
from datetime import date, timedelta
from pathlib import Path

import argus_sho as sho


CUTOFF = "2026-08-15T00:00:00Z"


def evidence(field, value, period="2026-08-01", available="2026-08-02T00:00:00Z",
             instrument="MARKET", **extra):
    return {
        "instrumentId": instrument,
        "field": field,
        "periodEnd": period,
        "availableFrom": available,
        "value": value,
        "revision": 0,
        **extra,
    }


def bars(instrument="NIKKEI_225_INDEX", count=70, *, start=100.0):
    first = date(2026, 5, 1)
    result = []
    for index in range(count):
        day = first + timedelta(days=index)
        close = start + index * 0.1 + (1.0 if index % 5 == 0 else 0.0)
        open_ = close - 0.2
        result.append({
            "instrumentId": instrument,
            "kind": "OHLCV_BAR",
            "date": day.isoformat(),
            "availableFrom": (day + timedelta(days=1)).isoformat() + "T00:00:00Z",
            "open": open_, "high": close + 2.0, "low": open_ - 2.0,
            "close": close, "volume": 1_000_000 + index,
            "sourceRef": "fixture:ohlcv", "revision": 0,
        })
    return result


def provenance(evidence_id, value, provenance_class="OBSERVED", **extra):
    row = {
        "evidenceId": evidence_id,
        "value": value,
        "provenance": provenance_class,
        "availableFrom": "2026-08-02T00:00:00Z",
        "sourceRef": "fixture:stock",
        **extra,
    }
    if provenance_class == "DERIVED":
        row.setdefault("derivedFrom", ["fixture:stock"])
    if provenance_class == "INFERRED":
        row.setdefault("inferenceMethod", "explicit-test-method")
    return row


class RegistryAndCoverageTest(unittest.TestCase):
    def test_canonical_registry_is_sealed_and_originals_are_exact(self):
        self.assertEqual(
            sho.CANONICAL_SHO_RFC_SHA256,
            "69a631ebc549b3bede6356cabf338e38d9418fc3683821198ef9a3c1eb440d51",
        )
        self.assertEqual(
            sho.SHO_REGISTRY_SHA256,
            "0ddae6123f70dd858d5135528768fa9b6cea561f31f47201b8e882c978cbf532",
        )
        registry = sho.sealed_proposition_registry()
        self.assertEqual(sho.validate_proposition_registry(registry), (True, "valid"))
        originals = [row for row in registry["propositions"]
                     if row["lineage"] == "SHO_ORIGINAL"]
        self.assertEqual([row["family"] for row in originals],
                         ["D01", "D02", "D03", "D04", "D05", "D06", "D07"])
        d02 = next(row for row in originals if row["family"] == "D02")
        self.assertEqual(d02["parameter"], {"operator": ">=", "value": 1,
                                            "unit": "RATIO"})
        candidate_ids = {row["id"] for row in registry["propositions"]
                         if row["lineage"] == "ARGUS_CANDIDATE"}
        self.assertIn("ARGUS-D06-MACD-12-26-9", candidate_ids)
        self.assertEqual(len([item for item in candidate_ids
                              if item.startswith("ARGUS-D01-SENS-")]), 5)
        registry["propositions"][0]["claim"] = "tampered"
        self.assertEqual(sho.validate_proposition_registry(registry),
                         (False, "registry_not_exact_sealed_value"))
        self.assertNotEqual(sho.sealed_proposition_registry()["propositions"][0]["claim"],
                            "tampered")

    def test_coverage_artifact_locks_exact_credit_csv(self):
        artifact = sho.coverage_artifact()
        credit = next(row for row in artifact["coverage"]
                      if row["dataId"] == "two_market_margin_balances")
        self.assertEqual(credit["repositoryPath"],
                         "ops/imports/jpx_two_market_credit_20020802_20260710.csv")
        self.assertEqual(credit["sha256"],
                         "50c57ae35762d90f5123f4fc40614c85954c7dee417ff249fc688b9130ee37cb")
        self.assertEqual((credit["coverageStart"], credit["coverageEnd"]),
                         ("2002-08-02", "2026-07-10"))
        self.assertEqual(credit["rowCount"], 2434)
        self.assertTrue(artifact["registrySealed"])
        self.assertEqual(len(artifact["registryIndex"]), 14)
        self.assertEqual(
            artifact["artifactId"],
            "sho-coverage-f7915840ff5a9d2eb8b94fa618b5ff4a7515d5fcf1a6d5b52594232e01973237",
        )
        committed = json.loads(
            (Path(__file__).parent / "artifacts" /
             "round2-sho-registry-coverage-v1.json").read_text(encoding="utf-8"))
        self.assertEqual(committed, artifact)


class PointInTimeAndPropositionTest(unittest.TestCase):
    def test_pit_excludes_future_missing_time_and_selects_revision(self):
        rows = [
            evidence("x", 1, available="2026-08-01T00:00:00Z"),
            {**evidence("x", 2, available="2026-08-02T00:00:00Z"),
             "revision": 1, "knownAt": "2026-08-02T00:00:00Z"},
            {**evidence("x", 3, available="2026-08-20T00:00:00Z"),
             "revision": 2, "knownAt": "2026-08-20T00:00:00Z"},
            {"instrumentId": "MARKET", "field": "y", "periodEnd": "2026-08-01",
             "value": 9},
        ]
        selected, proof = sho.point_in_time_rows(rows, CUTOFF)
        self.assertEqual([row["value"] for row in selected], [2])
        self.assertEqual(proof["excludedFutureCount"], 1)
        self.assertEqual(proof["excludedMalformedCount"], 1)
        self.assertFalse(proof["futureRowsAdmitted"])

    def test_revision_without_own_known_at_is_never_admitted(self):
        original = evidence("x", 1, available="2026-08-01T00:00:00Z")
        revision = {
            **original,
            "revision": 1,
            "value": 999,
            "sourceRef": "fixture:retrospective-without-known-at",
        }
        selected, proof = sho.point_in_time_rows([original, revision], CUTOFF)
        self.assertEqual([row["value"] for row in selected], [1])
        self.assertEqual(proof["excludedMalformedCount"], 1)
        self.assertFalse(proof["futureRowsAdmitted"])

    def test_same_revision_conflicting_payload_fails_closed(self):
        first = evidence("x", 1, available="2026-08-01T00:00:00Z")
        conflicting = {**first, "value": 2, "sourceRef": "fixture:conflict"}
        newer = {
            **first, "value": 3, "revision": 1,
            "knownAt": "2026-08-02T00:00:00Z"}
        for ordered in (
                [first, conflicting],
                [first, newer, conflicting],
                [first, conflicting, newer]):
            with self.assertRaisesRegex(ValueError, "conflicting_row_revision"):
                sho.point_in_time_rows(ordered, CUTOFF)

    def test_date_only_availability_is_conservative_end_of_day(self):
        rows = [evidence("x", 1, available="2026-08-02")]
        selected, proof = sho.point_in_time_rows(
            rows, "2026-08-02T12:00:00Z")
        self.assertEqual(selected, [])
        self.assertEqual(proof["excludedFutureCount"], 1)

    def test_future_observation_date_is_excluded_even_if_known_early(self):
        row = evidence(
            "x", 1, period="2099-01-01",
            available="2026-08-01T00:00:00Z")
        selected, proof = sho.point_in_time_rows([row], CUTOFF)
        self.assertEqual(selected, [])
        self.assertEqual(proof["excludedFutureCount"], 1)
        self.assertFalse(proof["futureRowsAdmitted"])

    def test_same_session_date_is_admitted_when_already_known(self):
        row = evidence(
            "x", 1, period="2026-08-15",
            available="2026-08-15T00:00:00Z")
        selected, proof = sho.point_in_time_rows(
            [row], "2026-08-15T20:30:00Z")
        self.assertEqual([item["value"] for item in selected], [1])
        self.assertEqual(proof["excludedFutureCount"], 0)

    def test_d01_exact_boundary_and_candidates(self):
        rows = [
            evidence("credit.short_balance", 800_000_000_000),
            evidence("credit.long_balance", 2_000_000_000_000),
        ]
        result = sho.evaluate_d01(rows, cutoff=CUTOFF)
        self.assertFalse(result["conditionMet"])
        self.assertEqual(result["threshold"]["operator"], "<")
        self.assertEqual(len(result["sensitivityCandidates"]), 5)
        rows[0]["value"] = 799_999_999_999
        self.assertTrue(sho.evaluate_d01(rows, cutoff=CUTOFF)["conditionMet"])

    def test_d02_never_infers_missing_1570_ratio(self):
        self.assertEqual(sho.evaluate_d02([], cutoff=CUTOFF)["status"], "MISSING")
        one = sho.evaluate_d02(
            [evidence("margin_ratio", 1, instrument="1570")], cutoff=CUTOFF)
        self.assertTrue(one["conditionMet"])
        self.assertFalse(one["inferred"])

    def test_direct_relative_strength_precedes_proxy_candidate(self):
        direct = evidence("relative_strength", 1.1, instrument="NIKKEI_225_INDEX")
        proxy = evidence("relative_strength", 1.2, instrument="1321")
        chosen = sho.evaluate_d03(
            cutoff=CUTOFF, direct_evidence=direct, proxy_evidence=proxy)
        self.assertEqual(chosen["sourceType"], "DIRECT_INDEX")
        proxy_only = sho.evaluate_d03(cutoff=CUTOFF, proxy_evidence=proxy)
        self.assertEqual(proxy_only["lineage"], "ARGUS_CANDIDATE")
        self.assertEqual(proxy_only["sourceType"], "ETF_PROXY")

    def test_nikkei_valuation_is_license_and_identity_gated(self):
        eps = evidence("nikkei_eps", 2000, instrument="NIKKEI_225_INDEX")
        blocked = sho.evaluate_d04(
            cutoff=CUTOFF, analysis_instrument="NIKKEI_225_INDEX",
            eps_evidence=eps)
        self.assertEqual(blocked["status"], "LICENSE_BLOCKED")
        proxy = sho.evaluate_d04(
            cutoff=CUTOFF, analysis_instrument="1321", eps_evidence=eps,
            license_status="AVAILABLE")
        self.assertTrue(proxy["identityViolationPrevented"])
        self.assertEqual(proxy["levels"], [])
        direct = sho.evaluate_d04(
            cutoff=CUTOFF, analysis_instrument="NIKKEI_225_INDEX",
            eps_evidence=eps, license_status="AVAILABLE")
        self.assertEqual([row["multiple"] for row in direct["levels"]],
                         [17, 18, 19, 20, 21])

    def test_foreign_flow_is_publication_gated(self):
        row = evidence("flow.foreign", 123, available="2026-08-20T00:00:00Z")
        self.assertEqual(sho.evaluate_d05([row], cutoff=CUTOFF)["status"], "MISSING")
        row["availableFrom"] = "2026-08-02T00:00:00Z"
        self.assertEqual(sho.evaluate_d05([row], cutoff=CUTOFF)["direction"], "INFLOW")

    def test_d06_preserves_unknown_original_parameter(self):
        rows = [evidence("vix.close", 20 + index * 0.1,
                         period=(date(2026, 5, 1) + timedelta(days=index)).isoformat(),
                         available=(date(2026, 5, 2) + timedelta(days=index)).isoformat()
                         + "T00:00:00Z", instrument="VIX")
                for index in range(50)]
        result = sho.evaluate_d06(rows, cutoff=CUTOFF)
        self.assertEqual(result["originalParameter"], "UNKNOWN")
        self.assertEqual(result["shoOriginalTransition"], None)
        self.assertEqual(result["argusBaseline"]["lineage"], "ARGUS_CANDIDATE")

    def test_d07_does_not_synthesize_earnings_quality(self):
        stock = bars("7203", count=12)
        event = {
            "instrumentId": "7203", "kind": "EARNINGS_EVENT",
            "date": stock[2]["date"], "availableFrom": stock[2]["availableFrom"],
            "epsActual": 110, "epsEstimate": 100, "qualitySupported": False,
        }
        result = sho.evaluate_d07(
            cutoff=CUTOFF, earnings_event=event, stock_bars=stock)
        self.assertEqual(result["earningsQuality"], None)
        self.assertEqual(result["earningsQualityStatus"], "MISSING")
        self.assertEqual(result["supportedBeatMiss"], "BEAT")


class StrictTechnicalAndTargetsTest(unittest.TestCase):
    def test_complete_ohlcv_never_fills_missing_components(self):
        source = bars(count=3)
        del source[1]["open"]
        normalized = sho.normalize_complete_ohlcv(source, cutoff=CUTOFF)
        self.assertEqual(len(normalized["bars"]), 2)
        self.assertEqual(normalized["proof"]["filledFields"], [])
        self.assertGreaterEqual(normalized["proof"]["rejectedCount"], 1)

    def test_reversal_state_supersedes_lagging_downside_and_may_jump(self):
        def factor(value):
            return {"status": "AVAILABLE", "conditionMet": value, "details": {}}

        evidence_row = {"factors": {
            "bandWalkEnding": factor(True), "vixMacdDeadCross": factor(True),
            "sarBullishFlip": factor(True), "nikkeiMacdGoldenCross": factor(False),
            "rsiResistanceBreakout": factor(False),
            "bollingerMiddleReclaim": factor(True), "ma25Reclaim": factor(False),
            "ma5Ma25GoldenCross": factor(False), "reclaimFailure": factor(False),
        }}
        state = sho.classify_reversal_state(
            evidence_row, downside_background="SELL_OFF_ACTIVE")
        self.assertEqual(state["state"], "CONFIRMED_ADVANCE")
        self.assertFalse(state["slowDownsideVetoApplied"])

    def test_reversal_evidence_is_deterministic_and_strict(self):
        nikkei = bars("NIKKEI_225_INDEX")
        vix = bars("VIX", start=20)
        first = sho.reversal_evidence(
            cutoff=CUTOFF, nikkei_rows=nikkei, vix_rows=vix)
        second = sho.reversal_evidence(
            cutoff=CUTOFF, nikkei_rows=nikkei, vix_rows=vix)
        self.assertEqual(first, second)
        self.assertTrue(first["strictCompleteOhlcv"])
        self.assertEqual(first["probability"], None)
        details = first["factors"]["vixMacdDeadCross"]["details"]
        self.assertEqual(details["shoOriginalParameters"], "UNKNOWN")
        self.assertEqual(details["fakeCrossProbability"], None)
        proxy_only = sho.reversal_evidence(
            cutoff=CUTOFF, nikkei_rows=bars("1321"), vix_rows=vix)
        self.assertEqual(proxy_only["nikkeiProof"]["acceptedCount"], 0)
        self.assertEqual(proxy_only["nikkeiIdentityRejectedRowCount"], 70)

    def test_short_canonical_reversal_artifact_roundtrips_data_gated(self):
        short = sho.build_reversal_engine(
            cutoff=CUTOFF, analysis_instrument="NIKKEI_225_INDEX",
            downside_background="SELL_OFF_ACTIVE",
            nikkei_rows=bars("NIKKEI_225_INDEX", count=2), vix_rows=[])
        self.assertEqual(short["evidence"]["sarBullishFlip"]["status"],
                         "MISSING")
        self.assertEqual(sho.validate_reversal_artifact(short), short)

    def test_target_zones_withhold_all_prevalidation_statistics(self):
        source = bars("NIKKEI_225_INDEX")
        gap = [{
            "instrumentId": "NIKKEI_225_INDEX", "kind": "GAP",
            "date": "2026-07-20", "availableFrom": "2026-07-21T00:00:00Z",
            "level": 115, "filled": False, "gapId": "gap-1",
            "sourceRef": "fixture:gap",
        }]
        profile = [{
            "instrumentId": "NIKKEI_225_INDEX", "kind": "VOLUME_PROFILE",
            "date": "2026-07-20", "availableFrom": "2026-07-21T00:00:00Z",
            "level": 116, "levelId": "vp-1", "provenance": "OBSERVED",
            "sourceRef": "fixture:vp",
        }]
        target = sho.build_target_zones(
            cutoff=CUTOFF, analysis_instrument="NIKKEI_225_INDEX", bars=source,
            swing_low=80, swing_high=120, previous_high=122,
            gap_evidence=gap, observed_volume_profile=profile)
        self.assertEqual(target["status"], "AVAILABLE")
        self.assertTrue(target["probabilitiesWithheldPendingValidation"])
        self.assertTrue(target["zones"])
        for zone in target["zones"]:
            self.assertIsNone(zone["hitProbability"])
            self.assertIsNone(zone["breakProbability"])
            self.assertIsNone(zone["medianTimeToTarget"])
            self.assertIsNone(zone["maeBeforeTarget"])
            self.assertEqual(zone["sampleSize"], 0)
            self.assertIsNone(zone["confidenceInterval"])
            self.assertIsNone(zone["hit_probability"])
            self.assertIsNone(zone["break_probability"])

    def test_nikkei_valuation_targets_never_apply_to_1321(self):
        eps = evidence("nikkei_eps", 10, instrument="NIKKEI_225_INDEX")
        target = sho.build_target_zones(
            cutoff=CUTOFF, analysis_instrument="1321", bars=bars("1321"),
            swing_low=80, swing_high=120, previous_high=122,
            eps_evidence=eps, valuation_license_status="AVAILABLE")
        self.assertFalse(any(row["family"] == "VALUATION"
                             for row in target["candidateLevels"]))
        self.assertIn("nikkei_valuation_not_applicable_to_proxy_or_topix",
                      target["missing"])
        mislabeled = sho.build_target_zones(
            cutoff=CUTOFF, analysis_instrument="NIKKEI_225_INDEX",
            bars=bars("1321"), swing_low=80, swing_high=120,
            previous_high=122)
        self.assertEqual(mislabeled["status"], "MISSING")
        self.assertEqual(mislabeled["identityRejectedRowCount"], 70)


class IdentityStockLensAndProjectionTest(unittest.TestCase):
    def test_proxy_is_never_substituted_for_direct_index(self):
        proxy_rows = bars("1321")
        model = sho.build_direct_index_model(
            cutoff=CUTOFF, analysis_instrument="NIKKEI_225_INDEX",
            direct_rows=proxy_rows, proxy_rows=proxy_rows)
        self.assertEqual(model["status"], "DATA_GATED")
        self.assertEqual(model["analysisInstrument"]["latestClose"], None)
        self.assertEqual(model["tradableProxy"]["status"], "AVAILABLE")
        self.assertFalse(model["proxyUsedAsDirectIndex"])
        direct = sho.build_direct_index_model(
            cutoff=CUTOFF, analysis_instrument="NIKKEI_225_INDEX",
            direct_rows=bars("NIKKEI_225_INDEX"), proxy_rows=proxy_rows)
        self.assertEqual(direct["analysisInstrument"]["status"], "AVAILABLE")
        self.assertEqual(direct["analysisInstrument"]["instrumentType"], "INDEX")

    def test_provenance_rejects_unsupported_observed_and_preserves_inference(self):
        missing_source = provenance("margin_ratio", 2)
        del missing_source["sourceRef"]
        inferred = provenance("foreign_stock_flow", 10, "INFERRED")
        unknown = provenance("mystery", 1, "UNKNOWN")
        result = sho.validate_evidence_provenance(
            [missing_source, inferred, unknown], cutoff=CUTOFF)
        self.assertEqual(len(result["observed"]), 0)
        self.assertEqual(len(result["inferred"]), 1)
        self.assertEqual(len(result["unknown"]), 1)
        self.assertEqual(result["proof"]["inferredPromotedToObserved"], False)
        self.assertEqual(result["rejected"][0]["reason"],
                         "observed_requires_source_ref_and_available_from")

    def test_stock_lens_uses_required_hierarchy_and_no_inferred_driver(self):
        supply = [
            provenance("return_5d_pct", -6),
            provenance("volume_ratio_20", 1.8, "DERIVED"),
            provenance("margin_long_1w_change", -100),
            provenance("foreign_stock_flow", -500, "INFERRED"),
        ]
        lens = sho.build_stock_lens(
            cutoff=CUTOFF, symbol="7203", market_state="SELL_OFF_ACTIVE",
            sector_style_evidence=[provenance("sector_relative_strength", -2)],
            supply_evidence=supply,
            technical_earnings_evidence=[provenance("earnings_reaction_5d", 1)],
            target_invalidation_evidence=[provenance("invalidation_price", 95)],
        )
        self.assertEqual(lens["hierarchy"], [
            "SHO_JP_MARKET_STATE", "SECTOR_STYLE_STATE",
            "STOCK_SUPPLY_DEMAND", "STOCK_TECHNICAL_EARNINGS",
            "STOCK_TARGET_INVALIDATION",
        ])
        self.assertEqual(lens["supplyState"]["state"], "FORCED_LIQUIDATION")
        self.assertEqual(lens["supplyState"]["inferredDriverCount"], 0)
        self.assertFalse(lens["inferredForeignFlowPresentedAsObserved"])
        self.assertIsNone(lens["action"])

    def test_today_sda_projection_accepts_exact_artifacts_only(self):
        reversal = sho.build_reversal_engine(
            cutoff=CUTOFF, analysis_instrument="NIKKEI_225_INDEX",
            downside_background="SELL_OFF_ACTIVE",
            nikkei_rows=bars("NIKKEI_225_INDEX"), vix_rows=bars("VIX", start=20))
        self.assertEqual(
            sho.validate_reversal_artifact(reversal), reversal)
        hostile = copy.deepcopy(reversal)
        hostile["evidenceArtifact"]["factors"]["bandWalkEnding"].update({
            "conditionMet": True,
            "evidenceDate": "2026-08-15",
            "status": "MISSING",
        })
        evidence_body = {
            key: value for key, value in hostile["evidenceArtifact"].items()
            if key != "artifactId"}
        hostile["evidenceArtifact"]["artifactId"] = \
            "sho-reversal-evidence-" + sho._sha256(evidence_body)
        hostile["evidenceArtifactId"] = hostile[
            "evidenceArtifact"]["artifactId"]
        hostile["evidence"] = hostile["evidenceArtifact"]["factors"]
        hostile_body = {key: value for key, value in hostile.items()
                        if key != "artifactId"}
        hostile["artifactId"] = "sho-reversal-" + sho._sha256(hostile_body)
        with self.assertRaisesRegex(
                ValueError, "invalid_reversal_evidence_artifact"):
            sho.validate_reversal_artifact(hostile)
        for axis in ("downsideAxis", "reversalAxis"):
            hostile_axis = copy.deepcopy(reversal)
            hostile_axis[axis] = {}
            hostile_axis_body = {
                key: value for key, value in hostile_axis.items()
                if key != "artifactId"}
            hostile_axis["artifactId"] = \
                "sho-reversal-" + sho._sha256(hostile_axis_body)
            with self.assertRaises(ValueError):
                sho.validate_reversal_artifact(hostile_axis)
        hostile_proof = copy.deepcopy(reversal)
        hostile_proof["evidenceArtifact"]["nikkeiProof"] = {
            "futureRowsAdmitted": True}
        evidence_body = {
            key: value for key, value in hostile_proof[
                "evidenceArtifact"].items() if key != "artifactId"}
        hostile_proof["evidenceArtifact"]["artifactId"] = \
            "sho-reversal-evidence-" + sho._sha256(evidence_body)
        hostile_proof["evidenceArtifactId"] = hostile_proof[
            "evidenceArtifact"]["artifactId"]
        hostile_proof["evidence"] = hostile_proof[
            "evidenceArtifact"]["factors"]
        hostile_body = {key: value for key, value in hostile_proof.items()
                        if key != "artifactId"}
        hostile_proof["artifactId"] = \
            "sho-reversal-" + sho._sha256(hostile_body)
        with self.assertRaisesRegex(
                ValueError, "invalid_reversal_evidence_artifact"):
            sho.validate_reversal_artifact(hostile_proof)
        zero_coverage = copy.deepcopy(reversal)
        pit_body = {
            "policyId": "sho-explicit-publication-pit-v1",
            "cutoff": CUTOFF,
            "inputCount": 0,
            "includedCount": 0,
            "excludedFutureCount": 0,
            "excludedMalformedCount": 0,
            "futureRowsAdmitted": False,
            "datasetHash": sho._sha256([]),
        }
        pit = {**pit_body, "proofId": "sho-pit-" + sho._sha256(pit_body)}
        ohlcv_body = {
            "policyId": "sho-complete-ohlcv-v1",
            "pointInTimeProofId": pit["proofId"],
            "pointInTimeProof": pit,
            "visibleCount": 0,
            "acceptedCount": 0,
            "rejectedCount": 0,
            "rejectionReasons": {},
            "filledFields": [],
            "datasetHash": sho._sha256([]),
        }
        zero_proof = {
            **ohlcv_body,
            "proofId": "sho-ohlcv-" + sho._sha256(ohlcv_body),
        }
        zero_coverage["evidenceArtifact"]["nikkeiProof"] = zero_proof
        zero_coverage["evidenceArtifact"]["vixProof"] = zero_proof
        evidence_body = {
            key: value for key, value in zero_coverage[
                "evidenceArtifact"].items() if key != "artifactId"}
        zero_coverage["evidenceArtifact"]["artifactId"] = \
            "sho-reversal-evidence-" + sho._sha256(evidence_body)
        zero_coverage["evidenceArtifactId"] = zero_coverage[
            "evidenceArtifact"]["artifactId"]
        zero_coverage["evidence"] = zero_coverage[
            "evidenceArtifact"]["factors"]
        zero_coverage["reversalAxis"] = sho.classify_reversal_state(
            zero_coverage["evidenceArtifact"],
            downside_background=zero_coverage["downsideAxis"]["state"])
        zero_body = {key: value for key, value in zero_coverage.items()
                     if key != "artifactId"}
        zero_coverage["artifactId"] = \
            "sho-reversal-" + sho._sha256(zero_body)
        with self.assertRaisesRegex(
                ValueError, "invalid_reversal_evidence_artifact"):
            sho.validate_reversal_artifact(zero_coverage)
        target = sho.build_target_zones(
            cutoff=CUTOFF, analysis_instrument="NIKKEI_225_INDEX",
            bars=bars("NIKKEI_225_INDEX"), swing_low=80, swing_high=120,
            previous_high=122)
        projection = sho.project_today_sda_safe(
            cutoff=CUTOFF, reversal=reversal, target_ladder=target)
        self.assertEqual(projection["status"], "AVAILABLE")
        self.assertFalse(projection["actionAuthority"])
        self.assertIsNone(projection["action"])
        self.assertEqual(projection["automaticAiCalls"], 0)
        tampered = copy.deepcopy(reversal)
        tampered["reversalAxis"]["state"] = "CONFIRMED_ADVANCE"
        rejected = sho.project_today_sda_safe(cutoff=CUTOFF, reversal=tampered)
        self.assertEqual(rejected["status"], "MISSING")
        self.assertEqual(rejected["rejectedArtifacts"], ["reversal"])

    def test_facade_is_json_serializable_and_has_no_action(self):
        result = sho.evaluate_d01_d07(cutoff=CUTOFF)
        json.dumps(result, allow_nan=False)
        self.assertIsNone(result["action"])
        self.assertEqual(result["automaticAiCalls"], 0)
        self.assertEqual(sorted(result["families"]),
                         ["D01", "D02", "D03", "D04", "D05", "D06", "D07"])


if __name__ == "__main__":
    unittest.main()
