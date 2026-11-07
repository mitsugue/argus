"""Correction hints retain strict citations, original text and the two-call cap."""
import copy
import json

import pytest

from argus_presentation_intent import caption_reference_guidance, validate_plan
from test_argus_presentation_repair import _evidence_case


def test_outside_element_and_unknown_references_get_only_inventory_owned_hints():
    context, catalog, plan = _evidence_case()
    source = next(r for r in catalog['elements'] if r['id'].startswith('evidence-'))
    item = next(r for r in plan['elements'] if r['id'] == source['id'])
    wrong = next(r['evidenceId'] for r in context['facts'] if r['evidenceId'] not in source['evidenceIds'])
    item['caption'].update(textJa='private-model-text-must-not-be-reflected',
                           evidenceIds=[wrong, 'unknown-model-id', {'unexpected':'private-value'}])
    before = copy.deepcopy((plan, catalog, context))
    hints = caption_reference_guidance(plan, catalog, context)
    assert hints == [{'id': source['id'], 'invalidReferenceCount': 3,
                      'allowedEvidenceIds': source['evidenceIds']}]
    assert 'private-' not in json.dumps(hints) and 'unknown-model-id' not in json.dumps(hints)
    assert (plan, catalog, context) == before


@pytest.mark.parametrize('bad', [None, 'not-a-plan', {'elements': None},
                               {'elements': [{'id': {'unexpected': 'value'}}]}])
def test_malformed_shapes_do_not_create_hints_or_reflect_free_values(bad):
    context, catalog, _ = _evidence_case()
    assert caption_reference_guidance(bad, catalog, context) == []


def test_known_citations_still_cannot_authorize_unverified_fact_or_invented_number():
    context, catalog, plan = _evidence_case()
    item = next(r for r in plan['elements'] if r['id'].startswith('evidence-'))
    item['caption']['kind'] = 'FACT'
    assert caption_reference_guidance(plan, catalog, context) == []
    with pytest.raises(ValueError, match='presentation_caption_unverified_fact'):
        validate_plan(plan, catalog, context)
    item['caption'].update(kind='UNKNOWN', textJa='価格は999999です。')
    assert caption_reference_guidance(plan, catalog, context) == []
    with pytest.raises(ValueError, match='presentation_caption_unsupported_claim'):
        validate_plan(plan, catalog, context)


def test_guidance_has_closed_element_and_reference_bounds():
    facts = [{'evidenceId': 'fact-'+str(i)} for i in range(24)]
    refs = [row['evidenceId'] for row in facts]
    catalog = {'elements': [{'id': 'evidence-market-'+str(i), 'evidenceIds': refs}
                            for i in range(12)]}
    plan = {'elements': [{'id': row['id'], 'caption': {'evidenceIds': ['unknown']*24}}
                         for row in catalog['elements']]}
    hints = caption_reference_guidance(plan, catalog, {'facts': facts})
    assert len(hints) == 6 and all(len(row['allowedEvidenceIds']) == 24 for row in hints)
    assert all(set(row) == {'id','invalidReferenceCount','allowedEvidenceIds'} for row in hints)


@pytest.mark.parametrize('second_invalid', [False, True])
def test_real_correction_uses_aliased_allowed_ids_and_keeps_bounded_calls(monkeypatch, second_invalid):
    import scanner
    import argus_market_brief as mb
    from test_argus_unified_brief import brief, model_response
    value = brief()
    value['facts'].append({'text': '報道では市場反応が分かれました。', 'source': 'trusted_mail',
                           'priority': 'P1', 'verification': 'UNCONFIRMED'})
    value['unifiedContext'] = mb.unified_context(value)
    original = copy.deepcopy(value['unifiedContext'])
    calls = []

    def provider(user, **kwargs):
        context, raw = model_response(user)
        item = next(r for r in raw['presentation']['elements'] if r['id'].startswith('evidence-market-'))
        wrong = next(f['evidenceId'] for f in context['facts'] if f['source'] == 'trusted_mail')
        if not calls or second_invalid:
            item['caption']['evidenceIds'] = [wrong]
        if calls:
            hints = json.loads(user.split('\n引用の修正対象: ', 1)[1].split('。各id', 1)[0])
            hint = next(row for row in hints if row['id'] == item['id'])
            assert all(ref.startswith('ref-') for ref in hint['allowedEvidenceIds'])
            assert wrong not in hint['allowedEvidenceIds']
            assert '無関係な根拠へ付け替えてはいけません' in user
            if not second_invalid:
                item['caption']['evidenceIds'] = hint['allowedEvidenceIds'][:1]
        else:
            assert '\n引用の修正対象: ' not in user
        calls.append(user)
        kwargs['diagnostic'].update(outcome='ok', returnedModel=scanner._OPENAI_MODEL,
                                    inputTokens=100, outputTokens=10, estUsd=.001)
        return raw

    monkeypatch.setattr(scanner, '_openai_prose', provider)
    result = scanner._market_brief_ai_polish(value)
    assert len(calls) == 2
    assert result['unifiedContext'] == original
    assert result['unifiedStatus'] == 'GENERATED'
    assert result['presentationStatus'] == ('INVALID_RESPONSE' if second_invalid else 'GENERATED')
    first = result['aiDiagnostics']['attempts'][0]['validation']
    assert first['detail'] == 'presentation_caption_evidence'
    assert first['presentationCitationErrors'] == [
        {'id': 'evidence-market-0', 'invalidReferenceCount': 1, 'allowedReferenceCount': 1}]
    assert 'allowedEvidenceIds' not in json.dumps(result['aiDiagnostics'])
    assert result['aiDiagnostics']['callReduction']['correctionCalls'] == 1
