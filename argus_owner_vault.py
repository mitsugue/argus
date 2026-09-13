"""Bounded, owner-authorized client-encrypted snapshots in the private repository.

The server validates ciphertext structure and transport checksums only. Decryption
and device data validation stay in the browser. All accepted snapshots are immutable.
"""
import base64
from contextlib import contextmanager
import hashlib
import json
import os
import re
import sqlite3
import threading
import time
import argus_analysis_history_backup as transport

PREFIX='owner-vault/v2'
MAX_BYTES=8*1024*1024
UPLOAD_CHUNK=16000
REMOTE_CHUNK=512*1024
MAX_CATALOG=2000


def identifier(value):
    if not transport.valid_digest(value):raise ValueError('vault_invalid_identity')
    return value


def envelope(raw):
    if not isinstance(raw,bytes) or not 64<=len(raw)<=MAX_BYTES:raise ValueError('vault_size_bound')
    value=json.loads(raw)
    if not isinstance(value,dict) or set(value)!={'v','salt','iv','ct','exportedAt'} or value['v']!=1:
        raise ValueError('vault_invalid_envelope')
    for key,size in [('salt',16),('iv',12)]:
        if not isinstance(value[key],str) or len(value[key])>100 or len(base64.b64decode(value[key],validate=True))!=size:
            raise ValueError('vault_invalid_envelope')
    if not isinstance(value['ct'],str) or len(base64.b64decode(value['ct'],validate=True))<16:
        raise ValueError('vault_invalid_envelope')
    if not isinstance(value['exportedAt'],str) or len(value['exportedAt'])>40:raise ValueError('vault_invalid_envelope')
    return value


class PrivateStore(transport.GitHubStore):
    write_message='Save client-encrypted owner device snapshot'
    def __init__(self,**kwargs):
        self.deadline=time.monotonic()+180
        self.repository=kwargs['repo'];self.private_verified=False
        super().__init__(**kwargs)
    def _check_deadline(self):
        if time.monotonic()>self.deadline:raise TimeoutError('vault_remote_deadline')
    def assert_private(self):
        self._check_deadline()
        response=self.http('GET',self.base.removesuffix('/contents/'),headers=self.headers,timeout=(5,15),allow_redirects=False,stream=True)
        try:
            if response.status_code!=200:raise ValueError('vault_private_repository_unverified')
            raw=bytearray()
            for part in response.iter_content(8192):
                self._check_deadline();raw.extend(part)
                if len(raw)>65536:raise ValueError('vault_metadata_bound')
            value=json.loads(raw)
            if value.get('private') is not True or str(value.get('full_name','')).lower()!=self.repository.lower():
                raise ValueError('vault_private_repository_required')
            self.private_verified=True
        finally:response.close()
    def put(self,path,raw,*,expected_version):
        if not self.private_verified or not re.fullmatch(r'owner-vault/v2/[a-f0-9]{64}/(?:catalog\.json|(?:chunks|manifests)/[a-f0-9]{64}\.(?:bin|json))',path):
            raise ValueError('vault_private_scope_required')
        return super().put(path,raw,expected_version=expected_version)


def catalog(remote,vault):
    raw,version=remote.get(PREFIX+'/'+identifier(vault)+'/catalog.json')
    if raw is None:return [],version
    value=json.loads(raw)
    if not isinstance(value,dict) or set(value)!={'schemaVersion','snapshots'} or value['schemaVersion']!='argus-owner-vault-catalog-v2':
        raise ValueError('vault_catalog_invalid')
    rows=value['snapshots']
    if not isinstance(rows,list) or len(rows)>MAX_CATALOG:raise ValueError('vault_catalog_bound')
    seen=set()
    for row in rows:
        if not isinstance(row,dict) or set(row)!={'snapshotId','bytes','savedAt','exportedAt'} or not transport.valid_digest(row['snapshotId']):
            raise ValueError('vault_catalog_invalid')
        if row['snapshotId'] in seen or type(row['bytes']) is not int or not 64<=row['bytes']<=MAX_BYTES:
            raise ValueError('vault_catalog_invalid')
        if not isinstance(row['savedAt'],(int,float)) or not isinstance(row['exportedAt'],str):raise ValueError('vault_catalog_invalid')
        seen.add(row['snapshotId'])
    return rows,version


def read_snapshot(remote,vault,identity):
    prefix=PREFIX+'/'+identifier(vault);identifier(identity)
    raw,_=remote.get(prefix+'/manifests/'+identity+'.json')
    if raw is None:raise ValueError('vault_snapshot_missing')
    manifest=json.loads(raw)
    if not isinstance(manifest,dict) or set(manifest)!={'snapshotId','bytes','chunks'} or manifest['snapshotId']!=identity:
        raise ValueError('vault_manifest_invalid')
    chunks=manifest['chunks']
    if not isinstance(chunks,list) or not 1<=len(chunks)<=MAX_BYTES//REMOTE_CHUNK:raise ValueError('vault_chunk_count')
    parts=[];total=0
    for chunk in chunks:
        if not isinstance(chunk,dict) or set(chunk)!={'sha256','bytes'} or not transport.valid_digest(chunk['sha256']) or type(chunk['bytes']) is not int or not 1<=chunk['bytes']<=REMOTE_CHUNK:
            raise ValueError('vault_chunk_invalid')
        part,_=remote.get(prefix+'/chunks/'+chunk['sha256']+'.bin')
        if part is None or len(part)!=chunk['bytes'] or transport.digest(part)!=chunk['sha256']:raise ValueError('vault_chunk_readback_failed')
        total+=len(part)
        if total>MAX_BYTES:raise ValueError('vault_size_bound')
        parts.append(part)
    result=b''.join(parts)
    if total!=manifest['bytes'] or transport.digest(result)!=identity:raise ValueError('vault_snapshot_readback_failed')
    envelope(result)
    return result


def publish(remote,vault,raw,now):
    remote.assert_private();env=envelope(raw);identity=transport.digest(raw);prefix=PREFIX+'/'+identifier(vault)
    chunks=[]
    for offset in range(0,len(raw),REMOTE_CHUNK):
        part=raw[offset:offset+REMOTE_CHUNK];sha=transport.digest(part)
        transport._immutable(remote,prefix+'/chunks/'+sha+'.bin',part);chunks.append({'sha256':sha,'bytes':len(part)})
    manifest={'snapshotId':identity,'bytes':len(raw),'chunks':chunks}
    transport._immutable(remote,prefix+'/manifests/'+identity+'.json',transport.encode(manifest))
    if read_snapshot(remote,vault,identity)!=raw:raise ValueError('vault_snapshot_readback_failed')
    for _ in range(3):
        rows,version=catalog(remote,vault)
        if any(row['snapshotId']==identity for row in rows):return identity
        if len(rows)>=MAX_CATALOG:raise ValueError('vault_catalog_full_existing_snapshots_retained')
        rows.append({'snapshotId':identity,'bytes':len(raw),'savedAt':now,'exportedAt':env['exportedAt']})
        try:remote.put(prefix+'/catalog.json',transport.encode({'schemaVersion':'argus-owner-vault-catalog-v2','snapshots':rows}),expected_version=version)
        except ValueError as exc:
            if str(exc)!='history_remote_write_conflict_or_unavailable':raise
            continue
        verified,_=catalog(remote,vault)
        if any(row['snapshotId']==identity for row in verified):return identity
    raise ValueError('vault_catalog_concurrent_change')


class VaultService:
    def __init__(self,*,path,remote,now=time.time):self.path=path;self.remote=remote;self.now=now;self.lock=threading.Lock();self.boot=str(time.time_ns())
    @contextmanager
    def db(self):
        path=self.path()
        if not path:raise ValueError('vault_storage_unavailable')
        os.makedirs(os.path.dirname(path),exist_ok=True)
        fd=os.open(path,os.O_CREAT|os.O_RDWR,0o600);os.close(fd);os.chmod(path,0o600)
        db=sqlite3.connect(path,timeout=5);db.row_factory=sqlite3.Row
        try:
            db.execute('PRAGMA synchronous=FULL')
            db.executescript('''CREATE TABLE IF NOT EXISTS uploads (
              vault TEXT, identity TEXT, bytes INTEGER, state TEXT, updated REAL, boot TEXT,
              error TEXT, PRIMARY KEY(vault,identity));
              CREATE TABLE IF NOT EXISTS chunks (vault TEXT, identity TEXT, part INTEGER, body BLOB,
              PRIMARY KEY(vault,identity,part));''')
            yield db;db.commit()
        finally:db.close()
    def handle(self,body):
        allowed={'action','ownerToken','operation','vaultId','snapshotId','bytes','part','data','offset'}
        if set(body)-allowed:raise ValueError('vault_invalid_request')
        vault=identifier(body.get('vaultId'));op=body.get('operation');now=self.now()
        if op=='list':
            remote=self.remote();remote.assert_private();rows,_=catalog(remote,vault)
            offset=body.get('offset',0)
            if type(offset) is not int or not 0<=offset<=MAX_CATALOG:raise ValueError('vault_invalid_offset')
            ordered=sorted(rows,key=lambda r:r['savedAt'],reverse=True)
            return {'snapshots':ordered[offset:offset+20],'nextOffset':offset+20 if len(rows)>offset+20 else None,'transportVerified':True,'decryptionVerified':False}
        identity=identifier(body.get('snapshotId'))
        if op=='read':
            remote=self.remote();remote.assert_private();raw=read_snapshot(remote,vault,identity)
            return {'snapshotId':identity,'blob':raw.decode(),'transportVerified':True,'decryptionVerified':False}
        if op not in {'begin','chunk','commit','status'}:raise ValueError('vault_invalid_operation')
        start=False
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT * FROM uploads WHERE vault=? AND identity=?',(vault,identity)).fetchone()
            if op=='begin':
                size=body.get('bytes')
                if type(size) is not int or not 64<=size<=MAX_BYTES:raise ValueError('vault_size_bound')
                if row and row['bytes']!=size:raise ValueError('vault_upload_conflict')
                if not row:
                    # Bound staging without deleting any in-progress owner data.
                    if db.execute("SELECT count(*) FROM uploads WHERE state!='VERIFIED'").fetchone()[0]>=5:raise ValueError('vault_staging_full')
                    db.execute('INSERT INTO uploads VALUES(?,?,?,\'UPLOADING\',?,?,NULL)',(vault,identity,size,now,self.boot))
            else:
                if not row:raise ValueError('vault_upload_missing')
                if op=='chunk':
                    part=body.get('part');data=body.get('data')
                    count=(row['bytes']+UPLOAD_CHUNK-1)//UPLOAD_CHUNK
                    if type(part) is not int or not 0<=part<count or not isinstance(data,str) or len(data)>UPLOAD_CHUNK*2:raise ValueError('vault_chunk_invalid')
                    raw=data.encode('utf-8');expected=min(UPLOAD_CHUNK,row['bytes']-part*UPLOAD_CHUNK)
                    if len(raw)!=expected:raise ValueError('vault_chunk_size')
                    old=db.execute('SELECT body FROM chunks WHERE vault=? AND identity=? AND part=?',(vault,identity,part)).fetchone()
                    if old and old[0]!=raw:raise ValueError('vault_upload_conflict')
                    if row['state']!='UPLOADING' and not old:raise ValueError('vault_upload_closed')
                    db.execute('INSERT OR IGNORE INTO chunks VALUES(?,?,?,?)',(vault,identity,part,raw))
                elif op=='commit':
                    count=db.execute('SELECT count(*) FROM chunks WHERE vault=? AND identity=?',(vault,identity)).fetchone()[0]
                    if row['state']!='VERIFIED' and count!=(row['bytes']+UPLOAD_CHUNK-1)//UPLOAD_CHUNK:raise ValueError('vault_upload_incomplete')
                    if row['state'] in {'UPLOADING','FAILED'} or (row['state']=='SAVING' and row['boot']!=self.boot):
                        db.execute("UPDATE uploads SET state='SAVING',boot=?,updated=?,error=NULL WHERE vault=? AND identity=?",(self.boot,now,vault,identity));start=True
            row=db.execute('SELECT * FROM uploads WHERE vault=? AND identity=?',(vault,identity)).fetchone()
            parts=[r[0] for r in db.execute('SELECT part FROM chunks WHERE vault=? AND identity=? ORDER BY part',(vault,identity))]
            result={'snapshotId':identity,'state':row['state'] if row['boot']==self.boot or row['state']!='SAVING' else 'INTERRUPTED',
                'parts':parts,'chunkBytes':UPLOAD_CHUNK,'bytes':row['bytes'],'error':row['error'],'transportVerified':row['state']=='VERIFIED','decryptionVerified':False}
        if start:
            try:threading.Thread(target=self._publish,args=(vault,identity),daemon=True,name='owner-vault-save').start()
            except Exception:
                with self.db() as db:db.execute("UPDATE uploads SET state='FAILED',error='vault_worker_start_failed' WHERE vault=? AND identity=?",(vault,identity))
                raise ValueError('vault_worker_start_failed')
        return result
    def _publish(self,vault,identity):
        try:
            with self.lock:
                with self.db() as db:
                    row=db.execute('SELECT * FROM uploads WHERE vault=? AND identity=?',(vault,identity)).fetchone()
                    parts=db.execute('SELECT part,body FROM chunks WHERE vault=? AND identity=? ORDER BY part',(vault,identity)).fetchall()
                if [r[0] for r in parts]!=list(range((row['bytes']+UPLOAD_CHUNK-1)//UPLOAD_CHUNK)):raise ValueError('vault_upload_incomplete')
                raw=b''.join(r[1] for r in parts)
                if len(raw)!=row['bytes'] or transport.digest(raw)!=identity:raise ValueError('vault_upload_checksum')
                publish(self.remote(),vault,raw,self.now())
                with self.db() as db:
                    db.execute("UPDATE uploads SET state='VERIFIED',error=NULL,updated=? WHERE vault=? AND identity=?",(self.now(),vault,identity))
                    db.execute('DELETE FROM chunks WHERE vault=? AND identity=?',(vault,identity))
        except Exception as exc:
            reason=str(exc) if isinstance(exc,ValueError) and str(exc).startswith('vault_') else 'vault_remote_unavailable'
            try:
                with self.db() as db:db.execute("UPDATE uploads SET state='FAILED',error=? WHERE vault=? AND identity=?",(reason,vault,identity))
            except Exception:pass
