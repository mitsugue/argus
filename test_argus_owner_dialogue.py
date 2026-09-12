from copy import deepcopy
import pytest
import argus_owner_dialogue as dialogue
import argus_market_brief as brief

AT='2026-09-13T00:00:00Z'


def market_brief():
    base={'facts':[{'text':f'日経平均・{h}営業日先の参考値100。','source':'price_path_calculation','priority':'P2','verification':'UNCONFIRMED','provenance':{'eventId':f'n225-price-path-{h}'}} for h in (1,5,10,20)]}
    base['unifiedContext']=brief.unified_context(base);return base


def owner():return {'symbol':'5803','market':'JP','state':'HELD','quantity':100,'averageCost':5000,'purchaseReason':'長期の需要を確認するため','holdingPeriod':'数か月','reportedAt':AT}


def context(**kwargs):
    return dialogue.build_context(brief=market_brief(),symbol='5803',market='JP',horizon=5,question='市場と銘柄の違いは？',received_at=AT,**kwargs)


def answer():return {key:{'textJa':'根拠を確認できていません。','kind':'UNKNOWN','evidenceIds':[]} for key in brief.UNIFIED_SECTIONS}


def test_private_context_never_mutates_public_or_owner_and_keeps_only_target_horizon():
    b=market_brief();o=owner();before=deepcopy((b,o));c=dialogue.build_context(brief=b,symbol='5803',market='JP',horizon=5,question='理由は？',received_at=AT,owner=o)
    assert (b,o)==before and c['scope']=='OWNER_PRIVATE' and c['ownerContextAvailable'] is True
    ids=[(f.get('provenance') or {}).get('eventId') for f in c['facts']]
    assert 'n225-price-path-5' in ids and 'n225-price-path-20' not in ids
    assert c['owner']['costCurrency']=='JPY' and c['officialPositionMutation'] is False
    assert any(f.get('evidenceKind')=='OWNER_REPORTED' and f['verification']=='UNCONFIRMED' for f in c['facts'])


@pytest.mark.parametrize('patch',[{'symbol':'7203'},{'market':'US'},{'state':'NOT_HELD'},{'quantity':True},{'quantity':-1},{'quantity':0},{'reportedAt':'2026-09-14T00:00:00Z'},{'unknown':'instruction'}])
def test_conflicting_or_unknown_owner_fields_rejected(patch):
    with pytest.raises(ValueError):context(owner={**owner(),**patch})


def test_missing_owner_and_wrong_period_history_are_explicit():
    c=context();assert c['ownerContextAvailable'] is False
    prior=deepcopy(c);prior['horizonSessions']=20
    current=context(previous=prior)
    assert current['previousFacts']==[] and not current['changes']['comparisonAvailable']
    valid=dialogue.validate_answer(answer(),current)
    assert '保有情報を含めていません' in valid['sections']['impact']['textJa']


def test_prior_same_scope_requires_integrity_and_preserves_changes():
    old=context(owner=owner());c=context(owner=owner(),previous=old)
    assert c['changes']['comparisonAvailable'] and c['previousFacts']==old['facts']
    old['facts'][0]['text']='changed'
    with pytest.raises(ValueError,match='integrity'):context(previous=old)


def quote():return {'instrumentId':'NIKKEI_225_INDEX','priceBasis':'CASH_INDEX_CLOSE','close':60000,'observedAt':'2026-09-11T06:30:00Z','receivedAt':AT,'sourceResponseSha256':'a'*64}


def test_fx_conversion_is_hypothesis_and_cannot_rewrite_yen_price_or_become_fact():
    q=quote();before=deepcopy(q);c=context(hypothesis={'kind':'FX_TRANSLATION','usdJpy':150,'yenIndexUnchanged':True},index_quote=q)
    assert q==before and c['calculatedHypothesis']['value']==400 and c['calculatedHypothesis']['unit']=='USD'
    assert c['officialPredictionMutation'] is False
    f=next(f for f in c['facts'] if f.get('evidenceKind')=='HYPOTHESIS')
    value=answer();value['view']={'textJa':'仮定の計算は400 USDです。','kind':'INFERENCE','evidenceIds':[f['evidenceId']]}
    assert dialogue.validate_answer(value,c)
    value['view']['textJa']='計算は400 USDです。'
    assert dialogue.validate_answer(value,c) is None
    value['view']['kind']='FACT'
    assert dialogue.validate_answer(value,c) is None


@pytest.mark.parametrize('patch',[{'priceBasis':'ETF_CLOSE'},{'receivedAt':'2026-09-14T00:00:00Z'},{'sourceResponseSha256':None}])
def test_unverified_or_future_scenario_inputs_are_not_calculated(patch):
    c=context(hypothesis={'kind':'FX_TRANSLATION','usdJpy':150,'yenIndexUnchanged':True},index_quote={**quote(),**patch})
    assert c['calculatedHypothesis']['status']=='UNAVAILABLE'


def test_derived_eps_is_not_published_eps_and_no_fixed_multiple_is_assumed():
    eps={'instrumentId':'NIKKEI_225_INDEX','definitionVerified':True,'value':3000,'sourceKind':'DERIVED_PRICE_PER',**{k:quote()[k] for k in ('observedAt','receivedAt','sourceResponseSha256')}}
    c=context(hypothesis={'kind':'EPS_MULTIPLE','per':20},eps_input=eps)
    assert c['calculatedHypothesis']['status']=='UNAVAILABLE'
    eps['sourceKind']='PUBLISHED_INDEX_EPS'
    assert context(hypothesis={'kind':'EPS_MULTIPLE','per':20},eps_input=eps)['calculatedHypothesis']['value']==60000


def test_unreferenced_numbers_and_trade_authority_are_rejected():
    c=context(owner=owner());value=answer();value['view']['textJa']='上昇確率は90%です。'
    assert dialogue.validate_answer(value,c) is None
    value=answer();value['reasons']={'textJa':'利益は999です。','kind':'INFERENCE','evidenceIds':[c['facts'][0]['evidenceId']]}
    assert dialogue.validate_answer(value,c) is None


def test_us_context_does_not_inherit_japan_price_forecasts():
    c=dialogue.build_context(brief=market_brief(),symbol='AAPL',market='US',horizon=5,question='どう見る？',received_at=AT)
    assert not any(f['source']=='price_path_calculation' for f in c['facts'])
    assert any(f['source']=='subject_coverage' for f in c['facts'])
    with pytest.raises(ValueError,match='not_applicable'):
        dialogue.build_context(brief=market_brief(),symbol='AAPL',market='US',horizon=5,question='どう見る？',received_at=AT,hypothesis={'kind':'EPS_MULTIPLE','per':20})


def test_market_context_change_cannot_hide_behind_old_identity():
    base=market_brief();base['unifiedContext']['facts'][0]['text']='different'
    with pytest.raises(ValueError,match='market_context_integrity'):
        dialogue.build_context(brief=base,symbol='5803',market='JP',horizon=5,question='理由は？',received_at=AT)


def test_old_hypothesis_stays_explicit_when_discussing_changes():
    old=context(hypothesis={'kind':'FX_TRANSLATION','usdJpy':150,'yenIndexUnchanged':True},index_quote=quote())
    current=context(previous=old);value=answer()
    f=next(f for f in current['previousFacts'] if f.get('evidenceKind')=='HYPOTHESIS')
    value['changes']={'textJa':'計算は400 USDでした。','kind':'INFERENCE','evidenceIds':[f['evidenceId']]}
    assert dialogue.validate_answer(value,current) is None
    value['changes']['textJa']='仮定の計算は400 USDでした。'
    assert dialogue.validate_answer(value,current)
