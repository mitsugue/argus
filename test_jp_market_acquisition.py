import csv
import io
import json
from pathlib import Path

import pytest

import jp_market_acquisition as m
import jp_market_features as features
import jp_market_valuation as valuation

AT = '2026-09-20T02:00:00Z'
LATER = '2026-09-21T02:00:00Z'


def mof(value='-0.1', day='R8.9.17'):
    header = ['基準日'] + [str(n) + '年' for n in (*range(1, 11), 15, 20, 25, 30, 40)]
    return ('国債金利情報,,,,,,,,,,,,,,,(単位 : %)\n' + ','.join(header) + '\n' +
            ','.join([day] + [value] * 15) + '\n' + ',' * 15 + '\n').encode('cp932')


def vix(close='15.0'):
    return ('DATE,OPEN,HIGH,LOW,CLOSE\n09/18/2026,15,18,12,' + close + '\n').encode()


def test_native_units_missing_and_negative_rates():
    row = m.parse(mof(), url=m.MOF_HISTORY, received_at=AT)[0]
    assert row['values']['10'] == -.1 and row['unit'] == 'PERCENT'
    assert m.parse(mof('-'), url=m.MOF_HISTORY, received_at=AT)[0]['values']['10'] is None
    assert m.feature_rows([dict(row, knownAt=AT)], 'jp_yield_curve')[0]['value'] == -.1


@pytest.mark.parametrize('raw,url', [(mof('nan'), m.MOF_HISTORY), (mof(day='H31.5.1'), m.MOF_CURRENT),
                                   (vix('19'), m.VIX_HISTORY), (vix() + vix().split(b'\n')[1], m.VIX_HISTORY)])
def test_invalid_data_rejected(raw, url):
    with pytest.raises(ValueError): m.parse(raw, url=url, received_at=AT)


def test_vintages_restart_idempotence_and_original_retained(tmp_path):
    path = tmp_path/'source.sqlite3'; db = m.connect(path)
    first = m.ingest(db, mof(), url=m.MOF_CURRENT, received_at=AT)
    assert first['changedObservations'] == 1
    assert m.ingest(db, mof(), url=m.MOF_CURRENT, received_at=LATER)['changedObservations'] == 0
    assert m.ingest(db, mof('.2'), url=m.MOF_CURRENT, received_at=LATER)['changedObservations'] == 1
    assert db.execute('SELECT count(*) FROM observations').fetchone()[0] == 2
    db.close(); db = m.connect(path); m.verify_raw(db)
    row = m.latest_rows(db, 'jp_yield_curve')[0]
    assert row['revision'] == 1 and row['values']['10'] == .2
    assert row['supersedesRawId'] == first['rawId']
    assert row['knownAt'] == LATER and row['publishedAt'] is None
    assert not row['historicalVintageVerified']
    history = m.history_rows(db, 'jp_yield_curve')
    assert [item['revision'] for item in history] == [0, 1]
    features = m.feature_rows(history, 'jp_yield_curve')
    assert [item['value'] for item in features] == [-.1, .2]
    assert [item['knownAt'] for item in features] == [AT, LATER]
    assert path.stat().st_mode & 0o777 == 0o600


def test_source_cache_keeps_revision_as_an_appended_feature_input(tmp_path):
    path = tmp_path/'source.sqlite3'; current = {'rate': '-0.1'}
    def get(url, **kwargs):
        raw = vix() if url == m.VIX_HISTORY else mof(current['rate'])
        return Response(raw)
    first = m.SourceCache(); first.warm(path, get=get, now=lambda: AT)
    original = list(first.rows['jp_yield_curve'])
    current['rate'] = '.2'
    revised = m.SourceCache(); revised.warm(path, get=get, now=lambda: LATER)
    assert revised.rows['jp_yield_curve'][:len(original)] == original
    assert revised.rows['jp_yield_curve'][-1]['revision'] == 1
    assert revised.rows['jp_yield_curve'][-1]['knownAt'] == LATER
    before = features.build_feature_history(
        cutoffs=[AT], price_series={'jp10y': original})
    before['status'] = 'AVAILABLE'
    after = features.build_feature_history(
        cutoffs=[AT, LATER], previous_history=before,
        price_series={'jp10y': revised.rows['jp_yield_curve']})
    assert after['calculationWork'] == {'reusedCutoffs': 1, 'evaluatedCutoffs': 1}
    assert after['reuseDecision'] == {
        'reason': 'unchanged_source_prefix', 'source': None}


def test_corrupt_normalized_data_detected_from_raw(tmp_path):
    db = m.connect(tmp_path/'source.sqlite3')
    m.ingest(db, mof(), url=m.MOF_CURRENT, received_at=AT)
    db.execute("UPDATE observations SET body=replace(body,'-0.1','1.0')")
    db.commit()
    with pytest.raises(ValueError, match='normalized_integrity'): m.verify_raw(db)


class Response:
    def __init__(self, raw, status=200): self.raw = raw; self.status_code = status
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def iter_content(self, _): yield self.raw


def test_bootstrap_once_then_only_small_current_month_and_read_without_io(tmp_path):
    path = tmp_path/'source.sqlite3'; calls = []
    def get(url, **kwargs):
        calls.append(url)
        assert kwargs['allow_redirects'] is False
        return Response(vix() if url == m.VIX_HISTORY else mof())
    cache = m.SourceCache(); cache.warm(path, get=get, now=lambda: AT)
    assert calls == [m.MOF_HISTORY, m.VIX_HISTORY, m.MOF_CURRENT]
    assert cache.status['status'] == 'AVAILABLE'
    snapshot = cache.snapshot(); snapshot['sources'].clear()
    assert cache.snapshot()['sources']
    restored = m.SourceCache(); restored.warm(path, get=get, now=lambda: AT)
    assert len(calls) == 3 and restored.rows == cache.rows
    restored.next_attempt = 0; restored.warm(path, get=get, now=lambda: LATER)
    assert calls == [m.MOF_HISTORY, m.VIX_HISTORY, m.MOF_CURRENT, m.MOF_CURRENT]
    assert restored.status['automaticAiCalls'] == 0


def test_denied_no_retry_on_same_day_even_restart(tmp_path):
    path = tmp_path/'source.sqlite3'; calls = []
    def get(url, **kw): calls.append(url); return Response(b'', 403)
    cache = m.SourceCache(); cache.warm(path, get=get, now=lambda: AT)
    assert len(calls) == 3 and cache.status['status'] == 'PARTIAL'
    m.SourceCache().warm(path, get=get, now=lambda: AT)
    assert len(calls) == 3


def test_download_does_not_rewrite_historical_features(tmp_path):
    db = m.connect(tmp_path/'source.sqlite3')
    for day in range(10, 18):
        m.ingest(db, mof(str(day/100), 'R8.9.'+str(day)), url=m.MOF_CURRENT, received_at=AT)
    rates = m.feature_rows(m.latest_rows(db, 'jp_yield_curve'), 'jp_yield_curve')
    early = features.build_market_features(cutoff='2026-09-18T00:00:00Z', price_series={'jp10y': rates})
    current = features.build_market_features(cutoff=AT, price_series={'jp10y': rates})
    assert 'rate.jp10y_change5' in early['missingFeatures']
    row = next(r for r in current['features'] if r['seriesId'] == 'rate.jp10y_change5')
    assert row['value'] == pytest.approx(.05)
    assert row['unit'] == 'PERCENTAGE_POINTS' and not current['actionAuthority']


def test_overlap_does_not_invent_cross_provider_revision():
    legacy = [{'date':'2026-09-18', 'value':15, 'instrumentId':'VIX', 'availableFrom':AT}]
    official = [{'date':'2026-09-18', 'value':16, 'instrumentId':'VIX', 'availableFrom':LATER}]
    assert m.merge_feature_sources(legacy, official) == [dict(legacy[0], seriesId='close')]


def export(per='20', basis='INDEX_WEIGHT_BASIS'):
    text = io.StringIO(); writer = csv.writer(text)
    writer.writerow(['date','nikkei_close','index_per','per_basis','source_url','source_sha256'])
    writer.writerow(['2026-09-18','40000',per,basis,valuation.SOURCE,'a'*64])
    return text.getvalue().encode()


def test_export_uses_existing_vintage_store_without_claiming_original_pit(tmp_path):
    rows = valuation.parse_export(export(), received_at=AT)
    row = rows[0]; path = tmp_path/'valuation.sqlite3'; valuation.initialize(path)
    valuation.append(path, row)
    assert valuation.latest(path, AT) == row and row['indexClose']/row['per'] == 2000
    assert row['sourceExportSha256'] != row['claimedOriginalSha256']
    assert row['publishedAt'] is None and row['originalHashVerified'] is False
    assert valuation.latest(path, '2026-09-19T00:00:00Z') is None


@pytest.mark.parametrize('per,basis', [('0','INDEX_WEIGHT_BASIS'), ('NaN','INDEX_WEIGHT_BASIS'), ('20','WEIGHTED_AVERAGE')])
def test_bad_exports_never_enter_store(per,basis):
    with pytest.raises(ValueError): valuation.parse_export(export(per,basis), received_at=AT)


def test_supplied_registry_hashes_and_scope_are_not_completion_claims():
    import hashlib
    root=Path(__file__).parent/'ops/imports/acquisition_20260920'
    manifest=json.loads((root/'provenance.json').read_text())
    for path,digest in manifest['importedFiles'].items():
        assert hashlib.sha256((root/path).read_bytes()).hexdigest()==digest
    registry=json.loads((root/'source_registry.json').read_text())
    assert len(registry['indicators'])==43
    assert not manifest['allIndicators10yComplete'] and not manifest['predictivePowerVerified']


def test_background_runtime_passes_saved_sources_into_existing_feature_calculation(monkeypatch):
    import scanner
    from types import SimpleNamespace
    monkeypatch.setattr(scanner, '_cost_policy_durable_enabled', lambda: False)
    monkeypatch.setattr(scanner, '_N225_ANALOG_HISTORY', {'data':[{'date':'2026-09-18'}]})
    monkeypatch.setattr(scanner, '_JP_MARKET_ENGINE_INDEX_OHLCV_CACHE', {})
    monkeypatch.setattr(scanner, '_JP_MARKET_FEATURE_HISTORY', {})
    monkeypatch.setattr(scanner, '_JP_OFFICIAL_SOURCE_CACHE', SimpleNamespace(rows={
        'jp_yield_curve':[{'date':'2026-09-17','instrumentId':'JP10Y','value':2.993,'unit':'PERCENT'}],
        'vix_ohlc':[{'date':'2026-09-18','instrumentId':'VIX','value':14.81}]}))
    captured = {}
    def build(**kwargs):
        captured.update(kwargs)
        return {'features':[], 'conditions':[]}
    monkeypatch.setattr(scanner.jp_market_features, 'build_feature_history', build)
    monkeypatch.setattr(scanner.requests, 'get', lambda *a,**kw: pytest.fail('feature calculation cannot fetch'))
    scanner._jp_market_feature_history_warm()
    assert captured['price_series']['jp10y'][0]['value'] == 2.993
    assert captured['price_series']['vix'][0]['value'] == 14.81
    assert scanner._JP_MARKET_FEATURE_HISTORY['status'] == 'AVAILABLE'


def test_rolling_provider_cache_retains_selected_prefix_and_revisions(tmp_path):
    path = tmp_path/'sources.sqlite3'
    def row(day, value, source):
        return {'date':day, 'close':value, 'availableFrom':AT, 'sourceRef':source}
    official = [row('2026-09-17', 16, 'official'), row('2026-09-18', 15, 'official')]
    yahoo = [row('2026-09-18', 15.1, 'yahoo')]
    initial = m.merge_feature_sources(yahoo, official, path=path, received_at=AT)
    new = row('2026-09-21', 14, 'yahoo')
    appended = m.merge_feature_sources([new], official, path=path, received_at=LATER)
    assert appended[:-1] == initial  # Dropped Yahoo date retains exact provider and vintage.
    assert m.merge_feature_sources([], official, path=path, received_at=LATER) == appended
    corrected = m.merge_feature_sources([row('2026-09-18', 15.2, 'yahoo')], official,
                                         path=path, received_at=LATER)
    assert corrected[1]['availableFrom'] == LATER and corrected[1]['close'] == 15.2
    with m.connect(path) as db:
        assert db.execute('SELECT count(*) FROM selected_vix_inputs').fetchone()[0] == 4
        original = json.loads(db.execute("SELECT body FROM selected_vix_inputs WHERE session='2026-09-18' ORDER BY seq LIMIT 1").fetchone()[0])
        assert original == initial[1]
