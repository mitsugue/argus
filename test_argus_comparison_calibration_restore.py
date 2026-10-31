"""Restart reuses only content-bound completed studies in the existing file."""
from copy import deepcopy
import json
from unittest.mock import Mock

import pytest

import argus_index_research_cache as store
import jp_market_analog_backtest as backtest
import jp_market_price_paths as paths
from test_jp_market_analog_cache_revisions import BARS, DAYS, CUTOFF, row


def compare(state, *, bars=None, sessions=None, **kwargs):
    return paths.cached_index_comparison(bars if bars is not None else BARS,
        cutoff=CUTOFF, session_dates=sessions if sessions is not None else DAYS,
        backtest_cache=state, **kwargs)


def persist(path, state, *, at=CUTOFF, method='engine-code-hash'):
    saved = store.calibration_record(state, method=method, at=at)
    reports = {'comparison:N225:5': store.record('comparison:N225:5',
        {'comparison': {'unchanged': 3}}, method='reports', at=CUTOFF)}
    path.write_text(json.dumps(store.envelope(reports, calibration=saved)))
    return store.load_with_calibration(path, method='reports', now=CUTOFF,
                                        calibration_method='engine-code-hash')


def test_restart_rebuilds_episodes_but_reuses_studies_with_exact_result(tmp_path, monkeypatch):
    state = {}
    original = compare(state)
    reports, restored = persist(tmp_path/'existing.json', state)
    assert set(restored) == store.CALIBRATION_FIELDS
    assert 'sealedCandidates' not in restored and 'signEventStudy' not in restored
    for name in ('walk_forward', 'weight_search'):
        monkeypatch.setattr(backtest, name, Mock(side_effect=AssertionError('unchanged study replayed')))
    # JSON changes tuple containers to lists; the numerical outcome stays exact.
    assert json.loads(json.dumps(compare(restored))) == json.loads(json.dumps(original))
    assert 'sealedCandidates' in restored
    assert reports['comparison:N225:5']['calculatedAt'] == CUTOFF
    assert not original['actionAuthority']


@pytest.mark.parametrize('changed', ['price', 'receipt', 'state', 'condition', 'reaction', 'calendar'])
def test_restored_study_never_hides_same_count_revision(tmp_path, monkeypatch, changed):
    evidence = dict(state_rows=[row('credit.loss_pct', -1)],
                    condition_rows=[row('d01_credit_stress', 1)],
                    reaction_rows=[row('material.CPI.3', 1, eventId='test', eventType='CPI',
                                       reactionWindowSessions=3)])
    state = {}; compare(state, **evidence)
    _, restored = persist(tmp_path/'existing.json', state)
    bars, sessions = deepcopy(BARS), list(DAYS)
    if changed == 'price': bars[35]['close'] += 700
    elif changed == 'receipt': bars[35]['availableFrom'] = CUTOFF
    elif changed == 'calendar': sessions[2] = '2026-01-03'
    else:
        key = {'state': 'state_rows', 'condition': 'condition_rows', 'reaction': 'reaction_rows'}[changed]
        evidence[key][0]['value'] += 9
    walk = Mock(wraps=backtest.walk_forward); monkeypatch.setattr(backtest, 'walk_forward', walk)
    compare(restored, bars=bars, sessions=sessions, **evidence)
    assert walk.call_count == 2
    assert restored['key'] != state['key']


@pytest.mark.parametrize('ineligible', ['code', 'future'])
def test_code_change_or_future_save_keeps_reports_but_not_calibration(tmp_path, ineligible):
    state = {}; compare(state)
    path = tmp_path/'existing.json'
    saved = store.calibration_record(state, method='other' if ineligible == 'code' else 'engine-code-hash',
                                     at='2099-01-01T00:00:00Z' if ineligible == 'future' else CUTOFF)
    path.write_text(json.dumps(store.envelope({}, calibration=saved)))
    assert store.load_with_calibration(path, method='reports', now=CUTOFF,
                                       calibration_method='engine-code-hash') == ({}, {})


def test_legacy_file_and_tampering_do_not_admit_a_study(tmp_path):
    path = tmp_path/'existing.json'
    path.write_text(json.dumps(store.envelope({})))
    assert store.load_with_calibration(path, method='reports', now=CUTOFF,
                                       calibration_method='engine-code-hash') == ({}, {})
    state = {}; compare(state)
    persist(path, state)
    doc = json.loads(path.read_text()); doc['comparisonCalibration']['state']['result']['method'] = 'edited'
    path.write_text(json.dumps(doc))
    with pytest.raises(ValueError, match='integrity'):
        store.load_with_calibration(path, method='reports', now=CUTOFF,
                                    calibration_method='engine-code-hash')


def test_oversize_optional_state_does_not_prevent_existing_report_save(tmp_path, monkeypatch):
    import scanner
    monkeypatch.setattr(scanner, '_INDEX_RESEARCH_REPORTS', {})
    monkeypatch.setattr(scanner, '_INDEX_RESEARCH_STATUS', {'restoreAttempted': True})
    state = {}; compare(state)
    state['result']['padding'] = 'x' * store.CALIBRATION_MAX_BYTES
    monkeypatch.setattr(scanner, '_JP_ANALOG_BACKTEST_CACHE', state)
    monkeypatch.setattr(scanner, '_index_research_path', lambda: str(tmp_path/'existing.json'))
    monkeypatch.setattr(scanner, '_ai_now_iso', lambda: CUTOFF)
    monkeypatch.setattr(scanner.argus_product_naming, 'require_allowed', lambda _: None)
    monkeypatch.setattr(scanner, '_index_chart_calculate', lambda *a: {'status': 'unavailable'})
    monkeypatch.setattr(scanner, '_jp_market_comparison_calculate',
                        lambda h: {'status': 'available', 'comparison': {'horizon': h}})
    scanner._index_research_warm()
    assert scanner._INDEX_RESEARCH_STATUS['persistenceStatus'] == 'VERIFIED'
    assert scanner._INDEX_RESEARCH_STATUS['calibrationSaveError'] == 'ValueError'
    assert len(store.load(tmp_path/'existing.json', method=scanner._INDEX_RESEARCH_METHOD, now=CUTOFF)) == 4


def test_scanner_cold_restore_adopts_small_calibration_without_running_engine(tmp_path, monkeypatch):
    import scanner
    state = {}; compare(state)
    saved = store.calibration_record(state, method=store.calibration_method(), at=CUTOFF)
    path = tmp_path/'existing.json'; path.write_text(json.dumps(store.envelope({}, calibration=saved)))
    monkeypatch.setattr(scanner, '_INDEX_RESEARCH_REPORTS', {})
    monkeypatch.setattr(scanner, '_INDEX_RESEARCH_STATUS', {})
    monkeypatch.setattr(scanner, '_JP_ANALOG_BACKTEST_CACHE', {})
    monkeypatch.setattr(scanner, '_index_research_path', lambda: str(path))
    monkeypatch.setattr(scanner, '_ai_now_iso', lambda: CUTOFF)
    monkeypatch.setattr(scanner.argus_product_naming, 'require_allowed', lambda _: None)
    monkeypatch.setattr(backtest, 'walk_forward', Mock(side_effect=AssertionError('restore computed')))
    scanner._index_research_restore()
    assert scanner._INDEX_RESEARCH_STATUS['calibrationRestored']
    assert scanner._JP_ANALOG_BACKTEST_CACHE == saved['state']


def test_engine_fingerprint_changes_when_numerical_source_changes(tmp_path, monkeypatch):
    root = tmp_path/'argus_index_research_cache.py'; root.write_text('unused')
    names = ('argus_index_research_cache.py', 'jp_market_price_paths.py', 'jp_market_analog_backtest.py',
             'jp_market_analogs.py', 'jp_market_engine.py', 'jp_market_level_map.py')
    for name in names: (tmp_path/name).write_text('original')
    monkeypatch.setattr(store, '__file__', str(root)); store.calibration_method.cache_clear()
    try:
        before = store.calibration_method()
        (tmp_path/names[1]).write_text('changed numerical code')
        store.calibration_method.cache_clear()
        assert store.calibration_method() != before
    finally:
        store.calibration_method.cache_clear()


def test_optional_state_cannot_push_valid_reports_over_existing_file_bound(tmp_path, monkeypatch):
    state = {}; compare(state)
    saved = store.calibration_record(state, method='m', at=CUTOFF)
    reports = {'comparison:N225:5': store.record('comparison:N225:5',
        {'comparison': {'kept': True}}, method='reports', at=CUTOFF)}
    limit = len(json.dumps(store.envelope(reports)).encode()) + 1
    monkeypatch.setattr(store, 'MAX_BYTES', limit)
    doc = store.envelope(reports, calibration=saved)
    assert 'comparisonCalibration' not in doc
    path = tmp_path/'existing.json'; path.write_text(json.dumps(doc))
    assert store.load(path, method='reports', now=CUTOFF) == reports
