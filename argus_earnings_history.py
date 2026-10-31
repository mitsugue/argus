"""Retain licensed financial inputs in the existing private source store.

No fetch, AI call or warning threshold lives here. Raw financial observations
are local only; this adapter does not export provider data to public history.
"""
import hashlib
import json
import re
import threading
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


# What may differ between two receipts of the same content: the receipt's own
# time, its digest (which binds that time), how many observations were new at
# that moment, and the component proof's time-stamped wrapper of the same rows.
_CODE_RECEIPT_TIMES = frozenset({'receivedAt', 'receiptSha256'})
_DATE_RECEIPT_TIMES = frozenset({'receivedAt', 'knownAt', 'coverageSha256', 'newObservations', 'componentReceipt'})


def _same_receipt(old, new, ignored, db=None):
    """Same original (rawId and its SHA-256) and the same scope and counts.

    With `db`, the stored original's bytes must still hash to that SHA-256;
    otherwise the new receipt is kept, so readers check it against the
    stored bytes as before (a replaced or broken original is still found at
    the next collection, not only at the next restart)."""
    if not isinstance(old, dict) or not old.get('rawId') or old.get('rawId') != new.get('rawId') \
            or old.get('sourceResponseSha256') != new.get('sourceResponseSha256'):
        return False
    strip = lambda row: {k: v for k, v in row.items() if k not in ignored}
    if strip(old) != strip(new):
        return False
    if db is not None:
        stored = db.execute('SELECT raw,sha256 FROM raw_sources WHERE id=?', (new['rawId'],)).fetchone()
        if not stored or stored[1] != new['sourceResponseSha256'] \
                or hashlib.sha256(stored[0]).hexdigest() != stored[1]:
            return False
    return True


def retain(path, rows, *, received_at, member_codes, query_date=None, complete_scope=None, query_code=None, component_receipt=None):
    if component_receipt is not None:
        import argus_earnings_scope as scopes
        scopes.validate(component_receipt, rows)
        if (query_code is not None or query_date != component_receipt['queryDate']
                or sorted(member_codes) != component_receipt['memberCodes']
                or sorted(complete_scope or ()) != component_receipt['memberCodes']
                or received_at != component_receipt['knownAt']):
            raise ValueError('financial_composite_scope_mismatch')
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
                # Owner decision 2026-10-22: the same response received again
                # (same original, scope and counts; only the receipt time
                # differs) is not kept as another revision. The first receipt
                # stays; it is the earlier, still-valid proof.
                same = any(_same_receipt(json.loads(value), receipt_body, _CODE_RECEIPT_TIMES, db)
                           for (value,) in db.execute('SELECT value FROM metadata WHERE key LIKE ?',
                                                      ('financial-summary-code:' + query_code + ':revision:%',)))
                if same:
                    status['unchangedReceipt'] = True
                else:
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
                if component_receipt is not None:
                    if rejected or selected != rows or not complete:
                        raise ValueError('financial_composite_selected_input')
                    status.update(collectionKind='COMPANY_DATE_COMPONENT_SET', componentReceipt=component_receipt)
                status['coverageSha256']=hashlib.sha256(sources._json(status).encode()).hexdigest()
                # Owner decision 2026-10-22: a re-read of the same date with the
                # same original and scope is not another revision (it grew by
                # about 84 a day and every read re-checks each one). The newest
                # stored receipt stays as it is.
                latest_row = db.execute('SELECT value FROM metadata WHERE key=?',
                                        ('financial-summary-date:' + query_date,)).fetchone()
                if latest_row and _same_receipt(json.loads(latest_row[0]), status, _DATE_RECEIPT_TIMES, db):
                    status['unchangedReceipt'] = True
                    return status
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


def retain_composite(path, rows, *, receipt_proof):
    """Store a separately proven component set, never a whole-company receipt.

    Uses only the existing selected-input store and date-coverage metadata.
    The proof has already been built from independently preserved raw pages;
    old observations and original receipt hashes stay immutable.
    """
    return retain(path, rows, received_at=receipt_proof['knownAt'],
                  member_codes=receipt_proof['memberCodes'], query_date=receipt_proof['queryDate'],
                  complete_scope=receipt_proof['memberCodes'], component_receipt=receipt_proof)


def validate_composite_coverage(row, raw):
    """Same validation before read and private snapshot; no HTTP-body claim."""
    if 'collectionKind' not in row and 'componentReceipt' not in row:
        return
    import argus_earnings_scope as scopes
    if row.get('collectionKind') != 'COMPANY_DATE_COMPONENT_SET':
        raise ValueError('financial_composite_scope_mismatch')
    proof = scopes.validate(row.get('componentReceipt'), json.loads(raw)['data'])
    if (row.get('queryDate') != proof['queryDate'] or row.get('memberCodes') != proof['memberCodes']
            or row.get('knownAt') != proof['knownAt'] or row.get('receivedAt') != proof['knownAt']
            or row.get('sourceResponseSha256') != proof['selectedInputSha256']
            or row.get('retainedRows') != proof['retainedRows'] or row.get('complete') is not True
            or row.get('rejectedRows') != 0 or row.get('actionAuthority') is not False):
        raise ValueError('financial_composite_scope_mismatch')


# Owner decision 2026-10-16: an original response is content-addressed and
# never rewritten, so its hash and the presence of each observation in it are
# verified once per process. Every read still runs each observation's own
# checks; a new original or a new observation is always verified against the
# original. Disk damage after a verification is found at the next restart.
_VERIFIED_PRESENT = {}
_VERIFIED_COUNT = [0]
_VERIFIED_LIMIT = 50000
_VERIFIED_LOCK = threading.Lock()


_VERIFIED_RECEIPTS = {}


def _remember_receipt(key, value):
    with _VERIFIED_LOCK:
        if len(_VERIFIED_RECEIPTS) >= _VERIFIED_LIMIT:
            _VERIFIED_RECEIPTS.clear()
        _VERIFIED_RECEIPTS[key] = value


# 2026-10-21: date receipts are remembered by their content. The newest-date
# key always holds the same content as one of its revisions, and both were
# checked against the same original, including the 225-company component
# check (77 KB per receipt). Every new content (each collection adds a
# revision with its own receipt time) is still checked against the bytes of
# its original.
def coverage_content_verified(coverage_sha256):
    """True when a date receipt with exactly this content (its coverageSha256,
    which binds rawId and sourceResponseSha256) passed the original and
    composite checks in this process. The caller must have recomputed the
    digest from the stored receipt and hashed the original's bytes itself."""
    with _VERIFIED_LOCK:
        return _VERIFIED_RECEIPTS.get(('date-content', coverage_sha256)) is True


def remember_coverage_content(coverage_sha256):
    _remember_receipt(('date-content', coverage_sha256), True)


def clear_verified_originals():
    with _VERIFIED_LOCK:
        _VERIFIED_PRESENT.clear()
        _VERIFIED_RECEIPTS.clear()
        _VERIFIED_COUNT[0] = 0


def store_identity(path):
    """Cheap read-only identity of the financial originals (2026-10-16).

    The adopted rules reuse their results while this is unchanged. The file's
    modification time changed with every unrelated source write, so the
    results were recomputed on each read. Counts and the newest sequence of
    the financial observations and receipts change exactly when they do.
    """
    from pathlib import Path
    import sqlite3
    location = Path(path) if path else None
    if location is None or not location.exists():
        return None
    if location.is_symlink() or not location.is_file():
        raise ValueError('financial_store_regular_file_required')
    db = sqlite3.connect(location.resolve().as_uri() + '?mode=ro', uri=True)
    try:
        observations = db.execute(
            "SELECT COUNT(*), MAX(seq) FROM observations "
            "WHERE source_id >= 'financial-summary:' AND source_id < 'financial-summary;'").fetchone()
        receipts = db.execute(
            "SELECT COUNT(*) FROM metadata WHERE key LIKE 'financial-summary-%'").fetchone()
        return [observations[0], observations[1], receipts[0]]
    except sqlite3.OperationalError:
        return ['schema_unavailable']
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
    # 2026-10-16: one original response holds many companies' rows. It was
    # fetched, hashed and parsed again for every observation (28.5 s and
    # +142 MB in production). Observations are now grouped by their original:
    # each original is fetched, hashed and parsed exactly once, one at a time,
    # and every per-observation check is unchanged. Results keep the previous
    # company/sequence order.
    try:
        observations = []
        for position, code in enumerate(sorted(set(member_codes))):
            if not re.fullmatch(r'[0-9A-Z]{4}', code):
                raise ValueError('financial_code_required')
            for seq, raw, raw_id, source_digest, source_time in db.execute(
                'SELECT o.seq,o.body,r.id,r.sha256,r.received_at FROM observations o JOIN raw_sources r ON o.raw_id=r.id '
                'WHERE o.source_id=? ORDER BY o.seq', ('financial-summary:' + code,)):
                observations.append((raw_id, source_digest, position, seq, raw, source_time))
        kept = []
        observations.sort(key=lambda item: (item[0], item[2], item[3]))
        index = 0
        while index < len(observations):
            raw_id, source_digest = observations[index][0], observations[index][1]
            group_end = index
            while group_end < len(observations) and observations[group_end][0] == raw_id:
                group_end += 1
            group = [(item, json.loads(item[4])) for item in observations[index:group_end]]
            index = group_end
            with _VERIFIED_LOCK:
                known = _VERIFIED_PRESENT.get((raw_id, source_digest)) or frozenset()
            source_rows = None
            if any(body.get('observationId') not in known for _, body in group):
                source_raw = db.execute('SELECT raw FROM raw_sources WHERE id=?', (raw_id,)).fetchone()[0]
                if hashlib.sha256(source_raw).hexdigest() != source_digest:
                    raise ValueError('financial_observation_integrity')
                source_rows = json.loads(source_raw)['data']
                del source_raw
            for (_, digest, position, seq, _, source_time), body in group:
                summary = _compact(body['summary'])
                present = (body['observationId'] in known if source_rows is None
                           else summary in source_rows)
                if (digest != source_digest or body['rawId'] != raw_id
                        or raw_id != hashlib.sha256((URL + ':' + source_digest).encode()).hexdigest()
                        or body['sourceResponseSha256'] != source_digest
                        or body['knownAt'] != source_time or body['receivedAt'] != source_time
                        or body['publishedAt'] != (_published(summary).isoformat() if _published(summary) else None)
                        or body['observationId'] != hashlib.sha256(sources._json(summary).encode()).hexdigest()
                        or not present):
                    raise ValueError('financial_observation_integrity')
                if sources._time(body['knownAt']) <= limit and sources._time(body['receivedAt']) <= limit:
                    kept.append((position, seq, body))
                    if len(kept) > MAX_ROWS:
                        raise ValueError('financial_history_bound')
            if source_rows is not None:
                with _VERIFIED_LOCK:
                    present_ids = frozenset(known | {body['observationId'] for _, body in group})
                    previous = _VERIFIED_PRESENT.get((raw_id, source_digest)) or frozenset()
                    if _VERIFIED_COUNT[0] - len(previous) + len(present_ids) > _VERIFIED_LIMIT:
                        _VERIFIED_PRESENT.clear()
                        _VERIFIED_COUNT[0] = 0
                        previous = frozenset()
                    _VERIFIED_PRESENT[(raw_id, source_digest)] = present_ids
                    _VERIFIED_COUNT[0] += len(present_ids) - len(previous)
            del source_rows
        kept.sort(key=lambda item: (item[0], item[1]))
        return [body for _, _, body in kept]
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
    # 同じSQLite読取と呼出しの中だけ、上限付きで原本を共用する。
    from collections import OrderedDict
    source_cache, source_cache_bytes = OrderedDict(), 0
    try:
        for key,raw in db.execute("SELECT key,value FROM metadata WHERE key LIKE 'financial-summary-date:%'"):
            # 2026-10-21: every read parsed, re-serialized and hashed each
            # receipt again (dozens of revisions per date, 77 KB for a
            # component set). The stored text is now hashed on every read
            # instead; a text accepted by the full check below in this
            # process is the same bytes, so the full check would accept it
            # again. Any other text (an edit, a new revision) gets the full
            # check. A receipt is parsed for output only when it becomes the
            # newest one seen for its date.
            row=None
            stored=hashlib.sha256(raw.encode() if isinstance(raw,str) else bytes(raw)).digest()
            with _VERIFIED_LOCK:
                fields=_VERIFIED_RECEIPTS.get(('date-text',stored))
            if fields is None:
                row=json.loads(raw); digest=row.pop('coverageSha256',None)
                if digest is None:
                    _remember_receipt(('date-text',stored),False)
                    continue  # Older receipts did not certify a 225-member scope.
                if hashlib.sha256(sources._json(row).encode()).hexdigest()!=digest:
                    raise ValueError('financial_coverage_integrity')
                # Owner decision 2026-10-16: the original behind a receipt is
                # verified once per process; the receipt's own digest on every
                # read (above, or as the stored text's hash once accepted).
                # 2026-10-21: remembered by the receipt's content (the digest
                # binds rawId and sourceResponseSha256), not by its key.
                if not coverage_content_verified(digest):
                    raw_id=row.get('rawId')
                    source=source_cache.get(raw_id)
                    if source is None:
                        source=db.execute('SELECT raw,sha256 FROM raw_sources WHERE id=?',(raw_id,)).fetchone()
                    else:
                        source_cache.move_to_end(raw_id)
                    if not source or hashlib.sha256(source[0]).hexdigest()!=source[1] or source[1]!=row.get('sourceResponseSha256'):
                        raise ValueError('financial_coverage_integrity')
                    validate_composite_coverage(row, source[0])
                    if raw_id not in source_cache and len(source[0])<=1024*1024:
                        while source_cache and (len(source_cache)>=16 or source_cache_bytes+len(source[0])>1024*1024):
                            source_cache_bytes-=len(source_cache.popitem(last=False)[1][0])
                        source_cache[raw_id]=source
                        source_cache_bytes+=len(source[0])
                    remember_coverage_content(digest)
                fields=(row['receivedAt'],row['knownAt'],row.get('queryDate'))
                _remember_receipt(('date-text',stored),fields)
            elif fields is False:
                continue
            received,known,day=fields
            if sources._time(received)<=limit and sources._time(known)<=limit:
                if not day or key.split(':',2)[1]!=day:
                    raise ValueError('financial_coverage_integrity')
                old=output.get(day)
                if old is None or sources._time(known)>sources._time(old['knownAt']):
                    if row is None:
                        row=json.loads(raw); digest=row.pop('coverageSha256')
                    output[day]={**row,'coverageSha256':digest}
        return output
    finally:db.close()


def completed_codes(path, *, cutoff, member_codes, required_disclosure_days=None):
    """Successful whole-company responses, including empty ones; no inferred date coverage."""
    proofs = read_company_coverage(path, cutoff=cutoff, member_codes=member_codes)
    if required_disclosure_days is None:
        return set(proofs)
    if (not isinstance(required_disclosure_days, (list, tuple, set))
            or len(required_disclosure_days) > 14
            or any(not isinstance(day, str) or date.fromisoformat(day).isoformat() != day
                   for day in required_disclosure_days)):
        raise ValueError('financial_required_disclosure_days_bound')
    required_days = set(required_disclosure_days); latest = {}
    for row in read(path, cutoff=cutoff, member_codes=member_codes):
        s = row['summary']; published = _published(s)
        if s['DiscDate'] not in required_days or published is None or published > sources._time(cutoff):
            continue
        key = (str(s['Code'])[:4], s['DiscDate'], s['DiscNo'])
        if key not in latest or sources._time(row['knownAt']) > sources._time(latest[key]['knownAt']):
            latest[key] = row
    completed = set(proofs)
    for (code, _, _), row in latest.items():
        proof = proofs.get(code)
        if (not proof or row['observationId'] not in proof['observationIds']
                or sources._time(proof['receivedAt']) < sources._time(row['knownAt'])):
            completed.discard(code)
    return completed


def read_company_coverage(path, *, cutoff, member_codes):
    """Verified whole-company receipts; only the available response span is certified."""
    from pathlib import Path
    import sqlite3
    location = Path(path); limit = sources._time(cutoff); members = set(member_codes)
    if len(members) > 400 or any(not re.fullmatch(r'[0-9A-Z]{4}', c) for c in members):
        raise ValueError('financial_member_scope_required')
    if not location.exists(): return {}
    if location.is_symlink() or not location.is_file(): raise ValueError('financial_store_regular_file_required')
    db = sqlite3.connect(location.resolve().as_uri() + '?mode=ro', uri=True)
    output = {}
    try:
        for key, raw in db.execute("SELECT key,value FROM metadata WHERE key LIKE 'financial-summary-code:%'"):
            row = json.loads(raw); digest = row.pop('receiptSha256', None)
            code = row.get('code')
            if code not in members: continue
            if (hashlib.sha256(sources._json(row).encode()).hexdigest() != digest
                    or key != 'financial-summary-code:' + code + ':revision:' + str(digest)):
                raise ValueError('financial_company_receipt_integrity')
            verified_key = ('company', key, digest)
            with _VERIFIED_LOCK:
                cached = _VERIFIED_RECEIPTS.get(verified_key)
            if cached is not None:
                # Verified once per process (owner decision 2026-10-16); the
                # receipt's own digest above is still checked on every read.
                if cached and row.get('complete') is True and sources._time(row['receivedAt']) <= limit:
                    old = output.get(code)
                    if old is None or sources._time(row['receivedAt']) > sources._time(old['receivedAt']):
                        output[code] = {**cached, 'observationIds': list(cached['observationIds'])}
                continue
            source = db.execute('SELECT raw,sha256,received_at,url FROM raw_sources WHERE id=?', (row.get('rawId'),)).fetchone()
            if (not source or hashlib.sha256(source[0]).hexdigest() != source[1]
                    or source[1] != row.get('sourceResponseSha256')
                    or source[3] != URL
                    or row.get('rawId') != hashlib.sha256((URL + ':' + source[1]).encode()).hexdigest()
                    or sources._time(source[2]) > sources._time(row.get('receivedAt'))):
                raise ValueError('financial_company_receipt_integrity')
            evidence = None
            if row.get('complete') is True:
                payload = json.loads(source[0])['data']
                if (not isinstance(payload, list) or len(payload) > MAX_ROWS
                        or row.get('retainedRows') != len(payload)
                        or any(_compact(r)['Code'] != code for r in payload)):
                    raise ValueError('financial_company_receipt_integrity')
                days = [r['DiscDate'] for r in payload]
                evidence = {**row, 'receiptSha256': digest,
                    'firstDisclosureDay': min(days) if days else None,
                    'lastDisclosureDay': max(days) if days else None,
                    'observationIds': [hashlib.sha256(sources._json(r).encode()).hexdigest() for r in payload]}
            _remember_receipt(verified_key, evidence or False)
            if evidence is not None and sources._time(row['receivedAt']) <= limit:
                old = output.get(code)
                if old is None or sources._time(row['receivedAt']) > sources._time(old['receivedAt']):
                    output[code] = evidence
        return output
    finally: db.close()
