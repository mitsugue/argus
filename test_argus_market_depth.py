"""Tests for argus_market_depth (Market Depth capability report). Pure, stdlib-only."""
import unittest
import argus_market_depth as MD

NOW = "2026-07-01T05:00:00Z"


def rpt(**kw):
    base = dict(now_iso=NOW, bridge_age_sec=30.0,
                moomoo_capability={"overallEntitlement": "unknown"},
                realtime_proof={}, source_registry={"sources": []}, jp_open=False, us_open=False)
    base.update(kw)
    return MD.build_market_depth_report(**base)


class MarketDepthTests(unittest.TestCase):
    def test_normalize_table(self):
        self.assertEqual(MD._normalize("confirmed_live"), "live")
        self.assertEqual(MD._normalize("confirmed_delayed"), "partial")
        self.assertEqual(MD._normalize("requires_test"), "testing")
        self.assertEqual(MD._normalize("paid_not_enabled"), "requires_contract")
        self.assertEqual(MD._normalize("missing"), "unavailable")
        self.assertEqual(MD._normalize(None), "unavailable")

    def test_guard_status_projection(self):
        self.assertEqual(MD._to_guard_status("live"), "live")
        self.assertEqual(MD._to_guard_status("partial"), "live")       # real, delayed
        self.assertEqual(MD._to_guard_status("testing"), "untested")
        self.assertEqual(MD._to_guard_status("requires_contract"), "unavailable")
        self.assertEqual(MD._to_guard_status("unavailable"), "unavailable")

    def test_bridge_live_partial_stale(self):
        self.assertEqual(rpt(bridge_age_sec=30.0)["capabilities"]["BRIDGE"]["status"], "live")
        self.assertEqual(rpt(bridge_age_sec=400.0)["capabilities"]["BRIDGE"]["status"], "partial")
        self.assertEqual(rpt(bridge_age_sec=5000.0)["capabilities"]["BRIDGE"]["status"], "unavailable")
        self.assertEqual(rpt(bridge_age_sec=None)["capabilities"]["BRIDGE"]["status"], "unavailable")

    def test_jp_cash_realtime_only_on_proof(self):
        # push cadence / unknown entitlement must NOT earn 'live'
        r = rpt(moomoo_capability={"overallEntitlement": "unknown"})
        self.assertEqual(r["capabilities"]["JP_CASH"]["status"], "partial")
        self.assertFalse(r["summary"]["jpRealtimeProven"])
        # only venue-timestamp proof earns live
        r2 = rpt(moomoo_capability={"overallEntitlement": "realtime_proven"})
        self.assertEqual(r2["capabilities"]["JP_CASH"]["status"], "live")
        self.assertTrue(r2["summary"]["jpRealtimeProven"])

    def test_structural_caps_never_live(self):
        r = rpt()
        for key in ("JP_PTS", "VWAP", "TAPE", "L2", "OPTIONS_IV", "BORROW_FEE", "FX_FUTURES"):
            self.assertIn(r["capabilities"][key]["status"], ("unavailable", "requires_contract", "testing"))
            self.assertNotEqual(r["capabilities"][key]["status"], "live")

    def test_us_extended_is_testing_not_live(self):
        self.assertEqual(rpt()["capabilities"]["US_EXTENDED"]["status"], "testing")
        self.assertEqual(rpt()["capabilitiesForGuard"]["US_EXTENDED"], "untested")

    def test_action_level_flags(self):
        caps = rpt()["capabilities"]
        self.assertTrue(caps["BRIDGE"]["affectsActionLevel"])
        self.assertTrue(caps["JP_CASH"]["affectsActionLevel"])
        self.assertFalse(caps["L2"]["affectsActionLevel"])
        self.assertFalse(caps["VWAP"]["affectsActionLevel"])

    def test_tdnet_from_registry(self):
        reg = {"sources": [{"capability": "tdnet_disclosure", "status": "confirmed_live"}]}
        self.assertEqual(rpt(source_registry=reg)["capabilities"]["TDNET"]["status"], "live")

    def test_guard_projection_keys_cover_structural(self):
        g = rpt()["capabilitiesForGuard"]
        for key in ("JP_PTS", "US_EXTENDED", "L2", "TAPE", "VWAP", "FX_FUTURES", "TDNET"):
            self.assertIn(key, g)

    def test_deterministic(self):
        self.assertEqual(rpt(bridge_age_sec=100.0), rpt(bridge_age_sec=100.0))

    def test_engine_version_present(self):
        self.assertEqual(rpt()["engineVersion"], "market-depth-v1")


if __name__ == "__main__":
    unittest.main()
