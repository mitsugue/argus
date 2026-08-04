"""v13.3.6 permanent scheduler identity / formal Soak closure contracts."""
from __future__ import annotations

import copy
import json
import socket
import types
from unittest import mock

import argus_runtime
import argus_remote_journal
import argus_tick_durability
import argus_checkpoint_v2_stage1


_moomoo = types.ModuleType("moomoo")
_moomoo.OpenQuoteContext = lambda *args, **kwargs: None
_moomoo.OpenSecTradeContext = lambda *args, **kwargs: None
_moomoo.RET_OK = 0
import sys
sys.modules.setdefault("moomoo", _moomoo)
import scanner
from scripts import argus_mission_tick


FULL_SHA = "a" * 40
BOOT = "2026-07-31T00:00:00Z"
SCHEDULED = "2026-07-31T00:07:00Z"
OBSERVED = "2026-07-31T00:08:00Z"


def _decision(**overrides):
    value = dict(
        now_iso=OBSERVED,
        scheduled_for=SCHEDULED,
        trigger_source="ec2_systemd",
        mission_window_id=f"mw-{SCHEDULED}",
        build_sha=FULL_SHA,
        app_version="13.3.6",
        process_booted_at=BOOT,
        restore_completed_at="2026-07-31T00:01:00Z",
        startup_state="ready",
        integrity_ok=True,
        public_leak_safe=True,
        scheduler_ready=True,
    )
    value.update(overrides)
    return argus_runtime.soak_start_decision(**value)


def test_only_natural_ec2_window_can_start_and_clock_is_scheduled_at():
    allowed = _decision()
    assert allowed["allowed"] is True
    assert allowed["startedAt"] == SCHEDULED
    assert allowed["startedBy"] == "ec2_systemd"
    assert allowed["firstMissionWindowId"] == f"mw-{SCHEDULED}"
    assert _decision(trigger_source="github_schedule")["allowed"] is False
    assert _decision(trigger_source="manual")["allowed"] is False
    assert _decision(
        scheduled_for="2026-07-30T23:59:00Z")["allowed"] is False


def test_formal_closure_keeps_four_proofs_separate():
    state = {
        "state": "completed", "elapsedHours": 72.1, "failureClass": None,
        "schedulerContinuityVerified": True}
    remote = {
        "remoteDurabilityState": "verification_pending",
        "readBackVerified": False, "walReadBackVerified": False,
        "receiptCommitSha": FULL_SHA, "receiptErrorClass": "timeout"}
    pending = argus_runtime.formal_soak_closure(
        soak_state=state, mission_result="caught_up", remote_cycle=remote)
    assert pending["duration"]["passed"] is True
    assert pending["schedulerContinuity"]["passed"] is True
    assert pending["missionExecution"]["passed"] is True
    assert pending["remoteDurability"]["passed"] is False
    assert pending["completed72h"] is False
    remote.update({
        "remoteDurabilityState": "verified",
        "readBackVerified": True, "walReadBackVerified": True,
        "receiptErrorClass": None})
    closed = argus_runtime.formal_soak_closure(
        soak_state=state, mission_result="caught_up", remote_cycle=remote)
    assert closed["completed72h"] is True


def test_remote_readback_url_is_immutable_commit_not_moving_ledger_branch():
    url = scanner._remote_commit_readback_url(FULL_SHA)
    assert url == (
        "https://raw.githubusercontent.com/mitsugue/argus/"
        f"{FULL_SHA}/ledger/osint/readback.json")
    assert "/ledger/ledger/" not in url
    assert scanner._remote_commit_readback_url("main") is None


class _HttpResponse:
    def __init__(self, status_code):
        self.status_code = status_code

    def json(self):
        raise ValueError("not json")


def test_remote_readback_retries_are_bounded_and_classified():
    saved = copy.deepcopy(scanner._REMOTE_CYCLE)
    try:
        scanner._REMOTE_CYCLE.update({
            "remoteCommitSha": FULL_SHA,
            "committedAt": "2026-07-31T00:00:00Z",
            "readBackVerified": False,
        })
        with mock.patch.object(
                scanner.requests, "get",
                side_effect=[_HttpResponse(502), _HttpResponse(502)]) as get:
            assert scanner._remote_readback_ack(now_iso=OBSERVED) is None
        assert get.call_count == 2
        assert all(FULL_SHA in call.args[0] for call in get.call_args_list)
        assert scanner._REMOTE_CYCLE["receiptAttempts"] == 2
        assert scanner._REMOTE_CYCLE["receiptErrorClass"] == "http_502"
        assert scanner._REMOTE_CYCLE[
            "remoteDurabilityState"] == "transient_failure"
    finally:
        scanner._REMOTE_CYCLE.clear()
        scanner._REMOTE_CYCLE.update(saved)


def test_exact_commit_receipt_reaches_verified_state():
    saved = copy.deepcopy(scanner._REMOTE_CYCLE)
    saved_ack = copy.deepcopy(scanner._REMOTE_ACK)
    section = argus_remote_journal.snapshot_journal_section(
        events=[], meta={}, now_iso="2026-07-31T00:00:00Z")
    remote = {
        "schemaVersion": "argus-durable-v3",
        "generatedAt": "2026-07-31T00:00:00Z",
        "missionTickDurability": {
            "schemaVersion": "argus-mission-batch-v1",
            "walAppliedSequence": 4,
            "remoteWalAppliedSequence": 4,
        },
        **section,
    }
    compact = argus_remote_journal.compact_readback_snapshot(remote)
    manifest_hash = compact["integrityManifest"]["manifestHash"]
    try:
        scanner._REMOTE_CYCLE.update({
            "remoteCommitSha": FULL_SHA,
            "committedAt": "2026-07-31T00:00:00Z",
            "expectedHash": manifest_hash,
            "verifiedWalSequence": 0,
        })
        with mock.patch.object(
                scanner, "_persist_remote_wal_receipt",
                return_value={"verified": True}):
            receipt = scanner._remote_readback_ack(
                now_iso=OBSERVED, blob=compact)
        assert receipt["verificationStatus"] == "verified"
        assert scanner._REMOTE_CYCLE["remoteDurabilityState"] == "verified"
        assert scanner._REMOTE_CYCLE["receiptCommitSha"] == FULL_SHA
        assert scanner._REMOTE_CYCLE["receiptVerifiedAt"] == OBSERVED
        assert scanner._REMOTE_CYCLE["receiptErrorClass"] is None
    finally:
        scanner._REMOTE_CYCLE.clear()
        scanner._REMOTE_CYCLE.update(saved)
        scanner._REMOTE_ACK.clear()
        scanner._REMOTE_ACK.update(saved_ack)


def test_remote_receipt_v2_additive_telemetry_is_integrity_bound():
    record = argus_tick_durability.remote_receipt_record(
        saved_at=OBSERVED, remote_commit_sha=FULL_SHA,
        committed_at=SCHEDULED, expected_hash="b" * 16,
        actual_hash="b" * 16, read_back_at=OBSERVED,
        read_back_verified=True, wal_read_back_verified=True,
        remote_wal_applied_sequence=4, verified_wal_sequence=4,
        compact_receipt_hash="proof", error_class=None,
        wal_error_class=None, remote_durability_state="verified",
        receipt_commit_sha=FULL_SHA, receipt_created_at=SCHEDULED,
        receipt_verified_at=OBSERVED, receipt_age_seconds=60,
        receipt_attempts=1, receipt_error_class=None)
    assert argus_tick_durability.verify_remote_receipt(record)
    tampered = dict(record)
    tampered["receiptAttempts"] = 99
    assert not argus_tick_durability.verify_remote_receipt(tampered)


def test_transport_error_classes_are_stable_and_public_safe():
    assert argus_mission_tick._transport_error_class(
        socket.timeout()) == "timeout"
    assert argus_mission_tick._transport_error_class(
        json.JSONDecodeError("x", "x", 0)) == "invalid_json"


def test_owner_arm_does_not_start_soak(monkeypatch):
    saved_soak = copy.deepcopy(scanner._SOAK)
    saved_control = copy.deepcopy(scanner._SOAK_CONTROL)
    saved_history = copy.deepcopy(scanner._SOAK_HISTORY)
    monkeypatch.setenv("RENDER_GIT_COMMIT", FULL_SHA)
    monkeypatch.setattr(scanner, "_require_admin", lambda: (True, None, 200))
    monkeypatch.setattr(
        scanner, "_osint_persist", lambda: {"verified": True})
    try:
        scanner._SOAK.update({
            "soakId": "soak-old", "buildSha": FULL_SHA[:7],
            "buildShaFull": None, "startedAt": "2026-07-27T00:07:25Z",
            "state": "interrupted", "heartbeats": [{"immutable": True}],
        })
        with scanner.app.test_client() as client:
            response = client.post(
                "/api/argus/admin/soak/arm",
                headers={"X-ARGUS-ADMIN-TOKEN": "unused"},
                json={"confirm": True, "buildSha": FULL_SHA})
        assert response.status_code == 200
        assert response.get_json()["startsNow"] is False
        assert scanner._SOAK["soakId"] == "soak-old"
        assert scanner._SOAK["startedAt"] == "2026-07-27T00:07:25Z"
        assert scanner._SOAK_CONTROL["armed"] is True

        old_snapshot = copy.deepcopy(scanner._SOAK)
        window = {"missionWindowId": f"mw-{SCHEDULED}",
                  "scheduledFor": SCHEDULED}
        scanner._activate_formal_soak(
            _decision(), window, rollover_armed=True)
        assert scanner._SOAK["soakId"] != "soak-old"
        assert scanner._SOAK["startedAt"] == SCHEDULED
        assert scanner._SOAK["startedBy"] == "ec2_systemd"
        assert scanner._SOAK_CONTROL["armed"] is False
        assert scanner._SOAK_HISTORY == [old_snapshot]
    finally:
        scanner._SOAK.clear()
        scanner._SOAK.update(saved_soak)
        scanner._SOAK_CONTROL.clear()
        scanner._SOAK_CONTROL.update(saved_control)
        scanner._SOAK_HISTORY[:] = saved_history


def test_checkpoint_v2_stage1_owner_arm_does_not_create_soak_or_heartbeat(
        monkeypatch):
    saved_soak = copy.deepcopy(scanner._SOAK)
    saved_control = copy.deepcopy(scanner._SOAK_CONTROL)
    saved_stage1 = copy.deepcopy(scanner._CHECKPOINT_V2_STAGE1_CONTROL)
    saved_status = copy.deepcopy(scanner._CHECKPOINT_V2_STATUS)
    monkeypatch.setenv("RENDER_GIT_COMMIT", FULL_SHA)
    monkeypatch.setattr(scanner, "_CHECKPOINT_V2_STAGE1_ENABLED", True)
    monkeypatch.setattr(scanner, "_require_admin", lambda: (True, None, 200))
    state = argus_checkpoint_v2_stage1.empty_state(FULL_SHA)
    for index in range(3):
        state = argus_checkpoint_v2_stage1.record_generation(
            state, {"verified": True, "generationId": f"gen-{index}"},
            trigger_source="ec2_systemd",
            mission_window_id=f"mw-{index}")
    state = argus_checkpoint_v2_stage1.record_acceptance(
        state, resource_accepted=True, disk_accepted=True,
        isolated_restore_verified=True, restore_authority_approved=True)

    def persist():
        scanner._CHECKPOINT_V2_STATUS["lastWriteVerified"] = True
        return {"verified": True}

    monkeypatch.setattr(scanner, "_osint_persist", persist)
    try:
        scanner._CHECKPOINT_V2_STAGE1_CONTROL.clear()
        scanner._CHECKPOINT_V2_STAGE1_CONTROL.update(state)
        scanner._SOAK.clear()
        scanner._SOAK.update({"soakId": None, "startedAt": None,
                              "heartbeats": [], "state": "not_started"})
        with scanner.app.test_client() as client:
            response = client.post(
                "/api/argus/admin/soak/arm",
                headers={"X-ARGUS-ADMIN-TOKEN": "unused"},
                json={"confirm": True, "buildSha": FULL_SHA})
        payload = response.get_json()
        assert response.status_code == 200
        assert payload["startsNow"] is False
        assert payload["soakCreated"] is False
        assert payload["heartbeatCreated"] is False
        assert scanner._SOAK["soakId"] is None
        assert scanner._SOAK["startedAt"] is None
        assert scanner._SOAK["heartbeats"] == []
        assert scanner._CHECKPOINT_V2_STAGE1_CONTROL["formalSoakArmed"] is True
    finally:
        scanner._SOAK.clear()
        scanner._SOAK.update(saved_soak)
        scanner._SOAK_CONTROL.clear()
        scanner._SOAK_CONTROL.update(saved_control)
        scanner._CHECKPOINT_V2_STAGE1_CONTROL.clear()
        scanner._CHECKPOINT_V2_STAGE1_CONTROL.update(saved_stage1)
        scanner._CHECKPOINT_V2_STATUS.clear()
        scanner._CHECKPOINT_V2_STATUS.update(saved_status)


def test_public_health_and_ready_expose_exact_render_sha(monkeypatch):
    monkeypatch.setenv("RENDER_GIT_COMMIT", FULL_SHA)
    saved_state = scanner._STARTUP["state"]
    saved_outcome = scanner._STARTUP.get("restoreOutcome")
    try:
        scanner._STARTUP["state"] = "ready"
        scanner._STARTUP["restoreOutcome"] = "restored"
        with scanner.app.test_client() as client:
            health = client.get("/healthz")
            ready = client.get("/readyz")
        assert health.status_code == 200
        assert health.get_json()["buildSha"] == FULL_SHA
        assert ready.status_code == 200
        assert ready.get_json()["buildSha"] == FULL_SHA
    finally:
        scanner._STARTUP["state"] = saved_state
        scanner._STARTUP["restoreOutcome"] = saved_outcome
