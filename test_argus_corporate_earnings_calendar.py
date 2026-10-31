from copy import deepcopy
from datetime import datetime,timezone
import pytest
from argus_corporate_earnings_calendar import scheduled_events
NOW=datetime(2026,10,31,1,tzinfo=timezone.utc)
SHARED=[('JP','1111','共有日本株'),('US','AAA','共有米国株'),('US','BBB','共有米国株2')]

def items():
    return {'JP:1111':{'scheduleStatus':'AVAILABLE','earnings':{'market':'JP','symbol':'1111',
        'source':'Yahoo Finance','fetchedAt':'2026-10-30T10:00:00Z','next':{'from':'2026-11-05','to':'2026-11-05',
        'certainty':'COMPANY_SCHEDULE','timezone':'Asia/Tokyo','source':'J-Quants 決算発表予定日',
        'fetchedAt':'2026-10-30T10:01:00Z','publishedDate':'2026-10-29'}}},
        'US:AAA':{'earnings':{'market':'US','symbol':'AAA','source':'Yahoo Finance','fetchedAt':'2026-10-30T10:00:00Z',
        'next':{'from':'2026-11-05','to':'2026-11-06','certainty':'PROVIDER_ESTIMATE','timezone':'America/New_York'}}}}

def run(d,now=NOW):return scheduled_events(d,shared_symbols=SHARED,now=now)

def test_company_and_us_range_keep_source_dates_and_never_claim_a_release():
    d=items();before=deepcopy(d);rows,gaps=run(d)
    assert len(rows)==2 and not gaps and d==before
    jp,us=rows
    assert jp['certainty']=='COMPANY_SCHEDULE' and jp['receivedAt']=='2026-10-30T10:01:00+00:00'
    assert us['sourceFromDate']=='2026-11-05' and us['sourceToDate']=='2026-11-06'
    assert us['sourceTimezone']=='America/New_York' and us['at'].endswith('-05:00')
    assert all(r['dateOnly'] and not r['actionAuthority'] for r in rows)
    assert not any(k in r for r in rows for k in ('eventTimeUtc','releasedAt','actual','price','estimate','company'))

@pytest.mark.parametrize('damage',['withdrawn','conflict','future_receipt','no_receipt','no_timezone','reverse','wide_range','wrong_symbol','wrong_market','wrong_source','future_publication','bad_day','shape'])
def test_invalid_source_never_becomes_a_calendar_event(damage):
    d=items();raw=d['JP:1111'];e=raw['earnings'];s=e['next']
    if damage=='withdrawn':raw['scheduleStatus']='NO_SCHEDULE'
    elif damage=='conflict':raw['scheduleStatus']='CONFLICT'
    elif damage=='future_receipt':s['fetchedAt']='2099-01-01T00:00:00Z'
    elif damage=='no_receipt':s['fetchedAt']=None;e['fetchedAt']=None
    elif damage=='no_timezone':s['timezone']='UTC'
    elif damage=='reverse':s['to']='2026-11-04'
    elif damage=='wide_range':s['to']='2026-12-31'
    elif damage=='wrong_symbol':e['symbol']='9999'
    elif damage=='wrong_market':e['market']='US'
    elif damage=='wrong_source':s['source']='arbitrary original body'
    elif damage=='future_publication':s['publishedDate']='2026-11-04'
    elif damage=='bad_day':s['from']='20261105'
    else:raw['earnings']=['not a record']
    assert all(r['market']!='JP' for r in run(d)[0])

def test_same_date_multiple_companies_remain_distinct_and_owner_rows_are_excluded():
    d=items();d['US:BBB']=deepcopy(d['US:AAA']);d['US:BBB']['earnings']['symbol']='BBB'
    d['US:PRIVATE']=deepcopy(d['US:AAA']);d['US:PRIVATE']['earnings']['symbol']='PRIVATE'
    rows,_=run(d)
    assert len(rows)==3 and len(set(r['eventId']for r in rows))==3
    assert 'PRIVATE' not in str(rows)

def test_us_date_survives_tokyo_next_day_and_is_removed_only_after_local_range_end():
    d=items();s=d['US:AAA']['earnings']['next'];s.update({'from':'2026-10-30','to':'2026-10-30'})
    rows,_=run(d,NOW)
    assert any(r['market']=='US' for r in rows)  # Still 10/30 evening in New York.
    assert all(r['market']!='US' for r in run(d,datetime(2026,10,31,4,1,tzinfo=timezone.utc))[0])

def test_stale_estimate_is_not_refreshed_by_a_new_local_receipt():
    d=items();d['US:AAA']['earnings']['fetchedAt']='2026-10-01T00:00:00Z'
    rows,gaps=run(d)
    assert all(r['market']!='US' for r in rows) and gaps==['corporate_earnings_estimate_stale']
