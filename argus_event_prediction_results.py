"""Read-only links from event evidence to canonical issued predictions/results.

These links describe records that cited an event when issued. They do not
attribute a price move to that event or score its causal hypothesis.
"""
import copy
from datetime import datetime

import argus_decision_ledger as ledger


MAX_PAIRS = 512
MAX_RESULTS = 24
SCHEMA = 'argus-event-prediction-result-v1'


def _time(value):
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('event_result_timezone_required')
    return parsed


def project_result(prediction, outcome, *, as_of):
    """Validate the original pair before selecting its public explanation fields."""
    if not ledger.verify_prediction_record_v2(prediction) or not \
            ledger.verify_outcome_resolution_event(outcome, prediction):
        raise ValueError('event_result_canonical_pair_invalid')
    cutoff = _time(as_of)
    issued = _time(prediction['issuedAt'])
    recorded = _time(outcome['recordedAt'])
    target = _time(outcome['targetAt'])
    maturity = _time(prediction['maturity']['maturityAt'])
    if not issued <= target <= maturity <= recorded <= cutoff:
        raise ValueError('event_result_time_contract_invalid')
    if any(outcome.get(key) != prediction.get(key)
           for key in ('symbol', 'market', 'forecastHorizon', 'candidateAction')):
        raise ValueError('event_result_subject_mismatch')
    if prediction['mode'] != 'forward_live':
        raise ValueError('event_result_live_record_required')
    refs = prediction.get('evidenceRefs') or []
    event_ids = sorted({ref[len('causal-event:'):] for ref in refs
                        if ref.startswith('causal-event:') and ref != 'causal-event:'})
    hypothesis_ids = sorted({ref[len('causal-hypothesis:'):] for ref in refs
                             if ref.startswith('causal-hypothesis:')
                             and ref != 'causal-hypothesis:'})
    truth = outcome['truthRef']
    if _time(truth['knownAt']) > recorded:
        raise ValueError('event_result_future_truth')
    return {
        'schemaVersion': SCHEMA,
        'predictionId': prediction['id'],
        'predictionIntegrityHash': prediction['integrityHash'],
        'outcomeId': outcome['id'],
        'outcomeIntegrityHash': outcome['integrityHash'],
        'sequence': outcome['sequence'],
        'previousOutcomeId': outcome['previousEventId'],
        'eventIds': event_ids, 'hypothesisIds': hypothesis_ids,
        'symbol': prediction['symbol'], 'market': prediction['market'],
        'forecastHorizon': prediction['forecastHorizon'],
        'issuedAt': prediction['issuedAt'], 'targetAt': outcome['targetAt'],
        'targetSessionId': outcome['targetSessionId'],
        'recordedAt': outcome['recordedAt'], 'mode': prediction['mode'],
        'forecastValue': prediction['forecastValue'],
        'candidateAction': prediction['candidateAction'],
        'status': outcome['status'],
        'metrics': copy.deepcopy(outcome['metrics']),
        'truthRef': copy.deepcopy(truth),
        'missingReasons': list(outcome['missingReasons']),
        'relation': 'EVENT_REFERENCED_WHEN_PREDICTION_ISSUED',
        'causalAttributionVerified': False,
        'predictiveProbabilityVerified': False,
        'actionAuthority': False,
    }


def select_event_results(event, pairs, *, as_of, market, symbol, limit=2):
    """Bounded, exact-subject lookup; later corrections never enter an earlier view.

    Callers provide canonical pairs, not derived projections or mutable prices.
    Unrelated instruments cannot stand in for a cash index or an owner's stock.
    """
    if type(limit) is not int or not 1 <= limit <= MAX_RESULTS:
        raise ValueError('event_result_limit_invalid')
    if not isinstance(pairs, (list, tuple)) or len(pairs) > MAX_PAIRS:
        raise ValueError('event_result_pair_bound')
    cutoff = _time(as_of)
    first_seen = _time(event['firstSeenAt'])
    if first_seen > cutoff:
        raise ValueError('event_result_future_event')
    event_id = event['eventId']
    hypotheses = {h['hypothesisId'] for h in event.get('causalHypotheses') or []}
    latest, seen = {}, {}
    matched = excluded_future = 0
    for pair in pairs:
        prediction, outcome = pair['prediction'], pair['outcome']
        # Verify seals even for records outside this cutoff. Never trust a
        # tampered recordedAt to hide malformed evidence as a future record.
        if not ledger.verify_prediction_record_v2(prediction) or not \
                ledger.verify_outcome_resolution_event(outcome, prediction):
            raise ValueError('event_result_canonical_pair_invalid')
        if _time(outcome['recordedAt']) > cutoff:
            excluded_future += 1
            continue
        row = project_result(prediction, outcome, as_of=as_of)
        if event_id not in row['eventIds'] or row['market'] != market or row['symbol'] != symbol:
            continue
        if _time(row['issuedAt']) < first_seen:
            raise ValueError('event_result_reference_predates_event')
        if not hypotheses.intersection(row['hypothesisIds']):
            continue
        if row['outcomeId'] in seen:
            if seen[row['outcomeId']] != row:
                raise ValueError('event_result_conflicting_identity')
            continue
        seen[row['outcomeId']] = row
        matched += 1
        prior = latest.get(row['predictionId'])
        if prior and prior['sequence'] == row['sequence'] and prior != row:
            raise ValueError('event_result_conflicting_sequence')
        if prior is None or (row['sequence'], _time(row['recordedAt'])) > \
                (prior['sequence'], _time(prior['recordedAt'])):
            latest[row['predictionId']] = row
    rows = sorted(latest.values(), key=lambda r: (
        _time(r['issuedAt']), r['predictionId']), reverse=True)
    return {'status': 'AVAILABLE' if rows else 'NOT_RECORDED_IN_SEARCH_SCOPE',
            'asOf': as_of, 'market': market, 'symbol': symbol,
            'records': rows[:limit], 'scannedPairCount': len(pairs),
            'matchedRecordCount': matched, 'supersededCount': matched - len(rows),
            'excludedFutureCount': excluded_future,
            'omittedByLimit': max(0, len(rows) - limit),
            'historyComplete': False, 'actionAuthority': False}
