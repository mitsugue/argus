import ast
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace as N
import pytest
import argus_ai_usage_runtime as runtime
import argus_ai_usage_store as store
import scanner


def response():return N(model='test-model',usage=N(input_tokens=100,output_tokens=25,input_tokens_details=N(cached_tokens=20)))


def test_openai_counts_output_once_and_preserves_unknown_metadata():
    value=runtime.usage(response(),'openai')
    assert value=={'inputTokens':100,'outputTokens':25,'cachedInputTokens':20,'returnedModel':'test-model'}
    empty=runtime.usage(N(model='served-model'),'openai')
    assert empty['inputTokens'] is None and empty['outputTokens'] is None
    chat=runtime.usage({'usage':{'prompt_tokens':100,'completion_tokens':30,'completion_tokens_details':{'reasoning_tokens':10}}},'openai')
    assert chat['outputTokens']==30 and chat['cachedInputTokens'] is None


def test_gemini_thoughts_are_included_only_when_known():
    value=runtime.usage(N(model_version='test-model',usage_metadata=N(prompt_token_count=100,candidates_token_count=20,thoughts_token_count=7,cached_content_token_count=10)),'gemini')
    assert value['outputTokens']==27 and value['cachedInputTokens']==10
    assert runtime.usage(N(usage_metadata=N(candidates_token_count=20)),'gemini')['outputTokens'] is None


def test_observer_preserves_success_and_original_error_without_new_calls():
    rows=[];calls=[];expected=response()
    def invoke():calls.append(True);return expected
    result=runtime.observe(invoke,provider='openai',feature='market_brief',requested_model='test-model',record=rows.append,estimate=lambda *args:.001)
    assert result is expected and len(calls)==1 and rows[0]['estimatedCostUsd']==.001
    original=RuntimeError('provider unavailable')
    def failed():raise original
    with pytest.raises(RuntimeError) as err:
        runtime.observe(failed,provider='openai',feature='news_analysis',requested_model='test-model',record=rows.append,estimate=lambda *args:0)
    assert err.value is original and len(rows)==2
    assert rows[1]['errorClass']=='RuntimeError'
    assert rows[1]['outcome']=='provider_error' and rows[1]['estimatedCostUsd'] is None and rows[1]['inputTokens'] is None


def test_recorder_failure_does_not_repeat_request_or_destroy_result():
    errors=[];expected=response()
    def failed(row):raise OSError('disk')
    assert runtime.observe(lambda:expected,provider='openai',feature='market_brief',requested_model='test-model',record=failed,estimate=lambda *args:.01,on_record_error=errors.append) is expected
    assert errors==['OSError']


@pytest.fixture
def bound_store(tmp_path,monkeypatch):
    path=tmp_path/'usage.sqlite3'
    monkeypatch.setattr(scanner,'_ai_usage_path',lambda:str(path))
    monkeypatch.setattr(scanner,'_AI_USAGE_PENDING',{})
    monkeypatch.setattr(scanner,'_AI_USAGE_STATUS',{'status':'NOT_RECORDED'})
    monkeypatch.setattr(scanner,'_AI_PRICING',{'test-model':{'in':1,'out':2}})
    return path


def test_runtime_persistence_restart_readonly_and_no_double_accounting(bound_store,monkeypatch):
    before=deepcopy(scanner._COST_POLICY)
    for feature in ['market_brief','news_analysis','headline_translation']:
        scanner._ai_usage_provider_call('openai',feature,'test-model',response)
    assert scanner._COST_POLICY==before
    snapshot=scanner._ai_usage_snapshot();assert snapshot['summary']['uniqueReceipts']==3
    assert {r['feature'] for r in snapshot['summary']['groups']}=={'market_brief','news_analysis','headline_translation'}
    monkeypatch.setattr(scanner,'_AI_USAGE_PENDING',{})
    monkeypatch.setattr(scanner,'_AI_USAGE_STATUS',{'status':'NOT_RECORDED'})
    def forbidden(*args,**kwargs):raise AssertionError('public/protected read must not write or call provider')
    monkeypatch.setattr(store,'initialize',forbidden);monkeypatch.setattr(store,'append',forbidden)
    assert scanner._ai_usage_snapshot()['summary']['uniqueReceipts']==3
    assert bound_store.stat().st_mode&0o777==0o600


def test_persistence_failure_retains_receipt_and_retries_without_duplicate(bound_store,monkeypatch):
    append=store.append
    def fail(*args,**kwargs):raise OSError('disk')
    monkeypatch.setattr(store,'append',fail)
    scanner._ai_usage_provider_call('openai','market_brief','test-model',response)
    assert scanner._AI_USAGE_STATUS['status']=='SAVE_FAILED' and len(scanner._AI_USAGE_PENDING)==1
    monkeypatch.setattr(store,'append',append)
    scanner._ai_usage_provider_call('openai','market_brief','test-model',response)
    assert not scanner._AI_USAGE_PENDING and store.read_summary(bound_store)['uniqueReceipts']==2


def test_absent_store_is_unknown_and_protected_endpoint_stays_protected(bound_store,monkeypatch):
    assert scanner._ai_usage_snapshot()['readStatus']=='NOT_RECORDED' and not bound_store.exists()
    monkeypatch.setattr(scanner,'_require_admin',lambda:(False,{'error':'unauthorized'},401))
    with scanner.app.test_request_context('/api/argus/ai-cost'):
        _,code=scanner.api_argus_ai_cost();assert code==401


def test_every_sdk_call_in_scanner_is_wrapped_with_feature_receipt():
    tree=ast.parse(Path(scanner.__file__).read_text());parents={child:parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)};count=0
    for node in ast.walk(tree):
        if isinstance(node,ast.Call) and ast.unparse(node.func) in ('client.responses.create','client.chat.completions.create','client.models.generate_content'):
            count+=1;parent=parents[node]
            assert isinstance(parent,ast.Lambda)
            wrapper=parents[parent];assert isinstance(wrapper,ast.Call) and isinstance(wrapper.func,ast.Name) and wrapper.func.id=='_ai_usage_provider_call'
    assert count==18


def test_prose_sdk_fallback_retains_both_attempts_and_feature(bound_store):
    seen=[]
    def responses(**kwargs):
        seen.append(('responses',kwargs));raise RuntimeError('unsupported endpoint')
    def chat(**kwargs):
        seen.append(('chat',kwargs));r=response();r.choices=[N(message=N(content='{}'))];return r
    client=N(responses=N(create=responses),chat=N(completions=N(create=chat)))
    _,text=scanner._openai_prose_call(client,'test-model','test system','test input',purpose='market_brief')
    assert text=='{}' and len(seen)==2
    assert seen[0][1]['input']=='test input' and seen[1][1]['messages'][1]['content']=='test input'
    page=store.read_page(bound_store)
    rows=[r['receipt'] for r in page['rows']]
    assert [r['attempt'] for r in rows]==[1,2]
    assert all(r['feature']=='market_brief' for r in rows)
    assert rows[0]['estimatedCostUsd'] is None and rows[1]['inputTokens']==100


def test_rejected_receipt_does_not_poison_retry_queue(bound_store,monkeypatch):
    def rejected(row):raise ValueError('metadata rejected')
    monkeypatch.setattr(scanner.argus_product_naming,'require_allowed',rejected)
    expected=response()
    assert scanner._ai_usage_provider_call('openai','market_brief','test-model',lambda:expected) is expected
    assert not scanner._AI_USAGE_PENDING and scanner._AI_USAGE_STATUS['status']=='RECEIPT_FAILED'
