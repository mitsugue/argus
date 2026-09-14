"""Validate GPT editorial choices against an exact, engine-owned display inventory.

This module does not produce a plan, choose model text, compute prices or grant
trading authority. A valid structure still requires semantic and visual review.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import re
from typing import Any, Mapping
from argus_explanation_contract import _digits_of, _FORBIDDEN_BRIEF_PATTERNS

SCHEMA = 'argus-presentation-intent-v1'
MAX_ELEMENTS = 32
PRIORITIES = {'lead', 'support', 'detail'}
EMPHASIS = {'primary', 'normal', 'quiet'}
VOICE = ('あなたはARGUSそのものです。集めた情報を理解し、一人の相手へ、'
    '何が変わり、その人にどう関係し、次に何を確かめるかを一貫して伝えます。'
    '文章、数値、チャート、情報順序と強調に伝える目的を持たせます。'
    '短く自然な日本語で語り、毎文で名乗らず、入力資料を紹介するだけの前置きを避けます。'
    '数値・時点・出典を守り、事実・推論・不明点を分け、既存の売買制約を上書きしません。')


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def inventory(*, context_id: str, surface: str, subject: str, horizon: int,
              elements: list[dict[str, Any]]) -> dict[str, Any]:
    """Freeze displayable evidence and numeric/chart payload identities first."""
    if not re.fullmatch('[a-f0-9]{64}', context_id) or surface not in {'today', 'asset', 'dialogue'}:
        raise ValueError('presentation_scope_invalid')
    if not isinstance(subject, str) or not 1 <= len(subject) <= 80 or type(horizon) is not int or horizon not in {1, 5, 10, 20}:
        raise ValueError('presentation_subject_invalid')
    if not isinstance(elements, list) or not 1 <= len(elements) <= MAX_ELEMENTS:
        raise ValueError('presentation_inventory_bound')
    identifiers = set()
    for row in elements:
        if set(row) != {'id', 'kind', 'payloadId', 'evidenceIds', 'mandatory', 'urgent'}:
            raise ValueError('presentation_element_schema')
        if not isinstance(row['id'], str) or not re.fullmatch('[a-z][a-z0-9_-]{0,63}', row['id']) or row['id'] in identifiers:
            raise ValueError('presentation_element_identity')
        identifiers.add(row['id'])
        if row['kind'] not in {'narrative', 'number', 'chart', 'event', 'status'} or not re.fullmatch('[a-f0-9]{64}', str(row['payloadId'])):
            raise ValueError('presentation_payload_identity')
        if type(row['mandatory']) is not bool or type(row['urgent']) is not bool:
            raise ValueError('presentation_protection_invalid')
        refs = row['evidenceIds']
        if not isinstance(refs, list) or len(refs) > 24 or any(not isinstance(ref, str) or not 1 <= len(ref) <= 120 for ref in refs) or len(set(refs)) != len(refs):
            raise ValueError('presentation_evidence_invalid')
    body = {'contextId': context_id, 'surface': surface, 'subject': subject,
            'horizonSessions': horizon, 'elements': deepcopy(elements)}
    return {**body, 'inventoryId': _digest(body)}


def _validate_caption(value: Any, source: Mapping[str, Any], context: Mapping[str, Any]) -> None:
    if not isinstance(value, Mapping) or set(value) != {'textJa', 'evidenceIds', 'kind'}:
        raise ValueError('presentation_caption_schema')
    text, refs, kind = value['textJa'], value['evidenceIds'], value['kind']
    if (not isinstance(text, str) or not text.strip() or len(text) > 180
            or kind not in {'FACT', 'INFERENCE', 'UNKNOWN'} or not isinstance(refs, list)
            or not 1 <= len(refs) <= 6 or any(not isinstance(r, str) for r in refs)
            or len(refs) != len(set(refs))):
        raise ValueError('presentation_caption_fields')
    facts = {f['evidenceId']: f for f in context.get('facts', [])}
    if any(r not in source['evidenceIds'] or r not in facts for r in refs):
        raise ValueError('presentation_caption_evidence')
    if kind == 'FACT' and any(facts[r].get('verification') != 'VERIFIED' for r in refs):
        raise ValueError('presentation_caption_unverified_fact')
    allowed = set().union(*(_digits_of(facts[r]['text']) for r in refs))
    if (_digits_of(text) - allowed or '確率' in text
            or any(fragment in text for fragment in _FORBIDDEN_BRIEF_PATTERNS)):
        raise ValueError('presentation_caption_unsupported_claim')


def validate_plan(value: Any, catalog: Mapping[str, Any], context=None) -> dict[str, Any]:
    """No omitted inventory entries, replaced prices, or demoted urgent items."""
    expected = {k: v for k, v in catalog.items() if k != 'inventoryId'}
    if catalog.get('inventoryId') != _digest(expected):
        raise ValueError('presentation_inventory_integrity')
    if not isinstance(value, Mapping) or set(value) != {'inventoryId', 'intentJa', 'elements'}:
        raise ValueError('presentation_plan_schema')
    if value['inventoryId'] != catalog['inventoryId']:
        raise ValueError('presentation_inventory_mismatch')
    intent = value['intentJa']
    if not isinstance(intent, str) or not 1 <= len(intent.strip()) <= 160:
        raise ValueError('presentation_intent_invalid')
    rows = value['elements']
    known = {r['id']: r for r in catalog['elements']}
    if not isinstance(rows, list) or len(rows) != len(known):
        raise ValueError('presentation_inventory_incomplete')
    seen = set()
    primary_count = 0
    for row in rows:
        if not isinstance(row, Mapping):
            raise ValueError('presentation_choice_schema')
        identifier = row.get('id')
        if not isinstance(identifier, str) or identifier not in known or identifier in seen:
            raise ValueError('presentation_choice_identity')
        fields = {'id', 'purposeJa', 'placement', 'emphasis'}
        if identifier.startswith('evidence-'):
            fields.add('caption')
        if set(row) != fields:
            raise ValueError('presentation_choice_schema')
        seen.add(identifier)
        if row['placement'] not in PRIORITIES or row['emphasis'] not in EMPHASIS:
            raise ValueError('presentation_visual_vocabulary')
        if not isinstance(row['purposeJa'], str) or not 1 <= len(row['purposeJa'].strip()) <= 160:
            raise ValueError('presentation_purpose_required')
        source = known[identifier]
        if identifier.startswith('evidence-'):
            if not isinstance(context, Mapping) or context.get('contextId') != catalog['contextId']:
                raise ValueError('presentation_caption_context')
            refs = [f for f in context.get('facts', []) if f['evidenceId'] in source['evidenceIds']]
            if source['payloadId'] != _digest(refs):
                raise ValueError('presentation_caption_payload')
            _validate_caption(row['caption'], source, context)
            if row['emphasis'] == 'primary' and len(row['caption']['textJa']) > 80:
                raise ValueError('presentation_primary_caption_too_long')
        if source['urgent'] and (row['placement'] != 'lead' or row['emphasis'] == 'quiet'):
            raise ValueError('presentation_urgent_demotion')
        if source['mandatory'] and row['placement'] == 'detail':
            raise ValueError('presentation_required_demotion')
        primary_count += row['emphasis'] == 'primary'
    if primary_count != 1:
        raise ValueError('presentation_primary_hierarchy')
    seen_nonurgent = False
    for row in rows:
        if known[row['id']]['urgent'] and seen_nonurgent:
            raise ValueError('presentation_urgent_order')
        if not known[row['id']]['urgent']:
            seen_nonurgent = True
    body = {'schemaVersion': SCHEMA, 'contextId': catalog['contextId'],
            'inventoryId': catalog['inventoryId'], 'surface': catalog['surface'],
            'subject': catalog['subject'], 'horizonSessions': catalog['horizonSessions'],
            'intentJa': intent.strip(), 'elements': deepcopy(rows),
            'actionAuthority': False, 'semanticValidation': 'UNVERIFIED'}
    return {**body, 'planId': _digest(body)}


def brief_inventory(context: Mapping[str, Any], calculations: Mapping[str, Any]) -> dict[str, Any]:
    """The first connected surface is the public five-session Today account."""
    current = [row['evidenceId'] for row in context.get('facts', [])]
    elements = []
    for key in ('view', 'reasons', 'changes', 'impact', 'next', 'invalidation'):
        elements.append({'id': key, 'kind': 'narrative',
            'payloadId': _digest({'contextId': context['contextId'], 'section': key}),
            'evidenceIds': current[:24], 'mandatory': key in {'view', 'changes', 'invalidation'},
            'urgent': False})
    comparison = calculations.get('5')
    if isinstance(comparison, Mapping) and isinstance(comparison.get('comparison'), Mapping):
        elements.append({'id': 'nikkei-comparison', 'kind': 'chart',
            'payloadId': _digest(comparison), 'evidenceIds': current[:24],
            'mandatory': True, 'urgent': False})
    # Every current fact belongs to an exact evidence payload. GPT chooses
    # what deserves the surface and what belongs in a disclosure, rather than
    # independent widgets deciding their own emphasis outside this edition.
    groups = {}
    for fact in context.get('facts', []):
        source = fact.get('source')
        group = ('news' if source == 'trusted_mail' else
                 'events' if source == 'calendar' else
                 'supply' if source in {'licensed_market_data', 'derived_margin_change'} else
                 'currency' if source == 'official_weekly_position' else
                 'horizons' if source == 'price_path_calculation' else 'market')
        groups.setdefault(group, []).append(fact)
    for group, rows in groups.items():
        for start in range(0, len(rows), 24):
            chunk = rows[start:start + 24]
            urgent = any(r.get('priority') == 'P0' for r in chunk)
            elements.append({'id': f'evidence-{group}-{start // 24}',
                'kind': 'event' if group in {'news', 'events'} else 'number',
                'payloadId': _digest(chunk), 'evidenceIds': [r['evidenceId'] for r in chunk],
                'mandatory': urgent, 'urgent': urgent})
    return inventory(context_id=context['contextId'], surface='today', subject='N225',
        horizon=5, elements=elements)


def generation_instruction(catalog: Mapping[str, Any]) -> str:
    return ('ARGUSとしてアプリ全体を一つの意図で編集してください。読み手へ何を伝えるかを決め、'
        '6項目の説明と同時にpresentationを返す。見立ては表現の一部です。'
        'presentation={inventoryId:下記ID,intentJa:今回の編集意図160字以内,elements:表示順の配列}。'
        '各要素は{id:候補ID,purposeJa:表示する理由160字以内,placement:lead/support/detail,'
        'emphasis:primary/normal/quiet}。全候補を重複なく含め、primaryは一つ。'
        'mandatory要素は詳細だけにせず、urgent要素は先頭のleadとしquietにしない。'
        '文章は一人の相手へ短く自然に語る。情報不足を作文で埋めず、報道・事実・推論を区別する。'
        '主対象と期間は表示候補のsubject/horizonSessionsに従う。別期間の警戒をこの期間の予測として混ぜない。'
        'evidence-で始まる候補にはcaption:{textJa:180字以内,evidenceIds:同候補から1〜6件,kind:FACT/INFERENCE/UNKNOWN}も必須。'
        'primaryのcaptionは80字以内。大きな文字で長文を読ませない。'
        'captionは資料の紹介ではなく、読み手に伝えたい変化・意味・未確認点を短く語る。'
        '数字が必要な時は参照根拠の値を使い、FACTはVERIFIED根拠のみ。確率や売買指示は書かない。'
        '重要なニュースや目前の予定は冒頭に、詳細な計算は必要時に開く配置を選ぶ。'
        '期間別計算のcaptionでは対象期間を区別し、一つの強気度へ合算しない。'
        '数値・線は候補の計算結果を参照する。JSONに新しい価格・確率・HTML・CSSを追加しない。'
        '\n表示候補:\n'+json.dumps(catalog, ensure_ascii=False, separators=(',', ':')))


def dialogue_inventory(context: Mapping[str, Any]) -> dict[str, Any]:
    refs = [row['evidenceId'] for row in context.get('facts', [])][:24]
    elements = [{'id': key, 'kind': 'narrative',
        'payloadId': _digest({'contextId': context['contextId'], 'section': key}),
        'evidenceIds': refs, 'mandatory': key in {'view', 'impact', 'invalidation'}, 'urgent': False}
        for key in ('view', 'reasons', 'changes', 'impact', 'next', 'invalidation')]
    if context.get('indexComparison') is not None:
        elements.append({'id': 'nikkei-comparison', 'kind': 'chart',
            'payloadId': _digest(context['indexComparison']),
            'evidenceIds': [context['indexComparisonEvidenceId']], 'mandatory': True, 'urgent': False})
    return inventory(context_id=context['contextId'], surface='dialogue',
        subject=context['subject']['symbol'], horizon=context['horizonSessions'],
        elements=elements)
