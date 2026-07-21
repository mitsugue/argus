import datetime as dt
import pathlib
import sys
import types
import unittest
from unittest import mock

import argus_chart_intelligence as ci

# The SDK creates a user-home rotating log during import.  Tests exercise only
# public Flask/data functions, so use the same inert process-local stub as CI.
sys.modules.setdefault("moomoo", types.SimpleNamespace(
    OpenQuoteContext=object, OpenSecTradeContext=object, RET_OK=0))
import scanner


def history(count=260, start=100.0, step=0.2):
    dates, opens, highs, lows, closes, volumes = [], [], [], [], [], []
    day = dt.date(2024, 1, 1)
    value = start
    while len(dates) < count:
        if day.weekday() < 5:
            dates.append(day.isoformat()); opens.append(value - .2)
            highs.append(value + 1); lows.append(value - 1); closes.append(value)
            volumes.append(1000 + len(dates)); value += step
        day += dt.timedelta(days=1)
    # Provider caches are newest-first.
    return {"dates": dates[::-1], "opens": opens[::-1], "highs": highs[::-1],
            "lows": lows[::-1], "closes": closes[::-1], "volumes": volumes[::-1]}


class ArgusV1240IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.chart_state = ci.normalize_state(scanner._CHART_INTELLIGENCE)
        scanner._CHART_INTELLIGENCE.clear()
        scanner._CHART_INTELLIGENCE.update(ci.empty_state())

    def tearDown(self):
        scanner._CHART_INTELLIGENCE.clear()
        scanner._CHART_INTELLIGENCE.update(self.chart_state)

    def test_asset_chart_get_is_deterministic_and_provider_ai_zero(self):
        fake = history()
        with mock.patch.object(scanner, "_jq_price_history", return_value=fake), \
                mock.patch.object(scanner, "_td_price_history", return_value=fake), \
                mock.patch.object(scanner, "get_events_snapshot", return_value={"events": []}), \
                mock.patch.object(scanner, "_execute_ai_judgment") as ai:
            response = scanner.app.test_client().get(
                "/api/argus/chart-intelligence?scope=asset&symbol=7203&market=JP")
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual(body["schemaVersion"], ci.SCHEMA_VERSION)
        self.assertEqual(body["automaticAiCalls"], 0)
        self.assertEqual(body["costPolicyMode"], "DETERMINISTIC")
        self.assertTrue(body["zones"])
        self.assertLessEqual(len(body["critique"]), 5)
        serialized = str(body).lower()
        self.assertNotIn("x-api-key", serialized)
        self.assertNotIn("holdings", serialized)
        self.assertNotIn("providerresponse", serialized)
        ai.assert_not_called()

    def test_market_chart_has_relative_rotation_and_proxy_disclosure(self):
        fake = history()
        with mock.patch.object(scanner, "_jq_price_history", return_value=fake), \
                mock.patch.object(scanner, "_td_price_history", return_value=fake), \
                mock.patch.object(scanner, "get_events_snapshot", return_value={"events": []}):
            body = scanner.app.test_client().get(
                "/api/argus/chart-intelligence?scope=market").get_json()
        self.assertIn("relativeStrength", body)
        self.assertIn("rotationMap", body)
        self.assertIn("ledgerTurningPoints", body)
        self.assertIn("proxyDisclosureJa", body)
        self.assertEqual(body["relativeStrength"]["nikkei_sp500"]["classification"],
                         "sho_heuristic")

    def test_asset_chart_reuses_cached_earnings_without_provider_fetch(self):
        fake = history()
        event_date = fake["dates"][10]
        cached = {"items": [{"symbol": "7203", "earnings": {
            "date": event_date, "epsEstimate": 10, "epsActual": 12},
            "filings": [], "disclosures": []}]}
        with mock.patch.dict(scanner._CAT_CACHE, {"data": cached}, clear=False), \
                mock.patch.object(scanner, "_jq_price_history", return_value=fake), \
                mock.patch.object(scanner, "get_events_snapshot", return_value={"events": []}), \
                mock.patch.object(scanner, "get_catalysts_snapshot") as provider_path:
            body = scanner.app.test_client().get(
                "/api/argus/chart-intelligence?scope=asset&symbol=7203&market=JP").get_json()
        self.assertTrue(any(x["kind"] == "earnings" for x in body["eventMarkers"]))
        provider_path.assert_not_called()

    def test_weekly_switch_and_invalid_timeframe(self):
        fake = history()
        with mock.patch.object(scanner, "_jq_price_history", return_value=fake), \
                mock.patch.object(scanner, "get_events_snapshot", return_value={"events": []}):
            client = scanner.app.test_client()
            daily = client.get("/api/argus/chart-intelligence?scope=asset&symbol=7203&market=JP&timeframe=daily")
            weekly = client.get("/api/argus/chart-intelligence?scope=asset&symbol=7203&market=JP&timeframe=weekly")
            invalid = client.get("/api/argus/chart-intelligence?scope=asset&symbol=7203&market=JP&timeframe=minute")
        self.assertEqual(weekly.status_code, 200)
        self.assertNotEqual(daily.get_json()["reportId"], weekly.get_json()["reportId"])
        self.assertEqual(weekly.get_json()["timeframe"], "weekly")
        self.assertLess(len(weekly.get_json()["indicators"]["bars"]), 80)
        self.assertEqual(invalid.status_code, 400)

    def test_durable_v3_snapshot_contains_chart_state_and_hash(self):
        old_restored = scanner._OSINT_PERSIST_STATE["restored"]
        scanner._OSINT_PERSIST_STATE["restored"] = True
        try:
            body = scanner.app.test_client().get("/api/argus/osint/memory-snapshot").get_json()
        finally:
            scanner._OSINT_PERSIST_STATE["restored"] = old_restored
        self.assertEqual(body["schemaVersion"], "argus-durable-v3")
        self.assertIn("chartIntelligence", body)
        self.assertIn("chartIntelligenceStateHash", body)
        self.assertNotIn("holdings", str(body).lower())

    def test_frontend_uses_get_shared_cache_hidden_pause_and_no_ai_post(self):
        hook = pathlib.Path("web/src/hooks/useChartIntelligence.ts").read_text()
        panel = pathlib.Path("web/src/components/chart/ChartIntelligencePanel.tsx").read_text()
        self.assertIn("method: 'GET'", hook)
        self.assertIn("visibilityState === 'hidden'", hook)
        self.assertIn("const inflight", hook)
        self.assertNotIn("method: 'POST'", hook + panel)
        self.assertIn("slice(0, 3)", panel)
        self.assertIn("AI API 0", panel)

    def test_runtime_version_matches_release(self):
        self.assertEqual(scanner._semantic_app_version(), "12.7.11")


if __name__ == "__main__":
    unittest.main()
