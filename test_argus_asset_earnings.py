import copy
import json
import pytest
from datetime import datetime, timezone

import argus_asset_earnings as earnings
import argus_earnings_history
import scanner

AT = '2026-10-07T10:00:00Z'
TODAY = '2026-10-07'
def epoch(day):
    return int(datetime.fromisoformat(day).replace(tzinfo=timezone.utc).timestamp())

PAYLOAD = {'quoteSummary': {'result': [{
    'financialData': {'financialCurrency': 'JPY'},
    'calendarEvents': {'earnings': {'earningsDate': [{'raw': epoch('2026-11-02T21:00:00')}, {'raw': epoch('2026-11-04T21:00:00')}] }},
    'earningsHistory': {'history': [{'quarter': {'raw': epoch('2026-06-30T00:00:00')}, 'currency': 'USD', 'epsActual': {'raw': -2}, 'epsEstimate': {'raw': -3}}]},
    'earningsTrend': {'trend': [{'period': '0q', 'endDate': '2026-09-30',
        'earningsEstimate': {'earningsCurrency': 'USD', 'avg': {'raw': 2}, 'low': {'raw': 1}, 'high': {'raw': 3}, 'numberOfAnalysts': {'raw': 8}, 'growth': {'raw': .25}},
        'revenueEstimate': {'revenueCurrency': 'JPY', 'avg': {'raw': 123456789}, 'numberOfAnalysts': {'raw': 7}},
        'epsTrend': {'epsTrendCurrency': 'USD', '30daysAgo': {'raw': 1.5}}}]}
}]}}

def parse(payload=PAYLOAD, market='US'):
    return earnings.parse('TEST', market, payload, fetched_at=AT, today=TODAY)


def test_calendar_market_dates_period_end_and_reporting_currency_are_distinct():
    row = parse()
    assert row['next'] == {'from': '2026-11-02', 'to': '2026-11-04', 'certainty': 'PROVIDER_ESTIMATE', 'timezone': 'America/New_York'}
    assert parse(market='JP')['next']['from'] == '2026-11-03'
    assert row['previous']['periodEnd'] == '2026-06-30'  # Not June 29 in New York; not an announcement day.
    assert row['previous']['surprisePct'] == pytest.approx(100 / 3)
    assert row['previous']['currency'] == 'USD' and row['estimate']['epsCurrency'] == 'USD'
    assert row['estimate']['revenueCurrency'] == 'JPY' and row['estimate']['eps30DaysAgo'] == 1.5
    assert row['currency'] == 'JPY'  # US ADR reporting currency must not become USD.
    assert row['estimate']['eps'] == 2 and row['estimate']['epsGrowthPct'] == 25
    assert row['estimate']['revenueAnalysts'] == 7 and row['actionAuthority'] is False
    assert earnings.market_today(at='2026-10-08T00:01:00+09:00', market='US') == '2026-10-07'


def test_missing_invalid_and_expired_dates_never_become_confirmed_or_zero_estimates():
    value = copy.deepcopy(PAYLOAD)
    data = value['quoteSummary']['result'][0]
    data['calendarEvents']['earnings']['earningsDate'] = [{'raw': epoch('2020-01-01T21:00:00')}, {'raw': True}, {'raw': -1}, {'raw': float('inf')}]
    data['earningsHistory']['history'][0]['epsEstimate'] = {'raw': 0}
    data['earningsTrend']['trend'][0]['earningsEstimate']['numberOfAnalysts'] = {'raw': 1.5}
    row = parse(value)
    assert row['next'] is None and row['previous']['surprisePct'] is None
    assert row['estimate']['eps'] is None and row['estimate']['analysts'] is None
    for payload in ({}, {'quoteSummary': {'result': [None]}}, {'quoteSummary': {'result': [{'financialData': {}}]}}):
        assert parse(payload) is None
    assert earnings.day('2026-02-31', 'JP') is None


def test_company_latest_result_excludes_forecast_revision_and_preserves_zero_profit():
    def observation(doc, day, **patch):
        return {'receivedAt': AT, 'summary': {'DocType': doc, 'DiscDate': day, 'CurPerEn': '2026-06-30',
            'CurPerType': '1Q', 'CurFYEn': '2027-03-31', 'OP': '0', 'FOP': '500000000', **patch}}
    row = earnings.company_summary([observation('1QFinancialStatements_Consolidated', '2026-07-31'),
        observation('ForecastRevision', '2026-10-01', OP='9999'), observation('2QFinancialStatements', '2027-01-01')], today=TODAY)
    assert row['disclosedDate'] == '2026-07-31' and row['operatingProfit'] == 0
    assert row['forecastOperatingProfit'] == 500000000 and row['periodType'] == '1Q'
    assert earnings.company_summary([], today=TODAY) is None


def test_failed_acquisition_preserves_original_earnings_and_success_empty_clears_old_schedule():
    previous = {'earnings': parse()}
    failed = earnings.attach(previous, {}, earnings=None, success=False)
    assert failed['earnings'] == previous['earnings'] and failed['earningsStatus'] == 'FETCH_FAILED'
    cleared = earnings.attach(previous, {}, earnings=None, success=True)
    assert cleared['earnings'] is None and cleared['earningsStatus'] == 'NO_DATA'


def test_no_target_earnings_are_persisted_and_cached_get_never_fetches(monkeypatch, tmp_path):
    calls = []
    class Response:
        status_code = 200
        text = 'public-test-crumb'
        def json(self): return PAYLOAD
    class Session:
        headers = {}
        def get(self, url, **kw):
            calls.append((url, kw))
            return Response()
        def close(self): pass
    path = tmp_path / 'analyst_targets.json'
    monkeypatch.setattr(scanner.requests, 'Session', Session)
    monkeypatch.setattr(scanner, '_analyst_targets_symbols', lambda: [('US', 'TEST')])
    monkeypatch.setattr(scanner, '_analyst_targets_path', lambda: str(path))
    monkeypatch.setattr(scanner, '_ANALYST_TARGETS', {'loaded': False, 'items': {}, 'lastAttemptAt': None, 'lastError': None})
    scanner._analyst_targets_warm()
    assert 'calendarEvents' in calls[-1][1]['params']['modules']
    assert json.loads(path.read_text())['items']['US:TEST']['earnings']['previous']['epsActual'] == -2
    count = len(calls)
    scanner._analyst_targets_warm()
    scanner._ANALYST_TARGETS['loaded'] = False
    scanner._ANALYST_TARGETS['items'] = {}
    result = scanner.app.test_client().get('/api/argus/analyst-targets').get_json()
    assert result['items'] == {} and result['earningsItems']['US:TEST']['previous']['epsActual'] == -2
    assert result['earningsItems']['US:TEST']['acquisitionStatus'] == 'AVAILABLE'
    assert len(calls) == count


def test_company_reporting_scope_comes_from_document_not_amount_presence():
    base = {'DiscDate': '2026-07-31', 'CurPerEn': '2026-06-30', 'CurPerType': '1Q', 'OP': '100', 'FOP': '500',
            'NCOP': '80', 'FNCOP': '400'}
    read = lambda patch: earnings.company_summary([{'summary': {**base, **patch}, 'receivedAt': AT}], today=TODAY)
    single = read({'DocType': '1QFinancialStatements_NonConsolidated_JP'})
    assert single['consolidated'] is False and single['operatingProfit'] == 100
    assert single['forecastOperatingProfit'] == 500
    assert read({'DocType': '1QFinancialStatements_Consolidated_JP'})['consolidated'] is True
    assert read({'DocType': '1QFinancialStatements_Consolidated_JP', 'OP': ''}) is None
    assert read({'DocType': '1QFinancialStatements_Unknown'}) is None


def test_missing_or_mismatched_eps_units_never_use_reporting_currency_or_compare_trend():
    value = copy.deepcopy(PAYLOAD); data = value['quoteSummary']['result'][0]
    del data['earningsHistory']['history'][0]['currency']
    del data['earningsTrend']['trend'][0]['earningsEstimate']['earningsCurrency']
    row = parse(value)
    assert row['previous']['currency'] is None and row['estimate']['epsCurrency'] is None
    assert row['estimate']['eps30DaysAgo'] is None and row['currency'] == 'JPY'
    data['earningsTrend']['trend'][0]['earningsEstimate']['earningsCurrency'] = 'EUR'
    assert parse(value)['estimate']['eps30DaysAgo'] is None


def test_company_schedule_corrections_withdrawals_future_publications_and_conflicts():
    base = {'Code': '10010', 'FYE': '0331', 'FQName': '2Q', 'PubDate': '2026-10-01', 'SchDate': '2026-11-01'}
    project = lambda rows: earnings.scheduled_date('1001', rows, today=TODAY, fetched_at=AT)
    corrected = {**base, 'PubDate': TODAY, 'SchDate': '2026-11-03'}
    row, status = project([corrected, base, {**base, 'PubDate': '2027-01-01', 'SchDate': '2027-02-01'}])
    assert status == 'AVAILABLE' and row['from'] == '2026-11-03'
    assert row['certainty'] == 'COMPANY_SCHEDULE' and row['publishedDate'] == TODAY
    assert project([base, {**corrected, 'SchDate': ''}]) == (None, 'NO_SCHEDULE')
    assert project([corrected, {**corrected, 'SchDate': '2026-11-04'}]) == (None, 'CONFLICT')
    assert project([{**base, 'Code': '99990'}]) == (None, 'NOT_REPORTED')
    with pytest.raises(ValueError, match='schedule_date_invalid'):
        project([{**base, 'SchDate': '2026-02-31'}])


def test_saved_company_and_official_schedule_survive_yahoo_bootstrap_failure_and_restart(monkeypatch, tmp_path):
    today = scanner.datetime.now(scanner.TZ_JST).strftime('%Y-%m-%d')
    future = (scanner.datetime.now(scanner.TZ_JST).date() + scanner.timedelta(days=20)).isoformat()
    path = tmp_path / 'targets.json'
    monkeypatch.setattr(scanner, '_analyst_targets_path', lambda: str(path))
    monkeypatch.setattr(scanner, '_analyst_targets_symbols', lambda: [('JP', '1001')])
    monkeypatch.setattr(scanner, '_cost_policy_durable_enabled', lambda: True)
    monkeypatch.setattr(scanner, '_DURABILITY_PATHS', {'root': str(tmp_path)})
    monkeypatch.setattr(scanner, '_JQUANTS_API_KEY', 'synthetic-fixture')
    monkeypatch.setattr(scanner, '_ANALYST_TARGETS', {'loaded': True, 'items': {}, 'lastError': None})
    observation = {'receivedAt': AT, 'summary': {'DocType': '1QFinancialStatements_Consolidated', 'DiscDate': '2026-07-31',
        'CurPerEn': '2026-06-30', 'CurPerType': '1Q', 'CurFYEn': '2027-03-31', 'OP': '250000000', 'FOP': '1000000000'}}
    monkeypatch.setattr(argus_earnings_history, 'read', lambda *args, **kwargs: [observation])
    calls = []
    def official(endpoint, params, **kwargs):
        calls.append((endpoint, params, kwargs))
        return [{'Code': '10010', 'FYE': '0331', 'FQName': '2Q', 'PubDate': today, 'SchDate': future}]
    monkeypatch.setattr(scanner, '_jquants_paginated', official)
    class BrokenSession:
        headers = {}
        def get(self, *args, **kwargs): raise RuntimeError('synthetic connection failure')
        def close(self): pass
    monkeypatch.setattr(scanner.requests, 'Session', BrokenSession)
    scanner._analyst_targets_warm()
    saved = json.loads(path.read_text())['items']['JP:1001']
    assert saved['earnings']['company']['operatingProfit'] == 250000000
    assert saved['earnings']['company']['receivedAt'] == AT
    assert saved['earnings']['next']['from'] == future and saved['scheduleStatus'] == 'AVAILABLE'
    assert saved['scheduleAttemptDayJst'] == today and calls[0][2]['max_pages'] == 1
    scanner._analyst_targets_warm()
    assert len(calls) == 1  # Same day does not repeat the official request.
    scanner._ANALYST_TARGETS.update(loaded=False, items={})
    before = path.read_bytes()
    result = scanner.app.test_client().get('/api/argus/analyst-targets').get_json()
    assert result['earningsItems']['JP:1001']['next']['from'] == future
    assert result['earningsItems']['JP:1001']['company']['receivedAt'] == AT
    assert result['items'] == {} and path.read_bytes() == before and len(calls) == 1


def test_official_schedule_batch_is_bounded_and_continues_after_failure(monkeypatch):
    monkeypatch.setattr(scanner, '_JQUANTS_API_KEY', 'synthetic-fixture')
    monkeypatch.setattr(scanner, '_ANALYST_TARGETS', {'items': {}})
    calls = []
    def fail(endpoint, params, **kwargs):
        calls.append(params['code'])
        raise RuntimeError('synthetic failure')
    monkeypatch.setattr(scanner, '_jquants_paginated', fail)
    pairs = [('JP', str(1000+i)) for i in range(12)] + [('US', 'TEST')]
    scanner._analyst_targets_schedule_warm(pairs, TODAY)
    assert len(calls) == 10 and 'US:TEST' not in scanner._ANALYST_TARGETS['items']
    scanner._analyst_targets_schedule_warm(pairs, TODAY)
    assert len(calls) == 12
    assert all(row['scheduleStatus'] == 'FETCH_FAILED' for row in scanner._ANALYST_TARGETS['items'].values())
