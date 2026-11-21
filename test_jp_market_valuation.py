"""Synthetic fixtures: export vintages, revisions, and unchanged shape selection.

2026-11-21 (owner): the direct read of Nikkei's daily summary page was removed;
the last tests prove it is gone and that the current valuation still comes from
the J-Quants-based lane without any network read.
"""
from copy import deepcopy
import csv
import io
import sqlite3
import pytest
import jp_market_valuation as v
from jp_market_price_paths import index_valuation_scale

AT = '2026-09-11T10:00:00.100000+00:00'
LATER = '2026-09-11T11:00:00+00:00'


def export(per='20.00', close='40000'):
    handle = io.StringIO(); writer = csv.writer(handle)
    writer.writerow(['date', 'nikkei_close', 'index_per', 'per_basis', 'source_url', 'source_sha256'])
    writer.writerow(['2026-09-11', close, per, 'INDEX_WEIGHT_BASIS', v.SOURCE, 'a' * 64])
    return handle.getvalue().encode()


def row(per='20.00', at=AT): return v.parse_export(export(per), received_at=at)[0]


def test_exact_index_per_definition_and_receipt_not_backdated():
    data = row(); assert data['per'] == 20 and data['indexClose'] == 40000
    assert data['publishedAt'] is None and data['availableFrom'] == AT
    assert not data['historicalVintageVerified']
    scale = index_valuation_scale(data, cutoff=LATER, anchor_date='2026-09-11', anchor_price=40000)
    assert scale['eps'] == 2000 and scale['epsKind'].startswith('DERIVED_')
    assert index_valuation_scale(data, cutoff='2026-09-11T10:00:00Z',
                                 anchor_date='2026-09-11', anchor_price=40000)['status'] == 'UNAVAILABLE'


def test_direct_summary_read_is_removed():
    import scanner
    for name in ('parse_summary', '_Summary', 'ValuationCache', 'MAX_RESPONSE'):
        assert not hasattr(v, name), name
    for name in ('_JP_INDEX_VALUATION', '_jp_index_valuation_warm', 'jp_market_valuation'):
        assert not hasattr(scanner, name), name
    source = open(v.__file__, encoding='utf-8').read()
    for word in ('requests', 'urllib', 'urlopen', 'iter_content', 'HTMLParser', 'User-Agent'):
        assert word not in source, word


def test_restart_keeps_vintages_same_value_idempotent_and_reversion_is_new(tmp_path):
    path = tmp_path/'valuation.sqlite3'; v.initialize(path)
    original = v.append(path, row()); assert path.stat().st_mode & 0o777 == 0o600
    assert v.append(path, row(at='2026-09-11T10:30:00Z')) == original
    revised = v.append(path, row('25.00', LATER))
    assert v.latest(path, '2026-09-11T10:30:00Z') == original
    assert v.latest(path, LATER) == revised
    reverted = v.append(path, row(at='2026-09-11T12:00:00Z'))
    assert reverted['knownAt'] != original['knownAt']
    with sqlite3.connect(path) as db: assert db.execute('SELECT count(*) FROM vintages').fetchone()[0] == 3
    assert v.latest(path, '2026-09-11T09:59:00Z') is None


def test_corruption_and_backward_revision_fail_without_overwrite(tmp_path):
    path = tmp_path/'valuation.sqlite3'; v.initialize(path); v.append(path,row())
    with pytest.raises(ValueError): v.append(path,row('25.00','2026-09-11T09:59:00Z'))
    with sqlite3.connect(path) as db: db.execute("UPDATE vintages SET body=replace(body,'40000.0','41000.0')")
    with pytest.raises(ValueError,match='integrity'): v.latest(path,LATER)
    with pytest.raises(ValueError,match='integrity'): v.append(path,row(at=LATER))


@pytest.mark.parametrize("current_missing", [False, True])
def test_runtime_cached_comparison_uses_current_scale_without_legacy_fallback_or_network(monkeypatch, current_missing):
    import scanner
    from jp_market_level_map import weighted_eps, EPS_BASIS
    legacy = row()
    current = {**weighted_eps({"A": {"MktCap": 1000, "FwdPER": 40}}, ["A"],
                index_close=40000, date='2026-09-11', constituents_as_of='2026-08-31'),
               "recordedAt": LATER}
    level_map = {'eps': {} if current_missing else {'2026-09-11': current}}
    current_before = deepcopy(level_map)
    monkeypatch.setattr(scanner, '_LEVEL_MAP', level_map)
    monkeypatch.setattr(scanner, '_N225_ANALOG_HISTORY', {'data': [], 'calendar': []})
    monkeypatch.setattr(scanner, '_JP_MARKET_ENGINE_INDEX_OHLCV_CACHE', {'^N225':{
        'data':[{'date':'2026-09-11', 'close':40000, 'instrumentId':'NIKKEI_225_INDEX',
                 'availableFrom':AT}], 'acquiredAt':AT}})
    monkeypatch.setattr(scanner.argus_market_clock,'canonical_trading_day',lambda *a:True)
    def calculate(*args, **kwargs):
        if current_missing:
            assert kwargs['valuation'] == {'basis': EPS_BASIS}
        else:
            assert kwargs['valuation']['basis'] == EPS_BASIS
            assert kwargs['valuation']['per'] == 40 != legacy['per']
            assert kwargs['valuation']['eps'] == 1000
            assert kwargs['valuation']['recordedAt'] == LATER
        return {'status':'available'}
    monkeypatch.setattr(scanner.jp_market_price_paths,'cached_index_comparison',calculate)
    monkeypatch.setattr(scanner.requests,'get',lambda *a,**kw:pytest.fail('public GET cannot fetch'))
    result = scanner._jp_market_comparison_calculate(5)
    assert result['status'] == 'available'
    assert result['valuationAcquisition']['basis'] == EPS_BASIS
    assert result['valuationAcquisition']['status'] == ('CURRENT_ESTIMATE_UNAVAILABLE' if current_missing else 'AVAILABLE')
    assert result['proxyValuation'] is None
    assert scanner._LEVEL_MAP == current_before


def test_refresh_status_does_not_regenerate_ai_but_changed_per_does():
    import argus_market_brief as brief
    first = {'5':{'valuation':row(), 'valuationAcquisition':{'status':'AVAILABLE'}}}
    second = deepcopy(first); second['5']['valuationAcquisition']={'status':'ACQUIRING','lastAttemptAt':LATER}
    assert brief.calculation_identity(first) == brief.calculation_identity(second)
    second['5']['valuation'] = row('25.00',LATER)
    assert brief.calculation_identity(first) != brief.calculation_identity(second)
