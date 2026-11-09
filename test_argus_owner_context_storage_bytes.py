"""The context wire bound must match the bytes actually stored in SQLite."""
import copy
import json
import uuid

import pytest
import argus_owner_dialogue as dialogue
import argus_owner_dialogue_backup as backup
import argus_owner_dialogue_store as store
from test_argus_owner_prior_context_packing import changed_context


def sized_context(size, *, with_prior=True):
    pair = changed_context();value=pair[1 if with_prior else 0]
    value['storageBoundaryFixture'] = ''
    value['contextId'] = dialogue.digest({k:v for k,v in value.items() if k!='contextId'})
    spare = size - len(store.encoded(value).encode())
    assert spare > 0
    value['storageBoundaryFixture'] = 'a' * spare
    value['contextId'] = dialogue.digest({k:v for k,v in value.items() if k!='contextId'})
    assert len(store.encoded(value).encode()) == size
    return value


def request(value):
    return store.sealed({'requestId':str(uuid.uuid4()),'inputHash':'a'*64,
        'bootId':'fixture','context':value})


def test_exact_stored_bound_keeps_every_value_and_original_identity():
    value = sized_context(65536);before=copy.deepcopy(value)
    assert len(json.dumps(value,ensure_ascii=False).encode()) > 65536
    result = dialogue.bounded_context(value)
    assert result == before and value == before
    assert len(store.encoded(result).encode()) == 65536
    assert dialogue.previous_facts(result) == dialogue.previous_facts(before)


def test_archive_uses_the_same_exact_context_storage_bound():
    value = sized_context(65536)
    assert backup._request(request(value))['context'] == value


def test_one_byte_over_actual_storage_bound_cannot_be_archived_as_is():
    value = sized_context(65537)
    with pytest.raises(ValueError,match='dialogue_backup_context_invalid'):
        backup._request(request(value))
    before=copy.deepcopy(value)
    packed=dialogue.bounded_context(value)
    assert len(store.encoded(packed).encode())<=65536
    assert packed['facts']==before['facts']
    assert dialogue.previous_facts(packed)==dialogue.previous_facts(before)
    assert value==before


def test_current_facts_one_byte_over_the_actual_bound_cannot_be_packed_away():
    value=changed_context()[0]
    row=value['facts'][0]
    spare=65537-len(dialogue.stored_context_bytes(value['facts']))
    assert spare>0
    row['text']+='a'*spare
    value['retrievalRecord']=dialogue.retrieval_record(value)
    value['contextId']=dialogue.digest({k:v for k,v in value.items() if k!='contextId'})
    assert len(dialogue.stored_context_bytes(value['facts']))==65537
    with pytest.raises(ValueError,match='private_context_size_bound'):
        dialogue.bounded_context(value)


def test_storage_encoding_matches_the_existing_store_with_utf8_and_literal_spaces():
    _, value = changed_context()
    value['literalFixture'] = '空白 は保持、, : " 引用と改行\n絵文字📈'
    raw = dialogue.stored_context_bytes(value)
    assert raw == store.encoded(value).encode()
    assert json.loads(raw) == value
    assert '空白 は保持' in raw.decode()


def test_nonfinite_context_is_not_admitted_by_byte_measurement():
    _, value = changed_context();value['nonfiniteFixture']=float('nan')
    with pytest.raises(ValueError):dialogue.bounded_context(value)


def test_ordinary_failure_keeps_only_closed_capacity_counts_without_starting_ai(tmp_path,monkeypatch):
    from test_argus_saved_overview import service
    from scripts.run_intel_collect import private_runtime_record
    value=sized_context(65537,with_prior=False)
    value['question']='private-capacity-sentinel'
    error=dialogue.ContextCapacityError(value,prior=[])
    error.capacity['secret']='private-capacity-sentinel'
    def fail(_):raise error
    path,members,calls,materials,setup,client,controls,body=service(tmp_path)
    monkeypatch.setattr(dialogue,'bounded_context',fail)
    result=controls['refreshSubjectOverviews']()
    assert result['status']=='UNAVAILABLE' and result['lastErrorCode']=='private_context_size_bound'
    closed=controls['overviewStatus']()['lastCapacityFailure']
    assert closed['phase']=='FINAL_OVERVIEW' and closed['measurement']=='STORE_CANONICAL_UTF8'
    assert closed['finalStoredBytes']==len(store.encoded(value).encode())
    assert 'private-capacity-sentinel' not in json.dumps(closed)
    projected=private_runtime_record({'ownerSubjectOverviews':controls['overviewStatus']()}, {})
    assert projected['ownerSubjectOverviews']['lastCapacityFailure']==closed
    assert not calls and not path.exists()


def test_capacity_projection_rejects_free_text_boolean_and_unbounded_values():
    from argus_owner_recovery_diagnostics import capacity_failure
    value={'phase':'private-sentinel','codec':'private-sentinel','observedAt':'private-sentinel',
        'currentFactsBytes':True,'finalStoredBytes':1000001,'priorFactsBytes':-1,
        'previousViewBytes':'private-sentinel','factCount':64,'context':{'text':'private-sentinel'}}
    before=copy.deepcopy(value);out=capacity_failure(value)
    assert value==before and 'private-sentinel' not in json.dumps(out)
    assert out['phase']=='UNKNOWN' and out['codec']=='UNKNOWN' and out['observedAt'] is None
    assert out['currentFactsBytes'] is None and out['finalStoredBytes'] is None
    assert out['priorFactsBytes'] is None and out['previousViewBytes'] is None and out['factCount']==64
