from __future__ import annotations

import copy
import unittest

from argus_risk_discipline import build_risk_kernel
from argus_single_decision import (
    PRIMARY_ACTIONS,
    SINGLE_DECISION_AUTHORITY_V2_POLICY,
    SingleDecisionValidationError,
    build_data_gated_input_v2,
    build_prediction_ledger_v2_adapter,
    compute_prediction_adapter_id,
    compute_single_decision_id,
    evaluate_single_decision_authority,
    validate_single_decision_input_v2,
    validate_single_decision_result_v2,
)


AUTHORITY_SHA = "a" * 64
RISK_SHA = "b" * 64
TRUTH_SHA = "c" * 64
PREDICTION_SHA = "d" * 64
SHO_SHA = "e" * 64
SEVEN_SHA = "f" * 64


SUBJECT = {
    "kind": "ASSET",
    "instrumentId": "7203",
    "market": "JP",
    "horizon": "FIVE_DAY",
}
AUTHORITY_POLICY = {
    "policyId": "single-decision-authority-v2",
    "policySha256": AUTHORITY_SHA,
}


def owner(position="NOT_HELD", add="ALLOWED"):
    return {
        "schemaVersion": "owner-decision-context-v1",
        "privacyClass": "DEVICE_LOCAL",
        "asOf": "2026-08-16T09:00:00Z",
        "positionState": position,
        "positionRiskBand": "LOW",
        "concentrationBand": "LOW",
        "addPermission": add,
    }


def risk_kernel(constraint="NONE", *, factor="trend.market", cap=8500):
    return build_risk_kernel(
        {
            "schemaVersion": "argus-risk-discipline-input-v1",
            "subject": {"kind": "ASSET", "instrumentId": "7203", "market": "JP"},
            "asOf": "2026-08-16T09:00:00Z",
            "informationCutoffAt": "2026-08-16T08:59:00Z",
            "policy": {"policyId": "risk-discipline-v1", "policySha256": RISK_SHA},
            "contributions": [
                {
                    "evidenceRef": f"risk:{factor}",
                    "primitiveFactorId": factor,
                    "sourceKind": "MARKET",
                    "constraint": constraint,
                    "status": "ACTIVE",
                    "severity": "LOW" if constraint == "NONE" else "HIGH",
                    "confidenceCapBps": cap,
                    "observedAt": "2026-08-16T08:58:00Z",
                }
            ],
        }
    )


def complete_input(*, position="NOT_HELD", sho_state="REVERSAL_EARLY", buy=True, constraint="NONE"):
    return {
        "schemaVersion": "single-decision-authority-input-v2",
        "subject": copy.deepcopy(SUBJECT),
        "decisionAt": "2026-08-16T09:00:00Z",
        "informationCutoffAt": "2026-08-16T08:59:00Z",
        "authorityPolicy": copy.deepcopy(AUTHORITY_POLICY),
        "marketTruth": {
            "status": "AVAILABLE",
            "schemaVersion": "argus-market-truth-v1",
            "snapshotId": "market:snapshot-7203",
            "observationId": "market:observation-7203",
            "observedAt": "2026-08-16T08:57:00Z",
            "knownAt": "2026-08-16T08:58:00Z",
            "policyId": "market-truth-v1",
            "policySha256": TRUTH_SHA,
        },
        "predictionLedger": {
            "status": "AVAILABLE",
            "schemaVersion": "argus-prediction-ledger-v2",
            "contextId": "prediction:context-7203",
            "mode": "FORWARD_LIVE",
            "asOf": "2026-08-16T08:58:00Z",
            "policyId": "prediction-ledger-v2",
            "policySha256": PREDICTION_SHA,
        },
        "sho": {
            "status": "AVAILABLE",
            "schemaVersion": "argus-sho-v1",
            "artifactId": "sho:artifact-7203",
            "asOf": "2026-08-16T08:58:00Z",
            "policyId": "sho-policy-v1",
            "policySha256": SHO_SHA,
            "state": sho_state,
            "validationStatus": "VALIDATED",
            "buyEligible": buy,
            "primitiveFactorIds": ["momentum.reversal", "trend.market"],
            "targets": [
                {
                    "targetId": "target.primary",
                    "value": "3125.5",
                    "unit": "PRICE",
                    "sourceRef": "sho:target-primary",
                }
            ],
            "invalidation": {
                "invalidationId": "invalidation.primary",
                "value": "2840",
                "unit": "PRICE",
                "sourceRef": "sho:invalidation-primary",
            },
        },
        "riskKernel": risk_kernel(constraint),
        "contextEvidence": [
            {
                "evidenceRef": "event:calendar-clear",
                "primitiveFactorId": "event.calendar_clear",
                "sourceKind": "EVENT",
                "constraint": "NONE",
                "status": "ACTIVE",
                "observedAt": "2026-08-16T08:58:00Z",
            }
        ],
        "quality": {
            "status": "COMPLETE",
            "freshness": "FRESH",
            "missingReasonCodes": [],
            "conflictReasonCodes": [],
        },
        "ownerContext": owner(position),
        "challengeEvidence": [],
        "sevenSignCalibration": {
            "status": "MISSING",
            "artifactId": None,
            "policyId": None,
            "policySha256": None,
            "expectancyBpsByLevel": None,
            "sampleSizeByLevel": None,
            "outOfSample": False,
            "holdoutImmutable": False,
        },
    }


class SingleDecisionTests(unittest.TestCase):
    def test_exported_authority_policy_is_frozen_and_usable(self):
        with self.assertRaises(TypeError):
            SINGLE_DECISION_AUTHORITY_V2_POLICY["policyId"] = "caller-policy"
        value = build_data_gated_input_v2(
            subject=SUBJECT,
            decision_at="2026-08-16T09:00:00Z",
            information_cutoff_at="2026-08-16T08:59:00Z",
            authority_policy=SINGLE_DECISION_AUTHORITY_V2_POLICY,
        )
        self.assertEqual(value["authorityPolicy"], dict(SINGLE_DECISION_AUTHORITY_V2_POLICY))

    def test_closed_five_action_reducer_and_held_only_invariants(self):
        cases = (
            (complete_input(), "BUY"),
            (complete_input(position="HELD", sho_state="MIXED", buy=False), "HOLD"),
            (complete_input(sho_state="MIXED", buy=False), "WAIT"),
            (complete_input(position="HELD", constraint="REDUCE_RISK"), "REDUCE"),
            (complete_input(position="HELD", constraint="EXIT_RISK"), "EXIT"),
        )
        observed = []
        for value, expected in cases:
            result = evaluate_single_decision_authority(value)
            observed.append(result["primaryAction"])
            self.assertEqual(result["status"], "EVALUATED")
            self.assertEqual(result["primaryAction"], expected)
            validate_single_decision_result_v2(result)
        self.assertEqual(set(observed), set(PRIMARY_ACTIONS))

        self.assertEqual(
            evaluate_single_decision_authority(complete_input(constraint="REDUCE_RISK"))[
                "primaryAction"
            ],
            "WAIT",
        )
        self.assertEqual(
            evaluate_single_decision_authority(complete_input(constraint="EXIT_RISK"))[
                "primaryAction"
            ],
            "WAIT",
        )
        self.assertEqual(
            evaluate_single_decision_authority(
                complete_input(position="HELD", constraint="BLOCK_BUY")
            )["primaryAction"],
            "HOLD",
        )

    def test_missing_artifacts_have_an_honest_deterministic_wait_builder(self):
        value = build_data_gated_input_v2(
            subject=SUBJECT,
            decision_at="2026-08-16T09:00:00Z",
            information_cutoff_at="2026-08-16T08:59:00Z",
            authority_policy=AUTHORITY_POLICY,
        )
        validate_single_decision_input_v2(value)
        first = evaluate_single_decision_authority(value)
        second = evaluate_single_decision_authority(copy.deepcopy(value))

        self.assertEqual(first, second)
        self.assertEqual(first["status"], "DATA_GATED")
        self.assertEqual(first["primaryAction"], "WAIT")
        self.assertEqual(first["identities"]["marketTruth"]["status"], "MISSING")
        self.assertEqual(first["identities"]["predictionLedger"]["status"], "MISSING")
        self.assertEqual(first["identities"]["sho"]["status"], "MISSING")
        self.assertEqual(first["identities"]["risk"]["status"], "DATA_GATED")
        self.assertIsNone(first["sevenSign"]["candidateLevel"])
        self.assertIsNone(first["sevenSign"]["productionLevel"])
        self.assertEqual(first["decisionId"], compute_single_decision_id(first))

    def test_invalid_private_or_unknown_owner_fails_closed(self):
        private = complete_input()
        private["ownerContext"]["quantity"] = 100
        invalid = evaluate_single_decision_authority(private)
        self.assertEqual(invalid["status"], "DATA_GATED")
        self.assertEqual(invalid["primaryAction"], "WAIT")
        self.assertIsNone(invalid["subject"])
        self.assertEqual(invalid["missingReasonCodes"], ["input_invalid"])

        unknown = complete_input()
        unknown["ownerContext"] = owner("UNKNOWN", "UNKNOWN")
        unknown["ownerContext"]["positionRiskBand"] = "UNKNOWN"
        unknown["ownerContext"]["concentrationBand"] = "UNKNOWN"
        result = evaluate_single_decision_authority(unknown)
        self.assertEqual(result["status"], "DATA_GATED")
        self.assertEqual(result["primaryAction"], "WAIT")
        self.assertIn("owner_context_unknown", result["missingReasonCodes"])

    def test_ai_and_legacy_challenges_are_evidence_only(self):
        baseline_input = complete_input()
        baseline = evaluate_single_decision_authority(baseline_input)
        challenged = copy.deepcopy(baseline_input)
        challenged["challengeEvidence"] = [
            {
                "challengeId": "ai.challenge-1",
                "sourceKind": "AI",
                "status": "AVAILABLE",
                "asOf": "2026-08-16T09:00:00Z",
                "proposedAction": "EXIT",
                "dissentReasonCodes": ["ai_downside_dissent"],
                "evidenceRefs": ["ai:challenge-1"],
            },
            {
                "challengeId": "legacy.challenge-1",
                "sourceKind": "LEGACY",
                "status": "AVAILABLE",
                "asOf": "2026-08-16T08:59:00Z",
                "proposedAction": "WAIT",
                "dissentReasonCodes": ["legacy_wait_dissent"],
                "evidenceRefs": ["legacy:signal-1"],
            },
        ]
        result = evaluate_single_decision_authority(challenged)

        self.assertEqual(result["primaryAction"], baseline["primaryAction"])
        self.assertEqual(result["confidence"], baseline["confidence"])
        self.assertEqual(result["sevenSign"]["candidateLevel"], baseline["sevenSign"]["candidateLevel"])
        self.assertIn("ai_proposed_action_ignored", result["dissentReasonCodes"])
        self.assertIn("legacy_proposed_action_ignored", result["dissentReasonCodes"])

        mutated = copy.deepcopy(challenged)
        mutated["challengeEvidence"][0]["proposedAction"] = "HOLD"
        mutated["challengeEvidence"][1]["proposedAction"] = "REDUCE"
        self.assertEqual(
            evaluate_single_decision_authority(mutated)["primaryAction"],
            result["primaryAction"],
        )

    def test_primitive_factors_are_deduped_across_authorities(self):
        value = complete_input()
        value["contextEvidence"] = [
            {
                "evidenceRef": "event:trend-confirmation",
                "primitiveFactorId": "trend.market",
                "sourceKind": "EVENT",
                "constraint": "NONE",
                "status": "ACTIVE",
                "observedAt": "2026-08-16T08:58:00Z",
            }
        ]
        result = evaluate_single_decision_authority(value)
        self.assertEqual(result["primitiveFactorIds"].count("trend.market"), 1)

    def test_seven_sign_is_a_guarded_projection_not_old_action_level(self):
        value = complete_input()
        shadow = evaluate_single_decision_authority(value)
        self.assertEqual(shadow["primaryAction"], "BUY")
        self.assertEqual(shadow["sevenSign"]["candidateLevel"], 5)
        self.assertEqual(shadow["sevenSign"]["status"], "DATA_GATED")
        self.assertIsNone(shadow["sevenSign"]["productionLevel"])

        value["sevenSignCalibration"] = {
            "status": "VALIDATED",
            "artifactId": "seven:calibration-1",
            "policyId": "seven-sign-calibration-v1",
            "policySha256": SEVEN_SHA,
            "expectancyBpsByLevel": [-500, -300, -100, 0, 150, 300, 500],
            "sampleSizeByLevel": [30, 30, 30, 30, 30, 30, 30],
            "outOfSample": True,
            "holdoutImmutable": True,
        }
        guarded_claim = evaluate_single_decision_authority(value)
        self.assertEqual(guarded_claim["sevenSign"]["status"], "DATA_GATED")
        self.assertIsNone(guarded_claim["sevenSign"]["productionLevel"])
        self.assertIn("calibration_artifact_not_verified",
                      guarded_claim["sevenSign"]["reasonCodes"])

        value["sevenSignCalibration"]["expectancyBpsByLevel"] = [0, 100, 50, 200, 300, 400, 500]
        guarded = evaluate_single_decision_authority(value)
        self.assertEqual(guarded["sevenSign"]["status"], "DATA_GATED")
        self.assertIsNone(guarded["sevenSign"]["productionLevel"])
        self.assertIn("calibration_non_monotonic", guarded["sevenSign"]["reasonCodes"])

    def test_pit_and_exact_reference_contracts_are_enforced(self):
        value = complete_input()
        value["marketTruth"]["knownAt"] = "2026-08-16T09:00:00Z"
        with self.assertRaises(SingleDecisionValidationError):
            validate_single_decision_input_v2(value)
        self.assertEqual(evaluate_single_decision_authority(value)["primaryAction"], "WAIT")

        value = complete_input()
        value["marketTruth"]["secretProviderPayload"] = {"raw": True}
        with self.assertRaises(SingleDecisionValidationError):
            validate_single_decision_input_v2(value)

    def test_content_address_and_append_only_ledger_binding(self):
        result = evaluate_single_decision_authority(complete_input())
        before = copy.deepcopy(result)
        adapter = build_prediction_ledger_v2_adapter(result)

        self.assertEqual(result, before)
        self.assertEqual(adapter["recordType"], "canonical_decision_binding")
        self.assertEqual(adapter["appendMode"], "APPEND_ONLY")
        self.assertFalse(adapter["mutatesExistingRows"])
        self.assertEqual(adapter["decisionId"], result["decisionId"])
        self.assertEqual(adapter["marketTruthRef"], result["identities"]["marketTruth"])
        self.assertEqual(adapter["predictionLedgerRef"], result["identities"]["predictionLedger"])
        self.assertEqual(adapter["shoRef"], result["identities"]["sho"])
        self.assertEqual(adapter["riskRef"], result["identities"]["risk"])
        self.assertEqual(adapter["singleDecisionRef"]["decisionId"], result["decisionId"])
        self.assertEqual(adapter["sevenSignRef"]["status"], result["sevenSign"]["status"])
        self.assertEqual(adapter["adapterId"], compute_prediction_adapter_id(adapter))


if __name__ == "__main__":
    unittest.main()
