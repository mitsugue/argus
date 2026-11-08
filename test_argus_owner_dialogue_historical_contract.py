"""Pre-binding archive compatibility; active generation stays fail closed."""
import copy
import json
import uuid
import pytest
import argus_owner_dialogue as dialogue
import argus_owner_dialogue_backup as backup
import argus_owner_dialogue_store as store
from argus_owner_dialogue_recovery import RecoveryWorker
from test_argus_owner_dialogue import context, answer, AT
from test_argus_owner_dialogue_backup import Remote, keys, add

CUTOFF = '2026-09-19T19:44:41Z'


def edition(*, received_at=AT, completed_at=AT, bound=False):
    from argus_presentation_intent import dialogue_inventory
    c = context();c['receivedAt'] = received_at
    c['changes'] = {'comparisonAvailable': True}
    if bound:
        c['facts'][0]['validationSubject'] = {'labelJa': '明示した手法'}
        c['facts'][0]['evidenceId'] = 'dialogue-fact-' + dialogue.digest(
            {k:v for k,v in c['facts'][0].items() if k != 'evidenceId'})
    c['previousFacts'] = [copy.deepcopy(c['facts'][0])]
    c['contextId'] = dialogue.digest({k:v for k,v in c.items() if k != 'contextId'})
    supplied = answer()
    supplied['changes'] = {'textJa': '前回との違いを確認します。', 'kind': 'INFERENCE',
        'evidenceIds': [c['facts'][0]['evidenceId']]}
    catalog = dialogue_inventory(c)
    supplied['presentation'] = {'inventoryId': catalog['inventoryId'],
        'intentJa': '結論と根拠を順に読む', 'elements': [
            {'id': row['id'], 'purposeJa': '保存した説明を読む',
             'placement': 'lead' if row['id'] == 'view' else 'support',
             'emphasis': 'primary' if row['id'] == 'view' else 'normal'}
            for row in catalog['elements']]}
    saved = dialogue.validate_answer(supplied, c)
    assert saved is not None and saved['presentationStatus'] == 'GENERATED'
    saved['sections']['changes']['textJa'] = '基準モデルを下回っています。'
    return c, {'status': 'SUCCEEDED', 'answer': saved, 'completedAt': completed_at}


def supplied(result):
    a = result['answer'];p = a['presentationPlan']
    return {**a['sections'], 'presentation': {k:p[k] for k in ('inventoryId', 'intentJa', 'elements')}}


def test_old_saved_contract_recovers_original_prose_digests_and_pending_jobs(tmp_path):
    c, result = edition();before = copy.deepcopy(result)
    diagnostic = {}
    assert dialogue.validate_answer(supplied(result), c, diagnostic=diagnostic) is None
    assert diagnostic['reason'] == 'validation_method_scope_mismatch'
    path = tmp_path/'original';store.initialize(path);identity = str(uuid.uuid4())
    store.submit(path, identity=identity, input_hash='a'*64, boot_id='old', context=c)
    store.complete(path, identity, result);pending = add(path, pending=True)
    remote = Remote();first = backup.synchronize(path, remote, keys())
    cold = tmp_path/'cold';restored = backup.synchronize(cold, remote, keys())
    assert store.read(cold, identity, 'new')['result']['answer'] == before['answer']
    assert store.read(cold, identity, 'new')['result']['recordDigest'] == store.read(path, identity, 'old')['result']['recordDigest']
    assert backup.snapshot(cold)[0] == backup.snapshot(path)[0]
    assert restored['restoredCounts'] == first['counts']
    assert first['counts']['historicalMethodScopeCompletions'] == 1
    assert store.read(cold, pending, 'new')['status'] == 'INTERRUPTED'
    assert dialogue.validate_answer(supplied(result), c) is None
    assert result == before


@pytest.mark.parametrize('received_at,completed_at,bound', [
    (CUTOFF, CUTOFF, False), (AT, CUTOFF, False),
    ('2026-11-08T09:00:00Z', '2026-11-08T09:01:00Z', False),
    (AT, AT, True), ('2026-09-18T00:00:00Z', AT, False)])
def test_new_or_explicitly_bound_or_inconsistent_records_keep_current_method_guard(received_at, completed_at, bound):
    c, result = edition(received_at=received_at, completed_at=completed_at, bound=bound)
    with pytest.raises(ValueError, match='dialogue_backup_answer_invalid'):
        backup._completion(store.sealed(result), c)


@pytest.mark.parametrize('fault', ['number', 'reference', 'authority', 'kind', 'shape', 'digest'])
def test_historical_contract_keeps_number_reference_authority_schema_and_integrity_checks(fault):
    c, result = edition();section = result['answer']['sections']['changes']
    if fault == 'number':section['textJa'] = '基準モデルを987654321回下回っています。'
    if fault == 'reference':section['evidenceIds'] = ['not-a-saved-reference']
    if fault == 'authority':section['textJa'] = '今すぐ買えます。'
    if fault == 'kind':section['kind'] = 'INVALID'
    if fault == 'shape':section['unexpected'] = True
    raw = store.sealed(result)
    if fault == 'digest':
        changed = json.loads(raw);changed['answer']['sections']['changes']['textJa'] = '別の原文です。';raw = json.dumps(changed)
    with pytest.raises(ValueError):backup._completion(raw, c)


def test_actual_worker_opens_only_after_full_legacy_archive_restore_without_resuming_old_ai(tmp_path):
    c, result = edition();source = tmp_path/'source';store.initialize(source)
    identity = str(uuid.uuid4());store.submit(source, identity=identity, input_hash='a'*64, boot_id='old', context=c)
    store.complete(source, identity, result);pending = add(source, pending=True)
    remote = Remote();backup.synchronize(source, remote, keys())
    cold = tmp_path/'cold';worker = RecoveryWorker(storage_path=lambda:cold,
        configuration=lambda:(True, 'configured'), keys=keys, remote=lambda:remote, now=lambda:AT)
    assert worker.status()['generationReady'] is False
    assert worker._lock.acquire(False);worker._run()
    state = worker.status()
    assert state['generationReady'] is True and state['restoredThisBoot'] is True
    assert state['restoredCounts']['historicalMethodScopeCompletions'] == 1
    assert store.read(cold, pending, 'new')['status'] == 'INTERRUPTED'
    assert dialogue.validate_answer(supplied(result), c) is None


def test_active_generation_never_selects_archive_validation_even_with_an_old_clock(monkeypatch):
    import argus_explanation_contract as contract
    c, result = edition()
    def forbidden(*args, **kwargs):raise AssertionError('active generation cannot select archive policy')
    monkeypatch.setattr(contract, 'validate_saved_unified_ai', forbidden)
    assert dialogue.validate_answer(supplied(result), c) is None
    clean = supplied(result);clean['changes']['textJa'] = '前回との違いを確認します。'
    assert dialogue.validate_answer(clean, c) is not None


def test_private_projection_records_only_the_compatible_completion_count():
    from argus_owner_recovery_diagnostics import status
    result = status({'status': 'VERIFIED', 'generationReady': True,
        'counts': {'requests': 2, 'completions': 1, 'historicalMethodScopeCompletions': 1,
                   'original': 'private-sentinel'}})
    assert result['counts'] == {'requests': 2, 'completions': 1, 'historicalMethodScopeCompletions': 1}
    assert 'private-sentinel' not in json.dumps(result)
