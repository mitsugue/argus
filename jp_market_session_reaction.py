"""Offline cash-index reactions to an explicitly sourced event time.

These are reconstructed daily references, never an intraday event attribution,
a historically received vintage, or a probability. No collection or storage.
"""
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo
import hashlib
import json

TOKYO = ZoneInfo('Asia/Tokyo')
INSTRUMENT = 'NIKKEI_225_INDEX'

def instant(value):
    at = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if at.tzinfo is None:
        raise ValueError('timezone_required')
    return at

def session_close(day):
    d = date.fromisoformat(day)
    return datetime.combine(d, time(15, 30) if day >= '2024-11-05' else time(15), TOKYO)

def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()

#: 2026-10-18 owner decision: past releases (archived date, fixed release time)
#: are treated as known when the window's last close was published.
RESEARCH_TIME_BASIS = 'ARCHIVED_RELEASE_DATE_FIXED_TIME_RULE'
RESEARCH_AVAILABILITY = 'RESEARCH_KNOWN_AT_ENDPOINT_CLOSE'


def measure(*, event, rows, sessions, cutoff, instrument=INSTRUMENT, research_availability=False):
    if instrument != INSTRUMENT:
        raise ValueError('cash_index_identity_required')
    if len(rows) > 3000 or len(sessions) > 3000:
        raise ValueError('bounded_history_required')
    if list(sessions) != sorted(set(sessions)):
        raise ValueError('ordered_unique_calendar_required')
    for day in sessions:
        date.fromisoformat(day)
    now = instant(cutoff)
    at, received = instant(event['eventTime']), instant(event['receivedAt'])
    if received > now or at > now:
        raise ValueError('future_event_or_receipt')
    if not event.get('eventId') or not event.get('eventType') or not event.get('sourceRef') or not event.get('sourceSha256'):
        raise ValueError('event_provenance_required')
    if research_availability is not (event.get('timeBasis') == RESEARCH_TIME_BASIS):
        raise ValueError('research_time_basis_requires_research_availability')
    if not research_availability and event.get('timeBasis') not in {'OFFICIAL_EMBARGO_BOUNDARY', 'VERIFIED_ACTUAL_PUBLICATION'}:
        raise ValueError('scheduled_time_is_not_actual_evidence')
    before = [day for day in sessions if session_close(day) < at]
    after = [day for day in sessions if session_close(day) >= at]
    if not before:
        raise ValueError('baseline_calendar_missing')
    baseline = before[-1]
    prices = {}
    for row in rows:
        if row.get('instrumentId') != instrument:
            raise ValueError('cash_index_identity_required')
        day = row['date']; date.fromisoformat(day)
        if day in prices:
            raise ValueError('ambiguous_price_day')
        prices[day] = row
    output = []
    for count in (1, 3, 5):
        span = [baseline, *after[:count]]
        out = {'eventId': event['eventId'], 'eventType': event['eventType'],
               'instrumentId': instrument, 'reactionWindowSessions': count,
               'baselineDate': baseline, 'endpointDate': after[count-1] if len(after) >= count else None,
               'expectedDates': span, 'status': 'DATA_GATED', 'value': None, 'unit': 'PERCENT',
               'eventTime': event['eventTime'], 'eventTimeBasis': event['timeBasis'],
               'actualPublicationTimeVerified': event['timeBasis'] == 'VERIFIED_ACTUAL_PUBLICATION',
               'historicalVintageVerified': False, 'receivedAt': event['receivedAt'],
               'sourceRef': event['sourceRef'], 'eventSourceSha256': event['sourceSha256'],
               'basis': 'RECONSTRUCTED_DAILY_CLOSE_REFERENCE', 'actionAuthority': False, 'probability': None}
        if len(after) < count:
            out['reason'] = 'future_session_calendar_missing'
        elif session_close(span[-1]) > now:
            out['reason'] = 'endpoint_not_closed'
        elif any(day not in prices for day in span):
            out['reason'] = 'price_session_missing'
        else:
            selected = [prices[day] for day in span]
            values = []
            try:
                for row in selected:
                    if isinstance(row['close'], bool):
                        raise ValueError('invalid_price')
                    value = Decimal(str(row['close']))
                    if isinstance(row['close'], bool) or not value.is_finite() or value <= 0:
                        raise ValueError('invalid_price')
                    if instant(row['receivedAt']) > now:
                        raise ValueError('price_receipt_after_cutoff')
                    if instant(row['receivedAt']) < session_close(row['date']):
                        raise ValueError('price_receipt_before_close')
                    if not row.get('sourceSha256') or not row.get('sourceRef'):
                        raise ValueError('price_provenance_missing')
                    values.append(value)
            except (ValueError, KeyError, InvalidOperation):
                out['reason'] = 'price_or_receipt_invalid'
            else:
                known = (session_close(span[-1]) if research_availability else
                         max([received, *[instant(row['receivedAt']) for row in selected]]))
                out.update(status='AVAILABLE', value=float((values[-1] / values[0] - 1) * 100),
                           periodEnd=span[-1], date=span[-1], availableFrom=known.isoformat(),
                           availabilityBasis=RESEARCH_AVAILABILITY if research_availability else 'ACTUAL_RECEIPT',
                           sourceRowsHash=fingerprint(selected), sourceSessionDates=span)
        output.append(out)
    return output
