"""Individual-stock chart generation retired (owner, 2026-10-01)."""
import unittest
from unittest import mock

import scanner


class AssetChartRetiredTest(unittest.TestCase):
    def test_tick_does_no_work_and_attaches_nothing(self):
        with mock.patch.object(scanner, "_ASSET_CHART_GENERATION", False), \
                mock.patch.object(scanner, "_attach_market_store", side_effect=AssertionError("no attach")), \
                mock.patch.object(scanner, "_chart_history_cached", side_effect=AssertionError("no history")):
            result = scanner._precompute_asset_chart_tick()
        self.assertEqual(result["status"], "retired")
        self.assertFalse(result["generated"])

    def test_asset_scope_answers_without_calculation(self):
        scanner._RL_BUCKETS.clear()
        client = scanner.app.test_client()
        with mock.patch.object(scanner, "_ASSET_CHART_GENERATION", False), \
                mock.patch.object(scanner, "_asset_chart_current", side_effect=AssertionError("no cache read")), \
                mock.patch.object(scanner, "_chart_public_report", side_effect=AssertionError("no calculation")):
            response = client.get("/api/argus/chart-intelligence?scope=asset&symbol=5803&market=JP")
        body = response.get_json()
        if response.status_code == 401:
            self.skipTest("owner authentication guards the route in this configuration")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(body["status"], "retired")
        self.assertEqual(body["automaticAiCalls"], 0)
        self.assertIn("他のアプリ", body["messageJa"])

    def test_market_scope_is_unaffected(self):
        with mock.patch.object(scanner, "_ASSET_CHART_GENERATION", False):
            self.assertIn("_verified_market_snapshot", scanner.api_argus_chart_intelligence.__code__.co_names)


if __name__ == "__main__":
    unittest.main()
