import copy
import unittest
from jp_market_session_reaction import measure, session_close

DAYS=['2026-09-11','2026-09-14','2026-09-15','2026-09-16','2026-09-17','2026-09-18']
E={'eventId':'e','eventType':'CPI','eventTime':'2026-09-11T12:30:00Z','receivedAt':'2026-10-11T00:00:00Z','sourceRef':'official:release','sourceSha256':'a'*64,'timeBasis':'OFFICIAL_EMBARGO_BOUNDARY'}
ROWS=[{'instrumentId':'NIKKEI_225_INDEX','date':d,'close':100+i,'receivedAt':'2026-10-11T00:00:00Z','sourceRef':'retained:cash','sourceSha256':'b'*64}for i,d in enumerate(DAYS)]
def run(rows=ROWS, event=E, sessions=DAYS, cutoff='2026-10-11T00:05:00Z'):
    return measure(event=event,rows=rows,sessions=sessions,cutoff=cutoff)
class ReactionTest(unittest.TestCase):
    def test_weekend_does_not_count_and_horizons_are_distinct(self):
        r=run(); self.assertEqual([x['endpointDate']for x in r],['2026-09-14','2026-09-16','2026-09-18'])
        self.assertEqual([round(x['value'],8)for x in r],[1,3,5])
        self.assertTrue(all(x['historicalVintageVerified'] is False and x['actualPublicationTimeVerified'] is False for x in r))
    def test_missing_intermediate_session_blocks_long_window(self):
        r=run(rows=[x for x in ROWS if x['date']!='2026-09-15']); self.assertEqual([x['status']for x in r],['AVAILABLE','DATA_GATED','DATA_GATED'])
    def test_invalid_intermediate_price_is_not_bridged(self):
        for value in (0,float('nan'),float('inf'),True):
            rows=copy.deepcopy(ROWS); rows[2]['close']=value
            self.assertEqual(run(rows=rows)[1]['status'],'DATA_GATED')
    def test_future_or_unproven_receipt_is_rejected(self):
        rows=copy.deepcopy(ROWS); rows[2]['receivedAt']='2026-10-12T00:00:00Z'
        self.assertEqual(run(rows=rows)[1]['status'],'DATA_GATED')
        rows[2]['receivedAt']='2026-09-14T00:00:00Z';self.assertEqual(run(rows=rows)[1]['status'],'DATA_GATED')
    def test_schedule_cannot_prove_an_actual_release(self):
        event={**E,'timeBasis':'SCHEDULED'}
        with self.assertRaises(ValueError):run(event=event)
    def test_duplicate_and_identity_rejected(self):
        with self.assertRaises(ValueError):run(rows=[*ROWS,ROWS[0]])
        rows=copy.deepcopy(ROWS);rows[0]['instrumentId']='TOPIX_PROXY'
        with self.assertRaises(ValueError):run(rows=rows)
    def test_missing_calendar_or_unclosed_endpoint_is_not_ready(self):
        self.assertEqual(run(sessions=DAYS[:3])[1]['status'],'DATA_GATED')
        r=run(rows=[{**x,'receivedAt':x['date']+'T06:31:00Z'}for x in ROWS],event={**E,'receivedAt':'2026-09-11T12:30:01Z'},cutoff='2026-09-16T06:00:00Z')
        self.assertEqual(r[1]['reason'],'endpoint_not_closed')
    def test_close_boundary_and_historical_hours(self):
        self.assertEqual(session_close('2024-11-01').hour,15)
        self.assertEqual(session_close('2024-11-01').minute,0)
        self.assertEqual(session_close('2024-11-05').minute,30)
        e={**E,'eventTime':'2026-09-11T06:30:00Z'}
        with self.assertRaises(ValueError):run(event=e)
if __name__=='__main__': unittest.main()
