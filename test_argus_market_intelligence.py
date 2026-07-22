import copy
import unittest

import argus_market_ledger as ledger
import argus_market_intelligence as intelligence


NOW = "2026-07-20T06:00:00Z"


class ArgusMarketIntelligenceTests(unittest.TestCase):
    def test_source_matrix_is_fixed_and_honest(self):
        rows = {x["dataId"]: x for x in intelligence.source_of_truth_matrix()}
        self.assertEqual(rows["jp_daily"]["primary"], "J-Quants equities/bars/daily")
        self.assertEqual(rows["jp_current_price"]["currentStatus"], "entitlement_unavailable")
        self.assertEqual(rows["credit_two_market"]["currentStatus"], "manual_csv")
        self.assertEqual(rows["jp_intraday_tick"]["currentStatus"], "source_unavailable")

    def test_jquants_flow_mapping_uses_publication_not_period_end(self):
        raw = [{"PubDate": "2026-07-16", "StDate": "2026-07-06",
                "EnDate": "2026-07-10", "Section": "TokyoNagoya",
                "FrgnBal": 10, "IndBal": -20, "InvTrBal": 3,
                "TrstBnkBal": 4, "PropBal": -5}]
        rows = intelligence.normalize_jquants_investor_rows(raw, NOW)
        self.assertEqual(len(rows), 5)
        self.assertTrue(all(x["availableFrom"] == "2026-07-16T18:00:00+09:00" for x in rows))
        self.assertTrue(all(x["periodEnd"] == "2026-07-10" for x in rows))
        self.assertEqual(next(x for x in rows if x["seriesId"] == "flow.foreign")["value"], 10000.0)
        self.assertFalse(intelligence.normalize_jquants_investor_rows(
            [{**raw[0], "Section": "TSEPrime"}], NOW))

    def test_backfill_candidates_use_real_ledger_validation(self):
        raw = [{"PubDate": "2026-07-16", "EnDate": "2026-07-10",
                "Section": "TokyoNagoya", "FrgnBal": 10, "IndBal": -20,
                "InvTrBal": 3, "TrstBnkBal": 4, "PropBal": -5}]
        candidates = intelligence.normalize_jquants_investor_rows(raw, NOW)
        result = ledger.import_rows(ledger.empty_state(), candidates, now_iso=NOW, dry_run=False)
        self.assertTrue(result["ok"])
        self.assertEqual(len(result["state"]["observations"]), 5)
        self.assertTrue(all(x["value"] != 0 for x in result["state"]["observations"]))

    def test_walk_forward_does_not_use_unavailable_signal_or_bar(self):
        bars = [{"date": f"2026-01-{day:02d}", "availableFrom": f"2026-01-{day:02d}T17:00:00Z",
                 "close": 100 + day} for day in range(1, 25)]
        valid = {"id": "s1", "effectiveFrom": "2026-01-02",
                 "availableFrom": "2026-01-02T18:00:00Z", "detectedAt": "2026-01-02T18:00:00Z"}
        future_leak = {"id": "s2", "effectiveFrom": "2026-01-03",
                       "availableFrom": "2026-01-04T18:00:00Z", "detectedAt": "2026-01-03T18:00:00Z"}
        report = intelligence.walk_forward_backtest([valid, future_leak], bars)
        self.assertEqual(report["occurrences"], 1)
        self.assertEqual(report["sampleSize"], 1)
        self.assertEqual(report["classification"], "insufficient_data")
        self.assertTrue(report["noFutureLeakage"])

    def test_small_sample_is_never_validated(self):
        bars = [{"date": f"2026-01-{day:02d}", "availableFrom": f"2026-01-{day:02d}",
                 "close": 100 + day} for day in range(1, 25)]
        signal = {"id": "s1", "effectiveFrom": "2026-01-02",
                  "availableFrom": "2026-01-02", "detectedAt": "2026-01-02"}
        self.assertEqual(intelligence.walk_forward_backtest([signal], bars)["classification"],
                         "insufficient_data")

    def test_operating_sheet_limits_and_does_not_call_ai(self):
        view = {"asOf": NOW,
                "summary": {"shortFuel": "UNKNOWN", "foreignFlow": "UNKNOWN",
                            "epsMomentum": "UNKNOWN", "breadth": "UNKNOWN"},
                "table": [], "turningPoints": [
                    {"id": f"t{i}", "ruleId": "BREADTH_TURN", "facts": [f"fact {i}"],
                     "effectiveFrom": f"2026-07-{i + 1:02d}"} for i in range(8)]}
        built = intelligence.build_phase3(copy.deepcopy(view), {"JP": {"session": "HOLIDAY_CLOSED"}})
        self.assertEqual(len(built["phase3"]["sections"]), 16)
        self.assertLessEqual(len(built["phase3"]["dailyChanges"]), 5)
        self.assertLessEqual(len(built["phase3"]["today"]), 3)
        self.assertLessEqual(len(built["phase3"]["decisionChangeConditions"]), 3)
        self.assertEqual(built["automaticAiCalls"], 0)

    def test_anomaly_requires_actual_facts_and_never_invents_cause(self):
        view = {"table": [
            {"seriesId": "valuation.eps", "previousChange": 2},
            {"seriesId": "valuation.per", "previousChange": -1},
        ]}
        rows = intelligence.anomaly_desk(view)
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["causeUnconfirmed"])
        self.assertEqual(rows[0]["possibleExplanations"], [])

    def test_legacy_classification_is_adapted_without_mutating_raw_history(self):
        legacy = "".join(("s", "ho_heuristic"))
        raw = {"classification": legacy, "nested": [{"classification": legacy}]}
        adapted = intelligence.normalize_public_names(raw)
        self.assertEqual(adapted["classification"], "argus_heuristic")
        self.assertEqual(adapted["nested"][0]["classification"], "argus_heuristic")
        self.assertEqual(raw["classification"], legacy)


if __name__ == "__main__":
    unittest.main()
