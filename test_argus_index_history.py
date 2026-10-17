from copy import deepcopy
from datetime import date,timedelta
import json
import pytest
import argus_index_history as h


def bar(day,value=100):
    return dict(instrumentId=h.INSTRUMENT,date=day,open=value,high=value+1,low=value-1,
        close=value,volume=1,availableFrom=day+'T07:00:00Z',sourceRef='synthetic')


def official_calendar(start,end):
    first,last=date.fromisoformat(start),date.fromisoformat(end)
    return [{'Date':(first+timedelta(days=i)).isoformat(),'HolDiv':'1' if (first+timedelta(days=i)).weekday()<5 else '0'}
        for i in range((last-first).days+1)]  # Synthetic provider-shaped data, not an exchange calendar.


def test_completed_inputs_are_reused_and_calendar_only_updates_its_tail():
    prior={'data':[bar('2016-09-16'),bar('2026-09-15')],
        'backfillRequestedStart':'2016-09-16','calendarCheckedDate':'2026-09-16',
        'calendar':official_calendar('2016-09-16','2026-09-16')}
    original=deepcopy(prior)
    def forbidden(*args,**kwargs):raise AssertionError('no full retrieval needed')
    same=h.refresh(prior,current_rows=[bar('2026-09-15')],now_iso='2026-09-16T08:00:00Z',
        get=forbidden,fetch_calendar=forbidden)
    assert same['historicalRequestsThisRefresh']==0 and same['data']==prior['data']
    calls=[]
    def calendar(start,end):calls.append((start,end));return official_calendar(start,end)
    newer=h.refresh(same,current_rows=[bar('2026-09-16')],now_iso='2026-09-17T08:00:00Z',
        get=forbidden,fetch_calendar=calendar)
    assert calls==[('2026-09-09','2026-09-17')]
    assert newer['historicalRequestsThisRefresh']==0
    assert prior==original


def test_backfill_only_requests_missing_interval_and_failure_preserves_existing_rows():
    received=[]
    def fail(url,**kwargs):received.append(kwargs['params']);raise TimeoutError()
    rows=[bar('2024-09-17'),bar('2026-09-15')]
    result=h.refresh({},current_rows=rows,now_iso='2026-09-16T08:00:00Z',get=fail,
        fetch_calendar=lambda *args: (_ for _ in ()).throw(TimeoutError()))
    assert result['data']==rows
    assert len(received)==1 and received[0]['period2']<1789516800
    assert result['backfillStatus']=='FAILED' and result['calendarStatus']=='FAILED'
    assert 'backfillRequestedStart' not in result


def test_missing_calendar_day_is_not_invented_as_closed():
    source=official_calendar('2026-09-01','2026-09-16');del source[3]
    with pytest.raises(ValueError,match='missing_days'):
        h.calendar_rows(source,start='2026-09-01',end='2026-09-16')


def test_instrument_confusion_and_integrity_damage_fail_closed(tmp_path):
    wrong=bar('2026-09-15');wrong['instrumentId']='1321'
    with pytest.raises(ValueError,match='instrument'):h.merge_bars([], [wrong])
    path=tmp_path/'history.json';body={'data':[bar('2026-09-15')]}
    path.write_text(json.dumps(h.envelope(body)))
    assert h.read(path)==body
    damaged=json.loads(path.read_text());damaged['body']['data'][0]['close']=200
    path.write_text(json.dumps(damaged))
    with pytest.raises(ValueError,match='integrity'):h.read(path)


def test_source_revision_changes_only_the_affected_bar_and_preserves_old_snapshot():
    old=[bar('2026-09-14'),bar('2026-09-15')];before=deepcopy(old)
    revised=h.merge_bars(old,[bar('2026-09-15',101)])
    assert old==before and revised[0]==old[0] and revised[1]['close']==101


def test_successful_backfill_is_persisted_and_repeated_use_does_not_fetch(tmp_path):
    stamp=1473984000
    body={'chart':{'result':[{'meta':{'symbol':'^N225','gmtoffset':32400},
        'timestamp':[stamp], 'indicators':{'quote':[{'open':[100], 'high':[101],
        'low':[99], 'close':[100], 'volume':[0]}]}}]}}
    class Response:
        status_code=200
        content=json.dumps(body).encode()
        def json(self):return body
        def close(self):pass
    calls=[]
    def get(*args,**kwargs):calls.append(kwargs['params']);return Response()
    result=h.refresh({},current_rows=[bar('2024-09-17'),bar('2026-09-15')],
        now_iso='2026-09-16T08:00:00Z',get=get,fetch_calendar=official_calendar)
    assert result['sourceStart']=='2016-09-16'
    assert result['backfillStatus']=='AVAILABLE' and len(calls)==1
    path=tmp_path/'inputs.json';path.write_text(json.dumps(h.envelope(result)))
    restored=h.read(path)
    def forbidden(*args,**kwargs):pytest.fail('saved inputs must be reused')
    again=h.refresh(restored,current_rows=[bar('2026-09-15')],
        now_iso='2026-09-16T09:00:00Z',get=forbidden,fetch_calendar=forbidden)
    assert again['historicalRequestsThisRefresh']==0 and again['data']==restored['data']
    assert not again['historicalVintageVerified']


def test_failed_backfill_and_calendar_do_not_retry_on_every_collection():
    calls=[]
    def fail(*args,**kwargs):calls.append(True);raise TimeoutError()
    first=h.refresh({},current_rows=[bar('2024-09-17')],
        now_iso='2026-09-16T08:00:00Z',get=fail,fetch_calendar=fail)
    second=h.refresh(first,current_rows=[bar('2024-09-17')],
        now_iso='2026-09-16T09:00:00Z',get=fail,fetch_calendar=fail)
    assert len(calls)==2 and second['historicalRequestsThisRefresh']==0
    assert second['backfillStatus']=='FAILED' and second['calendarStatus']=='FAILED'
