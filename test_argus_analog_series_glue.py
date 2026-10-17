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
        import sys
        scanner._TOPIX_HIST_CACHE.update(data=None, expires=0.0, status="NOT_RUN")
        # The official client path is tried first; make it unavailable here so
        # the raw-endpoint fallback is exercised without any network access.
        self._client = mock.patch.dict(sys.modules, {"jquantsapi": None})
        self._client.start()

    def tearDown(self):
        self._client.stop()

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
        self.assertEqual(rows[0]["availableFrom"], "2026-09-29T09:00:00Z")
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


class ComparisonRetentionTest(unittest.TestCase):
    def test_warm_keeps_saved_market_condition_comparison_while_history_recalculates(self):
        import argus_index_research_cache as cache
        market = {"status": "available", "comparison": {"candidates": [{"missingGroups": ["materialReaction"]}], "limitations": []}}
        shape_only = {"status": "available", "comparison": {"candidates": [{"missingGroups": ["marketState", "conditionOrder", "materialReaction"]}], "limitations": []}}
        saved = {f"comparison:N225:{h}": cache.record(f"comparison:N225:{h}", market, method=scanner._INDEX_RESEARCH_METHOD,
                                                       at="2026-09-30T06:00:00Z") for h in (1, 5, 10, 20)}
        status = {"status": "NOT_RUN", "restoreAttempted": True}
        with mock.patch.object(scanner, "_INDEX_RESEARCH_REPORTS", dict(saved)) as reports, \
                mock.patch.object(scanner, "_INDEX_RESEARCH_STATUS", status), \
                mock.patch.object(scanner, "_JP_MARKET_FEATURE_HISTORY", {"status": "NOT_RUN", "features": []}), \
                mock.patch.object(scanner, "_index_research_path", return_value=None), \
                mock.patch.object(scanner, "_index_chart_calculate", return_value={"status": "unavailable"}), \
                mock.patch.object(scanner, "_jp_market_comparison_calculate", return_value=shape_only), \
                mock.patch.object(scanner, "_ai_now_iso", return_value="2026-09-30T09:30:00Z"):
            scanner._index_research_warm()
            self.assertEqual(set(status["retained"]), set(saved))
            self.assertEqual(status["retained"]["comparison:N225:5"]["reason"], "feature_history_recalculating")
            self.assertEqual(reports["comparison:N225:5"], saved["comparison:N225:5"])
            served = scanner._index_research_read("comparison:N225:5")
            self.assertIn("再計算中", served["comparison"]["retainedNoteJa"])
            self.assertEqual(served["researchCache"]["retained"]["reason"], "feature_history_recalculating")
            # History back: the fresh market-condition result replaces the saved one.
            status["lastAttemptMonotonic"] = None
            with mock.patch.object(scanner, "_JP_MARKET_FEATURE_HISTORY", {"status": "AVAILABLE", "features": [1]}), \
                    mock.patch.object(scanner, "_jp_market_comparison_calculate", return_value=market):
                scanner._index_research_warm()
            self.assertEqual(status["retained"], {})
            self.assertEqual(reports["comparison:N225:5"]["calculatedAt"], "2026-09-30T09:30:00Z")


class IndexPerInputTest(unittest.TestCase):
    def test_proxy_per_rows_reach_the_feature_warm_labelled(self):
        history = [{"date": "2026-09-28", "availableFrom": "2026-09-28T07:00:00+00:00", "eps": 3000.0, "per": 19.2,
                    "epsVariant": "FORECAST_COVERED_ONLY", "basis": "ARGUS_PROXY_INDEX_BASED_PER", "sourceRef": "x"},
                   {"date": "2026-09-29", "availableFrom": None, "eps": 3000.0, "per": 19.4},
                   {"date": "2026-09-30", "availableFrom": "2026-09-30T07:00:00+00:00", "eps": 3000.0, "per": None}]
        captured = {}
        def fake_history(**kwargs):
            captured.update(kwargs); raise RuntimeError("stop")
        with mock.patch.object(scanner, "_jp_index_proxy_eps_history", return_value=history), \
                mock.patch.object(scanner.jp_market_features, "build_feature_history", side_effect=fake_history), \
                mock.patch.dict(scanner._N225_ANALOG_HISTORY, {"data": [{"date": "2026-09-29", "close": 1.0}]}), \
                mock.patch.object(scanner, "_cost_policy_durable_enabled", return_value=False):
            scanner._jp_market_feature_history_warm()
        rows = captured["price_series"]["index_per"]
        self.assertEqual([(r["date"], r["value"]) for r in rows], [("2026-09-28", 19.2)])
        self.assertEqual(rows[0]["instrumentId"], "NIKKEI_225_PER")
        self.assertEqual(rows[0]["derivationBasis"], "ARGUS_PROXY_INDEX_BASED_PER")


class TopixClientPathTest(unittest.TestCase):
    def test_official_client_rows_are_normalized_and_path_recorded(self):
        import sys, types
        scanner._TOPIX_HIST_CACHE.update(data=None, expires=0.0, status="NOT_RUN")
        class Frame:
            def to_dict(self, orient):
                return [{"Date": "2026-09-29 00:00:00", "O": 3000.0, "H": 3010.0, "L": 2990.0, "C": 3005.0}]
        seen = {}
        class Client:
            def __init__(self, api_key): seen["key"] = api_key
            def get_idx_bars_daily_topix(self, from_yyyymmdd, to_yyyymmdd):
                seen["range"] = (from_yyyymmdd, to_yyyymmdd); return Frame()
        module = types.SimpleNamespace(ClientV2=Client)
        with mock.patch.dict(sys.modules, {"jquantsapi": module}), \
                mock.patch.object(scanner, "_JQUANTS_API_KEY", "k"), \
                mock.patch.object(scanner, "_jquants_paginated", side_effect=AssertionError("fallback not needed")):
            rows = scanner._jquants_topix_history(fetch=True)
        self.assertEqual([r["date"] for r in rows], ["2026-09-29"])
        self.assertEqual(scanner._TOPIX_HIST_CACHE["path"], "jquantsapi_client")
        self.assertEqual(len(seen["range"][0]), 8)
        status = scanner._jp_market_series_acquisition_status()
        self.assertEqual(status["topix"]["rows"], 1)
        self.assertEqual(status["topix"]["first"], "2026-09-29")
        self.assertEqual(set(status), {"topix", "usdjpy", "us10y", "margin1570", "foreignFlow"})
        scanner._TOPIX_HIST_CACHE.update(data=None, expires=0.0, status="NOT_RUN", path=None)


class BacktestWiringTest(unittest.TestCase):
    def test_comparison_passes_the_shared_backtest_cache(self):
        captured = {}
        def fake(rows, **kwargs):
            captured.update(kwargs); return {"status": "unavailable", "comparison": None}
        with mock.patch.dict(scanner._N225_ANALOG_HISTORY, {"data": [{"date": "2026-09-29", "close": 1.0},
                                                                     {"date": "2026-09-30", "close": 1.0}]}), \
                mock.patch.object(scanner.jp_market_price_paths, "cached_index_comparison", side_effect=fake):
            scanner._jp_market_comparison_calculate(5)
        self.assertIs(captured["backtest_cache"], scanner._JP_ANALOG_BACKTEST_CACHE)


class ResearchAfterFeaturesTest(unittest.TestCase):
    def test_a_new_feature_history_lifts_the_research_throttle(self):
        status = {"status": "AVAILABLE", "restoreAttempted": True, "lastAttemptMonotonic": time.monotonic()}
        history = {"status": "AVAILABLE", "features": [], "conditions": [], "latest": {}}
        with mock.patch.object(scanner, "_INDEX_RESEARCH_STATUS", status), \
                mock.patch.object(scanner.jp_market_features, "build_feature_history", return_value=history), \
                mock.patch.object(scanner, "_jp_market_feature_history_persist", lambda *a, **k: None), \
                mock.patch.dict(scanner._N225_ANALOG_HISTORY, {"data": [{"date": "2026-09-29", "close": 1.0}]}), \
                mock.patch.object(scanner, "_JP_MARKET_FEATURE_HISTORY", {"status": "NOT_RUN", "features": [], "conditions": []}), \
                mock.patch.object(scanner, "_cost_policy_durable_enabled", return_value=False):
            scanner._jp_market_feature_history_warm()
            self.assertEqual(scanner._JP_MARKET_FEATURE_HISTORY["status"], "AVAILABLE")
        self.assertIsNone(status["lastAttemptMonotonic"])


class OwnerAuthBucketTest(unittest.TestCase):
    def test_owner_auth_has_its_own_rate_bucket(self):
        scanner._RL_BUCKETS.clear()
        client = scanner.app.test_client()
        with mock.patch.object(scanner, "_RL_MAX", 3), mock.patch.object(scanner, "_RL_MAX_HEAVY", 3):
            for _ in range(3):
                client.get("/api/argus/operational")
            self.assertEqual(client.get("/api/argus/operational").status_code, 429)
            # Data polling exhausted its bucket; the owner session check is unaffected.
            self.assertNotEqual(client.get("/api/argus/owner-auth/session").status_code, 429)
        scanner._RL_BUCKETS.clear()


class TenYearIndexHistoryTest(unittest.TestCase):
    """2026-10-03: D03 (Japan/US relative strength) and D06 (VIX MACD) had a
    record only from late 2024 because the S&P 500 and VIX histories were two years."""
    def setUp(self):
        self.saved = dict(scanner._JP_MARKET_ENGINE_INDEX_OHLCV_CACHE)
        scanner._JP_MARKET_ENGINE_INDEX_OHLCV_CACHE.clear()

    def tearDown(self):
        scanner._JP_MARKET_ENGINE_INDEX_OHLCV_CACHE.clear()
        scanner._JP_MARKET_ENGINE_INDEX_OHLCV_CACHE.update(self.saved)

    @staticmethod
    def _chart(days):
        import calendar, datetime as dt
        stamps = [calendar.timegm(dt.datetime.strptime(d, "%Y-%m-%d").timetuple()) + 20 * 3600 for d in days]
        n = len(days)
        return {"chart": {"result": [{"meta": {"gmtoffset": 0}, "timestamp": stamps,
                "indicators": {"quote": [{"open": [1.0] * n, "high": [2.0] * n, "low": [0.5] * n,
                                           "close": [1.5] * n, "volume": [0] * n}]}}]}}

    def test_vix_and_sp500_are_requested_for_ten_years(self):
        seen = []
        def get(url, params=None, **kwargs):
            seen.append((url.rsplit("/", 1)[1], params["range"]))
            return _Resp(self._chart(["2026-10-01", "2026-10-02"]))
        with mock.patch.object(scanner.requests, "get", side_effect=get):
            rows, source = scanner._jp_market_engine_vix_rows(fetch=True)
            scanner._yahoo_index_ohlcv("^GSPC", "SP500_INDEX", fetch=True, next_day_available=True, range_="10y")
        self.assertEqual(source, "yahoo_ohlcv")
        self.assertEqual(seen, [("^VIX", "10y"), ("^GSPC", "10y")])
        self.assertEqual(rows[-1]["availableFrom"], "2026-10-03T00:00:00Z")
        import inspect
        self.assertIn('_yahoo_index_ohlcv("^GSPC", "SP500_INDEX", fetch=warm, next_day_available=True, range_="10y")',
                      inspect.getsource(scanner._jp_market_engine_pit_inputs))

    def test_a_shorter_refetch_keeps_the_longer_history(self):
        with mock.patch.object(scanner.requests, "get",
                               return_value=_Resp(self._chart(["2017-01-03", "2020-06-01", "2026-09-30"]))):
            first = scanner._yahoo_index_ohlcv("^GSPC", "SP500_INDEX", fetch=True, next_day_available=True, range_="10y")
        self.assertEqual([r["date"] for r in first], ["2017-01-03", "2020-06-01", "2026-09-30"])
        scanner._JP_MARKET_ENGINE_INDEX_OHLCV_CACHE["^GSPC"]["expires"] = 0.0
        with mock.patch.object(scanner.requests, "get",
                               return_value=_Resp(self._chart(["2026-09-30", "2026-10-01"]))):
            again = scanner._yahoo_index_ohlcv("^GSPC", "SP500_INDEX", fetch=True, next_day_available=True)
        self.assertEqual([r["date"] for r in again], ["2017-01-03", "2020-06-01", "2026-09-30", "2026-10-01"])


    def test_fresh_two_year_cache_does_not_satisfy_ten_year_warm(self):
        seen = []
        def get(url, params=None, **kwargs):
            seen.append(params['range'])
            return _Resp(self._chart(['2017-01-03', '2026-10-02'] if params['range'] == '10y'
                                     else ['2024-10-03', '2026-10-02']))
        with mock.patch.object(scanner.requests, 'get', side_effect=get):
            scanner._yahoo_index_ohlcv('^GSPC', 'SP500_INDEX', fetch=True, next_day_available=True)
            # Reading, including a requested longer scope, never fetches.
            short = scanner._yahoo_index_ohlcv('^GSPC', 'SP500_INDEX', range_='10y')
            self.assertEqual(short[0]['date'], '2024-10-03')
            long = scanner._yahoo_index_ohlcv('^GSPC', 'SP500_INDEX', fetch=True,
                                             next_day_available=True, range_='10y')
            scanner._yahoo_index_ohlcv('^GSPC', 'SP500_INDEX', fetch=True,
                                      next_day_available=True, range_='10y')
        self.assertEqual(seen, ['2y', '10y'])
        self.assertEqual(long[0]['date'], '2017-01-03')

    def test_failed_scope_upgrade_keeps_short_history_and_retry_delay(self):
        with mock.patch.object(scanner.requests, 'get', return_value=_Resp(self._chart(['2024-10-03', '2026-10-02']))):
            previous = scanner._yahoo_index_ohlcv('^GSPC', 'SP500_INDEX', fetch=True, next_day_available=True)
        with mock.patch.object(scanner.requests, 'get', side_effect=RuntimeError('synthetic_failure')) as get:
            retained = scanner._yahoo_index_ohlcv('^GSPC', 'SP500_INDEX', fetch=True,
                                                 next_day_available=True, range_='10y')
            scanner._yahoo_index_ohlcv('^GSPC', 'SP500_INDEX', fetch=True,
                                      next_day_available=True, range_='10y')
        self.assertEqual(get.call_count, 1)
        self.assertEqual(retained, previous)
        self.assertEqual(scanner._JP_MARKET_ENGINE_INDEX_OHLCV_CACHE['^GSPC']['lastFetchStatus'], 'FAILED')

    def test_legacy_scope_is_upgraded_once_without_discarding_prior_rows(self):
        scanner._JP_MARKET_ENGINE_INDEX_OHLCV_CACHE['^GSPC'] = {
            'data': [{'date':'2016-10-03', 'close':1.5}], 'expires':scanner.time.time() + 1800}
        with mock.patch.object(scanner.requests, 'get', return_value=_Resp(self._chart(['2026-10-02']))) as get:
            rows = scanner._yahoo_index_ohlcv('^GSPC', 'SP500_INDEX', fetch=True,
                                            next_day_available=True, range_='10y')
            scanner._yahoo_index_ohlcv('^GSPC', 'SP500_INDEX', fetch=True,
                                      next_day_available=True, range_='10y')
        self.assertEqual(get.call_count, 1)
        self.assertEqual(rows[0]['date'], '2016-10-03')
