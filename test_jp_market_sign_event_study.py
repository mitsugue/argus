"""Event study of the seven warning conditions (2026-10-02)."""
from datetime import date, timedelta
import unittest

import jp_market_sign_event_study as study
from jp_market_price_paths import cached_index_comparison

SERIES = study.ACTIVATION_RULES["D01"]["seriesId"]


def sessions(n, start="2016-10-03"):
    out, day = [], date.fromisoformat(start)
    while len(out) < n:
        if day.weekday() < 5:
            out.append(day.isoformat())
        day += timedelta(days=1)
    return out


def event(day, value=1, series=SERIES, known=None, revision=0):
    known = known or day + "T10:00:00Z"
    return {"instrumentId": "NIKKEI_225_INDEX", "seriesId": series, "date": day, "value": value,
            "unit": "DIRECTION", "availableFrom": known, "knownAt": known, "revision": revision,
            "validationStatus": "UNVALIDATED"}


def run(rows, closes, days, cutoff=None):
    return study.sign_event_study(rows, closes, days, cutoff=cutoff or days[-1] + "T08:00:00Z")


class SignEventStudyTest(unittest.TestCase):
    def test_entry_is_the_next_close_after_the_known_date(self):
        days = sessions(60)
        closes = {d: 100.0 for d in days}
        # The activation is known on day 10 (after its close). Day 10's close
        # jumps; entering at day 10 would see a fall, entering at day 11 does not.
        closes[days[10]] = 120.0
        result = run([event(days[0], -1), event(days[10])], closes, days)
        d01 = result["conditions"]["D01"]
        self.assertEqual(d01["firstActivation"], days[11])
        self.assertEqual(d01["horizons"]["5"]["falls"], 0)
        self.assertEqual(d01["horizons"]["5"]["meanReturnPct"], 0.0)
        # Knowledge after the date itself (a later replay) moves the entry.
        late = run([event(days[0], -1), event(days[10], known=days[13] + "T09:00:00Z")], closes, days)
        self.assertEqual(late["conditions"]["D01"]["firstActivation"], days[14])

    def test_rows_known_after_the_cutoff_and_later_revisions_are_ignored(self):
        days = sessions(80)
        closes = {d: 100.0 + i for i, d in enumerate(days)}
        rows = [event(days[0], -1), event(days[20]),
                event(days[20], value=-1, known=days[40] + "T10:00:00Z", revision=1),
                event(days[50], known=days[70] + "T10:00:00Z")]
        d01 = run(rows, closes, days, cutoff=days[60] + "T08:00:00Z")["conditions"]["D01"]
        self.assertEqual(d01["rawActivations"], 1)          # first-known revision, no future row
        self.assertEqual(d01["firstActivation"], days[21])
        self.assertLessEqual(d01["coverageEnd"], days[55])  # no close after the cutoff

    def test_overlapping_activations_are_merged(self):
        days = sessions(200)
        closes = {d: 100.0 for d in days}
        rows = [event(days[0], -1)]
        for i in (10, 15, 29, 31, 60):
            rows += [event(days[i]), event(days[i + 1], -1)]
        d01 = run(rows, closes, days)["conditions"]["D01"]
        self.assertEqual(d01["rawActivations"], 5)
        # entries 11, 16, 30, 32, 61: 16 and 30 fall within 20 sessions of 11.
        self.assertEqual(d01["activations"], 3)
        self.assertEqual(d01["overlappingMerged"], 2)

    def test_baseline_counts_every_session_in_the_coverage(self):
        days = sessions(100)
        # Alternating closes: every 5-session return from an odd index falls.
        closes = {d: (100.0 if i % 2 == 0 else 101.0) for i, d in enumerate(days)}
        d01 = run([event(days[0], -1), event(days[10])], closes, days)["conditions"]["D01"]
        h5 = d01["horizons"]["5"]
        self.assertEqual(d01["coverageStart"], days[1])
        self.assertEqual(h5["evaluated"], 1)
        self.assertEqual(h5["falls"], 1)                     # entry at odd index 11
        # Coverage 1..94: odd starts fall (47 of 94).
        self.assertEqual(h5["baselineSessions"], 94)
        self.assertAlmostEqual(h5["baselineFallShare"], 0.5)

    def test_three_period_split_and_insufficient_sample(self):
        days = sessions(900)
        closes = {d: 100.0 for d in days}
        rows = [event(days[0], -1)]
        for i in range(10, 880, 30):
            rows += [event(days[i]), event(days[i + 1], -1)]
        d01 = run(rows, closes, days)["conditions"]["D01"]
        names = [p["name"] for p in d01["periods"]]
        self.assertEqual(names, ["design", "confirm", "report"])
        for left, right in zip(d01["periods"], d01["periods"][1:]):
            self.assertLess(left["end"], right["start"])
        self.assertEqual(sum(p["activations"] for p in d01["periods"]), d01["activations"])
        self.assertGreaterEqual(d01["activations"], study.MINIMUM_ACTIVATIONS)
        # Flat prices: nothing falls, so the condition is not above baseline.
        self.assertEqual(d01["status"], "NOT_ABOVE_BASELINE")
        self.assertEqual(d01["falseAlarmShare"], 1.0)
        few = run(rows[:11], closes, days)["conditions"]["D01"]
        self.assertEqual(few["status"], "INSUFFICIENT_SAMPLE")
        result = run(rows, closes, days)
        self.assertEqual(result["conditions"]["D02"]["status"], "INSUFFICIENT_SAMPLE")
        self.assertEqual(result["conditions"]["D07"]["status"], "NOT_EVALUABLE")
        self.assertIsNone(result["predictiveProbabilities"])
        self.assertFalse(result["actionAuthority"])
        self.assertTrue(all(c["predictiveProbabilities"] is None and c["actionAuthority"] is False
                            for c in result["conditions"].values()))

    def test_a_condition_followed_by_falls_beats_the_baseline_in_the_report_period(self):
        days = sessions(1500)
        closes, value = {}, 100.0
        activation_entries = set(range(31, 1450, 30))
        drops = {i + k for i in activation_entries for k in range(1, 6)}
        for i, d in enumerate(days):
            value *= 0.99 if i in drops else 1.002
            closes[d] = value
        rows = [event(days[0], -1)]
        for entry in sorted(activation_entries):
            rows += [event(days[entry - 1]), event(days[entry + 1], -1)]
        d01 = run(rows, closes, days)["conditions"]["D01"]
        self.assertEqual(d01["status"], "ABOVE_BASELINE")
        report = d01["periods"][-1]["horizons"]["5"]
        self.assertGreater(report["fallShareWilsonLower95"], report["baselineFallShare"])
        # D06's activation is the move into a negative histogram (value -1).
        d06_rows = [{**r, "seriesId": "vix_macd_cross", "value": -r["value"]} for r in rows]
        self.assertEqual(run(d06_rows, closes, days)["conditions"]["D06"]["status"], "ABOVE_BASELINE")

    def test_malformed_inputs(self):
        days = sessions(30)
        with self.assertRaises(ValueError):
            study.sign_event_study([], {}, days[::-1], cutoff=days[-1] + "T08:00:00Z")
        with self.assertRaises(ValueError):
            study.sign_event_study([], {}, days, cutoff="not-a-time")
        result = run([{"seriesId": SERIES, "date": days[3], "value": True, "availableFrom": days[3] + "T10:00:00Z"},
                      "garbage", event(days[4], value=2)], {d: 100.0 for d in days}, days)
        self.assertEqual(result["status"], "UNAVAILABLE")


class ComparisonWiringTest(unittest.TestCase):
    def test_comparison_document_carries_the_study_and_reuses_it(self):
        days = sessions(400)
        closes = [30000 * (1 + 0.0002 * i) for i in range(len(days))]
        rows = [{"instrumentId": "NIKKEI_225_INDEX", "date": d, "open": c, "high": c, "low": c, "close": c,
                 "volume": 1, "availableFrom": d + "T07:00:00Z"} for d, c in zip(days, closes)]
        conditions = [event(days[100], -1), event(days[150]), event(days[160], -1)]
        cache = {}
        doc = cached_index_comparison(rows, cutoff=days[-1] + "T08:00:00Z", session_dates=days,
                                      condition_rows=conditions, backtest_cache=cache)
        signs = doc["comparison"]["forecast"]["signEventStudy"]
        self.assertEqual(signs["method"], study.METHOD)
        self.assertEqual(signs["conditions"]["D01"]["activations"], 1)
        self.assertIsNone(signs["predictiveProbabilities"])
        key = cache["signEventStudy"]["key"]
        cached_index_comparison(rows, cutoff=days[-1] + "T08:00:00Z", session_dates=days,
                                condition_rows=conditions, horizon_sessions=20, backtest_cache=cache)
        self.assertEqual(cache["signEventStudy"]["key"], key)
        without_cache = cached_index_comparison(rows, cutoff=days[-1] + "T08:00:00Z", session_dates=days,
                                                condition_rows=conditions)
        self.assertEqual(without_cache["comparison"]["forecast"]["signEventStudy"], signs)


if __name__ == "__main__":
    unittest.main()
