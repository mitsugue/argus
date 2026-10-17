from copy import deepcopy
import pytest
from argus_presentation_intent import inventory, validate_plan


def example():
    catalog = inventory(context_id='a'*64, surface='today', subject='N225', horizon=5,
        elements=[{'id':'view','kind':'narrative','payloadId':'b'*64,
                   'evidenceIds':['fact-one'],'mandatory':True,'urgent':False},
                  {'id':'comparison','kind':'chart','payloadId':'c'*64,
                   'evidenceIds':['fact-one'],'mandatory':False,'urgent':False}])
    plan = {'inventoryId':catalog['inventoryId'],'intentJa':'変化とその成立条件を順に伝える',
            'elements':[{'id':'view','purposeJa':'現在の判断の要点を伝える','placement':'lead','emphasis':'primary'},
                        {'id':'comparison','purposeJa':'過去と現在の違いを線で比較する','placement':'support','emphasis':'normal'}]}
    return catalog, plan


def test_plan_binds_exact_engine_payload_without_creating_numbers():
    catalog, raw = example()
    result = validate_plan(raw, catalog)
    assert result['contextId'] == catalog['contextId']
    assert result['inventoryId'] == catalog['inventoryId']
    assert result['actionAuthority'] is False
    assert result['semanticValidation'] == 'UNVERIFIED'
    raw['elements'][0]['purposeJa'] = 'changed'
    assert result['elements'][0]['purposeJa'] != 'changed'


@pytest.mark.parametrize('change', ['payload', 'scope', 'horizon', 'inventory'])
def test_stale_or_changed_context_cannot_reuse_intent(change):
    catalog, raw = example()
    if change == 'payload':catalog['elements'][1]['payloadId'] = 'd'*64
    elif change == 'scope':catalog['subject'] = 'SPY'
    elif change == 'horizon':catalog['horizonSessions'] = 20
    else:raw['inventoryId'] = 'd'*64
    with pytest.raises(ValueError):validate_plan(raw, catalog)


@pytest.mark.parametrize('change', ['omit', 'duplicate', 'invent', 'number', 'purpose', 'hierarchy', 'mandatory'])
def test_gpt_cannot_drop_or_invent_elements_and_must_explain_emphasis(change):
    catalog, raw = example()
    if change == 'omit':raw['elements'].pop()
    elif change == 'duplicate':raw['elements'][1]['id'] = 'view'
    elif change == 'invent':raw['elements'][1]['id'] = 'unknown'
    elif change == 'number':raw['elements'][1]['prices'] = [100, 110]
    elif change == 'purpose':raw['elements'][1]['purposeJa'] = ''
    elif change == 'hierarchy':raw['elements'][1]['emphasis'] = 'primary'
    else:raw['elements'][0]['placement'] = 'detail'
    with pytest.raises(ValueError):validate_plan(raw, catalog)


def test_urgent_information_cannot_be_buried_by_editorial_choice():
    catalog, raw = example()
    elements = deepcopy(catalog['elements']);elements[1]['urgent'] = True
    catalog = inventory(context_id='a'*64, surface='today', subject='N225', horizon=5,elements=elements)
    raw['inventoryId'] = catalog['inventoryId']
    with pytest.raises(ValueError):validate_plan(raw, catalog)
    raw['elements'].reverse();raw['elements'][0]['placement'] = 'lead'
    assert validate_plan(raw, catalog)['elements'][0]['id'] == 'comparison'


def test_new_edition_reads_as_one_account_without_rewriting_old_editions():
    from argus_market_brief import unified_context
    from argus_presentation_intent import brief_inventory, validate_current_reading_flow
    context = unified_context({'generatedAt':'2026-09-14T00:00:00Z','facts':[
        {'text':'報道後の市場反応は確認待ちです。','source':source,'priority':'P0','verification':'UNCONFIRMED'}
        for source in ('trusted_mail','calendar','market_data')]})
    current_catalog = brief_inventory(context, {'5':{'comparison':{}}})
    catalog = inventory(context_id=context['contextId'],surface='today',subject='N225',
        horizon=5,elements=current_catalog['elements'])
    choices = {}
    for source in catalog['elements']:
        row = {'id':source['id'],'purposeJa':'変化と次の確認を伝える',
               'placement':'lead' if source['urgent'] or source['id']=='view' else 'support',
               'emphasis':'primary' if source['id']=='view' else 'normal'}
        if source['id'].startswith('evidence-'):
            row['caption']={'textJa':'報道後の市場反応は確認待ちです。',
                'evidenceIds':source['evidenceIds'][:1],'kind':'UNKNOWN'}
        choices[source['id']]=row
    urgent=[row['id'] for row in catalog['elements'] if row['urgent']]
    tail=['changes','nikkei-comparison','reasons','impact','next','invalidation']
    raw={'inventoryId':catalog['inventoryId'],'intentJa':'主文から変化とチャートへつなぐ',
         'elements':[choices[key] for key in urgent+['view']+tail]}
    old=validate_plan(raw,catalog,context)
    summary={'sections':{'view':{'textJa':'私は慎重に見ています。市場の反応を確かめます。'}}}
    with pytest.raises(ValueError,match='main_account_buried'):
        validate_current_reading_flow(old,catalog,summary)
    # Archive validation still accepts the exact old presentation and identity.
    assert validate_plan(raw,catalog,context)==old
    current_raw=deepcopy(raw);current_raw['inventoryId']=current_catalog['inventoryId']
    with pytest.raises(ValueError,match='main_account_buried'):
        validate_plan(current_raw,current_catalog,context)
    catalog=current_catalog;raw['inventoryId']=catalog['inventoryId']
    raw['elements']=[choices[key] for key in ['view']+urgent+tail]
    current=validate_plan(raw,catalog,context)
    assert validate_current_reading_flow(current,catalog,summary)==current
    assert current['planId']!=old['planId']
    raw['elements']=[choices[key] for key in [urgent[0],'view']+urgent[1:]+tail]
    assert validate_current_reading_flow(validate_plan(raw,catalog,context),catalog,summary)
    choices[urgent[0]]['caption']['textJa']='報道の確認を続けます。'*5
    with pytest.raises(ValueError,match='advance_notice_too_long'):
        validate_current_reading_flow(validate_plan(raw,catalog,context),catalog,summary)


def test_urgent_item_after_chart_still_fails_with_main_account_first():
    catalog,raw=example();elements=deepcopy(catalog['elements'])
    elements.append({'id':'notice','kind':'event','payloadId':'d'*64,'evidenceIds':['fact-one'],'mandatory':True,'urgent':True})
    catalog=inventory(context_id='a'*64,surface='today',subject='N225',horizon=5,elements=elements)
    raw['inventoryId']=catalog['inventoryId']
    raw['elements'].append({'id':'notice','purposeJa':'重要な変化を伝える','placement':'lead','emphasis':'normal'})
    with pytest.raises(ValueError,match='urgent_order'):validate_plan(raw,catalog)
