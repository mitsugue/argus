"""Canonical AI usage receipts and explicit feature/model summaries.

No provider calls, budget authorization or inferred prices. The caller stores
receipts with the existing durable accounting path; this module preserves
unknown token/model information rather than turning missing usage into zero.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
from typing import Any, Iterable, Mapping

SCHEMA = 'argus-ai-usage-receipt-v1'
OUTCOMES = {'success', 'provider_error', 'invalid_output', 'cache_hit', 'skipped', 'legacy_recorded'}


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    allow_nan=False, separators=(',', ':')).encode()).hexdigest()


def _instant(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('usage_timestamp_requires_timezone')
    return parsed.astimezone(timezone.utc)


def _text(value, *, required=False):
    if value is None and not required:
        return None
    if not isinstance(value, str) or not value.strip() or len(value) > 160:
        raise ValueError('invalid_usage_identifier')
    return value.strip()


def _tokens(value):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError('invalid_usage_tokens')
    return value


def make_receipt(*, call_id: str, provider: str, feature: str,
                 started_at: str, completed_at: str | None,
                 requested_model: str | None, returned_model: str | None,
                 outcome: str, input_tokens: int | None = None,
                 output_tokens: int | None = None, cached_input_tokens: int | None = None,
                 estimated_cost_usd: float | None = None, provider_called: bool | None = None,
                 attempt: int | None = None, source_ref: str | None = None) -> dict[str, Any]:
    start = _instant(started_at)
    end = _instant(completed_at) if completed_at is not None else None
    if end is not None and end < start:
        raise ValueError('usage_completion_precedes_start')
    if outcome not in OUTCOMES or provider_called not in (True, False, None):
        raise ValueError('invalid_usage_outcome')
    if provider_called is not None and not isinstance(provider_called, bool):
        raise ValueError('invalid_provider_called_flag')
    if outcome in {'skipped', 'cache_hit'} and provider_called is not False:
        raise ValueError('non_call_outcome_cannot_bill_provider')
    inp, out, cached = map(_tokens, (input_tokens, output_tokens, cached_input_tokens))
    if cached is not None and inp is not None and cached > inp:
        raise ValueError('cached_input_exceeds_input')
    if estimated_cost_usd is not None and (isinstance(estimated_cost_usd, bool) or
            not isinstance(estimated_cost_usd, (float, int)) or
            not math.isfinite(estimated_cost_usd) or estimated_cost_usd < 0):
        raise ValueError('invalid_usage_cost')
    if provider_called is False and (estimated_cost_usd not in (None, 0) or
                                    any(value not in (None, 0) for value in (inp, out, cached))):
        raise ValueError('non_call_has_provider_usage')
    if attempt is not None and (isinstance(attempt, bool) or not isinstance(attempt, int) or attempt < 1):
        raise ValueError('invalid_usage_attempt')
    result = {
        'schemaVersion': SCHEMA, 'callId': _text(call_id, required=True),
        'provider': _text(provider, required=True), 'feature': _text(feature, required=True),
        'startedAt': start.isoformat(), 'completedAt': end.isoformat() if end else None,
        'durationMs': round((end - start).total_seconds() * 1000) if end else None,
        'requestedModel': _text(requested_model), 'returnedModel': _text(returned_model),
        'outcome': outcome, 'providerCalled': provider_called, 'attempt': attempt,
        'inputTokens': inp, 'outputTokens': out, 'cachedInputTokens': cached,
        'estimatedCostUsd': round(float(estimated_cost_usd), 9) if estimated_cost_usd is not None else None,
        'sourceRef': _text(source_ref), 'costIsEstimate': True,
    }
    result['receiptDigest'] = _digest(result)
    return result


def validate_receipt(receipt: Mapping[str, Any]) -> dict[str, Any]:
    if receipt.get('schemaVersion') != SCHEMA:
        raise ValueError('unknown_usage_receipt_schema')
    rebuilt = make_receipt(call_id=receipt.get('callId'), provider=receipt.get('provider'),
        feature=receipt.get('feature'), started_at=receipt.get('startedAt'),
        completed_at=receipt.get('completedAt'), requested_model=receipt.get('requestedModel'),
        returned_model=receipt.get('returnedModel'), outcome=receipt.get('outcome'),
        input_tokens=receipt.get('inputTokens'), output_tokens=receipt.get('outputTokens'),
        cached_input_tokens=receipt.get('cachedInputTokens'), estimated_cost_usd=receipt.get('estimatedCostUsd'),
        provider_called=receipt.get('providerCalled'), attempt=receipt.get('attempt'), source_ref=receipt.get('sourceRef'))
    if dict(receipt) != rebuilt:
        raise ValueError('usage_receipt_integrity_mismatch')
    return rebuilt


def legacy_receipts(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Convert only retained settled rows; never fabricate missing detail.

    Identical rows have occurrence identities so two same-second executions
    are retained. Re-reading the same ordered checkpoint yields the same IDs.
    Reservation IDs, when present, identify the actual settlement directly.
    """
    occurrences = Counter()
    receipts, pending, rejected = [], 0, []
    for index, row in enumerate(rows):
        if row.get('pending'):
            pending += 1
            continue
        try:
            fingerprint = _digest(dict(row))
            occurrences[fingerprint] += 1
            identity = ('reservation:' + str(row['reservationId']) if row.get('reservationId')
                        else f'legacy:{fingerprint}:{occurrences[fingerprint]}')
            receipt = make_receipt(call_id=identity, provider=row.get('provider'),
                feature=row.get('purpose'), started_at=row.get('at'),
                completed_at=row.get('settledAt'), requested_model=None, returned_model=None,
                outcome='legacy_recorded', estimated_cost_usd=row.get('estimatedCostUsd'),
                provider_called=None, source_ref='legacy-cost-row:' + fingerprint)
            receipts.append(receipt)
        except (ValueError, TypeError, KeyError):
            rejected.append(index)
    return {'receipts': receipts, 'pendingReservationsExcluded': pending, 'rejectedRowIndices': rejected,
            'coverage': 'retained_legacy_rows_only', 'olderTruncatedHistoryReconstructed': False,
            'tokensReconstructed': False, 'modelsReconstructed': False}


def summarize(receipts: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Group immutable receipts by UTC day, feature, provider and model pair.

    Calling code must supply durable receipt coverage, not its latest-N display
    cache, before presenting this as an all-period aggregate.
    """
    seen, groups = {}, {}
    for item in receipts:
        row = validate_receipt(item)
        identity, digest = row['callId'], row['receiptDigest']
        if identity in seen:
            if seen[identity] != digest:
                raise ValueError('conflicting_usage_call_id')
            continue
        seen[identity] = digest
        day = row['startedAt'][:10]
        key = (day, row['feature'], row['provider'], row['requestedModel'], row['returnedModel'])
        group = groups.setdefault(key, {
            'dayUtc': day, 'monthUtc': day[:7], 'feature': row['feature'], 'provider': row['provider'],
            'requestedModel': row['requestedModel'], 'returnedModel': row['returnedModel'],
            'records': 0, 'providerCalls': 0, 'unknownProviderCallCount': 0, 'outcomes': {},
            'knownEstimatedCostUsd': 0.0, 'unknownCostRecords': 0,
            'inputTokens': 0, 'outputTokens': 0, 'cachedInputTokens': 0,
            'unknownTokenRecords': {'inputTokens': 0, 'outputTokens': 0, 'cachedInputTokens': 0},
            'knownDurationMs': 0, 'unknownDurationRecords': 0,
            'retryRecords': 0, 'unknownAttemptRecords': 0,
        })
        group['records'] += 1
        group['providerCalls'] += row['providerCalled'] is True
        group['unknownProviderCallCount'] += row['providerCalled'] is None
        group['outcomes'][row['outcome']] = group['outcomes'].get(row['outcome'], 0) + 1
        if row['estimatedCostUsd'] is None:
            group['unknownCostRecords'] += 1
        else:
            group['knownEstimatedCostUsd'] += row['estimatedCostUsd']
        for field in group['unknownTokenRecords']:
            if row[field] is None:
                group['unknownTokenRecords'][field] += 1
            else:
                group[field] += row[field]
        if row['durationMs'] is None:
            group['unknownDurationRecords'] += 1
        else:
            group['knownDurationMs'] += row['durationMs']
        group['retryRecords'] += row['attempt'] is not None and row['attempt'] > 1
        group['unknownAttemptRecords'] += row['attempt'] is None
    result = sorted(groups.values(), key=lambda r: (r['dayUtc'], r['feature'], r['provider'],
                    r['requestedModel'] or '', r['returnedModel'] or ''))
    for row in result:
        if not math.isfinite(row['knownEstimatedCostUsd']):
            raise ValueError('usage_aggregate_numeric_range_exceeded')
        row['knownEstimatedCostUsd'] = round(row['knownEstimatedCostUsd'], 9)
        row['estimatedCostComplete'] = row['unknownCostRecords'] == 0
    return {'schemaVersion': 'argus-ai-usage-summary-v1', 'uniqueReceipts': len(seen),
            'groups': result, 'timeBasis': 'UTC', 'coverage': 'supplied_receipts_only',
            'budgetAuthorizationChanged': False}
