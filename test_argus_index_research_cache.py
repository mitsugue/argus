from copy import deepcopy
import json
import pytest
import argus_index_research_cache as cache

AT = '2026-09-15T10:00:00Z'
LATER = '2026-09-15T11:00:00Z'
KEY = 'chart:N225:daily'
METHOD = 'test-calculation-v1'


def report(index='N225', timeframe='daily'):
    return {'reportId':'original', 'index':index, 'symbol':index, 'timeframe':timeframe,
            'todayIntelligence':{'calibration':{'validated':False, 'modelBrier':.6686}}}


def test_persistent_readback_keeps_numeric_payload_and_original_time(tmp_path):
    original = report()
    value = cache.record(KEY, original, method=METHOD, at=AT)
    path = tmp_path / 'cache.json'
    path.write_text(json.dumps(cache.envelope({KEY:value})))
    restored = cache.load(path, method=METHOD, now=LATER)
    read = cache.read(restored, KEY, method=METHOD, now=LATER)
    assert read['payload'] == original and read['calculatedAt'] == AT
    read['payload']['todayIntelligence']['calibration']['modelBrier'] = 0
    assert restored[KEY]['payload'] == original
    assert cache.load(path, method='new-method', now=LATER) == {}
    assert cache.load(path, method=METHOD, now='2026-09-14T00:00:00Z') == {}


@pytest.mark.parametrize('damage', ['body', 'record_hash', 'key', 'size'])
def test_corrupt_or_unbounded_cache_is_not_admitted(tmp_path, monkeypatch, damage):
    value = cache.record(KEY, report(), method=METHOD, at=AT)
    doc = cache.envelope({KEY:value})
    if damage == 'body': doc['records'][KEY]['payload']['reportId'] = 'edited'
    if damage == 'record_hash':
        doc['records'][KEY]['sha256'] = '0'*64; doc['sha256'] = cache.digest(doc['records'])
    if damage == 'key':
        doc['records']['chart:unknown:daily'] = value; doc['sha256'] = cache.digest(doc['records'])
    if damage == 'size': monkeypatch.setattr(cache, 'MAX_BYTES', 8)
    path = tmp_path/'cache.json'; path.write_text(json.dumps(doc))
    with pytest.raises(ValueError): cache.load(path, method=METHOD, now=LATER)


def test_public_chart_and_comparison_never_compute_fetch_or_write(monkeypatch):
    import scanner
    monkeypatch.setattr(scanner, '_INDEX_RESEARCH_REPORTS', {})
    monkeypatch.setattr(scanner, '_ai_now_iso', lambda:LATER)
    def forbidden(*args, **kwargs): pytest.fail('public screen invoked background work')
    for name in ('_index_chart_calculate', '_jp_market_comparison_calculate', '_index_research_restore', '_index_research_warm'):
        monkeypatch.setattr(scanner, name, forbidden)
    monkeypatch.setattr(scanner.requests, 'get', forbidden)
    monkeypatch.setattr(scanner.argus_persistent_storage, 'atomic_write_json', forbidden)
    with scanner.app.test_client() as client:
        assert client.get('/api/argus/index-chart?index=N225').json['status'] == 'expected_skip'
        assert client.get('/api/argus/index-chart?index=N225&comparison=1').json['status'] == 'unavailable'
        saved = cache.record(KEY, report(), method=scanner._INDEX_RESEARCH_METHOD, at=AT)
        scanner._INDEX_RESEARCH_REPORTS[KEY] = saved
        comparison = {'status':'available', 'comparison':{'horizonSessions':5, 'probabilityValidated':False}}
        scanner._INDEX_RESEARCH_REPORTS['comparison:N225:5'] = cache.record(
            'comparison:N225:5', comparison, method=scanner._INDEX_RESEARCH_METHOD, at=AT)
        for _ in range(3):
            value = client.get('/api/argus/index-chart?index=N225').json
            assert value['todayIntelligence'] == report()['todayIntelligence']
            assert value['researchCache']['calculatedAt'] == AT
            assert value['researchCache']['fullRecalculations'] == 0
            assert client.get('/api/argus/index-chart?index=N225&comparison=1').json['comparison'] == comparison['comparison']
        assert scanner._INDEX_RESEARCH_REPORTS[KEY] == saved


def test_background_warm_persists_and_retains_last_good_on_failure(monkeypatch,tmp_path):
    import scanner
    monkeypatch.setattr(scanner, '_INDEX_RESEARCH_REPORTS', {})
    monkeypatch.setattr(scanner, '_INDEX_RESEARCH_STATUS', {'restoreAttempted':False})
    monkeypatch.setattr(scanner, '_index_research_path', lambda:str(tmp_path/'cache.json'))
    monkeypatch.setattr(scanner, '_ai_now_iso', lambda:AT)
    monkeypatch.setattr(scanner.argus_product_naming, 'require_allowed', lambda v:None)
    monkeypatch.setattr(scanner, '_index_chart_calculate', report)
    monkeypatch.setattr(scanner, '_jp_market_comparison_calculate', lambda h:{'status':'available','comparison':{'horizon':h}})
    scanner._index_research_warm()
    before = deepcopy(scanner._INDEX_RESEARCH_REPORTS)
    assert len(before) == 12
    assert scanner._INDEX_RESEARCH_STATUS['persistenceStatus'] == 'VERIFIED'
    scanner._INDEX_RESEARCH_REPORTS.clear()
    scanner._INDEX_RESEARCH_STATUS['restoreAttempted'] = False
    scanner._index_research_restore()
    assert scanner._INDEX_RESEARCH_REPORTS == before
    scanner._INDEX_RESEARCH_STATUS['lastAttemptMonotonic'] = -1e20
    monkeypatch.setattr(scanner, '_ai_now_iso', lambda:LATER)
    def failed(*a,**kw): raise ValueError('source_unavailable')
    monkeypatch.setattr(scanner, '_index_chart_calculate', failed)
    monkeypatch.setattr(scanner, '_jp_market_comparison_calculate', failed)
    scanner._index_research_warm()
    assert scanner._INDEX_RESEARCH_REPORTS == before
    assert scanner._INDEX_RESEARCH_STATUS['status'] == 'PARTIAL'


def test_cache_read_diagnostics_do_not_invent_a_changed_calculation():
    from argus_explanation_contract import calculation_identity
    first = {'5':{'comparison':{'estimate':101.2}, 'researchCache':{'calculatedAt':AT,'refreshStatus':'AVAILABLE'}}}
    second = deepcopy(first)
    second['5']['researchCache'] = {'calculatedAt':LATER,'refreshStatus':'PARTIAL','recordSha256':'updated'}
    assert calculation_identity(first) == calculation_identity(second)
    second['5']['comparison']['estimate'] = 99.8
    assert calculation_identity(first) != calculation_identity(second)
