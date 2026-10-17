"""Retained official-result contract and receipt metadata; synthetic transport only."""
import ast
from copy import deepcopy
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import pytz
import pytest
import argus_macro_results

NOW = '2026-10-11T07:40:00Z'
RAW = {'Results': {'series': [
    {'seriesID': 'CES0000000001', 'data': [
        {'year': '2026', 'period': 'M09', 'value': '100100'},
        {'year': '2026', 'period': 'M08', 'value': '100000'}]},
    {'seriesID': 'LNS14000000', 'data': [
        {'year': '2026', 'period': 'M09', 'value': '4.1'}]}]}}
EVENT = {'eventCode': 'NFP', 'eventDate': '2026-10-02', 'id': 'synthetic-nfp'}

class Response:
    status_code = 200
    url = 'https://api.bls.gov/publicAPI/v2/timeseries/data/'
    history = []
    def __init__(self, raw=RAW):
        self.raw = deepcopy(raw)
        self.content = json.dumps(self.raw, indent=2).encode()
    def json(self):
        return deepcopy(self.raw)

def run(response, event=EVENT):
    state = {'NFP': {}}
    calls = []
    def post(*args, **kwargs):
        calls.append((args, kwargs))
        return response
    env = {'datetime': datetime, 'timedelta': timedelta, 'pytz': pytz,
        'argus_macro_results': argus_macro_results,
        'argus_fastdate': SimpleNamespace(strptime=datetime.strptime),
        'requests': SimpleNamespace(post=post), '_ai_now_iso': lambda: NOW,
        '_MACRO_RESULT_STATE': state}
    source = (Path(__file__).parent / 'scanner.py').read_text()
    node = next(n for n in ast.parse(source).body
        if isinstance(n, ast.FunctionDef) and n.name == '_bls_nfp_result')
    exec(compile(ast.Module([node], type_ignores=[]), '<real-nfp-function>', 'exec'), env)
    result = env['_bls_nfp_result'](deepcopy(event))
    assert len(calls) == 1
    return result, state

def test_nfp_receipt_preserves_official_values_and_legacy_receipt():
    response = Response()
    result, state = run(response)
    assert result['available'] is True
    assert result['metrics'] == {'nfpChangeK': 100, 'unemploymentRate': '4.1', 'referenceMonth': '2026-09'}
    assert state['NFP']['status'] == 'live'
    for key, value in argus_macro_results.series_receipt(RAW, NOW).items():
        assert result[key] == value
    receipt = result['sourceHttpReceipt']
    assert receipt['rawHttpResponseSha256'] == hashlib.sha256(response.content).hexdigest()
    assert receipt['parsedResponseSha256'] == result['sourceResponseSha256']
    assert receipt['receivedAt'] == result['receivedAt'] == NOW
    assert result['releasedAt'] is None and 'eventTimeEvidence' not in result
    assert receipt['rawHttpBodyRetained'] is False
    assert receipt['actualPublicationTimeVerified'] is False

@pytest.mark.parametrize('case', ['missing_content', 'redirected', 'wrong_url', 'parsed_mismatch'])
def test_invalid_optional_receipt_keeps_the_existing_official_result(case):
    response = Response()
    if case == 'missing_content':
        del response.content
    elif case == 'redirected':
        response.history = [object()]
    elif case == 'wrong_url':
        response.url = 'https://invalid.example.test/'
    else:
        response.content = b'{}'
    result, state = run(response)
    assert result['available'] is True and result['metrics']['nfpChangeK'] == 100
    assert state['NFP']['status'] == 'live'
    assert 'sourceHttpReceipt' not in result

def test_unreleased_reference_month_is_not_promoted():
    result, _ = run(Response(), {'eventCode': 'NFP', 'eventDate': '2026-11-06'})
    assert result['available'] is False and 'sourceHttpReceipt' not in result

def test_empty_series_stays_partial():
    result, state = run(Response({'Results': {'series': []}}))
    assert result['available'] is False and state['NFP']['status'] == 'partial'
    assert 'sourceHttpReceipt' not in result

def test_rate_limit_keeps_the_existing_stop_status():
    response = Response()
    response.status_code = 429
    result, state = run(response)
    assert result['available'] is False and state['NFP']['status'] == 'rate_limited'
    assert 'sourceHttpReceipt' not in result

def test_corrupt_response_has_no_receipt_or_available_result():
    class Broken(Response):
        def json(self):
            raise ValueError('synthetic_bad_json')
    result, state = run(Broken())
    assert result['available'] is False and state['NFP']['status'] == 'error'
    assert 'sourceHttpReceipt' not in result
