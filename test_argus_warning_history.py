from datetime import date, timedelta
from copy import deepcopy

from argus_warning_history import warning_event_study, performance_for, METHOD
from argus_warning_conditions import project_warning_conditions
from test_argus_warning_conditions import evidence, AT


def fixture():
    sessions = [(date(2025, 1, 1) + timedelta(days=n)).isoformat() for n in range(450)]
    rows = []
    for n, day in enumerate(sessions):
        rows.append({'seriesId': 'flow.foreign', 'periodEnd': day,
                     'value': -1 if (n // 22) % 2 else 1, 'availableFrom': day+'T07:00:00Z'})
    closes = {day: 1000-n for n, day in enumerate(sessions)}
    return rows, closes, sessions


def test_current_foreign_warning_is_negative_not_legacy_inflow_or_zero():
    rows, closes, sessions = fixture()
    original = deepcopy(rows)
    report = warning_event_study(foreign_rows=rows, closes=closes, session_dates=sessions, cutoff=AT)
    row = report['conditions']['D05']
    assert row['expects'] == 'FALL' and row['ruleId'] == 'jp-warning-conditions-v2.D05'
    assert row['horizons']['5']['falls'] == row['horizons']['5']['evaluated'] > 0
    assert rows == original and not report['legacySupportResultsReused']
    assert report['validationStatus'] == 'UNVALIDATED' and not report['historicalVintageVerified']
    assert report['predictiveProbabilities'] is None and not report['actionAuthority']
    zero = deepcopy(rows)
    for r in zero: r['value'] = 0
    assert warning_event_study(foreign_rows=zero, closes=closes, session_dates=sessions, cutoff=AT)['conditions']['D05']['evaluated'] == 0


def test_future_corrections_and_total_margin_do_not_change_warning_statistics():
    rows, closes, sessions = fixture()
    future = {**rows[22], 'value': 999, 'availableFrom': '2027-01-01T00:00:00Z'}
    base = warning_event_study(foreign_rows=rows, closes=closes, session_dates=sessions, cutoff=AT)
    changed = warning_event_study(foreign_rows=rows+[future], closes=closes, session_dates=sessions, cutoff=AT)
    assert base['conditions'] == changed['conditions']
    totals = [{**r, 'seriesId': 'margin.long_balance'} for r in rows]
    report = warning_event_study(margin_rows=totals, closes=closes, session_dates=sessions, cutoff=AT)
    assert report['conditions']['D02']['evaluated'] == 0
    assert all(report['conditions'][f]['status'] == 'NOT_EVALUABLE' for f in ('D03','D04','D07'))


def test_signed_unrounded_vix_and_standardized_margin_boundaries():
    rows, closes, sessions = fixture()
    vix = [{**r, 'seriesId':'vix.macd_histogram','value':1e-15 if r['value']<0 else 0} for r in rows]
    margins = [dict(r, seriesId='margin.standardized.long_balance', value=1 if r['value']<0 else .9) for r in rows]
    margins += [dict(r, seriesId='margin.standardized.short_balance', value=1) for r in rows]
    report = warning_event_study(vix_features=vix, margin_rows=margins, closes=closes, session_dates=sessions, cutoff=AT)
    assert report['conditions']['D06']['evaluated'] > 0
    assert report['conditions']['D02']['evaluated'] == report['conditions']['D06']['evaluated']


def test_current_projection_accepts_only_bound_report_and_keeps_undefined_rules():
    rows, closes, sessions = fixture()
    report = warning_event_study(foreign_rows=rows, closes=closes, session_dates=sessions, cutoff=AT)
    projection = project_warning_conditions(evidence(), cutoff=AT, performance=report)
    assert projection['signals'][4]['performance']['evaluated'] > 0
    assert projection['signals'][2]['state'] == 'DATA_GATED'
    tampered = deepcopy(report); tampered['conditions']['D05']['evaluated'] += 1
    assert performance_for(tampered, 'D05', AT) is None
    assert performance_for(report, 'D05', '2026-10-07T00:00:00Z') is None
    rejected = project_warning_conditions(evidence(), cutoff=AT, performance=tampered)
    assert rejected['signals'][4]['performance']['evaluated'] == 0


def test_scanner_uses_cash_indexes_cached_only_and_excludes_later_same_date_us_close(monkeypatch):
    import scanner
    jp = [{'instrumentId':'NIKKEI_225_INDEX','seriesId':'close','date':(date(2026,8,1)+timedelta(days=n)).isoformat(),
           'close':100+n,'availableFrom':(date(2026,8,1)+timedelta(days=n)).isoformat()+'T07:00:00Z'} for n in range(30)]
    us = [{**r,'instrumentId':'SP500_INDEX','close':100} for r in jp]
    us[-1]['close'] = 9999
    monkeypatch.setattr(scanner, '_JP_MARKET_ENGINE_INDEX_OHLCV_CACHE', {'^N225':{'data':jp},'^GSPC':{'data':us}})
    monkeypatch.setattr(scanner, '_ai_now_iso', lambda: AT)
    result = scanner._jp_market_engine_relative_strength_direct()
    assert result['instrumentId'] == 'NIKKEI_225_INDEX'
    assert result['indexRatio'] == 1.29 and result['comparisonDate'] == us[-2]['date']
    assert abs(result['value'] - (129/109-1)) < 1e-12
    monkeypatch.setattr(scanner, '_JP_MARKET_ENGINE_INDEX_OHLCV_CACHE', {})
    assert scanner._jp_market_engine_relative_strength_direct() is None


def test_runtime_study_uses_original_standardized_balances_not_ratio_adapter(monkeypatch):
    import scanner
    rows, closes, sessions = fixture()
    margins = [dict(r, seriesId='margin.standardized.long_balance', value=1 if r['value']<0 else .9) for r in rows]
    margins += [dict(r, seriesId='margin.standardized.short_balance', value=1) for r in rows]
    bars = [dict(instrumentId='NIKKEI_225_INDEX', seriesId='close', date=day, close=value,
                 availableFrom=day+'T07:00:00Z') for day, value in closes.items()]
    monkeypatch.setattr(scanner, '_N225_ANALOG_HISTORY', {'data': bars, 'calendar': []})
    monkeypatch.setattr(scanner, '_JP_MARKET_FEATURE_HISTORY', {'features': []})
    monkeypatch.setattr(scanner, '_JQ_MARGIN_CACHE', {'1570': {'sourceSnapshot': {'rows': margins}}})
    monkeypatch.setattr(scanner, '_jp_exchange_sessions', lambda *_: (sessions, False))
    monkeypatch.setattr(scanner.requests, 'get', lambda *_a, **_k: (_ for _ in ()).throw(AssertionError('no_fetch')))
    inputs = {'margin1570Rows': [{'value': 99, 'date': sessions[-1]}]}
    result = scanner._jp_warning_performance(inputs, AT)
    assert result['conditions']['D02']['evaluated'] > 0
    assert result['conditions']['D02']['horizons']['5']['falls'] > 0
    monkeypatch.setattr(scanner, '_JQ_MARGIN_CACHE', {})
    assert scanner._jp_warning_performance(inputs, AT)['conditions']['D02']['evaluated'] == 0
