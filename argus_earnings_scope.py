"""Verify explicit company/date component scope. No fetch or store write.

Caller supplies the independently checked company/date request records and raw
bytes. Empty responses alone do not prove their request parameters. Membership
is explicitly reconstructed; this does not certify historical receipt timing.
"""
import hashlib
import json
import math
import re
from datetime import date, datetime
from zoneinfo import ZoneInfo


FIELDS = ('Code', 'DiscDate', 'DiscTime', 'DiscNo', 'DocType', 'CurPerType',
          'CurPerEn', 'CurFYEn', 'NxtFYEn', 'OP', 'FOP', 'NxFOP', 'NCOP', 'FNCOP', 'NxFNCOP')


class ScopeError(ValueError):
    pass


def require(value, category):
    if not value:
        raise ScopeError(category)


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def stamp(value):
    require(isinstance(value, str), 'TIMESTAMP_REQUIRED')
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise ScopeError('TIMESTAMP_REQUIRED') from None
    require(parsed.tzinfo is not None and parsed.utcoffset() is not None, 'TIMESTAMP_ZONE_REQUIRED')
    return parsed


def numeric(value, maximum):
    return type(value) in (int, float) and math.isfinite(value) and 0 <= value <= maximum


def admit(*, day, member_codes, membership_sha256, request_record_sha256, components, cutoff):
    """Build a separately named scope envelope, preserving actual receipt times.

    Each component = {queryKind, receipt, rawPages, normalizedBytes}.
    The resulting hash binds empty component receipts as well as selected rows.
    Actual availability is the last page receipt, never the historical date.
    """
    require(type(day) is str and date.fromisoformat(day).isoformat() == day, 'DATE_REQUIRED')
    require(isinstance(member_codes, list) and len(member_codes) == 225
            and all(type(c) is str and re.fullmatch('[0-9A-Z]{4}', c) for c in member_codes)
            and len(set(member_codes)) == 225, 'EXACT_225_MEMBERS_REQUIRED')
    for value in (membership_sha256, request_record_sha256):
        require(type(value) is str and re.fullmatch('[0-9a-f]{64}', value), 'INPUT_BINDING_REQUIRED')
    require(isinstance(components, list) and len(components) == 225, 'ALL_COMPONENTS_REQUIRED')
    require(all(isinstance(c, dict) and isinstance(c.get('receipt'), dict) for c in components), 'COMPONENT_REQUIRED')
    records = sorted([c['receipt'] for c in components], key=lambda rec: str(rec.get('code', '')))
    require(digest(records) == request_record_sha256, 'REQUEST_RECORD_BINDING_MISMATCH')
    limit = stamp(cutoff)
    seen, identities, selected, proof, receipts = set(), set(), [], [], []
    for component in components:
        require(isinstance(component, dict) and component.get('queryKind') == 'COMPANY_AND_DATE', 'QUERY_KIND_REQUIRED')
        rec = component.get('receipt')
        require(isinstance(rec, dict) and rec.get('complete') is True
                and not rec.get('fixedErrorCategory'), 'COMPONENT_INCOMPLETE')
        code = rec.get('code')
        require(code in member_codes and code not in seen and rec.get('queryDate') == day, 'COMPONENT_SCOPE_MISMATCH')
        seen.add(code)
        pages, raws = rec.get('pages'), component.get('rawPages')
        require(isinstance(pages, list) and isinstance(raws, list)
                and 1 <= len(pages) <= 3 and len(raws) == len(pages), 'PAGE_BOUND_OR_MISSING')
        prior_cursor, expected_cursor, prior_time, joined, page_proofs = set(), None, None, [], []
        for index, (page, raw) in enumerate(zip(pages, raws)):
            require(isinstance(page, dict) and page.get('http') == 200 and not page.get('errorClass'), 'PAGE_NOT_SUCCESSFUL')
            # Older single-page records need no continuation token. A multi-page
            # receipt needs an explicit recorded request token; order alone is
            # insufficient to prove which continuation was requested.
            require(page.get('requestPaginationKey') == expected_cursor, 'REQUEST_PAGE_LINK_REQUIRED')
            require(type(raw) is bytes and 0 < len(raw) <= 2097152
                    and type(page.get('bytes')) is int and page['bytes'] == len(raw)
                    and type(page.get('decodedBytesObserved')) is int and page['decodedBytesObserved'] == len(raw), 'PAGE_BYTES_BOUND')
            raw_hash = hashlib.sha256(raw).hexdigest()
            require(page.get('sha256') == raw_hash, 'RAW_HASH_MISMATCH')
            require(numeric(page.get('elapsedSeconds'), 20), 'PAGE_TIME_BOUND')
            requested, received = stamp(page.get('requestedAt')), stamp(page.get('receivedAt'))
            require(requested <= received <= limit and (received-requested).total_seconds() <= 20
                    and (prior_time is None or prior_time <= requested), 'PAGE_RECEIPT_TIME')
            require(date.fromisoformat(day) <= received.astimezone(ZoneInfo('Asia/Tokyo')).date(), 'FUTURE_DISCLOSURE')
            prior_time = received
            receipts.append(received)
            try:
                payload = json.loads(raw)
            except (ValueError, UnicodeError):
                raise ScopeError('RAW_JSON_REQUIRED') from None
            require(isinstance(payload, dict) and isinstance(payload.get('data'), list)
                    and len(payload['data']) <= 10000, 'RAW_ROWS_BOUND')
            for row in payload['data']:
                require(isinstance(row, dict), 'ROW_REQUIRED')
                raw_code = row.get('Code')
                require(type(raw_code) is str and re.fullmatch('[0-9A-Z]{4}0?', raw_code)
                        and raw_code[:4] == code and row.get('DiscDate') == day, 'ROW_SCOPE_MISMATCH')
                require(type(row.get('DiscNo')) is str and row['DiscNo'], 'DISCLOSURE_ID_REQUIRED')
                identity = code, day, row['DiscNo']
                require(identity not in identities, 'DUPLICATE_DISCLOSURE')
                identities.add(identity)
                compact = {k: row[k] for k in FIELDS if k in row}
                require(all(type(v) in (str, int, float, type(None)) and len(str(v)) <= 160
                            and (type(v) is not float or math.isfinite(v)) for v in compact.values()), 'FIELD_BOUND')
                compact['Code'] = code
                clock = compact.get('DiscTime')
                if isinstance(clock, str) and re.fullmatch(r'\d{2}:\d{2}(?::\d{2})?', clock):
                    try:
                        published = datetime.fromisoformat(day+'T'+clock).replace(tzinfo=ZoneInfo('Asia/Tokyo'))
                    except ValueError:
                        raise ScopeError('PUBLICATION_TIME_INVALID') from None
                    require(published <= received, 'FUTURE_PUBLICATION')
                selected.append(compact)
                joined.append(row)
                require(len(selected) <= 30000, 'SELECTED_ROWS_BOUND')
            cursor = payload.get('pagination_key')
            if index + 1 < len(pages):
                require(type(cursor) is str and 0 < len(cursor) <= 2048 and cursor not in prior_cursor, 'PAGE_CHAIN_INCOMPLETE')
                prior_cursor.add(cursor)
                expected_cursor = cursor
            else:
                require(not cursor, 'PAGE_CHAIN_INCOMPLETE')
            page_proofs.append({'sha256': raw_hash, 'bytes': len(raw), 'http': 200,
                                'requestedAt': page['requestedAt'], 'receivedAt': page['receivedAt']})
        # Normalized input hash is a different hash domain from a raw HTTP body.
        require(type(rec.get('rows')) is int and rec['rows'] == len(joined), 'ROW_COUNT_MISMATCH')
        require(type(rec.get('cacheSha256')) is str and re.fullmatch('[0-9a-f]{64}', rec['cacheSha256']), 'CACHE_BINDING_REQUIRED')
        normal = component.get('normalizedBytes')
        require(type(normal) is bytes and len(normal) <= 2097152 * 3
                and hashlib.sha256(normal).hexdigest() == rec['cacheSha256'], 'CACHE_HASH_MISMATCH')
        try:
            normalized_rows = json.loads(normal)
        except (ValueError, UnicodeError):
            raise ScopeError('CACHE_JSON_REQUIRED') from None
        require(normalized_rows == joined, 'CACHE_ROWS_MISMATCH')
        compact_rows = [r for r in selected if r['Code'] == code]
        compact_rows.sort(key=lambda row: (row['Code'], row['DiscDate'], row['DiscNo']))
        proof.append({'code': code, 'queryDate': day, 'queryKind': 'COMPANY_AND_DATE',
                      'rows': len(joined), 'pages': page_proofs, 'cacheSha256': rec['cacheSha256'],
                      'canonicalRowsSha256': digest(joined), 'selectedRowsSha256': digest(compact_rows), 'complete': True})
    require(seen == set(member_codes), 'EXACT_COMPONENT_SET_REQUIRED')
    selected.sort(key=lambda row: (row['Code'], row['DiscDate'], row['DiscNo']))
    require(len(canonical({'data': selected})) <= 524288, 'SELECTED_BYTES_BOUND')
    envelope = {'schemaVersion': 'financial-company-date-composite-scope-v1',
                'scopeKind': 'RECONSTRUCTED_225_COMPANY_DATE_COMPONENT_SET',
                'queryDate': day, 'memberCodes': sorted(member_codes),
                'membershipInputSha256': membership_sha256, 'requestRecordSha256': request_record_sha256,
                'components': sorted(proof, key=lambda rec: rec['code']),
                'selectedInputSha256': digest({'data': selected}), 'retainedRows': len(selected),
                'knownAt': max(receipts).isoformat(), 'completeComponentSet': True,
                'wholeMarketDateQueryAccepted': False, 'companyFullHistoryReceiptAccepted': False,
                'datedMembershipOriginalAccepted': False, 'contemporaneousReceiptAccepted': False,
                'historicalStudyAccepted': False,
                'actionAuthority': False}
    envelope['compositeSha256'] = digest(envelope)
    return envelope, selected


def validate(envelope, selected):
    """Revalidate the persisted selected-input envelope, including empty components.

    Raw HTTP hashes are references to separately preserved originals. They do
    not mean the private selected-input snapshot contains full HTTP bodies.
    """
    fields = {'schemaVersion','scopeKind','queryDate','memberCodes','membershipInputSha256',
              'requestRecordSha256','components','selectedInputSha256','retainedRows','knownAt',
              'completeComponentSet','wholeMarketDateQueryAccepted','companyFullHistoryReceiptAccepted',
              'datedMembershipOriginalAccepted','contemporaneousReceiptAccepted','historicalStudyAccepted',
              'actionAuthority','compositeSha256'}
    require(isinstance(envelope, dict) and set(envelope) == fields, 'COMPOSITE_FIELDS')
    require(envelope['schemaVersion']=='financial-company-date-composite-scope-v1'
            and envelope['scopeKind']=='RECONSTRUCTED_225_COMPANY_DATE_COMPONENT_SET', 'COMPOSITE_KIND')
    require(all(envelope[k] is False for k in ('wholeMarketDateQueryAccepted','companyFullHistoryReceiptAccepted',
                'datedMembershipOriginalAccepted','contemporaneousReceiptAccepted','historicalStudyAccepted','actionAuthority'))
            and envelope['completeComponentSet'] is True, 'COMPOSITE_AUTHORITY')
    body={k:v for k,v in envelope.items() if k!='compositeSha256'}
    require(digest(body)==envelope['compositeSha256'], 'COMPOSITE_HASH')
    for key in ('membershipInputSha256','requestRecordSha256','selectedInputSha256'):
        require(type(envelope[key]) is str and re.fullmatch('[0-9a-f]{64}',envelope[key]), 'INPUT_BINDING_REQUIRED')
    members=envelope['memberCodes'];day=envelope['queryDate']
    require(type(day) is str and date.fromisoformat(day).isoformat()==day, 'DATE_REQUIRED')
    require(isinstance(members,list) and len(members)==225 and len(set(members))==225
            and members==sorted(members) and all(type(c) is str and re.fullmatch('[0-9A-Z]{4}',c) for c in members), 'EXACT_225_MEMBERS_REQUIRED')
    require(isinstance(selected,list) and len(selected)<=30000
            and type(envelope['retainedRows']) is int and envelope['retainedRows']==len(selected)
            and len(canonical({'data':selected}))<=524288
            and digest({'data':selected})==envelope['selectedInputSha256'], 'COMPOSITE_SELECTED_INPUT')
    by_code={code:[] for code in members};identities=set()
    for row in selected:
        require(isinstance(row,dict) and not set(row)-set(FIELDS)
                and row.get('Code') in by_code and row.get('DiscDate')==day, 'ROW_SCOPE_MISMATCH')
        require(type(row.get('DiscNo')) is str and row['DiscNo'], 'DISCLOSURE_ID_REQUIRED')
        identity=(row['Code'],row['DiscDate'],row['DiscNo'])
        require(identity not in identities,'DUPLICATE_DISCLOSURE');identities.add(identity)
        require(all(type(v) in (str,int,float,type(None)) and len(str(v))<=160
                    and (type(v) is not float or math.isfinite(v)) for v in row.values()),'FIELD_BOUND')
        by_code[row['Code']].append(row)
    parts=envelope['components'];require(isinstance(parts,list) and len(parts)==225,'ALL_COMPONENTS_REQUIRED')
    seen=set();times=[]
    for part in parts:
        require(isinstance(part,dict) and set(part)=={'code','queryDate','queryKind','rows','pages',
                    'cacheSha256','canonicalRowsSha256','selectedRowsSha256','complete'},'COMPONENT_FIELDS')
        code=part['code'];require(code in by_code and code not in seen and part['queryDate']==day
                and part['queryKind']=='COMPANY_AND_DATE' and part['complete'] is True,'COMPONENT_SCOPE_MISMATCH')
        seen.add(code)
        rows=sorted(by_code[code],key=lambda r:(r['Code'],r['DiscDate'],r['DiscNo']))
        require(type(part['rows']) is int and part['rows']==len(rows)
                and digest(rows)==part['selectedRowsSha256'],'COMPONENT_SELECTED_INPUT')
        for key in ('cacheSha256','canonicalRowsSha256','selectedRowsSha256'):
            require(type(part[key]) is str and re.fullmatch('[0-9a-f]{64}',part[key]),'INPUT_BINDING_REQUIRED')
        pages=part['pages'];require(isinstance(pages,list) and 1<=len(pages)<=3,'PAGE_BOUND_OR_MISSING')
        previous=None
        for page in pages:
            require(isinstance(page,dict) and set(page)=={'sha256','bytes','http','requestedAt','receivedAt'},'PAGE_FIELDS')
            require(type(page['bytes']) is int and 0<page['bytes']<=2097152 and page['http']==200
                    and type(page['sha256']) is str and re.fullmatch('[0-9a-f]{64}',page['sha256']),'PAGE_BYTES_BOUND')
            requested,received=stamp(page['requestedAt']),stamp(page['receivedAt'])
            require(requested<=received and (received-requested).total_seconds()<=20
                    and (previous is None or previous<=requested)
                    and date.fromisoformat(day)<=received.astimezone(ZoneInfo('Asia/Tokyo')).date(),'PAGE_RECEIPT_TIME')
            previous=received;times.append(received)
        for row in rows:
            clock=row.get('DiscTime')
            if isinstance(clock,str) and re.fullmatch(r'\d{2}:\d{2}(?::\d{2})?',clock):
                try: published=datetime.fromisoformat(day+'T'+clock).replace(tzinfo=ZoneInfo('Asia/Tokyo'))
                except ValueError: raise ScopeError('PUBLICATION_TIME_INVALID') from None
                require(published<=previous,'FUTURE_PUBLICATION')
    require(seen==set(members) and stamp(envelope['knownAt'])==max(times),'COMPOSITE_AVAILABILITY')
    return envelope
