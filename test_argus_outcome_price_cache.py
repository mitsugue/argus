"""Real cached-reader connection, no invented helper or provider request."""
from copy import deepcopy
from datetime import date
import time

import pytest

import argus_market_clock as clock
from argus_outcome_price_cache import closing_pair
import scanner


NOW = '2026-11-06T00:00:00Z'


def bars(market='JP'):
    kind = clock.JP_EQUITY if market == 'JP' else clock.US_EQUITY
    return [{'date': day, 'close': close, 'adjusted': False, 'source': 'retained',
             'datasetId': 'same-received-revision', 'knownAt': NOW,
             'observedAt': clock.market_session_bounds(kind, date.fromisoformat(day))['regularCloseUtc']}
            for day, close in [('2026-11-05', 110), ('2026-11-04', 100)]]


@pytest.mark.parametrize('market', ['JP', 'US'])
def test_original_cache_rows_are_sorted_without_mutation(market):
    rows = bars(market); original = deepcopy(rows)
    assert closing_pair(rows, market=market, issued_day='2026-11-04', now=NOW) == [
        {'date': '2026-11-04', 'close': 100}, {'date': '2026-11-05', 'close': 110}]
    assert rows == original


@pytest.mark.parametrize('change', ['missing', 'zero', 'negative', 'bool', 'nan',
    'infinity', 'future_receipt', 'missing_receipt', 'before_close', 'wrong_close',
    'different_adjustment', 'conflicting_day', 'next_session_gap'])
def test_incomplete_or_conflicting_original_pair_stays_unresolved(change):
    rows = bars()
    if change == 'missing': rows.pop(0)
    elif change in ('zero', 'negative', 'bool', 'nan', 'infinity'):
        rows[0]['close'] = {'zero': 0, 'negative': -1, 'bool': True,
                           'nan': float('nan'), 'infinity': float('inf')}[change]
    elif change == 'future_receipt': rows[0]['knownAt'] = '2026-11-06T00:00:01Z'
    elif change == 'missing_receipt': rows[0].pop('knownAt')
    elif change == 'before_close': rows[0]['knownAt'] = '2026-11-05T06:29:00Z'
    elif change == 'wrong_close': rows[0]['observedAt'] = '2026-11-05T06:29:00Z'
    elif change == 'different_adjustment': rows[0]['adjusted'] = True
    elif change == 'conflicting_day': rows.append({**rows[0], 'close': 111})
    elif change == 'next_session_gap': rows[0]['date'] = '2026-11-06'
    assert closing_pair(rows, market='JP', issued_day='2026-11-04', now=NOW) == []


def test_incomplete_current_bar_is_not_a_completed_next_session():
    assert closing_pair(bars(), market='JP', issued_day='2026-11-04',
                        now='2026-11-05T06:29:59Z') == []


@pytest.mark.parametrize('market,symbol,cache_name', [
    ('JP', '9999', '_JQ_HISTORY_CACHE'), ('US', 'CACHEONLY', '_TD_HISTORY_CACHE')])
def test_real_scanner_resolves_with_received_cache_and_never_fetches(monkeypatch, market, symbol, cache_name):
    # The former production reader was absent. Do not install a fake reader.
    assert callable(scanner._price_history_cached)
    cache = {symbol: {'expires': time.time() + 600, 'acquiredAt': NOW,
        'provider': 'twelvedata', 'data': {'dates': ['2026-11-05', '2026-11-04'],
                                        'closes': [110, 100]}}}
    monkeypatch.setattr(scanner, cache_name, cache)
    monkeypatch.setattr(scanner, '_FORECAST_LEDGER', [{'id': 'cache-only-prediction',
        'symbol': symbol, 'market': market,
        'issuedAt': ('2026-11-04T08:30:00+09:00' if market == 'JP'
                     else '2026-11-04T08:30:00-05:00'),
        'forecastHorizon': 'next_session', 'origin': 'forward_live'}])
    monkeypatch.setattr(scanner, '_OUTCOME_LEDGER', [])
    monkeypatch.setattr(scanner, '_journal', lambda *a, **k: None)
    def forbidden(*a, **k): raise AssertionError('provider/AI/write attempted')
    for name in ['_chart_history', '_jq_price_history', '_td_price_history', '_us_price_history', '_execute_ai_judgment']:
        monkeypatch.setattr(scanner, name, forbidden)
    before = deepcopy(cache)
    assert scanner._dl_resolve_matured(NOW) == 1
    result = deepcopy(scanner._OUTCOME_LEDGER)
    assert result[0]['absoluteReturnPct'] == 10.0
    assert scanner._dl_resolve_matured(NOW) == 0
    assert scanner._OUTCOME_LEDGER == result and cache == before


def test_expired_cache_stays_missing_without_refresh(monkeypatch):
    monkeypatch.setattr(scanner, '_JQ_HISTORY_CACHE', {'9999': {
        'expires': time.time() - 1, 'acquiredAt': NOW,
        'data': {'dates': ['2026-11-05', '2026-11-04'], 'closes': [110, 100]}}})
    assert scanner._price_history_cached('9999', market='JP',
        issued_day='2026-11-04', now=NOW) == []


def test_expiry_is_not_a_substitute_for_recorded_receipt(monkeypatch):
    monkeypatch.setattr(scanner, '_JQ_HISTORY_CACHE', {'9999': {
        'expires': time.time() + 600,
        'data': {'dates': ['2026-11-05', '2026-11-04'], 'closes': [110, 100]}}})
    assert scanner._price_history_cached('9999', market='JP',
        issued_day='2026-11-04', now=NOW) == []


@pytest.mark.parametrize('market,issued,days,now', [
    ('US', issued, ['2026-10-02', '2026-10-05'], '2026-10-06T12:00:00Z')
    for issued in ('2026-10-03T08:30:00+09:00', '2026-10-02T23:30:00Z',
                   '2026-10-02T19:30:00-04:00')
] + [
    ('US', issued, ['2026-11-06', '2026-11-09'], '2026-11-10T12:00:00Z')
    for issued in ('2026-11-07T08:30:00+09:00', '2026-11-06T23:30:00Z',
                   '2026-11-06T18:30:00-05:00')
] + [
    ('JP', issued, ['2026-11-04', '2026-11-05'], '2026-11-06T00:00:00Z')
    for issued in ('2026-11-04T08:30:00+09:00', '2026-11-03T23:30:00Z')
])
def test_resolver_uses_market_date_of_original_instant(monkeypatch, market, issued, days, now):
    symbol = 'DATEONLY' if market == 'US' else '9999'
    cache_name = '_TD_HISTORY_CACHE' if market == 'US' else '_JQ_HISTORY_CACHE'
    cache = {symbol: {'expires': time.time() + 600, 'acquiredAt': now,
        'provider': 'twelvedata', 'data': {'dates': days, 'closes': [100, 110]}}}
    forecasts = [{'id': 'market-date-prediction', 'symbol': symbol, 'market': market,
                  'issuedAt': issued, 'forecastHorizon': 'next_session',
                  'origin': 'forward_live'}]
    original_forecasts, original_cache = deepcopy(forecasts), deepcopy(cache)
    monkeypatch.setattr(scanner, cache_name, cache)
    monkeypatch.setattr(scanner, '_FORECAST_LEDGER', forecasts)
    monkeypatch.setattr(scanner, '_OUTCOME_LEDGER', [])
    monkeypatch.setattr(scanner, '_journal', lambda *a, **k: None)
    def forbidden(*a, **k): raise AssertionError('provider/AI/write attempted')
    for name in ['_chart_history', '_jq_price_history', '_td_price_history',
                 '_us_price_history', '_execute_ai_judgment']:
        monkeypatch.setattr(scanner, name, forbidden)
    assert scanner._dl_resolve_matured(now) == 1
    result = deepcopy(scanner._OUTCOME_LEDGER)
    assert result[0]['absoluteReturnPct'] == 10.0
    assert scanner._dl_resolve_matured(now) == 0
    assert scanner._OUTCOME_LEDGER == result
    assert forecasts == original_forecasts and cache == original_cache


@pytest.mark.parametrize('issued', ['2026-11-04', '2026-11-04T08:30:00', '', 'invalid'])
def test_ambiguous_issue_instant_never_requests_price_pair(monkeypatch, issued):
    forecasts = [{'id': 'invalid-market-date', 'symbol': 'DATEONLY', 'market': 'US',
                  'issuedAt': issued, 'forecastHorizon': 'next_session'}]
    monkeypatch.setattr(scanner, '_FORECAST_LEDGER', forecasts)
    monkeypatch.setattr(scanner, '_OUTCOME_LEDGER', [])
    def forbidden(*a, **k): raise AssertionError('ambiguous date reached price reader')
    monkeypatch.setattr(scanner, '_price_history_cached', forbidden)
    monkeypatch.setattr(scanner, '_journal', forbidden)
    assert scanner._dl_resolve_matured(NOW) == 0
    assert scanner._OUTCOME_LEDGER == []
