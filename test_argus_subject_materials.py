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
    facts=materials.news_facts([article()],symbol='1234',cutoff=AT)
    def resolve(**kw):calls.append(kw);return deepcopy(facts)
    api.register(app,authorize=lambda token:(True,None,200),storage_path=lambda:str(tmp_path/'private.sqlite3'),
        market_brief=lambda:brief,generate=lambda *a,**kw:None,now=lambda:AT,subject_materials=resolve)
    client=app.test_client();body={'action':'ask','requestId':str(uuid.uuid4()),'symbol':'1234','market':'JP',
        'horizon':5,'question':'この材料の影響は？','baseContextId':brief['unifiedContext']['contextId']}
    first=client.post('/api/argus/owner-dialogue',json=body)
    assert first.status_code==202 and facts[0] in first.json['context']['facts']
    facts.clear()
    same=client.post('/api/argus/owner-dialogue',json=body)
    assert same.json['context']==first.json['context'] and len(calls)==1
    assert client.post('/api/argus/owner-dialogue',json={**body,'material_facts':[]}).status_code==400
