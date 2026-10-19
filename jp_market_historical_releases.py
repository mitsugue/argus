"""Past US release events from archived release dates and fixed release times (2026-10-18).

BLS refuses automated reads of its release documents (HTTP 403 from every
place tried on 2026-10-18), so the embargo line cannot be read per release.
Owner decision 2026-10-18: past releases take their date from the St. Louis
Fed archive of release dates (FRED release/dates, actual dates including
moved ones) and their time from the fixed BLS release time of each series.

The Nikkei reaction compares Tokyo closes before and after the release, so
any release time between the Tokyo close and the next Tokyo close gives the
same windows; the date decides the result, the time only places it in the
US day. This is a rule-derived time, never an observed publication time.
Pure functions: no clock, no store, no network.
"""
from datetime import date, datetime, time, timezone
import hashlib
import json
from typing import Any, Dict, List
from zoneinfo import ZoneInfo

SCHEMA = 'jp-market-historical-release-events-v1'
TIME_BASIS = 'ARCHIVED_RELEASE_DATE_FIXED_TIME_RULE'
SOURCE = 'https://api.stlouisfed.org/fred/release/dates'
FIRST_DATE = '2016-01-01'
MAX_DATES = 400
#: event code (as in the event calendar) -> FRED release id and BLS release time (ET)
RELEASES = {
    'nfp': (50, time(8, 30)),     # Employment Situation
    'cpi': (10, time(8, 30)),     # Consumer Price Index
    'ppi': (46, time(8, 30)),     # Producer Price Index
    'jolts': (192, time(10, 0)),  # Job Openings and Labor Turnover Survey
}
_EASTERN = ZoneInfo('America/New_York')


def request_params(code: str) -> Dict[str, Any]:
    """Query for one release; the key is added by the caller and never stored."""
    release_id, _ = RELEASES[code]
    return {'release_id': release_id, 'realtime_start': FIRST_DATE, 'file_type': 'json',
            'sort_order': 'asc', 'include_release_dates_with_no_data': 'false', 'limit': 1000}


def events(code: str, raw: bytes, *, received_at: str) -> List[Dict[str, Any]]:
    """Release events of one series from one archived release-dates response."""
    if code not in RELEASES or not isinstance(raw, bytes) or not 0 < len(raw) <= 512 * 1024:
        raise ValueError('bounded_release_dates_response_required')
    received = datetime.fromisoformat(received_at.replace('Z', '+00:00'))
    if received.tzinfo is None:
        raise ValueError('receipt_timezone_required')
    body = json.loads(raw)
    release_id, at_et = RELEASES[code]
    rows = body.get('release_dates') if isinstance(body, dict) else None
    if not isinstance(rows, list) or len(rows) > MAX_DATES:
        raise ValueError('release_dates_shape_or_bound')
    digest = hashlib.sha256(raw).hexdigest()
    out, seen = [], set()
    for row in rows:
        if not isinstance(row, dict) or row.get('release_id') != release_id:
            raise ValueError('release_dates_identity')
        day = date.fromisoformat(str(row.get('date')))
        moment = datetime.combine(day, at_et, _EASTERN).astimezone(timezone.utc)
        if day.isoformat() < FIRST_DATE or day.isoformat() in seen or moment > received:
            continue   # before the window, repeated, or not yet released at receipt
        seen.add(day.isoformat())
        out.append({'schemaVersion': SCHEMA, 'eventId': f'hist-{code}-{day.isoformat()}', 'eventType': code,
                    'releaseDate': day.isoformat(), 'eventTime': moment.isoformat(),
                    'timeBasis': TIME_BASIS, 'sourceRef': f'{SOURCE}?release_id={release_id}',
                    'sourceSha256': digest, 'receivedAt': received.isoformat(),
                    'actualPublicationTimeVerified': False, 'historicalVintageVerified': False})
    return out


# 2026-10-19: central-bank decisions are added to the same past-release study.
# FRED has no archive of their dates (its "FOMC Press Release" is updated every
# day), so the decision days are the ones each bank publishes, read on
# 2026-10-19 from federalreserve.gov (fomccalendars.htm and
# fomchistorical<year>.htm) and boj.or.jp (mpmsche_minu/past.htm, index.htm).
# Scheduled meetings with a policy statement, plus the two unscheduled 2020
# rate cuts. The time is a rule, never an observed publication time: the FOMC
# statement at 14:00 New York time; the Bank of Japan announces its result
# during the Tokyo session, which any time before the close places alike.
SCHEDULE_TIME_BASIS = TIME_BASIS
FOMC_DECISION_DAYS = (
    '2016-01-27', '2016-03-16', '2016-04-27', '2016-06-15', '2016-07-27', '2016-09-21', '2016-11-02', '2016-12-14',
    '2017-02-01', '2017-03-15', '2017-05-03', '2017-06-14', '2017-07-26', '2017-09-20', '2017-11-01', '2017-12-13',
    '2018-01-31', '2018-03-21', '2018-05-02', '2018-06-13', '2018-08-01', '2018-09-26', '2018-11-08', '2018-12-19',
    '2019-01-30', '2019-03-20', '2019-05-01', '2019-06-19', '2019-07-31', '2019-09-18', '2019-10-30', '2019-12-11',
    '2020-01-29', '2020-03-03', '2020-03-15', '2020-04-29', '2020-06-10', '2020-07-29', '2020-09-16', '2020-11-05',
    '2020-12-16',
    '2021-01-27', '2021-03-17', '2021-04-28', '2021-06-16', '2021-07-28', '2021-09-22', '2021-11-03', '2021-12-15',
    '2022-01-26', '2022-03-16', '2022-05-04', '2022-06-15', '2022-07-27', '2022-09-21', '2022-11-02', '2022-12-14',
    '2023-02-01', '2023-03-22', '2023-05-03', '2023-06-14', '2023-07-26', '2023-09-20', '2023-11-01', '2023-12-13',
    '2024-01-31', '2024-03-20', '2024-05-01', '2024-06-12', '2024-07-31', '2024-09-18', '2024-11-07', '2024-12-18',
    '2025-01-29', '2025-03-19', '2025-05-07', '2025-06-18', '2025-07-30', '2025-09-17', '2025-10-29', '2025-12-10',
    '2026-01-28', '2026-03-18', '2026-04-29', '2026-06-17', '2026-07-29', '2026-09-16', '2026-10-28', '2026-12-09',
)
#: The unscheduled 2020 cuts: 10:00 on 3 March, 17:00 on Sunday 15 March (New York).
FOMC_TIME_EXCEPTIONS = {'2020-03-03': time(10, 0), '2020-03-15': time(17, 0)}
BOJ_DECISION_DAYS = (
    '2016-01-29', '2016-03-15', '2016-04-28', '2016-06-16', '2016-07-29', '2016-09-21', '2016-11-01', '2016-12-20',
    '2017-01-31', '2017-03-16', '2017-04-27', '2017-06-16', '2017-07-20', '2017-09-21', '2017-10-31', '2017-12-21',
    '2018-01-23', '2018-03-09', '2018-04-27', '2018-06-15', '2018-07-31', '2018-09-19', '2018-10-31', '2018-12-20',
    '2019-01-23', '2019-03-15', '2019-04-25', '2019-06-20', '2019-07-30', '2019-09-19', '2019-10-31', '2019-12-19',
    '2020-01-21', '2020-03-16', '2020-04-27', '2020-05-22', '2020-06-16', '2020-07-15', '2020-09-17', '2020-10-29',
    '2020-12-18',
    '2021-01-21', '2021-03-19', '2021-04-27', '2021-06-18', '2021-07-16', '2021-09-22', '2021-10-28', '2021-12-17',
    '2022-01-18', '2022-03-18', '2022-04-28', '2022-06-17', '2022-07-21', '2022-09-22', '2022-10-28', '2022-12-20',
    '2023-01-18', '2023-03-10', '2023-04-28', '2023-06-16', '2023-07-28', '2023-09-22', '2023-10-31', '2023-12-19',
    '2024-01-23', '2024-03-19', '2024-04-26', '2024-06-14', '2024-07-31', '2024-09-20', '2024-10-31', '2024-12-19',
    '2025-01-24', '2025-03-19', '2025-05-01', '2025-06-17', '2025-07-31', '2025-09-19', '2025-10-30', '2025-12-19',
    '2026-01-23', '2026-03-19', '2026-04-28', '2026-06-16', '2026-07-31', '2026-09-18', '2026-10-30', '2026-12-18',
)
_TOKYO = ZoneInfo('Asia/Tokyo')
SCHEDULES = {
    'fomc': (FOMC_DECISION_DAYS, time(14, 0), _EASTERN, FOMC_TIME_EXCEPTIONS,
             'https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm'),
    'boj': (BOJ_DECISION_DAYS, time(12, 0), _TOKYO, {},
            'https://www.boj.or.jp/mopo/mpmsche_minu/past.htm'),
}


def scheduled_events(code: str, *, received_at: str) -> List[Dict[str, Any]]:
    """Past decisions of one central bank from its published schedule (no network)."""
    if code not in SCHEDULES:
        raise ValueError('unknown_schedule')
    received = datetime.fromisoformat(received_at.replace('Z', '+00:00'))
    if received.tzinfo is None:
        raise ValueError('receipt_timezone_required')
    days, at_local, zone, exceptions, source = SCHEDULES[code]
    if list(days) != sorted(set(days)):
        raise ValueError('ordered_unique_schedule_required')
    digest = hashlib.sha256(json.dumps([code, list(days), sorted((k, v.isoformat()) for k, v in exceptions.items())],
                                       separators=(',', ':')).encode()).hexdigest()
    out = []
    for text in days:
        day = date.fromisoformat(text)
        moment = datetime.combine(day, exceptions.get(text, at_local), zone).astimezone(timezone.utc)
        if text < FIRST_DATE or moment > received:
            continue
        out.append({'schemaVersion': SCHEMA, 'eventId': f'hist-{code}-{text}', 'eventType': code,
                    'releaseDate': text, 'eventTime': moment.isoformat(),
                    'timeBasis': SCHEDULE_TIME_BASIS, 'sourceRef': source,
                    'sourceSha256': digest, 'receivedAt': received.isoformat(),
                    'actualPublicationTimeVerified': False, 'historicalVintageVerified': False})
    return out
