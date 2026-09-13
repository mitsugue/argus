"""Encrypted owner dialogue recovery using the existing private connection and keys."""
from contextlib import closing
import base64
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import argus_analysis_history_backup as transport
import argus_owner_dialogue as dialogue
import argus_owner_dialogue_store as store

PREFIX='owner-dialogue/v1'
SCHEMA='argus-owner-dialogue-backup-v1'
MAX_ARCHIVE_BYTES=32*1024*1024
CHUNK_BYTES=512*1024
MAX_CIPHER_BYTES=MAX_ARCHIVE_BYTES+4096


def _key(material,salt):
    if not isinstance(material,bytes) or len(material)!=32:raise ValueError('dialogue_backup_key_invalid')
    return HKDF(algorithm=hashes.SHA256(),length=32,salt=salt,
        info=b'argus-owner-dialogue-backup-v1').derive(material)


def _encrypt(raw,current):
    salt=os.urandom(32);nonce=os.urandom(12)
    header={'schemaVersion':SCHEMA,'scope':'OWNER_PRIVATE','keyId':current['keyId'],
        'salt':base64.b64encode(salt).decode(),'nonce':base64.b64encode(nonce).decode()}
    store.require_allowed(header)
    encoded=transport.encode(header)
    return len(encoded).to_bytes(4,'big')+encoded+AESGCM(_key(current['key'],salt)).encrypt(nonce,raw,encoded)


def _decrypt(raw,keys):
    if len(raw)>MAX_CIPHER_BYTES or len(raw)<20:raise ValueError('dialogue_backup_cipher_bound')
    size=int.from_bytes(raw[:4],'big')
    if not 1<=size<=2048:raise ValueError('dialogue_backup_header_bound')
    encoded=raw[4:4+size];header=json.loads(encoded)
    if set(header)!={'schemaVersion','scope','keyId','salt','nonce'} or header['schemaVersion']!=SCHEMA or header['scope']!='OWNER_PRIVATE':
        raise ValueError('dialogue_backup_header_invalid')
    selected=next((keys.get(k) for k in ('current','previous') if (keys.get(k) or {}).get('keyId')==header['keyId']),None)
    if not selected:raise ValueError('dialogue_backup_key_unavailable')
    salt=base64.b64decode(header['salt'],validate=True);nonce=base64.b64decode(header['nonce'],validate=True)
    if len(salt)!=32 or len(nonce)!=12:raise ValueError('dialogue_backup_nonce_invalid')
    plain=AESGCM(_key(selected['key'],salt)).decrypt(nonce,raw[4+size:],encoded)
    if len(plain)>MAX_ARCHIVE_BYTES:raise ValueError('dialogue_backup_archive_bound')
    return plain,header['keyId']


def _request(raw):
    value=store.decode(raw);store.request_id(value['requestId'])
    if set(value)!={'requestId','inputHash','bootId','context','recordDigest'} or not transport.valid_digest(value['inputHash']):
        raise ValueError('dialogue_backup_request_invalid')
    c=value['context']
    if c.get('schemaVersion')!=dialogue.SCHEMA or c.get('scope')!='OWNER_PRIVATE' or c.get('contextId')!=dialogue.digest({k:v for k,v in c.items() if k!='contextId'}):
        raise ValueError('dialogue_backup_context_invalid')
    if any(c.get(k) is not False for k in ('actionAuthority','officialMarketStateMutation','officialPositionMutation','officialPredictionMutation')):
        raise ValueError('dialogue_backup_authority_invalid')
    dialogue.instant(c['receivedAt'])
    return value


def _completion(raw,context):
    value=store.decode(raw)
    if value.get('status') not in ('SUCCEEDED','REJECTED','FAILED','UNAVAILABLE'):raise ValueError('dialogue_backup_result_invalid')
    dialogue.instant(value['completedAt'])
    if value['status']=='SUCCEEDED':
        answer=value.get('answer') or {}
        if dialogue.validate_answer(answer.get('sections'),context)!=answer:raise ValueError('dialogue_backup_answer_invalid')
    elif value.get('answer') is not None:raise ValueError('dialogue_backup_unaccepted_answer')
    return value


def snapshot(path):
    """One read transaction, no retention truncation and no changes to the live DB."""
    parts=[transport.encode({'schemaVersion':SCHEMA,'scope':'OWNER_PRIVATE'})+b'\n'];total=len(parts[0]);counts={'requests':0,'completions':0}
    with closing(store.connect(path,True)) as db:
        db.execute('BEGIN')
        for identity,raw,result in db.execute('SELECT r.request_id,r.body,c.body FROM requests r LEFT JOIN completions c USING(request_id) ORDER BY r.sequence'):
            request=_request(raw)
            if request['requestId']!=identity:raise ValueError('dialogue_backup_row_identity')
            values=[{'kind':'request','value':request}]
            counts['requests']+=1
            if result is not None:
                values.append({'kind':'completion','requestId':identity,'value':_completion(result,request['context'])});counts['completions']+=1
            for row in values:
                part=transport.encode(row)+b'\n';total+=len(part)
                if total>MAX_ARCHIVE_BYTES:raise ValueError('dialogue_backup_archive_bound')
                parts.append(part)
        db.execute('COMMIT')
    return b''.join(parts),counts


def restore(path,raw):
    """Validate into a private staging DB, then merge all rows atomically by UUID."""
    if len(raw)>MAX_ARCHIVE_BYTES:raise ValueError('dialogue_backup_archive_bound')
    with tempfile.TemporaryDirectory(prefix='.owner-recovery-',dir=Path(path).parent) as directory:
        staging=Path(directory)/'validated.sqlite3';store.initialize(staging)
        lines=raw.splitlines()
        if not lines or json.loads(lines[0])!={'schemaVersion':SCHEMA,'scope':'OWNER_PRIVATE'}:raise ValueError('dialogue_backup_archive_schema')
        counts={'requests':0,'completions':0}
        with closing(store.connect(staging)) as db:
            db.execute('BEGIN IMMEDIATE')
            for line in lines[1:]:
                if len(line)>store.MAX_BYTES+256:raise ValueError('dialogue_backup_row_bound')
                row=json.loads(line);body=store.encoded(row['value'])
                if row.get('kind')=='request' and set(row)=={'kind','value'}:
                    value=_request(body)
                    db.execute('INSERT INTO requests(request_id,input_hash,boot_id,body) VALUES(?,?,?,?)',
                        (value['requestId'],value['inputHash'],value['bootId'],body));counts['requests']+=1
                elif row.get('kind')=='completion' and set(row)=={'kind','requestId','value'}:
                    previous=db.execute('SELECT body FROM requests WHERE request_id=?',(row['requestId'],)).fetchone()
                    if not previous:raise ValueError('dialogue_backup_orphan_completion')
                    _completion(body,_request(previous[0])['context'])
                    db.execute('INSERT INTO completions VALUES(?,?)',(row['requestId'],body));counts['completions']+=1
                else:raise ValueError('dialogue_backup_row_kind')
            db.execute('COMMIT')
        store.initialize(path)
        with closing(store.connect(path)) as db:
            db.execute('ATTACH DATABASE ? AS recovered',(str(staging),));db.execute('BEGIN IMMEDIATE')
            for table in ('requests','completions'):
                if db.execute(f'SELECT 1 FROM main.{table} a JOIN recovered.{table} b USING(request_id) WHERE a.body<>b.body LIMIT 1').fetchone():
                    raise ValueError('dialogue_backup_immutable_conflict')
                fields='request_id,input_hash,boot_id,body' if table=='requests' else 'request_id,body'
                order=' ORDER BY sequence' if table=='requests' else ''
                db.execute(f'INSERT INTO main.{table}({fields}) SELECT {fields} FROM recovered.{table} WHERE request_id NOT IN (SELECT request_id FROM main.{table})'+order)
            db.execute('COMMIT')
        return counts


def _head(remote):
    raw,version=remote.get(PREFIX+'/head.json')
    if raw is None:
        if version is not None:raise ValueError('dialogue_backup_head_missing')
        return None,None
    value=json.loads(raw)
    if set(value)!={'schemaVersion','cipherSha256','cipherBytes','chunks'} or value['schemaVersion']!=SCHEMA or not transport.valid_digest(value['cipherSha256']):
        raise ValueError('dialogue_backup_head_invalid')
    chunks=value['chunks']
    if not isinstance(chunks,list) or not 1<=len(chunks)<=MAX_CIPHER_BYTES//CHUNK_BYTES+1:raise ValueError('dialogue_backup_chunk_count')
    if any(set(c)!={'sha256','bytes'} or not transport.valid_digest(c['sha256']) or type(c['bytes']) is not int or not 1<=c['bytes']<=CHUNK_BYTES for c in chunks):raise ValueError('dialogue_backup_chunk_invalid')
    if sum(c['bytes'] for c in chunks)!=value['cipherBytes'] or value['cipherBytes']>MAX_CIPHER_BYTES:raise ValueError('dialogue_backup_size_invalid')
    return value,version


def synchronize(path,remote,keys,*,previous=None):
    """Private transport is verified before any owner data can leave this process."""
    if keys.get('status')!='configured' or not keys.get('current'):raise ValueError('dialogue_backup_keys_required')
    remote.assert_private()
    head,version=_head(remote);known=previous or {};restored=None;remote_plain_sha=None;encrypted_key=None
    if head and (not Path(path).exists() or known.get('headVersion')!=version):
        parts=[]
        for chunk in head['chunks']:
            part,_=remote.get(PREFIX+'/chunks/'+chunk['sha256']+'.bin')
            if part is None or len(part)!=chunk['bytes'] or transport.digest(part)!=chunk['sha256']:raise ValueError('dialogue_backup_chunk_corrupt')
            parts.append(part)
        cipher=b''.join(parts)
        if transport.digest(cipher)!=head['cipherSha256']:raise ValueError('dialogue_backup_cipher_corrupt')
        plain,encrypted_key=_decrypt(cipher,keys)
        restored=restore(path,plain);remote_plain_sha=transport.digest(plain)
    elif head:
        remote_plain_sha=known.get('archiveSha256');encrypted_key=known.get('keyId')
    store.initialize(path);plain,counts=snapshot(path);plain_sha=transport.digest(plain)
    if plain_sha!=remote_plain_sha or encrypted_key!=keys['current']['keyId']:
        cipher=_encrypt(plain,keys['current']);chunks=[]
        for pos in range(0,len(cipher),CHUNK_BYTES):
            part=cipher[pos:pos+CHUNK_BYTES];identity=transport.digest(part)
            transport._immutable(remote,PREFIX+'/chunks/'+identity+'.bin',part)
            chunks.append({'sha256':identity,'bytes':len(part)})
        head={'schemaVersion':SCHEMA,'cipherSha256':transport.digest(cipher),'cipherBytes':len(cipher),'chunks':chunks}
        remote.put(PREFIX+'/head.json',transport.encode(head),expected_version=version)
    verified,version=_head(remote)
    if verified!=head:raise ValueError('dialogue_backup_head_readback_changed')
    return {'status':'VERIFIED','headVersion':version,'archiveSha256':plain_sha,'counts':counts,
        'restoredCounts':restored,'keyId':keys['current']['keyId'],'encryption':'AES_256_GCM_HKDF_SHA256',
        'remoteRecoveryVerified':False}


class PrivateGitHubStore(transport.GitHubStore):
    write_message='Save encrypted owner dialogue recovery'
    def __init__(self,**kwargs):
        self.deadline=time.monotonic()+180
        original=kwargs['http']
        def bounded_http(method,url,**options):
            remaining=self.deadline-time.monotonic()
            if remaining<=0:raise TimeoutError('dialogue_backup_deadline')
            options['timeout']=(min(5,remaining),min(20,remaining))
            return original(method,url,**options)
        super().__init__(**{**kwargs,'http':bounded_http});self.repository=kwargs['repo'];self.private_verified=False
    def _check_deadline(self):
        if time.monotonic()>=self.deadline:raise TimeoutError('dialogue_backup_deadline')
    def assert_private(self):
        response=self.http('GET',self.base.removesuffix('/contents/'),headers=self.headers,timeout=(5,20),allow_redirects=False,stream=True)
        try:
            if response.status_code!=200:raise ValueError('dialogue_backup_private_repo_unverified')
            data=bytearray()
            for part in response.iter_content(8192):
                self._check_deadline()
                data.extend(part)
                if len(data)>65536:raise ValueError('dialogue_backup_repo_metadata_bound')
            metadata=json.loads(data)
            if metadata.get('private') is not True or str(metadata.get('full_name','')).lower()!=self.repository.lower():
                raise ValueError('dialogue_backup_private_repo_required')
            self.private_verified=True
        finally:response.close()
    def put(self,path,raw,*,expected_version):
        if not self.private_verified or not path.startswith(PREFIX+'/'):raise ValueError('dialogue_backup_private_scope_required')
        return super().put(path,raw,expected_version=expected_version)
