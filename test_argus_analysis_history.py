import copy
import json
from concurrent.futures import ThreadPoolExecutor
import pytest

import argus_analysis_history as history
import argus_market_brief as composer
import scanner


def brief(at='2026-09-13T00:00:00Z', material='VIX 20を観測'):
    item = composer.compose_brief(now_iso=at)
    item['facts'] = [{'text': material, 'source': 'official_sensor', 'priority': 'P1', 'verification': 'VERIFIED'}]
    context = composer.unified_context(item)
    ref = context['facts'][0]['evidenceId']
    raw = {key: {'textJa': '市場の反応を確認します。', 'evidenceIds': [ref], 'kind': 'INFERENCE'} for key in composer.UNIFIED_SECTIONS}
    for key in ('impact', 'changes'): raw[key] = {'textJa':'未確認です。','evidenceIds':[],'kind':'UNKNOWN'}
    item.update(unifiedContext=context, unifiedSummary=composer.validate_unified_ai(raw, context),
                unifiedStatus='GENERATED', aiDiagnostics={'completedAt':at, 'requestedModel':'gpt-6-astra', 'returnedModel':'gpt-6-astra'},
                aiText={'nowJa':'市場の反応を確認します。','whyJa':'需給の変化を確認します。','nextJa':'価格の反応を確認します。'})
    return item


def test_input_update_keeps_original_explanation_and_calculation(tmp_path):
    path = tmp_path/'history.sqlite'; history.initialize(path)
    first = history.make_record(brief(), {'5': {'epsInput': 3000, 'forecastLine': [100, 101]}})
    second = history.make_record(brief('2026-09-14T00:00:00Z', 'VIX 21を観測'), {'5': {'epsInput':3100,'forecastLine':[100,102]}})
    assert history.append(path, first)['inserted']
    assert history.append(path, second)['inserted']
    assert history.read_record(path, first['recordId']) == first
    assert history.read_record(path) == second
    assert first['inputSnapshotDigest'] != second['inputSnapshotDigest']
    assert history.read_record(path, first['recordId'])['calculations']['5']['epsInput'] == 3000
    assert not history.append(path, first)['inserted']
    page = history.read_page(path,limit=1)
    assert page['hasMore'] and page['rows'][0]['recordId'] == second['recordId']
    assert history.read_page(path,before_sequence=page['nextBeforeSequence'])['rows'][0]['recordId'] == first['recordId']
    assert path.stat().st_mode & 0o777 == 0o600


def test_record_does_not_alias_mutable_inputs_or_admit_changed_old_values(tmp_path):
    b = brief(); calc = {'5':{'epsInput':3000}}
    row = history.make_record(b,calc); calc['5']['epsInput']=9999; b['facts'][0]['text']='changed'
    assert row['calculations']['5']['epsInput']==3000
    changed = copy.deepcopy(row); changed['calculations']['5']['epsInput']=9999
    with pytest.raises(ValueError): history.validate_record(changed)
    path=tmp_path/'history.sqlite'; history.initialize(path); history.append(path,row)
    with pytest.raises(ValueError): history.append(path,changed)
    assert history.read_record(path)==row


def test_read_missing_storage_does_not_initialize_it(tmp_path):
    path=tmp_path/'missing.sqlite'
    with pytest.raises(FileNotFoundError): history.read_page(path)
    assert not path.exists()


def test_concurrent_first_writes_keep_each_distinct_record(tmp_path):
    path=tmp_path/'history.sqlite'
    def add(day):
        history.initialize(path)
        return history.append(path,history.make_record(brief(f'2026-09-{day:02d}T00:00:00Z'),{}))
    with ThreadPoolExecutor(max_workers=4) as pool: list(pool.map(add,range(13,17)))
    assert len(history.read_page(path)['rows'])==4


@pytest.mark.parametrize('field,value', [('unifiedStatus','INVALID_RESPONSE'),('sdaAuthority',True)])
def test_only_accepted_non_authoritative_views_are_recorded(field,value):
    b=brief(); b[field]=value
    with pytest.raises(ValueError): history.make_record(b,{})


def test_public_history_does_not_accept_private_owner_context():
    b=brief(); b['unifiedContext']['ownerContextAvailable']=True
    with pytest.raises(ValueError): history.make_record(b,{})


def test_worker_restart_restores_previous_inputs_and_history_read_is_readonly(tmp_path,monkeypatch):
    path=tmp_path/'history.sqlite'; monkeypatch.setattr(scanner,'_market_brief_history_path',lambda:str(path))
    original=brief(); original['calculationSnapshots']={'5':{'epsInput':3000}}
    scanner._market_brief_history_save(original)
    assert original['analysisHistory']['status']=='LOCAL_DURABLE'
    state={};monkeypatch.setattr(scanner,'_MARKET_BRIEF',state)
    scanner._market_brief_history_restore()
    assert state['lastSuccessful']['unifiedContext']==original['unifiedContext']
    assert state['lastSuccessful']['calculationSnapshots']==original['calculationSnapshots']
    def forbidden(*args,**kwargs):raise AssertionError('public request must not write or call AI')
    monkeypatch.setattr(history,'initialize',forbidden);monkeypatch.setattr(history,'append',forbidden)
    monkeypatch.setattr(scanner,'_openai_prose',forbidden)
    with scanner.app.test_request_context('/api/argus/market-brief?history=1'):
        result=scanner.api_argus_market_brief().get_json()
    assert result['rows'][0]['recordId']==original['analysisHistory']['recordId']
    assert result['remoteRecoveryVerified'] is False


def test_missing_history_does_not_destroy_current_view_and_reports_save_failure(tmp_path,monkeypatch):
    monkeypatch.setattr(scanner,'_market_brief_history_path',lambda:str(tmp_path/'absent'/'history.sqlite'))
    b=brief(); scanner._market_brief_history_save(b)
    assert b['unifiedStatus']=='GENERATED' and b['analysisHistory']['status']=='SAVE_FAILED'


def test_later_result_is_appended_and_wrong_session_or_preissue_data_cannot_score(tmp_path):
    b=brief('2026-09-13T00:00:00Z')
    calculation={'comparison':{'schemaVersion':'jp-market-comparison-v1','anchorDate':'2026-09-11',
        'actualAnchorPrice':100,'unit':'ANCHOR_100','forecast':{'horizonSessions':1,
        'line':[{'offsetSessions':1,'value':102}],'flatThresholdPct':1,'validationStatus':'UNVALIDATED'}}}
    record=history.make_record(b,{'1':calculation})
    path=tmp_path/'history.sqlite';history.initialize(path);history.append(path,record)
    assert history.outcome_candidates(record,[{'date':'2026-09-14','close':98}],received_at='2026-09-14T06:00:00Z')==[]
    assert history.outcome_candidates(record,[{'date':'2026-09-15','close':98}],received_at='2026-09-15T07:00:00Z')==[]
    result=history.outcome_candidates(record,[{'date':'2026-09-14','close':98}],received_at='2026-09-14T07:00:00Z')
    assert result[0]['actualClass']=='down' and result[0]['forecastValue']==102
    assert result[0]['comparisonUnit']=='ANCHOR_100' and result[0]['actualComparisonValue']==98
    assert history.append_outcomes(path,result)==1
    assert history.append_outcomes(path,history.outcome_candidates(record,[{'date':'2026-09-14','close':98}],received_at='2026-09-15T07:00:00Z'))==0
    corrected=history.outcome_candidates(record,[{'date':'2026-09-14','close':97}],received_at='2026-09-16T07:00:00Z')
    assert history.append_outcomes(path,corrected)==1
    assert len(history.read_outcomes(path,record['recordId']))==2
    assert history.read_record(path,record['recordId'])==record
    after_close=history.make_record(brief('2026-09-14T08:00:00Z'),{'1':calculation})
    assert history.outcome_candidates(after_close,[{'date':'2026-09-14','close':98}],received_at='2026-09-15T07:00:00Z')==[]
