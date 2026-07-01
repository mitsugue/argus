"""Tests for argus_visibility (Visibility Risk Guard). Pure, stdlib-only."""
import unittest
import argus_visibility as V

NOW = "2026-07-01T05:00:00Z"
ALL_LIVE = {k: "live" for k in V.DEFAULT_CAPABILITIES}


def guard(**kw):
    base = dict(now_iso=NOW, capabilities=ALL_LIVE, calibration_stage="reliable",
                decision_value_phase="", jp_open=False, us_open=False,
                bridge_age_sec=10.0, moomoo_overall_entitlement="realtime_proven")
    base.update(kw)
    return V.build_visibility_guard(**base)


class VisibilityGuardTests(unittest.TestCase):
    def test_clean_full(self):
        g = guard()
        self.assertEqual(g["visibilityLevel"], "full")
        self.assertEqual(g["warnings"], [])
        self.assertEqual(g["blockedActions"], [])
        self.assertIsNone(g["confidenceCap"])
        self.assertEqual(g["engineVersion"], "visibility-guard-v1")
        self.assertEqual(g["asOf"], NOW)

    def test_structural_gaps_are_context_not_alarm(self):
        # Default capabilities = PTS/L2/tape/VWAP/... not live.
        g = guard(capabilities=None)
        codes = g["reasonCodes"]
        for c in ("JP_PTS_UNAVAILABLE", "L2_UNAVAILABLE", "TAPE_UNAVAILABLE", "VWAP_UNAVAILABLE"):
            self.assertIn(c, codes)
        self.assertIn("US_EXTENDED_UNTESTED", codes)
        # Structural gaps NEVER drop level / block / cap.
        self.assertEqual(g["visibilityLevel"], "full")
        self.assertEqual(g["blockedActions"], [])
        self.assertIsNone(g["confidenceCap"])
        self.assertTrue(g["coverageLineJa"])
        self.assertTrue(any("未接続" in x for x in g["limitations"]))

    def test_us_extended_untested_wording(self):
        g = guard(capabilities={**ALL_LIVE, "US_EXTENDED": "untested"})
        self.assertIn("US_EXTENDED_UNTESTED", g["reasonCodes"])
        self.assertTrue(any("未検証" in x for x in g["limitations"]))

    def test_bridge_stale_only_when_open(self):
        g = guard(jp_open=True, bridge_age_sec=1200.0)
        self.assertIn("BRIDGE_STALE", g["reasonCodes"])
        self.assertEqual(g["visibilityLevel"], "minimal")
        self.assertEqual(g["blockedActions"], ["ENTER"])
        self.assertEqual(g["confidenceCap"], 0.55)
        self.assertTrue(any(w["code"] == "BRIDGE_STALE" for w in g["warnings"]))

    def test_bridge_stale_ignored_when_closed(self):
        g = guard(jp_open=False, us_open=False, bridge_age_sec=99999.0)
        self.assertNotIn("BRIDGE_STALE", g["reasonCodes"])
        self.assertEqual(g["visibilityLevel"], "full")
        self.assertEqual(g["blockedActions"], [])

    def test_bridge_never_when_open(self):
        g = guard(us_open=True, bridge_age_sec=None)
        self.assertIn("BRIDGE_NEVER", g["reasonCodes"])
        self.assertEqual(g["visibilityLevel"], "minimal")
        self.assertEqual(g["blockedActions"], ["ENTER"])

    def test_bridge_never_ignored_when_closed(self):
        g = guard(jp_open=False, us_open=False, bridge_age_sec=None)
        self.assertNotIn("BRIDGE_NEVER", g["reasonCodes"])
        self.assertEqual(g["visibilityLevel"], "full")

    def test_realtime_unproven_reduced(self):
        g = guard(jp_open=True, moomoo_overall_entitlement="unknown")
        self.assertIn("REALTIME_UNPROVEN", g["reasonCodes"])
        self.assertEqual(g["visibilityLevel"], "reduced")

    def test_regime_held_stale(self):
        g = guard(regime_held_over_min=45)
        self.assertIn("REGIME_HELD_STALE", g["reasonCodes"])
        self.assertEqual(g["visibilityLevel"], "reduced")
        self.assertEqual(g["confidenceCap"], 0.60)

    def test_ai_budget_stopped(self):
        g = guard(system_health={"overall": "warning", "lamps": [{"id": "ai_budget", "status": "stopped"}]})
        self.assertIn("AI_BUDGET_STOPPED", g["reasonCodes"])
        self.assertEqual(g["visibilityLevel"], "reduced")

    def test_prices_stopped_minimal_blocks_enter(self):
        g = guard(system_health={"overall": "stopped", "lamps": [{"id": "prices_jp", "status": "stopped"}]})
        self.assertEqual(g["visibilityLevel"], "minimal")
        self.assertEqual(g["blockedActions"], ["ENTER"])

    def test_burn_in_caps_but_stays_full(self):
        g = guard(calibration_stage="burn_in")
        self.assertIn("CALIBRATION_BURN_IN", g["reasonCodes"])
        self.assertEqual(g["confidenceCap"], 0.60)
        self.assertEqual(g["visibilityLevel"], "full")  # persistent → context, not alarm

    def test_confidence_cap_is_min_of_active(self):
        g = guard(jp_open=True, bridge_age_sec=1200.0, calibration_stage="burn_in", regime_held_over_min=30)
        # burn-in 0.60, held 0.60, bridge-stale 0.55 → min 0.55
        self.assertEqual(g["confidenceCap"], 0.55)

    def test_confidence_cap_bounds(self):
        g = guard(calibration_stage="burn_in")
        self.assertTrue(0.0 <= g["confidenceCap"] <= 1.0)

    def test_dv_shadow_only_context(self):
        g = guard(decision_value_phase="phase1_shadow_recording_active")
        self.assertIn("DV_SHADOW_ONLY", g["reasonCodes"])
        self.assertTrue(any("edge" in x or "優位性" in x for x in g["limitations"]))


    def test_early_signal_still_caps(self):
        # 30-59 days = "early_signal" — still unproven, must cap at 0.60
        g = guard(calibration_stage="early_signal")
        self.assertIn("CALIBRATION_BURN_IN", g["reasonCodes"])
        self.assertEqual(g["confidenceCap"], 0.60)

    def test_regime_level_does_not_cap(self):
        g = guard(calibration_stage="regime_level")
        self.assertNotIn("CALIBRATION_BURN_IN", g["reasonCodes"])
        self.assertIsNone(g["confidenceCap"])

    def test_deterministic(self):
        a = guard(jp_open=True, bridge_age_sec=1200.0, capabilities=None)
        b = guard(jp_open=True, bridge_age_sec=1200.0, capabilities=None)
        self.assertEqual(a, b)


if __name__ == "__main__":
    unittest.main()
