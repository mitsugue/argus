"""Runtime write verification keeps independent receipt and installed-file checks."""
import pytest
import argus_index_research_cache as research
import argus_persistent_storage as storage
import jp_market_features as features
from test_argus_derived_cache_verification import AT, METHOD, feature_history


def test_separate_restores_public_reads_and_record_sources_remain_independent(tmp_path):
    from copy import deepcopy
    import json
    payload = {'comparison': {'values': [1.25, -0.0], 'policy': ('a', 'b')}}
    original = deepcopy(payload)
    key = 'comparison:N225:5'
    record = research.record(key, payload, method=METHOD, at=AT)
    payload['comparison']['values'][0] = 999
    assert record['payload'] == json.loads(json.dumps(original))
    state = dict(key='c'*64, result={'values':[1.25]}, search=None,
                 materialReactionResearch=None, yardstickResearch=None)
    saved = research.calibration_record(state, method='calibration', at=AT)
    path = tmp_path/'cache.json'
    path.write_text(json.dumps(research.envelope({key:record}, calibration=saved)))
    first, calibration = research.load_with_calibration(path, method=METHOD, now=AT,
                                                        calibration_method='calibration')
    second, other_calibration = research.load_with_calibration(path, method=METHOD, now=AT,
                                                              calibration_method='calibration')
    assert first == second == {key:record}
    public = research.read(first, key, method=METHOD, now=AT)
    public['payload']['comparison']['values'][0] = 888
    assert first == second
    first[key]['payload']['comparison']['values'][0] = 777
    calibration['result']['values'][0] = 666
    assert second == {key:record}
    assert other_calibration == saved['state'] == state
    restored, checked = research.load_with_calibration(path, method=METHOD, now=AT,
                                                       calibration_method='calibration')
    assert restored == second and checked == other_calibration

@pytest.mark.parametrize('damage', ['receipt', 'installed', 'mutated_source', None])
def test_feature_save_checks_source_and_installed_bytes_without_parsing(tmp_path, monkeypatch, damage):
    import scanner
    history = feature_history()
    monkeypatch.setattr(scanner, '_JP_MARKET_FEATURE_HISTORY', history)
    monkeypatch.setattr(scanner, '_JP_MARKET_FEATURE_CACHE_STATUS', {})
    monkeypatch.setattr(scanner.argus_product_naming, 'require_allowed', lambda _: None)
    def forbidden(*args, **kwargs):
        pytest.fail('write verification parsed the complete cache')
    monkeypatch.setattr(features, 'load_history_cache', forbidden)
    writer = storage.atomic_write_json
    def write(path, doc, **kwargs):
        if damage == 'mutated_source': doc['history']['features'][0]['value'] = 999
        result = writer(path, doc, **kwargs)
        if damage == 'receipt': result['snapshotHash'] = '0' * 64
        if damage == 'installed':
            from pathlib import Path
            Path(path).write_bytes(b'{}')
        return result
    monkeypatch.setattr(storage, 'atomic_write_json', write)
    scanner._jp_market_feature_history_persist(str(tmp_path/'feature.json'), METHOD, AT)
    assert scanner._JP_MARKET_FEATURE_CACHE_STATUS['persistenceStatus'] == (
        'VERIFIED' if damage is None else 'FAILED')


@pytest.mark.parametrize('damage', ['receipt', 'installed', None])
def test_research_save_distrusts_receipt_and_never_parses_full_readback(tmp_path, monkeypatch, damage):
    import scanner
    monkeypatch.setattr(scanner, '_INDEX_RESEARCH_REPORTS', {})
    monkeypatch.setattr(scanner, '_INDEX_RESEARCH_STATUS', {'restoreAttempted': True})
    monkeypatch.setattr(scanner, '_JP_ANALOG_BACKTEST_CACHE', {})
    monkeypatch.setattr(scanner, '_index_research_path', lambda: str(tmp_path/'research.json'))
    monkeypatch.setattr(scanner, '_ai_now_iso', lambda: AT)
    monkeypatch.setattr(scanner.argus_product_naming, 'require_allowed', lambda _: None)
    monkeypatch.setattr(scanner, '_index_chart_calculate', lambda *a: {'status':'unavailable'})
    monkeypatch.setattr(scanner, '_jp_market_comparison_calculate',
        lambda h: {'status':'available', 'comparison': {'horizon':h}})
    def forbidden(*args, **kwargs): pytest.fail('parsed full write readback')
    monkeypatch.setattr(research, 'load_with_calibration', forbidden)
    writer = storage.atomic_write_json
    def write(path, doc, **kwargs):
        result = writer(path, doc, **kwargs)
        if damage == 'receipt': result['snapshotHash'] = '0' * 64
        if damage == 'installed':
            from pathlib import Path
            Path(path).write_bytes(b'{}')
        return result
    monkeypatch.setattr(storage, 'atomic_write_json', write)
    scanner._index_research_warm()
    assert scanner._INDEX_RESEARCH_STATUS.get('persistenceStatus') == ('VERIFIED' if damage is None else None)
    if damage is not None:
        assert scanner._INDEX_RESEARCH_STATUS['status'] == 'FAILED'
