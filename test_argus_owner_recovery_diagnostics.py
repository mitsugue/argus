import copy
import json
import pytest
import argus_owner_recovery_diagnostics as diagnostics
from scripts.run_intel_collect import private_runtime_record


def test_recovery_projection_never_exports_exception_text_ids_or_saved_values():
    secret = 'private-saved-body-and-key'
    bad = {'status': 'FAILED', 'configured': True, 'generationReady': False,
        'lastAttemptAt': secret, 'lastVerifiedAt': '2026-11-08T07:57:00Z',
        'counts': {'requests': 320, 'completions': True, 'symbol': secret},
        'failure': {'phase': secret, 'code': secret, 'message': secret, 'requestId': secret,
            'answer': {'rebuiltAccepted': True, 'changedFields': ['sections', secret],
                'otherFieldsChanged': True,
                'sectionFields': {'reasons': ['textJa', secret], secret: ['textJa']},
                'textJa': secret}}, 'key': secret}
    original = copy.deepcopy(bad)
    result = private_runtime_record({'ownerDialogueRecovery': bad}, {})
    projected = result['ownerDialogueRecovery']
    assert secret not in json.dumps(result) and bad == original
    assert projected['failure'] == {'phase': 'UNKNOWN', 'code': 'OTHER', 'answer': {
        'rebuiltAccepted': True, 'changedFields': ['sections'], 'otherFieldsChanged': True,
        'sectionFields': {'reasons': ['textJa']}}}
    assert projected['lastAttemptAt'] is None
    assert projected['counts'] == {'requests': 320}
    assert projected['generationReady'] is False


def test_original_exception_identity_type_and_message_are_preserved():
    error = TimeoutError('not-for-output')
    def operation(): raise error
    with pytest.raises(TimeoutError) as caught:
        diagnostics.phase('remote_chunks', operation)
    assert caught.value is error and str(caught.value) == 'not-for-output'
    assert diagnostics.failure(error) == {'phase': 'remote_chunks', 'code': 'OTHER'}
    assert diagnostics.failure(ValueError({'secret': 'not-for-output'}))['code'] == 'OTHER'


def test_existing_completed_runtime_window_carries_only_the_closed_recovery_status():
    first = private_runtime_record({'ownerDialogueRecovery': {
        'status': 'FAILED', 'generationReady': False, 'restoredThisBoot': False,
        'failure': {'phase': 'remote_records', 'code': 'dialogue_backup_answer_invalid'}}}, {})
    first['ownerDialogueRecovery']['injected'] = 'never-output'
    projected = private_runtime_record({'intelCollect': {'completedMemoryWindows': [first]}}, {})
    row = projected['completedOrdinaryWindows'][0]['ownerDialogueRecovery']
    assert row['failure']['phase'] == 'remote_records'
    assert 'never-output' not in json.dumps(projected)
    assert 'ownerDialogueRecovery' not in private_runtime_record({}, {})


def test_existing_collection_read_saves_failure_privately_without_an_extra_request():
    from scripts.run_intel_collect import run
    calls = []; private = []
    def request(**kwargs):
        calls.append(kwargs['method'])
        if kwargs['method'] == 'POST':
            return 200, json.dumps({'status': 'done', 'runId': 'recovery-test'})
        return 200, json.dumps({'ownerDialogueRecovery': {
            'status': 'FAILED', 'generationReady': False, 'restoredThisBoot': False,
            'failure': {'phase': 'remote_records', 'code': 'dialogue_backup_answer_invalid'}}})
    public = run(base='https://example.test', token='test-secret', request_id='recovery-test',
        request=request, private_runtime=private.append)
    assert calls == ['POST', 'GET'] and public['status'] == 'done'
    assert private[0]['ownerDialogueRecovery']['generationReady'] is False
    assert private[0]['ownerDialogueRecovery']['failure']['phase'] == 'remote_records'
    assert 'remote_records' not in json.dumps(public) and 'test-secret' not in json.dumps(private)
