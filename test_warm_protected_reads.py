import io
import urllib.error
import pytest
from scripts.warm_protected_reads import BACKEND, RUNTIME_PATHS, CHART_PATHS, NoRedirect, warm

class Response(io.BytesIO):
    status = 200
    def __init__(self, url):
        super().__init__(b'x' * 200000)
        self.url = url
    def geturl(self):
        return self.url

@pytest.mark.parametrize('group,paths', [('runtime', RUNTIME_PATHS), ('charts', CHART_PATHS)])
def test_exact_paths_streamed_with_server_header(group, paths):
    calls = []
    def request(req, timeout):
        assert timeout == 120
        assert req.headers['X-argus-admin-token'] == 'synthetic-token'
        assert req.full_url.startswith(BACKEND + '/api/argus/')
        calls.append(req.full_url)
        return Response(req.full_url)
    result = warm(group, 'synthetic-token', open_request=request)
    assert calls == [BACKEND + path for path in paths]
    assert len(result) == len(paths)
    assert all(row['status'] == 200 for row in result)
    assert 'synthetic-token' not in str(result)

@pytest.mark.parametrize('status', [204,301,302,307,308,401,403,429,500])
def test_unsuccessful_read_stops_immediately(status):
    calls = []
    def request(req, timeout):
        calls.append(req)
        response = Response(req.full_url)
        response.status = status
        return response
    with pytest.raises(ValueError, match='warm_read_failed:0'):
        warm('runtime', 'synthetic-token', open_request=request)
    assert len(calls) == 1

@pytest.mark.parametrize('error', [TimeoutError('synthetic-token'), OSError('synthetic-token')])
def test_transport_exception_never_discloses_secret(error):
    def request(req, timeout):
        raise error
    with pytest.raises(ValueError) as exc:
        warm('charts', 'synthetic-token', open_request=request)
    assert str(exc.value) == 'warm_read_failed:0'
    assert exc.value.__suppress_context__

def test_missing_token_never_requests():
    with pytest.raises(ValueError, match='warm_configuration'):
        warm('runtime', '', open_request=lambda *a, **k: pytest.fail('network'))

def test_redirect_handler_and_changed_final_url_rejected():
    assert NoRedirect().redirect_request(None,None,302,'',{},'https://elsewhere.example') is None
    with pytest.raises(ValueError, match='warm_read_failed:0'):
        warm('runtime', 'synthetic-token', open_request=lambda *a, **k: Response('https://elsewhere.example'))
