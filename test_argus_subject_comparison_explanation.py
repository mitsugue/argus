"""Scoped comparison guidance uses existing facts, never new market requests."""
from copy import deepcopy
import json

import pytest

import argus_owner_dialogue as dialogue
from test_argus_owner_cached_inputs import inputs, calc
from test_argus_owner_dialogue import answer


def current(*, sector=True):
    brief, history, classification = inputs()
    row = calc(brief, history, classification if sector else {})
    context = dialogue.build_context(brief=brief, symbol='1234', market='JP', horizon=5,
        received_at=history['acquiredAt'], question='この銘柄の現在地は？',
        subject_comparison=row, watchlist_only=True)
    context['intent'] = 'SUBJECT_OVERVIEW'
    context['contextId'] = dialogue.digest({k:v for k,v in context.items() if k!='contextId'})
    return context


def test_generation_prompt_asks_for_dates_populations_and_relative_not_absolute_direction():
    context = current()
    original = deepcopy(context)
    text, restore, _ = dialogue.generation_prompt(context)
    assert '開始日〜終了日' in text and 'reasonsで引用' in text
    assert '個別銘柄・日経225・業種ETFは異なる母集団' in text
    assert '相対的に強いことを絶対的な上昇と取り違えず' in text
    assert '価格差だけから材料や下落の原因を断定せず' in text
    # Real fixture: index -10%, sector +10%, this stock +5%.
    fact = next(f for f in context['facts'] if f.get('source')=='subject_market_comparison')
    assert fact['marketInput']['returnPct'] == pytest.approx(5)
    assert fact['marketInput']['relativeToNikkeiPct'] == pytest.approx(15)
    assert fact['marketInput']['relativeToSectorPct'] == pytest.approx(-5)
    assert fact['marketInput']['startDate'] in text and fact['marketInput']['endDate'] in text
    assert context == original
    assert restore({'reasons': {'evidenceIds': [fact['evidenceId']]}})['reasons']['evidenceIds'] == [fact['evidenceId']]


@pytest.mark.parametrize('fault', ['subject','market','index','intent','missing','unverified',
    'scope','base','cutoff','body_hash','fact_hash'])
def test_guidance_never_borrows_another_subject_period_or_unbound_legacy_input(fault):
    context = current()
    fact = next(f for f in context['facts'] if f.get('source')=='subject_market_comparison')
    value = fact['marketInput']
    if fault=='subject': context['subject']['symbol']='9999'
    elif fault=='market': context['subject']['market']='US'
    elif fault=='index': context['subject']['symbol']='N225'
    elif fault=='intent': context.pop('intent')
    elif fault=='missing': context['facts'].remove(fact)
    elif fault=='unverified': fact['verification']='UNCONFIRMED'
    elif fault=='scope': value.pop('comparisonScope')
    elif fault=='base': value['baseMarketContextId']='a'*64
    elif fault=='cutoff': value['informationCutoff']='2027-01-01T00:00:00Z'
    elif fault=='body_hash': value['returnPct']=9999
    elif fault=='fact_hash': fact['text']='untrusted replacement'
    assert dialogue.subject_comparison_instruction(context)==''


def test_missing_sector_does_not_manufacture_a_sector_or_cause():
    context=current(sector=False)
    fact=next(f for f in context['facts'] if f.get('source')=='subject_market_comparison')
    assert fact['marketInput']['relativeToSectorPct'] is None
    assert fact['marketInput']['sectorEvidenceId'] is None
    assert '業種の欠測は推測で補いません' in dialogue.subject_comparison_instruction(context)


def test_original_saved_contract_and_context_bytes_are_not_modified_by_guidance():
    context=current(); original=deepcopy(context)
    before=json.dumps(context,ensure_ascii=False,sort_keys=True)
    old=dialogue.validate_saved_answer(answer(),context,completed_at=context['receivedAt'])
    assert old is not None
    dialogue.generation_prompt(context)
    assert dialogue.validate_saved_answer(answer(),context,completed_at=context['receivedAt'])==old
    assert context==original and json.dumps(context,ensure_ascii=False,sort_keys=True)==before
