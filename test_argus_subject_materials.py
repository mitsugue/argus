from copy import deepcopy
import pytest
import argus_subject_materials as materials
import argus_owner_dialogue as dialogue
from test_argus_owner_dialogue import market_brief, AT


def article(**patch):
    return {'sourceId':'bloomberg_public','linkedAssets':['1234'],
        'canonicalUrl':'https://example.test/article','title':'設備投資の計画を発表',
        'publicSnippet':'会社は工場更新の計画を発表した。','publishedAt':'2026-09-11T08:00:00Z',
        'fetchedAt':'2026-09-11T09:00:00Z',**patch}


def test_news_is_frozen_with_source_times_and_association_limits():
    item=article(fullText='Must not enter the model');before=deepcopy(item)
    facts=materials.news_facts([item],symbol='1234',cutoff=AT)
    assert len(facts)==2 and facts[0]['evidenceKind']=='REPORTED'
    value=facts[0]['materialInput']
    assert value['companyImpactVerified'] is False and value['fullArticleVerified'] is False
    assert 'Must not enter' not in str(facts) and item==before
    assert facts[0]['provenance']['url']==item['canonicalUrl']
    context=dialogue.build_context(brief=market_brief(),symbol='1234',market='JP',horizon=5,
        question='この銘柄への影響は？',received_at=AT,material_facts=facts)
    assert facts[0] in context['facts'] and context['officialPredictionMutation'] is False


@pytest.mark.parametrize('patch',[
    {'sourceId':'unregistered-test-source'}, {'sourceId':'lseg_mrn'}, {'linkedAssets':['9999']},
    {'fetchedAt':None}, {'fetchedAt':'2026-09-14T00:00:00Z'}, {'publishedAt':'2026-09-12T00:00:00Z'},
    {'publishedAt':'2026-08-01T00:00:00Z'}, {'canonicalUrl':'javascript:alert(1)'}, {'sourceId':{}},
])
def test_disallowed_unknown_time_unrelated_and_future_reports_are_not_facts(patch):
    facts=materials.news_facts([article(**patch)],symbol='1234',cutoff=AT)
    assert len(facts)==1 and facts[0]['evidenceKind']=='UNKNOWN'


def test_revision_changes_new_context_but_does_not_overwrite_saved_inputs():
    first=materials.news_facts([article()],symbol='1234',cutoff=AT)
    old=deepcopy(first)
    revised=article(title='設備投資の計画を訂正',fetchedAt='2026-09-12T09:00:00Z',updatedAt='2026-09-12T08:00:00Z')
    second=materials.news_facts([article(),revised],symbol='1234',cutoff=AT)
    assert len(second)==2 and first==old
    assert first[0]['evidenceId']!=second[0]['evidenceId']
    assert second[0]['materialInput']['title']==revised['title']


def test_unknown_publication_is_disclosed_and_article_cap_does_not_claim_completeness():
    rows=[article(canonicalUrl=f'https://example.test/{i}',publishedAt=None) for i in range(6)]
    facts=materials.news_facts(rows,symbol='1234',cutoff=AT)
    assert len(facts)==5 and all('公表: 不明' in f['text'] for f in facts[:-1])
    assert '最大4記事' in facts[-1]['text']


def test_authenticated_api_freezes_server_materials_and_idempotent_reads_do_not_refresh(tmp_path):
    from flask import Flask
    import uuid
    import argus_owner_dialogue_api as api
    app=Flask(__name__);brief=market_brief();calls=[]
    facts=materials.saved_facts([article()],earnings=earnings(),symbol='1234',market='JP',cutoff=AT)
    def resolve(**kw):calls.append(kw);return deepcopy(facts)
    api.register(app,authorize=lambda token:(True,None,200),storage_path=lambda:str(tmp_path/'private.sqlite3'),
        market_brief=lambda:brief,generate=lambda *a,**kw:None,now=lambda:AT,subject_materials=resolve)
    client=app.test_client();body={'action':'overview','symbol':'1234','market':'JP',
        'horizon':5,'baseContextId':brief['unifiedContext']['contextId']}
    first=client.post('/api/argus/owner-dialogue',json=body)
    assert first.status_code==202 and facts[0] in first.json['context']['facts']
    assert facts[0]['source']=='subject_saved_earnings'
    facts.clear()
    same=client.post('/api/argus/owner-dialogue',json=body)
    assert same.json['context']==first.json['context'] and len(calls)==1
    assert client.post('/api/argus/owner-dialogue',json={**body,'material_facts':[]}).status_code==400


def earnings(**patch):
    return {'symbol':'1234','market':'JP','source':'Yahoo Finance','fetchedAt':'2026-09-11T09:00:00Z',
        'company':{'source':'J-Quants 決算短信','currency':'JPY','consolidated':True,
            'disclosedDate':'2026-08-10','periodEnd':'2026-06-30','operatingProfit':-250000000,
            'fiscalYearEnd':'2027-03-31','forecastOperatingProfit':0,
            'receivedAt':'2026-08-10T09:00:00Z','forecastDisclosedDate':'2026-09-10',
            'forecastReceivedAt':'2026-09-10T09:00:00Z'},
        'previous':{'periodEnd':'2026-06-30','epsActual':-12.5,'epsEstimate':-10,'currency':'JPY'},
        'estimate':{'periodEnd':'2026-09-30','eps':15,'epsLow':10,'epsHigh':20,'epsCurrency':'JPY',
            'analysts':4,'eps30DaysAgo':18},**patch}


def test_saved_earnings_freezes_actual_plan_consensus_separate_times_and_negative_zero():
    row=earnings();before=deepcopy(row)
    fact,=materials.earnings_facts(row,symbol='1234',market='JP',cutoff=AT)
    value=fact['materialInput']
    assert row==before and fact['verification']=='UNCONFIRMED'
    assert value['company']['operatingProfit']==-250000000 and value['company']['forecastOperatingProfit']==0
    assert value['company']['receivedAt']!=value['company']['forecastReceivedAt']
    assert value['vendor']['estimate']['eps30DaysAgo']==18 and '4人' in fact['text']
    assert '2026-06-30期末の実績EPS-12.5JPY' in fact['text']
    assert '2026-06-30公表' not in fact['text'] and '上方修正' not in fact['text']
    assert fact['provenance']['sourceRowSha256']==materials._digest(value)
    assert value['projectionOnly'] and not value['priceMoveCauseVerified']


def test_future_plan_is_omitted_without_losing_actual_or_substituting_its_receipt():
    row=earnings(source='J-Quants 決算短信',previous=None,estimate=None)
    row['company']['forecastReceivedAt']='2026-09-14T00:00:00Z'
    fact,=materials.earnings_facts(row,symbol='1234',market='JP',cutoff=AT)
    actual=fact['materialInput']['company']
    assert 'forecastOperatingProfit' not in actual and actual['operatingProfit']==-250000000
    assert fact['provenance']['receivedAt']=='2026-08-10T09:00:00Z'


@pytest.mark.parametrize('patch',[
    {'symbol':'9999'},{'market':'US'},{'source':'unknown','company':None},
    {'company':None,'fetchedAt':'2026-09-14T00:00:00Z'},
    {'company':None,'fetchedAt':'2026-08-01T00:00:00Z'},
])
def test_wrong_subject_or_future_unknown_vendor_is_not_financial_evidence(patch):
    assert materials.earnings_facts(earnings(**patch),symbol='1234',market='JP',cutoff=AT)==[]


@pytest.mark.parametrize('field,value',[
    ('operatingProfit',float('nan')),('operatingProfit',True),('currency','USD'),
    ('consolidated',None),('receivedAt','2026-09-14T00:00:00Z'),
    ('disclosedDate','2026-09-11'),('periodEnd','2026-08-11'),
])
def test_bad_actual_does_not_become_a_company_fact(field,value):
    row=earnings(source='J-Quants 決算短信',previous=None,estimate=None)
    row['company'][field]=value
    assert materials.earnings_facts(row,symbol='1234',market='JP',cutoff=AT)==[]


def test_vendor_missing_currency_or_analysts_does_not_borrow_stock_currency_or_fill_zero():
    row=earnings(company=None,currency='JPY')
    row['previous']['currency']=None;row['estimate']['analysts']=None
    assert materials.earnings_facts(row,symbol='1234',market='JP',cutoff=AT)==[]


def test_us_projection_keeps_declared_eps_currency_and_accounting_period():
    row=earnings(symbol='TEST',market='US',company=None,currency='USD')
    row['previous']['currency']='EUR';row['estimate']['epsCurrency']='EUR'
    fact,=materials.earnings_facts(row,symbol='TEST',market='US',cutoff=AT)
    assert 'EUR' in fact['text'] and 'USD' not in fact['text']
    assert '2026-06-30期末' in fact['text'] and '公表' not in fact['text']


def test_combined_materials_keep_five_fact_bound_without_mutation_or_extra_collection():
    rows=[article(canonicalUrl=f'https://example.test/{i}') for i in range(8)]
    row=earnings();before=deepcopy((rows,row))
    facts=materials.saved_facts(rows,earnings=row,symbol='1234',market='JP',cutoff=AT)
    assert len(facts)==5 and len([f for f in facts if f['source']=='subject_news_metadata'])==3
    assert facts[0]['source']=='subject_saved_earnings' and '最大3記事' in facts[-1]['text']
    assert (rows,row)==before
    context=dialogue.build_context(brief=market_brief(),symbol='1234',market='JP',horizon=5,
        question='この銘柄への影響は？',received_at=AT,material_facts=facts)
    assert len(dialogue.stored_context_bytes(context))<=65536
    assert all(f in context['facts'] for f in facts)
    assert not context['officialPredictionMutation']


def test_runtime_resolver_uses_only_existing_selected_cache_and_freezes_row():
    import ast
    from pathlib import Path
    import types
    tree=ast.parse(Path('scanner.py').read_text())
    node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='_owner_dialogue_subject_materials')
    row=earnings();calls=[];captured=[]
    def saved(items,**kw):captured.append((items,kw));kw['earnings']['company']['operatingProfit']=42;return ['saved']
    scope={'_analyst_targets_load_saved':lambda:calls.append('local_saved_cache'),
        '_ANALYST_TARGETS':{'items':{'JP:1234':{'earnings':row}}},'_INTEL_STORE':[article()],
        'copy':__import__('copy'),'argus_subject_materials':types.SimpleNamespace(saved_facts=saved)}
    exec(compile(ast.Module(body=[node],type_ignores=[]),'selected-cache','exec'),scope)
    assert scope[node.name](symbol='1234',market='JP',cutoff=AT)==['saved']
    assert calls==['local_saved_cache'] and row['company']['operatingProfit']==-250000000
    assert captured[0][1]['cutoff']==AT
    assert scope[node.name](symbol='N225',market='JP',cutoff=AT) is None
    assert len(calls)==1


def test_subject_prose_guidance_asks_for_business_materials_without_missingness_laundry_list():
    context=dialogue.build_context(brief=market_brief(),symbol='1234',market='JP',horizon=5,
        question='この銘柄への影響は？',received_at=AT)
    context['intent']='SUBJECT_OVERVIEW'
    context['contextId']=dialogue.digest({k:v for k,v in context.items() if k!='contextId'})
    text=dialogue.prompt(context)
    for part in ('保存決算・会社予想・市場予想・関連報道','何が変わったか','原因ではありません','一文','繰り返さず'):
        assert part in text
    assert dialogue.subject_material_instruction({**context,'intent':'OTHER'})==''
    assert dialogue.subject_material_instruction({**context,'subject':{'market':'JP','symbol':'N225'}})==''
