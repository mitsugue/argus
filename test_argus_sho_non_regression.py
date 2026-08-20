"""Hostile non-regression tests for SHO D01-D07 independence.

These tests deliberately use compact, content-addressed evidence artifacts so
that they exercise the production SHO consumer seam without inventing an
action authority or reducing the seven evidence families to votes.
"""
import ast
import inspect
import unittest
from unittest import mock

import argus_sho as sho


CUTOFF = "2026-08-15T00:00:00Z"
FAMILIES = tuple(f"D0{index}" for index in range(1, 8))


def _family_row(family, state):
    if state == "TRIGGERED":
        status, condition, validation = "AVAILABLE", True, "VALIDATED"
    elif state == "NOT_TRIGGERED":
        status, condition, validation = "AVAILABLE", False, "VALIDATED"
    elif state == "DATA_GATED":
        status, condition, validation = "DATA_GATED", None, "DATA_GATED"
    elif state == "UNKNOWN":
        status, condition, validation = "UNKNOWN", None, "UNVALIDATED"
    else:
        raise ValueError("invalid_test_state")
    return {
        "family": family,
        "propositionId": f"SHO-{family}-ORIGINAL",
        "lineage": "SHO_ORIGINAL",
        "importance": "P0" if family == "D01" else "UNSPECIFIED",
        "status": status,
        "conditionMet": condition,
        "validationStatus": validation,
    }


def _evidence_artifact(states):
    families = {
        family: _family_row(family, states.get(family, "UNKNOWN"))
        for family in FAMILIES
    }
    body = {
        "schemaVersion": sho.SHO_EVIDENCE_SCHEMA,
        "canonicalRfcSha256": sho.CANONICAL_SHO_RFC_SHA256,
        "registrySha256": sho.SHO_REGISTRY_SHA256,
        "informationCutoff": CUTOFF,
        "families": families,
        "action": None,
        "automaticAiCalls": 0,
    }
    return {**body, "artifactId": "sho-evidence-" + sho._sha256(body)}


def _projection(states):
    return sho.project_today_sda_safe(
        cutoff=CUTOFF, evidence=_evidence_artifact(states))


def _validated_triggers(projection):
    return sorted(
        family for family, row in projection["families"].items()
        if row["conditionMet"] is True
        and row["validationStatus"] == "VALIDATED"
    )


class ShoIndependentFamilyHostileTest(unittest.TestCase):
    def test_d01_triggered_with_six_unknown_survives(self):
        projection = _projection({"D01": "TRIGGERED"})
        self.assertEqual(_validated_triggers(projection), ["D01"])
        registry = sho.sealed_proposition_registry()
        d01 = next(row for row in registry["propositions"]
                   if row["id"] == "SHO-D01-ORIGINAL")
        self.assertEqual(d01["importance"], "P0")
        self.assertEqual(
            projection["families"]["D01"]["validationStatus"], "VALIDATED")
        for family in FAMILIES[1:]:
            self.assertEqual(projection["families"][family]["status"], "UNKNOWN")
            self.assertIsNone(projection["families"][family]["conditionMet"])
        self.assertFalse(projection["actionAuthority"])
        self.assertIsNone(projection["action"])

    def test_d01_and_d03_confluence_survives_without_other_families(self):
        projection = _projection({"D01": "TRIGGERED", "D03": "TRIGGERED"})
        self.assertEqual(_validated_triggers(projection), ["D01", "D03"])
        registry = sho.sealed_proposition_registry()
        d03 = next(row for row in registry["propositions"]
                   if row["id"] == "SHO-D03-ORIGINAL")
        self.assertEqual(d03["importance"], "UNSPECIFIED")
        self.assertTrue(all(
            projection["families"][family]["conditionMet"] is None
            for family in ("D02", "D04", "D05", "D06", "D07")))

    def test_validated_d06_triggered_alone_survives(self):
        projection = _projection({"D06": "TRIGGERED"})
        self.assertEqual(_validated_triggers(projection), ["D06"])
        self.assertEqual(
            projection["families"]["D06"]["validationStatus"], "VALIDATED")

    def test_three_triggered_four_not_triggered_is_not_a_seven_of_seven_gate(self):
        projection = _projection({
            "D01": "TRIGGERED", "D02": "NOT_TRIGGERED",
            "D03": "TRIGGERED", "D04": "NOT_TRIGGERED",
            "D05": "NOT_TRIGGERED", "D06": "TRIGGERED",
            "D07": "NOT_TRIGGERED",
        })
        self.assertEqual(_validated_triggers(projection), ["D01", "D03", "D06"])
        self.assertEqual(sum(
            row["conditionMet"] is False
            for row in projection["families"].values()), 4)

    def test_one_triggered_six_data_gated_never_collapses_unknown_to_false(self):
        states = {family: "DATA_GATED" for family in FAMILIES}
        states["D01"] = "TRIGGERED"
        projection = _projection(states)
        self.assertEqual(_validated_triggers(projection), ["D01"])
        for family in FAMILIES[1:]:
            row = projection["families"][family]
            self.assertEqual(row["status"], "DATA_GATED")
            self.assertEqual(row["validationStatus"], "DATA_GATED")
            self.assertIsNone(row["conditionMet"])
            self.assertIsNot(row["conditionMet"], False)

    def test_all_valid_not_triggered_has_no_sho_downside_trigger(self):
        projection = _projection({family: "NOT_TRIGGERED" for family in FAMILIES})
        self.assertEqual(_validated_triggers(projection), [])
        self.assertTrue(all(
            row["status"] == "AVAILABLE" and row["conditionMet"] is False
            for row in projection["families"].values()))

    def test_simultaneous_downside_and_reversal_keep_both_axes(self):
        def factor(condition):
            return {
                "status": "AVAILABLE", "conditionMet": condition,
                "details": {}, "validationStatus": "UNVALIDATED",
            }

        factors = {
            "bandWalkEnding": factor(True),
            "vixMacdDeadCross": factor(True),
            "sarBullishFlip": factor(True),
            "nikkeiMacdGoldenCross": factor(False),
            "rsiResistanceBreakout": factor(False),
            "bollingerMiddleReclaim": factor(True),
            "ma25Reclaim": factor(False),
            "ma5Ma25GoldenCross": factor(False),
            "reclaimFailure": factor(False),
        }
        evidence = {
            "artifactId": "sho-reversal-evidence-hostile",
            "factors": factors,
        }
        with mock.patch.object(sho, "reversal_evidence", return_value=evidence):
            artifact = sho.build_reversal_engine(
                cutoff=CUTOFF,
                analysis_instrument="NIKKEI_225_INDEX",
                downside_background="DOWNSIDE_TRIGGERED",
            )
        self.assertEqual(artifact["downsideAxis"], {
            "state": "DOWNSIDE_TRIGGERED", "computedIndependently": True})
        self.assertEqual(artifact["reversalAxis"]["state"], "CONFIRMED_ADVANCE")
        self.assertFalse(artifact["reversalAxis"]["slowDownsideVetoApplied"])
        self.assertIsNone(artifact["action"])

    def test_production_family_seams_contain_no_all_or_seven_count_gate(self):
        functions = (
            sho.evaluate_d01_d07,
            sho.project_today_sda_safe,
            sho.classify_reversal_state,
            sho.build_reversal_engine,
        )
        for function in functions:
            source = inspect.getsource(function)
            tree = ast.parse(source)
            self.assertNotIn("7/7", source)
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                    self.assertNotEqual(node.func.id, "all", function.__name__)
                if isinstance(node, ast.Compare):
                    constants = [child.value for child in ast.walk(node)
                                 if isinstance(child, ast.Constant)]
                    self.assertNotIn(7, constants, function.__name__)
                if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.And):
                    text = ast.unparse(node)
                    referenced = {family for family in FAMILIES if family in text}
                    self.assertNotEqual(referenced, set(FAMILIES), function.__name__)

        module_tree = ast.parse(inspect.getsource(sho))
        for node in ast.walk(module_tree):
            text = ast.unparse(node) if isinstance(
                node, (ast.Call, ast.Compare, ast.BoolOp)) else ""
            normalized = text.lower()
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                    and node.func.id == "all":
                self.assertNotIn("famil", normalized, text)
            if isinstance(node, ast.Compare) and "famil" in normalized:
                constants = [child.value for child in ast.walk(node)
                             if isinstance(child, ast.Constant)]
                self.assertNotIn(7, constants, text)
            if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.And):
                referenced = {family for family in FAMILIES if family in text}
                self.assertNotEqual(referenced, set(FAMILIES), text)


if __name__ == "__main__":
    unittest.main()
