import copy
import json
import pytest

import argus_jp_market_research as research
import argus_today_intelligence as engine
import argus_market_brief as composer
from test_argus_today_intelligence import market_bars


@pytest.fixture(scope='module')
def snapshot():
    calibration = engine.calibrate_forecast(market_bars(180), market='JP')
    body = {'symbol': 'N225', 'market': 'JP', 'asOf': '2026-09-15T10:00:00Z',
        'ohlcv': None, 'calibration': calibration, 'shortSelling': {},
        'failedRally': {}, 'methodVersion': engine.METHOD_VERSION}
    return {**body, 'id': 'today-' + engine._hash(body)}


def test_original_output_preserved_and_no_probability_promotion(snapshot):
    original = copy.deepcopy(snapshot)
    package = research.package_from_snapshot(snapshot)
    assert package['calculation'] == snapshot['calibration']
    assert package['actionAuthority'] is False
    assert package['predictiveProbabilityValidated'] is False
    assert snapshot == original
    package['calculation']['historyCount'] = 0
    assert snapshot == original


def test_repeated_lookup_never_invokes_calculation_or_changes_package(snapshot, monkeypatch):
    def forbidden(*args, **kwargs): raise AssertionError('unexpected recomputation')
    monkeypatch.setattr(engine, 'calibrate_forecast', forbidden)
    monkeypatch.setattr(engine, 'analyze', forbidden)
    state = {'snapshots': [snapshot]}
    first = research.lookup(state, cutoff='2026-09-15T11:00:00Z')
    second = research.lookup(state, cutoff='2026-09-15T12:00:00Z')
    assert first['packages'] == second['packages']
    assert len(first['packages']) == 1
    assert first['readReceipt']['fullRecalculations'] == 0
    assert first['readReceipt']['sources'][0]['sourceSnapshotId'] == snapshot['id']


def test_future_or_tampered_latest_is_not_used(snapshot):
    state = {'snapshots': [snapshot]}
    assert not research.lookup(state, cutoff='2026-09-15T09:00:00Z')['packages']
    broken = copy.deepcopy(snapshot)
    broken['calibration']['historyCount'] += 1
    result = research.lookup({'snapshots': [broken]}, cutoff='2026-09-15T11:00:00Z')
    assert not result['packages']
    assert result['readReceipt']['errors'][0]['reason'] == 'research_source_integrity_failed'


def test_package_version_changes_only_for_changed_calculation(snapshot):
    newer = copy.deepcopy(snapshot)
    newer['asOf'] = '2026-09-15T11:00:00Z'
    newer['id'] = 'today-' + engine._hash({k:v for k,v in newer.items() if k != 'id'})
    assert research.package_from_snapshot(newer) == research.package_from_snapshot(snapshot)
    newer['calibration']['horizons']['5']['modelBrier'] = 0.999
    newer['id'] = 'today-' + engine._hash({k:v for k,v in newer.items() if k != 'id'})
    assert research.package_from_snapshot(newer)['packageVersion'] != research.package_from_snapshot(snapshot)['packageVersion']


def test_index_and_etf_are_distinct_and_original_kept(snapshot):
    etf = copy.deepcopy(snapshot)
    etf['symbol'] = '1321'
    etf['id'] = 'today-' + engine._hash({k:v for k,v in etf.items() if k != 'id'})
    result = research.lookup({'snapshots': [snapshot, etf]}, cutoff='2026-09-15T11:00:00Z')
    assert {p['instrumentId'] for p in result['packages']} == {'JP:N225:INDEX', 'JP:1321:ETF'}
    assert len({p['packageVersion'] for p in result['packages']}) == 2


def test_context_contains_bounded_calculated_references(snapshot):
    result = research.lookup({'snapshots': [snapshot]}, cutoff='2026-09-15T11:00:00Z')
    brief = composer.compose_brief(now_iso='2026-09-15T11:00:00Z')
    brief['numericalResearch'] = result
    brief['facts'] += research.explanation_facts(result)
    context = composer.unified_context(brief)
    refs = context['researchPackages']
    assert refs[0]['packageVersion'] == result['packages'][0]['packageVersion']
    assert refs[0]['horizons']['5']['modelBrier'] == snapshot['calibration']['horizons']['5']['modelBrier']
    assert len(json.dumps(refs).encode()) < 8192
    assert 'readReceipt' not in context
    assert any(f['source'] == 'jp_market_research' for f in context['facts'])


def test_snapshot_admission_bounds(snapshot):
    huge = copy.deepcopy(snapshot)
    huge['calibration']['extra'] = 'x' * research.MAX_PACKAGE_BYTES
    huge['id'] = 'today-' + engine._hash({k:v for k,v in huge.items() if k != 'id'})
    with pytest.raises(ValueError, match='bound_exceeded'):
        research.package_from_snapshot(huge)
    old = copy.deepcopy(snapshot); old['methodVersion'] = 'unknown'
    with pytest.raises(ValueError, match='method_not_admitted'):
        research.package_from_snapshot(old)


def test_same_research_version_survives_existing_history_and_private_context(snapshot, tmp_path):
    import argus_analysis_history as history
    import argus_owner_dialogue as dialogue
    from test_argus_unified_brief import response
    lookup = research.lookup({'snapshots': [snapshot]}, cutoff='2026-09-15T11:00:00Z')
    brief = composer.compose_brief(now_iso='2026-09-15T11:00:00Z')
    brief['numericalResearch'] = lookup
    brief['facts'] += research.explanation_facts(lookup)
    brief['unifiedContext'] = composer.unified_context(brief)
    brief['unifiedSummary'] = {'contextId': brief['unifiedContext']['contextId'],
        'ownerContextAvailable': False, 'actionAuthority': False, 'sections': response(brief['unifiedContext'])}
    brief['unifiedStatus'] = 'GENERATED'
    brief['aiDiagnostics'] = {'completedAt': '2026-09-15T11:01:00Z'}
    record = history.make_record(brief, {})
    path = tmp_path / 'existing_history.sqlite3'
    history.initialize(path); history.append(path, record)
    restored = history.read_record(path, record['recordId'])
    assert restored['brief']['numericalResearch'] == lookup
    context = dialogue.build_context(brief=brief, symbol='N225', market='JP', horizon=20,
        question='中期はどうですか', received_at='2026-09-15T11:02:00Z')
    assert set(context['researchPackages'][0]['horizons']) == {'20'}
    assert not any(f['source'] == 'jp_market_research' for f in context['facts'])
    assert context['researchPackages'][0]['packageVersion'] == lookup['packages'][0]['packageVersion']
    assert context['actionAuthority'] is False
