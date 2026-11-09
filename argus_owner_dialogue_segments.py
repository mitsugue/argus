"""Bounded segments inside the existing encrypted owner-dialogue transport.

The old 32 MiB archive and readers remain intact. A growing history uses
smaller encrypted segments on the same private connection, under the same
head and chunk namespace. No source row, key, timer or store is replaced.
"""
import base64
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import time

import argus_owner_dialogue_backup as legacy
import argus_owner_dialogue_store as store
import argus_analysis_history_backup as transport
import argus_owner_recovery_diagnostics as diagnostics

SCHEMA='argus-owner-dialogue-segmented-manifest-v2'
HEAD_SCHEMA='argus-owner-dialogue-segmented-head-v2'
SEGMENT_BYTES=8*1024*1024
SEGMENT_TARGET=4*1024*1024
MANIFEST_BYTES=512*1024
MAX_SEGMENTS=1000
# The existing streamed history contract; never one in-memory allocation.
MAX_LOGICAL_BYTES=4*1024*1024*1024
MINIMUM_FREE_BYTES=1024*1024*1024
HEADER=transport.encode({'schemaVersion':legacy.SCHEMA,'scope':'OWNER_PRIVATE'})+b'\n'


def _time(remote,started):
    check=getattr(remote,'_check_deadline',None)
    if callable(check):check()
    if time.monotonic()-started>=180:raise TimeoutError('dialogue_backup_deadline')


def _space(parent,needed):
    if shutil.disk_usage(parent).free<MINIMUM_FREE_BYTES+needed:
        raise ValueError('dialogue_backup_segment_storage_headroom')


def _add(target,counts):
    for key,value in counts.items():target[key]=target.get(key,0)+value


def _counts(value):
    allowed={'requests','completions','historicalMethodScopeCompletions'}
    return (isinstance(value,dict) and {'requests','completions'}<=set(value)<=allowed
        and all(type(v) is int and 0<=v<=1000000 for v in value.values())
        and value['completions']<=value['requests']
        and value.get('historicalMethodScopeCompletions',0)<=value['completions'])


def _validate_manifest(value):
    if (not isinstance(value,dict) or set(value)!={'schemaVersion','scope','keyId',
            'logicalSha256','logicalBytes','counts','segments'} or value['schemaVersion']!=SCHEMA
            or value['scope']!='OWNER_PRIVATE' or not isinstance(value['keyId'],str)
            or not 1<=len(value['keyId'])<=128 or not transport.valid_digest(value['logicalSha256'])
            or type(value['logicalBytes']) is not int or not len(HEADER)<=value['logicalBytes']<=MAX_LOGICAL_BYTES
            or not _counts(value['counts'])):
        raise ValueError('dialogue_backup_segment_manifest_invalid')
    segments=value['segments']
    if not isinstance(segments,list) or not 1<=len(segments)<=MAX_SEGMENTS:
        raise ValueError('dialogue_backup_segment_manifest_invalid')
    total=0;counts={'requests':0,'completions':0};seen=set()
    cap=min(SEGMENT_BYTES,legacy.MAX_ARCHIVE_BYTES)
    for row in segments:
        if (not isinstance(row,dict) or set(row)!={'plainSha256','plainBytes','counts',
                'cipherSha256','cipherBytes','chunks','keyId'}
                or not transport.valid_digest(row['plainSha256']) or row['plainSha256'] in seen
                or type(row['plainBytes']) is not int or not len(HEADER)<row['plainBytes']<=cap
                or row['keyId']!=value['keyId'] or not _counts(row['counts'])
                or not transport.valid_digest(row['cipherSha256'])
                or type(row['cipherBytes']) is not int or not 20<=row['cipherBytes']<=cap+4096):
            raise ValueError('dialogue_backup_segment_manifest_invalid')
        chunks=row['chunks']
        if (not isinstance(chunks,list) or not 1<=len(chunks)<=(cap+4096)//legacy.CHUNK_BYTES+1
                or any(not isinstance(c,dict) or set(c)!={'sha256','bytes'}
                    or not transport.valid_digest(c['sha256']) or type(c['bytes']) is not int
                    or not 1<=c['bytes']<=legacy.CHUNK_BYTES for c in chunks)
                or sum(c['bytes'] for c in chunks)!=row['cipherBytes']):
            raise ValueError('dialogue_backup_segment_manifest_invalid')
        total+=row['plainBytes'];_add(counts,row['counts']);seen.add(row['plainSha256'])
    if (counts!=value['counts'] or total-(len(segments)-1)*len(HEADER)!=value['logicalBytes']
            or len(transport.encode(value))>MANIFEST_BYTES):
        raise ValueError('dialogue_backup_segment_manifest_invalid')
    return value


def open_head(raw,keys):
    if not keys or len(raw)>MANIFEST_BYTES:raise ValueError('dialogue_backup_segment_manifest_invalid')
    value=json.loads(raw)
    if (not isinstance(value,dict) or set(value)!={'schemaVersion','cipherSha256','cipherBytes','manifest'}
            or value['schemaVersion']!=HEAD_SCHEMA or not transport.valid_digest(value['cipherSha256'])
            or type(value['cipherBytes']) is not int or not 20<=value['cipherBytes']<=MANIFEST_BYTES+4096
            or not isinstance(value['manifest'],str)):
        raise ValueError('dialogue_backup_segment_manifest_invalid')
    cipher=base64.b64decode(value['manifest'],validate=True)
    if (base64.b64encode(cipher).decode()!=value['manifest'] or len(cipher)!=value['cipherBytes']
            or transport.digest(cipher)!=value['cipherSha256']):
        raise ValueError('dialogue_backup_segment_manifest_invalid')
    plain,key_id=legacy._decrypt(cipher,keys,maximum_bytes=MANIFEST_BYTES)
    manifest=_validate_manifest(json.loads(plain))
    if manifest['keyId']!=key_id:raise ValueError('dialogue_backup_segment_manifest_invalid')
    return manifest


def _sealed_head(value,current):
    raw=transport.encode(_validate_manifest(value));cipher=legacy._encrypt(raw,current)
    head=transport.encode({'schemaVersion':HEAD_SCHEMA,'cipherSha256':transport.digest(cipher),
        'cipherBytes':len(cipher),'manifest':base64.b64encode(cipher).decode()})
    if len(head)>MANIFEST_BYTES:raise ValueError('dialogue_backup_segment_manifest_invalid')
    return head


def _spool(path,directory,remote,started):
    """End the consistent DB read before doing any network write."""
    cap=min(SEGMENT_BYTES,legacy.MAX_ARCHIVE_BYTES);target=min(SEGMENT_TARGET,cap)
    parts=[];batch=[HEADER];size=len(HEADER);part_counts={'requests':0,'completions':0}
    counts={'requests':0,'completions':0};logical=len(HEADER);digest=hashlib.sha256(HEADER)
    def emit():
        raw=b''.join(batch);_space(directory,len(raw)*2)
        file=Path(directory)/str(len(parts))
        with os.fdopen(os.open(file,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600),'wb') as handle:handle.write(raw)
        parts.append({'file':file,'plainSha256':transport.digest(raw),'plainBytes':len(raw),'counts':dict(part_counts)})
        if len(parts)>MAX_SEGMENTS:raise ValueError('dialogue_backup_segment_manifest_invalid')
    with closing(store.connect(path,True)) as db:
        db.execute('BEGIN')
        for identity,raw,result in db.execute('SELECT r.request_id,r.body,c.body FROM requests r LEFT JOIN completions c USING(request_id) ORDER BY r.sequence'):
            _time(remote,started);request=legacy._request(raw)
            if request['requestId']!=identity:raise ValueError('dialogue_backup_row_identity')
            values=[{'kind':'request','value':request}];unit={'requests':1,'completions':0}
            if result is not None:
                diagnostic={};completion=legacy._completion(result,request['context'],diagnostic=diagnostic)
                values.append({'kind':'completion','requestId':identity,'value':completion});unit['completions']=1
                if diagnostic.get('historicalMethodScope'):unit['historicalMethodScopeCompletions']=1
            lines=[transport.encode(row)+b'\n' for row in values]
            if any(len(line)>store.MAX_BYTES+256 for line in lines):raise ValueError('dialogue_backup_row_bound')
            extra=sum(map(len,lines))
            if extra+len(HEADER)>cap:raise ValueError('dialogue_backup_archive_bound')
            if size>len(HEADER) and (size+extra>cap or size>=target):
                emit();batch=[HEADER];size=len(HEADER);part_counts={'requests':0,'completions':0}
            batch.extend(lines);size+=extra;_add(part_counts,unit);_add(counts,unit)
            for line in lines:digest.update(line)
            logical+=extra
            if logical>MAX_LOGICAL_BYTES:raise ValueError('dialogue_backup_archive_bound')
        if size>len(HEADER):emit()
        db.execute('COMMIT')
    return parts,counts,logical,digest.hexdigest()


def _read_part(row,remote,keys,started):
    parts=[]
    for chunk in row['chunks']:
        _time(remote,started);part,_=diagnostics.phase('remote_chunks',remote.get,
            legacy.PREFIX+'/chunks/'+chunk['sha256']+'.bin')
        if part is None or len(part)!=chunk['bytes'] or transport.digest(part)!=chunk['sha256']:
            raise ValueError('dialogue_backup_chunk_corrupt')
        parts.append(part)
    cipher=b''.join(parts)
    if transport.digest(cipher)!=row['cipherSha256']:raise ValueError('dialogue_backup_cipher_corrupt')
    raw,key_id=diagnostics.phase('decrypt',legacy._decrypt,cipher,keys,
        maximum_bytes=min(SEGMENT_BYTES,legacy.MAX_ARCHIVE_BYTES))
    if key_id!=row['keyId'] or len(raw)!=row['plainBytes'] or transport.digest(raw)!=row['plainSha256']:
        raise ValueError('dialogue_backup_segment_integrity')
    return raw


def _restore(path,head,remote,keys,started):
    _space(Path(path).parent,head['logicalBytes']*2)
    with tempfile.TemporaryDirectory(prefix='.owner-segment-restore-',dir=Path(path).parent) as directory:
        staging=Path(directory)/'validated.sqlite3';store.initialize(staging)
        digest=hashlib.sha256(HEADER);logical=len(HEADER);counts={'requests':0,'completions':0}
        for row in head['segments']:
            raw=_read_part(row,remote,keys,started)
            if not raw.startswith(HEADER):raise ValueError('dialogue_backup_archive_schema')
            actual=diagnostics.phase('remote_records',legacy.restore,staging,raw)
            if actual!=row['counts']:raise ValueError('dialogue_backup_segment_integrity')
            _add(counts,actual);digest.update(raw[len(HEADER):]);logical+=len(raw)-len(HEADER)
        if logical!=head['logicalBytes'] or digest.hexdigest()!=head['logicalSha256'] or counts!=head['counts']:
            raise ValueError('dialogue_backup_segment_integrity')
        with closing(store.connect(staging,True)) as db:
            if (db.execute('SELECT COUNT(*) FROM requests').fetchone()[0]!=counts['requests']
                    or db.execute('SELECT COUNT(*) FROM completions').fetchone()[0]!=counts['completions']):
                raise ValueError('dialogue_backup_segment_integrity')
        _time(remote,started);legacy._merge_staging(path,staging)
    return counts


def synchronize(path,remote,keys,*,head,version,previous,restored=None):
    """Same single worker/CAS head; publish only after every part is verified."""
    started=time.monotonic();segmented=head and head.get('schemaVersion')==SCHEMA
    if segmented and (not Path(path).exists() or previous.get('headVersion')!=version):
        restored=_restore(path,head,remote,keys,started)
    store.initialize(path);_space(Path(path).parent,2*min(SEGMENT_BYTES,legacy.MAX_ARCHIVE_BYTES))
    with tempfile.TemporaryDirectory(prefix='.owner-segment-export-',dir=Path(path).parent) as directory:
        parts,counts,logical,logical_sha=diagnostics.phase('local_records',_spool,path,directory,remote,started)
        old={row['plainSha256']:row for row in head['segments']} if segmented else {}
        entries=[]
        for part in parts:
            _time(remote,started);prior=old.get(part['plainSha256'])
            if (prior and prior['plainBytes']==part['plainBytes'] and prior['counts']==part['counts']
                    and prior['keyId']==keys['current']['keyId']):
                entries.append(prior);continue
            raw=part['file'].read_bytes();cipher=legacy._encrypt(raw,keys['current']);chunks=[]
            for pos in range(0,len(cipher),legacy.CHUNK_BYTES):
                body=cipher[pos:pos+legacy.CHUNK_BYTES];identity=transport.digest(body)
                diagnostics.phase('remote_write',transport._immutable,remote,
                    legacy.PREFIX+'/chunks/'+identity+'.bin',body)
                chunks.append({'sha256':identity,'bytes':len(body)})
            entries.append({'plainSha256':part['plainSha256'],'plainBytes':part['plainBytes'],
                'counts':part['counts'],'cipherSha256':transport.digest(cipher),'cipherBytes':len(cipher),
                'chunks':chunks,'keyId':keys['current']['keyId']})
        manifest={'schemaVersion':SCHEMA,'scope':'OWNER_PRIVATE','keyId':keys['current']['keyId'],
            'logicalSha256':logical_sha,'logicalBytes':logical,'counts':counts,'segments':entries}
        _validate_manifest(manifest)
        if manifest!=head:
            diagnostics.phase('remote_write',remote.put,legacy.PREFIX+'/head.json',
                _sealed_head(manifest,keys['current']),expected_version=version)
        verified,version=diagnostics.phase('readback',legacy._head,remote,keys)
        if verified!=manifest:raise ValueError('dialogue_backup_head_readback_changed')
    return {'status':'VERIFIED','headVersion':version,'archiveSha256':logical_sha,'counts':counts,
        'restoredCounts':restored,'keyId':keys['current']['keyId'],'encryption':'AES_256_GCM_HKDF_SHA256',
        'remoteRecoveryVerified':False,'archiveStorage':{'mode':'SEGMENTED_ENCRYPTED_V2',
            'parts':len(entries),'logicalBytes':logical,'largestPlainPartBytes':max(r['plainBytes'] for r in entries),
            'plainPartLimit':min(SEGMENT_BYTES,legacy.MAX_ARCHIVE_BYTES),'legacyArchiveLimit':legacy.MAX_ARCHIVE_BYTES}}
