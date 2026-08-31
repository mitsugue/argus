"""Focused bounded tests for the secondary natural Remote Journal re-arm."""
from __future__ import annotations

import copy
import datetime as dt
import fcntl
import io
import json
import os
import re
import sys
import types
from pathlib import Path
from unittest import mock
import urllib.error
import urllib.request

import pytest

import argus_remote_journal as journal
import argus_remote_receipt_queue as queue
import argus_state_journal
from scripts.deploy_scope import classify
from scripts import argus_remote_journal_rearm as rearm
from scripts import argus_watchtower_writer_dispatch as writer
from scripts.remote_journal_publish_policy import (
    PublishPolicyError,
    publication_decision,
    receipt_request,
)


BUILD = "a" * 40
REMOTE_COMMIT = "b" * 40
LOCAL_WAL = 4694
REMOTE_WAL = 4659

_moomoo = types.ModuleType("moomoo")
_moomoo.OpenQuoteContext = lambda *args, **kwargs: None
_moomoo.OpenSecTradeContext = lambda *args, **kwargs: None
_moomoo.RET_OK = 0
sys.modules.setdefault("moomoo", _moomoo)
import scanner


def _truth(*, local_wal=LOCAL_WAL, remote_wal=REMOTE_WAL,
           pending=30, committed=370):
    health = {
        "status": "ok", "backendVersion": "13.4.12", "buildSha": BUILD,
    }
    ready = {
        "ready": True, "backendVersion": "13.4.12", "buildSha": BUILD,
    }
    quality = {
        "schemaVersion": "argus-operational-diagnostics-v1",
        "service": {
            "backendVersion": "13.4.12", "buildSha": BUILD,
        },
        "durability": {
            "integrityStatus": "ok", "journalCorruptCount": 0,
            "missionWalCorruptCount": 0,
            "checkpoint": {
                "verified": True, "readBackVerified": True,
                "includedWalSequence": local_wal,
            },
        },
        "remoteJournal": {
            "readBackVerified": True, "walReadBackVerified": True,
            "state": "verified",
            "remoteWalAppliedSequence": remote_wal,
            "verifiedWalSequence": remote_wal,
            "localCommittedCount": pending + committed,
            "pendingCount": pending,
            "committedCount": committed, "failedCount": 0,
            "errorPresent": False,
        },
    }
    return health, ready, quality


def _event(number):
    return argus_state_journal.event(
        event_type="mission_completed", aggregate_type="mission",
        aggregate_id=f"rearm-{number}", sequence=number,
        occurred_at=f"2026-08-12T00:{number:02d}:00Z", payload={})


def _readback(wal, count):
    full = {
        "schemaVersion": journal.SCHEMA_V3,
        "generatedAt": "2026-08-12T00:30:00Z",
        "asOf": "2026-08-12T00:30:00Z",
        "buildIdentity": {"appVersion": "13.4.13", "buildSha": BUILD},
        "outcomes": [],
        "missionTickDurability": {
            "walAppliedSequence": wal, "remoteWalAppliedSequence": wal,
            "verifiedWalSequence": min(wal, REMOTE_WAL),
        },
        "marketLedgerStateHash": "1" * 16,
        "chartIntelligenceStateHash": "2" * 16,
        "todayIntelligenceStateHash": "3" * 16,
        "marketReplayStateHash": "4" * 16,
        **journal.snapshot_journal_section(
            events=[_event(n) for n in range(1, count + 1)], meta={},
            now_iso="2026-08-12T00:30:00Z"),
    }
    return journal.compact_readback_snapshot(full)


class _Response:
    def __init__(self, body=None, status=200):
        self.status = status
        self.body = body if isinstance(body, bytes) else json.dumps(
            body or {}).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, amount=-1):
        return self.body if amount < 0 else self.body[:amount]


WRITER_TOKEN = "github_pat_" + "A" * 40


def _writer_root(tmp_path):
    root = tmp_path / "writer-state"
    root.mkdir(mode=0o700, parents=True)
    return root


def _writer_public_opener(request, timeout):
    assert timeout > 0
    body = {
        "status": "ok", "ready": True, "backendVersion": "13.5.36",
        "buildSha": BUILD,
    }
    return _Response(body)


def test_writer_calendar_is_exact_duplicate_free_and_bounded():
    assert writer.WEEKDAY_MINUTES == (4, 11, 19, 26, 34, 41, 49, 56)
    assert writer.WEEKEND_MINUTES == (4, 34)
    weekday_gaps = [7, 8, 7, 8, 7, 8, 7, 8]
    weekend_gaps = [30, 30]
    assert max(weekday_gaps) * 60 == 480
    assert max(weekend_gaps) * 60 == 1800
    assert len(set(writer.WEEKDAY_MINUTES)) == 8
    assert len(set(writer.WEEKEND_MINUTES)) == 2
    monday = dt.datetime(2026, 8, 31, 13, 21, 55,
                         tzinfo=dt.timezone.utc)
    sunday = dt.datetime(2026, 8, 30, 13, 50,
                         tzinfo=dt.timezone.utc)
    assert writer.format_slot(writer.canonical_slot(monday)) == \
        "2026-08-31T13:19:00Z"
    assert writer.format_slot(writer.canonical_slot(sunday)) == \
        "2026-08-30T13:34:00Z"


def test_writer_inputs_are_disjoint_and_deterministically_bound():
    scheduled = "2026-08-31T13:19:00Z"
    dispatch_id = writer.writer_dispatch_id(scheduled)
    natural = writer.validate_dispatch_inputs(
        remote_journal_rearm=False,
        dispatch_mode="ec2_systemd_writer",
        writer_scheduled_for=scheduled,
        supplied_dispatch_id=dispatch_id)
    assert natural == {
        "natural": True,
        "policySource": "ec2_systemd_writer",
        "writerScheduledFor": scheduled,
        "writerDispatchId": dispatch_id,
    }
    assert writer.validate_dispatch_inputs(
        remote_journal_rearm=False, dispatch_mode="owner_manual",
        writer_scheduled_for="", supplied_dispatch_id=""
    )["natural"] is False
    assert writer.validate_dispatch_inputs(
        remote_journal_rearm=True, dispatch_mode="owner_manual",
        writer_scheduled_for="", supplied_dispatch_id=""
    )["policySource"] == "remote_journal_rearm"


@pytest.mark.parametrize("kwargs,error", [
    ({"remote_journal_rearm": False, "dispatch_mode": "ec2_systemd_writer",
      "writer_scheduled_for": "2026-08-31T13:20:00Z",
      "supplied_dispatch_id": "awwd-" + "a" * 32},
     "writer_slot_not_canonical"),
    ({"remote_journal_rearm": False, "dispatch_mode": "ec2_systemd_writer",
      "writer_scheduled_for": "2026-08-31T13:19:00Z",
      "supplied_dispatch_id": "awwd-" + "a" * 32},
     "writer_dispatch_id_invalid"),
    ({"remote_journal_rearm": False, "dispatch_mode": "owner_manual",
      "writer_scheduled_for": "2026-08-31T13:19:00Z",
      "supplied_dispatch_id": ""}, "manual_dispatch_inputs_mixed"),
    ({"remote_journal_rearm": True, "dispatch_mode": "ec2_systemd_writer",
      "writer_scheduled_for": "2026-08-31T13:19:00Z",
      "supplied_dispatch_id": "awwd-" + "a" * 32},
     "rearm_dispatch_inputs_mixed"),
])
def test_writer_invalid_or_mixed_inputs_fail_closed(kwargs, error):
    with pytest.raises(writer.WriterDispatchError, match=error):
        writer.validate_dispatch_inputs(**kwargs)


@pytest.mark.parametrize("field,value,error", [
    ("repository", "other/argus", "writer_repository_invalid"),
    ("workflow", "other.yml", "writer_workflow_invalid"),
    ("ref", "ledger", "writer_ref_invalid"),
])
def test_writer_wrong_repository_workflow_or_ref_fails(field, value, error):
    scheduled = "2026-08-31T13:19:00Z"
    kwargs = {
        "remote_journal_rearm": False,
        "dispatch_mode": "ec2_systemd_writer",
        "writer_scheduled_for": scheduled,
        "supplied_dispatch_id": writer.writer_dispatch_id(scheduled),
        field: value,
    }
    with pytest.raises(writer.WriterDispatchError, match=error):
        writer.validate_dispatch_inputs(**kwargs)


def test_writer_dispatch_is_exactly_once_and_duplicate_safe(tmp_path):
    root = _writer_root(tmp_path)
    posts = []

    def post(request, timeout):
        assert timeout > 0
        posts.append(request)
        return _Response(status=204)

    now = dt.datetime(2026, 8, 31, 13, 21, tzinfo=dt.timezone.utc)
    first = writer.dispatch_slot(
        now=now, token=WRITER_TOKEN, root=root,
        public_opener=_writer_public_opener, post_opener=post)
    second = writer.dispatch_slot(
        now=now, token=WRITER_TOKEN, root=root,
        public_opener=lambda *_args, **_kwargs: pytest.fail(
            "duplicate fetched public state"),
        post_opener=lambda *_args, **_kwargs: pytest.fail("duplicate POST"))
    assert first["phase"] == "DISPATCH_ACCEPTED"
    assert first["status"] == "dispatch_accepted"
    assert first["executionProven"] is False
    assert second["status"] == "duplicate_suppressed"
    assert len(posts) == 1
    assert json.loads(posts[0].data) == {
        "ref": "main",
        "inputs": {
            "remoteJournalRearm": "false",
            "dispatchMode": "ec2_systemd_writer",
            "writerScheduledFor": "2026-08-31T13:19:00Z",
            "writerDispatchId": writer.writer_dispatch_id(
                "2026-08-31T13:19:00Z"),
        },
    }
    assert "Authorization" in posts[0].headers
    assert WRITER_TOKEN not in json.dumps(first)


def test_writer_crash_before_attempt_can_resume_without_duplicate(tmp_path):
    root = _writer_root(tmp_path)
    now = dt.datetime(2026, 8, 31, 13, 21, tzinfo=dt.timezone.utc)
    with pytest.raises(RuntimeError, match="before attempt"):
        writer.dispatch_slot(
            now=now, token=WRITER_TOKEN, root=root,
            public_opener=_writer_public_opener,
            post_opener=lambda *_args, **_kwargs: pytest.fail(
                "POST before marker"),
            before_attempt=lambda: (_ for _ in ()).throw(
                RuntimeError("before attempt")))
    sent = []
    result = writer.dispatch_slot(
        now=now, token=WRITER_TOKEN, root=root,
        public_opener=_writer_public_opener,
        post_opener=lambda request, **_kwargs: (
            sent.append(request) or _Response(status=204)))
    assert result["phase"] == "DISPATCH_ACCEPTED"
    assert len(sent) == 1


def test_writer_crash_after_attempt_reconciles_and_never_resends(tmp_path):
    root = _writer_root(tmp_path)
    now = dt.datetime(2026, 8, 31, 13, 21, tzinfo=dt.timezone.utc)
    with pytest.raises(RuntimeError, match="post boundary"):
        writer.dispatch_slot(
            now=now, token=WRITER_TOKEN, root=root,
            public_opener=_writer_public_opener,
            post_opener=lambda *_args, **_kwargs: pytest.fail(
                "crash precedes POST"),
            before_post=lambda: (_ for _ in ()).throw(
                RuntimeError("post boundary")))
    dispatch_id = writer.writer_dispatch_id("2026-08-31T13:19:00Z")
    runs = {"workflow_runs": [{
        "display_title": f"Watchtower EC2 {dispatch_id}",
        "event": "workflow_dispatch", "head_branch": "main",
    }]}
    result = writer.dispatch_slot(
        now=now, token=WRITER_TOKEN, root=root,
        post_opener=lambda *_args, **_kwargs: pytest.fail("ambiguous resend"),
        reconcile_opener=lambda *_args, **_kwargs: _Response(runs))
    assert result["phase"] == "DISPATCH_ACCEPTED"
    assert result["reconciled"] is True


def test_writer_crash_after_accepted_post_reconciles_without_resend(tmp_path):
    root = _writer_root(tmp_path)
    now = dt.datetime(2026, 8, 31, 13, 21, tzinfo=dt.timezone.utc)
    with pytest.raises(RuntimeError, match="accepted boundary"):
        writer.dispatch_slot(
            now=now, token=WRITER_TOKEN, root=root,
            public_opener=_writer_public_opener,
            post_opener=lambda *_args, **_kwargs: _Response(status=204),
            after_post=lambda: (_ for _ in ()).throw(
                RuntimeError("accepted boundary")))
    dispatch_id = writer.writer_dispatch_id("2026-08-31T13:19:00Z")
    result = writer.dispatch_slot(
        now=now, token=WRITER_TOKEN, root=root,
        post_opener=lambda *_args, **_kwargs: pytest.fail(
            "accepted POST repeated"),
        reconcile_opener=lambda *_args, **_kwargs: _Response({"workflow_runs": [{
            "display_title": f"Watchtower EC2 {dispatch_id}",
            "event": "workflow_dispatch", "head_branch": "main",
        }]}))
    assert result["status"] == "dispatch_acceptance_reconciled"


def test_writer_unproven_ambiguous_dispatch_is_terminal(tmp_path):
    root = _writer_root(tmp_path)
    now = dt.datetime(2026, 8, 31, 13, 21, tzinfo=dt.timezone.utc)
    with pytest.raises(writer.WriterDispatchError,
                       match="workflow_dispatch_ambiguous"):
        writer.dispatch_slot(
            now=now, token=WRITER_TOKEN, root=root,
            public_opener=_writer_public_opener,
            post_opener=lambda *_args, **_kwargs: (
                _ for _ in ()).throw(TimeoutError()),
            reconcile_opener=lambda *_args, **_kwargs: _Response(
                {"workflow_runs": []}))
    state_file = next(path for path in root.glob("*.json"))
    assert json.loads(state_file.read_text())["phase"] == "FAILED_AMBIGUOUS"


@pytest.mark.parametrize("status,phase", [
    (401, "FAILED_DEFINITE"), (403, "FAILED_DEFINITE"),
    (404, "FAILED_DEFINITE"), (500, "FAILED_AMBIGUOUS"),
])
def test_writer_http_failures_are_visible_without_retry(tmp_path, status, phase):
    root = _writer_root(tmp_path)

    def failure(request, timeout):
        assert timeout > 0
        raise urllib.error.HTTPError(
            request.full_url, status, "failure", {}, None)

    with pytest.raises(writer.WriterDispatchError,
                       match="workflow_dispatch_http_error"):
        writer.dispatch_slot(
            now=dt.datetime(2026, 8, 31, 13, 21,
                            tzinfo=dt.timezone.utc),
            token=WRITER_TOKEN, root=root,
            public_opener=_writer_public_opener, post_opener=failure,
            reconcile_opener=lambda *_args, **_kwargs: _Response(
                {"workflow_runs": []}))
    state_file = next(path for path in root.glob("*.json"))
    assert json.loads(state_file.read_text())["phase"] == phase


def test_writer_state_corruption_symlink_mode_and_lock_fail_closed(tmp_path):
    now = dt.datetime(2026, 8, 31, 13, 21, tzinfo=dt.timezone.utc)
    scheduled = "2026-08-31T13:19:00Z"
    dispatch_id = writer.writer_dispatch_id(scheduled)

    corrupt_root = _writer_root(tmp_path / "corrupt")
    path = writer._state_path(corrupt_root, scheduled)
    path.write_text("not-json")
    path.chmod(0o600)
    with pytest.raises(writer.WriterDispatchError, match="writer_state_corrupt"):
        writer.dispatch_slot(now=now, token=WRITER_TOKEN, root=corrupt_root)

    mode_root = _writer_root(tmp_path / "mode")
    path = writer._state_path(mode_root, scheduled)
    path.write_text(json.dumps(writer._new_state(scheduled, dispatch_id)))
    path.chmod(0o644)
    with pytest.raises(writer.WriterDispatchError,
                       match="writer_state_metadata_invalid"):
        writer.dispatch_slot(now=now, token=WRITER_TOKEN, root=mode_root)

    symlink_root = _writer_root(tmp_path / "symlink")
    target = symlink_root / "target"
    target.write_text("{}")
    writer._state_path(symlink_root, scheduled).symlink_to(target)
    with pytest.raises(writer.WriterDispatchError,
                       match="writer_state_metadata_invalid"):
        writer.dispatch_slot(now=now, token=WRITER_TOKEN, root=symlink_root)

    lock_root = _writer_root(tmp_path / "lock")
    lock = (lock_root / ".lock").open("w")
    lock_root.joinpath(".lock").chmod(0o600)
    try:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(writer.WriterDispatchError,
                           match="writer_state_lock_contended"):
            writer.dispatch_slot(now=now, token=WRITER_TOKEN, root=lock_root)
    finally:
        lock.close()


def test_writer_reconciliation_is_bounded_and_malformed_fails(tmp_path):
    oversized = b"x" * (writer.MAX_GITHUB_RESPONSE_BYTES + 1)
    with pytest.raises(writer.WriterDispatchError,
                       match="http_response_oversized"):
        writer.reconcile_dispatch(
            WRITER_TOKEN, "awwd-" + "a" * 32, timeout=3,
            opener=lambda *_args, **_kwargs: _Response(oversized))
    with pytest.raises(writer.WriterDispatchError,
                       match="github_runs_response_invalid"):
        writer.reconcile_dispatch(
            WRITER_TOKEN, "awwd-" + "a" * 32, timeout=3,
            opener=lambda *_args, **_kwargs: _Response(
                {"workflow_runs": {}}))


def test_writer_invalid_token_and_safe_output_never_disclose_secret(tmp_path):
    with pytest.raises(writer.WriterDispatchError, match="workflow_pat_invalid"):
        writer.dispatch_slot(
            now=dt.datetime(2026, 8, 31, 13, 21,
                            tzinfo=dt.timezone.utc),
            token="secret-value", root=_writer_root(tmp_path))
    output = io.StringIO()
    with mock.patch.dict(os.environ, {
            "ARGUS_REMOTE_JOURNAL_REARM_PAT": "secret-value",
            "ARGUS_WATCHTOWER_WRITER_STATE_ROOT": str(
                _writer_root(tmp_path / "main")),
            }, clear=False), mock.patch("sys.stdout", output):
        assert writer.main([]) == 1
    assert "secret-value" not in output.getvalue()
    assert json.loads(output.getvalue())["errorClass"] == \
        "workflow_pat_invalid"


def test_verified_gap_dispatches_exactly_once_without_polling():
    health, ready, _ = _truth()
    assert rearm.evaluate_truth(health, ready) == {
        "action": "dispatch", "reason": "public_ready",
    }
    seen = []

    def opener(request, timeout):
        seen.append(request)
        return _Response(status=204)

    assert rearm.dispatch_natural_rearm(
        "secret-test-token", timeout=6, opener=opener) == 204
    assert len(seen) == 1
    assert json.loads(seen[0].data) == {
        "ref": "main", "inputs": {"remoteJournalRearm": "true"}}


def test_identity_gate_tracks_live_semver_without_a_frozen_version():
    health, ready, _ = _truth()
    health["backendVersion"] = "13.4.13"
    ready["backendVersion"] = "13.4.13"
    assert rearm.evaluate_truth(health, ready)["action"] == "dispatch"
    assert "EXPECTED_BACKEND_VERSION" not in Path(
        "scripts/argus_remote_journal_rearm.py").read_text()


@pytest.mark.parametrize("mutate,error", [
    (lambda h, r: h.update(status="failed"), "health_not_ok"),
    (lambda h, r: r.update(ready=False), "backend_not_ready"),
    (lambda h, r: r.update(backendVersion="13.4.13"),
     "health_ready_version_mismatch"),
    (lambda h, r: r.update(buildSha="c" * 40),
     "health_ready_identity_mismatch"),
])
def test_public_identity_or_readiness_fails_closed(mutate, error):
    health, ready, _ = _truth()
    mutate(health, ready)
    with pytest.raises(rearm.RearmError, match=error):
        rearm.evaluate_truth(health, ready)


def test_public_truth_retry_is_two_complete_rounds_max():
    health, ready, _ = _truth()
    values = [
        urllib.error.URLError("first"), health, ready,
    ]
    calls = []

    def opener(request, timeout):
        calls.append(request.full_url)
        value = values.pop(0)
        if isinstance(value, BaseException):
            raise value
        return _Response(value)

    result = rearm.fetch_public_truth(
        "https://example.invalid", timeout=3, attempts=2, opener=opener)
    assert result[-1] == 2
    assert len(calls) == 3
    assert len(calls) <= 4


def test_public_response_size_is_bounded():
    oversized = b"x" * (rearm.MAX_PUBLIC_RESPONSE_BYTES + 1)
    with pytest.raises(rearm.RearmError, match="public_response_oversized"):
        rearm._request_json(
            "https://example.invalid", timeout=3,
            opener=lambda *_args, **_kwargs: _Response(oversized))


@pytest.mark.parametrize("response,error", [
    (_Response(b"not-json"), json.JSONDecodeError),
    (_Response({}, status=503), rearm.RearmError),
])
def test_public_json_and_http_fail_closed(response, error):
    with pytest.raises(error):
        rearm._request_json(
            "https://example.invalid", timeout=3,
            opener=lambda *_args, **_kwargs: response)


def test_public_timeout_exhausts_two_attempts():
    calls = []

    def timeout(*_args, **_kwargs):
        calls.append(1)
        raise TimeoutError

    with pytest.raises(rearm.RearmError, match="public_truth_unavailable"):
        rearm.fetch_public_truth(
            "https://example.invalid", timeout=3, attempts=2,
            opener=timeout)
    assert len(calls) == 2


def test_non_204_dispatch_is_rejected():
    with pytest.raises(rearm.RearmError, match="workflow_dispatch_rejected"):
        rearm.dispatch_natural_rearm(
            "secret", timeout=3,
            opener=lambda *_args, **_kwargs: _Response(status=202))


def test_missing_pat_and_logs_never_expose_secret_or_payload():
    health, ready, _ = _truth()
    output = io.StringIO()
    env = {
        "ARGUS_REMOTE_JOURNAL_REARM_PAT": "",
        "ARGUS_REMOTE_JOURNAL_REARM_MAX_ATTEMPTS": "1",
    }
    with mock.patch.dict(os.environ, env, clear=False), mock.patch.object(
            rearm, "fetch_public_truth",
            return_value=(health, ready, 1)), mock.patch(
                "sys.stdout", output):
        assert rearm.main() == 1
    record = json.loads(output.getvalue())
    assert record["errorClass"] == "missing_workflow_pat"
    text = output.getvalue()
    for forbidden in ("Authorization", "remoteJournalRearm", "inputs", "ref"):
        assert forbidden not in text


def test_authenticated_dispatch_disables_redirects():
    handler = rearm._NoRedirect()
    request = urllib.request.Request(
        rearm.DISPATCH_URL, headers={"Authorization": "Bearer secret"})
    assert handler.redirect_request(
        request, None, 302, "redirect", {}, "https://evil.invalid") is None
    source = Path("scripts/argus_remote_journal_rearm.py").read_text()
    assert "build_opener(_NoRedirect()).open" in source


def test_runtime_wal_gap_paths_and_stale_rearm_are_fail_closed():
    _, _, quality = _truth()
    source = _readback(LOCAL_WAL, 2)
    ledger = _readback(REMOTE_WAL, 1)
    publish = publication_decision(
        source, ledger, event_name="workflow_dispatch", utc_minute=7,
        runtime_data_quality=quality, natural_rearm=True)
    assert publish["action"] == "publish"
    assert publish["policySource"] == "remote_journal_rearm"
    assert publish["eventName"] == "workflow_dispatch"

    ledger_current = _readback(LOCAL_WAL, 2)
    receipt_only = publication_decision(
        ledger_current, ledger_current, event_name="workflow_dispatch",
        utc_minute=7, runtime_data_quality=quality, natural_rearm=True)
    assert receipt_only["action"] == "receipt_only"
    assert receipt_only["reason"] == "natural_receipt_recovery"
    request = receipt_request(
        ledger_current, remote_commit_sha=REMOTE_COMMIT,
        backend_build_sha=BUILD,
        expected_hash=ledger_current["integrityManifest"]["manifestHash"])
    assert request["payload"]["targetWalSequence"] == LOCAL_WAL

    _, _, no_event_pending = _truth(pending=0, committed=400)
    wal_recovery = publication_decision(
        ledger_current, ledger_current, event_name="workflow_dispatch",
        utc_minute=7, runtime_data_quality=no_event_pending,
        natural_rearm=True)
    assert wal_recovery["action"] == "receipt_only"
    assert wal_recovery["reason"] == "natural_runtime_wal_recovery"

    stale = _readback(REMOTE_WAL, 1)
    with pytest.raises(
            PublishPolicyError, match="natural_rearm_proof_runtime_mismatch"):
        publication_decision(
            stale, stale, event_name="workflow_dispatch", utc_minute=7,
            runtime_data_quality=quality, natural_rearm=True)

    _, _, caught_up = _truth(local_wal=LOCAL_WAL, remote_wal=LOCAL_WAL)
    skip = publication_decision(
        ledger_current, ledger_current, event_name="workflow_dispatch",
        utc_minute=7, runtime_data_quality=caught_up, natural_rearm=True)
    assert skip["action"] == "skip"
    assert skip["reason"] == "natural_rearm_caught_up"


def test_ec2_scheduled_writer_is_natural_but_owner_manual_stays_manual():
    _, _, quality = _truth(pending=0, committed=400)
    current = _readback(LOCAL_WAL, 2)
    scheduled = publication_decision(
        current, current, event_name="workflow_dispatch", utc_minute=19,
        runtime_data_quality=quality, scheduled_writer=True)
    assert scheduled["natural"] is True
    assert scheduled["scheduledWriter"] is True
    assert scheduled["naturalRearm"] is False
    assert scheduled["policySource"] == "ec2_systemd_writer"
    assert scheduled["action"] == "skip"

    manual = publication_decision(
        current, current, event_name="workflow_dispatch", utc_minute=19,
        runtime_data_quality=quality)
    assert manual["natural"] is False
    assert manual["scheduledWriter"] is False
    assert manual["policySource"] == "manual"
    assert manual["action"] == "publish"


@pytest.mark.parametrize("kwargs,error", [
    ({"event_name": "schedule", "natural_rearm": False,
      "scheduled_writer": True}, "scheduled_writer_event_invalid"),
    ({"event_name": "workflow_dispatch", "natural_rearm": True,
      "scheduled_writer": True}, "scheduled_writer_rearm_mixed"),
])
def test_scheduled_writer_invalid_combinations_fail_closed(kwargs, error):
    _, _, quality = _truth()
    current = _readback(LOCAL_WAL, 2)
    with pytest.raises(PublishPolicyError, match=error):
        publication_decision(
            current, current, utc_minute=19,
            runtime_data_quality=quality, **kwargs)


def test_duplicate_rearm_produces_one_idempotent_intent():
    source = _readback(LOCAL_WAL, 2)
    request = receipt_request(
        source, remote_commit_sha=REMOTE_COMMIT, backend_build_sha=BUILD,
        expected_hash=source["integrityManifest"]["manifestHash"])
    payload = request["payload"]
    store = queue.empty_store()
    first_store, first, replayed = queue.accept_intent(
        store, idempotency_key=request["idempotencyKey"],
        build_sha=payload["backendBuildSha"],
        remote_commit_sha=payload["remoteCommitSha"],
        expected_hash=payload["expectedHash"],
        target_wal_sequence=payload["targetWalSequence"],
        accepted_at="2026-08-12T00:31:00Z")
    assert replayed is False
    final_store, duplicate, replayed = queue.accept_intent(
        first_store, idempotency_key=request["idempotencyKey"],
        build_sha=payload["backendBuildSha"],
        remote_commit_sha=payload["remoteCommitSha"],
        expected_hash=payload["expectedHash"],
        target_wal_sequence=payload["targetWalSequence"],
        accepted_at="2026-08-12T00:32:00Z")
    assert replayed is True
    assert duplicate["operationId"] == first["operationId"]
    assert len(final_store["receipts"]) == 1


def test_exact_4694_rearm_then_next_natural_drain_advances_once():
    saved_queue = copy.deepcopy(scanner._REMOTE_RECEIPT_QUEUE)
    saved_cycle = copy.deepcopy(scanner._REMOTE_CYCLE)
    try:
        scanner._REMOTE_RECEIPT_QUEUE = queue.empty_store()
        scanner._REMOTE_CYCLE.update({
            "verifiedWalSequence": REMOTE_WAL,
            "remoteWalAppliedSequence": REMOTE_WAL,
            "readBackVerified": True,
            "walReadBackVerified": True,
            "remoteDurabilityState": "verified",
        })
        with mock.patch.object(
                scanner, "_osint_persist",
                side_effect=lambda: {"verified": True}):
            assert scanner._persist_with_remote_receipt_drain(
                "2026-08-12T00:07:00Z")["remoteReceiptFlush"][
                    "status"] == "noop"
            assert scanner._persist_with_remote_receipt_drain(
                "2026-08-12T00:37:00Z")["remoteReceiptFlush"][
                    "status"] == "noop"

        source = _readback(LOCAL_WAL, 2)
        ledger = _readback(REMOTE_WAL, 1)
        health, ready, quality = _truth()
        assert rearm.evaluate_truth(health, ready)["action"] == "dispatch"
        decision = publication_decision(
            source, ledger, event_name="workflow_dispatch", utc_minute=43,
            runtime_data_quality=quality, natural_rearm=True)
        assert decision["action"] == "publish"
        request = receipt_request(
            source, remote_commit_sha=REMOTE_COMMIT,
            backend_build_sha=BUILD,
            expected_hash=source["integrityManifest"]["manifestHash"])
        payload = request["payload"]
        accepted, first, replayed = queue.accept_intent(
            scanner._REMOTE_RECEIPT_QUEUE,
            idempotency_key=request["idempotencyKey"],
            build_sha=payload["backendBuildSha"],
            remote_commit_sha=payload["remoteCommitSha"],
            expected_hash=payload["expectedHash"],
            target_wal_sequence=payload["targetWalSequence"],
            accepted_at="2026-08-12T00:43:01Z")
        assert replayed is False
        accepted, duplicate, replayed = queue.accept_intent(
            accepted, idempotency_key=request["idempotencyKey"],
            build_sha=payload["backendBuildSha"],
            remote_commit_sha=payload["remoteCommitSha"],
            expected_hash=payload["expectedHash"],
            target_wal_sequence=payload["targetWalSequence"],
            accepted_at="2026-08-12T00:43:02Z")
        assert replayed is True
        assert duplicate["operationId"] == first["operationId"]
        scanner._REMOTE_RECEIPT_QUEUE = accepted

        def persist(store):
            scanner._REMOTE_RECEIPT_QUEUE = copy.deepcopy(store)
            return {"verified": True, "readBackVerified": True}

        def verify(now_iso=None, blob=None):
            scanner._REMOTE_CYCLE.update({
                "readBackVerified": True,
                "walReadBackVerified": True,
                "remoteDurabilityState": "verified",
                "verifiedWalSequence": LOCAL_WAL,
                "remoteWalAppliedSequence": LOCAL_WAL,
                "receiptCommitSha": REMOTE_COMMIT,
                "receiptErrorClass": None,
                "walErrorClass": None,
                "errorClass": None,
            })
            return {"verificationStatus": "verified"}

        with mock.patch.object(
                scanner, "_persist_remote_receipt_queue",
                side_effect=persist), mock.patch.object(
                scanner, "_remote_readback_ack",
                side_effect=verify) as readback, mock.patch.object(
                scanner, "_journal_compact", return_value=0), \
                mock.patch.object(
                    scanner, "_osint_persist",
                    side_effect=lambda: {"verified": True}) as checkpoint:
            drained = scanner._persist_with_remote_receipt_drain(
                "2026-08-12T01:07:00Z")
        flush = drained["remoteReceiptFlush"]
        assert flush["status"] == "verified"
        assert flush["targetWalSequence"] == LOCAL_WAL
        assert flush["verifiedWalSequence"] == LOCAL_WAL
        assert flush["queueBefore"] == 1
        assert flush["queueAfter"] == 0
        assert flush["coalescedReceiptCount"] == 1
        assert checkpoint.call_count == 1
        assert readback.call_count == 1

        with mock.patch.object(
                scanner, "_osint_persist",
                side_effect=lambda: {"verified": True}), \
                mock.patch.object(
                    scanner, "_remote_readback_ack") as second_readback:
            following = scanner._persist_with_remote_receipt_drain(
                "2026-08-12T01:37:00Z")
        assert following["remoteReceiptFlush"]["status"] == "noop"
        assert second_readback.call_count == 0
    finally:
        if scanner._REMOTE_RECEIPT_FLUSH_LOCK.locked():
            scanner._REMOTE_RECEIPT_FLUSH_LOCK.release()
        scanner._REMOTE_RECEIPT_QUEUE = saved_queue
        scanner._REMOTE_CYCLE.clear()
        scanner._REMOTE_CYCLE.update(saved_cycle)


def test_cross_proof_mismatch_matrix_is_fail_closed():
    _, _, quality = _truth()
    source = _readback(LOCAL_WAL, 2)
    ledger = _readback(REMOTE_WAL, 1)
    cases = []
    stale_source = _readback(REMOTE_WAL, 1)
    cases.append((stale_source, stale_source, quality))
    local_mismatch = copy.deepcopy(quality)
    local_mismatch["durability"]["checkpoint"][
        "includedWalSequence"] = LOCAL_WAL + 1
    cases.append((source, ledger, local_mismatch))
    remote_above_ledger = copy.deepcopy(quality)
    remote_above_ledger["remoteJournal"].update({
        "remoteWalAppliedSequence": REMOTE_WAL + 1,
        "verifiedWalSequence": REMOTE_WAL + 1,
    })
    cases.append((source, ledger, remote_above_ledger))
    no_ledger = None
    cases.append((source, no_ledger, quality))
    ledger_ahead = _readback(LOCAL_WAL + 1, 2)
    cases.append((source, ledger_ahead, quality))
    for candidate_source, candidate_ledger, candidate_quality in cases:
        with pytest.raises(PublishPolicyError):
            publication_decision(
                candidate_source, candidate_ledger,
                event_name="workflow_dispatch", utc_minute=18,
                runtime_data_quality=candidate_quality,
                natural_rearm=True)


def test_timer_secret_isolation_workflow_bound_and_deploy_scope():
    timer = Path("ops/systemd/argus-remote-journal-rearm.timer").read_text()
    service = Path("ops/systemd/argus-remote-journal-rearm.service").read_text()
    mission = Path("ops/systemd/argus-mission-tick.service").read_text()
    workflow = Path(".github/workflows/caos-watchtower.yml").read_text()
    schedule = re.search(r"^OnCalendar=.*\*:(.+):00 UTC$", timer,
                         re.MULTILINE)
    assert schedule is not None
    minutes = [int(value) for value in schedule.group(1).split(",")]
    gaps = [right - left for left, right in zip(minutes, minutes[1:])]
    gaps.append(60 + minutes[0] - minutes[-1])
    ec2_rearm_max_gap_seconds = max(gaps) * 60
    post_publication_drain_bound_seconds = 240
    total_modeled_bound_seconds = (
        ec2_rearm_max_gap_seconds + post_publication_drain_bound_seconds)
    slo_margin_seconds = 1800 - total_modeled_bound_seconds
    assert minutes == [13, 33, 53]
    assert ec2_rearm_max_gap_seconds == 1200
    assert total_modeled_bound_seconds == 1440
    assert slo_margin_seconds == 360
    assert total_modeled_bound_seconds < 1800
    assert "Persistent=true" in timer
    assert "AccuracySec=1us" in timer
    assert "RandomizedDelaySec=0" in timer
    assert "EnvironmentFile=/etc/argus-remote-journal-rearm.env" in service
    assert (
        "ExecStart=/usr/bin/python3 /opt/argus-rearm/"
        "argus_remote_journal_rearm.py" in service)
    assert "/opt/argus/scripts/" not in service
    assert "User=argus-rearm" in service
    assert "Group=argus-rearm" in service
    assert "argus-trigger.env" not in service
    assert "argus-trigger.env" not in mission
    assert "ARGUS_REMOTE_JOURNAL_REARM_PAT" not in mission
    assert "TimeoutStartSec=60" in service
    assert "'caos-watchtower-remote-journal-rearm'" in workflow
    assert "|| 'caos-watchtower'" in workflow
    assert "cancel-in-progress: false" in workflow
    assert "queue: max" not in workflow
    assert "remoteJournalRearm:" in workflow
    assert "inputs.remoteJournalRearm != true" in workflow
    assert "--natural-rearm)" in workflow
    rearm_job = workflow.split("  remote-journal-rearm:", 1)[1]
    assert "timeout-minutes: 8" in rearm_job
    assert "--budget-seconds 240" in rearm_job
    assert workflow.count("remote_receipt_drain.py") == 6
    assert workflow.count("--budget-seconds 240") == 2
    assert classify([
        ".github/workflows/caos-watchtower.yml",
        ".github/workflows/memory-attribution.yml",
        ".github/workflows/release-gate.yml",
        "docs/EC2_MISSION_SCHEDULER.md",
        "ops/systemd/argus-remote-journal-rearm.service",
        "ops/systemd/argus-remote-journal-rearm.timer",
        "ops/systemd/argus-watchtower-writer.service",
        "ops/systemd/argus-watchtower-writer.timer",
        "scripts/argus_remote_journal_rearm.py",
        "scripts/argus_watchtower_writer_dispatch.py",
        "scripts/install_argus_mission_timer.sh",
        "scripts/install_argus_remote_journal_rearm.sh",
        "scripts/install_argus_watchtower_writer.sh",
        "scripts/remote_journal_publish_policy.py",
        "test_argus_identity_installer.py",
        "test_argus_v12_3_2.py",
        "test_remote_journal_liveness.py",
        "test_remote_journal_rearm.py",
    ])["backendDeploy"] is False
    assert json.loads(Path("backend-version.json").read_text())[
        "version"] == "13.5.36"
