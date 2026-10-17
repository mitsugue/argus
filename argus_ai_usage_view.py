"""Owner-only monthly display of committed usage, independent of cost gates."""
from copy import deepcopy
from datetime import date, datetime, timezone
import math
import re

COUNTS = ('records', 'providerCalls', 'unknownProviderCallCount', 'unknownCostRecords',
          'inputTokens', 'outputTokens', 'cachedInputTokens', 'knownDurationMs',
          'unknownDurationRecords', 'retryRecords', 'unknownAttemptRecords')
MAPS = ('outcomes', 'errorClasses', 'unknownTokenRecords')


def _empty():
    return {**{k: 0 for k in COUNTS}, **{k: {} for k in MAPS}, 'knownEstimatedCostUsd': 0.0}


def _add(target, source):
    for key in COUNTS:
        value = source[key]
        if type(value) is not int or value < 0: raise ValueError('invalid_usage_summary')
        target[key] += value
    for key in MAPS:
        for name, value in source[key].items():
            if type(value) is not int or value < 0: raise ValueError('invalid_usage_summary')
            target[key][name] = target[key].get(name, 0) + value
    cost = source['knownEstimatedCostUsd']
    if type(cost) not in (int, float) or not math.isfinite(cost) or cost < 0:
        raise ValueError('invalid_usage_summary')
    target['knownEstimatedCostUsd'] = round(target['knownEstimatedCostUsd'] + cost, 9)
    if not math.isfinite(target['knownEstimatedCostUsd']): raise ValueError('invalid_usage_summary')


def monthly_view(snapshot, *, at, month=None, offset=0, through_sequence=None):
    now = datetime.fromisoformat(at.replace('Z', '+00:00'))
    if now.tzinfo is None: raise ValueError('invalid_usage_period')
    current = now.astimezone(timezone.utc).strftime('%Y-%m')
    month = current if month is None else month
    if not isinstance(month, str) or not re.fullmatch(r'\d{4}-(0[1-9]|1[0-2])', month):
        raise ValueError('invalid_usage_period')
    date.fromisoformat(month+'-01')
    if month > current or type(offset) is not int or not 0 <= offset <= 100000:
        raise ValueError('invalid_usage_period')
    if through_sequence is not None and (type(through_sequence) is not int or through_sequence < 0):
        raise ValueError('invalid_usage_cursor')
    base = {'schemaVersion': 'argus-owner-usage-view-v1', 'scope': 'OWNER_PRIVATE',
            'generatedAt': at, 'monthUtc': month, 'timeBasis': 'UTC',
            'status': snapshot.get('readStatus', 'UNAVAILABLE'),
            'state': {k: snapshot.get('state', {}).get(k) for k in
                      ('status', 'pendingReceipts', 'lastSavedAt', 'lastErrorClass')},
            'rows': [], 'totals': None, 'nextOffset': None, 'throughSequence': None,
            'remoteRecoveryVerified': snapshot.get('remoteRecoveryVerified') is True,
            'coverage': 'committed_sdk_receipts_only', 'historyBeforeFirstReceiptReconstructed': False,
            'providerResponseIsContentAcceptance': False, 'addToLegacyTotal': False}
    summary = snapshot.get('summary')
    if base['status'] != 'AVAILABLE' or not summary: return base
    if (summary.get('schemaVersion') != 'argus-ai-usage-summary-v1'
            or summary.get('coverage') != 'all_committed_receipts_in_this_store'
            or summary.get('displayWindowLimitApplied') is not False):
        raise ValueError('incomplete_usage_coverage')
    watermark = summary['throughSequence']
    if through_sequence is not None and through_sequence != watermark:
        raise ValueError('usage_snapshot_changed')
    groups = {}; totals = _empty()
    for row in summary['groups']:
        if row['monthUtc'] != month: continue
        if not row['dayUtc'].startswith(month+'-'): raise ValueError('invalid_usage_summary')
        key = tuple(row[k] for k in ('feature', 'provider', 'requestedModel', 'returnedModel'))
        group = groups.setdefault(key, {**dict(zip(('feature', 'provider', 'requestedModel', 'returnedModel'), key)), **_empty()})
        _add(group, row); _add(totals, row)
    rows = sorted(groups.values(), key=lambda r: (-r['knownEstimatedCostUsd'], r['feature'],
                  r['provider'], r['requestedModel'] or '', r['returnedModel'] or ''))
    if offset > len(rows): raise ValueError('invalid_usage_cursor')
    return {**base, 'rows': deepcopy(rows[offset:offset+50]), 'totals': totals,
            'nextOffset': offset+50 if offset+50 < len(rows) else None,
            'groupCount': len(rows), 'throughSequence': watermark,
            'durableReceiptCount': summary['durableReceiptCount'],
            'firstRecordedAt': summary['firstRecordedAt'], 'lastRecordedAt': summary['lastRecordedAt']}
