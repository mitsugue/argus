"""Closed recovery diagnostics: fixed states only, without saved content or IDs."""
from datetime import datetime

PHASES = ('private_repository', 'remote_head', 'remote_chunks', 'decrypt',
          'remote_records', 'local_records', 'remote_write', 'readback')
CODES = frozenset(('dialogue_backup_answer_invalid', 'dialogue_backup_context_invalid',
    'dialogue_backup_authority_invalid', 'dialogue_backup_request_invalid',
    'dialogue_backup_result_invalid', 'dialogue_backup_unaccepted_answer',
    'dialogue_record_integrity', 'dialogue_backup_immutable_conflict',
    'dialogue_backup_key_unavailable', 'dialogue_backup_keys_required',
    'dialogue_backup_key_invalid', 'dialogue_backup_nonce_invalid',
    'dialogue_backup_private_repo_unverified', 'dialogue_backup_head_invalid',
    'dialogue_backup_head_missing', 'dialogue_backup_chunk_count',
    'dialogue_backup_chunk_invalid', 'dialogue_backup_size_invalid',
    'dialogue_backup_chunk_corrupt', 'dialogue_backup_cipher_corrupt',
    'dialogue_backup_cipher_bound', 'dialogue_backup_header_bound',
    'dialogue_backup_header_invalid', 'dialogue_backup_compression_invalid',
    'dialogue_backup_plain_size_invalid', 'dialogue_backup_archive_bound',
    'dialogue_backup_archive_schema', 'dialogue_backup_row_bound',
    'dialogue_backup_row_identity', 'dialogue_backup_row_kind',
    'dialogue_backup_orphan_completion', 'dialogue_backup_head_readback_changed',
    'dialogue_recovery_durable_path_unavailable', 'dialogue_backup_deadline'))
SECTIONS = ('view', 'reasons', 'changes', 'impact', 'invalidation', 'next')
SECTION_FIELDS = ('textJa', 'evidenceIds', 'kind')
ANSWER_FIELDS = ('schemaVersion', 'contextId', 'sections', 'actionAuthority',
    'ownerContextAvailable', 'historyStatus', 'presentationStatus',
    'presentationCatalog', 'presentationPlan', 'scope', 'subject',
    'horizonSessions', 'isHypotheticalConversation', 'calculatedHypothesis',
    'officialMarketStateMutation', 'officialPositionMutation', 'officialPredictionMutation')
VALIDATION_REASONS = frozenset(('six_section_schema_required', 'section_schema_invalid',
    'section_field_invalid', 'unknown_evidence_reference', 'evidence_reference_required',
    'owner_context_unavailable', 'previous_context_unavailable', 'fact_requires_verified_references',
    'unsupported_authority_or_probability', 'validation_method_scope_mismatch',
    'unsupported_numeric_tokens', 'hypothesis_must_remain_explicit_inference'))


def completion_difference(original, rebuilt, validation=None):
    accepted = isinstance(rebuilt, dict)
    old = original if isinstance(original, dict) else {}
    new = rebuilt if accepted else {}
    old_sections = old.get('sections') if isinstance(old.get('sections'), dict) else {}
    new_sections = new.get('sections') if isinstance(new.get('sections'), dict) else {}
    sections = {}
    for name in SECTIONS:
        a = old_sections.get(name)
        b = new_sections.get(name)
        if accepted and a != b:
            a = a if isinstance(a, dict) else {}
            b = b if isinstance(b, dict) else {}
            sections[name] = [field for field in SECTION_FIELDS if a.get(field) != b.get(field)]
    result = {'rebuiltAccepted': accepted,
        'changedFields': [key for key in ANSWER_FIELDS if accepted and old.get(key) != new.get(key)],
        'otherFieldsChanged': accepted and bool((set(old) ^ set(new)) - set(ANSWER_FIELDS)),
        'sectionFields': sections}
    if isinstance(validation, dict) and validation.get('status') == 'REJECTED':
        result['validation'] = validation_projection(validation)
    return result


def validation_projection(value):
    value = value if isinstance(value, dict) else {}
    reason = value.get('reason');section = value.get('section')
    result = {'reason': reason if isinstance(reason, str) and reason in VALIDATION_REASONS else 'OTHER',
        'section': section if isinstance(section, str) and section in SECTIONS else None}
    fields = value.get('fieldIssues')
    if isinstance(fields, dict):
        result['fieldIssues'] = {}
        for key in ('textCharacters', 'referenceCount'):
            count = fields.get(key)
            result['fieldIssues'][key] = count if type(count) is int and 0 <= count <= 1000000 else None
        for key in ('kindAllowed', 'referencesDistinctStrings'):
            flag = fields.get(key)
            result['fieldIssues'][key] = flag if type(flag) is bool else None
    return result


def phase(name, callback, *args, **kwargs):
    """Re-raise the original exception; observe without changing its behavior."""
    try:
        return callback(*args, **kwargs)
    except Exception as error:
        error._argus_recovery_phase = name
        raise


def failure(error):
    code = error.args[0] if error.args else None
    value = {'phase': getattr(error, '_argus_recovery_phase', None),
             'code': code if isinstance(code, str) and code in CODES else 'OTHER'}
    return project_failure({**value, 'answer': getattr(error, '_argus_recovery_answer', None)})


def project_failure(value):
    value = value if isinstance(value, dict) else {}
    phase_name = value.get('phase')
    code = value.get('code')
    result = {'phase': phase_name if isinstance(phase_name, str) and phase_name in PHASES else 'UNKNOWN',
              'code': code if isinstance(code, str) and code in CODES else 'OTHER'}
    answer = value.get('answer')
    if isinstance(answer, dict):
        fields = answer.get('changedFields')
        section_fields = answer.get('sectionFields')
        result['answer'] = {
            'rebuiltAccepted': answer.get('rebuiltAccepted') is True,
            'changedFields': [key for key in ANSWER_FIELDS if isinstance(fields, list) and key in fields],
            'otherFieldsChanged': answer.get('otherFieldsChanged') is True,
            'sectionFields': {key: [field for field in SECTION_FIELDS if field in section_fields[key]]
                for key in SECTIONS if isinstance(section_fields, dict)
                and isinstance(section_fields.get(key), list)}}
        if isinstance(answer.get('validation'), dict):
            result['answer']['validation'] = validation_projection(answer['validation'])
    return result


def status(value):
    """Projection used by existing private runtime capture, never public output."""
    value = value if isinstance(value, dict) else {}
    result = {'status': value.get('status') if value.get('status') in
        ('NOT_RUN', 'RUNNING', 'NOT_CONFIGURED', 'VERIFIED', 'FAILED') else None}
    for key in ('configured', 'generationReady', 'restoredThisBoot', 'pending'):
        result[key] = value.get(key) if type(value.get(key)) is bool else None
    for key in ('lastAttemptAt', 'lastVerifiedAt'):
        raw = value.get(key)
        try:
            parsed = datetime.fromisoformat(raw.replace('Z', '+00:00')) if isinstance(raw, str) and len(raw) <= 64 else None
            result[key] = raw if parsed is not None and parsed.tzinfo is not None else None
        except ValueError:
            result[key] = None
    for key in ('counts', 'restoredCounts'):
        row = value.get(key)
        result[key] = {name: row[name] for name in ('requests', 'completions', 'historicalMethodScopeCompletions')
            if type(row.get(name)) is int and 0 <= row[name] <= 1000000} if isinstance(row, dict) else None
    result['failure'] = project_failure(value['failure']) if isinstance(value.get('failure'), dict) else None
    return result
