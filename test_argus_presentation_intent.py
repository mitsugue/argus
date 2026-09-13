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
