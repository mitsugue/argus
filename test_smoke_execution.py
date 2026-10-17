"""本番監視は読み取りだけを認証し、拒否・遅延を合格にしない。"""
import io
import time
import urllib.error

import pytest

import smoke_test as smoke


NEGATIVE_PROBES = [
    smoke._crypto_scan_gated, smoke.v_watchlist_sync_gated,
    smoke.v_official_admin_gated, smoke.v_explain_request_public,
    smoke.v_translation_request_public, smoke.v_queue_admin_gated,
    smoke.v_investigate_now_public, smoke.v_bridge_heartbeat_gated,
    smoke.v_patrol_self_check_gated, smoke.v_watchtower_admin_gated,
    smoke.v_macro_reaction_admin_gated, smoke.v_macro_repair_admin_gated,
    smoke.v_macro_admin_gated, smoke.v_learning_memory_admin_gated,
    smoke.v_admin_gated_401('/api/argus/security-status'),
]


@pytest.mark.parametrize('probe', NEGATIVE_PROBES)
def test_rejection_probes_never_send_the_available_admin_credential(monkeypatch, probe):
    monkeypatch.setitem(smoke._SMOKE_HEADERS, 'X-ARGUS-ADMIN-TOKEN', 'test-only')
    calls = []
    def reject(request, **kwargs):
        calls.append(request)
        assert all(k.lower() != 'x-argus-admin-token' for k, v in request.header_items())
        raise urllib.error.HTTPError(request.full_url, 401, 'Unauthorized', {},
                                     io.BytesIO(b'{"error":"owner_auth_required"}'))
    monkeypatch.setattr(smoke.urllib.request, 'urlopen', reject)
    assert probe()[0] is True
    assert calls


def test_actual_read_retains_admin_authentication(monkeypatch):
    monkeypatch.setitem(smoke._SMOKE_HEADERS, 'X-ARGUS-ADMIN-TOKEN', 'test-only')
    class Response(io.BytesIO):
        def getcode(self):
            return 200
    def read(request, **kwargs):
        assert dict((k.lower(), v) for k, v in request.header_items())['x-argus-admin-token'] == 'test-only'
        return Response(b'{"status":"ok"}')
    monkeypatch.setattr(smoke.urllib.request, 'urlopen', read)
    assert smoke._get('/api/argus/action-labels') == (200, {'status': 'ok'})


@pytest.mark.parametrize('probe', NEGATIVE_PROBES)
def test_rate_limit_is_not_proof_of_authentication(monkeypatch, probe):
    def limited(request, **kwargs):
        raise urllib.error.HTTPError(request.full_url, 429, 'Limited', {}, io.BytesIO(b'{}'))
    monkeypatch.setattr(smoke.urllib.request, 'urlopen', limited)
    assert probe()[0] is False


def test_retry_never_turns_rate_limiting_into_a_pass(monkeypatch):
    monkeypatch.setattr(smoke.time, 'sleep', lambda _: None)
    calls = []
    def limited():
        calls.append(1)
        raise urllib.error.HTTPError('https://example.invalid', 429, 'Limited', {}, None)
    assert smoke.check('limit', limited)[1] is False
    assert len(calls) == 3


def test_probe_deadline_interrupts_nested_sleep_and_reports_unverified():
    started = time.monotonic()
    _, passed, detail = smoke.check('slow', lambda: (time.sleep(2), 'x'), budget_seconds=.02)
    assert not passed and '未確認' in detail
    assert time.monotonic() - started < .5


def test_total_deadline_reports_all_unrun_items_and_prints_completed_result(monkeypatch, capsys):
    ran = []
    monkeypatch.setattr(smoke, 'CHECKS', [('slow', lambda: time.sleep(2)),
                                        ('next', lambda: ran.append(True))])
    assert smoke.main(total_budget=.02) == 1
    assert ran == []
    out = capsys.readouterr().out
    assert 'slow' in out and 'next' in out and '未実施' in out and '0/2' in out
