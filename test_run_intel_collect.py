import json

from scripts.run_intel_collect import run


def test_lost_response_reuses_id_and_waits_until_warming_finishes():
    calls, tick = [], [0]

    def request(**kwargs):
        body = json.loads(kwargs["data"])
        calls.append(body)
        if len(calls) == 1:
            raise TimeoutError("lost response")
        status = "done" if len(calls) == 4 else "running"
        return 200, json.dumps({"status": status, "runId": "test-run-1",
                                "finishedAt": "2026-09-09T00:00:00Z" if status == "done" else None,
                                "result": {"collected": 3, "stored": 40}})

    def sleep(n):
        tick[0] += n

    result = run(base="https://example.test", token="secret", request=request,
                 clock=lambda: tick[0], sleep=sleep, request_id="test-run-1")
    assert result["status"] == "done" and result["collected"] == 3
    assert calls[:2] == [{"async": True, "requestId": "test-run-1"}] * 2
    assert calls[2:] == [{"statusOnly": True, "requestId": "test-run-1"}] * 2
    assert "secret" not in json.dumps(result)


def test_failure_restart_or_legacy_endpoint_never_passes():
    for code, body in [(404, {}), (200, {"collected": 2}),
                       (200, {"status": "failed", "runId": "test-run-1", "errorClass": "RuntimeError"})]:
        result = run(base="https://example.test", token="secret", request_id="test-run-1",
                     request=lambda **kw: (code, json.dumps(body)))
        assert result["status"] == "failed"


def test_still_running_at_deadline_fails_and_poll_identity_cannot_change():
    tick = [0]
    def sleep(n):
        tick[0] += n
    result = run(base="https://example.test", token="secret", timeout=10,
                 request_id="test-run-1", clock=lambda: tick[0], sleep=sleep,
                 request=lambda **kw: (200, '{"status":"running","runId":"test-run-1"}'))
    assert result["errorClass"] == "collect_poll_timeout"
    replies = iter([{"status": "running", "runId": "active-run-2"},
                    {"status": "done", "runId": "different-run-3"}])
    result = run(base="https://example.test", token="secret", request_id="test-run-1",
                 request=lambda **kw: (200, json.dumps(next(replies))), sleep=lambda n: None)
    assert result["errorClass"] == "collect_run_identity_mismatch"


def test_all_failed_feeds_do_not_pass_just_because_the_worker_finished():
    result = run(base="https://example.test", token="secret", request_id="test-run-1",
                 request=lambda **kw: (200, json.dumps({"status": "done", "runId": "test-run-1",
                    "result": {"feeds": 2, "failedFeeds": ["feed-a", "feed-b"], "stored": 40}})))
    assert result["status"] == "failed" and result["errorClass"] == "all_intel_feeds_unavailable"
