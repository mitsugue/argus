"""Authenticated lossless recovery transport; original dialogue records survive."""
import base64
import json
import os
import zlib

import pytest
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

import argus_owner_dialogue_backup as backup
import argus_owner_dialogue_store as store
from test_argus_owner_dialogue_backup import Remote, add, keys


def envelope(payload, key, *, codec=None, plain_bytes=None):
    salt=os.urandom(32);nonce=os.urandom(12)
    header={'schemaVersion':backup.SCHEMA if codec is None else backup.ENVELOPE_SCHEMA,
        'scope':'OWNER_PRIVATE','keyId':key['keyId'],
        'salt':base64.b64encode(salt).decode(),'nonce':base64.b64encode(nonce).decode()}
    if codec is not None:header.update(codec=codec,plainBytes=plain_bytes)
    aad=backup.transport.encode(header)
    cipher=AESGCM(backup._key(key['key'],salt)).encrypt(nonce,payload,aad)
    return len(aad).to_bytes(4,'big')+aad+cipher


def test_legacy_encrypted_archive_restores_then_new_records_use_compression(tmp_path,monkeypatch):
    path=tmp_path/'old';cold=tmp_path/'new';remote=Remote();keyset=keys();one=add(path)
    encrypt=backup._encrypt
    with monkeypatch.context() as patch:
        patch.setattr(backup,'_encrypt',lambda raw,key:envelope(raw,key))
        first=backup.synchronize(path,remote,keyset)
    old_objects=dict(remote.files)
    second=backup.synchronize(cold,remote,keyset)
    assert second['restoredCounts']==first['counts']
    assert remote.files==old_objects  # No rewrite simply for changing codecs.
    assert store.read(path,one,'old')['context']==store.read(cold,one,'new')['context']
    add(cold)
    backup.synchronize(cold,remote,keyset,previous=second)
    head,_=backup._head(remote)
    cipher=b''.join(remote.files[backup.PREFIX+'/chunks/'+c['sha256']+'.bin'] for c in head['chunks'])
    size=int.from_bytes(cipher[:4],'big');header=json.loads(cipher[4:4+size])
    assert header['schemaVersion']==backup.ENVELOPE_SCHEMA and header['codec']=='zlib'
    raw,counts=backup.snapshot(cold)
    assert len(cipher)<len(raw) and backup._decrypt(cipher,keyset)==(raw,keyset['current']['keyId'])
    final=tmp_path/'final';result=backup.synchronize(final,remote,keyset)
    assert result['restoredCounts']==counts and backup.snapshot(final)==backup.snapshot(cold)
    assert all(remote.files[p]==v for p,v in old_objects.items() if '/chunks/' in p)
    assert backup._encrypt is encrypt


def test_compression_is_lossless_and_each_encryption_uses_fresh_randomness():
    raw=b'private original content\n'*10000;keyset=keys()
    a=backup._encrypt(raw,keyset['current']);b=backup._encrypt(raw,keyset['current'])
    assert len(a)<len(raw)//20 and a!=b
    assert backup._decrypt(a,keyset)[0]==raw==backup._decrypt(b,keyset)[0]
    with pytest.raises(InvalidTag):backup._decrypt(a,keys(b'b'*32))


def test_incompressible_data_preserves_wire_bound_and_roundtrip():
    raw=os.urandom(4096);keyset=keys();cipher=backup._encrypt(raw,keyset['current'])
    size=int.from_bytes(cipher[:4],'big');header=json.loads(cipher[4:4+size])
    assert header['codec']=='identity' and len(cipher)<len(raw)+4096
    assert backup._decrypt(cipher,keyset)[0]==raw


@pytest.mark.parametrize('payload,declared',[
    (zlib.compress(b'a'*100000),8),
    (zlib.compress(b'abc')+b'trailing',3),
    (zlib.compress(b'abc')+zlib.compress(b'def'),3),
    (zlib.compress(b'abc')[:-1],3),
    (zlib.compress(b'abc'),4),
])
def test_authenticated_but_invalid_compression_is_rejected(payload,declared):
    keyset=keys();cipher=envelope(payload,keyset['current'],codec='zlib',plain_bytes=declared)
    with pytest.raises(ValueError):backup._decrypt(cipher,keyset)


@pytest.mark.parametrize('codec,size',[('unknown',3),('identity',-1),('zlib',True),('zlib',backup.MAX_ARCHIVE_BYTES+1)])
def test_unknown_codec_and_unbounded_expansion_are_rejected(codec,size):
    keyset=keys();cipher=envelope(b'abc',keyset['current'],codec=codec,plain_bytes=size)
    with pytest.raises(ValueError,match='header_invalid'):backup._decrypt(cipher,keyset)


def test_codec_and_size_are_authenticated():
    keyset=keys();cipher=backup._encrypt(b'a'*10000,keyset['current'])
    size=int.from_bytes(cipher[:4],'big');header=json.loads(cipher[4:4+size])
    header['plainBytes']+=1;aad=backup.transport.encode(header)
    modified=len(aad).to_bytes(4,'big')+aad+cipher[4+size:]
    with pytest.raises(InvalidTag):backup._decrypt(modified,keyset)


def test_bad_compressed_cipher_never_creates_restore_database(tmp_path):
    keyset=keys();remote=Remote();cipher=envelope(zlib.compress(b'a'*10000),keyset['current'],codec='zlib',plain_bytes=1)
    digest=backup.transport.digest(cipher)
    remote.put(backup.PREFIX+'/chunks/'+digest+'.bin',cipher,expected_version=None)
    remote.put(backup.PREFIX+'/head.json',backup.transport.encode({'schemaVersion':backup.SCHEMA,
        'cipherSha256':digest,'cipherBytes':len(cipher),'chunks':[{'sha256':digest,'bytes':len(cipher)}]}),expected_version=None)
    before=dict(remote.files);cold=tmp_path/'cold'
    with pytest.raises(ValueError):backup.synchronize(cold,remote,keyset)
    assert not cold.exists() and remote.files==before
