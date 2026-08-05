"""v13.4.2 cross-SHA running-Soak terminalization regression matrix."""

import copy
import json

import argus_runtime


OLD_SHA = "a" * 40
NEW_SHA = "b" * 40
OLD_BOOT = "2026-08-04T14:07:00+09:00"
NEW_BOOT = "2026-08-05T11:37:05+09:00"


def _running_soak(**overrides):
    soak = {
        "soakId": "soak-old-immutable",
        "buildSha": OLD_SHA[:7],
        "buildShaFull": OLD_SHA,
        "startedAt": "2026-08-04T05:07:00Z",
        "state": "running",
        "status": "running",
        "processBootedAt": OLD_BOOT,
        "processBootId": "boot-old",
        "heartbeats": [
            {"observedAt": "2026-08-04T06:07:02Z",
             "healthStatus": "ok", "buildSha": OLD_SHA[:7]},
            {"observedAt": "2026-08-04T07:07:03Z",
             "healthStatus": "ok", "buildSha": OLD_SHA[:7]},
        ],
        "interruptions": [{"type": "scheduler_delay",
                            "detectedAt": "2026-08-04T06:20:00Z"}],
        "completed72h": False,
    }
    soak.update(overrides)
    return soak


def test_different_sha_running_soak_is_terminalized_without_replacement():
    source = _running_soak()
    before = copy.deepcopy(source)
    decision = argus_runtime.soak_restore_decision(
        persisted=source, current_build_sha=NEW_SHA, boot_iso=NEW_BOOT,
        current_boot_id="boot-new")

    assert decision["action"] == "terminalize_interrupted"
    terminal = decision["terminalSoak"]
    assert terminal["terminalState"] == "interrupted"
    assert terminal["interruptionClass"] == "backend_build_changed"
    assert terminal["terminalizationProvenance"] == \
        "derived_from_persisted_build_and_boot_evidence"
    assert terminal["interruptionClassSource"] == \
        "derived_from_persisted_build_and_boot_evidence"
    assert terminal["previousBackendBuildSha"] == OLD_SHA
    assert terminal["heartbeats"] == before["heartbeats"]
    assert terminal["interruptions"] == before["interruptions"]
    assert "newSoak" not in decision
    assert source == before


def test_cross_sha_summary_preserves_history_and_exact_relationship():
    source = _running_soak()
    summary = argus_runtime.historical_soak_summary(
        persisted=source, superseding_build_sha=NEW_SHA,
        superseded_at=NEW_BOOT)

    assert summary["state"] == summary["status"] == \
        summary["terminalState"] == "interrupted"
    assert summary["failureClass"] == "backend_build_changed"
    assert summary["interruptionClass"] == "backend_build_changed"
    assert summary["failureReason"] == \
        "backend_build_changed_during_running_soak"
    assert summary["interruptionClassSource"] == \
        "derived_from_persisted_build_and_boot_evidence"
    assert summary["heartbeatCount"] == 2
    assert summary["continuityInterruptions"] == source["interruptions"]
    assert summary["previousBackendBuildSha"] == OLD_SHA
    assert summary["supersededByBuildSha"] == NEW_SHA
    assert summary["previousBoot"] == OLD_BOOT
    assert summary["successorBoot"] == NEW_BOOT
    assert summary["lifecycleRelation"] == \
        "superseded_by_backend_deployment"
    assert summary["completed72h"] is False
    assert summary["historicalEvidenceState"] == \
        "preserved_from_immutable_history"


def test_different_sha_same_boot_is_still_backend_build_interruption():
    source = _running_soak(processBootedAt=NEW_BOOT,
                           processBootId="boot-same")
    decision = argus_runtime.soak_restore_decision(
        persisted=source, current_build_sha=NEW_SHA,
        boot_iso=NEW_BOOT, current_boot_id="boot-same")
    assert decision["action"] == "terminalize_interrupted"
    assert decision["interruptionClass"] == "backend_build_changed"


def test_normalization_is_idempotent_and_does_not_mutate_immutable_history():
    history = [_running_soak()]
    frozen = copy.deepcopy(history)
    previous = {
        "soakId": "soak-old-immutable",
        "startedAt": "2026-08-04T05:07:00Z",
        "supersededByBuildSha": NEW_SHA,
        "supersededAt": NEW_BOOT,
    }
    first = argus_runtime.normalize_previous_soak_summary(
        previous=previous, history=history,
        current_build_sha=NEW_SHA, boot_iso=NEW_BOOT)
    second = argus_runtime.normalize_previous_soak_summary(
        previous=first, history=history,
        current_build_sha=NEW_SHA, boot_iso=NEW_BOOT)

    assert first == second
    assert first["terminalState"] == "interrupted"
    assert history == frozen


def test_repeated_process_restore_preserves_the_same_terminal_truth():
    first = argus_runtime.soak_restore_decision(
        persisted=_running_soak(), current_build_sha=NEW_SHA,
        boot_iso=NEW_BOOT, current_boot_id="boot-new")
    second = argus_runtime.soak_restore_decision(
        persisted=first["terminalSoak"], current_build_sha=NEW_SHA,
        boot_iso="2026-08-05T12:00:00+09:00", current_boot_id="boot-newer")
    assert second["action"] == "new_soak"
    assert second["previousSoakSummary"]["terminalState"] == "interrupted"
    assert second["previousSoakSummary"]["failureClass"] == \
        "backend_build_changed"
    assert second["previousSoakSummary"]["soakId"] == \
        first["terminalSoak"]["soakId"]
    assert second["previousSoakSummary"]["heartbeatCount"] == 2


def test_checkpoint_json_round_trip_keeps_cross_sha_terminal_truth():
    history = json.loads(json.dumps([_running_soak()]))
    previous = {
        "soakId": "soak-old-immutable",
        "startedAt": "2026-08-04T05:07:00Z",
        "supersededByBuildSha": NEW_SHA,
        "supersededAt": NEW_BOOT,
    }
    restored = json.loads(json.dumps({"history": history,
                                      "previous": previous}))
    summary = argus_runtime.normalize_previous_soak_summary(
        previous=restored["previous"], history=restored["history"],
        current_build_sha=NEW_SHA, boot_iso=NEW_BOOT)
    assert summary["terminalState"] == "interrupted"
    assert summary["failureClass"] == "backend_build_changed"
    assert summary["heartbeatCount"] == 2


def test_same_sha_different_boot_uses_existing_unplanned_classification():
    decision = argus_runtime.soak_restore_decision(
        persisted=_running_soak(), current_build_sha=OLD_SHA,
        boot_iso=NEW_BOOT, current_boot_id="boot-new")
    assert decision["action"] == "terminalize_interrupted"
    assert decision["interruptionClass"] == "boot_discontinuity"


def test_valid_durable_owner_marker_is_the_only_planned_restart_path():
    marker = {
        "durable": True,
        "interruptionClass": "planned_owner_restart",
        "soakId": "soak-old-immutable",
        "sourceBootId": "boot-old",
    }
    planned = argus_runtime.soak_restore_decision(
        persisted=_running_soak(), current_build_sha=OLD_SHA,
        boot_iso=NEW_BOOT, current_boot_id="boot-new",
        planned_restart_marker=marker)
    unmarked = argus_runtime.soak_restore_decision(
        persisted=_running_soak(), current_build_sha=OLD_SHA,
        boot_iso=NEW_BOOT, current_boot_id="boot-new")
    assert planned["interruptionClass"] == "planned_owner_restart"
    assert unmarked["interruptionClass"] == "boot_discontinuity"


def test_missing_build_with_persisted_boot_evidence_is_interrupted():
    source = _running_soak(buildSha=None, buildShaFull=None)
    decision = argus_runtime.soak_restore_decision(
        persisted=source, current_build_sha=NEW_SHA,
        boot_iso=NEW_BOOT, current_boot_id="boot-new")
    assert decision["action"] == "terminalize_interrupted"
    assert decision["interruptionClass"] == "boot_discontinuity"


def test_missing_boot_with_persisted_build_evidence_is_interrupted():
    source = _running_soak(processBootedAt=None, processBootId=None)
    decision = argus_runtime.soak_restore_decision(
        persisted=source, current_build_sha=NEW_SHA,
        boot_iso=NEW_BOOT, current_boot_id="boot-new")
    assert decision["action"] == "terminalize_interrupted"
    assert decision["interruptionClass"] == "backend_build_changed"


def test_insufficient_build_and_boot_evidence_stays_explicitly_incomplete():
    source = _running_soak(buildSha=None, buildShaFull=None,
                           processBootedAt=None, processBootId=None)
    decision = argus_runtime.soak_restore_decision(
        persisted=source, current_build_sha=NEW_SHA,
        boot_iso=NEW_BOOT, current_boot_id=None)
    assert decision["action"] == "new_soak"
    assert decision["previousSoakSummary"]["terminalState"] == \
        "historical_evidence_incomplete"
    assert decision["previousSoakSummary"]["failureClass"] is None


def test_already_interrupted_history_remains_unchanged_terminal_truth():
    source = _running_soak(
        state="interrupted", terminalState="interrupted",
        interruptionClass="mission_timeout", failureClass="mission_timeout",
        interruptedAt="2026-08-04T08:00:00Z")
    summary = argus_runtime.historical_soak_summary(
        persisted=source, superseding_build_sha=NEW_SHA,
        superseded_at=NEW_BOOT)
    assert summary["terminalState"] == "interrupted"
    assert summary["failureClass"] == "mission_timeout"
    assert summary["interruptionClass"] == "mission_timeout"
    assert summary["interruptedAt"] == "2026-08-04T08:00:00Z"


def test_pure_terminalization_does_not_arm_formal_soak_or_change_v2_mode():
    controls = {"formalSoakArmed": False,
                "checkpointMode": "dual_write_validation",
                "v2Authority": False}
    frozen = copy.deepcopy(controls)
    argus_runtime.soak_restore_decision(
        persisted=_running_soak(), current_build_sha=NEW_SHA,
        boot_iso=NEW_BOOT, current_boot_id="boot-new")
    assert controls == frozen
