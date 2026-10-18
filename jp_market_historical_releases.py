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
