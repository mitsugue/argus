import json

import argus_analyst_targets as t
import scanner

PAYLOAD = {"quoteSummary": {"result": [{"financialData": {
    "currentPrice": {"raw": 5598.0}, "targetMeanPrice": {"raw": 7351.6665}, "targetMedianPrice": {"raw": 7500.0},
    "targetHighPrice": {"raw": 11700.0}, "targetLowPrice": {"raw": 3500.0},
    "numberOfAnalystOpinions": {"raw": 12}, "financialCurrency": "JPY", "recommendationKey": "buy"}}]}}


def test_parse_keeps_the_spread_and_count_but_no_recommendation_word():
    row = t.parse_financial_data("5803", PAYLOAD, fetched_at="2026-10-04T11:00:00Z")
    assert (row["mean"], row["median"], row["high"], row["low"], row["analysts"]) == (7351.67, 7500.0, 11700.0, 3500.0, 12)
    assert row["gapPct"] == 31.3 and row["currency"] == "JPY" and row["source"] == "Yahoo Finance"
    assert "buy" not in json.dumps(row) and row["actionAuthority"] is False
    assert t.parse_financial_data("1570", {"quoteSummary": {"result": [{"financialData": {}}]}}, fetched_at="x") is None
    assert t.yahoo_symbol("JP", "5803") == "5803.T" and t.yahoo_symbol("US", "NVDA") == "NVDA"
    assert t.due({"fetchedDayJst": "2026-10-04"}, "2026-10-04") is False and t.due(None, "2026-10-04") is True


def test_warm_fetches_once_a_day_and_the_route_never_fetches(monkeypatch, tmp_path):
    calls = []

    class Response:
        def __init__(self, status, body=None, text=""):
            self.status_code, self._body, self.text = status, body, text
        def json(self):
            return self._body

    class Session:
        headers = {}
        def get(self, url, params=None, **kw):
            calls.append(url)
            if "getcrumb" in url:
                return Response(200, text="crumb123")
            if "quoteSummary/5803.T" in url:
                return Response(200, PAYLOAD)
            if "quoteSummary" in url:
                return Response(200, {"quoteSummary": {"result": [{"financialData": {}}]}})
            return Response(200)

    monkeypatch.setattr(scanner.requests, "Session", Session)
    monkeypatch.setattr(scanner, "_analyst_targets_path", lambda: str(tmp_path / "targets.json"))
    monkeypatch.setattr(scanner, "_analyst_targets_symbols", lambda: [("JP", "5803"), ("JP", "1570")])
    monkeypatch.setattr(scanner, "_ANALYST_TARGETS", {"loaded": False, "items": {}, "lastAttemptAt": None,
                                                      "lastError": None, "fetchedLastWarm": 0})
    scanner._analyst_targets_warm()
    assert scanner._ANALYST_TARGETS["items"]["JP:5803"]["mean"] == 7351.67
    assert scanner._ANALYST_TARGETS["items"]["JP:1570"]["unavailable"] is True
    first = len(calls)
    scanner._analyst_targets_warm()                       # same JST day: nothing fetched
    assert len(calls) == first
    saved = json.loads((tmp_path / "targets.json").read_text())
    assert saved["schemaVersion"] == t.SCHEMA and "JP:5803" in saved["items"]
    client = scanner.app.test_client()
    body = client.get("/api/argus/analyst-targets").get_json()
    assert list(body["items"]) == ["JP:5803"] and body["actionAuthority"] is False
    assert len(calls) == first                            # the route never fetches


def test_failed_attempt_retains_price_date_and_is_due_only_next_day():
    previous = {**t.parse_financial_data('1001', PAYLOAD, fetched_at='2026-10-05T03:00:00Z'),
                'market': 'JP', 'fetchedDayJst': '2026-10-05'}
    result = t.attempt_result(previous, None, market='JP', symbol='1001',
        today='2026-10-06', at='2026-10-06T03:00:00Z', status='HTTP_503')
    assert result['mean'] == previous['mean'] and result['fetchedAt'] == previous['fetchedAt']
    assert result['acquisitionStatus'] == 'HTTP_503' and not result.get('unavailable')
    assert not t.due(result, '2026-10-06') and t.due(result, '2026-10-07')


def test_invalid_analyst_counts_and_nonpositive_current_price():
    import copy
    for count in (-1, 0, 1.5, float('inf'), float('nan'), True):
        payload = copy.deepcopy(PAYLOAD)
        payload['quoteSummary']['result'][0]['financialData']['numberOfAnalystOpinions'] = {'raw': count}
        assert t.parse_financial_data('1001', payload, fetched_at='2026-10-06T03:00:00Z') is None
    payload = copy.deepcopy(PAYLOAD)
    payload['quoteSummary']['result'][0]['financialData']['currentPrice'] = {'raw': -3}
    row = t.parse_financial_data('1001', payload, fetched_at='2026-10-06T03:00:00Z')
    assert row['priceAtFetch'] is None and row['gapPct'] is None
    assert t.parse_financial_data('1001', {'quoteSummary': {'result': [{'financialData': None}]}}, fetched_at='x') is None


def test_restart_reads_saved_targets_without_waiting_for_collector(monkeypatch, tmp_path):
    path = tmp_path / 'targets.json'
    saved = {**t.parse_financial_data('1001', PAYLOAD, fetched_at='2026-10-05T03:00:00Z'), 'market': 'JP', 'currency':'USD'}
    adr = {**saved, 'market':'US', 'symbol':'TM', 'currency':'JPY'}
    path.write_text(json.dumps({'schemaVersion': t.SCHEMA, 'items': {'JP:1001': saved, 'US:TM':adr}}))
    original_bytes = path.read_bytes()
    monkeypatch.setattr(scanner, '_analyst_targets_path', lambda: str(path))
    monkeypatch.setattr(scanner, '_ANALYST_TARGETS', {'loaded': False, 'items': {}, 'lastAttemptAt': None, 'lastError': None})
    class NoNetwork:
        def __getattr__(self, key): raise AssertionError('network forbidden')
    monkeypatch.setattr(scanner, 'requests', NoNetwork())
    # An ongoing provider collection must not block an initial card read.
    assert scanner._ANALYST_TARGETS_LOCK.acquire(blocking=False)
    try:
        result = scanner.app.test_client().get('/api/argus/analyst-targets').get_json()
    finally:
        scanner._ANALYST_TARGETS_LOCK.release()
    assert result['items']['JP:1001']['fetchedAt'] == saved['fetchedAt']
    assert result['items']['JP:1001']['currency'] == 'JPY'
    assert result['items']['US:TM']['currency'] == 'USD'
    assert result['items']['US:TM']['mean'] == adr['mean']
    assert path.read_bytes() == original_bytes
    assert result['actionAuthority'] is False


def test_per_symbol_failure_does_not_drop_saved_target_or_stop_the_batch(monkeypatch, tmp_path):
    import copy
    today = scanner.datetime.now(scanner.TZ_JST).strftime('%Y-%m-%d')
    old = {**t.parse_financial_data('1001', PAYLOAD, fetched_at='2026-10-05T03:00:00Z'),
           'market': 'JP', 'fetchedDayJst': '2000-01-01'}
    calls = []
    class Response:
        def __init__(self, status, body=None, text=''): self.status_code, self.body, self.text = status, body, text
        def json(self):
            if self.body is None: raise ValueError('bad JSON')
            return self.body
    class Session:
        headers = {}
        def get(self, url, **kwargs):
            calls.append(url)
            if 'getcrumb' in url: return Response(200, text='crumb123')
            if '/1001.T' in url: return Response(200)  # malformed body for just this symbol
            if '/1002.T' in url:
                data = copy.deepcopy(PAYLOAD)
                data['quoteSummary']['result'][0]['financialData']['financialCurrency'] = 'USD'
                return Response(200, data)
            return Response(404)
        def close(self): calls.append('closed')
    monkeypatch.setattr(scanner.requests, 'Session', Session)
    monkeypatch.setattr(scanner, '_analyst_targets_path', lambda: str(tmp_path / 'targets.json'))
    monkeypatch.setattr(scanner, '_analyst_targets_symbols', lambda: [('JP','1001'), ('JP','1002')])
    monkeypatch.setattr(scanner, '_ANALYST_TARGETS', {'loaded': True, 'items': {'JP:1001': old}, 'lastError': None})
    scanner._analyst_targets_warm()
    rows = scanner._ANALYST_TARGETS['items']
    assert rows['JP:1001']['fetchedAt'] == old['fetchedAt'] and rows['JP:1001']['acquisitionStatus'] == 'FETCH_FAILED'
    assert rows['JP:1002']['currency'] == 'JPY' and rows['JP:1002']['acquisitionStatus'] == 'AVAILABLE'
    assert rows['JP:1001']['attemptDayJst'] == today and calls[-1] == 'closed'
    before = len(calls)
    scanner._analyst_targets_warm()
    assert len(calls) == before
