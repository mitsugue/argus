import copy
import unittest
import json
import tempfile
from pathlib import Path
from datetime import date,timedelta

from jp_market_features import (build_market_features, build_feature_history,
    history_cache_envelope, load_history_cache, history_method_identity)


def prices(instrument, count=60, start=100, change=.1, **extra):
    return [{'instrumentId':instrument, 'field':'close', 'date':(date(2026,6,1)+timedelta(days=i)).isoformat(),
             'availableFrom':(date(2026,6,1)+timedelta(days=i)).isoformat()+'T07:00:00Z',
             'value':start+i*change, **extra} for i in range(count)]


class MarketFeaturesTest(unittest.TestCase):
    def test_cache_roundtrip_preserves_all_values_provenance_and_limits(self):
        at = '2026-08-01T00:00:00Z'
        history = {**build_feature_history(cutoffs=[at], price_series={'vix': prices('VIX')}),
                   'status': 'AVAILABLE', 'inputIdentity': 'a' * 64,
                   'lastSuccessfulCalculationAt': at}
        method = history_method_identity()
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'cache.json'
            doc = history_cache_envelope(history, method=method)
            path.write_text(json.dumps(doc))
            self.assertEqual(history, load_history_cache(path, method=method, now=at))
            self.assertIsNone(load_history_cache(path, method='b' * 64, now=at))
            with self.assertRaisesRegex(ValueError, 'future'):
                load_history_cache(path, method=method, now='2026-07-31T00:00:00Z')
            doc['history']['features'][0]['value'] += 10
            path.write_text(json.dumps(doc))
            with self.assertRaisesRegex(ValueError, 'integrity'):
                load_history_cache(path, method=method, now=at)

    def test_cache_cannot_promote_vintage_or_action_authority(self):
        at = '2026-08-01T00:00:00Z'
        history = {**build_feature_history(cutoffs=[at], price_series={}),
                   'status': 'AVAILABLE', 'inputIdentity': 'a' * 64,
                   'lastSuccessfulCalculationAt': at}
        for field in ('historicalVintageVerified', 'actionAuthority'):
            with self.assertRaisesRegex(ValueError, 'identity'):
                history_cache_envelope({**history, field: True}, method='b' * 64)

    def test_future_corrections_and_other_instruments_do_not_change_values(self):
        raw={'vix':prices('VIX',start=20), 'nikkei':prices('NIKKEI_225_INDEX')}
        cutoff='2026-08-01T00:00:00Z'
        first=build_market_features(cutoff=cutoff,price_series=raw)
        changed=copy.deepcopy(raw)
        changed['vix'] += [dict(raw['vix'][-1],value=90,revision=1,knownAt='2026-09-01T00:00:00Z')]
        changed['vix'] += prices('1321')
        self.assertEqual(first,build_market_features(cutoff=cutoff,price_series=changed))
        self.assertFalse(first['observedCoveringOrders'])
        self.assertFalse(first['actionAuthority'])

    def test_negative_yield_and_units_not_conflated_with_price_returns(self):
        raw={'jp10y':prices('JP10Y',start=-.2,change=.001,unit='PERCENT'),
             'us10y':prices('US10Y',start=40,unit='INDEX_POINTS')}
        result=build_market_features(cutoff='2026-08-01T00:00:00Z',price_series=raw)
        fields={row['seriesId']:row for row in result['features']}
        self.assertAlmostEqual(fields['rate.jp10y_change5']['value'],.005)
        self.assertIn('rate.us10y_change5',result['missingFeatures'])
        self.assertEqual(fields['rate.jp10y_change5']['unit'],'PERCENTAGE_POINTS')

    def test_direct_index_relative_strength_does_not_substitute_etf(self):
        raw={'nikkei':prices('NIKKEI_225_INDEX'), 'sp500':prices('SPY')}
        absent=build_market_features(cutoff='2026-08-01T00:00:00Z',price_series=raw)
        self.assertIn('relative_jp_us.return20',absent['missingFeatures'])
        raw['sp500']=prices('SP500_INDEX')
        present=build_market_features(cutoff='2026-08-01T00:00:00Z',price_series=raw)
        value=next(row for row in present['features'] if row['seriesId']=='relative_jp_us.return20')
        self.assertEqual(value['value'],0)
        self.assertEqual(len(value['inputReferences']),42)

    def test_sq_distance_is_bound_to_its_actual_calculation_day(self):
        from jp_market_events import sq_calendar
        from test_jp_market_events import SOURCE
        from datetime import datetime
        now = datetime.fromisoformat('2026-10-08T08:00:00+09:00')
        events = sq_calendar(now=now, schedule=SOURCE)['events']
        result = build_market_features(cutoff=now.isoformat(), price_series={}, sq_events=events)
        fact = next(row for row in result['features'] if row['seriesId'] == 'event.sq_sessions')
        self.assertEqual(fact['value'], 1)
        previous = build_market_features(cutoff='2026-10-07T08:00:00+09:00', price_series={}, sq_events=events)
        self.assertIn('event.sq_sessions', previous['missingFeatures'])

    def test_unrelated_fields_cannot_become_extra_price_observations(self):
        original = prices('VIX', start=20)
        unrelated = [dict(row, field='volume', value=10000) for row in original]
        first = build_market_features(cutoff='2026-08-01T00:00:00Z', price_series={'vix': original})
        second = build_market_features(cutoff='2026-08-01T00:00:00Z', price_series={'vix': original + unrelated})
        self.assertEqual(first, second)

    def test_mismatched_nt_sessions_remain_unknown(self):
        raw={'nikkei':prices('NIKKEI_225_INDEX'), 'topix':prices('TOPIX_INDEX')[:-1]}
        result=build_market_features(cutoff='2026-08-01T00:00:00Z',price_series=raw)
        self.assertIn('nt.ratio_change5',result['missingFeatures'])


if __name__=='__main__':
    unittest.main()
