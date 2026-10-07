"""Whitelist-only market originals in the existing source store/private backup.

No owner registry, credentials, HTTP headers or runtime response is exported.
Source receipts and revisions are immutable; this is a backup adapter, not a
second collection lane or a claim of historical publication vintage.
"""
import base64
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import tempfile
import time

import argus_earnings_history as earnings
import jp_market_acquisition as sources
from argus_analysis_history_backup import CHUNK_BYTES, MAX_ARCHIVE_BYTES, MAX_SYNC_SECONDS

PRIVATE_REPO='mitsugue/argus-l2b-private'
PREFIX='market-analysis/source-inputs/v1'
SCHEMA='argus-private-market-inputs-v1'
SECTOR_CODES={str(n) for n in range(1617,1634)}
BAR_FIELDS={'Date','Code','O','H','L','C','Vo','Va','AdjFactor','AdjO','AdjH','AdjL','AdjC','AdjVo',
            'UL','LL','MO','MH','ML','MC','MUL','MLL','MVo','MVa',
            'MAdjO','MAdjH','MAdjL','MAdjC','MAdjVo',
            'AO','AH','AL','AC','AUL','ALL','AVo','AVa',
            'AAdjO','AAdjH','AAdjL','AAdjC','AAdjVo',
            # Official V2 daily columns plus these two scalar fields observed
            # in the authenticated daily response on 2026-10-07. Unknown fields
            # still abort export; never strip fields from retained originals.
            'ExRT','MktCap'}


def _hash(raw):return hashlib.sha256(raw).hexdigest()

def _sector_payload(raw,symbol):
    if symbol not in SECTOR_CODES or not isinstance(raw,bytes) or not 0<len(raw)<=sources.MAX_BYTES:
        raise ValueError('private_sector_original_scope')
    body=json.loads(raw)
    if not isinstance(body,dict) or set(body)-{'data','pagination_key'} or body.get('pagination_key'):
        raise ValueError('private_sector_original_schema')
    rows=body.get('data')
    if not isinstance(rows,list) or not 1<=len(rows)<=6000:raise ValueError('private_sector_original_bound')
    for row in rows:
        if not isinstance(row,dict) or set(row)-BAR_FIELDS or str(row.get('Code') or '')[:4]!=symbol:
            raise ValueError('private_sector_original_fields')
        sources._time(str(row.get('Date'))+'T00:00:00Z')
        if any(type(v) not in (str,int,float,type(None)) for v in row.values()):
            raise ValueError('private_sector_original_fields')
    # Reject non-finite values before storing the original bytes.
    sources._json(body)
    return rows


def retain_sector(path,raw,*,symbol,received_at):
    rows=_sector_payload(raw,symbol);receipt=sources._time(received_at)
    if any(sources._time(r['Date']+'T00:00:00Z')>receipt for r in rows):
        raise ValueError('private_sector_future_original')
    url='https://api.jquants.com/v2/equities/bars/daily?code='+symbol
    digest=_hash(raw);raw_id=_hash((url+':'+digest).encode())
    db=sources.connect(path)
    try:
        with db:
            db.execute('INSERT OR IGNORE INTO raw_sources VALUES(?,?,?,?,?)',(raw_id,url,digest,received_at,raw))
    finally:db.close()
    return {'status':'RETAINED','sourceResponseSha256':digest,'rows':len(rows),'receivedAt':received_at}


def _validate_original(url,raw):
    if url==earnings.URL:
        body=json.loads(raw)
        if set(body)!= {'data'} or not isinstance(body['data'],list) or len(body['data'])>earnings.MAX_ROWS:
            raise ValueError('private_financial_original_schema')
        for row in body['data']:
            if not isinstance(row,dict) or set(row)-set(earnings.FIELDS):
                raise ValueError('private_financial_original_fields')
            earnings._compact(row)
        sources._json(body)
    else:
        match=re.fullmatch(r'https://api\.jquants\.com/v2/equities/bars/daily\?code=(\d{4})',url)
        if not match:raise ValueError('private_original_source_not_approved')
        _sector_payload(raw,match[1])


def snapshot(path,directory):
    location=Path(path)
    if location.is_symlink() or not location.is_file():raise ValueError('private_original_store_required')
    db=sqlite3.connect(location.resolve().as_uri()+'?mode=ro',uri=True)
    destination=Path(directory)/'inputs.ndjson';ids=set();counts={'financial':0,'sector17':0,'observations':0,'coverageReceipts':0}
    try:
        db.execute('BEGIN')
        with destination.open('wb') as out:
            def write(row):
                out.write(sources._json(row).encode()+b'\n')
                if out.tell()>MAX_ARCHIVE_BYTES:raise ValueError('private_original_backup_bound')
            write({'schemaVersion':SCHEMA,'scope':'PUBLIC_MARKET_INPUTS','ownerRecordsIncluded':False})
            for identity,url,digest,received,raw in db.execute('SELECT id,url,sha256,received_at,raw FROM raw_sources ORDER BY id'):
                if url!=earnings.URL and not re.fullmatch(r'https://api\.jquants\.com/v2/equities/bars/daily\?code=16(?:1[7-9]|2[0-9]|3[0-3])',url):continue
                if len(raw)>sources.MAX_BYTES or _hash(raw)!=digest or identity!=_hash((url+':'+digest).encode()):
                    raise ValueError('private_original_integrity')
                _validate_original(url,raw);sources._time(received);ids.add(identity)
                write({'kind':'raw','id':identity,'url':url,'sha256':digest,'receivedAt':received,'dataBase64':base64.b64encode(raw).decode()})
                counts['financial' if url==earnings.URL else 'sector17']+=1
            for source_id,session,raw_id,body in db.execute('SELECT source_id,session,raw_id,body FROM observations ORDER BY seq'):
                if raw_id not in ids or not re.fullmatch(r'financial-summary:[0-9A-Z]{4}',source_id):continue
                row=json.loads(body)
                allowed={'summary','receivedAt','knownAt','publishedAt','historicalVintageVerified','sourceRef','sourceResponseSha256','rawId','observationId'}
                if set(row)-allowed or set(row.get('summary') or {})-set(earnings.FIELDS):raise ValueError('private_observation_fields')
                summary=earnings._compact(row['summary'])
                original=db.execute('SELECT raw,sha256,received_at FROM raw_sources WHERE id=?',(raw_id,)).fetchone()
                published=earnings._published(summary)
                if (not original or row.get('rawId')!=raw_id or row.get('sourceResponseSha256')!=original[1]
                        or row.get('sourceRef')!=earnings.URL or row.get('knownAt')!=original[2]
                        or row.get('receivedAt')!=original[2]
                        or row.get('publishedAt')!=(published.isoformat() if published else None)
                        or row.get('observationId')!=session or session!=_hash(sources._json(summary).encode())
                        or summary not in json.loads(original[0])['data']):
                    raise ValueError('private_observation_integrity')
                write({'kind':'observation','sourceId':source_id,'session':session,'rawId':raw_id,'body':row});counts['observations']+=1
            coverage_allowed={'status','retainedRows','newObservations','rejectedRows','receivedAt','memberCount','queryDate','goodEarningsRuleDefined','actionAuthority','complete','memberCodes','knownAt','rawId','sourceResponseSha256','coverageSha256'}
            for key,body in db.execute("SELECT key,value FROM metadata WHERE key LIKE 'financial-summary-date:%' ORDER BY key"):
                row=json.loads(body)
                if row.get('rawId') not in ids:continue
                if set(row)-coverage_allowed:raise ValueError('private_coverage_fields')
                checksum=row.pop('coverageSha256',None)
                if checksum and _hash(sources._json(row).encode())!=checksum:raise ValueError('private_coverage_integrity')
                if checksum:row['coverageSha256']=checksum
                if any(not re.fullmatch(r'[0-9A-Z]{4}',c) for c in row.get('memberCodes',[])):raise ValueError('private_coverage_fields')
                source=db.execute('SELECT sha256 FROM raw_sources WHERE id=?',(row['rawId'],)).fetchone()
                if not source or row.get('sourceResponseSha256')!=source[0]:raise ValueError('private_coverage_integrity')
                sources._time(row['knownAt']);sources._time(row['receivedAt'])
                write({'kind':'coverage','key':key,'body':row});counts['coverageReceipts']+=1
        db.execute('COMMIT')
    finally:db.close()
    chunks=[];total=0;digest=hashlib.sha256()
    with destination.open('rb') as handle:
        while raw:=handle.read(CHUNK_BYTES):
            checksum=_hash(raw);(Path(directory)/checksum).write_bytes(raw);digest.update(raw);total+=len(raw)
            chunks.append({'sha256':checksum,'bytes':len(raw)})
    return {'schemaVersion':SCHEMA,'scope':'PUBLIC_MARKET_INPUTS','ownerRecordsIncluded':False,
            'credentialsIncluded':False,'originalArchiveSha256':digest.hexdigest(),'archiveBytes':total,
            'chunks':chunks,'counts':counts,'actionAuthority':False}


def synchronize(path,remote):
    # Reuse the existing configured Contents connection, but require exactly
    # the owner-approved private repository before the first outbound body.
    started=time.monotonic()
    def budget():
        if time.monotonic()-started>=MAX_SYNC_SECONDS:
            raise ValueError('private_original_backup_deadline')
    expected='https://api.github.com/repos/'+PRIVATE_REPO+'/contents/'
    if getattr(remote,'base',None)!=expected:raise ValueError('private_original_backup_destination')
    repo=remote._read_json(expected.removesuffix('/contents/'))
    if not isinstance(repo,dict) or repo.get('private') is not True:
        raise ValueError('private_original_backup_visibility')
    with tempfile.TemporaryDirectory(prefix='argus-market-input-backup-') as directory:
        manifest=snapshot(path,directory)
        def immutable(key,raw):
            budget()
            old,version=remote.get(key)
            if old is not None:
                if old!=raw:raise ValueError('private_original_backup_conflict')
                return
            budget()
            remote.put(key,raw,expected_version=None)
            budget()
            reread,_=remote.get(key)
            if reread!=raw:raise ValueError('private_original_backup_readback')
        for chunk in manifest['chunks']:
            raw=(Path(directory)/chunk['sha256']).read_bytes()
            if _hash(raw)!=chunk['sha256']:raise ValueError('private_original_backup_chunk')
            immutable(PREFIX+'/chunks/'+chunk['sha256']+'.bin',raw)
        encoded=sources._json(manifest).encode();identity=_hash(encoded)
        immutable(PREFIX+'/manifests/'+identity+'.json',encoded)
        # Immutable manifests preserve earlier copies even across interrupted
        # uploads, revisions, or deployment. No moving cursor hides them.
        return {'status':'VERIFIED','manifestSha256':identity,'counts':manifest['counts'],
                'archiveBytes':manifest['archiveBytes'],'privateRepositoryVerified':True,'actionAuthority':False}
