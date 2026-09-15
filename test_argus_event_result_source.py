import json

import pytest
import requests

import argus_event_result_source as source


@pytest.fixture
def reset(monkeypatch):
    monkeypatch.setattr(source, '_CACHE', None)
    monkeypatch.setattr(source, '_RETRY_AT', 0)


class Response:
    status_code = 200
    closed = False
    def __init__(self, data): self.data = data
    def __enter__(self): return self
    def __exit__(self, *args): self.closed = True
    def raise_for_status(self): pass
    def iter_content(self, chunk_size): yield self.data


def test_success_is_cached_and_failed_read_is_not_presented_as_fresh(reset, monkeypatch):
    response = Response(json.dumps({'schemaVersion':'argus-event-result-source-v1','pairs':[]}).encode())
    calls = []
    def get(url, **kwargs):
        calls.append(url)
        assert kwargs['stream'] is True and kwargs['allow_redirects'] is False
        return response
    monkeypatch.setattr(requests, 'get', get)
    first = source.read_source(); first['data']['pairs'].append('client-mutation')
    assert source.read_source()['data']['pairs'] == [] and len(calls) == 1
    assert response.closed
    read_at = source._CACHE['readAt']
    monkeypatch.setattr(source, '_RETRY_AT', 0)
    def fail(*args, **kwargs): raise requests.Timeout()
    monkeypatch.setattr(requests, 'get', fail)
    failure = source.read_source()
    assert failure['status'] == 'UNAVAILABLE' and 'data' not in failure
    assert failure['lastSuccessfulReadAt'] == read_at
    assert source.read_source() == failure


def test_response_bound_closes_stream_and_reports_unavailable(reset, monkeypatch):
    response = Response(b'x' * (source.MAX_BYTES + 1))
    monkeypatch.setattr(requests, 'get', lambda *args, **kwargs:response)
    assert source.read_source()['status'] == 'UNAVAILABLE'
    assert response.closed
