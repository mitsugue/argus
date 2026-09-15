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


MAX_SOURCE_SEGMENTS = 8
MAX_SOURCE_BYTES = 48 * 1024 * 1024
MAX_PAIR_BYTES = 1024 * 1024


def load_recent_pairs(ledger_root):
    """Read a bounded projection of one committed ledger generation.

    This is a derived retrieval input, never a replacement for the writer's
    complete authority validation. Call after the writer has committed, or
    against a checkout pinned to one Git commit; do not rescan on each UI read.
    Missing indexed originals and bounded omissions remain explicit.
    """
    import json
    import os
    import stat
    from pathlib import Path
    from scripts import run_prediction_ledger as runner

    root = Path(ledger_root)
    read_bytes = 0

    def read(path, maximum):
        nonlocal read_bytes
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, 'rb') as source:
            info = os.fstat(source.fileno())
            if not stat.S_ISREG(info.st_mode):
                raise ValueError('event_result_regular_file_required')
            remaining = min(maximum, MAX_SOURCE_BYTES - read_bytes)
            if info.st_size > remaining:
                raise ValueError('event_result_source_byte_bound')
            raw = source.read(remaining + 1)
            if len(raw) > remaining:
                raise ValueError('event_result_source_byte_bound')
        read_bytes += len(raw)
        value = json.loads(raw)
        if raw != runner._canonical_bytes(value) + b'\n':
            raise ValueError('event_result_source_encoding_invalid')
        return value

    head = runner._decode_commit_head(read(root / 'commit-head.json', runner.MAX_COMMIT_HEAD_BYTES))
    manifest_path = runner._confined_path(root, head['manifest']['path'], top='manifests')
    manifest = runner._verify_document(read(manifest_path, runner.MAX_MANIFEST_BYTES),
        schema=runner.MANIFEST_SCHEMA, record_type='prediction_ledger_manifest')
    if head != runner._commit_head_document(manifest, manifest_path=head['manifest']['path']):
        raise ValueError('event_result_commit_manifest_mismatch')
    as_of = manifest['updatedAt']
    _time(as_of)
    inventory_ref = manifest['inventory']
    inventory_path = runner._confined_path(root, inventory_ref['path'], top='inventories')
    inventory = runner._decode_inventory(read(inventory_path, runner.MAX_INVENTORY_BYTES))
    if inventory['digest'] != inventory_ref['digest'] or inventory['head'] != manifest['head']:
        raise ValueError('event_result_inventory_mismatch')
    references = {row['path']: row for row in inventory['segments']}
    index_ref = manifest['index']
    index_path = runner._confined_path(root, index_ref['path'], top='indexes')
    index_doc = read(index_path, runner.MAX_INDEX_BYTES)
    index = runner._decode_index(index_doc)
    if index_doc['digest'] != index_ref['digest']:
        raise ValueError('event_result_index_mismatch')
    segments = {}
    omissions = {}

    def omit(reason): omissions[reason] = omissions.get(reason, 0) + 1

    def segment(relative):
        if relative in segments: return segments[relative]
        if relative not in references:
            raise ValueError('event_result_segment_not_committed')
        if len(segments) >= MAX_SOURCE_SEGMENTS:
            omit('SOURCE_SEGMENT_BOUND'); return None
        ref = references[relative]
        path = runner._confined_path(root, relative, top='segments')
        if read_bytes + path.lstat().st_size > MAX_SOURCE_BYTES:
            omit('SOURCE_BYTE_BOUND'); return None
        value = runner._verify_segment(read(path, runner.MAX_SEGMENT_BYTES))
        if runner._segment_reference(value, relative) != ref:
            raise ValueError('event_result_segment_reference_mismatch')
        segments[relative] = value
        return value

    current = segment(manifest['head']['path'])
    if current is None: raise ValueError('event_result_head_unreadable')
    outcomes = sorted(current['outcomeResolutions'],
        key=lambda row: (row['recordedAt'], row['predictionId'], row['sequence']), reverse=True)
    pairs = []; pair_bytes = 2
    for outcome in outcomes:
        if len(pairs) >= MAX_PAIRS:
            omit('PAIR_COUNT_BOUND'); continue
        identity = index['identities'].get(outcome['predictionId'])
        if not identity:
            omit('ORIGINAL_NOT_IN_BOUNDED_INDEX'); continue
        original = segment(identity['sourceSegment'])
        if original is None: continue
        prediction = next((row for row in original['issuedDecisions']
                           if row['id'] == outcome['predictionId']), None)
        if prediction is None or prediction['integrityHash'] != identity['integrityHash']:
            raise ValueError('event_result_original_reference_mismatch')
        project_result(prediction, outcome, as_of=as_of)
        pair = {'prediction': prediction, 'outcome': outcome}
        size = len(json.dumps(pair, ensure_ascii=False, separators=(',', ':')).encode()) + 1
        if pair_bytes + size > MAX_PAIR_BYTES:
            omit('PAIR_BYTE_BOUND'); continue
        pair_bytes += size; pairs.append(copy.deepcopy(pair))
    return {'schemaVersion': 'argus-event-result-source-v1',
        'asOf': as_of, 'manifestDigest': manifest['digest'],
        'commitHeadDigest': head['digest'], 'generation': manifest['generation'],
        'scope': 'LATEST_COMMITTED_SEGMENT_OUTCOMES', 'historyComplete': False,
        'sourceSegmentCount': len(segments), 'sourceBytesRead': read_bytes,
        'outcomeCount': len(outcomes), 'selectedPairCount': len(pairs),
        'omissions': omissions, 'pairs': pairs,
        'actionAuthority': False, 'causalAttributionVerified': False}
