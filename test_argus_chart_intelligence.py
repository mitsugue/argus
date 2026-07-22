import copy
import datetime as dt
import unittest

import argus_chart_intelligence as ci


def bars(count=260, start=100.0, step=0.35, volume=1000.0):
    out = []
    day = dt.date(2024, 1, 1)
    value = start
    while len(out) < count:
        if day.weekday() < 5:
            close = value
            out.append({"date": day.isoformat(), "open": close - 0.2,
                        "high": close + 1.0, "low": close - 1.0,
                        "close": close, "volume": volume + len(out) * 2,
                        "sourceId": f"b{len(out)}", "adjusted": True})
            value += step
        day += dt.timedelta(days=1)
    return out


class ChartCalculationTests(unittest.TestCase):
    def test_all_indicators_and_input_order_independence(self):
        source = bars()
        a = ci.calculate_indicators(source)
        b = ci.calculate_indicators(list(reversed(source)))
        self.assertEqual(a, b)
        latest = a["bars"][-1]
        for window in (5, 25, 75, 100, 200):
            self.assertIsNotNone(latest["ma"][str(window)])
        self.assertIsNotNone(latest["bollinger"])
        self.assertIsNotNone(latest["rsi14"])
        self.assertIsNotNone(latest["macd"])
        self.assertIsNotNone(latest["atr14"])
        self.assertIsNotNone(latest["sar"])
        self.assertIsNotNone(latest["ichimoku"]["spanA"])
        self.assertTrue(latest["adjusted"])
        self.assertIn(a["priceStructure"]["high"],
                      {"higher_high", "lower_high", "equal_high", "unconfirmed"})

    def test_missing_ohlcv_holiday_and_duplicate(self):
        source = bars(30)
        source.append({"date": source[-1]["date"], "close": 999,
                       "open": 999, "high": 1000, "low": 998, "volume": 1})
        source.append({"date": "2024-03-02", "close": None})
        result = ci.calculate_indicators(source)
        self.assertEqual(len(result["bars"]), 30)
        self.assertEqual(result["bars"][-1]["close"], 999)
        self.assertIn("duplicate_date_latest_kept", result["missingReasons"])
        self.assertIn("missing_date_or_close", result["missingReasons"])

    def test_zero_and_invalid_values_never_become_price(self):
        result = ci.calculate_indicators([{"date": "2025-01-02", "close": 0}])
        self.assertEqual(result["status"], "missing")
        self.assertEqual(result["bars"], [])


class ZoneAndTurningPointTests(unittest.TestCase):
    def test_zone_contract_and_idempotent_cluster(self):
        source = bars(90, step=0.08)
        for idx in (20, 35, 50, 65):
            source[idx]["low"] = 98.8
            source[idx]["close"] = 100.0
        indicators = ci.calculate_indicators(source)
        first = ci.support_resistance_zones(indicators)
        second = ci.support_resistance_zones(indicators)
        self.assertEqual(first, second)
        self.assertTrue(first)
        required = {"lower", "upper", "center", "firstObservedAt", "lastTestedAt",
                    "testCount", "breakCount", "sourceTypes", "strength", "status"}
        self.assertTrue(required.issubset(first[0]))
        self.assertTrue({x["status"] for x in first} <=
                        {"active", "broken", "reclaimed", "unconfirmed"})

    def test_structure_break_candidate_confirmed_and_invalidation(self):
        source = bars(80, step=0.4)
        # First two closes below a still-rising MA25, followed by a reclaim.
        ma_ref = sum(x["close"] for x in source[-27:-2]) / 25
        source[-2].update({"open": ma_ref, "high": ma_ref + 1,
                           "low": ma_ref - 3, "close": ma_ref - 2})
        source[-1].update({"open": ma_ref - 2, "high": ma_ref + 3,
                           "low": ma_ref - 2.5, "close": ma_ref + 2})
        report = ci.calculate_indicators(source)
        points = ci.technical_turning_points(report, ci.support_resistance_zones(report))
        states = {(x["ruleId"], x["status"]) for x in points}
        self.assertIn(("TREND_STRUCTURE_BREAK", "candidate"), states)
        self.assertIn(("TREND_STRUCTURE_BREAK", "invalidated"), states)
        self.assertIn(("TREND_STRUCTURE_RECLAIM", "confirmed"), states)

    def test_extreme_deviation_has_no_buy_claim(self):
        source = bars(80, step=0.1)
        source[-1].update({"open": 80, "high": 81, "low": 70, "close": 72})
        indicators = ci.calculate_indicators(source)
        points = ci.technical_turning_points(indicators,
                                             ci.support_resistance_zones(indicators))
        extreme = [x for x in points if x["ruleId"] == "EXTREME_DEVIATION"]
        self.assertTrue(extreme)
        self.assertNotIn("買い確定", str(extreme))

    def test_rsi_divergence_candidate_confirmation_and_detection_mode(self):
        indicators = ci.calculate_indicators(bars(45, step=0.03))
        rows = indicators["bars"]
        # Make the final two completed swing highs deterministic: price higher,
        # RSI lower.  Latest close below the second swing low confirms it.
        for idx in range(len(rows)):
            rows[idx]["high"] = rows[idx]["close"] + .2
            rows[idx]["low"] = rows[idx]["close"] - .2
        rows[34].update({"high": 130, "close": 125, "rsi14": 72, "low": 124})
        rows[39].update({"high": 135, "close": 130, "rsi14": 61, "low": 129})
        rows[-1].update({"open": 127, "high": 128, "low": 126, "close": 127})
        points = ci.technical_turning_points(
            indicators, [], detected_at="2030-01-01T00:00:00Z")
        rsi = [x for x in points if x["ruleId"] == "RSI_DIVERGENCE"]
        self.assertTrue(any(x["status"] == "candidate" for x in rsi))
        self.assertTrue(any(x["status"] == "confirmed" for x in rsi))
        self.assertTrue(all(x["detectionMode"] == "retrospective" for x in rsi))
        self.assertEqual(len({x["id"] for x in points}), len(points))

    def test_resistance_cluster_rejection_is_candidate_not_trade_command(self):
        indicators = ci.calculate_indicators(bars(50, step=0.1))
        latest = indicators["bars"][-1]
        latest["open"] = latest["close"] + 1
        latest["high"] = latest["open"] + .5
        latest["volumeRatio20"] = .7
        zones = [{"id": "z1", "lower": latest["close"], "upper": latest["high"] + .2,
                  "center": latest["close"] + .5},
                 {"id": "z2", "lower": latest["close"] + .2, "upper": latest["high"] + .8,
                  "center": latest["close"] + .8}]
        points = ci.technical_turning_points(indicators, zones)
        reject = [x for x in points if x["ruleId"] == "RESISTANCE_CLUSTER_REJECTION"]
        self.assertTrue(reject)
        self.assertEqual(reject[-1]["status"], "candidate")
        self.assertIn("参考分類：壁ドン", reject[-1]["facts"])
        self.assertNotIn("売り", str(reject[-1]))

    def test_stale_price_cannot_remain_confirmed(self):
        report = ci.analyze("OLD", "US", bars(), now_iso="2030-01-01T00:00:00Z")
        self.assertEqual(report["status"], "stale")
        self.assertIn("stale_price", report["missingReasons"])
        self.assertFalse(any(x["status"] == "confirmed" for x in report["turningPoints"]))


class RelativeReactionAndCritiqueTests(unittest.TestCase):
    def test_valuation_levels_use_each_dates_available_eps(self):
        ledger = {"valuationHistory": [
            {"asOf": "2026-01-01", "availableFrom": "2026-01-02", "value": 100,
             "inputObservationIds": ["old"]},
            {"asOf": "2026-02-01", "availableFrom": "2026-02-02", "value": 200,
             "inputObservationIds": ["new"]},
        ]}
        old = ci.valuation_levels(ledger, "2026-01-15T00:00:00Z")
        current = ci.valuation_levels(ledger, "2026-03-01T00:00:00Z")
        self.assertEqual(old[-1]["value"], 2100)
        self.assertEqual(current[-1]["history"][0]["value"], 2100)
        self.assertEqual(current[-1]["history"][1]["value"], 4200)

    def test_relative_strength_ns_turn_and_zero_guard(self):
        left, right = bars(80, step=0.5), bars(80, step=0.15)
        result = ci.relative_strength("nikkei_sp500", left, right,
                                      classification="argus_heuristic")
        self.assertEqual(result["status"], "live")
        self.assertGreater(result["change20Pct"], 0)
        self.assertEqual(result["classification"], "argus_heuristic")
        broken = copy.deepcopy(right)
        broken[-1]["close"] = 0
        guarded = ci.relative_strength("guard", left, broken)
        self.assertTrue(all(x["value"] > 0 for x in guarded["history"]))

    def test_relative_strength_turn_is_explicit_and_deterministic(self):
        row = {"seriesId": "topix_nikkei", "directionTurn": "improving",
               "periodEnd": "2026-07-17", "availableFrom": "2026-07-17",
               "inputIds": ["topix", "nikkei"], "classification": "derived"}
        first = ci.relative_strength_turning_points({"topix_nikkei": row})
        second = ci.relative_strength_turning_points({"topix_nikkei": row})
        self.assertEqual(first, second)
        self.assertEqual(first[0]["ruleId"], "RELATIVE_STRENGTH_TURN")
        self.assertEqual(first[0]["status"], "confirmed")

    def test_rotation_missing_is_honest(self):
        result = ci.rotation_map({"TOPIX": bars(40), "半導体": bars(40, step=0.8),
                                  "高配当": []})
        missing = next(x for x in result if x["label"] == "高配当")
        self.assertEqual(missing["state"], "missing")

    def test_good_news_bad_reaction_and_unconfirmed_cause(self):
        source = bars(50, step=0.1, volume=1000)
        idx = 30
        source[idx].update({"open": source[idx - 1]["close"] + 3,
                            "high": source[idx - 1]["close"] + 4,
                            "low": source[idx - 1]["close"] - 2,
                            "close": source[idx - 1]["close"] - 1,
                            "volume": 5000})
        source[idx + 1].update({"open": source[idx]["close"],
                                "high": source[idx]["close"] + 1,
                                "low": source[idx]["close"] - 2,
                                "close": source[idx]["close"] - 1,
                                "volume": 4000})
        event = {"id": "ev1", "date": source[idx]["date"],
                 "classification": "earnings_beat"}
        result = ci.reaction_anomalies([event], source)
        self.assertEqual(result[0]["ruleId"], "GOOD_NEWS_BAD_REACTION")
        self.assertEqual(result[0]["causeStatus"], "原因未確認")

    def test_bad_news_resilient_and_volume_guard(self):
        source = bars(50, step=0.1, volume=1000)
        idx = 30
        source[idx]["volume"] = 5000
        event = {"id": "ev2", "date": source[idx]["date"],
                 "classification": "downward_revision"}
        result = ci.reaction_anomalies([event], source)
        self.assertTrue(any(x["ruleId"] == "BAD_NEWS_RESILIENT_REACTION" for x in result))
        source[idx]["volume"] = 10
        self.assertEqual(ci.reaction_anomalies([event], source), [])
        unknown = {"id": "ev3", "date": source[idx]["date"], "classification": "unconfirmed"}
        self.assertEqual(ci.reaction_anomalies([unknown], source), [])

    def test_relationship_break_and_short_critique(self):
        breaks = ci.relationship_breaks(
            ledger_summary={"foreignFlow": "INFLOW"},
            relative={"dollar_nikkei": {"change5Pct": -1}},
            eps_change=2, per_change=-1)
        self.assertEqual(len(breaks), 2)
        self.assertTrue(all("理由は未確認" in x["facts"] for x in breaks))
        report = ci.analyze("TEST", "US", bars(), now_iso="2026-07-20T12:00:00Z")
        self.assertLessEqual(len(report["critique"]), 5)
        self.assertEqual(len({x["label"] for x in report["critique"]}),
                         len(report["critique"]))
        self.assertNotIn("TREND_STRUCTURE", str(report["critique"]))
        self.assertEqual([x["label"] for x in report["scenarios"]],
                         ["強気条件", "基本条件", "弱気条件"])
        self.assertEqual(report["automaticAiCalls"] if "automaticAiCalls" in report else 0, 0)
        self.assertIn("確認", report["critique"][-1]["text"])


class PersistenceTests(unittest.TestCase):
    def test_append_only_restore_readback_method_version_and_idempotency(self):
        report = ci.analyze("TEST", "US", bars(), now_iso="2026-07-20T12:00:00Z")
        state = ci.merge_report(ci.empty_state(), report, "2026-07-20T12:00:00Z")
        repeated = ci.merge_report(state, report, "2026-07-20T12:01:00Z")
        self.assertEqual(len(state["snapshots"]), len(repeated["snapshots"]))
        self.assertEqual(len(state["zones"]), len(repeated["zones"]))
        restored = ci.normalize_state(copy.deepcopy(repeated))
        self.assertTrue(ci.read_back_verified(repeated, restored))
        self.assertEqual(restored["methodVersion"], ci.METHOD_VERSION)
        self.assertTrue(all(x.get("methodVersion") == ci.METHOD_VERSION
                            for x in restored["snapshots"]))

    def test_same_technical_id_is_kept_for_each_symbol_scope(self):
        source = bars(80, step=0.4)
        ma_ref = sum(x["close"] for x in source[-27:-2]) / 25
        source[-2].update({"open": ma_ref, "high": ma_ref + 1,
                           "low": ma_ref - 3, "close": ma_ref - 2})
        source[-1].update({"open": ma_ref - 1, "high": ma_ref,
                           "low": ma_ref - 4, "close": ma_ref - 3})
        first_report = ci.analyze("AAA", "US", source, now_iso="2026-07-20T12:00:00Z")
        second_report = ci.analyze("BBB", "US", source, now_iso="2026-07-20T12:00:00Z")
        state = ci.merge_report(ci.empty_state(), first_report, "2026-07-20T12:00:00Z")
        state = ci.merge_report(state, second_report, "2026-07-20T12:00:00Z")
        scoped = {(x.get("symbol"), x.get("id")) for x in state["turningPoints"]}
        ids = {x.get("id") for x in first_report["turningPoints"]}
        self.assertTrue(ids)
        self.assertTrue(all(("AAA", point_id) in scoped and ("BBB", point_id) in scoped
                            for point_id in ids))


if __name__ == "__main__":
    unittest.main()
