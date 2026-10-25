"""Undecided forecasts, predecessors, carried rows and holiday rows (2026-10-25 owner)."""
import jp_market_level_map as m
import argus_level_map_backfill as b
from test_jp_market_level_map_supply import _warm_scope


def _fy(day, np=None, nx=None, no='F'):
    return {'Code': '54010', 'DiscDate': day, 'DiscNo': no, 'DocType': 'FYFinancialStatements_Consolidated_IFRS',
            'NP': np, 'NxFNp': nx}


def test_stand_in_takes_the_newest_forecast_then_the_last_actual():
    rows = [_fy('2020-05-08', np='-431513000000', no='A'),
            {'Code': '54010', 'DiscDate': '2020-08-04', 'DiscNo': 'B', 'DocType': '1QFinancialStatements', 'FNP': ''}]
    value, source = m.earnings_stand_in(rows, before='2020-08-05')
    assert value == 0.0 and source['method'] == 'prior_actual_loss_as_zero' and source['discNo'] == 'A'
    rows.append(_fy('2021-05-10', np='-32432000000', nx='240000000000', no='C'))
    value, source = m.earnings_stand_in(rows, before='2021-05-11')
    assert value == 240000.0 and source['method'] == 'forecast'
    profit = [_fy('2024-05-10', np='120000000000', no='D'),
              {'Code': '43010', 'DiscDate': '2024-06-01', 'DiscNo': 'E', 'DocType': 'EarnForecastRevision', 'FNP': ''}]
    value, source = m.earnings_stand_in(profit, before='2024-06-05')
    assert value == 120000.0 and source['method'] == 'prior_actual'
    assert m.earnings_stand_in(profit, before='2024-05-10') is None      # same-day disclosure is not used


def test_stand_ins_fill_every_missing_member_or_none():
    rows = {'1001': {'MktCap': 1000.0, 'FwdPER': 10.0}, '5401': {'MktCap': 3000.0},
            '6367': {'MktCap': 2000.0, 'FwdEPS': 50.0}}
    members = ['1001', '5401', '6367']
    assert m.earnings_missing_members(rows, members) == ['5401']      # 6367 waits for a daily close
    disclosures = {'5401': [_fy('2020-05-08', np='100000000', no='A')]}
    joined, stood = m.valuation_with_earnings_stand_ins(rows, members, disclosures, date='2020-08-05')
    assert stood == {'5401': {'forecastNetIncome': 100.0, 'disclosure': stood['5401']['disclosure']}}
    assert 'suppliedForecastNetIncome' not in rows['5401']               # originals unchanged
    assert m.valuation_with_earnings_stand_ins(rows, members, {}, date='2020-08-05')[1] == {}
    # The remaining gap is a price; the daily-close check now treats 5401 as covered.
    assert m.daily_close_repairable(joined, members)


def test_stand_in_is_counted_as_supplied_earnings_only():
    rows = {'1001': {'MktCap': 1000.0, 'FwdPER': 10.0},
            '5401': {'MktCap': 3000.0, 'suppliedForecastNetIncome': 0.0, 'earningsStandIn': True}}
    est = m.weighted_eps(rows, ['1001', '5401'], index_close=10000.0, date='2020-08-05', constituents_as_of='t')
    assert est['coverage']['suppliedEarnings'] == 1 and est['coverage']['suppliedMarketCap'] == 0
    assert est['coverage']['missingEarnings'] == 0 and m.estimate_input_usable(est, strict=True)
    assert abs(est['per'] - 4000.0 / 100.0) < 1e-9                      # a loss counts as zero income


def test_holding_company_uses_its_predecessor_before_its_first_forecast():
    rows = {'1001': {'MktCap': 1000.0, 'FwdPER': 10.0}, '9147': {'MktCap': None}}
    bars = {'9147': [{'Date': '2022-01-05', 'Code': '91470', 'MktCap': 5000.0}]}
    disclosures = {'9147': [], '9062': [{'Code': '90620', 'DiscDate': '2021-11-10', 'DiscNo': 'P',
                                         'DocType': '2QFinancialStatements', 'FNP': '90000000000'}]}
    joined, supplied = m.valuation_with_supplied_members(rows, ['1001', '9147'], bars, disclosures, date='2022-01-05')
    assert supplied['9147']['predecessorCode'] == '9062' and supplied['9147']['forecastNetIncome'] == 90000.0
    # A company without a recorded predecessor is still left unfilled.
    rows['543A'] = {'MktCap': None}
    bars['543A'] = [{'Date': '2022-01-05', 'Code': '543A0', 'MktCap': 1.0}]
    assert m.valuation_with_supplied_members(rows, ['1001', '9147', '543A'], bars, disclosures, date='2022-01-05')[1] == {}


def test_delisted_member_carries_its_last_trading_day_row_for_a_week_only():
    rows = {'1001': {'MktCap': 1000.0, 'FwdPER': 10.0}}
    history = {'7205': [{'Date': '2026-03-26', 'Code': '72050', 'MktCap': 1.0, 'FwdPER': 5.0},
                        {'Date': '2026-03-27', 'Code': '72050', 'MktCap': 800.0, 'FwdPER': 8.0}]}
    joined, carried = m.valuation_with_carried_rows(rows, ['1001', '7205'], history, date='2026-03-30')
    assert carried == {'7205': '2026-03-27'} and joined['7205']['MktCap'] == 800.0
    est = m.weighted_eps(joined, ['1001', '7205'], index_close=10000.0, date='2026-03-30', constituents_as_of='t')
    assert est['coverage']['carriedForward'] == 1 and m.estimate_input_usable(est, strict=True)
    assert m.valuation_with_carried_rows(rows, ['1001', '7205'], history, date='2026-04-06')[1] == {}


def test_backfill_tries_every_set_aside_date_again_with_the_new_method():
    old = {'schemaVersion': b.SCHEMA, 'method': 'blank-member-supplement-2026-10-21', 'cursor': '2020-10-20',
           'exhausted': {'2020-08-05': {'signature': 'INPUT_INCOMPLETE:0:1', 'attempts': 3, 'since': '2026-10-21T00:00:00Z'}}}
    state = b.parse(old)
    assert state['exhausted'] == {} and state['cursor'] is None


def _undecided_scope(days):
    scope, requests, writes, provider, supply = _warm_scope(set())
    supply['valuation'] = {}
    scope['_LEVEL_MAP_SUPPLY_FIELDS']['disclosures'] += ('NP', 'NCNP')
    calls = []

    def valuation(day, headers):
        requests.append(day)
        rows = {'1001': {'MktCap': 1000.0, 'FwdPER': 10.0}, '1002': {'MktCap': 2000.0, 'FwdPER': 20.0},
                '543A': {'MktCap': 3000.0, 'FwdPER': 20.0}}
        if day in days:
            rows['1002'] = {'MktCap': 2000.0}
        return rows

    def paginated(path, params, max_pages=40, request_timeout=None):
        calls.append((path, params['code']))
        return [{'Code': '10020', 'DiscDate': '2026-05-01', 'DiscNo': 'Y',
                 'DocType': 'FYFinancialStatements_Consolidated_JP', 'NxFNp': '', 'NP': '50000000'}]
    scope['_jq_valuation_for_date'] = valuation
    scope['_jquants_paginated'] = paginated
    return scope, writes, calls


def test_warm_fills_an_undecided_forecast_from_the_last_actual():
    days = {'2026-07-14', '2026-07-15'}
    scope, writes, calls = _undecided_scope(days)
    scope['_level_map_warm']([])
    stood = [w for w in writes if w.get('earningsStandIn')]
    assert sorted(w['date'] for w in stood) == sorted(days)
    assert calls == [('/fins/summary', '1002')]                          # one read for the code
    for row in stood:
        assert row['earningsStandIn']['methods'] == {'1002': 'prior_actual'}
        assert row['coverage']['suppliedEarnings'] == 1 and row['coverage']['suppliedMarketCap'] == 0


def test_warm_does_not_set_aside_a_day_whose_supply_waits_for_budget():
    days = {'2026-07-14'}
    scope, writes, calls = _undecided_scope(days)
    scope['_LEVEL_MAP_SUPPLY_REQUESTS_PER_WARM'] = 0
    noted = []
    original = b.note
    scope['argus_level_map_backfill'] = type('B', (), {
        **{name: staticmethod(getattr(b, name)) for name in dir(b) if not name.startswith('_')},
        'note': staticmethod(lambda state, day, sig, now: (noted.append(day), original(state, day, sig, now)))})
    scope['_level_map_warm']([])
    assert '2026-07-14' not in noted and not any(w.get('earningsStandIn') for w in writes)


def test_warm_skips_a_holiday_row_in_the_price_history():
    scope, writes, calls = _undecided_scope(set())
    scope['_N225_ANALOG_HISTORY'] = {'data': [{'date': '2018-07-16', 'close': 22000.0},
                                              {'date': '2018-07-17', 'close': 22100.0}],
                                     'calendar': [{'Date': '2018-07-16', 'HolDiv': '0'},
                                                  {'Date': '2018-07-17', 'HolDiv': '1'}]}
    asked = []
    inner = scope['_jq_valuation_for_date']
    scope['_jq_valuation_for_date'] = lambda day, headers: (asked.append(day), inner(day, headers))[1]
    scope['_LEVEL_MAP_EPS_PER_WARM'] = 200
    scope['_level_map_warm']([])
    assert '2018-07-17' in asked and '2018-07-16' not in asked
