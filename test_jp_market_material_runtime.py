"""Receipt, price identity and real call-boundary contracts; no collection."""
import copy
import ast
from datetime import datetime, timezone, timedelta
import importlib.util
import json
from pathlib import Path
import sys
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

OUT = Path(__file__).parent
REPO = Path(__file__).resolve().parent
sys.path[:0] = [str(OUT), str(REPO)]
import pytz
import jp_market_material_reactions as material
import jp_market_analogs as analog
spec = importlib.util.spec_from_file_location('runtime_price_paths', str(REPO / 'jp_market_price_paths.py'))
paths = importlib.util.module_from_spec(spec); spec.loader.exec_module(paths)

SESSIONS = ['2026-09-03', '2026-09-04', '2026-09-07', '2026-09-08', '2026-09-09', '2026-09-10', '2026-09-11']
RECEIPT = '2026-09-12T00:00:00Z'
CUTOFF = '2026-09-13T00:00:00Z'
EVENT = {'eventId': 'synthetic-nfp', 'eventType': 'NFP', 'eventTime': '2026-09-04T12:30:00Z',
         'receivedAt': RECEIPT, 'sourceRef': 'synthetic:official-header', 'sourceSha256': 'a'*64,
         'timeBasis': 'OFFICIAL_EMBARGO_BOUNDARY'}
BARS = [{'instrumentId': material.INSTRUMENT, 'date': d, 'close': 100+i,
         'sourceRef': 'yahoo:chart:^N225'} for i,d in enumerate(SESSIONS)]

def history(bars=BARS):
    return {'data': bars, 'currentSourceAcquiredAt': RECEIPT, 'currentSourceSha256': 'b'*64}

def record(event=EVENT):
    return {'eventId': event['eventId'], 'eventCode': event['eventType'], 'eventTimeEvidence': event}

def derive(records=None, hist=None, cached=None, sessions=SESSIONS, cutoff=CUTOFF):
    return material.cached_reactions(records if records is not None else [record()],
        rows=material.cash_rows(hist or history(), cached or {}), sessions=sessions, cutoff=cutoff)

class RuntimeConnection(unittest.TestCase):
    def test_official_boundary_references_keep_unvalidated_and_late_receipt(self):
        out=derive(); self.assertEqual(len(out['rows']),3)
        for r in out['rows']:
            self.assertEqual(r['availableFrom'], '2026-09-12T00:00:00+00:00')
            self.assertFalse(r['actualPublicationTimeVerified']); self.assertFalse(r['historicalVintageVerified'])
            self.assertIsNone(r['probability']); self.assertFalse(r['actionAuthority'])
    def test_schedule_intraday_and_legacy_release_are_not_evidence(self):
        raw={'eventId':'synthetic-nfp', 'eventCode':'NFP', 'eventTimeUtc':EVENT['eventTime'],
             'actual':{'available':True,'releasedAt':EVENT['eventTime'],'receivedAt':RECEIPT},
             'marketReaction':{'windows':[{'window':'+5m','spyMovePct':5}]}}
        out=derive([raw]); self.assertFalse(out['rows'])
        self.assertEqual(out['diagnostics']['gatedReasonCounts'],{'event_source_time_evidence_missing':1})
    def test_explicit_schedule_basis_is_gated(self):
        self.assertFalse(derive([record({**EVENT,'timeBasis':'SCHEDULED'})])['rows'])
    def test_actual_publication_label_without_observation_proof_is_gated(self):
        self.assertFalse(derive([record({**EVENT,'timeBasis':'VERIFIED_ACTUAL_PUBLICATION'})])['rows'])
    def test_prior_backfill_receipt_is_required_after_a_later_refresh_failure(self):
        hist=history();hist.update(backfillStatus='FAILED',backfillSourceSha256='c'*64)
        self.assertFalse(derive(hist=hist)['rows'])
    def test_event_identity_cannot_be_borrowed(self):
        raw=record();raw['eventId']='different-event'
        self.assertFalse(derive([raw])['rows'])
    def test_missing_source_hash_cannot_use_assumed_close_availability(self):
        hist=history();hist.pop('currentSourceSha256')
        self.assertFalse(derive(hist=hist)['rows'])
    def test_interior_missing_session_is_not_bridged(self):
        rows=[r for r in BARS if r['date']!='2026-09-08']
        out=derive(hist=history(rows)); self.assertEqual([r['reactionWindowSessions']for r in out['rows']],[1])
    def test_future_or_before_close_price_receipt_is_gated(self):
        self.assertFalse(derive(cutoff='2026-09-11T01:00:00Z')['rows'])
        hist=history();hist['currentSourceAcquiredAt']='2026-09-04T00:00:00Z'
        self.assertFalse(derive(hist=hist)['rows'])
    def test_missing_backfill_receipt_rejects_retained_batch(self):
        hist=history();hist['backfillStatus']='AVAILABLE'
        self.assertFalse(derive(hist=hist)['rows'])
    def test_old_current_batch_does_not_replace_newer_retained_bar(self):
        cache={'data':[{**BARS[-1],'close':900}], 'acquiredAt':'2026-09-10T00:00:00Z','sourceResponseSha256':'c'*64}
        self.assertEqual(material.cash_rows(history(),cache)[-1]['close'], BARS[-1]['close'])
    def test_new_batch_replaces_whole_row_and_changes_reference_identity(self):
        a=derive();cache={'data':[{**BARS[6],'close':900}], 'acquiredAt':'2026-09-12T01:00:00Z','sourceResponseSha256':'c'*64}
        b=derive(cached=cache)
        self.assertNotEqual(a['rows'][2]['value'], b['rows'][2]['value'])
        self.assertNotEqual(a['rows'][2]['sourceRowsHash'], b['rows'][2]['sourceRowsHash'])
    def test_intermediate_correction_preserves_endpoint_return_but_changes_chain_hash(self):
        a=derive();cache={'data':[{**BARS[5],'close':900}], 'acquiredAt':'2026-09-12T01:00:00Z','sourceResponseSha256':'c'*64}
        b=derive(cached=cache)
        self.assertEqual(a['rows'][2]['value'], b['rows'][2]['value'])
        self.assertNotEqual(a['rows'][2]['sourceRowsHash'], b['rows'][2]['sourceRowsHash'])
    def test_proxy_and_duplicate_cash_batches_are_rejected(self):
        for bars in ([*BARS,BARS[-1]],[{**r,'sourceRef':'proxy:etf'}for r in BARS]):
            with self.assertRaises(ValueError):material.cash_rows(history(bars),{})
    def test_future_event_metadata_and_record_bound_are_gated(self):
        self.assertFalse(derive([record({**EVENT,'receivedAt':'2026-10-01T00:00:00Z'})])['rows'])
        with self.assertRaises(ValueError):derive([record()]*201)
    def test_existing_episode_excludes_later_received_material(self):
        reactions=derive()['rows']
        bars=[{**r,'availableFrom':'2026-09-03T00:00:00Z','seriesId':'close'}for r in BARS]
        episode=analog.build_episode(cutoff='2026-09-11T23:59:59Z',bars=bars,reaction_rows=reactions)
        self.assertFalse(episode['reactions'])
    def test_scanner_passes_rows_on_actual_comparison_call_and_preserves_chart_when_gated(self):
        captured=[]
        def compare(rows,**kw):
            captured.append(kw);return {'status':'available','comparison':None}
        ns={'_JP_MARKET_ENGINE_INDEX_OHLCV_CACHE':{}, '_N225_ANALOG_HISTORY':history(),
            '_nikkei_chart_rows':lambda:BARS,'datetime':datetime,'pytz':pytz,
            'argus_index_history':SimpleNamespace(MAX_BARS=3000,MAX_DAYS=4000),
            '_jp_exchange_sessions':lambda *a:(SESSIONS,False),'_MACRO_RECORD_LOCK':threading.RLock(),
            '_MACRO_ANALYSIS':{'synthetic-nfp':record()}, 'jp_market_price_paths':SimpleNamespace(cached_index_comparison=compare),
            '_level_map_current_valuation':lambda *a,**k:{'basis':'synthetic-current','date':None,'recordedAt':None},
            'jp_market_level_map':SimpleNamespace(EPS_BASIS='synthetic-current'), '_JP_MARKET_FEATURE_HISTORY':{},
            '_JP_ANALOG_BACKTEST_CACHE':{}, '_JP_MARKET_FEATURE_CACHE_STATUS':{}, '_jp_market_series_acquisition_status':lambda:{},
            '_JP_MARKET_FEATURE_INPUT_SPANS':{},'_JP_OFFICIAL_SOURCE_CACHE':SimpleNamespace(snapshot=lambda:{})}
        source = (REPO / 'scanner.py').read_text()
        node = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == '_jp_market_comparison_calculate')
        exec(compile(ast.Module([node], type_ignores=[]), '<real-scanner-comparison>', 'exec'), ns)
        result=ns['_jp_market_comparison_calculate'](1)
        self.assertEqual(len(captured[-1]['reaction_rows']),3)
        self.assertEqual(result['materialReactionAcquisition']['availableReferenceWindows'],3)
        ns['_MACRO_ANALYSIS']={'synthetic-nfp':{'eventId':'synthetic-nfp','eventCode':'NFP'}}
        result=ns['_jp_market_comparison_calculate'](1)
        self.assertEqual(result['status'],'available');self.assertEqual(captured[-1]['reaction_rows'],[])

if __name__=='__main__':unittest.main(verbosity=2)
