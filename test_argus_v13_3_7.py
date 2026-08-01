"""v13.3.7 immutable historical Soak terminal-result contracts."""
from __future__ import annotations

import copy
import json
from unittest import mock

import argus_persistent_storage
import argus_runtime
import argus_tick_durability
import scanner


OLD_SHA = "dbe3f94"
NEW_SHA = "950cc97a7fadfd7e824f216b41f25e197b73c4d3"
STARTED = "2026-07-29T04:37:20Z"
BOOT = "2026-07-31T08:26:00Z"


def _heartbeat(observed_at: str, *, source: str = "ec2_systemd"):
    return {
        "soakId": "soak-old", "buildSha": OLD_SHA,
        "runtimeVersion": "13.3.5",
        "expectedAt": observed_at, "observedAt": observed_at,
        "source": source, "healthStatus": "ok", "readyStatus": "ready",
        "restoreOutcome": "restored", "durableIntegrity": "ok",
        "journalStatus": "verified", "readBackVerified": True,
        "schedulerDelaySeconds": 0, "evidenceType": "scheduled_mission",
    }


def _interrupted_old():
    return {
        "soakId": "soak-old", "buildSha": OLD_SHA,
        "appVersion": "13.3.5", "startedAt": STARTED,
        "state": "interrupted", "completed72h": False,
        "heartbeats": [
            _heartbeat("2026-07-29T04:37:20Z"),
            _heartbeat("2026-07-29T05:07:20Z"),
            _heartbeat("2026-07-29T08:37:20Z"),
        ],
        "lastHeartbeatAt": "2026-07-29T08:37:20Z",
        "lastHeartbeatSource": "ec2_systemd",
        "interruptions": [{
            "type": "process_restart_same_build",
            "detectedAt": "2026-07-29T08:37:20Z",
            "lastPersistAt": "2026-07-29T05:07:20Z",
            "gapMinutes": 210.0, "verified": True,
        }],
        "interruptionCount": 1,
    }


def _active(previous=None):
    return {
        "soakId": None, "buildSha": None, "buildShaFull": None,
        "appVersion": None, "startedAt": None, "state": "not_started",
        "interruptions": [], "interruptionCount": 0, "heartbeats": [],
        "lastHeartbeatAt": None, "lastHeartbeatSource": None,
        "completed72h": False, "previousSoak": previous,
    }


def test_interrupted_terminal_state_and_failure_survive_new_build():
    decision = argus_runtime.soak_restore_decision(
        persisted=_interrupted_old(), current_build_sha=NEW_SHA,
        boot_iso=BOOT)
    previous = decision["previousSoakSummary"]
    assert decision["action"] == "new_soak"
    assert previous["state"] == "interrupted"
    assert previous["status"] == "interrupted"
    assert previous["terminalState"] == "interrupted"
    assert previous["failureClass"] == "scheduler_source_failure"
    assert previous["failureClassSource"] == \
        "derived_from_persisted_heartbeat_evidence"
    assert previous["supersededByBuildSha"] == NEW_SHA
    assert previous["lifecycleRelation"] == \
        "superseded_by_backend_deployment"
    assert previous["historicalEvidenceState"] == \
        "preserved_from_immutable_history"


def test_completed_terminal_state_is_not_rewritten_to_superseded():
    old = _interrupted_old()
    old.update({"state": "completed", "completed72h": True,
                "failureClass": None})
    summary = argus_runtime.historical_soak_summary(
        persisted=old, superseding_build_sha=NEW_SHA,
        superseded_at=BOOT)
    assert summary["state"] == "completed"
    assert summary["status"] == "completed"
    assert summary["completed72h"] is True
    assert summary["failureClass"] is None


def test_maximum_gap_and_restart_evidence_survive_projection():
    summary = argus_runtime.historical_soak_summary(
        persisted=_interrupted_old(), superseding_build_sha=NEW_SHA)
    assert summary["maximumEvidenceGapSeconds"] == 12600
    assert summary["maximumEvidenceGapStartAt"] == \
        "2026-07-29T05:07:20Z"
    assert summary["maximumEvidenceGapEndAt"] == \
        "2026-07-29T08:37:20Z"
    assert summary["interruptedAt"] == "2026-07-29T08:37:20Z"
    assert summary["continuityInterruptions"][0]["gapMinutes"] == 210.0
    assert summary["restartCount"] == 1


def test_projection_and_history_are_deep_copy_isolated():
    old = _interrupted_old()
    history = [copy.deepcopy(old)]
    summary = argus_runtime.normalize_previous_soak_summary(
        previous={"soakId": "soak-old", "startedAt": STARTED,
                  "supersededBy": NEW_SHA[:7]},
        history=history, current_build_sha=NEW_SHA, boot_iso=BOOT)
    old["interruptions"][0]["gapMinutes"] = 999
    summary["continuityInterruptions"][0]["gapMinutes"] = 888
    assert history[0]["interruptions"][0]["gapMinutes"] == 210.0


def test_checkpoint_round_trip_preserves_terminal_history(tmp_path):
    old = _interrupted_old()
    previous = argus_runtime.historical_soak_summary(
        persisted=old, superseding_build_sha=NEW_SHA,
        superseded_at=BOOT)
    path = tmp_path / "checkpoint.json"
    argus_persistent_storage.write_checkpoint(
        str(path), {"schemaVersion": "argus-durable-v3",
                    "soak": _active(previous), "soakHistory": [old]},
        temp_directory=str(tmp_path))
    restored = argus_persistent_storage.load_checkpoint(
        str(path), require_seal=True)
    assert restored["soakHistory"][0]["state"] == "interrupted"
    assert restored["soak"]["previousSoak"]["failureClass"] == \
        "scheduler_source_failure"


def test_wal_replay_cannot_mutate_archived_history(tmp_path):
    old = _interrupted_old()
    path = tmp_path / "mission.wal"
    record = argus_tick_durability.append_wal(
        str(path), sequence=1, kind="journal_transition",
        payload={"aggregatePatch": {"type": "soak", "record": old}},
        job_id="tick-test", mission_window_id="mw-test",
        build_sha=OLD_SHA, occurred_at=BOOT)
    valid = argus_tick_durability.read_valid_wal(str(path))
    assert valid["corruptCount"] == 0
    assert valid["records"][0]["payload"]["aggregatePatch"]["record"][
        "state"] == "interrupted"

    saved_soak = copy.deepcopy(scanner._SOAK)
    saved_history = copy.deepcopy(scanner._SOAK_HISTORY)
    try:
        scanner._SOAK.clear()
        scanner._SOAK.update(_active())
        scanner._SOAK["buildSha"] = NEW_SHA[:7]
        scanner._SOAK_HISTORY[:] = [copy.deepcopy(old)]
        scanner._apply_mission_wal_record(record)
        assert scanner._SOAK["buildSha"] == NEW_SHA[:7]
        assert scanner._SOAK_HISTORY == [old]
    finally:
        scanner._SOAK.clear()
        scanner._SOAK.update(saved_soak)
        scanner._SOAK_HISTORY[:] = saved_history


def test_remote_snapshot_and_public_projection_keep_both_concepts():
    old = _interrupted_old()
    previous = argus_runtime.historical_soak_summary(
        persisted=old, superseding_build_sha=NEW_SHA,
        superseded_at=BOOT)
    saved_soak = copy.deepcopy(scanner._SOAK)
    saved_history = copy.deepcopy(scanner._SOAK_HISTORY)
    try:
        scanner._SOAK.clear()
        scanner._SOAK.update(_active(previous))
        scanner._SOAK_HISTORY[:] = [copy.deepcopy(old)]
        with mock.patch.object(scanner, "_osint_restore_once", return_value=None):
            with scanner.app.test_client() as client:
                remote = client.get("/api/argus/osint/memory-snapshot")
        assert remote.status_code == 200
        payload = remote.get_json()
        assert payload["soakHistory"][0]["state"] == "interrupted"
        projected = payload["soak"]["previousSoak"]
        assert projected["state"] == "interrupted"
        assert projected["supersededByBuildSha"] == NEW_SHA

        public = argus_runtime.build_soak(
            soak=scanner._SOAK, now_iso=BOOT, startup_state="ready",
            process_booted_at=BOOT, current_build_sha=NEW_SHA[:7])
        assert public["previousSoak"]["state"] == "interrupted"
        assert public["previousSoak"]["failureClass"] == \
            "scheduler_source_failure"
    finally:
        scanner._SOAK.clear()
        scanner._SOAK.update(saved_soak)
        scanner._SOAK_HISTORY[:] = saved_history


def test_pre_natural_tick_has_no_active_soak_then_natural_tick_is_unique(
        monkeypatch):
    old = _interrupted_old()
    previous = argus_runtime.normalize_previous_soak_summary(
        previous={"soakId": "soak-old", "startedAt": STARTED,
                  "status": "superseded", "failureClass": None,
                  "supersededBy": NEW_SHA[:7]},
        history=[old], current_build_sha=NEW_SHA, boot_iso=BOOT)
    active = _active(previous)
    assert active["soakId"] is None
    assert active["startedAt"] is None
    assert active["state"] == "not_started"

    saved_soak = copy.deepcopy(scanner._SOAK)
    saved_history = copy.deepcopy(scanner._SOAK_HISTORY)
    saved_control = copy.deepcopy(scanner._SOAK_CONTROL)
    monkeypatch.setenv("RENDER_GIT_COMMIT", NEW_SHA)
    try:
        scanner._SOAK.clear()
        scanner._SOAK.update(active)
        scanner._SOAK_HISTORY[:] = [copy.deepcopy(old)]
        scanner._SOAK_CONTROL.update({"armed": False})
        decision = argus_runtime.soak_start_decision(
            now_iso="2026-07-31T08:38:00Z",
            scheduled_for="2026-07-31T08:37:00Z",
            trigger_source="ec2_systemd", mission_window_id="mw-natural",
            build_sha=NEW_SHA[:7], app_version="13.3.7",
            process_booted_at=BOOT, restore_completed_at=BOOT,
            startup_state="ready", integrity_ok=True,
            public_leak_safe=True, scheduler_ready=True)
        scanner._activate_formal_soak(
            decision, {"missionWindowId": "mw-natural",
                       "scheduledFor": "2026-07-31T08:37:00Z"},
            rollover_armed=False)
        assert scanner._SOAK["soakId"].startswith("soak-950cc97-")
        assert scanner._SOAK["soakId"] != "soak-old"
        assert scanner._SOAK_HISTORY == [old]
        assert scanner._SOAK["previousSoak"]["state"] == "interrupted"
    finally:
        scanner._SOAK.clear()
        scanner._SOAK.update(saved_soak)
        scanner._SOAK_HISTORY[:] = saved_history
        scanner._SOAK_CONTROL.clear()
        scanner._SOAK_CONTROL.update(saved_control)


def test_normalization_is_idempotent_and_does_not_duplicate_history():
    old = _interrupted_old()
    history = [copy.deepcopy(old)]
    first = argus_runtime.normalize_previous_soak_summary(
        previous={"soakId": "soak-old", "startedAt": STARTED,
                  "supersededBy": NEW_SHA[:7]},
        history=history, current_build_sha=NEW_SHA, boot_iso=BOOT)
    second = argus_runtime.normalize_previous_soak_summary(
        previous=first, history=history,
        current_build_sha=NEW_SHA, boot_iso=BOOT)
    assert second == first
    assert history == [old]


def test_missing_authoritative_history_fails_closed_without_invention():
    summary = argus_runtime.normalize_previous_soak_summary(
        previous={"soakId": "soak-lost", "buildSha": "abc1234",
                  "startedAt": STARTED, "status": "superseded",
                  "failureClass": None, "supersededBy": NEW_SHA[:7]},
        history=[], current_build_sha=NEW_SHA, boot_iso=BOOT)
    assert summary["state"] == "historical_evidence_incomplete"
    assert summary["failureClass"] is None
    assert summary["failureClassSource"] == "unavailable"
    assert "authoritativeHistoryRecord" in summary["missingHistoricalFields"]


def test_short_and_full_same_sha_restore_does_not_create_a_new_soak():
    decision = argus_runtime.soak_restore_decision(
        persisted=_interrupted_old(), current_build_sha=OLD_SHA + "a" * 33,
        boot_iso=BOOT, last_persist_at="2026-07-31T08:20:00Z")
    assert decision["action"] == "inherit_with_interruption"
