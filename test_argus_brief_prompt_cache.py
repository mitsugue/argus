"""Offline request serialization and accounting; no provider/model evaluation."""
from types import SimpleNamespace as N
import copy
import pytest
import openai
import scanner
from argus_ai_usage_receipt import make_receipt, validate_receipt, summarize
from argus_ai_usage_runtime import cache_write_tokens, observe
from argus_ai_usage_store import initialize, append
from scripts.brief_cost_window import report
from test_argus_brief_call_reduction import scheduled_brief
from test_argus_unified_brief import model_response


def test_real_sdk_serializes_explicit_boundary_without_losing_or_reordering_content(monkeypatch):
    captured = []
    sdk = openai.OpenAI(api_key='offline-synthetic', base_url='https://unused.invalid')
    response = N(output_text='{}')
    def offline_post(path, *, body, **kwargs):
        captured.append(body)
        return response
    monkeypatch.setattr(sdk.responses, '_post', offline_post)
    client = N(responses=sdk.responses)
    monkeypatch.setattr(scanner, '_ai_usage_provider_call', lambda p,f,m,invoke,**kw:invoke())
    prefix = '同じ分析規則。'
    for suffix in ('\n{"source":"first"}', '\n{"source":"corrected"}\n訂正依頼'):
        result = scanner._openai_prose_call(client, 'gpt-5.6-terra', '元の方針', prefix+suffix,
            purpose='market_brief', cache_prefix_chars=len(prefix))
        assert result == (response, '{}')
        body = captured[-1]
        assert body['model'] == 'gpt-5.6-terra' and body['store'] is False
        assert body['instructions'] == scanner.argus_evidence_pack.ANALYSIS_EXPLANATION_POLICY_JA+'\n元の方針'
        assert body['prompt_cache_options'] == {'mode':'explicit'}
        assert len(body['input']) == 1 and body['input'][0]['role'] == 'user'
        blocks = body['input'][0]['content']
        assert ''.join(b['text'] for b in blocks) == prefix+suffix
        assert blocks[0]['prompt_cache_breakpoint'] == {'mode':'explicit'}
        assert 'prompt_cache_breakpoint' not in blocks[1]
        assert not any(k in body for k in ('reasoning','text','previous_response_id','prompt_cache_retention'))
    assert captured[0]['input'][0]['content'][0] == captured[1]['input'][0]['content'][0]
    sdk.close()


@pytest.mark.parametrize('model,purpose,boundary', [
    ('unreviewed-model','market_brief',2), ('gpt-5.6-terra','event_analysis',2),
    ('gpt-5.6-terra','market_brief',True), ('gpt-5.6-terra','market_brief',0),
    ('gpt-5.6-terra','market_brief',5)])
def test_invalid_boundary_fails_before_any_paid_request(monkeypatch,model,purpose,boundary):
    def forbidden(*a,**k): raise AssertionError('provider called')
    monkeypatch.setattr(scanner,'_ai_usage_provider_call',forbidden)
    with pytest.raises(ValueError,match='brief_cache_boundary_invalid'):
        scanner._openai_prose_call(N(),model,'policy','input',purpose=purpose,cache_prefix_chars=boundary)


def test_polish_keeps_current_facts_and_correction_outside_stable_prefix(monkeypatch):
    requests=[]
    def provider(user,**kwargs):
        context, raw=model_response(user)
        requests.append((user,kwargs['cache_prefix_chars'],copy.deepcopy(context)))
        for key in ('view', 'reasons', 'next', 'invalidation'):
            raw[key]['textJa']='物価の方向を確認します。'
        if len(requests)==1:raw['view']['textJa']='根拠にない99%の値。'
        kwargs['diagnostic'].update(outcome='ok',cacheWriteInputTokens=150,estUsd=.01)
        return raw
    monkeypatch.setattr(scanner,'_openai_prose',provider)
    brief=scheduled_brief();brief['unifiedContext']=scanner.argus_market_brief.unified_context(brief)
    result=scanner._market_brief_ai_polish(brief)
    assert len(requests)==2 and result['unifiedStatus']=='GENERATED'
    first,n,context=requests[0];second,m,again=requests[1]
    assert n==m and first[:n]==second[:m]
    assert '表示候補:' in first[n:] and '"facts"' in first[n:]
    assert '表示候補:' not in first[:n] and '"facts"' not in first[:n]
    assert second.startswith(first) and context==again
    assert result['aiDiagnostics']['cacheWriteInputTokens']==150
    assert result['aiDiagnostics']['promptCachePolicy']['dynamicSuffixCached'] is False


def row(**overrides):
    return make_receipt(**dict(dict(call_id='fixture',provider='openai',feature='market_brief',
        started_at='2026-10-10T00:00:00Z',completed_at='2026-10-10T00:00:00Z',
        requested_model='gpt-5.6-terra',returned_model='gpt-5.6-terra',outcome='success',
        input_tokens=1000,output_tokens=10,cached_input_tokens=200,provider_called=True,
        estimated_cost_usd=.002),**overrides))


def test_usage_extension_preserves_legacy_hashes_and_unknown_writes(tmp_path):
    legacy=row();before=copy.deepcopy(legacy)
    assert 'cacheWriteInputTokens' not in legacy and validate_receipt(legacy)==before
    written=row(call_id='written',cache_write_input_tokens=400)
    assert validate_receipt(written)['cacheWriteInputTokens']==400
    assert summarize([legacy,written])['uniqueReceipts']==2
    tampered=dict(written,cacheWriteInputTokens=300)
    with pytest.raises(ValueError,match='integrity'):validate_receipt(tampered)
    path=tmp_path/'existing.sqlite3';initialize(path);append(path,[legacy,written])
    unchanged=path.read_bytes()
    result=report(path,'2026-10-10T00:00:00Z','2026-10-11T00:00:00Z')
    assert result['cacheWrites'][0]['knownCacheWriteInputTokens']==400
    assert result['cacheWrites'][0]['unknownCacheWriteRecords']==1
    assert not result['cacheWriteFeeIncludedInEstimate'] and not result['invoiceSavingsVerified']
    assert path.read_bytes()==unchanged


@pytest.mark.parametrize('written', [True,-1,1001,801])
def test_cache_write_counts_cannot_corrupt_existing_receipts(written):
    with pytest.raises(ValueError):row(cache_write_input_tokens=written)


def test_observer_stores_reported_writes_and_never_infers_missing_zero():
    records=[]
    response=N(model='gpt-5.6-terra',usage=N(input_tokens=1000,output_tokens=10,
        input_tokens_details=N(cached_tokens=200,cache_write_tokens=400)))
    assert cache_write_tokens(response,'openai')==400
    assert cache_write_tokens(N(),'openai') is None
    observe(lambda:response,provider='openai',feature='market_brief',requested_model='gpt-5.6-terra',
        record=records.append,estimate=lambda *args:.002)
    assert len(records)==1 and records[0]['cacheWriteInputTokens']==400


def test_malformed_provider_write_count_preserves_other_usage_without_retry():
    records=[];calls=[]
    response={'model':'gpt-5.6-terra','usage':{'input_tokens':1000,'output_tokens':10,
        'input_tokens_details':{'cached_tokens':200,'cache_write_tokens':1001}}}
    def invoke():
        calls.append(True)
        return response
    observe(invoke,provider='openai',feature='market_brief',requested_model='gpt-5.6-terra',
        record=records.append,estimate=lambda *args:.002)
    assert len(calls)==len(records)==1
    assert records[0]['inputTokens']==1000 and records[0]['cachedInputTokens']==200
    assert 'cacheWriteInputTokens' not in records[0]
