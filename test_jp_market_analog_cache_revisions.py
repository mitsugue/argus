"""Same-count corrections must invalidate study results, unchanged inputs reuse."""
import copy
from datetime import date,timedelta
import importlib.util
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parent;sys.path.insert(0,str(ROOT))
import jp_market_analog_backtest as backtest
spec=importlib.util.spec_from_file_location('audited_price_paths',os.environ.get('ARGUS_CACHE_CANDIDATE',str(ROOT/'jp_market_price_paths.py')))
paths=importlib.util.module_from_spec(spec);spec.loader.exec_module(paths)
start=date(2026,1,1)
DAYS=[(start+timedelta(days=i)).isoformat() for i in range(140) if (start+timedelta(days=i)).weekday()<5]
BARS=[{'instrumentId':'NIKKEI_225_INDEX','seriesId':'close','date':d,'close':40000+(i%23)*30,'availableFrom':d+'T07:00:00Z','sourceRef':'synthetic:cash'}for i,d in enumerate(DAYS)]
CUTOFF=DAYS[-1]+'T12:00:00Z'
def row(series,value,**extra):
    d=DAYS[35]
    return {'instrumentId':'NIKKEI_225_INDEX','seriesId':series,'date':d,'periodEnd':d,'value':value,'unit':'PERCENT','availableFrom':d+'T07:00:00Z','sourceRef':'synthetic:material',**extra}
class CacheRevisions(unittest.TestCase):
    def setUp(self):
        self.walk=patch.object(backtest,'walk_forward',return_value={'horizons':{},'method':'synthetic-validation'}).start()
        self.search=patch.object(backtest,'weight_search',return_value={'status':'INSUFFICIENT_DATA','adopted':False}).start()
        self.addCleanup(patch.stopall)
    def studies(self):
        # 2026-10-19: each study walks forward twice (current and recent-years yardstick).
        assert self.walk.call_count % 2 == 0
        return self.walk.call_count // 2
    def invoke(self,cache,bars=None,**kw):
        r=paths.cached_index_comparison(bars or BARS,cutoff=CUTOFF,session_dates=DAYS,backtest_cache=cache,**kw)
        self.assertEqual(r['status'],'available');self.assertIsNone(r['selection']['predictiveProbability']);self.assertFalse(r['actionAuthority'])
        return r
    def test_identical_inputs_reuse_study(self):
        cache={};self.invoke(cache);key=cache['key'];self.invoke(cache)
        self.assertEqual(self.studies(),1);self.assertEqual(key,cache['key'])
    def test_same_count_material_correction_revalidates(self):
        r=row('material.CPI.3',1,eventId='synthetic-cpi',eventType='CPI',reactionWindowSessions=3)
        cache={};self.invoke(cache,reaction_rows=[r]);key=cache['key']
        self.invoke(cache,reaction_rows=[{**r,'value':-2}])
        self.assertEqual(self.studies(),2);self.assertNotEqual(key,cache['key'])
    def test_same_count_material_receipt_change_revalidates(self):
        r=row('material.CPI.3',1,eventId='synthetic-cpi',eventType='CPI',reactionWindowSessions=3)
        cache={};self.invoke(cache,reaction_rows=[r]);key=cache['key']
        self.invoke(cache,reaction_rows=[{**r,'availableFrom':CUTOFF}])
        self.assertEqual(self.studies(),2);self.assertNotEqual(key,cache['key'])
    def test_same_count_historical_price_correction_revalidates(self):
        cache={};self.invoke(cache);bars=copy.deepcopy(BARS);bars[35]['close']+=700
        self.invoke(cache,bars=bars);self.assertEqual(self.studies(),2)
    def test_same_count_state_correction_revalidates(self):
        r=row('credit.loss_pct',-1);cache={};self.invoke(cache,state_rows=[r])
        self.invoke(cache,state_rows=[{**r,'value':-2}]);self.assertEqual(self.studies(),2)
    def test_same_count_condition_correction_revalidates(self):
        r=row('d01_credit_stress',1);cache={};self.invoke(cache,condition_rows=[r])
        self.invoke(cache,condition_rows=[{**r,'value':-1}]);self.assertEqual(self.studies(),2)
    def test_invisible_future_material_does_not_invalidate(self):
        r=row('material.CPI.3',1,eventId='synthetic-cpi',eventType='CPI',reactionWindowSessions=3,availableFrom='2026-12-01T00:00:00Z')
        cache={};self.invoke(cache,reaction_rows=[r]);key=cache['key']
        self.invoke(cache,reaction_rows=[{**r,'value':900}]);self.assertEqual(self.studies(),1);self.assertEqual(key,cache['key'])
    def test_added_future_material_does_not_invalidate(self):
        r=row('material.CPI.3',1,eventId='synthetic-cpi',eventType='CPI',reactionWindowSessions=3,availableFrom='2026-12-01T00:00:00Z')
        cache={};self.invoke(cache,reaction_rows=[]);key=cache['key']
        self.invoke(cache,reaction_rows=[r]);self.assertEqual(self.studies(),1);self.assertEqual(key,cache['key'])
    def test_shared_horizons_reuse_one_study(self):
        cache={}
        for horizon in (1,5,10,20):self.invoke(cache,horizon_sessions=horizon)
        self.assertEqual(self.studies(),1);self.assertEqual(self.search.call_count,1)
    def test_invisible_future_price_does_not_invalidate(self):
        bars=copy.deepcopy(BARS);bars[35]['availableFrom']='2026-12-01T00:00:00Z'
        cache={};self.invoke(cache,bars=bars);key=cache['key'];bars[35]['close']+=900
        self.invoke(cache,bars=bars);self.assertEqual(self.studies(),1);self.assertEqual(key,cache['key'])
if __name__=='__main__':unittest.main(verbosity=2)
