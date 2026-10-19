"""Whitelist-only market originals in the existing source store/private backup.

No owner registry, credentials, HTTP headers or runtime response is exported.
Source receipts and revisions are immutable; this is a backup adapter, not a
second collection lane or a claim of historical publication vintage.
"""
import base64
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
import tempfile
import time

import argus_earnings_history as earnings
import jp_market_acquisition as sources
import argus_credit_conditions as credit
import argus_jgb_auction as auctions
from argus_analysis_history_backup import CHUNK_BYTES, MAX_ARCHIVE_BYTES, MAX_SYNC_SECONDS

PRIVATE_REPO='mitsugue/argus-l2b-private'
PREFIX='market-analysis/source-inputs/v1'
SCHEMA='argus-private-market-inputs-v1'
SECTOR_CODES={str(n) for n in range(1617,1634)}
DIAGNOSTIC_PHASES={'CONFIGURATION','VISIBILITY','SNAPSHOT','SNAPSHOT_ORIGINALS',
                   'SNAPSHOT_OBSERVATIONS','SNAPSHOT_DATE_COVERAGE','SNAPSHOT_SELECTED',
                   'SNAPSHOT_COMPANY_COVERAGE','SNAPSHOT_CHUNKS','CHUNK_READ','CHUNK_WRITE',
                   'CHUNK_READBACK','MANIFEST_READ','MANIFEST_WRITE','MANIFEST_READBACK','COMPLETE'}
DIAGNOSTIC_ERRORS={'private_original_backup_destination','private_selected_integrity','private_original_backup_visibility',
    'private_original_backup_deadline','private_original_backup_conflict',
    'private_original_backup_readback','private_original_backup_chunk',
    'private_original_backup_bound','private_original_integrity','private_observation_fields',
    'private_observation_integrity','private_coverage_fields','private_coverage_integrity',
    'private_company_receipt_fields','private_company_receipt_integrity',
    'history_remote_read_unavailable','history_remote_write_conflict_or_unavailable',
    'history_remote_deadline_exceeded','history_remote_response_bound',
    'history_remote_object_invalid','history_remote_content_bound',
    'history_remote_blob_integrity_invalid','history_remote_write_bound'}


def diagnostic_error(exc):
    # Only exact protocol constants may escape; exceptions can contain inputs.
    text=str(exc)
    return text if text in DIAGNOSTIC_ERRORS else 'UNCLASSIFIED'


def status_projection(state, *, worker_active=False):
    """Owner diagnostic scalars; never serializes arbitrary status/input fields."""
    state=dict(state)
    out={'status':state.get('status') if state.get('status') in
         {'NOT_RUN','RUNNING','VERIFIED','FAILED','NOT_CONFIGURED'} else 'UNKNOWN',
         'workerActive':worker_active is True}
    if state.get('phase') in DIAGNOSTIC_PHASES:out['phase']=state['phase']
    for key in ('lastAttemptAt','finishedAt','verifiedAt'):
        value=state.get(key)
        if not isinstance(value,str) or len(value)>40:continue
        try:sources._time(value)
        except (ValueError,TypeError):continue
        out['lastVerifiedAt' if key=='verifiedAt' else key]=value
    if state.get('errorCategory') in DIAGNOSTIC_ERRORS|{'UNCLASSIFIED'}:
        out['errorCategory']=state['errorCategory']
    if state.get('errorClass') in {'ValueError','TimeoutError','OSError','RuntimeError',
            'ConnectionError','ReadTimeout','ConnectTimeout','HTTPError','WorkerStartFailed'}:
        out['errorClass']=state['errorClass']
    for key in ('chunksTotal','chunksProcessed','archiveBytes'):
        value=state.get(key)
        if type(value) is int and 0<=value<=MAX_ARCHIVE_BYTES:out[key]=value
    for key in ('elapsedSeconds','phaseElapsedSeconds','workerCpuSeconds'):
        value=state.get(key)
        if type(value) in (int,float) and 0<=value<=10000000 and math.isfinite(value):
            out[key]=value
    if isinstance(state.get('phaseSeconds'),dict):
        out['phaseSeconds']={key:value for key,value in state['phaseSeconds'].items()
            if key in DIAGNOSTIC_PHASES and type(value) in (int,float)
            and 0<=value<=10000000 and math.isfinite(value)}
    if isinstance(state.get('counts'),dict):
        out['counts']={k:v for k,v in state['counts'].items() if k in
            {'financial','sector17','creditConditions','jgbArchive','observations','coverageReceipts'}
            and type(v) is int and 0<=v<=10000000}
    if out['status']=='VERIFIED' and re.fullmatch(r'[0-9a-f]{64}',str(state.get('manifestSha256',''))):
        out['manifestSha256']=state['manifestSha256']
    return out
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


def retain_jgb_archive(path,raw,*,received_at):
    """The official auction-history workbook as received (2026-10-18, owner approved).

    Kept once per distinct content in the existing source store, so the private
    backup can read the original back; the ledger rows stay the authority."""
    rows=auctions.parse_archive(raw,acquired_at=received_at)
    digest=_hash(raw);raw_id=_hash((auctions.ARCHIVE_URL+':'+digest).encode())
    db=sources.connect(path)
    try:
        with db:
            db.execute('INSERT OR IGNORE INTO raw_sources VALUES(?,?,?,?,?)',(raw_id,auctions.ARCHIVE_URL,digest,received_at,raw))
    finally:db.close()
    return {'status':'RETAINED','sourceResponseSha256':digest,'rows':len(rows),'receivedAt':received_at}


def _validate_original(url,raw):
    if credit.approved_url(url):
        credit.validate_original(url,raw)
    elif url==earnings.URL:
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


def snapshot(path,directory,*,check_budget=None,progress=None):
    # The same operation deadline also covers local validation and chunking.
    # Callbacks do not change the archive's ordering, bytes or admission rules.
    def check():
        if check_budget is not None:check_budget()
    def stage(phase):
        check()
        if progress is not None:
            try:progress(phase)
            except Exception:pass
    check()
    location=Path(path)
    if location.is_symlink() or not location.is_file():raise ValueError('private_original_store_required')
    db=sqlite3.connect(location.resolve().as_uri()+'?mode=ro',uri=True)
    # 2026-10-20: every snapshot re-uploaded all 86 chunks (44.6 MB): originals
    # were ordered by their hash, so one new original shifted every later byte,
    # and one stream was cut into chunks end to end (740 MB of chunks in the
    # private repository). Rows are now in insertion order and each section is
    # its own chunk stream, so a new row changes only its section's last chunk.
    # The concatenated chunks are still the one archive, in the same format.
    sections=[];ids=set();counts={'financial':0,'sector17':0,'observations':0,'coverageReceipts':0,
                                  'selectedVix':0,'selectedFeatures':0}
    total_bytes=[0]
    current=[None]
    def section(name):
        if current[0] is not None:current[0].close()
        location=Path(directory)/('section-%02d-%s.ndjson'%(len(sections),name))
        sections.append(location);current[0]=location.open('wb')
    try:
        db.execute('BEGIN')
        try:
            def write(row):
                check()
                encoded=sources._json(row).encode()+b'\n'
                current[0].write(encoded);total_bytes[0]+=len(encoded)
                if total_bytes[0]>MAX_ARCHIVE_BYTES:raise ValueError('private_original_backup_bound')
            section('header')
            write({'schemaVersion':SCHEMA,'scope':'PUBLIC_MARKET_INPUTS','ownerRecordsIncluded':False})
            stage('SNAPSHOT_ORIGINALS')
            section('originals')
            for identity,url,digest,received,raw in db.execute('SELECT id,url,sha256,received_at,raw FROM raw_sources ORDER BY rowid'):
                check()
                if url!=earnings.URL and url!=auctions.ARCHIVE_URL and not credit.approved_url(url) and not re.fullmatch(r'https://api\.jquants\.com/v2/equities/bars/daily\?code=16(?:1[7-9]|2[0-9]|3[0-3])',url):continue
                bound=credit.MAX_BYTES if credit.approved_url(url) else sources.MAX_BYTES
                if len(raw)>bound or _hash(raw)!=digest or identity!=_hash((url+':'+digest).encode()):
                    raise ValueError('private_original_integrity')
                if url==auctions.ARCHIVE_URL:auctions.parse_archive(raw,acquired_at=received)
                else:_validate_original(url,raw)
                sources._time(received);ids.add(identity)
                write({'kind':'raw','id':identity,'url':url,'sha256':digest,'receivedAt':received,'dataBase64':base64.b64encode(raw).decode()})
                kind=('creditConditions' if credit.approved_url(url) else 'financial' if url==earnings.URL
                      else 'jgbArchive' if url==auctions.ARCHIVE_URL else 'sector17')
                counts[kind]=counts.get(kind,0)+1
            stage('SNAPSHOT_OBSERVATIONS')
            section('observations')
            # The read transaction fixes every source version for this export.
            # Keep only the immediately preceding original: adjacent rows from
            # one receipt must not repeatedly query and decode its full body.
            # Do not accumulate all originals or carry this cache to another
            # snapshot. Membership below remains exact dictionary equality.
            cached_original_key=None;cached_original=None;cached_financial_rows=None
            for source_id,session,raw_id,body in db.execute('SELECT source_id,session,raw_id,body FROM observations ORDER BY seq'):
                check()
                if raw_id in ids and source_id.startswith('credit-conditions:'):
                    row=json.loads(body)
                    if cached_original_key!=('credit',raw_id):
                        cached_original=db.execute('SELECT url,raw,received_at FROM raw_sources WHERE id=?',(raw_id,)).fetchone()
                        cached_original_key=('credit',raw_id);cached_financial_rows=None
                        check()
                    original=cached_original
                    credit.verify_observation(row,original[1],url=original[0],first_received=original[2])
                    if source_id!='credit-conditions:'+row['sourceId'] or session!=row['metric']+':'+str(row['observationPeriod'] or row['sourceUrl']):
                        raise ValueError('private_credit_source_binding')
                    write({'kind':'observation','sourceId':source_id,'session':session,'rawId':raw_id,'body':row})
                    counts['observations']+=1
                    continue
                if raw_id not in ids or not re.fullmatch(r'financial-summary:[0-9A-Z]{4}',source_id):continue
                row=json.loads(body)
                allowed={'summary','receivedAt','knownAt','publishedAt','historicalVintageVerified','sourceRef','sourceResponseSha256','rawId','observationId'}
                if set(row)-allowed or set(row.get('summary') or {})-set(earnings.FIELDS):raise ValueError('private_observation_fields')
                summary=earnings._compact(row['summary'])
                if cached_original_key!=('financial',raw_id):
                    cached_original=db.execute('SELECT raw,sha256,received_at FROM raw_sources WHERE id=?',(raw_id,)).fetchone()
                    cached_financial_rows=json.loads(cached_original[0])['data'] if cached_original else None
                    cached_original_key=('financial',raw_id)
                    check()
                original=cached_original
                published=earnings._published(summary)
                if (not original or row.get('rawId')!=raw_id or row.get('sourceResponseSha256')!=original[1]
                        or row.get('sourceRef')!=earnings.URL or row.get('knownAt')!=original[2]
                        or row.get('receivedAt')!=original[2]
                        or row.get('publishedAt')!=(published.isoformat() if published else None)
                        or row.get('observationId')!=session or session!=_hash(sources._json(summary).encode())
                        or summary not in cached_financial_rows):
                    raise ValueError('private_observation_integrity')
                write({'kind':'observation','sourceId':source_id,'session':session,'rawId':raw_id,'body':row});counts['observations']+=1
            cached_original_key=None;cached_original=None;cached_financial_rows=None
            coverage_allowed={'status','retainedRows','newObservations','rejectedRows','receivedAt','memberCount','queryDate','goodEarningsRuleDefined','actionAuthority','complete','memberCodes','knownAt','rawId','sourceResponseSha256','coverageSha256','collectionKind','componentReceipt'}
            stage('SNAPSHOT_DATE_COVERAGE')
            section('date-coverage')
            for key,body in db.execute("SELECT key,value FROM metadata WHERE key LIKE 'financial-summary-date:%' ORDER BY rowid"):
                check()
                row=json.loads(body)
                if row.get('rawId') not in ids:continue
                if set(row)-coverage_allowed:raise ValueError('private_coverage_fields')
                checksum=row.pop('coverageSha256',None)
                if checksum and _hash(sources._json(row).encode())!=checksum:raise ValueError('private_coverage_integrity')
                if checksum:row['coverageSha256']=checksum
                if any(not re.fullmatch(r'[0-9A-Z]{4}',c) for c in row.get('memberCodes',[])):raise ValueError('private_coverage_fields')
                source=db.execute('SELECT sha256,raw FROM raw_sources WHERE id=?',(row['rawId'],)).fetchone()
                if not source or row.get('sourceResponseSha256')!=source[0]:raise ValueError('private_coverage_integrity')
                earnings.validate_composite_coverage(row, source[1])
                sources._time(row['knownAt']);sources._time(row['receivedAt'])
                write({'kind':'coverage','key':key,'body':row});counts['coverageReceipts']+=1
            company_allowed={'code','complete','receivedAt','rawId','sourceResponseSha256','retainedRows','receiptSha256'}
            stage('SNAPSHOT_COMPANY_COVERAGE')
            section('company-coverage')
            for key,body in db.execute("SELECT key,value FROM metadata WHERE key LIKE 'financial-summary-code:%' ORDER BY rowid"):
                check()
                row=json.loads(body)
                if set(row)-company_allowed:raise ValueError('private_company_receipt_fields')
                checksum=row.pop('receiptSha256',None);code=row.get('code')
                if (not isinstance(code,str) or not re.fullmatch(r'[0-9A-Z]{4}',code)
                        or checksum!=_hash(sources._json(row).encode())
                        or key!='financial-summary-code:'+code+':revision:'+str(checksum)
                        or type(row.get('complete')) is not bool
                        or type(row.get('retainedRows')) is not int):
                    raise ValueError('private_company_receipt_integrity')
                original=db.execute('SELECT raw,url,sha256,received_at FROM raw_sources WHERE id=?',(row.get('rawId'),)).fetchone()
                if (not original or row.get('rawId') not in ids or original[1]!=earnings.URL
                        or row.get('sourceResponseSha256')!=original[2]
                        or sources._time(original[3])>sources._time(row['receivedAt'])):
                    raise ValueError('private_company_receipt_integrity')
                payload=json.loads(original[0])['data']
                if (row['retainedRows']!=len(payload)
                        or (row['complete'] and any(r.get('Code')!=code for r in payload))):
                    raise ValueError('private_company_receipt_integrity')
                write({'kind':'coverage','key':key,'body':{**row,'receiptSha256':checksum}})
                counts['coverageReceipts']+=1
            # 2026-10-20 (owner decision): the per-date selections of the VIX/JGB
            # inputs and the first receipts of TOPIX, US 10y and USD/JPY. Their
            # public originals can be fetched again; when each was first
            # received cannot, so these small tables are kept here.
            stage('SNAPSHOT_SELECTED')
            section('selected')
            tables={name for (name,) in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if 'selected_vix_inputs' in tables:
                for session,body,digest,received in db.execute(
                        'SELECT session,body,sha256,received_at FROM selected_vix_inputs ORDER BY seq'):
                    check()
                    if _hash(body.encode())!=digest or json.loads(body).get('date')!=session:
                        raise ValueError('private_selected_integrity')
                    sources._time(received)
                    write({'kind':'selectedVix','session':session,'sha256':digest,'receivedAt':received,'body':json.loads(body)})
                    counts['selectedVix']+=1
            if 'selected_feature_inputs' in tables:
                for source_id,session,body,digest,received in db.execute(
                        'SELECT source_id,session,body,sha256,received_at FROM selected_feature_inputs ORDER BY seq'):
                    check()
                    if (_hash(body.encode())!=digest or json.loads(body).get('date')!=session
                            or source_id not in sources.STABLE_FEATURE_SOURCES):
                        raise ValueError('private_selected_integrity')
                    sources._time(received)
                    write({'kind':'selectedFeature','sourceId':source_id,'session':session,'sha256':digest,
                           'receivedAt':received,'body':json.loads(body)})
                    counts['selectedFeatures']+=1
        finally:
            if current[0] is not None:current[0].close()
        check()
        db.execute('COMMIT')
    finally:db.close()
    stage('SNAPSHOT_CHUNKS')
    chunks=[];total=0;digest=hashlib.sha256()
    # The whole archive is still written as one file: the sections in order.
    with (Path(directory)/'inputs.ndjson').open('wb') as whole:
        for location in sections:
            with location.open('rb') as handle:
                while raw:=handle.read(CHUNK_BYTES):
                    check()
                    whole.write(raw)
                    checksum=_hash(raw);(Path(directory)/checksum).write_bytes(raw);digest.update(raw);total+=len(raw)
                    chunks.append({'sha256':checksum,'bytes':len(raw)})
    check()
    return {'schemaVersion':SCHEMA,'scope':'PUBLIC_MARKET_INPUTS','ownerRecordsIncluded':False,
            'credentialsIncluded':False,'originalArchiveSha256':digest.hexdigest(),'archiveBytes':total,
            'chunks':chunks,'counts':counts,'actionAuthority':False}


def synchronize(path,remote,*,progress=None):
    # Reuse the existing configured Contents connection, but require exactly
    # the owner-approved private repository before the first outbound body.
    started=time.monotonic()
    cpu_started=time.thread_time() if progress is not None else 0
    phase_started=started;current_phase=None;phase_seconds={}
    def report(phase,**scalars):
        nonlocal phase_started,current_phase
        if progress is not None:
            now=time.monotonic()
            if phase!=current_phase:
                if current_phase is not None:
                    phase_seconds[current_phase]=phase_seconds.get(current_phase,0)+now-phase_started
                phase_started=now;current_phase=phase
            try:progress({'phase':phase,**scalars,'elapsedSeconds':round(now-started,6),
                'phaseElapsedSeconds':round(now-phase_started,6),
                'phaseSeconds':{**{key:round(value,6) for key,value in phase_seconds.items()},
                    phase:round(phase_seconds.get(phase,0)+now-phase_started,6)},
                'workerCpuSeconds':round(time.thread_time()-cpu_started,6)})
            except Exception:pass  # Diagnostic delivery cannot change backup admission.
    def budget():
        if time.monotonic()-started>=MAX_SYNC_SECONDS:
            if current_phase is not None:report(current_phase)
            raise ValueError('private_original_backup_deadline')
    try:
        expected='https://api.github.com/repos/'+PRIVATE_REPO+'/contents/'
        if getattr(remote,'base',None)!=expected:raise ValueError('private_original_backup_destination')
        budget()
        report('VISIBILITY')
        repo=remote._read_json(expected.removesuffix('/contents/'))
        budget()
        if not isinstance(repo,dict) or repo.get('private') is not True:
            raise ValueError('private_original_backup_visibility')
        with tempfile.TemporaryDirectory(prefix='argus-market-input-backup-') as directory:
            report('SNAPSHOT')
            manifest=snapshot(path,directory,check_budget=budget,progress=report)
            report('SNAPSHOT_CHUNKS',counts=manifest['counts'],archiveBytes=manifest['archiveBytes'],
                   chunksTotal=len(manifest['chunks']),chunksProcessed=0)
            def immutable(key,raw,kind):
                budget()
                report(kind+'_READ')
                old,version=remote.get(key)
                budget()
                if old is not None:
                    if old!=raw:raise ValueError('private_original_backup_conflict')
                    return
                budget()
                report(kind+'_WRITE')
                remote.put(key,raw,expected_version=None)
                budget()
                report(kind+'_READBACK')
                reread,_=remote.get(key)
                budget()
                if reread!=raw:raise ValueError('private_original_backup_readback')
            for index,chunk in enumerate(manifest['chunks']):
                raw=(Path(directory)/chunk['sha256']).read_bytes()
                if _hash(raw)!=chunk['sha256']:raise ValueError('private_original_backup_chunk')
                immutable(PREFIX+'/chunks/'+chunk['sha256']+'.bin',raw,'CHUNK')
                report('CHUNK_READBACK',chunksProcessed=index+1)
            encoded=sources._json(manifest).encode();identity=_hash(encoded)
            immutable(PREFIX+'/manifests/'+identity+'.json',encoded,'MANIFEST')
            report('COMPLETE')
            # Immutable manifests preserve earlier copies even across interrupted
            # uploads, revisions, or deployment. No moving cursor hides them.
            return {'status':'VERIFIED','manifestSha256':identity,'counts':manifest['counts'],
                    'archiveBytes':manifest['archiveBytes'],'privateRepositoryVerified':True,'actionAuthority':False}
    except Exception:
        if current_phase is not None:report(current_phase)
        raise
