"""Rule-derived monthly SQ history (2026-09-30): labelled, never VERIFIED."""
from datetime import date, timedelta
import unittest

import jp_market_events as events
import jp_market_features as features


def sessions(start, end, closed=()):
    day, out = date.fromisoformat(start), []
    while day <= date.fromisoformat(end):
        if day.weekday() < 5 and day.isoformat() not in closed:
            out.append(day.isoformat())
        day += timedelta(days=1)
    return out


class RuleDerivedSqTest(unittest.TestCase):
    def test_second_friday_and_prior_session_shift(self):
        # September 2026: second Friday is 09-11. Treat 10-09 (second Friday
        # of October) as closed so the SQ shifts to 10-08.
        cal = sessions("2026-08-20", "2026-11-30", closed=("2026-10-09",))
        rows = events.rule_derived_sq_rows(cal, calculation_dates=["2026-09-01", "2026-09-11", "2026-09-14", "2026-10-01"])
        by = {r["date"]: r for r in rows}
        self.assertEqual(by["2026-09-01"]["sqDate"], "2026-09-11")
        self.assertEqual(by["2026-09-01"]["tradingSessionsUntil"], 8)
        self.assertEqual(by["2026-09-11"]["tradingSessionsUntil"], 0)
        self.assertEqual(by["2026-09-14"]["sqDate"], "2026-10-08")
        self.assertEqual(by["2026-10-01"]["sqDate"], "2026-10-08")
        self.assertEqual(by["2026-10-01"]["tradingSessionsUntil"], 5)
        self.assertEqual(by["2026-09-01"]["kind"], "MAJOR_SQ")
        self.assertEqual(by["2026-10-01"]["kind"], "MONTHLY_SQ")
        for row in rows:
            self.assertEqual(row["calendarStatus"], "RULE_DERIVED")
            self.assertEqual(row["knownAt"], row["calculatedAt"])
            self.assertEqual(row["knownAt"], row["date"] + "T00:00:00+09:00")
            self.assertEqual(row["sourceRef"], events.SQ_RULE_SOURCE)
            self.assertIs(row["historicalVintageVerified"], False)

    def test_calendar_that_does_not_reach_the_next_sq_yields_no_distance(self):
        cal = sessions("2026-09-01", "2026-09-30")
        rows = events.rule_derived_sq_rows(cal, calculation_dates=["2026-09-20"])
        self.assertEqual(rows, [])
        with self.assertRaises(ValueError):
            events.rule_derived_sq_rows([], calculation_dates=["2026-09-20"])

    def test_features_accept_rule_rows_and_prefer_the_published_schedule(self):
        cal = sessions("2026-08-20", "2026-11-30")
        # Cutoff 2026-09-01T23:59:59Z is JST 2026-09-02.
        rows = events.rule_derived_sq_rows(cal, calculation_dates=["2026-09-02"])
        snapshot = features.build_market_features(cutoff="2026-09-01T23:59:59Z", price_series={}, sq_events=rows)
        row = next(r for r in snapshot["features"] if r["seriesId"] == "event.sq_sessions")
        self.assertEqual(row["value"], 7)
        self.assertEqual(row["inputReferences"][0]["sourceRef"], events.SQ_RULE_SOURCE)
        verified = {**rows[0], "calendarStatus": "VERIFIED", "tradingSessionsUntil": 6,
                    "sourceRef": "https://www.jpx.co.jp/official", "knownAt": "2026-01-05T00:00:00Z"}
        both = features.build_market_features(cutoff="2026-09-01T23:59:59Z", price_series={}, sq_events=rows + [verified])
        row = next(r for r in both["features"] if r["seriesId"] == "event.sq_sessions")
        self.assertEqual(row["value"], 6)
        self.assertEqual(row["inputReferences"][0]["sourceRef"], "https://www.jpx.co.jp/official")

    def test_history_reuse_survives_appended_rule_rows_after_the_boundary(self):
        cal = sessions("2026-08-20", "2026-11-30")
        first_rows = events.rule_derived_sq_rows(cal, calculation_dates=["2026-09-02"])
        before = features.build_feature_history(cutoffs=["2026-09-01T23:59:59Z"], price_series={}, sq_events=first_rows)
        before["status"] = "AVAILABLE"
        more = events.rule_derived_sq_rows(cal, calculation_dates=["2026-09-02", "2026-09-03"])
        after = features.build_feature_history(cutoffs=["2026-09-01T23:59:59Z", "2026-09-02T23:59:59Z"],
                                               previous_history=before, price_series={}, sq_events=more)
        self.assertEqual(after["calculationWork"], {"reusedCutoffs": 1, "evaluatedCutoffs": 1})
        self.assertEqual(after["reuseDecision"]["reason"], "unchanged_source_prefix")


if __name__ == "__main__":
    unittest.main()
