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


@pytest.mark.parametrize('error,kind,status', [
    (urllib.error.HTTPError('https://secret.example/token', 502, 'secret-token', {'Secret':'secret-token'}, io.BytesIO(b'secret-token')), 'HTTP_ERROR', 502),
    (urllib.error.URLError(TimeoutError('secret-token')), 'TIMEOUT', None),
    (urllib.error.URLError('https://secret.example/token secret-token'), 'URL_ERROR', None),
])
def test_failed_open_reports_only_allowlisted_transport_metadata(error, kind, status):
    def request(req, timeout):
        assert timeout == 120
        raise error
    moments = iter([10, 130])
    with pytest.raises(ValueError) as caught:
        warm('runtime', 'secret-token', open_request=request, now=lambda: next(moments))
    expected = {'index':0, 'kind':kind, 'phase':'OPEN', 'elapsedMs':120000}
    if status is not None:
        expected['httpStatus'] = status
    assert caught.value.diagnostic == expected
    assert 'secret' not in str(caught.value.diagnostic)
    assert str(caught.value) == 'warm_read_failed:0'
    assert caught.value.__suppress_context__


def test_body_timeout_identifies_drain_without_retries_or_body_disclosure():
    calls=[]
    class BodyTimeout(Response):
        def read(self, size):
            assert size == 65536
            raise TimeoutError('secret-body-and-token')
    def request(req, timeout):
        calls.append(req.full_url)
        return BodyTimeout(req.full_url)
    moments=iter([0,120])
    with pytest.raises(ValueError) as caught:
        warm('runtime', 'secret-token', open_request=request, now=lambda: next(moments))
    assert caught.value.diagnostic == {'index':0, 'kind':'TIMEOUT', 'phase':'DRAIN_BODY', 'elapsedMs':120000, 'httpStatus':200}
    assert len(calls)==1
    assert 'secret' not in str(caught.value.diagnostic)


@pytest.mark.parametrize('status,kind', [(401,'HTTP_ERROR'),(200,'UNEXPECTED_RESPONSE_URL')])
def test_response_rejection_classifies_numeric_status_without_final_url(status,kind):
    def request(req, timeout):
        response=Response('https://secret.example/token')
        response.status=status
        return response
    moments=iter([0,0.25])
    with pytest.raises(ValueError) as caught:
        warm('charts','secret-token',open_request=request,now=lambda:next(moments))
    assert caught.value.diagnostic == {'index':0,'kind':kind,'phase':'VALIDATE_RESPONSE','elapsedMs':250,'httpStatus':status}
    assert 'secret' not in str(caught.value.diagnostic)


def test_cli_emits_safe_failure_metadata_and_failure_exit(monkeypatch,capsys):
    import json
    import sys
    from scripts import warm_protected_reads as module
    monkeypatch.setattr(sys,'argv',['warm_protected_reads.py','--group','runtime'])
    monkeypatch.setenv('ARGUS_ADMIN_TOKEN','secret-token')
    def failed(*args,**kwargs):
        raise module.WarmReadFailure(0,kind='TIMEOUT',phase='OPEN',elapsed_ms=120000,status=None)
    monkeypatch.setattr(module,'warm',failed)
    assert module.main()==1
    output=capsys.readouterr().out
    assert json.loads(output)=={'status':'failed','code':'warm_read_failed:0','diagnostic':{'index':0,'kind':'TIMEOUT','phase':'OPEN','elapsedMs':120000}}
    assert 'secret-token' not in output
