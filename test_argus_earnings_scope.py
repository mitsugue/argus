"""Adversarial admission checks, with no provider calls or market writes."""
import copy
import hashlib
import json
import unittest
import argus_earnings_scope as scope


def fixture():
    members = [str(n) for n in range(1000, 1225)]
    components = []
    for code in members:
        raw = b'{"data":[]}'
        normal = b'[]\n'
        rec = {'code': code, 'queryDate': '2017-05-12', 'complete': True, 'rows': 0,
               'cacheSha256': hashlib.sha256(normal).hexdigest(),
               'pages': [{'http': 200, 'bytes': len(raw), 'decodedBytesObserved': len(raw),
                          'sha256': hashlib.sha256(raw).hexdigest(), 'elapsedSeconds': 0.1,
                          'requestedAt': '2026-10-12T16:00:00+00:00', 'receivedAt': '2026-10-12T16:00:01+00:00'}]}
        components.append({'queryKind': 'COMPANY_AND_DATE', 'receipt': rec,
                           'rawPages': [raw], 'normalizedBytes': normal})
    return dict(day='2017-05-12', member_codes=members, membership_sha256='a'*64,
                request_record_sha256='', components=components, cutoff='2026-10-13T00:00:00+00:00')


def bind(data):
    data['request_record_sha256'] = scope.digest(sorted([c['receipt'] for c in data['components']], key=lambda r:r['code']))


def add_row(data, **changes):
    row = {'Code': '10000', 'DiscDate': '2017-05-12', 'DiscNo': 'receipt-1', 'FOP': '10'}
    row.update(changes)
    c = data['components'][0]
    raw = scope.canonical({'data': [row]})
    normal = scope.canonical([row])
    c.update(rawPages=[raw], normalizedBytes=normal)
    rec = c['receipt'];rec.update(rows=1, cacheSha256=hashlib.sha256(normal).hexdigest())
    rec['pages'][0].update(bytes=len(raw), decodedBytesObserved=len(raw), sha256=hashlib.sha256(raw).hexdigest())


class CompositeChecks(unittest.TestCase):
    def rejected(self, mutate, category):
        data = fixture();mutate(data);bind(data)
        with self.assertRaisesRegex(scope.ScopeError, '^'+category+'$'):
            scope.admit(**data)

    def test_empty_225_is_valid_only_for_separate_research_scope(self):
        data=fixture();bind(data);envelope,rows=scope.admit(**data)
        self.assertEqual(rows,[]);self.assertEqual(envelope['knownAt'],'2026-10-12T16:00:01+00:00')
        self.assertTrue(envelope['completeComponentSet'])
        for key in ('wholeMarketDateQueryAccepted','companyFullHistoryReceiptAccepted','datedMembershipOriginalAccepted',
                    'contemporaneousReceiptAccepted','historicalStudyAccepted','actionAuthority'):
            self.assertIs(envelope[key],False)

    def test_selected_rows_normalize_ordinary_code_and_keep_null(self):
        data=fixture();add_row(data, FOP=None);bind(data);_,rows=scope.admit(**data)
        self.assertEqual(rows[0]['Code'],'1000');self.assertIsNone(rows[0]['FOP'])

    def test_missing_empty_component_rejected(self):
        self.rejected(lambda d:d['components'].pop(),'ALL_COMPONENTS_REQUIRED')

    def test_duplicate_empty_component_rejected(self):
        self.rejected(lambda d:d['components'].__setitem__(1,copy.deepcopy(d['components'][0])),'COMPONENT_SCOPE_MISMATCH')

    def test_wrong_date(self):
        self.rejected(lambda d:d['components'][0]['receipt'].update(queryDate='2017-05-11'),'COMPONENT_SCOPE_MISMATCH')

    def test_whole_company_cannot_replace_date_component(self):
        self.rejected(lambda d:d['components'][0].update(queryKind='COMPANY_FULL_HISTORY'),'QUERY_KIND_REQUIRED')

    def test_partial_receipt(self):
        self.rejected(lambda d:d['components'][0]['receipt'].update(complete=False),'COMPONENT_INCOMPLETE')

    def test_non_200(self):
        self.rejected(lambda d:d['components'][0]['receipt']['pages'][0].update(http=403),'PAGE_NOT_SUCCESSFUL')

    def test_future_receipt_not_backdated_to_historical_day(self):
        self.rejected(lambda d:d.update(cutoff='2017-05-12T18:00:00+09:00'),'PAGE_RECEIPT_TIME')

    def test_naive_timestamp(self):
        self.rejected(lambda d:d['components'][0]['receipt']['pages'][0].update(receivedAt='2026-10-12T16:00:01'),'TIMESTAMP_ZONE_REQUIRED')

    def test_time_bound(self):
        self.rejected(lambda d:d['components'][0]['receipt']['pages'][0].update(elapsedSeconds=20.1),'PAGE_TIME_BOUND')

    def test_byte_count_not_assumed_from_hash(self):
        self.rejected(lambda d:d['components'][0]['receipt']['pages'][0].update(decodedBytesObserved=2097153),'PAGE_BYTES_BOUND')

    def test_raw_tamper(self):
        self.rejected(lambda d:d['components'][0].update(rawPages=[b'{"data":{}}']),'RAW_HASH_MISMATCH')

    def test_cache_tamper(self):
        self.rejected(lambda d:d['components'][0].update(normalizedBytes=b'{}\n'),'CACHE_HASH_MISMATCH')

    def test_cache_content_mismatch_even_with_matching_hash(self):
        def mutate(d):
            c=d['components'][0];c['normalizedBytes']=b'[{}]';c['receipt']['cacheSha256']=hashlib.sha256(b'[{}]').hexdigest()
        self.rejected(mutate,'CACHE_ROWS_MISMATCH')

    def test_cross_company_row(self):
        self.rejected(lambda d:add_row(d, Code='10010'),'ROW_SCOPE_MISMATCH')

    def test_cross_day_row(self):
        self.rejected(lambda d:add_row(d, DiscDate='2017-05-11'),'ROW_SCOPE_MISMATCH')

    def test_nan_forecast(self):
        # JSON forbids NaN for canonical accepted content; raw parser must reject it too.
        def mutate(d):
            add_row(d);c=d['components'][0];raw=b'{"data":[{"Code":"10000","DiscDate":"2017-05-12","DiscNo":"receipt-1","FOP":NaN}]}'
            c['rawPages']=[raw];c['receipt']['pages'][0].update(bytes=len(raw),decodedBytesObserved=len(raw),sha256=hashlib.sha256(raw).hexdigest())
        self.rejected(mutate,'FIELD_BOUND')

    def test_unended_pagination(self):
        def mutate(d):
            c=d['components'][0];raw=b'{"data":[],"pagination_key":"next"}';c['rawPages']=[raw]
            c['receipt']['pages'][0].update(bytes=len(raw),decodedBytesObserved=len(raw),sha256=hashlib.sha256(raw).hexdigest())
        self.rejected(mutate,'PAGE_CHAIN_INCOMPLETE')

    def test_record_tamper_keeps_original_binding(self):
        data=fixture();bind(data);data['components'][0]['receipt']['cacheSha256']='b'*64
        with self.assertRaisesRegex(scope.ScopeError,'REQUEST_RECORD_BINDING_MISMATCH'):scope.admit(**data)

    def test_duplicate_disclosure_even_identical_rejected(self):
        def mutate(d):
            add_row(d);c=d['components'][0];row=json.loads(c['rawPages'][0])['data'][0]
            raw=scope.canonical({'data':[row,row]});c['rawPages']=[raw]
            c['receipt']['pages'][0].update(bytes=len(raw),decodedBytesObserved=len(raw),sha256=hashlib.sha256(raw).hexdigest())
        self.rejected(mutate,'DUPLICATE_DISCLOSURE')

    def test_multi_page_without_recorded_request_link_rejected(self):
        def mutate(d):
            c=d['components'][0];p=c['receipt']['pages'][0];first=b'{"data":[],"pagination_key":"next"}'
            second=copy.deepcopy(p);second.update(requestedAt='2026-10-12T16:00:03+00:00',receivedAt='2026-10-12T16:00:04+00:00')
            p.update(bytes=len(first),decodedBytesObserved=len(first),sha256=hashlib.sha256(first).hexdigest())
            c['rawPages']=[first,c['rawPages'][0]];c['receipt']['pages'].append(second)
        self.rejected(mutate,'REQUEST_PAGE_LINK_REQUIRED')

    def test_multi_page_explicit_link_changes_availability(self):
        d=fixture();c=d['components'][0];p=c['receipt']['pages'][0];first=b'{"data":[],"pagination_key":"next"}'
        second=copy.deepcopy(p);second.update(requestPaginationKey='next',requestedAt='2026-10-12T16:00:03+00:00',receivedAt='2026-10-12T16:00:04+00:00')
        p.update(bytes=len(first),decodedBytesObserved=len(first),sha256=hashlib.sha256(first).hexdigest())
        c['rawPages']=[first,c['rawPages'][0]];c['receipt']['pages'].append(second)
        bind(d);env,_=scope.admit(**d);self.assertEqual(env['knownAt'],'2026-10-12T16:00:04+00:00')

    def test_forecast_boolean_not_numeric_zero(self):
        self.rejected(lambda d:add_row(d,FOP=False),'FIELD_BOUND')


if __name__=='__main__':unittest.main()
