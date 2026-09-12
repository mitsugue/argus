"""Synthetic fixtures: acquisition truth, revisions, and unchanged shape selection."""
from copy import deepcopy
import sqlite3
import pytest
import jp_market_valuation as v
from jp_market_price_paths import index_valuation_scale

AT = '2026-09-11T10:00:00.100000+00:00'
LATER = '2026-09-11T11:00:00+00:00'


def html(per='20.00', close='40,000.00'):
    return f'''<html><script>日経平均株価 99.00 +1% 株価収益率(PER)</script>
    <h1>2026年9月11日(金)</h1><h2>日経平均株価</h2><div>{close}</div><span>-1.00%</span>
    <h2>配当利回り</h2><span>指数ベース 1.55%</span>
    <h2><a>株価収益率(PER)</a></h2><div>加重平均 <span>15.00倍</span></div>
    <div>指数ベース <span>{per}倍</span></div><h2>株価純資産倍率(PBR)</h2>
    <span>加重平均 1.25倍 指数ベース 2.55倍</span></html>'''.encode()


def row(per='20.00', at=AT): return v.parse_summary(html(per), received_at=at)


def test_exact_index_per_definition_and_receipt_not_backdated():
    data = row(); assert data['per'] == 20 and data['indexClose'] == 40000
    assert data['publishedAt'] is None and data['availableFrom'] == AT
    assert not data['historicalVintageVerified']
    scale = index_valuation_scale(data, cutoff=LATER, anchor_date='2026-09-11', anchor_price=40000)
    assert scale['eps'] == 2000 and scale['epsKind'].startswith('DERIVED_')
    assert index_valuation_scale(data, cutoff='2026-09-11T10:00:00Z',
                                 anchor_date='2026-09-11', anchor_price=40000)['status'] == 'UNAVAILABLE'


@pytest.mark.parametrize('raw', [html().replace('指数ベース'.encode(), b'unknown'),
    html()+html(), html('0.00'), html().replace(b'(PER)', b'(PBR)'), b'x'*(v.MAX_RESPONSE+1)])
def test_ambiguous_missing_wrong_measure_fails(raw):
    with pytest.raises(ValueError): v.parse_summary(raw, received_at=AT)


def test_before_close_or_timezone_absent_fails():
    for at in ('2026-09-11T06:00:00Z', '2026-09-11T10:00:00'):
        with pytest.raises(ValueError): v.parse_summary(html(), received_at=at)


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


class Response:
    status_code = 200
    def __init__(self, raw): self.raw = raw
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def iter_content(self, size): yield self.raw


def test_warm_restores_after_failed_fetch_and_read_path_has_no_io(tmp_path):
    path = tmp_path/'valuation.sqlite3'; cache = v.ValuationCache()
    cache.warm(path, get=lambda *a,**kw: Response(html()), now=lambda: AT)
    assert cache.status['persistenceStatus'] == 'LOCAL_DURABLE'
    saved = cache.snapshot(LATER); saved['per'] = 1
    assert cache.snapshot(LATER)['per'] == 20
    restored = v.ValuationCache()
    def fail(*a,**kw): raise OSError('fixture')
    restored.warm(path, get=fail, now=lambda: LATER)
    assert restored.snapshot(LATER) == cache.snapshot(LATER)
    assert restored.status['status'] == 'FAILED' and restored.status['lastSuccessfulAcquisitionAt'] == AT
    assert restored.snapshot('2026-09-11T09:00:00Z') is None


def test_runtime_cached_comparison_uses_scale_without_network(monkeypatch):
    import scanner
    cache = v.ValuationCache(); cache.row = row()
    monkeypatch.setattr(scanner, '_JP_INDEX_VALUATION', cache)
    monkeypatch.setattr(scanner, '_JP_MARKET_ENGINE_INDEX_OHLCV_CACHE', {'^N225':{
        'data':[{'date':'2026-09-11'}], 'acquiredAt':AT}})
    monkeypatch.setattr(scanner.argus_market_clock,'canonical_trading_day',lambda *a:True)
    def calculate(*args, **kwargs):
        assert kwargs['valuation'] == cache.row
        return {'status':'available'}
    monkeypatch.setattr(scanner.jp_market_price_paths,'cached_index_comparison',calculate)
    monkeypatch.setattr(scanner.requests,'get',lambda *a,**kw:pytest.fail('public GET cannot fetch'))
    assert scanner._jp_market_comparison_cached(5)['status'] == 'available'


def test_refresh_status_does_not_regenerate_ai_but_changed_per_does():
    import argus_market_brief as brief
    first = {'5':{'valuation':row(), 'valuationAcquisition':{'status':'AVAILABLE'}}}
    second = deepcopy(first); second['5']['valuationAcquisition']={'status':'ACQUIRING','lastAttemptAt':LATER}
    assert brief.calculation_identity(first) == brief.calculation_identity(second)
    second['5']['valuation'] = row('25.00',LATER)
    assert brief.calculation_identity(first) != brief.calculation_identity(second)
