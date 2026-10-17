from copy import deepcopy
import pytest
import argus_today_intelligence as engine
from test_argus_today_intelligence import market_bars

AT = '2026-09-15T10:00:00Z'

@pytest.fixture(scope='module')
def prepared():
    bars=market_bars(180)
    result=engine.analyze(bars,symbol='N225',market='JP',as_of=AT)
    state=engine.merge_analysis(engine.empty_state(),result,bars[-1],[],AT)
    return bars,result,state['snapshots'][-1]


def test_repeated_execution_reuses_saved_calculations_after_state_roundtrip(prepared,monkeypatch):
    import json
    bars,original,snapshot=prepared
    recovered=engine.normalize_state(json.loads(json.dumps({'snapshots':[snapshot]})))['snapshots'][0]
    def blocked(*a,**kw):raise AssertionError('full calculation repeated')
    monkeypatch.setattr(engine,'calibrate_forecast',blocked)
    monkeypatch.setattr(engine,'failed_rally_backtest',blocked)
    reused=engine.analyze(bars,symbol='N225',market='JP',as_of='2026-09-15T11:00:00Z',stored_calculation=recovered)
    assert reused['calculationReuse']['calibration'] is True
    assert reused['calculationReuse']['failedRally'] is True
    for key in ('calibration','failedRally','shortSelling','historyCoverage'):
        assert reused[key]==original[key]
    assert reused['asOf']!=original['asOf']
    assert snapshot==prepared[2]


def test_source_correction_invalidates_only_dependent_results(prepared,monkeypatch):
    bars,original,snapshot=prepared
    calls=[]
    original_cal=engine.calibrate_forecast
    def calculate(*a,**kw):calls.append('calibration');return original_cal(*a,**kw)
    monkeypatch.setattr(engine,'calibrate_forecast',calculate)
    # Conditioning changes, while price/short-selling/comparison stay equal.
    context={'sourceIssues':['provider_not_available']}
    changed=engine.analyze(bars,symbol='N225',market='JP',as_of=AT,stored_calculation=snapshot,jp_market_engine_context=context)
    assert calls==['calibration']
    assert changed['calculationReuse']['failedRally'] is True
    assert changed['calculationReuse']['calibration'] is False


def test_price_revision_invalidates_both_and_matches_uncached(prepared):
    bars,_,snapshot=prepared
    corrected=deepcopy(bars);corrected[-2]['close']*=1.001
    actual=engine.analyze(corrected,symbol='N225',market='JP',as_of=AT,stored_calculation=snapshot)
    fresh=engine.analyze(corrected,symbol='N225',market='JP',as_of=AT)
    assert actual==fresh
    assert not actual['calculationReuse']['calibration']
    assert not actual['calculationReuse']['failedRally']


@pytest.mark.parametrize('case',['tampered','future','other_symbol','old_without_input_receipt'])
def test_untrusted_or_unbound_snapshot_does_not_avoid_calculation(prepared,case):
    bars,_,saved=prepared;snapshot=deepcopy(saved)
    if case=='tampered':snapshot['calibration']['historyCount']=0
    if case=='future':snapshot['asOf']='2026-09-16T10:00:00Z'
    if case=='other_symbol':snapshot['symbol']='1321'
    if case=='old_without_input_receipt':snapshot.pop('researchInputDigests')
    if case!='tampered':snapshot['id']='today-'+engine._hash({k:v for k,v in snapshot.items() if k!='id'})
    result=engine.analyze(bars,symbol='N225',market='JP',as_of=AT,stored_calculation=snapshot)
    assert not result['calculationReuse']['calibration']
    assert not result['calculationReuse']['failedRally']


def test_live_breadth_freshness_is_never_restored_from_old_calibration(prepared):
    bars,original,saved=prepared;snapshot=deepcopy(saved)
    snapshot['calibration']['horizons']['5']['probabilityTruthEvidence']['breadthLagTradingDays']=0
    snapshot['id']='today-'+engine._hash({k:v for k,v in snapshot.items() if k!='id'})
    result=engine.analyze(bars,symbol='N225',market='JP',as_of=AT,stored_calculation=snapshot)
    assert result['calculationReuse']['calibration'] is True
    assert result['calibration']==original['calibration']
    assert snapshot['calibration']['horizons']['5']['probabilityTruthEvidence']['breadthLagTradingDays']==0


def test_unchanged_calculation_keeps_original_receipt_and_does_not_consume_history(prepared):
    bars,result,snapshot=prepared
    state={'snapshots':[deepcopy(snapshot)]}
    reused=engine.analyze(bars,symbol='N225',market='JP',as_of='2026-09-15T11:00:00Z',stored_calculation=snapshot)
    next_state=engine.merge_analysis(state,reused,bars[-1],[],'2026-09-15T11:00:00Z')
    assert next_state['snapshots']==[snapshot]
    assert next_state['lastUpdatedAt']=='2026-09-15T11:00:00Z'
    revised=deepcopy(reused);revised['calibration']['horizons']['5']['modelBrier']=0.987
    updated=engine.merge_analysis(next_state,revised,bars[-1],[],'2026-09-15T12:00:00Z')
    assert len(updated['snapshots'])==2
    assert updated['snapshots'][0]==snapshot


@pytest.mark.parametrize('field,value', [('researchInputDigests', []), ('horizons', []), ('horizons', {'5': None})])
def test_malformed_saved_computation_falls_back_without_changing_values(prepared, field, value):
    bars, original, saved = prepared
    snapshot = deepcopy(saved)
    if field == 'researchInputDigests':
        snapshot[field] = value
    else:
        snapshot['calibration'][field] = value
    snapshot['id'] = 'today-' + engine._hash({k: v for k, v in snapshot.items() if k != 'id'})
    result = engine.analyze(bars, symbol='N225', market='JP', as_of=AT, stored_calculation=snapshot)
    assert result['calibration'] == original['calibration']
    assert result['calculationReuse']['calibration'] is False


def test_saved_research_edition_is_visible_before_next_input_comparison(monkeypatch):
    import scanner
    state = {'lastPresentation': {'generatedAt': '2026-09-15T09:00:00Z'}}
    monkeypatch.setattr(scanner, '_MARKET_BRIEF', state)
    monkeypatch.setattr(scanner, '_compose_market_brief', lambda: {'facts': [], 'generatedAt': AT})
    monkeypatch.setattr(scanner, '_jp_market_internals_cached', lambda: {})
    monkeypatch.setattr(scanner, '_jp_market_comparison_cached', lambda h: {})
    monkeypatch.setattr(scanner.argus_market_brief, 'calculation_facts', lambda c: [])
    monkeypatch.setattr(scanner.jp_market_internals, 'explanation_facts', lambda i: [])
    monkeypatch.setattr(scanner.argus_market_brief, 'unified_context', lambda *a: {})
    calls = []
    def fingerprint(*args):
        if calls:
            # A slow/failing post-generation refresh must not hold back saved output.
            assert state['data']['unifiedStatus'] == 'GENERATED'
            assert state['lastPresentation']['generatedAt'] == AT
            assert state['lastPresentation']['analysisHistory']['status'] == 'LOCAL_DURABLE'
        calls.append(True)
        return str(len(calls))
    def polish(brief):
        return {**brief, 'unifiedStatus': 'GENERATED', 'presentationStatus': 'GENERATED',
                'unifiedSummary': {'sections': {}}, 'aiDiagnostics': {'completedAt': AT}}
    monkeypatch.setattr(scanner, '_market_brief_generation_input_digest', fingerprint)
    monkeypatch.setattr(scanner, '_market_brief_ai_polish', polish)
    monkeypatch.setattr(scanner, '_market_brief_history_save',
                        lambda b: b.update(analysisHistory={'status': 'LOCAL_DURABLE'}))
    scanner._market_brief_refresh(allow_ai=True)
    assert len(calls) == 2
    assert state['generationInputDigest'] is None
