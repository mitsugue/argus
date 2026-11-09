"""Changing editions retain every original fact within the stored byte bound."""
import base64
import copy
import hashlib
import json
import uuid
import zlib
import pytest
import argus_owner_dialogue as d
import argus_owner_dialogue_backup as backup
import argus_owner_dialogue_store as store
from test_argus_owner_dialogue import AT,answer,market_brief
from test_argus_owner_dialogue_backup import Remote,keys


def edition(revision):
    b=market_brief();public=b['unifiedContext']
    public['facts']=[d.fact('確認した市場の根拠です。'*14+f' 観測{i}・改訂{revision}。',
        'market_context',kind='UNKNOWN') for i in range(64)]
    public['contextId']=d.digest({k:v for k,v in public.items() if k!='contextId'})
    return b


def context(brief,previous=None):
    c=d.build_context(brief=brief,symbol='9999',market='JP',horizon=5,
        question='市場と登録銘柄の説明',received_at=AT,watchlist_only=True,
        owner={'symbol':'9999','market':'JP','state':'WATCHING'},previous=previous)
    c['intent']='SUBJECT_OVERVIEW';c['contextId']=d.digest({k:v for k,v in c.items() if k!='contextId'})
    return c


def changed_context():
    old=context(edition(0));c=context(edition(1),old)
    assert c['previousFactEncoding']=='BOUNDED_DEFLATE_PREVIOUS_FACTS_V1'
    return old,c


def original_prior(c):
    return [r for r in c['facts'] if r.get('source')!='owner_report' and r.get('evidenceKind')!='OWNER_REPORTED']


def metadata_edition(revision):
    b=market_brief();rows=[]
    for i in range(64):
        h=lambda label:hashlib.sha256((label+str(i)).encode()).hexdigest()
        row=d.fact('市場の比較根拠です。'+h('text')+f' 改訂{revision}。','market_context',kind='UNKNOWN')
        row['provenance']={'sourceResponseSha256':h('response'),'sourceRowSha256':h('row'),
            'url':'https://example.test/'+h('url'),'receivedAt':'2026-09-19T00:00:00Z'}
        row['selected']={str(j):h('item'+str(j)) for j in range(2)};rows.append(row)
    public=b['unifiedContext'];public['facts']=rows
    public['contextId']=d.digest({k:v for k,v in public.items() if k!='contextId'})
    return b


def chunked_context():
    old=context(metadata_edition(0));c=context(metadata_edition(1),old)
    assert c['previousFactEncoding']=='BOUNDED_DICT_CHUNKS_PREVIOUS_FACTS_V1'
    return old,c


def test_dictionary_chunks_keep_complete_provenance_and_reordered_json_keys():
    old,c=chunked_context()
    assert d.previous_facts(c)==original_prior(old)
    assert len(json.dumps(c,ensure_ascii=False).encode())<=65536
    sorted_copy=json.loads(json.dumps(c,sort_keys=True))
    assert d.previous_facts(sorted_copy)==original_prior(old)
    distinct=[r for r in original_prior(old)
        if d.digest(r) not in {d.digest(x) for x in c['facts']}]
    assert d.reasoning_context(sorted_copy)['previousFacts']==distinct


@pytest.mark.parametrize('fault',['dictionary','missing','extra','reorder','expansion'])
def test_bad_dictionary_chunk_boundaries_are_rejected(fault):
    old,c=chunked_context();parts=c['previousFactsPacked']
    if fault=='dictionary':c['facts'][0]['text']+='変更'
    if fault=='missing':parts.pop()
    if fault=='extra':parts.append(parts[-1])
    if fault=='reorder':parts[0],parts[1]=parts[1],parts[0]
    if fault=='expansion':
        encoder=zlib.compressobj(zdict=d._prior_dictionary(c,0))
        parts[0]=base64.b64encode(encoder.compress(b' '*1000000)+encoder.flush()).decode()
    with pytest.raises(ValueError,match='previous_fact_reference'):d.previous_facts(c)


def test_oversized_new_encoded_context_is_rejected_by_archive():
    old,c=chunked_context();c['unexpectedPadding']='x'*65536
    c['contextId']=d.digest({k:v for k,v in c.items() if k!='contextId'})
    raw=store.sealed({'requestId':str(uuid.uuid4()),'inputHash':'a'*64,'bootId':'old','context':c})
    with pytest.raises(ValueError,match='dialogue_backup_context_invalid'):backup._request(raw)


def test_chunked_archive_restores_complete_original_record(tmp_path):
    old,c=chunked_context();identity=str(uuid.uuid4());path=tmp_path/'original';store.initialize(path)
    store.submit(path,identity=identity,input_hash='a'*64,boot_id='old',context=c)
    validated=d.validate_answer(answer(),c);assert validated is not None
    store.complete(path,identity,{'status':'SUCCEEDED','answer':validated,'completedAt':AT})
    remote=Remote();backup.synchronize(path,remote,keys());cold=tmp_path/'cold';backup.synchronize(cold,remote,keys())
    actual=store.read(cold,identity,'new')['context']
    assert actual==c and d.previous_facts(actual)==original_prior(old)
    assert backup.snapshot(cold)[0]==backup.snapshot(path)[0]


def test_changed_editions_preserve_all_previous_facts_and_provider_input():
    old,c=changed_context();before=copy.deepcopy(old);prior=original_prior(old)
    assert d.previous_facts(c)==prior and old==before
    assert len(json.dumps(c,ensure_ascii=False).encode())<=65536
    selected=d.reasoning_context(c)
    distinct=[r for r in prior if d.digest(r) not in {d.digest(x) for x in c['facts']}]
    assert selected['facts']==c['facts'] and selected['previousFacts']==distinct
    assert 'previousFactsPacked' not in selected and 'previousFactsByteLength' not in selected
    selection=d.expanded_retrieval_record(c['retrievalRecord'],c)['selection']
    assert selection['mandatoryCurrent']==[r['evidenceId'] for r in c['facts']]
    assert selection['previousDistinct']==[r['evidenceId'] for r in distinct]
    assert c['retrievalRecord']['omittedEvidenceCount']==0


def test_reentrant_final_context_keeps_previous_prose_and_receipt():
    old,c=changed_context();prior=d.previous_facts(c)
    c['previousView']={'requestId':str(uuid.uuid4()),'contextId':old['contextId'],
        'completedAt':AT,'sections':{k:{'textJa':'前回の説明です。'*12,
            'kind':'UNKNOWN','evidenceIds':[]} for k in answer()}}
    prose=copy.deepcopy(c['previousView']);c['contextId']=d.digest({k:v for k,v in c.items() if k!='contextId'})
    packed=d.bounded_context(c)
    assert packed['previousView']==prose and d.previous_facts(packed)==prior
    assert len(json.dumps(packed,ensure_ascii=False).encode())<=65536


@pytest.mark.parametrize('fault',['digest','length','extra_rows','false_rows','invalid_base64','trailing','truncated','expansion','forbidden'])
def test_corrupt_or_unbounded_previous_payload_is_rejected(fault):
    old,c=changed_context()
    if fault=='digest':c['previousFactsSha256']='0'*64
    if fault=='length':c['previousFactsByteLength']+=1
    if fault=='extra_rows':c['previousFacts']=[old['facts'][0]]
    if fault=='false_rows':c['previousFacts']=False
    if fault=='invalid_base64':c['previousFactsPacked']='!'
    if fault in ('trailing','truncated'):
        raw=base64.b64decode(c['previousFactsPacked'])
        c['previousFactsPacked']=base64.b64encode(raw+b'junk' if fault=='trailing' else raw[:-2]).decode()
    if fault=='expansion':
        c['previousFactsPacked']=base64.b64encode(zlib.compress(b' '*1000000)).decode();c['previousFactsByteLength']=65536
    if fault=='forbidden':c.pop('ownerInputPolicy')
    c['contextId']=d.digest({k:v for k,v in c.items() if k!='contextId'})
    raw=store.sealed({'requestId':str(uuid.uuid4()),'inputHash':'a'*64,'bootId':'old','context':c})
    with pytest.raises(ValueError,match='previous_fact_reference'):backup._request(raw)


def test_prior_index_corruption_and_retrieval_hash_are_rejected():
    old,c=changed_context();record=c['retrievalRecord']
    assert record['selectionEncoding']=='CURRENT_AND_PREVIOUS_FACT_INDICES_V2'
    record['selection']['previousDistinct'][0]={'prior':99999}
    with pytest.raises(ValueError,match='retrieval_record_integrity'):d.reasoning_context(c)


def test_same_input_digest_is_independent_of_packed_previous_format():
    old,c=changed_context();raw=copy.deepcopy(c)
    raw['previousFacts']=d.previous_facts(c)
    for key in ('previousFactEncoding','previousFactsSha256','previousFactsPacked','previousFactsByteLength'):
        raw.pop(key,None)
    raw['retrievalRecord']=d.retrieval_record(raw)
    raw['contextId']=d.digest({k:v for k,v in raw.items() if k!='contextId'})
    policy={'model':'test','ruleVersion':'fixed'}
    assert d.overview_input_digest(c,policy)==d.overview_input_digest(raw,policy)


def test_provider_receives_complete_changes_not_a_compressed_placeholder():
    old,c=changed_context();prompt=d.prompt(c)
    assert c['previousFactsPacked'] not in prompt
    assert 'previousFactsPacked' not in prompt and 'previousFactsByteLength' not in prompt
    for row in c['facts']+d.previous_facts(c):
        assert row['text'] in prompt
    assert '改訂0' in prompt and '改訂1' in prompt


def test_new_packed_archive_restores_exactly_and_keeps_original_prior(tmp_path):
    old,c=changed_context();before=copy.deepcopy(c);path=tmp_path/'original';identity=str(uuid.uuid4())
    store.initialize(path);store.submit(path,identity=identity,input_hash='a'*64,boot_id='old',context=c)
    validated=d.validate_answer(answer(),c);assert validated is not None
    store.complete(path,identity,{'status':'SUCCEEDED','answer':validated,'completedAt':AT})
    remote=Remote();backup.synchronize(path,remote,keys());cold=tmp_path/'cold';backup.synchronize(cold,remote,keys())
    restored=store.read(cold,identity,'new')['context']
    assert restored==before and d.previous_facts(restored)==original_prior(old)
    assert backup.snapshot(cold)[0]==backup.snapshot(path)[0]


def test_current_facts_alone_over_the_original_bound_remain_rejected():
    b=edition(0);public=b['unifiedContext'];public['facts']=[d.fact('独立した大きな観測です。'*75+str(i),
        'market_context',kind='UNKNOWN') for i in range(64)]
    public['contextId']=d.digest({k:v for k,v in public.items() if k!='contextId'})
    with pytest.raises(ValueError,match='private_context_size_bound'):context(b)
