"""Cache-only daily cash-index references from separately evidenced event times.

Scheduled event times and intraday reactions are not inputs to this adapter.
It reuses the macro record and index caches; it has no collector or store.
"""
from collections import Counter
from copy import deepcopy
from datetime import date
import math
import re

from jp_market_session_reaction import measure, instant, fingerprint, INSTRUMENT

MAX_EVENTS = 200
MAX_BARS = 3000


def _hash(value):
    return isinstance(value, str) and re.fullmatch(r'[0-9a-f]{64}', value) is not None


def cash_rows(history, current):
    """Conservatively bound retained history by its last source receipts.

    A snapshot digest identifies selected cache content, never original HTTP
    bytes. Batch receipts cannot establish each historical row's first receipt.
    The later receipt bounds the whole retained snapshot instead.
    """
    result = {}
    batches = []
    if history.get('data'):
        required = [('currentSourceAcquiredAt', 'currentSourceSha256')]
        if (history.get('backfillStatus') == 'AVAILABLE'
                or history.get('backfillAcquiredAt') or history.get('backfillSourceSha256')):
            required.append(('backfillAcquiredAt', 'backfillSourceSha256'))
        try:
            stamps = [instant(history[t]) for t, h in required if _hash(history.get(h))]
            if len(stamps) != len(required):
                raise ValueError('retained_price_receipt_missing')
            batches.append((history['data'], max(stamps),
                            [history[h] for t, h in required], 'RETAINED_BATCH_LATEST_RECEIPT'))
        except (ValueError, KeyError, TypeError, AttributeError):
            pass
    if current.get('data') and _hash(current.get('sourceResponseSha256')):
        try:
            batches.append((current['data'], instant(current['acquiredAt']),
                            [current['sourceResponseSha256']], 'CURRENT_BATCH_RECEIPT'))
        except (ValueError, KeyError, TypeError, AttributeError):
            pass
    if sum(len(rows) for rows, *_ in batches) > MAX_BARS * 2:
        raise ValueError('price_input_bound_exceeded')
    for rows, received, source_hashes, basis in batches:
        seen = set()
        for raw in rows:
            if raw.get('instrumentId') != INSTRUMENT or raw.get('sourceRef') != 'yahoo:chart:^N225':
                raise ValueError('cash_source_identity_required')
            day = raw['date']; date.fromisoformat(day)
            if day in seen:
                raise ValueError('duplicate_cash_batch_day')
            seen.add(day)
            row = {'instrumentId': INSTRUMENT, 'date': day, 'seriesId': 'close',
                   'close': raw.get('close'), 'receivedAt': received.isoformat(),
                   'availableFrom': received.isoformat(), 'receiptBasis': basis,
                   'sourceRef': raw['sourceRef'], 'sourceResponseHashReferences': source_hashes,
                   'sourceSha256': fingerprint({'selectedRow': raw, 'responseHashReferences': source_hashes}),
                   'sourceHashBasis': 'SELECTED_CACHE_CONTENT_NOT_RAW_HTTP_BODY',
                   'historicalVintageVerified': False}
            # A newer current cache replaces a whole same-day row. An older
            # cache cannot overwrite more recently received retained history.
            if day not in result or received >= instant(result[day]['receivedAt']):
                result[day] = row
    if len(result) > MAX_BARS:
        raise ValueError('price_history_bound_exceeded')
    return [result[d] for d in sorted(result)]


def cached_reactions(records, *, rows, sessions, cutoff):
    """Read explicit source-time evidence from existing macro-event records.

    eventTimeEvidence is optional compatible metadata in the existing record.
    Its absence stays gated; eventTimeUtc/releasedAt/firstSeenAt cannot fill it.
    """
    if len(records) > MAX_EVENTS:
        raise ValueError('macro_event_bound_exceeded')
    reasons = Counter(); output = []
    for record in records:
        evidence = record.get('eventTimeEvidence')
        if not isinstance(evidence, dict):
            reasons['event_source_time_evidence_missing'] += 1
            continue
        event = deepcopy(evidence)
        if (event.get('eventId') != record.get('eventId')
                or event.get('eventType') != record.get('eventCode')
                or not _hash(event.get('sourceSha256'))):
            reasons['event_evidence_identity_invalid'] += 1
            continue
        if (event.get('timeBasis') == 'VERIFIED_ACTUAL_PUBLICATION'
                and (event.get('actualPublicationTimeVerified') is not True
                     or event.get('sourceEvidenceKind') != 'OBSERVED_HTTP_PUBLICATION_RECORD')):
            reasons['actual_publication_proof_missing'] += 1
            continue
        try:
            references = measure(event=event, rows=rows, sessions=sessions, cutoff=cutoff)
        except (ValueError, KeyError, TypeError, AttributeError):
            reasons['event_or_cash_evidence_invalid'] += 1
            continue
        for row in references:
            if row['status'] != 'AVAILABLE':
                reasons[row['reason']] += 1
                continue
            value = row['value']
            if isinstance(value, bool) or not math.isfinite(value):
                reasons['nonfinite_reaction'] += 1
                continue
            row.update(seriesId='material_reaction.' + row['eventType'] + '.' + str(row['reactionWindowSessions']),
                       derivationBasis='DAILY_CLOSE_REFERENCE_NOT_INTRADAY_ATTRIBUTION',
                       eventReceiptBasis=event.get('receiptBasis'),
                       eventRawHttpBodyRead=event.get('rawHttpBodyRead') is True,
                       validationStatus='UNVALIDATED')
            row['sourceSha256'] = fingerprint(row)
            output.append(row)
    return {'rows': output, 'diagnostics': {
        'status': 'AVAILABLE' if output else 'DATA_GATED', 'eventCount': len(records),
        'availableReferenceWindows': len(output), 'gatedReasonCounts': dict(sorted(reasons.items())),
        'historicalVintageVerified': False, 'automaticAiCalls': 0, 'externalRequests': 0,
        'productionWrites': 0, 'actionAuthority': False, 'probability': None}}


#: Past release events read per comparison (four series, about ten years).
MAX_HISTORICAL_EVENTS = 800


def historical_reactions(events, *, rows, sessions, cutoff, exclude=()):
    """Reaction windows of past releases, known at each window's last close.

    Owner decision 2026-10-18: research availability, a separate basis from the
    receipts above. `exclude` holds (seriesId, date) already measured from
    evidenced records, which take precedence; a later close cannot rewrite them.
    """
    if len(events) > MAX_HISTORICAL_EVENTS:
        raise ValueError('historical_event_bound_exceeded')
    taken = set(exclude); reasons = Counter(); output = []
    for event in events:
        try:
            references = measure(event=event, rows=rows, sessions=sessions, cutoff=cutoff,
                                 research_availability=True)
        except (ValueError, KeyError, TypeError, AttributeError):
            reasons['historical_event_or_cash_evidence_invalid'] += 1
            continue
        for row in references:
            if row['status'] != 'AVAILABLE':
                reasons[row['reason']] += 1
                continue
            if isinstance(row['value'], bool) or not math.isfinite(row['value']):
                reasons['nonfinite_reaction'] += 1
                continue
            series = 'material_reaction.' + row['eventType'] + '.' + str(row['reactionWindowSessions'])
            if (series, row['date']) in taken:
                reasons['evidenced_record_takes_precedence'] += 1
                continue
            taken.add((series, row['date']))
            row.update(seriesId=series, derivationBasis='DAILY_CLOSE_REFERENCE_NOT_INTRADAY_ATTRIBUTION',
                       validationStatus='UNVALIDATED')
            row['sourceSha256'] = fingerprint(row)
            output.append(row)
    return {'rows': output, 'diagnostics': {
        'status': 'AVAILABLE' if output else 'DATA_GATED', 'eventCount': len(events),
        'availableReferenceWindows': len(output), 'gatedReasonCounts': dict(sorted(reasons.items())),
        'timeBasis': 'ARCHIVED_RELEASE_DATE_FIXED_TIME_RULE',
        'availabilityBasis': 'RESEARCH_KNOWN_AT_ENDPOINT_CLOSE',
        'historicalVintageVerified': False, 'actualPublicationTimeVerified': False,
        'automaticAiCalls': 0, 'actionAuthority': False, 'probability': None}}
