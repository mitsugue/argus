import importlib.util
import pathlib
import unittest
from unittest import mock


PATH = pathlib.Path(__file__).parent / "scripts" / "run_formal_research_benchmark.py"
SPEC = importlib.util.spec_from_file_location("run_formal_research_benchmark", PATH)
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


class FormalBenchmarkRunnerTests(unittest.TestCase):
    def test_dry_run_over_ceiling_never_executes(self):
        calls = []

        def request(url, **kwargs):
            calls.append((url, kwargs.get("payload")))
            if url.endswith("/cost-policy"):
                return {"mode": "DETERMINISTIC"}
            return {"ok": True, "status": "ready", "providersConfigured": True,
                    "estimatedCostJpy": 800.01, "effectiveBudgetJpy": 1000,
                    "caseCount": 18, "maximumCalls": 72, "dryRunHash": "a" * 64}

        with mock.patch.object(runner, "_request_json", side_effect=request):
            code = runner.run("https://example.test", token="secret",
                              ceiling_jpy=800, poll_seconds=1,
                              max_wait_seconds=1)
        self.assertEqual(code, 3)
        self.assertEqual(len(calls), 2)

    def test_ready_dry_run_executes_once_and_closes(self):
        execute_calls = []

        def request(url, **kwargs):
            payload = kwargs.get("payload")
            if url.endswith("/cost-policy"):
                return {"mode": "DETERMINISTIC"}
            if url.endswith("/dry-run"):
                return {"ok": True, "status": "ready", "providersConfigured": True,
                        "estimatedCostJpy": 524.16, "effectiveBudgetJpy": 800,
                        "caseCount": 18, "maximumCalls": 72,
                        "dryRunHash": "b" * 64}
            if url.endswith("/execute"):
                execute_calls.append(payload)
                return {"ok": True, "status": "running", "benchmarkId": "b1"}
            return {"status": "not_achieved", "mode": "DETERMINISTIC",
                    "twoXClaimAllowed": False, "resultClassification": "not_achieved"}

        with mock.patch.object(runner, "_request_json", side_effect=request):
            code = runner.run("https://example.test", token="secret",
                              ceiling_jpy=800, poll_seconds=1,
                              max_wait_seconds=1)
        self.assertEqual(code, 0)
        self.assertEqual(len(execute_calls), 1)
        self.assertTrue(execute_calls[0]["confirm"])


if __name__ == "__main__":
    unittest.main()
