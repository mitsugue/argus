"""Owner usage view: all committed coverage, unknown amounts, no public IO."""
from copy import deepcopy
from flask import Flask
import pytest
import argus_ai_usage_store as store
from argus_ai_usage_receipt import make_receipt
from argus_ai_usage_view import monthly_view
import argus_owner_dialogue_api as api

AT = '2026-09-13T01:00:00Z'


def receipt(identity, day='2026-09-11', feature='market_brief', **patch):
    return make_receipt(call_id=identity,provider='openai',feature=feature,started_at=day+'T12:00:00Z',
        completed_at=day+'T12:00:01Z',requested_model='requested-test-model',returned_model='returned-test-model',
        outcome='success',provider_called=True,**patch)


def snapshot(path):
    return {'readStatus':'AVAILABLE','state':{'status':'NO_CALL_THIS_PROCESS','pendingReceipts':0,'lastSavedAt':None,'lastErrorClass':None},
            'summary':store.read_summary(path),'remoteRecoveryVerified':False}


def test_month_aggregates_all_committed_records_across_display_windows(tmp_path):
    path=tmp_path/'usage.db';store.initialize(path)
    store.append(path,[receipt(str(i),estimated_cost_usd=.01,input_tokens=100,output_tokens=10,cached_input_tokens=0)
                      for i in range(600)])
    store.append(path,[receipt('next',day='2026-09-12',estimated_cost_usd=.2),receipt('other-month',day='2026-08-31',estimated_cost_usd=99)])
    source=snapshot(path);before=deepcopy(source);result=monthly_view(source,at=AT)
    assert source==before and result['monthUtc']=='2026-09'
    assert len(result['rows'])==1 and result['totals']['records']==601
    assert result['totals']['knownEstimatedCostUsd']==pytest.approx(6.2)
    assert result['totals']['unknownTokenRecords']['inputTokens']==1
    assert result['durableReceiptCount']==602 and result['historyBeforeFirstReceiptReconstructed'] is False
    assert result['providerResponseIsContentAcceptance'] is False and result['addToLegacyTotal'] is False


def test_unknown_cost_tokens_and_absent_database_never_become_known_zero(tmp_path):
    path=tmp_path/'usage.db';store.initialize(path);store.append(path,[receipt('unknown')])
    result=monthly_view(snapshot(path),at=AT)
    assert result['totals']['unknownCostRecords']==1
    assert result['totals']['unknownTokenRecords']['outputTokens']==1
    absent=monthly_view({'readStatus':'NOT_RECORDED','state':{}},at=AT)
    assert absent['totals'] is None and absent['rows']==[]


def test_bounded_pages_keep_whole_month_total_and_reject_changed_snapshot(tmp_path):
    path=tmp_path/'usage.db';store.initialize(path)
    store.append(path,[receipt(str(i),feature='feature-'+str(i),estimated_cost_usd=.1) for i in range(60)])
    source=snapshot(path);first=monthly_view(source,at=AT);second=monthly_view(source,at=AT,offset=50,through_sequence=first['throughSequence'])
    assert len(first['rows'])==50 and len(second['rows'])==10 and first['totals']==second['totals']
    store.append(path,[receipt('new')])
    with pytest.raises(ValueError,match='snapshot_changed'):
        monthly_view(snapshot(path),at=AT,offset=50,through_sequence=first['throughSequence'])


@pytest.mark.parametrize('patch',[{'month':'2026-10'},{'month':'2026-00'},{'month':'invalid'},
    {'offset':True},{'offset':-1},{'through_sequence':True}])
def test_bad_period_cursor_rejected(patch):
    with pytest.raises(ValueError):monthly_view({'readStatus':'NOT_RECORDED'},at=AT,**patch)


def test_usage_action_authorizes_before_read_and_never_initializes_dialogue_or_ai(tmp_path):
    path=tmp_path/'usage.db';store.initialize(path);store.append(path,[receipt('first')]);before=path.read_bytes();reads=[]
    app=Flask(__name__)
    def fail(*a,**kw):pytest.fail('no dialogue storage, recovery, or provider operation allowed')
    def read():reads.append(True);return snapshot(path)
    api.register(app,authorize=lambda token:(True,None,200) if token=='test-owner' else (False,{'error':'unauthorized'},401),
        storage_path=fail,market_brief=fail,generate=fail,now=lambda:AT,usage_snapshot=read,recovery_trigger=fail)
    client=app.test_client()
    assert client.post('/api/argus/owner-dialogue',json={'action':'usage'}).status_code==401 and not reads
    assert client.post('/api/argus/owner-dialogue',json={'action':'usage','ownerToken':'test-owner','runAi':True}).status_code==400 and not reads
    response=client.post('/api/argus/owner-dialogue',json={'action':'usage','ownerToken':'test-owner'})
    assert response.status_code==200 and response.headers['Cache-Control']=='private, no-store'
    assert response.json['totals']['records']==1 and path.read_bytes()==before
    assert client.get('/api/argus/owner-dialogue').status_code==405
    assert 'test-owner' not in response.text
