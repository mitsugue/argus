from __future__ import annotations

import copy
import unittest

from argus_risk_discipline import (
    RiskDisciplineValidationError,
    build_risk_kernel,
    compute_risk_kernel_id,
    validate_risk_kernel,
)


POLICY_SHA = "1" * 64


def request(*contributions):
    return {
        "schemaVersion": "argus-risk-discipline-input-v1",
        "subject": {"kind": "ASSET", "instrumentId": "7203", "market": "JP"},
        "asOf": "2026-08-16T09:00:00Z",
        "informationCutoffAt": "2026-08-16T08:59:00Z",
        "policy": {"policyId": "risk-discipline-v1", "policySha256": POLICY_SHA},
        "contributions": list(contributions),
    }


def row(
    evidence_ref,
    factor,
    *,
    source="MARKET",
    constraint="NONE",
    status="ACTIVE",
    severity="LOW",
    cap=9000,
):
    return {
        "evidenceRef": evidence_ref,
        "primitiveFactorId": factor,
        "sourceKind": source,
        "constraint": constraint,
        "status": status,
        "severity": severity,
        "confidenceCapBps": cap,
        "observedAt": "2026-08-16T08:58:00Z",
    }


class RiskDisciplineTests(unittest.TestCase):
    def test_duplicate_engines_are_one_factor_not_votes(self):
        value = request(
            row(
                "market:volatility-1",
                "volatility.regime",
                constraint="BLOCK_BUY",
                cap=7600,
            ),
            row(
                "sho:volatility-1",
                "volatility.regime",
                source="SHO",
                constraint="BLOCK_BUY",
                severity="MEDIUM",
                cap=7200,
            ),
        )
        kernel = build_risk_kernel(value)

        self.assertEqual(kernel["status"], "READY")
        self.assertEqual(kernel["constraint"], "BLOCK_BUY")
        self.assertEqual(kernel["confidenceCapBps"], 7200)
        self.assertEqual(len(kernel["primitiveFactors"]), 1)
        self.assertEqual(
            kernel["primitiveFactors"][0]["evidenceRefs"],
            ["market:volatility-1", "sho:volatility-1"],
        )
        self.assertFalse(kernel["finalActionAuthority"])
        self.assertTrue({"action", "finalAction", "primaryAction"}.isdisjoint(kernel))
        validate_risk_kernel(kernel)

    def test_correlated_disagreement_is_a_conflict_not_a_winner(self):
        kernel = build_risk_kernel(
            request(
                row("market:factor", "liquidity.stress", constraint="WAIT_REQUIRED"),
                row(
                    "scenario:factor",
                    "liquidity.stress",
                    source="SCENARIO",
                    constraint="EXIT_RISK",
                    severity="CRITICAL",
                ),
            )
        )

        self.assertEqual(kernel["status"], "DATA_GATED")
        self.assertEqual(kernel["constraint"], "WAIT_REQUIRED")
        self.assertEqual(kernel["confidenceCapBps"], 2500)
        self.assertEqual(kernel["primitiveFactors"][0]["status"], "CONFLICT")
        self.assertEqual(kernel["primitiveFactors"][0]["constraint"], "NONE")
        self.assertEqual(
            kernel["conflictReasonCodes"], ["risk_conflict.liquidity.stress"]
        )

    def test_safety_precedence_is_across_unique_factors(self):
        kernel = build_risk_kernel(
            request(
                row("event:block", "event.uncertainty", source="EVENT", constraint="BLOCK_BUY"),
                row(
                    "portfolio:reduce",
                    "portfolio.drawdown",
                    source="PORTFOLIO",
                    constraint="REDUCE_RISK",
                    severity="HIGH",
                    cap=6500,
                ),
            )
        )
        self.assertEqual(kernel["constraint"], "REDUCE_RISK")
        self.assertEqual(kernel["confidenceCapBps"], 6500)

    def test_missing_evidence_fails_closed(self):
        kernel = build_risk_kernel(
            request(
                row(
                    "discipline:risk-missing",
                    "risk.required_evidence",
                    source="DISCIPLINE",
                    status="MISSING",
                    severity="UNKNOWN",
                    cap=2500,
                )
            )
        )
        self.assertEqual(kernel["status"], "DATA_GATED")
        self.assertEqual(kernel["constraint"], "WAIT_REQUIRED")
        self.assertEqual(
            kernel["missingReasonCodes"], ["risk_missing.risk.required_evidence"]
        )

    def test_content_address_is_order_invariant_and_output_is_detached(self):
        first = row("event:a", "event.risk", source="EVENT", constraint="WAIT_REQUIRED")
        second = row("market:b", "trend.break", constraint="BLOCK_BUY")
        one = build_risk_kernel(request(first, second))
        two = build_risk_kernel(request(second, first))
        self.assertEqual(one, two)
        self.assertEqual(one["riskKernelId"], compute_risk_kernel_id(one))

        first["constraint"] = "EXIT_RISK"
        self.assertEqual(one["constraint"], "WAIT_REQUIRED")

    def test_rehashed_kernel_cannot_claim_constraint_without_factor_evidence(self):
        kernel = build_risk_kernel(request(
            row("market:risk", "market.selloff_risk",
                constraint="REDUCE_RISK", severity="HIGH", cap=6000)))
        kernel["primitiveFactors"] = []
        kernel["riskKernelId"] = compute_risk_kernel_id(kernel)
        with self.assertRaisesRegex(
                RiskDisciplineValidationError, "kernel.reasonCodes"):
            validate_risk_kernel(kernel)

    def test_closed_contract_rejects_private_or_future_fields(self):
        value = request(row("market:a", "trend.break"))
        value["ownerAccountId"] = "private-account"
        with self.assertRaises(RiskDisciplineValidationError):
            build_risk_kernel(value)

        value = request(row("market:a", "trend.break"))
        value["contributions"][0]["observedAt"] = "2026-08-16T09:00:00Z"
        with self.assertRaises(RiskDisciplineValidationError):
            build_risk_kernel(value)

    def test_kernel_tamper_is_detected(self):
        kernel = build_risk_kernel(request(row("market:a", "trend.break")))
        tampered = copy.deepcopy(kernel)
        tampered["confidenceCapBps"] -= 1
        with self.assertRaises(RiskDisciplineValidationError):
            validate_risk_kernel(tampered)


if __name__ == "__main__":
    unittest.main()
