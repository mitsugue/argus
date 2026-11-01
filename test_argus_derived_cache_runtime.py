"""Runtime write verification keeps independent receipt and installed-file checks."""
import pytest
import argus_index_research_cache as research
import argus_persistent_storage as storage
import jp_market_features as features
from test_argus_derived_cache_verification import AT, METHOD, feature_history

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
