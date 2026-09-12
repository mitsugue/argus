import copy

import pytest

from argus_ai_usage_receipt import legacy_receipts, make_receipt, summarize, validate_receipt


def receipt(**overrides):
    fields = dict(call_id='call-1', provider='openai', feature='news_intel',
        started_at='2026-09-12T08:59:59+09:00', completed_at='2026-09-12T09:00:01+09:00',
        requested_model='configured-primary', returned_model='actual-primary',
        outcome='success', input_tokens=100, output_tokens=20, cached_input_tokens=30,
        estimated_cost_usd=0.002, provider_called=True, attempt=1)
    return make_receipt(**dict(fields, **overrides))


def test_same_second_parallel_calls_are_distinct_and_replay_is_idempotent():
    first, second = receipt(), receipt(call_id='call-2')
    result = summarize([first, second, copy.deepcopy(first)])
    assert result['uniqueReceipts'] == 2
    row = result['groups'][0]
    assert row['dayUtc'] == '2026-09-11'
    assert row['providerCalls'] == 2 and row['records'] == 2
    assert row['knownEstimatedCostUsd'] == 0.004
    assert row['inputTokens'] == 200 and row['cachedInputTokens'] == 60
    assert row['knownDurationMs'] == 4000
    assert result['budgetAuthorizationChanged'] is False


def test_unknown_cost_is_not_a_zero_price_claim():
    row = summarize([receipt(estimated_cost_usd=None, input_tokens=None,
                             output_tokens=None, cached_input_tokens=None)])['groups'][0]
    assert row['unknownCostRecords'] == 1
    assert row['estimatedCostComplete'] is False
    assert row['unknownTokenRecords'] == {'inputTokens': 1, 'outputTokens': 1, 'cachedInputTokens': 1}


def test_features_models_errors_and_cache_calls_stay_separate():
    records = [receipt(), receipt(call_id='event', feature='event_analysis', outcome='invalid_output', attempt=2),
        receipt(call_id='fallback', returned_model='actual-fallback'),
        receipt(call_id='cache', outcome='cache_hit', input_tokens=0, output_tokens=0,
                cached_input_tokens=0, estimated_cost_usd=0, provider_called=False)]
    result = summarize(records)
    assert len(result['groups']) == 3
    assert sum(g['providerCalls'] for g in result['groups']) == 3
    assert sum(g['records'] for g in result['groups']) == 4
    assert sum(g['retryRecords'] for g in result['groups']) == 1
    assert next(g for g in result['groups'] if g['feature'] == 'event_analysis')['outcomes'] == {'invalid_output': 1}


def test_conflicting_call_and_tampered_receipt_fail_closed():
    first = receipt()
    with pytest.raises(ValueError, match='conflicting_usage_call_id'):
        summarize([first, receipt(estimated_cost_usd=0.003)])
    edited = dict(first, inputTokens=999)
    with pytest.raises(ValueError, match='usage_receipt_integrity_mismatch'):
        validate_receipt(edited)


@pytest.mark.parametrize('overrides', [
    {'cached_input_tokens': 101}, {'input_tokens': True}, {'estimated_cost_usd': float('nan')},
    {'provider_called': False}, {'provider_called': 0}, {'attempt': 0},
    {'started_at': '2026-09-12T00:00:00'}, {'completed_at': '2026-09-11T00:00:00Z'},
    {'outcome': 'cache_hit'},
])
def test_invalid_receipt_cannot_enter_aggregates(overrides):
    with pytest.raises(ValueError):
        receipt(**overrides)


def test_legacy_import_preserves_duplicate_counts_and_explicit_unknowns():
    row = {'provider': 'openai', 'purpose': 'news_intel', 'at': '2026-09-12T00:00:00Z',
           'estimatedCostUsd': 0.1}
    original = copy.deepcopy(row)
    imported = legacy_receipts([row, row, dict(row, pending=True), dict(row, at='invalid')])
    assert imported['pendingReservationsExcluded'] == 1
    assert imported['rejectedRowIndices'] == [3]
    assert imported['olderTruncatedHistoryReconstructed'] is False
    assert imported['tokensReconstructed'] is False
    assert row == original
    repeated = legacy_receipts([row, row])
    result = summarize(imported['receipts'] + repeated['receipts'])
    assert result['uniqueReceipts'] == 2
    total = result['groups'][0]
    assert total['knownEstimatedCostUsd'] == 0.2
    assert total['unknownProviderCallCount'] == 2
    assert total['unknownDurationRecords'] == 2
    assert total['requestedModel'] is None and total['returnedModel'] is None


def test_legacy_reservation_settlement_has_stable_identity():
    row = {'provider': 'openai', 'purpose': 'event_analysis', 'at': '2026-09-12T00:00:00Z',
           'settledAt': '2026-09-12T00:00:05Z', 'estimatedCostUsd': 0.1,
           'pending': False, 'reservationId': 'rsv-example'}
    imported = legacy_receipts([row])['receipts']
    assert imported[0]['callId'] == 'reservation:rsv-example'
    assert imported[0]['durationMs'] == 5000
    assert summarize(imported + imported)['uniqueReceipts'] == 1


def test_aggregate_overflow_is_not_reported_as_valid_cost():
    with pytest.raises(ValueError, match='usage_aggregate_numeric_range_exceeded'):
        summarize([receipt(call_id='large-1', estimated_cost_usd=1e308),
                   receipt(call_id='large-2', estimated_cost_usd=1e308)])
