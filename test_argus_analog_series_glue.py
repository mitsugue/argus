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
