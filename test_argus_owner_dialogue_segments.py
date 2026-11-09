"""Same private transport; complete history and bounded atomic recovery."""
import copy
import hashlib
import json
from pathlib import Path
import sqlite3
import uuid
from types import SimpleNamespace

import pytest
from cryptography.exceptions import InvalidTag
import argus_owner_dialogue_backup as backup
import argus_owner_dialogue_segments as segments
import argus_owner_dialogue_store as store
from test_argus_owner_dialogue_backup import Remote,keys,add


def rows_digest(path):
    out={}
    with sqlite3.connect(path) as db:
        for table in ('requests','completions'):
            digest=hashlib.sha256();count=0
            for identity,body in db.execute(f'SELECT request_id,body FROM {table} ORDER BY request_id'):
                digest.update(identity.encode());digest.update(body.encode());count+=1
            out[table]=(count,digest.hexdigest())
    return out


def large(tmp_path,monkeypatch):
    monkeypatch.setattr(backup,'MAX_ARCHIVE_BYTES',30000)
    monkeypatch.setattr(segments,'SEGMENT_BYTES',12000)
    monkeypatch.setattr(segments,'SEGMENT_TARGET',8000)
    path=tmp_path/'original';remote=Remote()
    for _ in range(12):add(path)
    with pytest.raises(ValueError,match='archive_bound'):backup.snapshot(path)
    return path,remote


def test_small_archives_keep_the_existing_format(tmp_path):
    path=tmp_path/'original';remote=Remote();add(path)
    result=backup.synchronize(path,remote,keys())
    assert json.loads(remote.files[backup.PREFIX+'/head.json'])['schemaVersion']==backup.SCHEMA
    assert 'archiveStorage' not in result


def test_segmented_full_restore_keeps_original_rows_and_reuses_unchanged_ciphertext(tmp_path,monkeypatch):
    path,remote=large(tmp_path,monkeypatch);before=rows_digest(path)
    result=backup.synchronize(path,remote,keys())
    assert result['archiveStorage']['parts']>1 and result['archiveStorage']['largestPlainPartBytes']<=12000
    assert result['archiveStorage']['logicalBytes']>backup.MAX_ARCHIVE_BYTES
    assert rows_digest(path)==before
    cold=tmp_path/'cold';restored=backup.synchronize(cold,remote,keys())
    assert restored['restoredCounts']==result['counts'] and rows_digest(cold)==before
    original=copy.deepcopy(remote.files);backup.synchronize(cold,remote,keys(),previous=restored)
    assert remote.files==original
    # Scope is deliberately in the existing authenticated envelope header;
    # private request IDs and actual text must remain inside the ciphertext.
    with sqlite3.connect(path) as db:
        identities=[row[0].encode() for row in db.execute('SELECT request_id FROM requests')]
    assert all(not any(identity in raw for identity in identities) and '質問'.encode() not in raw
        for raw in remote.files.values())


def test_appending_keeps_old_parts_and_full_history(tmp_path,monkeypatch):
    path,remote=large(tmp_path,monkeypatch);state=backup.synchronize(path,remote,keys());old=copy.deepcopy(remote.files)
    head,_=backup._head(remote,keys());add(path);new=backup.synchronize(path,remote,keys(),previous=state)
    after,_=backup._head(remote,keys())
    assert after['segments'][:len(head['segments'])-1]==head['segments'][:-1]
    assert new['counts']['requests']==13
    assert all(remote.files[p]==raw for p,raw in old.items() if '/chunks/' in p)
    cold=tmp_path/'cold';backup.synchronize(cold,remote,keys());assert rows_digest(cold)==rows_digest(path)


def test_migration_keeps_old_remote_history_and_newer_local_records(tmp_path,monkeypatch):
    monkeypatch.setattr(backup,'MAX_ARCHIVE_BYTES',30000)
    monkeypatch.setattr(segments,'SEGMENT_BYTES',12000)
    monkeypatch.setattr(segments,'SEGMENT_TARGET',8000)
    path=tmp_path/'original';remote=Remote();add(path)
    backup.synchronize(path,remote,keys());old=copy.deepcopy(remote.files)
    assert json.loads(old[backup.PREFIX+'/head.json'])['schemaVersion']==backup.SCHEMA
    for _ in range(11):add(path)
    before=rows_digest(path)
    # A new boot must first verify the old head, then merge all local additions.
    state=backup.synchronize(path,remote,keys())
    assert state['counts']=={'requests':12,'completions':12}
    assert state['restoredCounts']=={'requests':1,'completions':1}
    assert all(remote.files[name]==raw for name,raw in old.items() if '/chunks/' in name)
    cold=tmp_path/'cold';backup.synchronize(cold,remote,keys())
    assert rows_digest(cold)==before==rows_digest(path)


@pytest.mark.parametrize('existing',[False,True])
def test_late_corrupt_segment_never_partially_merges(tmp_path,monkeypatch,existing):
    path,remote=large(tmp_path,monkeypatch);backup.synchronize(path,remote,keys());head,_=backup._head(remote,keys())
    name=backup.PREFIX+'/chunks/'+head['segments'][-1]['chunks'][-1]['sha256']+'.bin'
    remote.files[name]=remote.files[name][:-1]+bytes([remote.files[name][-1]^1])
    cold=tmp_path/'cold'
    if existing:add(cold)
    before=rows_digest(cold) if existing else None
    with pytest.raises(ValueError,match='chunk_corrupt'):backup.synchronize(cold,remote,keys())
    assert rows_digest(cold)==before if existing else not cold.exists()


def test_wrong_key_cannot_read_the_encrypted_manifest(tmp_path,monkeypatch):
    path,remote=large(tmp_path,monkeypatch);backup.synchronize(path,remote,keys());cold=tmp_path/'cold'
    with pytest.raises(InvalidTag):backup.synchronize(cold,remote,keys(b'b'*32))
    assert not cold.exists()


def test_key_rotation_rewraps_all_parts_and_never_deletes_originals(tmp_path,monkeypatch):
    path,remote=large(tmp_path,monkeypatch);state=backup.synchronize(path,remote,keys());old=set(remote.files)
    rotated=keys(b'b'*32,'new-key');rotated['previous']=keys()['current']
    backup.synchronize(path,remote,rotated,previous=state)
    assert old<=set(remote.files)
    cold=tmp_path/'cold';backup.synchronize(cold,remote,keys(b'b'*32,'new-key'))
    assert rows_digest(cold)==rows_digest(path)


def test_head_cas_failure_keeps_old_authority_and_local_paid_records(tmp_path,monkeypatch):
    path,remote=large(tmp_path,monkeypatch);state=backup.synchronize(path,remote,keys());head=remote.files[backup.PREFIX+'/head.json'];add(path);before=rows_digest(path)
    put=remote.put
    def conflict(name,raw,**kwargs):
        if name.endswith('/head.json'):raise ValueError('compare_and_swap_conflict')
        return put(name,raw,**kwargs)
    remote.put=conflict
    with pytest.raises(ValueError,match='compare_and_swap'):backup.synchronize(path,remote,keys(),previous=state)
    assert remote.files[backup.PREFIX+'/head.json']==head and rows_digest(path)==before


@pytest.mark.parametrize('fault',['duplicate','counts','size','scope','unknown'])
def test_manifest_guards_remain_strict(tmp_path,monkeypatch,fault):
    path,remote=large(tmp_path,monkeypatch);backup.synchronize(path,remote,keys());head,_=backup._head(remote,keys())
    if fault=='duplicate':head['segments'].append(head['segments'][0])
    if fault=='counts':head['counts']['requests']+=1
    if fault=='size':head['segments'][0]['plainBytes']=12001
    if fault=='scope':head['scope']='PUBLIC_MARKET'
    if fault=='unknown':head['ownerText']='never-output'
    with pytest.raises(ValueError,match='segment_manifest'):segments._sealed_head(head,keys()['current'])


def test_full_logical_hash_is_checked_before_live_merge(tmp_path,monkeypatch):
    path,remote=large(tmp_path,monkeypatch);backup.synchronize(path,remote,keys());head,_=backup._head(remote,keys());head['logicalSha256']='f'*64
    remote.files[backup.PREFIX+'/head.json']=segments._sealed_head(head,keys()['current']);cold=tmp_path/'cold'
    with pytest.raises(ValueError,match='segment_integrity'):backup.synchronize(cold,remote,keys())
    assert not cold.exists()


def test_insufficient_disk_does_not_publish_or_mutate_history(tmp_path,monkeypatch):
    path,remote=large(tmp_path,monkeypatch);before=rows_digest(path)
    monkeypatch.setattr(segments.shutil,'disk_usage',lambda _:SimpleNamespace(free=0))
    with pytest.raises(ValueError,match='segment_storage_headroom'):backup.synchronize(path,remote,keys())
    assert not remote.files and rows_digest(path)==before


def test_network_upload_starts_after_the_consistent_database_read_ends(tmp_path,monkeypatch):
    path,remote=large(tmp_path,monkeypatch);put=remote.put;checked=[]
    def exclusive(name,raw,**kwargs):
        with sqlite3.connect(path,timeout=.01) as db:db.execute('BEGIN EXCLUSIVE');db.rollback()
        checked.append(True);return put(name,raw,**kwargs)
    remote.put=exclusive;backup.synchronize(path,remote,keys());assert checked


def test_original_archive_and_new_part_limits_are_not_raised(tmp_path,monkeypatch):
    path,remote=large(tmp_path,monkeypatch)
    with pytest.raises(ValueError,match='archive_bound'):backup._encrypt(b'x'*30001,keys()['current'])
    with pytest.raises(ValueError,match='archive_bound'):backup.restore(tmp_path/'cold',b'x'*30001)
    assert backup.MAX_ARCHIVE_BYTES==30000 and segments.SEGMENT_BYTES==12000


def test_real_32_mib_boundary_restores_every_original_record_without_raising_part_limits(tmp_path):
    from test_argus_owner_context_storage_bytes import sized_context
    from test_argus_owner_dialogue import answer,AT
    import argus_owner_dialogue as dialogue
    path=tmp_path/'original';store.initialize(path);value=sized_context(65536)
    accepted=dialogue.validate_answer(answer(),value)
    assert accepted is not None
    # Synthetic full-size contexts, not owner records. Cross the real limit.
    for _ in range(515):
        identity=str(uuid.uuid4())
        store.submit(path,identity=identity,input_hash='a'*64,boot_id='fixture',context=value)
        store.complete(path,identity,{'status':'SUCCEEDED','answer':accepted,'completedAt':AT})
    before=rows_digest(path);remote=Remote()
    with pytest.raises(ValueError,match='archive_bound'):backup.snapshot(path)
    result=backup.synchronize(path,remote,keys())
    assert 32*1024*1024<result['archiveStorage']['logicalBytes']<40*1024*1024
    assert result['counts']=={'requests':515,'completions':515}
    assert result['archiveStorage']['largestPlainPartBytes']<=8*1024*1024
    assert backup.MAX_ARCHIVE_BYTES==32*1024*1024
    cold=tmp_path/'cold';recovered=backup.synchronize(cold,remote,keys())
    assert recovered['restoredCounts']==result['counts']
    assert rows_digest(cold)==before==rows_digest(path)
    assert not list(tmp_path.glob('.owner-segment-*'))


def test_expired_existing_deadline_keeps_source_and_remote_authority(tmp_path,monkeypatch):
    path,remote=large(tmp_path,monkeypatch);before=rows_digest(path)
    def expired():raise TimeoutError('dialogue_backup_deadline')
    remote._check_deadline=expired
    with pytest.raises(TimeoutError,match='deadline'):backup.synchronize(path,remote,keys())
    assert not remote.files and rows_digest(path)==before


def test_nonprivate_remote_never_gets_a_head_or_upload(tmp_path,monkeypatch):
    path,remote=large(tmp_path,monkeypatch)
    def deny():raise ValueError('dialogue_backup_private_repo_required')
    remote.assert_private=deny
    with pytest.raises(ValueError,match='private_repo'):backup.synchronize(path,remote,keys())
    assert not remote.files


def test_segment_sizes_are_only_closed_counts_in_existing_private_diagnostic():
    from scripts.run_intel_collect import private_runtime_record
    storage={'mode':'SEGMENTED_ENCRYPTED_V2','parts':9,'logicalBytes':35000000,
        'largestPlainPartBytes':4200000,'plainPartLimit':8388608,'legacyArchiveLimit':33554432}
    output=private_runtime_record({'ownerDialogueRecovery':{'status':'VERIFIED','archiveStorage':storage}}, {})
    assert output['ownerDialogueRecovery']['archiveStorage']==storage
    bad={**storage,'mode':'private-owner-sentinel','parts':True,'logicalBytes':2**40,
        'text':'private-owner-sentinel','plainPartLimit':8388609}
    output=private_runtime_record({'ownerDialogueRecovery':{'status':'FAILED','archiveStorage':bad}}, {})
    safe=output['ownerDialogueRecovery']['archiveStorage']
    assert safe['mode'] is None and safe['parts'] is None and safe['logicalBytes'] is None
    assert safe['plainPartLimit'] is None and 'private-owner-sentinel' not in json.dumps(output)
