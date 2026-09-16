"""Persistent bounded N225 comparison inputs; no LLM or request-time collection."""
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path

SCHEMA = 'jp-index-comparison-inputs-v1'
MAX_BARS = 3000
MAX_DAYS = 4000
MAX_BYTES = 4 * 1024 * 1024
INSTRUMENT = 'NIKKEI_225_INDEX'


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def boundary(day):
    day=date.fromisoformat(day)
    try: return day.replace(year=day.year-10).isoformat()
    except ValueError:return day.replace(year=day.year-10,day=28).isoformat()


def merge_bars(prior, incoming):
    by={}
    for row in [*prior,*incoming]:
        if row.get('instrumentId') != INSTRUMENT: raise ValueError('index_instrument_mismatch')
        date.fromisoformat(row['date'])
        at=datetime.fromisoformat(row['availableFrom'].replace('Z','+00:00'))
        if at.tzinfo is None: raise ValueError('index_availability_timezone')
        for field in ('open','high','low','close','volume'):
            value=row.get(field)
            if type(value) not in (int,float) or not math.isfinite(value) or value < 0 or (field!='volume' and value==0):
                raise ValueError('index_bar_value')
        if row['high'] < max(row['open'],row['close'],row['low']) or row['low'] > min(row['open'],row['close']):
            raise ValueError('index_bar_range')
        by[row['date']]=deepcopy(row)
    output=[by[k] for k in sorted(by)]
    if len(output)>MAX_BARS:raise ValueError('index_bar_bound')
    return output


def calendar_rows(rows, *, start, end):
    lo,hi=date.fromisoformat(start),date.fromisoformat(end)
    if not 0 <= (hi-lo).days < MAX_DAYS:raise ValueError('calendar_range_bound')
    by={}
    for row in rows:
        day=str(row.get('Date') or row.get('date') or '')
        flag=str(row.get('HolDiv',row.get('HolidayDivision','')))
        if not start<=day<=end:continue
        date.fromisoformat(day)
        if flag not in {'0','1','2','3'}:raise ValueError('calendar_unknown_flag')
        if day in by and by[day]!=flag:raise ValueError('calendar_conflicting_day')
        by[day]=flag
    expected={(lo+timedelta(days=i)).isoformat() for i in range((hi-lo).days+1)}
    if set(by)!=expected:raise ValueError('calendar_missing_days')
    return [{'Date':day,'HolDiv':by[day]} for day in sorted(by)]


def parse_yahoo(body, *, start, end):
    result=(body.get('chart') or {}).get('result') or []
    if len(result)!=1 or (result[0].get('meta') or {}).get('symbol')!='^N225':
        raise ValueError('unexpected_index_source')
    data=result[0]; offset=int(data['meta']['gmtoffset']); quote=data['indicators']['quote'][0]
    rows=[]
    for i,stamp in enumerate(data.get('timestamp') or []):
        day=datetime.fromtimestamp(stamp+offset,timezone.utc).date().isoformat()
        if not start<=day<=end:continue
        values={field:quote.get(field,[])[i] if i<len(quote.get(field,[])) else None
            for field in ('open','high','low','close','volume')}
        if any(value is None for value in values.values()):continue
        rows.append({'instrumentId':INSTRUMENT,'date':day,**values,'availableFrom':day+'T07:00:00Z',
            'adjusted':False,'sourceRef':'yahoo:chart:^N225'})
    return merge_bars([],rows)


def read(path):
    path=Path(path)
    if path.is_symlink():raise ValueError('index_history_symlink')
    with path.open('rb') as stream:raw=stream.read(MAX_BYTES+1)
    if len(raw)>MAX_BYTES:raise ValueError('index_history_size')
    value=json.loads(raw); body=value['body']
    if value.get('schemaVersion')!=SCHEMA or value.get('sha256')!=digest(body):raise ValueError('index_history_integrity')
    merge_bars([],body['data'])
    if body.get('calendar'):
        calendar_rows(body['calendar'],start=body['calendar'][0]['Date'],end=body['calendar'][-1]['Date'])
    return body


def envelope(body):
    return {'schemaVersion':SCHEMA,'body':body,'sha256':digest(body)}


def refresh(prior, *, current_rows, now_iso, get, fetch_calendar):
    """Reuse stored bars; backfill only the missing older interval, then rolling corrections.

    Caller invokes on the existing collection lane and atomically persists the
    result. A calendar failure never substitutes observed price dates for it.
    """
    now=datetime.fromisoformat(now_iso.replace('Z','+00:00'))
    today=now.date().isoformat(); start=boundary(today)
    result=deepcopy(prior or {})
    rows=merge_bars([row for row in result.get('data',[]) if row['date']>=start],current_rows)
    result.update(data=rows,requestedStart=start,automaticAiCalls=0,historicalVintageVerified=False)
    requests_made=0
    requested_before=result.get('backfillRequestedStart')
    if (not requested_before or requested_before>start) and result.get('backfillAttemptDate')!=today:
        result['backfillAttemptDate']=today
        oldest=rows[0]['date'] if rows else today
        end=(date.fromisoformat(oldest)-timedelta(days=1)).isoformat()
        if end>=start:
            params={'interval':'1d','period1':int(datetime.fromisoformat(start).replace(tzinfo=timezone.utc).timestamp()),
                'period2':int(datetime.fromisoformat(oldest).replace(tzinfo=timezone.utc).timestamp())}
            response=None
            try:
                requests_made+=1
                response=get('https://query1.finance.yahoo.com/v8/finance/chart/%5EN225',params=params,
                    headers={'User-Agent':'Mozilla/5.0 (argus)'},timeout=15)
                if response.status_code!=200:raise ValueError('index_backfill_http_'+str(response.status_code))
                raw=response.content
                if not isinstance(raw,bytes) or len(raw)>MAX_BYTES:raise ValueError('index_backfill_size')
                older=parse_yahoo(response.json(),start=start,end=end)
                if not older:raise ValueError('index_backfill_empty')
                result['data']=merge_bars(older,rows)
                result.pop('backfillErrorClass',None)
                result.update(backfillRequestedStart=start,backfillAcquiredAt=now_iso,
                    backfillSourceSha256=hashlib.sha256(raw).hexdigest(),backfillStatus='AVAILABLE')
            except Exception as exc:
                result.update(backfillStatus='FAILED',backfillErrorClass=type(exc).__name__)
            finally:
                if response is not None:response.close()
        else:result.update(backfillRequestedStart=start,backfillStatus='NOT_NEEDED')
    known=result.get('calendar') or []
    # An official daily calendar is tiny. Initial bounded retrieval is one
    # range; after that only new dates plus a seven-day correction overlap.
    need_calendar=not known or known[0]['Date']>start or result.get('calendarCheckedDate')!=today
    if need_calendar and result.get('calendarAttemptDate')!=today:
        result['calendarAttemptDate']=today
        calendar_start=start if not known or known[0]['Date']>start else max(start,
            (date.fromisoformat(known[-1]['Date'])-timedelta(days=7)).isoformat())
        try:
            fetched=calendar_rows(fetch_calendar(calendar_start,today),start=calendar_start,end=today)
            kept=[row for row in known if start<=row['Date']<calendar_start]
            result.pop('calendarErrorClass',None)
            result.update(calendar=calendar_rows([*kept,*fetched],start=start,end=today),
                calendarStatus='AVAILABLE',calendarCheckedDate=today,calendarAcquiredAt=now_iso,
                calendarSource='jquants:/markets/calendar')
        except Exception as exc:
            result.update(calendarStatus='FAILED',calendarErrorClass=type(exc).__name__)
    result.update(lastAttemptAt=now_iso,historicalRequestsThisRefresh=requests_made,
        sourceStart=result['data'][0]['date'] if result['data'] else None,
        sourceEnd=result['data'][-1]['date'] if result['data'] else None)
    return result
