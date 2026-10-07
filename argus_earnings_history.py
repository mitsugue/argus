"""Retain licensed financial inputs in the existing private source store.

No fetch, AI call or warning threshold lives here. Raw financial observations
are local only; this adapter does not export provider data to public history.
"""
import hashlib
import json
import re
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import jp_market_acquisition as sources

URL = 'https://api.jquants.com/v2/fins/summary'
FIELDS = ('Code', 'DiscDate', 'DiscTime', 'DiscNo', 'DocType', 'CurPerType',
          'CurPerEn', 'CurFYEn', 'NxtFYEn', 'OP', 'FOP', 'NxFOP', 'NCOP', 'FNCOP', 'NxFNCOP')
MAX_ROWS = 30000


def acquisition_members(current_members, changes, *, through):
    """Collect current/former constituents, without certifying a dated cohort."""
    end = date.fromisoformat(through)
    members = set(current_members)
    if len(members) != 225 or any(not isinstance(c, str) or not re.fullmatch(r'[0-9A-Z]{4}', c) for c in members):
        raise ValueError('financial_member_scope_required')
    if not isinstance(changes, dict) or changes.get('schemaVersion') != 'nikkei225-constituent-changes-v1':
        raise ValueError('financial_membership_history_required')
    rows = changes.get('rows')
    if not isinstance(rows, list) or len(rows) > 400:
        raise ValueError('financial_membership_history_required')
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError('financial_membership_history_required')
        effective = date.fromisoformat(row.get('effective', ''))
        if not date(2016, 10, 3) <= effective <= end:
            continue
        for field in ('removed', 'added'):
            codes = row.get(field)
            if not isinstance(codes, list) or any(not isinstance(c, str) or not re.fullmatch(r'[0-9A-Z]{4}', c) for c in codes):
                raise ValueError('financial_membership_history_required')
            members.update(codes)
    if len(members) > 400:
        raise ValueError('financial_member_scope_required')
    return sorted(members)


def _compact(row):
    if not isinstance(row, dict):
        raise ValueError('financial_row_required')
    code = str(row.get('Code') or '')
    if not re.fullmatch(r'[0-9A-Z]{4}0?', code):
        raise ValueError('financial_code_required')
    day = str(row.get('DiscDate') or '')
    if date.fromisoformat(day).isoformat() != day:
        raise ValueError('financial_date_required')
    body = {key: row[key] for key in FIELDS if key in row}
    if any(type(value) not in (str, int, float, type(None)) or len(str(value)) > 160 for value in body.values()):
        raise ValueError('financial_field_bound')
    body['Code'] = code[:4]
    return body


def _published(row):
    stamp = str(row.get('DiscTime') or '')
    if re.fullmatch(r'\d{2}:\d{2}(?::\d{2})?', stamp):
        return datetime.combine(date.fromisoformat(row['DiscDate']), time.fromisoformat(stamp), ZoneInfo('Asia/Tokyo'))
    # Unknown publication time is not guessed; usable no earlier than receipt.
    return None


def retain(path, rows, *, received_at, member_codes, query_date=None, complete_scope=None, query_code=None):
    receipt = sources._time(received_at)
    if not isinstance(rows, list) or len(rows) > MAX_ROWS:
        raise ValueError('financial_response_bound')
    members = sorted(set(member_codes))
    if not members or len(members) > 400 or any(not re.fullmatch(r'[0-9A-Z]{4}', code) for code in members):
        raise ValueError('financial_member_scope_required')
    if query_code is not None and (query_code not in members or not re.fullmatch(r"[0-9A-Z]{4}", query_code)):
        raise ValueError("financial_query_code_required")
    selected, rejected = [], 0
    for row in rows:
        if not isinstance(row, dict) or str(row.get('Code') or '')[:4] not in members:
            continue
        try:
            compact = _compact(row)
            published = _published(compact)
            if date.fromisoformat(compact['DiscDate']) > receipt.astimezone(ZoneInfo('Asia/Tokyo')).date():
                raise ValueError('financial_future_disclosure')
            if published and published > receipt:
                raise ValueError('financial_future_publication')
            selected.append(compact)
        except (ValueError, TypeError):
            rejected += 1
    encoded = sources._json({'data': selected}).encode()
    if len(encoded) > sources.MAX_BYTES:
        raise ValueError('financial_response_bytes_bound')
    digest = hashlib.sha256(encoded).hexdigest()
    raw_id = hashlib.sha256((URL + ':' + digest).encode()).hexdigest()
    db = sources.connect(path)
    inserted = 0
    try:
        with db:
            db.execute('INSERT OR IGNORE INTO raw_sources VALUES(?,?,?,?,?)', (raw_id, URL, digest, received_at, encoded))
            for row in selected:
                identity = hashlib.sha256(sources._json(row).encode()).hexdigest()
                source_id = 'financial-summary:' + row['Code']
                if db.execute('SELECT 1 FROM observations WHERE source_id=? AND session=?', (source_id, identity)).fetchone():
                    continue
                published = _published(row)
                body = {'summary': row, 'receivedAt': received_at, 'knownAt': received_at,
                        'publishedAt': published.isoformat() if published else None,
                        'historicalVintageVerified': False, 'sourceRef': URL,
                        'sourceResponseSha256': digest, 'rawId': raw_id, 'observationId': identity}
                db.execute('INSERT INTO observations(source_id,session,raw_id,body) VALUES(?,?,?,?)',
                           (source_id, identity, raw_id, sources._json(body)))
                inserted += 1
            status = {'status': 'PARTIAL' if rejected else 'RECEIVED', 'retainedRows': len(selected),
                      'newObservations': inserted, 'rejectedRows': rejected, 'receivedAt': received_at,
                      'memberCount': len(members), 'queryDate': query_date,
                      'goodEarningsRuleDefined': False, 'actionAuthority': False}
            if query_code is not None:
                complete = rejected == 0 and all(isinstance(r, dict) and str(r.get('Code') or '')[:4] == query_code for r in rows)
                receipt_body = {'code': query_code, 'complete': complete, 'receivedAt': received_at,
                                'rawId': raw_id, 'sourceResponseSha256': digest, 'retainedRows': len(selected)}
                receipt_hash = hashlib.sha256(sources._json(receipt_body).encode()).hexdigest()
                receipt_body['receiptSha256'] = receipt_hash
                db.execute('INSERT OR IGNORE INTO metadata VALUES(?,?)',
                           ('financial-summary-code:' + query_code + ':revision:' + receipt_hash, sources._json(receipt_body)))
            if query_date is not None:
                if date.fromisoformat(query_date).isoformat() != query_date:
                    raise ValueError('financial_query_date_required')
                # A complete date query is different from per-company reads.
                scope=sorted(set(complete_scope or ()))
                complete=(len(scope)==225 and set(scope)<=set(members) and rejected==0
                          and all(r['DiscDate']==query_date for r in selected))
                status.update(complete=complete, memberCodes=scope if complete else [],
                              knownAt=received_at, rawId=raw_id, sourceResponseSha256=digest)
                status['coverageSha256']=hashlib.sha256(sources._json(status).encode()).hexdigest()
                # Keep each corrected coverage receipt, not just the newest
                # cursor. An old cutoff must still recover its earlier scope.
                db.execute('INSERT OR IGNORE INTO metadata VALUES(?,?)',
                           ('financial-summary-date:' + query_date + ':revision:' + status['coverageSha256'],
                            sources._json(status)))
                # Empty successful date responses are distinct from failed reads.
                db.execute('INSERT OR REPLACE INTO metadata VALUES(?,?)',
                           ('financial-summary-date:' + query_date, sources._json(status)))
        return status
    finally:
        db.close()


def read(path, *, cutoff, member_codes):
    """Read-only, original receipts preserved; does not create missing stores."""
    from pathlib import Path
    import sqlite3
    limit = sources._time(cutoff)
    location = Path(path)
    if not location.exists():
        return []
    if location.is_symlink() or not location.is_file():
        raise ValueError('financial_store_regular_file_required')
    db = sqlite3.connect(location.resolve().as_uri() + '?mode=ro', uri=True)
    result = []
    try:
        for code in sorted(set(member_codes)):
            if not re.fullmatch(r'[0-9A-Z]{4}', code):
                raise ValueError('financial_code_required')
            for raw, source_raw, raw_id, source_digest, source_time in db.execute(
                'SELECT o.body,r.raw,r.id,r.sha256,r.received_at FROM observations o JOIN raw_sources r ON o.raw_id=r.id '
                'WHERE o.source_id=? ORDER BY o.seq', ('financial-summary:' + code,)):
                body = json.loads(raw)
                summary = _compact(body['summary'])
                if (hashlib.sha256(source_raw).hexdigest() != source_digest or body['rawId'] != raw_id
                        or raw_id != hashlib.sha256((URL + ':' + source_digest).encode()).hexdigest()
                        or body['sourceResponseSha256'] != source_digest
                        or body['knownAt'] != source_time or body['receivedAt'] != source_time
                        or body['publishedAt'] != (_published(summary).isoformat() if _published(summary) else None)
                        or body['observationId'] != hashlib.sha256(sources._json(summary).encode()).hexdigest()
                        or summary not in json.loads(source_raw)['data']):
                    raise ValueError('financial_observation_integrity')
                if sources._time(body['knownAt']) <= limit and sources._time(body['receivedAt']) <= limit:
                    result.append(body)
                if len(result) > MAX_ROWS:
                    raise ValueError('financial_history_bound')
        return result
    finally:
        db.close()


def read_coverage(path, *, cutoff):
    from pathlib import Path
    import sqlite3
    location=Path(path); limit=sources._time(cutoff)
    if not location.exists():return {}
    if location.is_symlink() or not location.is_file():raise ValueError('financial_store_regular_file_required')
    db=sqlite3.connect(location.resolve().as_uri()+'?mode=ro',uri=True)
    output={}
    try:
        for key,raw in db.execute("SELECT key,value FROM metadata WHERE key LIKE 'financial-summary-date:%'"):
            row=json.loads(raw); digest=row.pop('coverageSha256',None)
            if digest is None:continue  # Older receipts did not certify a 225-member scope.
            if hashlib.sha256(sources._json(row).encode()).hexdigest()!=digest:
                raise ValueError('financial_coverage_integrity')
            source=db.execute('SELECT raw,sha256 FROM raw_sources WHERE id=?',(row.get('rawId'),)).fetchone()
            if not source or hashlib.sha256(source[0]).hexdigest()!=source[1] or source[1]!=row.get('sourceResponseSha256'):
                raise ValueError('financial_coverage_integrity')
            if sources._time(row['receivedAt'])<=limit and sources._time(row['knownAt'])<=limit:
                day=row.get('queryDate')
                if not day or key.split(':',2)[1]!=day:
                    raise ValueError('financial_coverage_integrity')
                old=output.get(day)
                if old is None or sources._time(row['knownAt'])>sources._time(old['knownAt']):
                    output[day]={**row,'coverageSha256':digest}
        return output
    finally:db.close()


def completed_codes(path, *, cutoff, member_codes):
    """Successful whole-company responses, including empty ones; no inferred date coverage."""
    from pathlib import Path
    import sqlite3
    location = Path(path); limit = sources._time(cutoff); members = set(member_codes)
    if len(members) > 400 or any(not re.fullmatch(r'[0-9A-Z]{4}', c) for c in members):
        raise ValueError('financial_member_scope_required')
    if not location.exists(): return set()
    if location.is_symlink() or not location.is_file(): raise ValueError('financial_store_regular_file_required')
    db = sqlite3.connect(location.resolve().as_uri() + '?mode=ro', uri=True)
    output = set()
    try:
        for key, raw in db.execute("SELECT key,value FROM metadata WHERE key LIKE 'financial-summary-code:%'"):
            row = json.loads(raw); digest = row.pop('receiptSha256', None)
            code = row.get('code')
            if code not in members: continue
            if (hashlib.sha256(sources._json(row).encode()).hexdigest() != digest
                    or key != 'financial-summary-code:' + code + ':revision:' + str(digest)):
                raise ValueError('financial_company_receipt_integrity')
            source = db.execute('SELECT raw,sha256,received_at FROM raw_sources WHERE id=?', (row.get('rawId'),)).fetchone()
            if (not source or hashlib.sha256(source[0]).hexdigest() != source[1]
                    or source[1] != row.get('sourceResponseSha256')
                    or sources._time(source[2]) > sources._time(row.get('receivedAt'))):
                raise ValueError('financial_company_receipt_integrity')
            if row.get('complete') is True and sources._time(row['receivedAt']) <= limit:
                output.add(code)
        return output
    finally: db.close()
