"""Previous prose remains complete when its stored transport is compressed."""
import base64
import copy
import json
import uuid
import zlib

import pytest
import argus_owner_dialogue as d
import argus_owner_dialogue_backup as backup
import argus_owner_dialogue_store as store
from test_argus_owner_prior_context_packing import chunked_context
from test_argus_owner_dialogue import AT,answer


def context(size=66290):
    _,value=chunked_context()
    view={'requestId':str(uuid.uuid4()),'contextId':'a'*64,'completedAt':AT,
        'sections':{name:{'textJa':'前回の根拠と確認点です。','kind':'UNKNOWN','evidenceIds':[]}
            for name in ('view','reasons','changes','impact','invalidation','next')}}
    spare=3082-len(d.stored_context_bytes(view));assert spare>0
    view['sections']['reasons']['textJa']+='根拠'* (spare//6)+'a'*(spare%6)
    assert len(d.stored_context_bytes(view))==3082
    value['previousView']=view;value['capacityFixture']=''
    value['contextId']=d.digest({k:v for k,v in value.items() if k!='contextId'})
    spare=size-len(d.stored_context_bytes(value));assert spare>0
    value['capacityFixture']='a'*spare
    value['contextId']=d.digest({k:v for k,v in value.items() if k!='contextId'})
    assert len(d.stored_context_bytes(value))==size
    return value


def test_previous_view_roundtrips_without_removing_current_or_prior_materials():
    old=context();before=copy.deepcopy(old);prior=d.previous_facts(old)
    new=d.bounded_context(old)
    assert len(d.stored_context_bytes(new))<=65536
    assert new['facts']==before['facts'] and d.previous_facts(new)==prior
    assert d.previous_view(new)==before['previousView'] and old==before
    assert new['previousView'] is None and new['previousViewEncoding'] in d.PREVIOUS_VIEW_CODECS
    assert new['retrievalRecord']==before['retrievalRecord']==d.retrieval_record(new)
    sent=d.reasoning_context(new)
    assert sent['previousView']==before['previousView']
    assert not any(key in sent for key in ('previousViewEncoding','previousViewPacked','previousViewByteLength','previousViewSha256'))


def test_prior_prose_transport_does_not_change_generation_reuse_inputs():
    old=context();new=d.bounded_context(old);policy={'model':'fixture','ruleVersion':'same'}
    assert d.overview_input_digest(old,policy)==d.overview_input_digest(new,policy)
    prompt=d.prompt(new)
    decoded,_=json.JSONDecoder().raw_decode(prompt.split('入力データ:\n',1)[1])
    assert decoded['previousView']==old['previousView']
    sdk_prompt,restore,compact=d.generation_prompt(new)
    assert old['previousView']['sections']['reasons']['textJa'] in sdk_prompt
    assert 'previousViewPacked' not in sdk_prompt


@pytest.mark.parametrize('fault',['hash','size','bool','trailing','bomb','wrong_codec','plain_and_packed','not_watchlist'])
def test_corrupt_or_unbounded_previous_view_is_rejected(fault):
    value=d.bounded_context(context())
    if fault=='hash':value['previousViewSha256']='f'*64
    if fault=='size':value['previousViewByteLength']=65537
    if fault=='bool':value['previousViewByteLength']=True
    if fault=='trailing':value['previousViewPacked']+='\n'
    if fault=='bomb':value['previousViewPacked']=base64.b64encode(zlib.compress(b'x'*1000000)).decode()
    if fault=='wrong_codec':value['previousViewEncoding']='UNKNOWN'
    if fault=='plain_and_packed':value['previousView']={'sections':{}}
    if fault=='not_watchlist':value['ownerInputPolicy']='LEGACY'
    with pytest.raises(ValueError,match='previous_view_reference'):d.previous_view(value)


def test_archive_and_cold_restore_preserve_exact_packed_original_record(tmp_path):
    value=d.bounded_context(context());path=tmp_path/'original';store.initialize(path)
    identity=str(uuid.uuid4());store.submit(path,identity=identity,input_hash='a'*64,boot_id='old',context=value)
    checked=d.validate_answer(answer(),value);assert checked is not None
    store.complete(path,identity,{'status':'SUCCEEDED','answer':checked,'completedAt':AT})
    raw,counts=backup.snapshot(path);cold=tmp_path/'cold';assert backup.restore(cold,raw)==counts
    before=store.read(path,identity,'old');after=store.read(cold,identity,'new')
    assert before['context']==after['context'] and before['result']==after['result']
    assert d.previous_view(after['context'])==d.previous_view(value)


def test_new_view_codec_does_not_bypass_actual_context_archive_limit():
    value=d.bounded_context(context());prior=d.previous_facts(value)
    for name in ('previousFactEncoding','previousFactsPacked','previousFactsByteLength','previousFactsSha256'):
        value.pop(name,None)
    value['previousFacts']=prior
    value['retrievalRecord']=d.retrieval_record(value)
    assert len(d.stored_context_bytes(value))>65536 and value['previousViewEncoding']
    value['contextId']=d.digest({k:v for k,v in value.items() if k!='contextId'})
    raw=store.sealed({'requestId':str(uuid.uuid4()),'inputHash':'a'*64,'bootId':'old','context':value})
    with pytest.raises(ValueError,match='context_invalid'):backup._request(raw)


@pytest.mark.parametrize('codec',['BOUNDED_DEFLATE_PREVIOUS_VIEW_V1',
    'BOUNDED_CURRENT_DICT_PREVIOUS_VIEW_V1','BOUNDED_PRIOR_DICT_PREVIOUS_VIEW_V1'])
def test_each_dictionary_mode_expands_the_complete_original(codec):
    old=context();value=d.bounded_context(old);raw=d.stored_context_bytes(old['previousView'])
    encoder=zlib.compressobj(9) if codec==d.PREVIOUS_VIEW_CODECS[0] else zlib.compressobj(9,zdict=d._previous_view_dictionary(value,codec))
    value['previousViewPacked']=base64.b64encode(encoder.compress(raw)+encoder.flush()).decode()
    value['previousViewEncoding']=codec
    assert d.previous_view(value)==old['previousView']
    if codec==d.PREVIOUS_VIEW_CODECS[1]:
        value['facts'][-1]['text']+='訂正'
        with pytest.raises(ValueError,match='previous_view_reference'):d.previous_view(value)


def test_plain_legacy_previous_view_keeps_original_interpretation():
    value={'previousView':{'sections':{'view':{'textJa':'保存当時の説明です。'}}}}
    before=copy.deepcopy(value)
    assert d.previous_view(value)==before['previousView'] and d.reasoning_context(value)==before
    value['previousViewPacked']='unused'
    with pytest.raises(ValueError,match='previous_view_reference'):d.previous_view(value)
