"""2026-10-24 (cost): rule-fixable layout faults are repaired before a second
model call; the repaired plan still passes the unchanged full validation."""
from copy import deepcopy

import pytest

from argus_market_brief import unified_context
from argus_presentation_intent import brief_inventory, inventory, validate_plan
from argus_presentation_repair import REPAIRABLE, repair


def example():
    catalog = inventory(context_id='a' * 64, surface='today', subject='N225', horizon=5,
        elements=[{'id': 'view', 'kind': 'narrative', 'payloadId': 'b' * 64,
                   'evidenceIds': ['fact-one'], 'mandatory': True, 'urgent': False},
                  {'id': 'comparison', 'kind': 'chart', 'payloadId': 'c' * 64,
                   'evidenceIds': ['fact-one'], 'mandatory': False, 'urgent': False}])
    plan = {'inventoryId': catalog['inventoryId'], 'intentJa': '変化とその成立条件を順に伝える',
            'elements': [{'id': 'view', 'purposeJa': '要点', 'placement': 'lead', 'emphasis': 'primary'},
                         {'id': 'comparison', 'purposeJa': '比較', 'placement': 'support', 'emphasis': 'normal'}]}
    return catalog, plan


def test_a_mandatory_element_in_detail_is_raised_and_then_validates():
    catalog, plan = example()
    plan['elements'] = [plan['elements'][1], plan['elements'][0]]
    plan['elements'][0]['emphasis'] = 'primary'
    plan['elements'][1].update(placement='detail', emphasis='normal')
    with pytest.raises(ValueError, match='presentation_required_demotion'):
        validate_plan(plan, catalog)
    fixed, changes = repair(plan, catalog, None)
    assert changes == [{'id': 'view', 'rule': 'presentation_required_demotion'}]
    assert validate_plan(fixed, catalog)['elements'][1]['placement'] == 'lead'
    assert plan['elements'][1]['placement'] == 'detail'          # the original is not mutated


def test_an_urgent_element_is_placed_in_lead():
    catalog, plan = example()
    elements = deepcopy(catalog['elements']); elements[1]['urgent'] = True
    catalog = inventory(context_id='a' * 64, surface='today', subject='N225', horizon=5, elements=elements)
    plan['inventoryId'] = catalog['inventoryId']
    plan['elements'].reverse()
    plan['elements'][0]['emphasis'] = 'quiet'
    with pytest.raises(ValueError, match='presentation_urgent_demotion'):
        validate_plan(plan, catalog)
    fixed, changes = repair(plan, catalog, None)
    assert {'id': 'comparison', 'rule': 'presentation_urgent_demotion'} in changes
    row = validate_plan(fixed, catalog)['elements'][0]
    assert row['placement'] == 'lead' and row['emphasis'] == 'normal'


def _evidence_case():
    context = unified_context({'generatedAt': '2026-09-14T00:00:00Z', 'facts': [
        {'text': '報道後の市場反応は確認待ちです。', 'source': source, 'priority': 'P0', 'verification': 'UNCONFIRMED'}
        for source in ('trusted_mail', 'calendar', 'market_data')]})
    current = brief_inventory(context, {'5': {'comparison': {}}})
    catalog = inventory(context_id=context['contextId'], surface='today', subject='N225',
                        horizon=5, elements=current['elements'])
    rows = []
    urgent = [r for r in catalog['elements'] if r['urgent']]
    ordered = urgent + [r for r in catalog['elements'] if not r['urgent']]
    for source in ordered:
        row = {'id': source['id'], 'purposeJa': '変化と次の確認を伝える',
               'placement': 'lead' if source['urgent'] or source['id'] == 'view' else 'support',
               'emphasis': 'primary' if source['id'] == 'view' else 'normal'}
        if source['id'].startswith('evidence-'):
            row['caption'] = {'textJa': '報道後の市場反応は確認待ちです。',
                              'evidenceIds': source['evidenceIds'][:1], 'kind': 'UNKNOWN'}
        rows.append(row)
    plan = {'inventoryId': catalog['inventoryId'], 'intentJa': '変化と次の確認', 'elements': rows}
    return context, catalog, plan


def test_a_caption_citing_an_unknown_evidence_id_keeps_only_its_own_ids():
    context, catalog, plan = _evidence_case()
    validate_plan(plan, catalog, context)                       # the base case is valid
    caption_row = next(r for r in plan['elements'] if r['id'].startswith('evidence-'))
    caption_row['caption']['evidenceIds'].append('fact-not-on-this-element')
    with pytest.raises(ValueError, match='presentation_caption_evidence'):
        validate_plan(plan, catalog, context)
    fixed, changes = repair(plan, catalog, context)
    assert {'id': caption_row['id'], 'rule': 'presentation_caption_evidence'} in changes
    validate_plan(fixed, catalog, context)


def test_a_caption_with_no_valid_id_left_is_not_repaired():
    context, catalog, plan = _evidence_case()
    caption_row = next(r for r in plan['elements'] if r['id'].startswith('evidence-'))
    caption_row['caption']['evidenceIds'] = ['fact-not-on-this-element']
    assert repair(plan, catalog, context) == (None, [])


def test_only_layout_faults_are_repairable():
    assert REPAIRABLE == {'presentation_caption_evidence', 'presentation_required_demotion',
                          'presentation_urgent_demotion'}
    catalog, plan = example()
    assert repair(plan, catalog, None) == (None, [])            # nothing to fix
    assert repair('not a plan', catalog, None) == (None, [])


def test_a_rule_fixable_layout_fault_costs_no_second_model_call(monkeypatch):
    import copy
    import scanner
    import argus_market_brief as mb
    from test_argus_unified_brief import model_response
    calls = []

    def provider(user, **kwargs):
        context, raw = model_response(user)
        ref = next(f['evidenceId'] for f in context['facts'] if f['source'] == 'calendar')
        raw['view']['textJa'] = '物価の方向を確認します。'
        raw['reasons']['textJa'] = '発表後の市場反応を確認します。'
        raw['invalidation']['textJa'] = '物価の方向が変われば見直します。'
        raw['next']['textJa'] = '{event:' + ref + '}で物価の方向を確認します。'
        raw['next']['evidenceIds'] = [ref]
        view = next(row for row in raw['presentation']['elements'] if row['id'] == 'view')
        view['placement'] = 'detail'                       # a mandatory element buried
        calls.append(copy.deepcopy(raw))
        kwargs['diagnostic'].update(outcome='ok', returnedModel=scanner._OPENAI_MODEL,
            completedAt='2026-10-10T00:00:00Z', inputTokens=100, outputTokens=10, estUsd=.001)
        return raw

    monkeypatch.setattr(scanner, '_openai_prose', provider)
    brief = mb.compose_brief(now_iso='2026-10-10T00:00:00Z', next_events=[{
        'eventId': 'cpi-fixture', 'title': '米CPI', 'eventTimeUtc': '2026-10-14T12:30:00Z'}])
    brief['unifiedContext'] = mb.unified_context(brief)
    result = scanner._market_brief_ai_polish(brief)
    assert len(calls) == 1
    assert result['presentationStatus'] == 'GENERATED'
    assert result['aiDiagnostics']['callReduction']['correctionCalls'] == 0
    view = next(row for row in result['presentationPlan']['elements'] if row['id'] == 'view')
    assert view['placement'] != 'detail'
