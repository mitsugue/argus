"""v12.3.2 formal Gemini benchmark safety and reproducibility tests."""
import copy
import json
import os
import sys
import types
import unittest
from unittest import mock

import argus_cost_policy as cost
import argus_remote_journal as remote_journal
import argus_research_benchmark as bench
import argus_state_journal as state_journal

_moomoo = types.ModuleType("moomoo")
_moomoo.OpenQuoteContext = lambda *a, **k: None
_moomoo.OpenSecTradeContext = lambda *a, **k: None
_moomoo.RET_OK = 0
sys.modules.setdefault("moomoo", _moomoo)
import scanner


NOW = "2026-07-20T03:00:00Z"


def _pricing():
    return {"gemini-fixed": {"in": 1.25, "out": 10.0},
            "argus-fixed": {"in": 1.25, "out": 10.0},
            "referee-fixed": {"in": 1.25, "out": 10.0}}


def _dry(**kw):
    args = dict(gemini_model="gemini-fixed", argus_model="argus-fixed",
                evaluator_model="referee-fixed", pricing=_pricing(),
                usd_jpy_ceiling=160, grounding_usd_per_call=0.04,
                existing_budget_usd=5.0, providers_configured=True)
    args.update(kw)
    return bench.estimate_cost(**args)


def _axes(value):
    return {key: value for key in bench.RUBRIC_WEIGHTS}


def _claims(case, source=None):
    src = source or ((case.get("expectedPrimarySources") or ["official_release"])[0])
    return [{"titleJa": "verified", "url": "https://example.test/source",
             "publishedAt": case["informationCutoff"], "sourceId": src,
             "fabricated": False}]


class DatasetTests(unittest.TestCase):
    def test_frozen_dataset_has_exact_split_and_hash(self):
        check = bench.validate_dataset()
        self.assertTrue(check["valid"], check["errors"])
        self.assertEqual(check["caseCount"], 18)
        self.assertEqual(check["calibrationCount"], 6)
        self.assertEqual(check["holdoutCount"], 12)
        self.assertEqual(check["datasetHash"], bench.DATASET_HASH)
        self.assertEqual(bench.frozen_dataset()["datasetHash"], bench.DATASET_HASH)

    def test_all_cases_have_cutoff_source_and_leakage_contract(self):
        required = {"caseId", "category", "question", "asOf",
                    "informationCutoff", "permittedSources",
                    "expectedPrimarySources", "leakageGuard",
                    "scoringRubricVersion"}
        for case in bench.FORMAL_DATASET:
            self.assertTrue(required.issubset(case))
            self.assertEqual(case["asOf"], case["informationCutoff"])
            self.assertEqual(case["leakageGuard"], "future_sources_forbidden")

    def test_execution_order_freezes_calibration_before_holdout(self):
        plan = bench.execution_plan()
        self.assertEqual([x["phase"] for x in plan[:6]], ["calibration"] * 6)
        self.assertEqual([x["phase"] for x in plan[6:]], ["holdout"] * 12)

    def test_blind_order_is_repeatable_and_varied(self):
        first = [bench.blind_order("b1", c["caseId"])["A"]
                 for c in bench.FORMAL_DATASET]
        second = [bench.blind_order("b1", c["caseId"])["A"]
                  for c in bench.FORMAL_DATASET]
        self.assertEqual(first, second)
        self.assertEqual(set(first), {"argus", "gemini"})


class BudgetAndModeTests(unittest.TestCase):
    def test_dry_run_is_bounded_and_hashed(self):
        dry = _dry()
        self.assertEqual(dry["status"], "ready")
        self.assertLessEqual(dry["estimatedCostJpy"], dry["effectiveBudgetJpy"])
        self.assertEqual(dry["maximumCalls"], 72)
        self.assertLessEqual(dry["inputTokensPerCall"]
                             + dry["outputTokensPerCall"],
                             dry["maximumTokensPerCall"])
        self.assertEqual(dry["dryRunHash"], bench.digest(
            {k: v for k, v in dry.items() if k != "dryRunHash"}))

    def test_budget_and_provider_block_before_execution(self):
        self.assertEqual(_dry(existing_budget_usd=0.01)["status"], "budget_blocked")
        self.assertEqual(_dry(providers_configured=False)["status"], "provider_blocked")

    def test_research_mode_is_manual_confirmation_and_scope_only(self):
        st = cost.default_state("RESEARCH_BENCHMARK")
        auto = cost.authorize(st, provider="gemini", purpose="research_benchmark",
                              automatic=True, confirmation=True,
                              estimated_cost_usd=0.1, estimated_tokens=100)
        wrong = cost.authorize(st, provider="gemini", purpose="osint_research",
                               automatic=False, confirmation=True,
                               estimated_cost_usd=0.1, estimated_tokens=100)
        allowed = cost.authorize(st, provider="gemini", purpose="research_benchmark",
                                 automatic=False, confirmation=True,
                                 estimated_cost_usd=0.1, estimated_tokens=100)
        self.assertFalse(auto["allowed"])
        self.assertFalse(wrong["allowed"])
        self.assertTrue(allowed["allowed"])
        self.assertEqual(cost.default_state()["mode"], "DETERMINISTIC")

    def test_scheduled_begin_rejected_and_holdout_one_shot(self):
        dry = _dry()
        state = bench.default_state()
        rejected = bench.begin(state, dry_run=dry, benchmark_id="b1",
                               trigger_source="schedule", confirmed=True,
                               started_at=NOW)
        self.assertFalse(rejected["allowed"])
        begun = bench.begin(state, dry_run=dry, benchmark_id="b1",
                            trigger_source="manual", confirmed=True,
                            started_at=NOW)
        self.assertTrue(begun["allowed"])
        self.assertIsNone(begun["state"]["holdoutConsumedBy"])
        consumed = bench.consume_holdout(begun["state"], benchmark_id="b1")
        self.assertTrue(consumed["allowed"])
        failed = bench.fail_closed(consumed["state"], status="provider_blocked",
                                   completed_at=NOW)
        again = bench.begin(failed, dry_run=dry, benchmark_id="b2",
                            trigger_source="manual", confirmed=True,
                            started_at=NOW)
        self.assertEqual(again["status"], "holdout_already_consumed")


class ScoringTests(unittest.TestCase):
    def test_future_leakage_fabrication_and_missing_source_penalized(self):
        case = copy.deepcopy(bench.FORMAL_DATASET[0])
        clean = bench.score_answer(axes=_axes(90), claims=_claims(case), case=case)
        bad_claim = {"titleJa": "bad", "publishedAt": "2027-01-01T00:00:00Z",
                     "fabricated": True}
        bad = bench.score_answer(axes=_axes(90), claims=[bad_claim], case=case)
        self.assertGreater(clean["score"], bad["score"])
        self.assertEqual(bad["futureLeakageCount"], 1)
        self.assertEqual(bad["criticalFabrications"], 1)
        self.assertFalse(bad["evidenceGatePassed"])
        self.assertFalse(bad["temporalIntegrityGatePassed"])

    def _result(self, benchmark_id, case, argus_axis=90, gemini_axis=40):
        order = bench.blind_order(benchmark_id, case["caseId"])
        axes = {label: _axes(argus_axis if provider == "argus" else gemini_axis)
                for label, provider in order.items()}
        return bench.case_result(
            benchmark_id=benchmark_id, case=case,
            evaluator_axes_by_label=axes,
            claims_by_provider={"argus": _claims(case),
                                "gemini": _claims(case)})

    def test_valid_holdout_can_achieve_only_all_gates(self):
        bid = "formal-good"
        results = [self._result(bid, c) for c in bench.FORMAL_DATASET]
        begun = bench.begin(bench.default_state(), dry_run=_dry(),
                            benchmark_id=bid, trigger_source="manual",
                            confirmed=True, started_at=NOW)["state"]
        done = bench.finalize(
            state=begun, benchmark_id=bid, research_epoch="epoch",
            code_sha="a" * 40, models={"gemini": "g", "argus": "a",
                                        "evaluator": "e", "argusVersion": "12.3.1"},
            provider_settings={"temperature": 0,
                               "costStatus": "conservative_estimate"},
            total_cost_jpy=100,
            case_results=results, completed_at=NOW)
        self.assertTrue(done["ok"])
        self.assertEqual(done["status"], "achieved")
        self.assertTrue(done["result"]["twoXClaimAllowed"])
        self.assertGreaterEqual(done["result"]["medianRatio"], 2.0)
        self.assertGreaterEqual(done["result"]["geometricMeanRatio"], 1.8)
        self.assertEqual(done["state"]["mode"], "DETERMINISTIC")

    def test_not_achieved_is_valid_and_not_relabelled(self):
        bid = "formal-honest"
        results = [self._result(bid, c, 65, 60) for c in bench.FORMAL_DATASET]
        begun = bench.begin(bench.default_state(), dry_run=_dry(),
                            benchmark_id=bid, trigger_source="manual",
                            confirmed=True, started_at=NOW)["state"]
        done = bench.finalize(
            state=begun, benchmark_id=bid, research_epoch="epoch",
            code_sha="b" * 40, models={"gemini": "g", "argus": "a",
                                        "evaluator": "e", "argusVersion": "12.3.1"},
            provider_settings={"costStatus": "conservative_estimate"},
            total_cost_jpy=100, case_results=results, completed_at=NOW)
        self.assertTrue(done["ok"])
        self.assertEqual(done["status"], "not_achieved")
        self.assertFalse(done["result"]["twoXClaimAllowed"])
        self.assertIn("NOT ACHIEVED", bench.public_status(done["state"])["noteJa"])

    def test_incomplete_or_over_budget_is_invalid(self):
        bid = "formal-invalid"
        results = [self._result(bid, c) for c in bench.FORMAL_DATASET[:-1]]
        begun = bench.begin(bench.default_state(), dry_run=_dry(),
                            benchmark_id=bid, trigger_source="manual",
                            confirmed=True, started_at=NOW)["state"]
        done = bench.finalize(
            state=begun, benchmark_id=bid, research_epoch="epoch",
            code_sha="c" * 40, models={}, provider_settings={},
            total_cost_jpy=2001, case_results=results, completed_at=NOW)
        self.assertFalse(done["ok"])
        self.assertEqual(done["status"], "invalid")


class RouteTests(unittest.TestCase):
    def setUp(self):
        self.old_token = scanner._ARGUS_ADMIN_TOKEN
        self.old_state = copy.deepcopy(scanner._FORMAL_BENCHMARK)
        scanner._ARGUS_ADMIN_TOKEN = "test-admin"

    def tearDown(self):
        scanner._ARGUS_ADMIN_TOKEN = self.old_token
        scanner._FORMAL_BENCHMARK.clear()
        scanner._FORMAL_BENCHMARK.update(self.old_state)

    def test_get_is_read_only_and_public_safe(self):
        with scanner.app.test_client() as client, \
                mock.patch.object(scanner, "_gemini_osint") as gemini, \
                mock.patch.object(scanner, "_gpt_osint") as gpt:
            response = client.get("/api/argus/research-benchmark")
        self.assertEqual(response.status_code, 200)
        gemini.assert_not_called(); gpt.assert_not_called()
        body = response.get_data(as_text=True)
        self.assertNotIn("GEMINI_API_KEY", body)
        self.assertNotIn("OPENAI_API_KEY", body)

    def test_claim_source_validation_fails_closed(self):
        case = bench.FORMAL_DATASET[0]
        valid = scanner._formal_claims({"claims": [{
            "titleJa": "source", "url": "https://example.test/a",
            "sourceName": "tdnet", "publishedAt": case["informationCutoff"]}]}, case)
        invalid = scanner._formal_claims({"claims": [{
            "titleJa": "source", "url": "http://example.test/a",
            "sourceName": "unapproved", "publishedAt": case["informationCutoff"]}]}, case)
        self.assertTrue(valid[0]["sourceValidated"])
        self.assertFalse(invalid[0]["sourceValidated"])
        self.assertFalse(bench.score_answer(
            axes=_axes(90), claims=invalid, case=case)["evidenceGatePassed"])

    def test_formal_journal_event_is_public_safe_and_remote_critical(self):
        ev = state_journal.event(
            event_type="research_benchmark_completed",
            aggregate_type="research_benchmark", aggregate_id="b1",
            sequence=1, occurred_at=NOW,
            payload={"classification": "not_achieved"},
            origin="admin_validation")
        self.assertTrue(state_journal.verify(ev))
        section = remote_journal.snapshot_journal_section(
            events=[ev], meta={}, now_iso=NOW)
        self.assertEqual(section["opsJournal"], [ev])
        self.assertEqual(section["integrityManifest"]["criticalityByEventId"]
                         [ev["eventId"]], "critical")

    def test_dry_run_requires_manual_and_makes_no_provider_call(self):
        headers = {"X-ARGUS-ADMIN-TOKEN": "test-admin"}
        with scanner.app.test_client() as client, \
                mock.patch.object(scanner, "_gemini_osint") as gemini, \
                mock.patch.object(scanner, "_gpt_osint") as gpt:
            denied = client.post("/api/argus/admin/research-benchmark/dry-run",
                                 headers=headers, json={"triggerSource": "schedule"})
            dry = client.post("/api/argus/admin/research-benchmark/dry-run",
                              headers=headers, json={"triggerSource": "manual"})
        self.assertEqual(denied.status_code, 400)
        self.assertEqual(dry.status_code, 200)
        gemini.assert_not_called(); gpt.assert_not_called()

    def test_execute_requires_matching_dry_run_and_never_from_schedule(self):
        headers = {"X-ARGUS-ADMIN-TOKEN": "test-admin"}
        scanner._FORMAL_BENCHMARK["dryRun"] = _dry()
        with scanner.app.test_client() as client:
            mismatch = client.post("/api/argus/admin/research-benchmark/execute",
                                   headers=headers,
                                   json={"triggerSource": "schedule", "confirm": True,
                                         "dryRunHash": "wrong"})
        self.assertEqual(mismatch.status_code, 409)

        dry = _dry()
        scanner._FORMAL_BENCHMARK.clear()
        scanner._FORMAL_BENCHMARK.update(bench.default_state())
        scanner._FORMAL_BENCHMARK["dryRun"] = dry
        with scanner.app.test_client() as client:
            scheduled = client.post(
                "/api/argus/admin/research-benchmark/execute", headers=headers,
                json={"triggerSource": "schedule", "confirm": True,
                      "dryRunHash": dry["dryRunHash"]})
        self.assertEqual(scheduled.status_code, 409)
        self.assertEqual(scheduled.get_json()["status"], "scheduled_execution_rejected")

    def test_worker_restores_deterministic_and_completes_once(self):
        dry = _dry()
        bid = "worker-test"
        started = bench.begin(
            bench.default_state(), dry_run=dry, benchmark_id=bid,
            trigger_source="manual", confirmed=True, started_at=NOW)["state"]
        old_cost = copy.deepcopy(scanner._COST_POLICY)
        scanner._FORMAL_BENCHMARK.clear()
        scanner._FORMAL_BENCHMARK.update(started)
        scanner._COST_POLICY.clear()
        scanner._COST_POLICY.update(cost.default_state("RESEARCH_BENCHMARK"))

        def answer(*args, **kwargs):
            return ({"claims": [{"titleJa": "source", "url": "https://example.test/a",
                                  "publishedAt": "2025-01-01T00:00:00Z",
                                  "sourceName": "official_release"}]}, "ok")

        def evaluate(case, benchmark_id, claims):
            order = bench.blind_order(benchmark_id, case["caseId"])
            return ({label: _axes(80 if provider == "argus" else 60)
                     for label, provider in order.items()}, "ok")

        try:
            with mock.patch.object(scanner, "_gemini_osint", side_effect=answer), \
                    mock.patch.object(scanner, "_gpt_osint", side_effect=answer), \
                    mock.patch.object(scanner, "_formal_blind_evaluate",
                                      side_effect=evaluate), \
                    mock.patch.object(scanner, "_osint_persist"), \
                    mock.patch.object(scanner, "_journal"):
                scanner._formal_benchmark_worker(bid, dry)
            self.assertEqual(scanner._COST_POLICY["mode"], "DETERMINISTIC")
            self.assertEqual(scanner._FORMAL_BENCHMARK["runningBenchmarkId"], None)
            self.assertEqual(len(scanner._FORMAL_BENCHMARK["results"]), 1)
            self.assertEqual(len(scanner._FORMAL_BENCHMARK["results"][0]["caseResults"]), 18)
        finally:
            scanner._COST_POLICY.clear(); scanner._COST_POLICY.update(old_cost)


if __name__ == "__main__":
    unittest.main()
