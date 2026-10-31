"""失敗を維持したまま正確な入力を非公開保存へ渡す契約。"""
from copy import deepcopy
import hashlib
import json

import pytest

import argus_market_data_truth as truth
import argus_prediction_failure_input as capture_module


AT = "2026-10-28T01:00:00Z"


def observation(price):
    return truth.build_observation(
        instrument_id="JP:1234", symbol="1234", market="JP", asset_type="EQUITY",
        fact_type="QUOTE", values={"price": price, "changePct": 1}, provider="jquants",
        adapter="scanner_quote_adapter_v1", source_ref="synthetic", observed_at=AT,
        received_at=AT, known_at=AT, freshness="FRESH", completeness="COMPLETE",
        fresh_until="2026-10-28T01:20:00Z", currency="JPY", revision=7)


def capture(rows, requests=None, **kw):
    return capture_module.capture(rows, requests if requests is not None else [{
        "instrumentId": "JP:1234", "market": "JP", "factType": "QUOTE",
        "currency": "JPY", "required": True}],
        **{"decision_at": AT, "generated_at": AT, "build_identity": "a" * 40, **kw})


def test_exact_input_replays_real_conflict_both_orders_and_has_no_aliases():
    rows = [observation(100), observation(101)]
    original = deepcopy(rows)
    out = capture(rows)
    assert out['complete'] is True and out['status'] == 'CAPTURED' and rows == original
    encoded = json.dumps(out['input'], sort_keys=True, ensure_ascii=False,
                         separators=(',', ':'), allow_nan=False).encode()
    assert out['inputBytes'] == len(encoded)
    assert out['inputSha256'] == hashlib.sha256(encoded).hexdigest()
    for values in (out['input']['values'], list(reversed(out['input']['values']))):
        with pytest.raises(ValueError, match='^conflicting_revision$'):
            truth.build_decision_snapshot(**{**out['input'], 'values': values})
    rows[0]['values']['price'] = 999
    assert out['input']['values'] == original


@pytest.mark.parametrize('count,status', [(513, 'COUNT_BOUND_EXCEEDED'), (512, 'BYTE_BOUND_EXCEEDED')])
def test_limits_do_not_return_or_claim_partial_input(count, status):
    out = capture([observation(100)] * count)
    assert out['complete'] is False and out['status'] == status
    assert 'input' not in out and 'inputSha256' not in out


def test_exact_byte_limit_and_one_byte_over(monkeypatch):
    rows = [observation(100), observation(101)]
    size = capture(rows)['inputBytes']
    monkeypatch.setattr(capture_module, 'MAX_INPUT_BYTES', size)
    assert capture(rows)['complete'] is True
    monkeypatch.setattr(capture_module, 'MAX_INPUT_BYTES', size - 1)
    assert capture(rows) == {'schemaVersion': 'prediction-truth-failure-input-v1',
                            'complete': False, 'observationCount': 2, 'requestCount': 1,
                            'status': 'BYTE_BOUND_EXCEEDED'}


def test_invalid_original_fields_do_not_leave_the_closed_schema():
    out = capture([{**observation(100), 'headers': {'token': 'private-test-value'}}])
    assert out['status'] == 'OBSERVATION_SHAPE_UNAVAILABLE'
    assert 'private-test-value' not in json.dumps(out) and 'input' not in out


@pytest.mark.parametrize('bad', [
    {'headers': 'private-test-value'}, {'instrumentId': {'token': 'private-test-value'}},
    {'market': ['private-test-value']}, {'required': 1}, {'currency': 'USD'},
    {'instrumentId': 'JP:1234\nprivate-test-value'},
])
def test_request_values_cannot_smuggle_extra_or_nested_fields(bad):
    request = {'instrumentId': 'JP:1234', 'market': 'JP', 'factType': 'QUOTE',
               'currency': 'JPY', 'required': True, **bad}
    out = capture([observation(100)], [request])
    assert out['status'] == 'REQUEST_SHAPE_UNAVAILABLE' and 'input' not in out
    assert 'private-test-value' not in json.dumps(out)


@pytest.mark.parametrize('kw', [
    {'decision_at': 'private-test-value'}, {'generated_at': '2026-10-28T00:59:59Z'},
    {'generated_at': '2026-10-28T01:00:00'}, {'build_identity': 'private-test-value'},
])
def test_unreplayable_metadata_is_not_captured(kw):
    out = capture([observation(100)], **kw)
    assert out['status'] == 'IDENTITY_UNAVAILABLE' and 'input' not in out
    assert 'private-test-value' not in json.dumps(out)


def test_unbounded_iterables_are_not_consumed():
    def forbidden():
        raise AssertionError('iterator consumed')
        yield None
    out = capture(forbidden())
    assert out == {'schemaVersion': 'prediction-truth-failure-input-v1',
                   'complete': False, 'status': 'SEQUENCE_UNAVAILABLE'}
