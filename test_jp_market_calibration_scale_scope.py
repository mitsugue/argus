"""Recent receipts do not invalidate unchanged historical study inputs."""
import copy
import unittest
from unittest.mock import patch
import test_jp_market_analog_cache_revisions as fixture
import jp_market_analog_backtest as backtest

class CalibrationScaleScope(unittest.TestCase):
    def setUp(self):
        self.walk = patch.object(backtest, 'walk_forward', return_value={'horizons': {}, 'method': 'synthetic-validation'}).start()
        self.search = patch.object(backtest, 'weight_search', return_value={'status': 'INSUFFICIENT_DATA', 'adopted': False}).start()
        self.addCleanup(patch.stopall)

    def invoke(self, cache, rows):
        result = fixture.paths.cached_index_comparison(fixture.BARS, cutoff=fixture.CUTOFF,
            session_dates=fixture.DAYS, backtest_cache=cache, state_rows=rows)
        self.assertEqual(result['status'], 'available')
        self.assertFalse(result['actionAuthority'])
        self.assertIsNone(result['selection']['predictiveProbability'])
        return result

    def test_new_receipt_after_last_candidate_reuses_unchanged_study(self):
        day = fixture.DAYS[-1]
        row = fixture.row('credit.loss_pct', -1, date=day, periodEnd=day,
            availableFrom=day+'T07:00:00Z', knownAt=day+'T07:00:00Z')
        cache = {}; self.invoke(cache, [row]); key=cache['key']; study=cache['result']
        self.invoke(cache, [{**row, 'knownAt': day+'T08:00:00Z',
            'availableFrom': day+'T08:00:00Z', 'sourceRef': 'synthetic:new-receipt'}])
        self.assertEqual(self.walk.call_count, 2)
        self.assertEqual(self.search.call_count, 1)
        self.assertEqual(cache['key'], key)
        self.assertIs(cache['result'], study)

    def test_older_revision_used_by_yearly_scale_still_revalidates(self):
        row=fixture.row('credit.loss_pct', -3, date='2015-06-01', periodEnd='2015-06-01',
            availableFrom='2015-06-01T07:00:00Z', knownAt='2015-06-01T07:00:00Z')
        corrected={**row,'revision':1,'value':-1,'knownAt':'2015-12-01T07:00:00Z'}
        cache={}; self.invoke(cache,[row,corrected]); key=cache['key']
        self.invoke(cache,[{**row,'value':-8},corrected])
        self.assertEqual(self.walk.call_count,4)
        self.assertEqual(self.search.call_count,2)
        self.assertNotEqual(cache['key'],key)

    def test_receipt_crossing_year_boundary_still_revalidates(self):
        row=fixture.row('credit.loss_pct', -3, date='2015-06-01',periodEnd='2015-06-01',
            availableFrom='2015-06-01T07:00:00Z',knownAt='2025-12-31T23:59:59Z')
        cache={}; self.invoke(cache,[row]); key=cache['key']
        self.invoke(cache,[{**row,'knownAt':'2026-01-01T00:00:00Z'}])
        self.assertEqual(self.walk.call_count,4)
        self.assertEqual(self.search.call_count,2)
        self.assertNotEqual(cache['key'],key)

if __name__=='__main__':unittest.main(verbosity=2)
