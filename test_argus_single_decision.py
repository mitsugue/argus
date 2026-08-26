from __future__ import annotations

import copy
import hashlib
import json
import unittest

import argus_decision_ledger as ledger
import argus_market_data_truth as truth
import argus_sho as sho
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
    verify_decision_evidence,
)


DECISION_AT = "2026-08-14T01:00:04Z"
CUTOFF = "2026-08-14T01:00:03Z"
INSTRUMENT = "JP:7203:EQUITY"
SUBJECT = {
    "kind": "ASSET",
    "instrumentId": INSTRUMENT,
    "market": "JP",
    "horizon": "FIVE_DAY",
}


def canonical_sha(value):
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def owner(position="HELD", add="ALLOWED"):
    return {
        "schemaVersion": "owner-decision-context-v1",
        "privacyClass": "DEVICE_LOCAL",
        "asOf": DECISION_AT,
        "positionState": position,
        "positionRiskBand": "LOW",
        "concentrationBand": "LOW",
        "addPermission": add,
    }


def risk_kernel(constraint="NONE"):
    return build_risk_kernel({
        "schemaVersion": "argus-risk-discipline-input-v1",
        "subject": {"kind": "ASSET", "instrumentId": INSTRUMENT, "market": "JP"},
        "asOf": DECISION_AT,
        "informationCutoffAt": CUTOFF,
        "policy": {"policyId": "risk-discipline-v1", "policySha256": "b" * 64},
        "contributions": [{
            "evidenceRef": "risk:trend.market",
            "primitiveFactorId": "trend.market",
            "sourceKind": "MARKET",
            "constraint": constraint,
            "status": "ACTIVE",
            "severity": "LOW" if constraint == "NONE" else "HIGH",
            "confidenceCapBps": 8500,
            "observedAt": "2026-08-14T01:00:02Z",
        }],
    })


def canonical_artifacts():
    observation = truth.build_observation(
        instrument_id=INSTRUMENT,
        symbol="7203",
        market="JP",
        asset_type="EQUITY",
        fact_type="QUOTE",
        values={"price": 3000.0},
        provider="moomoo",
        adapter="fixture.moomoo.v1",
        source_ref="fixture:moomoo:0",
        observed_at="2026-08-14T01:00:00Z",
        received_at="2026-08-14T01:00:01Z",
        known_at="2026-08-14T01:00:02Z",
        freshness="FRESH",
        completeness="COMPLETE",
        fresh_until="2026-08-14T01:05:00Z",
        currency="JPY",
        revision=0,
        provenance={"fixture": "credential-free"},
    )
    snapshot = truth.build_decision_snapshot(
        [observation],
        requests=[{
            "instrumentId": INSTRUMENT,
            "market": "JP",
            "factType": "QUOTE",
            "currency": "JPY",
            "required": True,
        }],
        decision_at=CUTOFF,
        generated_at=DECISION_AT,
        build_identity="a" * 40,
    )
    truth_ref = ledger.point_in_time_truth_ref(
        snapshot_id=snapshot["snapshotId"],
        source_id=observation["observationId"],
        provider="moomoo",
        as_of=observation["observedAt"],
        known_at=observation["knownAt"],
        revision=str(observation["revision"]),
        content_hash=observation["observationId"],
        observation_kind="decision_quote",
        observed_fields=sorted(observation["values"]),
    )
    maturity = ledger.session_maturity_contract(
        calendar_id="JPX",
        target_session_id="JPX:2026-08-21:regular",
        target_at="2026-08-21T06:00:00Z",
        maturity_at="2026-08-21T06:05:00Z",
        horizon="5d",
    )
    policy = {
        "policyId": "round2-scenario-5d",
        "policyVersion": "1",
        "parametersHash": "c" * 64,
    }
    prediction = ledger.prediction_record_v2(
        mode="forward_live",
        symbol="7203",
        market="JP",
        issued_at=CUTOFF,
        horizon="5d",
        target_type="scenario",
        forecast_value="sideways_stabilization",
        truth_ref=truth_ref,
        maturity=maturity,
        engine_id="argus-round2-fixture",
        engine_version="13.0",
        build_sha="a" * 40,
        evaluation_policy=policy,
        now_iso=CUTOFF,
        candidate_action="",
        evidence_refs=[observation["observationId"]],
    )
    reversal = sho.build_reversal_engine(
        cutoff=CUTOFF,
        analysis_instrument=INSTRUMENT,
        downside_background="MIXED",
    )
    assert truth.verify_decision_snapshot(snapshot)[0]
    assert ledger.verify_prediction_record_v2(prediction)
    sho.validate_reversal_artifact(reversal)
    return snapshot, prediction, reversal, policy


def complete_request(*, position="HELD", constraint="NONE", include_policy=True):
    snapshot, prediction, reversal, prediction_policy = canonical_artifacts()
    selection = snapshot["selections"][0]
    selected = selection["selected"]["observation"]
    axis = reversal["reversalAxis"]
    value = {
        "schemaVersion": "single-decision-authority-input-v2",
        "subject": copy.deepcopy(SUBJECT),
        "decisionAt": DECISION_AT,
        "informationCutoffAt": CUTOFF,
        "marketTruth": {
            "status": "AVAILABLE",
            "schemaVersion": snapshot["schemaVersion"],
            "snapshotId": snapshot["snapshotId"],
            "observationId": selected["observationId"],
            "observedAt": selected["observedAt"],
            "knownAt": selected["knownAt"],
            "policyId": truth.AUTHORITY_POLICY_ID,
            "policySha256": canonical_sha(truth.repository_authority_policy()),
        },
        "predictionLedger": {
            "status": "AVAILABLE",
            "schemaVersion": prediction["schemaVersion"],
            "contextId": prediction["id"],
            "mode": "FORWARD_LIVE",
            "asOf": prediction["issuedAt"],
            "policyId": prediction_policy["policyId"],
            "policySha256": canonical_sha(prediction_policy),
        },
        "sho": {
            "status": "AVAILABLE",
            "schemaVersion": reversal["schemaVersion"],
            "artifactId": reversal["artifactId"],
            "asOf": CUTOFF,
            "policyId": sho.SHO_REGISTRY_VERSION,
            "policySha256": sho.SHO_REGISTRY_SHA256,
            "state": axis["state"],
            "validationStatus": axis["validationStatus"],
            "primitiveFactorIds": [],
            "targets": [],
            "invalidation": None,
        },
        "riskKernel": risk_kernel(constraint),
        "contextEvidence": [{
            "evidenceRef": "event:calendar-clear",
            "primitiveFactorId": "event.calendar_clear",
            "sourceKind": "EVENT",
            "constraint": "NONE",
            "status": "ACTIVE",
            "observedAt": "2026-08-14T01:00:02Z",
        }],
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
    if include_policy:
        value["authorityPolicy"] = dict(SINGLE_DECISION_AUTHORITY_V2_POLICY)
    return value, (snapshot, prediction, reversal)


def admitted_request(**kwargs):
    request, artifacts = complete_request(**kwargs)
    return verify_decision_evidence(
        request,
        market_truth_artifact=artifacts[0],
        prediction_ledger_artifact=artifacts[1],
        sho_artifact=artifacts[2],
    )


class SingleDecisionTests(unittest.TestCase):
    def test_policy_is_repository_pinned_and_omission_uses_canonical(self):
        with self.assertRaises(TypeError):
            SINGLE_DECISION_AUTHORITY_V2_POLICY["policyId"] = "caller-policy"
        request, artifacts = complete_request(include_policy=False)
        verified = verify_decision_evidence(
            request,
            market_truth_artifact=artifacts[0],
            prediction_ledger_artifact=artifacts[1],
            sho_artifact=artifacts[2],
        )
        self.assertEqual(verified["authorityPolicy"], dict(SINGLE_DECISION_AUTHORITY_V2_POLICY))
        wrong = copy.deepcopy(dict(verified))
        wrong["authorityPolicy"]["policySha256"] = "f" * 64
        with self.assertRaises(SingleDecisionValidationError):
            verify_decision_evidence(
                wrong,
                market_truth_artifact=artifacts[0],
                prediction_ledger_artifact=artifacts[1],
                sho_artifact=artifacts[2],
            )

    def test_plain_objects_and_caller_buy_boolean_never_execute(self):
        request, _ = complete_request()
        request["sho"]["validationStatus"] = "VALIDATED"
        request["sho"]["buyEligible"] = True
        result = evaluate_single_decision_authority(request)
        self.assertEqual((result["status"], result["primaryAction"]), ("DATA_GATED", "WAIT"))
        with self.assertRaises(SingleDecisionValidationError):
            validate_single_decision_input_v2(request)

    def test_verified_artifacts_allow_deterministic_non_buy_actions(self):
        cases = (
            (admitted_request(position="HELD"), "HOLD"),
            (admitted_request(position="NOT_HELD"), "WAIT"),
            (admitted_request(position="HELD", constraint="REDUCE_RISK"), "REDUCE"),
            (admitted_request(position="HELD", constraint="EXIT_RISK"), "EXIT"),
        )
        observed = []
        for value, expected in cases:
            result = evaluate_single_decision_authority(value)
            observed.append(result["primaryAction"])
            self.assertEqual(result["status"], "EVALUATED")
            self.assertEqual(result["primaryAction"], expected)
            self.assertRegex(result["verifiedEvidenceBundleId"], r"^vdeb-[0-9a-f]{64}$")
            validate_single_decision_result_v2(result)
        self.assertNotIn("BUY", observed)
        self.assertEqual(set(PRIMARY_ACTIONS), {"BUY", "HOLD", "WAIT", "REDUCE", "EXIT"})

    def test_real_artifact_fake_reference_matrix_fails_closed(self):
        request, artifacts = complete_request()
        cases = []
        fake_sho = copy.deepcopy(request)
        fake_sho["sho"]["artifactId"] = "sho-reversal-" + "1" * 64
        cases.append(fake_sho)
        fake_market = copy.deepcopy(request)
        fake_market["marketTruth"]["snapshotId"] = "mds-" + "2" * 32
        cases.append(fake_market)
        for hostile in cases:
            with self.assertRaises(SingleDecisionValidationError):
                verify_decision_evidence(
                    hostile,
                    market_truth_artifact=artifacts[0],
                    prediction_ledger_artifact=artifacts[1],
                    sho_artifact=artifacts[2],
                )
            self.assertEqual(evaluate_single_decision_authority(hostile)["primaryAction"], "WAIT")

    def test_missing_backing_and_tampered_artifacts_fail_closed(self):
        request, artifacts = complete_request()
        with self.assertRaises(SingleDecisionValidationError):
            verify_decision_evidence(request)

        stale_digest = copy.deepcopy(artifacts[0])
        stale_digest["qualitySummary"]["missingRequiredCount"] = 99
        with self.assertRaises(SingleDecisionValidationError):
            verify_decision_evidence(
                request,
                market_truth_artifact=stale_digest,
                prediction_ledger_artifact=artifacts[1],
                sho_artifact=artifacts[2],
            )

        # A byte-identical, self-consistent clone still has no canonical
        # producer capability.  Content addressing proves identity only after
        # authority admission; it cannot mint authority by itself.
        for index in range(3):
            cloned = [artifacts[0], artifacts[1], artifacts[2]]
            cloned[index] = dict(cloned[index])
            with self.assertRaises(SingleDecisionValidationError):
                verify_decision_evidence(
                    request,
                    market_truth_artifact=cloned[0],
                    prediction_ledger_artifact=cloned[1],
                    sho_artifact=cloned[2],
                )

        recomputed_attacker = copy.deepcopy(request)
        recomputed_attacker["sho"]["artifactId"] = "sho-reversal-" + "3" * 64
        recomputed_attacker["sho"]["validationStatus"] = "VALIDATED"
        recomputed_attacker["sho"]["buyEligible"] = True
        self.assertEqual(evaluate_single_decision_authority(recomputed_attacker)["primaryAction"], "WAIT")

    def test_unvalidated_and_data_gated_sho_cannot_be_upgraded(self):
        verified = admitted_request(position="NOT_HELD")
        self.assertEqual(verified["sho"]["validationStatus"], "UNVALIDATED")
        self.assertEqual(evaluate_single_decision_authority(verified)["primaryAction"], "WAIT")
        hostile = copy.deepcopy(dict(verified))
        hostile["sho"]["validationStatus"] = "VALIDATED"
        hostile["sho"]["buyEligible"] = True
        self.assertEqual(evaluate_single_decision_authority(hostile)["primaryAction"], "WAIT")

    def test_missing_artifacts_builder_is_verified_and_deterministic(self):
        value = build_data_gated_input_v2(
            subject=SUBJECT,
            decision_at=DECISION_AT,
            information_cutoff_at=CUTOFF,
        )
        first = evaluate_single_decision_authority(value)
        second_value = build_data_gated_input_v2(
            subject=SUBJECT,
            decision_at=DECISION_AT,
            information_cutoff_at=CUTOFF,
        )
        second = evaluate_single_decision_authority(second_value)
        self.assertEqual(first, second)
        self.assertEqual((first["status"], first["primaryAction"]), ("DATA_GATED", "WAIT"))
        self.assertEqual(
            first["verifiedEvidenceBundleId"],
            "vdeb-a349db74bfcdc2ddfdeec558237009ce2f26d5eb7a8db49e374c1a78653bf56b",
        )
        self.assertEqual(
            first["decisionId"],
            "sda-3168a78e52b8bfc1ad3b85f31be6cae7344288606f9d39b214bfe486bfe6391b",
        )

        cloned = copy.deepcopy(dict(value))
        cloned["riskKernel"] = dict(value["riskKernel"])
        with self.assertRaises(SingleDecisionValidationError):
            verify_decision_evidence(cloned)

    def test_python_typescript_missing_artifact_parity_vector(self):
        value = build_data_gated_input_v2(
            subject={"kind": "ASSET", "instrumentId": "7203", "market": "JP", "horizon": "FIVE_DAY"},
            decision_at="2026-08-16T09:00:00Z",
            information_cutoff_at="2026-08-16T08:59:00Z",
        )
        result = evaluate_single_decision_authority(value)
        adapter = build_prediction_ledger_v2_adapter(result)
        self.assertEqual(result["verifiedEvidenceBundleId"],
                         "vdeb-ab78d51a78706f53606d546c3ff22e3a400bdce89e110ef6419f8c23faef37d2")
        self.assertEqual(result["decisionId"],
                         "sda-b45ead9150d861e72832c0f239e2471d49a8952a9a0a148d0bb6c8d882fa68b0")
        self.assertEqual(adapter["adapterId"],
                         "pla-7291ee01bd17dfa638d53a3dfcb7da5529dfd9e1feaa71a6658b1dba4307adad")

    def test_owner_privacy_and_unknown_owner_remain_fail_closed(self):
        private = admitted_request()
        private["ownerContext"]["quantity"] = 100
        self.assertEqual(evaluate_single_decision_authority(private)["primaryAction"], "WAIT")
        unknown = build_data_gated_input_v2(
            subject=SUBJECT,
            decision_at=DECISION_AT,
            information_cutoff_at=CUTOFF,
            owner_context=owner("UNKNOWN", "UNKNOWN"),
        )
        result = evaluate_single_decision_authority(unknown)
        self.assertEqual(result["primaryAction"], "WAIT")
        self.assertIn("owner_context_unknown", result["missingReasonCodes"])

    def test_ai_and_legacy_challenges_cannot_change_verified_action(self):
        baseline = admitted_request()
        expected = evaluate_single_decision_authority(baseline)["primaryAction"]
        request, artifacts = complete_request()
        request["challengeEvidence"] = [{
            "challengeId": "ai.challenge-1",
            "sourceKind": "AI",
            "status": "AVAILABLE",
            "asOf": DECISION_AT,
            "proposedAction": "BUY",
            "dissentReasonCodes": ["ai_buy_dissent"],
            "evidenceRefs": ["ai:challenge-1"],
        }]
        verified = verify_decision_evidence(
            request,
            market_truth_artifact=artifacts[0],
            prediction_ledger_artifact=artifacts[1],
            sho_artifact=artifacts[2],
        )
        result = evaluate_single_decision_authority(verified)
        self.assertEqual(result["primaryAction"], expected)
        self.assertIn("ai_proposed_action_ignored", result["dissentReasonCodes"])

        advisory, advisory_artifacts = complete_request()
        advisory["contextEvidence"][0]["constraint"] = "WAIT_REQUIRED"
        advisory_result = evaluate_single_decision_authority(verify_decision_evidence(
            advisory,
            market_truth_artifact=advisory_artifacts[0],
            prediction_ledger_artifact=advisory_artifacts[1],
            sho_artifact=advisory_artifacts[2],
        ))
        self.assertEqual(advisory_result["primaryAction"], expected)
        self.assertIn(
            "context_constraint_advisory_only",
            advisory_result["dissentReasonCodes"],
        )

    def test_ledger_adapter_requires_runtime_verified_result(self):
        result = evaluate_single_decision_authority(admitted_request())
        adapter = build_prediction_ledger_v2_adapter(result)
        self.assertEqual(adapter["decisionId"], result["decisionId"])
        self.assertEqual(adapter["verifiedEvidenceBundleId"], result["verifiedEvidenceBundleId"])
        self.assertEqual(adapter["adapterId"], compute_prediction_adapter_id(adapter))
        fabricated = copy.deepcopy(dict(result))
        fabricated["decisionId"] = compute_single_decision_id(fabricated)
        with self.assertRaises(SingleDecisionValidationError):
            build_prediction_ledger_v2_adapter(fabricated)


if __name__ == "__main__":
    unittest.main()


class DailyBasisFreshnessTests(unittest.TestCase):
    """v13.5.35 (owner discussion + external review #8): a FIVE_DAY decision
    runs on the latest COMPLETED session close. In mixed states (some
    reference degraded), DELAYED quality must not ADD a freshness gate code;
    STALE/UNKNOWN still must. (When every reference is AVAILABLE the verifier
    already enforces COMPLETE/FRESH, so the mixed state is the only shape
    where this gate is reachable.)"""

    def _decide_with_freshness(self, freshness):
        from argus_single_decision import (
            MISSING_SHO_REFERENCE, evaluate_single_decision_authority)
        request, artifacts = complete_request()
        request["sho"] = {**dict(MISSING_SHO_REFERENCE),
                          "primitiveFactorIds": [], "targets": [],
                          "invalidation": None}
        request["quality"] = {"status": "PARTIAL", "freshness": freshness,
                              "missingReasonCodes": ["sho_missing"],
                              "conflictReasonCodes": []}
        verified = verify_decision_evidence(
            request,
            market_truth_artifact=artifacts[0],
            prediction_ledger_artifact=artifacts[1],
            sho_artifact=None)
        return evaluate_single_decision_authority(verified)

    def test_delayed_official_close_adds_no_freshness_gate(self):
        result = self._decide_with_freshness("DELAYED")
        self.assertFalse([c for c in result["missingReasonCodes"]
                          if c.startswith("freshness_")],
                         result["missingReasonCodes"])

    def test_stale_and_unknown_still_gate(self):
        for freshness in ("STALE", "UNKNOWN"):
            result = self._decide_with_freshness(freshness)
            self.assertIn(f"freshness_{freshness.lower()}",
                          result["missingReasonCodes"])
