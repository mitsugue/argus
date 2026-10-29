import io
import json
import urllib.error

from scripts.event_snapshot_read import read_snapshot


class Response:
    status = 200
    def __init__(self, body): self.body = body
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def read(self, size): return self.body


def test_transient_unavailability_then_valid_snapshot(tmp_path):
    calls = []
    def request(req, timeout):
        calls.append(req)
        if len(calls) < 3:
            raise urllib.error.HTTPError(req.full_url, 503, 'private', {}, None)
        return Response(b'{"activeCount":2,"private":"body"}')
    now = [0]
    result = read_snapshot(url='https://example.test', token='secret', output=tmp_path/'snap',
                           request=request, clock=lambda: now[0], sleep=lambda n: now.__setitem__(0, now[0]+n))
    assert result == {'status': 'done', 'activeCount': 2, 'attempts': 3}
    assert json.loads((tmp_path/'snap').read_text())['activeCount'] == 2
    assert 'secret' not in json.dumps(result) and 'private' not in json.dumps(result)


def test_auth_rejection_does_not_retry_or_write(tmp_path):
    calls = []
    def request(req, timeout):
        calls.append(1)
        raise urllib.error.HTTPError(req.full_url, 401, 'secret', {}, None)
    result = read_snapshot(url='https://example.test', token='secret', output=tmp_path/'snap', request=request)
    assert result['errorClass'] == 'snapshot_rejected' and result['httpStatus'] == 401
    assert len(calls) == 1 and not (tmp_path/'snap').exists()


def test_timeout_and_malformed_snapshot_do_not_overwrite(tmp_path):
    target = tmp_path/'snap'
    target.write_text('prior')
    now = [0]
    def unavailable(req, timeout): raise TimeoutError('secret')
    result = read_snapshot(url='https://example.test', token='secret', output=target, timeout=30,
                           request=unavailable, clock=lambda: now[0], sleep=lambda n: now.__setitem__(0, now[0]+n))
    assert result['errorClass'] == 'snapshot_timeout' and target.read_text() == 'prior'
    result = read_snapshot(url='https://example.test', token='secret', output=target,
                           request=lambda *a, **k: Response(b'{"activeCount":"2\\nEVIL=1"}'))
    assert result['errorClass'] == 'snapshot_invalid' and target.read_text() == 'prior'


def test_redirect_is_not_followed_and_never_retries(tmp_path):
    from scripts.event_snapshot_read import _NoRedirect
    handler = _NoRedirect()
    assert handler.redirect_request(None, None, 302, 'redirect', {}, 'https://other.example') is None
    calls = []
    def redirect(req, timeout):
        calls.append(1)
        raise urllib.error.HTTPError(req.full_url, 302, 'redirect', {}, None)
    result = read_snapshot(url='https://example.test', token='secret', output=tmp_path/'snap', request=redirect)
    assert result['errorClass'] == 'snapshot_rejected' and result['httpStatus'] == 302
    assert len(calls) == 1 and not (tmp_path/'snap').exists()
