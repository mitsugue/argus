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


# ── VWAP computation + probe-driven capability (v10.200) ─────────────────────
def test_compute_vwap_known_value():
    bars = [{"high": 11, "low": 9, "close": 10, "volume": 100},   # tp=10
            {"high": 22, "low": 18, "close": 20, "volume": 300}]  # tp=20
    # vwap = (10*100 + 20*300)/400 = 7000/400 = 17.5
    assert MD.compute_vwap(bars) == 17.5

def test_compute_vwap_zero_volume_and_empty():
    assert MD.compute_vwap([{"high": 1, "low": 1, "close": 1, "volume": 0}]) is None
    assert MD.compute_vwap([]) is None
    assert MD.compute_vwap(None) is None
    assert MD.compute_vwap([{"high": "x", "low": 1, "close": 1, "volume": 5}]) is None

def test_vwap_capability_live_when_probe_computed():
    r = rpt(vwap_probe={"computed": True, "values": {"NVDA": 123.4}, "asOf": NOW})
    v = r["capabilities"]["VWAP"]
    assert v["status"] == "live" and v["probed"] is True
    assert v["sample"] == {"NVDA": 123.4}
    assert r["capabilitiesForGuard"]["VWAP"] == "live"

def test_vwap_capability_unavailable_but_probed_when_no_bars():
    r = rpt(vwap_probe={"computed": False, "probed": True, "note": "intraday bars empty"})
    v = r["capabilities"]["VWAP"]
    assert v["status"] == "unavailable" and v["probed"] is True

def test_us_extended_probe_reflected():
    r = rpt(us_extended_probe={"status": "requires_contract", "probed": True, "note": "Basic=regular only"})
    assert r["capabilities"]["US_EXTENDED"]["status"] == "requires_contract"
    assert r["capabilities"]["US_EXTENDED"]["probed"] is True

def test_bridge_and_jpcash_marked_probed():
    r = rpt(bridge_age_sec=30.0)
    assert r["capabilities"]["BRIDGE"]["probed"] is True
    assert r["capabilities"]["JP_CASH"]["probed"] is True
    assert r["capabilities"]["JP_PTS"]["probed"] is False   # structural, not measured
