import json
from unittest import mock
from scripts import macro_readiness as mr

READY = {'schemaVersion': 'argus-public-readiness-v1', 'ready': True, 'status': 'ready'}
PENDING = {**READY, 'ready': False, 'status': 'not_ready'}


def test_cutover_waits_then_reads_ready_without_post():
    with mock.patch.object(mr, 'request_json', side_effect=[
            (502, 'Bad Gateway'), (200, json.dumps(PENDING)),
            (200, json.dumps(READY))]) as request, mock.patch.object(mr.time, 'sleep'):
        assert mr.wait_ready('https://example.invalid/readyz')
    assert request.call_count == 3
    assert all(c.kwargs['method'] == 'GET' and c.kwargs['timeout'] == 20
               for c in request.call_args_list)


def test_pending_exhaustion_fails_with_bounded_wait():
    with mock.patch.object(mr, 'request_json', return_value=(200, json.dumps(PENDING))) as request, \
            mock.patch.object(mr.time, 'sleep') as sleep:
        assert not mr.wait_ready('https://example.invalid/readyz')
    assert request.call_count == 5
    assert sleep.call_args_list == [mock.call(30)] * 4


def test_invalid_contract_and_auth_never_succeed_or_retry():
    for code, body in [(200, {'ok': True}), (201, READY), (401, {'error': 'unauthorized'}),
                       (200, {**READY, 'ready': 'true'}), (200, {**READY, 'ok': False})]:
        with mock.patch.object(mr, 'request_json', return_value=(code, json.dumps(body))) as request:
            assert not mr.wait_ready('https://example.invalid/readyz')
        assert request.call_count == 1


def test_transport_retry_does_not_log_secret(capsys):
    with mock.patch.object(mr, 'request_json', side_effect=[OSError('private-token'),
            (200, json.dumps(READY))]), mock.patch.object(mr.time, 'sleep'):
        assert mr.wait_ready('https://example.invalid/readyz')
    assert 'private-token' not in capsys.readouterr().out
