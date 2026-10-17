"""Synthetic HTTP boundaries and real existing parser/store; zero network IO."""
import ast
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(ROOT))
import argus_macro_results as results
import argus_macro_event_store as store
import jp_market_macro_http_receipt as subject
import jp_market_material_reactions as reactions

AT = '2026-10-14T12:30:04+00:00'
RAW = {'status': 'REQUEST_SUCCEEDED', 'Results': {'series': []}}
BODY = json.dumps(RAW, indent=2).encode()


def evidence(**changes):
    kwargs = {'received_at': AT, 'response_url': subject.BLS_API,
              'status': 200, 'redirected': False}
    kwargs.update(changes)
    return subject.receipt(BODY, RAW, **kwargs)


def actual():
    return {'available': True, 'source': 'BLS', 'metrics': {'referenceMonth': '2026-09'},
            **results.series_receipt(RAW, AT)}


def functions_namespace(response):
    source = (ROOT / 'scanner.py').read_text()
    nodes = [node for node in ast.parse(source).body if isinstance(node, ast.FunctionDef)
             and node.name in {'_bls_fetch', '_macro_result_fetch'}]
    calls = []
    def post(*args, **kwargs):
        calls.append((args, kwargs))
        return response
    ns = {'requests': SimpleNamespace(post=post), 'datetime': datetime,
          'pytz': SimpleNamespace(utc=timezone.utc), '_ai_now_iso': lambda: AT,
          'argus_macro_results': results}
    exec(compile(ast.Module(nodes, type_ignores=[]), '<isolated-real-functions>', 'exec'), ns)
    return ns, calls


class ReceiptTests(unittest.TestCase):
    def test_distinct_wire_and_canonical_hashes(self):
        e = evidence()
        self.assertNotEqual(e['rawHttpResponseSha256'], e['parsedResponseSha256'])
        self.assertEqual(e['parsedResponseSha256'], actual()['sourceResponseSha256'])
        self.assertFalse(e['rawHttpBodyRetained'])
        self.assertFalse(e['actualPublicationTimeVerified'])

    def test_no_publication_time_and_no_event_adoption(self):
        a = subject.bind(actual(), evidence())
        self.assertIsNone(a['releasedAt'])
        self.assertNotIn('eventTimeEvidence', a)
        r = reactions.cached_reactions([{'eventId':'synthetic:CPI', 'eventCode':'CPI',
            'actual':a}], rows=[], sessions=[], cutoff=AT)
        self.assertEqual(r['rows'], [])
        self.assertEqual(r['diagnostics']['gatedReasonCounts'], {'event_source_time_evidence_missing':1})

    def test_body_mismatch(self):
        with self.assertRaises(ValueError):
            subject.receipt(BODY, {**RAW,'changed':True}, received_at=AT,
                            response_url=subject.BLS_API,status=200,redirected=False)

    def test_status_rejected(self):
        with self.assertRaises(ValueError):evidence(status=403)

    def test_redirect_rejected(self):
        with self.assertRaises(ValueError):evidence(redirected=True)

    def test_origin_rejected(self):
        with self.assertRaises(ValueError):evidence(response_url='https://example.invalid/')

    def test_missing_timezone(self):
        with self.assertRaises(ValueError):evidence(received_at='2026-10-14T12:30:04')

    def test_body_bound(self):
        with self.assertRaises(ValueError):
            subject.receipt(b'x'*(subject.MAX_RESPONSE_BYTES+1), RAW,received_at=AT,
                            response_url=subject.BLS_API,status=200,redirected=False)

    def test_cross_response_cannot_attach(self):
        a = actual(); e = evidence(); e['parsedResponseSha256']='a'*64
        self.assertEqual(subject.bind(a,e),a)

    def test_later_receipt_cannot_attach_to_earlier_actual(self):
        a=actual();e=evidence();e['receivedAt']='2026-10-14T12:31:00+00:00'
        self.assertEqual(subject.bind(a,e),a)

    def test_partial_and_invalid_metadata_leave_metrics(self):
        a=actual()
        self.assertEqual(subject.bind(a,None),a)
        self.assertEqual(subject.bind(a,{'receivedAt':AT}),a)
        self.assertEqual(subject.bind({**a,'available':False},evidence()),{**a,'available':False})
        e=evidence();del e['responseBytes']
        self.assertEqual(subject.bind(a,e),a)

    def test_secrets_and_body_are_not_carried(self):
        a=actual();e=evidence();e.update(body='synthetic secret', headers={'token':'secret'})
        x=subject.bind(a,e)
        self.assertNotIn('body',x['sourceHttpReceipt']);self.assertNotIn('headers',x['sourceHttpReceipt'])
        self.assertEqual(a,actual())

    def test_restore_preserves_old_revision_and_new_receipt(self):
        old={'eventId':'synthetic:CPI','eventCode':'CPI','actual':actual(),'updatedAt':AT}
        a=subject.bind(actual(), evidence())
        inc={**old,'actual':a,'updatedAt':'2026-10-14T12:31:00+00:00'}
        original=store.merge_record(None,old,now_iso=AT)
        merged=store.merge_record(original,inc,now_iso=inc['updatedAt'])
        self.assertEqual(merged['resultRevisions'],original['resultRevisions'])
        self.assertEqual(merged['actualRevisionId'],original['actualRevisionId'])
        restored=store.restore_from_snapshot(store.serialize_snapshot([merged],as_of=inc['updatedAt']))
        self.assertEqual(restored[old['eventId']]['actual']['sourceHttpReceipt'],a['sourceHttpReceipt'])

    def test_legacy_fetch_tuple_and_one_post(self):
        r=SimpleNamespace(status_code=200,content=BODY,url=subject.BLS_API,history=[],json=lambda:RAW)
        ns,calls=functions_namespace(r)
        self.assertEqual(ns['_bls_fetch'](['synthetic-series']), (RAW,200))
        self.assertEqual(len(calls),1)

    def test_enriched_fetch_one_post_and_parsed_input_unchanged(self):
        r=SimpleNamespace(status_code=200,content=BODY,url=subject.BLS_API,history=[],json=lambda:RAW)
        ns,calls=functions_namespace(r)
        received=ns['_bls_fetch'](['synthetic-series']);value,st=received;e=received.receipt
        self.assertEqual((value,st),(RAW,200));self.assertEqual(e,evidence());self.assertEqual(len(calls),1)

    def test_failed_http_one_post_and_no_receipt(self):
        ns,calls=functions_namespace(SimpleNamespace(status_code=403))
        self.assertEqual(ns['_bls_fetch']([]),(None,403))
        self.assertEqual(len(calls),1)

    def test_receipt_invalid_does_not_erase_existing_parsed_data(self):
        r=SimpleNamespace(status_code=200,content=BODY,url=subject.BLS_API,history=[object()],json=lambda:RAW)
        ns,calls=functions_namespace(r)
        received=ns['_bls_fetch']([])
        self.assertEqual(received,(RAW,200));self.assertIsNone(received.receipt)
        self.assertEqual(len(calls),1)

    def test_cpi_dispatch_connects_real_parser_without_extra_request(self):
        series=[]
        for sid in ['CUSR0000SA0','CUSR0000SA0L1E','CUUR0000SA0','CUUR0000SA0L1E']:
            series.append({'seriesID':sid,'data':[{'year':'2026','period':'M09','value':'310'},
                {'year':'2026','period':'M08','value':'309'},{'year':'2025','period':'M09','value':'300'}]})
        raw={'status':'REQUEST_SUCCEEDED','Results':{'series':series}};body=json.dumps(raw).encode()
        response=SimpleNamespace(status_code=200,content=body,url=subject.BLS_API,history=[],json=lambda:raw)
        ns,calls=functions_namespace(response)
        event={'eventCode':'CPI','eventDate':'2026-10-14','eventTimeUtc':'2026-10-14T12:30:00Z'}
        out=ns['_macro_result_fetch'](event)
        base=results.parse_cpi(raw,event,AT)
        self.assertTrue(out['available'])
        self.assertEqual({k:v for k,v in out.items()if k!='sourceHttpReceipt'},base)
        self.assertEqual(out['sourceHttpReceipt']['receivedAt'],AT)
        self.assertEqual(len(calls),1)

    def test_old_fetch_double_remains_compatible(self):
        ns,_=functions_namespace(SimpleNamespace())
        ns['_bls_fetch']=lambda series_ids:(None,403)
        out=ns['_macro_result_fetch']({'eventCode':'PPI'})
        self.assertEqual(out['status'],'source_unreachable')


if __name__=='__main__':unittest.main(verbosity=2)
