import io
import json
import os
import socket
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

import pytest

from scripts import remote_receipt_drain as drain


BUILD = "a" * 40
COMMIT = "b" * 40
OPERATION = "rr-" + "c" * 24
TARGET = 8403
BASE = "https://argus-backend.example"


class _Clock:
    def __init__(self):
        self.value = 0.0
        self.sleeps = []

    def monotonic(self):
        return self.value

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.value += seconds


def _body(*, state="pending", drain_status="writer_lock_contended",
          verified_at=None):
    value = {
        "ok": True,
        "status": "verified" if state == "verified" else "pending",
        "durabilityState": state,
        "drainStatus": drain_status,
        "operationId": OPERATION,
        "remoteCommitSha": COMMIT,
        "targetWalSequence": TARGET,
        "verifiedWalSequence": TARGET if state == "verified" else None,
        "verifiedByRemoteCommitSha": COMMIT if state == "verified" else None,
        "readBackVerified": state == "verified",
        "verifiedAt": verified_at,
        "ageSeconds": 12,
    }
    return 200 if state == "verified" else 202, json.dumps(value)


def _run(request, clock, *, budget=240):
    return drain.drain_until_verified(
        base_url=BASE,
        operation_id=OPERATION,
        backend_build_sha=BUILD,
        remote_commit_sha=COMMIT,
        target_wal_sequence=TARGET,
        token="admin",
        budget_seconds=budget,
        request_json=request,
        monotonic=clock.monotonic,
        sleep=clock.sleep)


def test_lock_contention_is_retriggered_and_never_green_while_pending():
    clock = _Clock()
    responses = iter([
        _body(),
        _body(state="verified", drain_status="verified",
              verified_at="2026-08-28T00:00:01Z"),
    ])
    calls = []

    def request(**kwargs):
        calls.append(kwargs)
        return next(responses)

    result = _run(request, clock)
    assert result["status"] == "verified"
    assert result["attempts"] == 2
    assert result["lockContentionCount"] == 1
    assert result["elapsedSeconds"] == 1.0
    assert clock.sleeps == [1.0]
    assert all(call["method"] == "POST" for call in calls)
    assert all(call["timeout"] <= 180 for call in calls)


def test_pending_exhaustion_fails_visibly_inside_one_wall_clock_budget():
    clock = _Clock()

    def request(**_kwargs):
        return _body()

    with pytest.raises(
            drain.DrainError, match="receipt_not_verified_within_budget"):
        _run(request, clock, budget=3)
    assert clock.value == 3.0


def test_timed_out_trigger_switches_to_status_only_and_accepts_exact_terminal():
    clock = _Clock()
    calls = []

    def request(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise socket.timeout()
        return _body(state="verified", drain_status=None,
                     verified_at="2026-08-28T00:00:02Z")

    result = _run(request, clock)
    assert result["status"] == "verified"
    assert result["attempts"] == 1
    assert calls[0]["method"] == "POST"
    assert calls[1]["method"] == "GET"
    assert "/receipts/" + OPERATION in calls[1]["url"]


@pytest.mark.parametrize("field,value,error", [
    ("operationId", "rr-" + "d" * 24, "drain_operation_mismatch"),
    ("remoteCommitSha", "d" * 40, "drain_commit_mismatch"),
    ("targetWalSequence", TARGET + 1, "drain_target_wal_mismatch"),
    ("verifiedWalSequence", TARGET - 1, "verified_wal_sequence_mismatch"),
    ("verifiedAt", "not-a-time", "verified_at_invalid"),
])
def test_terminal_identity_and_ack_timestamp_are_fail_closed(
        field, value, error):
    clock = _Clock()
    code, raw = _body(
        state="verified", drain_status="verified",
        verified_at="2026-08-28T00:00:03Z")
    body = json.loads(raw)
    body[field] = value

    def request(**_kwargs):
        return code, json.dumps(body)

    with pytest.raises(drain.DrainError, match=error):
        _run(request, clock)


def test_cli_never_logs_admin_secret_on_failure():
    out, err = io.StringIO(), io.StringIO()
    secret = "must-not-appear"
    with mock.patch.dict(os.environ, {"TEST_ADMIN_TOKEN": secret}), \
            mock.patch.object(
                drain, "drain_until_verified",
                side_effect=drain.DrainError("receipt_not_verified")), \
            redirect_stdout(out), redirect_stderr(err):
        rc = drain.main([
            "--name", "test",
            "--base-url", BASE,
            "--operation-id", OPERATION,
            "--backend-build-sha", BUILD,
            "--remote-commit-sha", COMMIT,
            "--target-wal-sequence", str(TARGET),
            "--token-env", "TEST_ADMIN_TOKEN",
        ])
    assert rc == 1
    assert secret not in out.getvalue() + err.getvalue()
