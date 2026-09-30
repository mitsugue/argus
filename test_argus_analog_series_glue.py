"""Market-condition series glue (2026-09-30): USD/JPY, US 10y and TOPIX
histories reach the feature warm with scheduled availability, cached-only on
the public path, and nothing is filled or displayed as an index level."""
import json
import time
import unittest
from unittest import mock

import scanner


class _Resp:
    def __init__(self, payload, status=200):
        self._payload = payload; self.status_code = status
        self.content = json.dumps(payload).encode()
    def json(self): return self._payload
    def raise_for_status(self):
        if self.status_code != 200: raise RuntimeError("http")


class Us10yTest(unittest.TestCase):
    def setUp(self):
        scanner._US10Y_HIST_DATED_CACHE.update(data=None, expires=0.0)

    def test_dated_rows_are_percent_yields_available_two_days_later(self):
        # The dated-history cache keeps a series only from one hundred rows on.
        observations = [{"date": f"2026-0{m}-{d:02d}", "value": str(4 + d / 100)}
                        for m in (5, 6, 7, 8, 9) for d in range(1, 29)]
        observations.append({"date": "2026-09-29", "value": "."})
        with mock.patch.object(scanner, "_FRED_API_KEY", "k"), \
                mock.patch.object(scanner.requests, "get", return_value=_Resp({"observations": observations})):
            rows = scanner._fred_us10y_history_dated()
        self.assertEqual(len(rows), 140)
        row = rows[-1]
        self.assertEqual((row["instrumentId"], row["seriesId"], row["unit"]), ("US10Y", "yield", "PERCENT"))
        self.assertEqual(row["date"], "2026-09-28")
        self.assertEqual(row["availableFrom"], "2026-09-30T00:00:00Z")
        self.assertEqual(row["availabilityBasis"], "SCHEDULED_PUBLICATION")
        self.assertIs(row["historicalVintageVerified"], False)
        # Cached-only read never requests.
        with mock.patch.object(scanner.requests, "get", side_effect=AssertionError("no request")):
            self.assertEqual(scanner._fred_us10y_history_dated(fetch=False), rows)
        scanner._US10Y_HIST_DATED_CACHE.update(data=None, expires=0.0)
        with mock.patch.object(scanner.requests, "get", side_effect=AssertionError("no request")):
            self.assertEqual(scanner._fred_us10y_history_dated(fetch=False), [])

    def test_vix_rows_keep_their_date_only_stamp(self):
        scanner._VIX_HIST_DATED_CACHE.update(data=None, expires=0.0)
        observations = [{"date": f"2026-09-{d:02d}", "value": "15"} for d in range(1, 29)] * 4
        with mock.patch.object(scanner, "_FRED_API_KEY", "k"), \
                mock.patch.object(scanner.requests, "get", return_value=_Resp({"observations": observations})):
            rows = scanner._fred_vix_history_dated()
        self.assertEqual(rows[0]["availableFrom"], "2026-09-02")
        scanner._VIX_HIST_DATED_CACHE.update(data=None, expires=0.0)


class TopixTest(unittest.TestCase):
    def setUp(self):
        scanner._TOPIX_HIST_CACHE.update(data=None, expires=0.0, status="NOT_RUN")

    def test_public_path_is_cached_only_and_warm_normalizes_with_next_day_availability(self):
        with mock.patch.object(scanner, "_jquants_paginated", side_effect=AssertionError("no request")):
            self.assertEqual(scanner._jquants_topix_history(fetch=False), [])
        bars = [{"Date": "2026-09-29", "O": 3000.0, "H": 3010.0, "L": 2990.0, "C": 3005.0},
                {"Date": "2026-09-30", "O": 3005.0, "H": 3020.0, "L": 3001.0, "C": 3015.0}]
        calls = []
        def paginated(path, params, **kwargs):
            calls.append((path, params)); return bars
        with mock.patch.object(scanner, "_JQUANTS_API_KEY", "k"), \
                mock.patch.object(scanner, "_jquants_paginated", side_effect=paginated):
            rows = scanner._jquants_topix_history(fetch=True)
        self.assertEqual(calls[0][0], "/indices/bars/daily/topix")
        self.assertEqual([r["date"] for r in rows], ["2026-09-29", "2026-09-30"])
        self.assertEqual(rows[0]["instrumentId"], "TOPIX_INDEX")
        self.assertEqual(rows[0]["availableFrom"], "2026-09-30T00:00:00Z")
        self.assertEqual(scanner._TOPIX_HIST_CACHE["status"], "AVAILABLE")
        # Within the six-hour window the warm does not request again.
        with mock.patch.object(scanner, "_jquants_paginated", side_effect=AssertionError("no request")):
            self.assertEqual(scanner._jquants_topix_history(fetch=True), rows)

    def test_missing_key_and_provider_failure_are_named_not_raised(self):
        with mock.patch.object(scanner, "_JQUANTS_API_KEY", None):
            self.assertEqual(scanner._jquants_topix_history(fetch=True), [])
        self.assertEqual(scanner._TOPIX_HIST_CACHE["status"], "KEY_NOT_CONFIGURED")
        with mock.patch.object(scanner, "_JQUANTS_API_KEY", "k"), \
                mock.patch.object(scanner, "_jquants_paginated", side_effect=RuntimeError("jquants_http_403")):
            self.assertEqual(scanner._jquants_topix_history(fetch=True), [])
        self.assertEqual(scanner._TOPIX_HIST_CACHE["status"], "FETCH_FAILED:RuntimeError")


class YahooRangeTest(unittest.TestCase):
    def test_usdjpy_requests_ten_years_and_n225_keeps_its_window(self):
        seen = []
        def get(url, params=None, headers=None, timeout=None):
            seen.append(params["range"]); return _Resp({"chart": {"result": []}})
        scanner._JP_MARKET_ENGINE_INDEX_OHLCV_CACHE.pop("JPY=X", None)
        with mock.patch.object(scanner.requests, "get", side_effect=get):
            scanner._yahoo_index_ohlcv("JPY=X", "USDJPY", fetch=True, next_day_available=True, range_="10y")
        self.assertEqual(seen, ["10y"])
        scanner._JP_MARKET_ENGINE_INDEX_OHLCV_CACHE.pop("JPY=X", None)


if __name__ == "__main__":
    unittest.main()


class BackfillWindowTest(unittest.TestCase):
    def test_margin_and_investor_windows_depend_on_store_depth(self):
        from datetime import date
        today = date(2026, 9, 30)
        recent = [{"periodEnd": "2026-07-03"}, {"periodEnd": "2026-09-25"}]
        deep = recent + [{"periodEnd": "2017-01-06"}]
        self.assertEqual(scanner._jq_margin_backfill_window_days(recent, today), 3640)
        self.assertEqual(scanner._jq_margin_backfill_window_days([], today), 3640)
        self.assertIsNone(scanner._jq_margin_backfill_window_days(deep, today))
        self.assertEqual(scanner._investor_types_window_days(recent, today), 3640)
        self.assertEqual(scanner._investor_types_window_days(deep, today), 45)
        self.assertEqual(scanner._investor_types_window_days([{"periodEnd": None}, "x"], today), 3640)


class SqEventInputsTest(unittest.TestCase):
    def test_rule_rows_for_history_and_published_rows_for_today(self):
        from datetime import date, timedelta
        bars = [{"date": (date(2026, 8, 3) + timedelta(days=n)).isoformat()} for n in range(0, 40)
                if (date(2026, 8, 3) + timedelta(days=n)).weekday() < 5]
        calendar = [{"Date": (date(2026, 8, 1) + timedelta(days=n)).isoformat(),
                     "HolDiv": "1" if (date(2026, 8, 1) + timedelta(days=n)).weekday() < 5 else "0"} for n in range(0, 120)]
        published = {"events": [{"eventId": "jp-monthly-sq-2026-10", "sqDate": "2026-10-09", "calendarStatus": "VERIFIED",
                                 "calculatedAt": "2026-09-30T08:00:00+00:00", "knownAt": "2026-09-11T11:17:56+00:00",
                                 "tradingSessionsUntil": 7, "sourceRef": "https://www.jpx.co.jp/x"},
                                {"eventId": "conflict", "calendarStatus": "UNAVAILABLE_OR_CONFLICT"}]}
        with mock.patch.dict(scanner._N225_ANALOG_HISTORY, {"calendar": calendar}), \
                mock.patch.object(scanner.jp_market_events, "published_sq_calendar", return_value=published):
            rows = scanner._jp_market_feature_sq_events(bars, "2026-09-30T08:00:00Z")
        rule = [r for r in rows if r["calendarStatus"] == "RULE_DERIVED"]
        verified = [r for r in rows if r["calendarStatus"] == "VERIFIED"]
        self.assertEqual(len(verified), 1)
        self.assertTrue(rule and all(r["sourceRef"] == scanner.jp_market_events.SQ_RULE_SOURCE for r in rule))
        # History rows are keyed by the JST date after each bar; today's JST date is present too.
        dates = {r["date"] for r in rule}
        self.assertIn("2026-08-04", dates)
        self.assertIn("2026-09-30", dates)
        self.assertEqual(next(r for r in rule if r["date"] == "2026-08-04")["sqDate"], "2026-08-14")
        # A calendar failure leaves only the published rows, never an exception.
        with mock.patch.object(scanner, "_jp_exchange_sessions", side_effect=ValueError("calendar")), \
                mock.patch.object(scanner.jp_market_events, "published_sq_calendar", return_value=published):
            self.assertEqual(len(scanner._jp_market_feature_sq_events(bars, "2026-09-30T08:00:00Z")), 1)
        with mock.patch.object(scanner.jp_market_events, "published_sq_calendar", side_effect=OSError("missing")):
            self.assertEqual(scanner._jp_market_feature_sq_events([], "2026-09-30T08:00:00Z"), [])


class MarginBackfillTest(unittest.TestCase):
    def test_backfill_appends_once_a_day_and_names_failures(self):
        scanner._JQ_MARGIN_BACKFILL.update(lastAttemptDay=None, status="NOT_RUN")
        saved = scanner._JQ_MARGIN_CACHE.pop("1570", None)
        rows = [{"Code": "15700", "Date": "2017-01-06", "LongVol": 1000, "ShrtVol": 500},
                {"Code": "15700", "Date": "2026-09-25", "LongVol": 2000, "ShrtVol": 800}]
        calls = []
        try:
            with mock.patch.object(scanner, "_JQUANTS_API_KEY", "k"), \
                    mock.patch.object(scanner, "_cost_policy_durable_enabled", return_value=False), \
                    mock.patch.object(scanner, "_jquants_paginated", side_effect=lambda p, q: calls.append((p, q)) or rows), \
                    mock.patch.object(scanner, "_ai_now_iso", return_value="2026-09-30T09:00:00Z"):
                self.assertEqual(scanner._jq_margin_history_backfill(), "APPENDED:4")
                self.assertEqual(calls[0][0], "/markets/margin-interest")
                self.assertEqual(calls[0][1]["code"], "1570")
                stored = scanner._JQ_MARGIN_CACHE["1570"]["sourceSnapshot"]["rows"]
                self.assertEqual(sorted({r["periodEnd"] for r in stored}), ["2017-01-06", "2026-09-25"])
                # Same day: no second request. Store now reaches nine years back: no window either.
                self.assertEqual(scanner._jq_margin_history_backfill(), "APPENDED:4")
                self.assertEqual(len(calls), 1)
            scanner._JQ_MARGIN_BACKFILL.update(lastAttemptDay=None)
            scanner._JQ_MARGIN_CACHE.pop("1570", None)
            with mock.patch.object(scanner, "_JQUANTS_API_KEY", "k"), \
                    mock.patch.object(scanner, "_cost_policy_durable_enabled", return_value=False), \
                    mock.patch.object(scanner, "_jquants_paginated", side_effect=RuntimeError("jquants_http_403")), \
                    mock.patch.object(scanner, "_ai_now_iso", return_value="2026-10-01T09:00:00Z"):
                self.assertEqual(scanner._jq_margin_history_backfill(), "FAILED:RuntimeError")
        finally:
            scanner._JQ_MARGIN_CACHE.pop("1570", None)
            if saved is not None:
                scanner._JQ_MARGIN_CACHE["1570"] = saved
            scanner._JQ_MARGIN_BACKFILL.update(lastAttemptDay=None, status="NOT_RUN")
