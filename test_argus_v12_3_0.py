import pathlib
import sys
import types
import unittest
from unittest import mock

_moomoo = types.ModuleType("moomoo")
_moomoo.OpenQuoteContext = lambda *a, **k: None
_moomoo.OpenSecTradeContext = lambda *a, **k: None
_moomoo.RET_OK = 0
sys.modules.setdefault("moomoo", _moomoo)
import scanner


class ArgusV1230IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.old_token = scanner._ARGUS_ADMIN_TOKEN
        self.old_startup = dict(scanner._STARTUP)
        self.old_restored = scanner._OSINT_PERSIST_STATE["restored"]
        scanner._ARGUS_ADMIN_TOKEN = "test-admin"
        scanner._STARTUP["state"] = "ready"
        scanner._STARTUP["restoreOutcome"] = "test_mode"
        scanner._OSINT_PERSIST_STATE["restored"] = True

    def tearDown(self):
        scanner._ARGUS_ADMIN_TOKEN = self.old_token
        scanner._STARTUP.clear(); scanner._STARTUP.update(self.old_startup)
        scanner._OSINT_PERSIST_STATE["restored"] = self.old_restored

    def test_public_cost_and_market_ledger_are_get_only_and_public_safe(self):
        client = scanner.app.test_client()
        cost = client.get("/api/argus/cost-policy")
        self.assertEqual(cost.status_code, 200)
        self.assertEqual(cost.get_json()["mode"], "DETERMINISTIC")
        self.assertFalse(cost.get_json()["automaticAiEnabled"])
        ledger = client.get("/api/argus/market-ledger")
        self.assertEqual(ledger.status_code, 200)
        self.assertEqual(ledger.get_json()["schemaVersion"], "argus-market-ledger-v1")
        self.assertNotIn("holdings", str(ledger.get_json()).lower())

    def test_runtime_keeps_v12_3_or_later_contract(self):
        version = tuple(int(x) for x in scanner._semantic_app_version().split("."))
        self.assertGreaterEqual(version, (12, 3, 0))

    def test_scheduled_ai_endpoint_is_expected_skip_without_provider_call(self):
        client = scanner.app.test_client()
        with mock.patch.object(scanner, "_execute_ai_judgment") as execute:
            response = client.post(
                "/api/argus/ai-judgment/run?checker=flash",
                headers={"X-ARGUS-ADMIN-TOKEN": "test-admin"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status"], "deterministic_mode")
        self.assertEqual(response.get_json()["classification"], "expected_skip")
        execute.assert_not_called()

    def test_durable_v3_snapshot_contains_ledger_and_policy(self):
        client = scanner.app.test_client()
        response = client.get("/api/argus/osint/memory-snapshot")
        body = response.get_json()
        self.assertEqual(body["schemaVersion"], "argus-durable-v3")
        self.assertIn("marketLedger", body)
        self.assertIn("marketLedgerStateHash", body)
        self.assertIn("costPolicy", body)

    def test_market_ledger_tick_is_idempotent(self):
        first = scanner._market_ledger_tick("2026-07-20T12:00:00Z")
        with mock.patch.object(scanner.argus_market_ledger, "rebuild",
                               wraps=scanner.argus_market_ledger.rebuild) as rebuild:
            second = scanner._market_ledger_tick("2026-07-20T12:00:00Z")
        self.assertEqual(first["stateHash"], second["stateHash"])
        self.assertFalse(second["changed"])
        self.assertTrue(second["rebuildSkipped"])
        rebuild.assert_not_called()

    def test_asset_consultation_source_has_no_ai_post(self):
        src = pathlib.Path("web/src/components/assetDesk/AssetResearchPanel.tsx").read_text()
        self.assertIn("clipboard.writeText", src)
        self.assertNotIn("method: 'POST'", src)
        self.assertIn("['ChatGPT', 'Gemini']", src)
        self.assertIn("${provider}に相談", src)


if __name__ == "__main__":
    unittest.main()
