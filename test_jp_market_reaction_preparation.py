"""Batch-local close preparation keeps legacy references and input checks."""
import copy
import hashlib
import json
import weakref
from unittest.mock import patch

import pytest
import jp_market_material_reactions as material
import jp_market_session_reaction as session
from test_jp_market_historical_reactions import DAYS, CASH, RECEIVED, event


GOLDEN = {'historical': 'bb1538791edf1af6cfb35f60540c60e25ef7b3ee7466e5bbeb3a4fd56bedcc26',
          'evidenced': '18f38386a33957080fb6c5b5b52cca970c0fc28010058d27645897a3ae68da69'}


def invoke(kind, rows=CASH, days=DAYS, events=None):
    events = events if events is not None else [event(DAYS[i]) for i in (8, 15, 22)]
    if kind == 'historical':
        return material.historical_reactions(events, rows=rows, sessions=days, cutoff=RECEIVED)
    records = [{'eventId': e['eventId'], 'eventCode': e['eventType'],
                'eventTimeEvidence': {**e, 'timeBasis': 'OFFICIAL_EMBARGO_BOUNDARY'}} for e in events]
    return material.cached_reactions(records, rows=rows, sessions=days, cutoff=RECEIVED)


@pytest.mark.parametrize('kind', ['historical', 'evidenced'])
def test_each_batch_prepares_closes_once_and_keeps_legacy_bytes(kind):
    unchanged = copy.deepcopy((DAYS, CASH))
    with patch.object(session, 'session_close', wraps=session.session_close) as close:
        value = invoke(kind)
        assert hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest() == GOLDEN[kind]
        assert close.call_count <= len(DAYS), 'same session close rebuilt for each event'
        first_count = close.call_count
        corrected = copy.deepcopy(CASH)
        corrected[9]['close'] += 50
        after = invoke(kind, rows=corrected)
        assert 0 < close.call_count - first_count <= len(DAYS), 'preparation outlived its batch'
        assert after != value
    assert (DAYS, CASH) == unchanged


@pytest.mark.parametrize('kind', ['historical', 'evidenced'])
def test_prepared_converter_is_released_with_adapter_call(kind, monkeypatch):
    original = material._batch_measurer
    references = []
    def tracked():
        calculate = original()
        references.append(weakref.ref(calculate))
        return calculate
    monkeypatch.setattr(material, '_batch_measurer', tracked)
    value = invoke(kind)
    assert value['rows'] and references
    assert all(reference() is None for reference in references)


@pytest.mark.parametrize('day', ['2024-11-01', '2024-11-05'])
@pytest.mark.parametrize('microseconds', [-1, 0, 1])
def test_prepared_split_keeps_exact_old_and_new_close_boundaries(day, microseconds):
    from datetime import timedelta
    days = ['2024-10-30', '2024-10-31', '2024-11-01', '2024-11-05', '2024-11-06',
            '2024-11-07', '2024-11-08', '2024-11-11', '2024-11-12']
    rows = [{**CASH[0], 'date': d, 'close': 100+i} for i, d in enumerate(days)]
    release = {**event(day), 'eventTime': (session.session_close(day) +
               timedelta(microseconds=microseconds)).isoformat()}
    kwargs = dict(event=release, rows=rows, sessions=days, cutoff=RECEIVED,
                  research_availability=True)
    assert session._batch_measurer()(**kwargs) == session.measure(**kwargs)


@pytest.mark.parametrize('damage', ['duplicate_day', 'price'])
def test_warm_preparation_rechecks_changed_calendar_and_prices(damage):
    prepared = session._batch_measurer()
    kwargs = dict(event=event(DAYS[8]), rows=CASH, sessions=DAYS,
                  cutoff=RECEIVED, research_availability=True)
    assert prepared(**kwargs) == session.measure(**kwargs)
    if damage == 'duplicate_day':
        kwargs['sessions'] = [*DAYS, DAYS[-1]]
        with pytest.raises(ValueError, match='ordered_unique_calendar_required'):
            prepared(**kwargs)
    else:
        kwargs['rows'] = copy.deepcopy(CASH)
        kwargs['rows'][9]['close'] = True
        assert prepared(**kwargs) == session.measure(**kwargs)


@pytest.mark.parametrize('kind', ['historical', 'evidenced'])
@pytest.mark.parametrize('damage', ['duplicate_day', 'unordered', 'invalid_day', 'duplicate_cash',
                                  'proxy', 'price', 'future_receipt', 'future_event', 'provenance'])
def test_batch_preparation_keeps_all_single_event_checks(kind, damage, monkeypatch):
    days, rows = copy.deepcopy(DAYS), copy.deepcopy(CASH)
    events = [event(DAYS[i]) for i in (8, 15, 22)]
    if damage == 'duplicate_day': days.append(days[-1])
    elif damage == 'unordered': days[1], days[2] = days[2], days[1]
    elif damage == 'invalid_day': days[0] = '2026-08-00'
    elif damage == 'duplicate_cash': rows.append(copy.deepcopy(rows[-1]))
    elif damage == 'proxy': rows[0]['instrumentId'] = 'SYNTHETIC_PROXY'
    elif damage == 'price': rows[9]['close'] = True
    elif damage == 'future_receipt': rows[9]['receivedAt'] = '2099-01-01T00:00:00Z'
    elif damage == 'future_event': events[1]['receivedAt'] = '2099-01-01T00:00:00Z'
    else: events[1]['sourceSha256'] = None
    unchanged = copy.deepcopy((days, rows, events))
    prepared = invoke(kind, rows, days, events)
    monkeypatch.setattr(material, '_batch_measurer', lambda: session.measure)
    assert prepared == invoke(kind, rows, days, events)
    assert (days, rows, events) == unchanged
