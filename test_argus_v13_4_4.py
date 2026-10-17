"""v13.4.4 Formal Soak start-gate safety truth table."""
from __future__ import annotations

import copy
import json
import sys
import types


_moomoo = types.ModuleType("moomoo")
_moomoo.OpenQuoteContext = lambda *args, **kwargs: None
_moomoo.OpenSecTradeContext = lambda *args, **kwargs: None
_moomoo.RET_OK = 0
sys.modules.setdefault("moomoo", _moomoo)

import argus_checkpoint_v2_stage1 as stage1
import argus_runtime
import scanner


SHA = "c" * 40
OLD_SHA = "d" * 40


def _telemetry(index: int) -> dict:
    return {
        "success": True,
        "processRssAfterBytes": 500_000_000 + index,
        "processPeakRssBytes": 800_000_000,
        "cgroupMemoryPeakBytes": 900_000_000,
        "diskFreeAfterBytes": 2 * 1024 ** 3,
        "pendingGenerationCount": 0,
        "legacyTempBaselineCount": 1,
        "legacyTempAfterCount": 1,
        "newLegacyTempCount": 0,
    }


def _accepted(build_sha: str = SHA) -> dict:
    value = stage1.empty_state(build_sha)
    for index in range(3):
        value = stage1.record_generation(
            value,
            {"verified": True, "generationId": f"gen-{index}",
             "createdAt": f"2026-08-06T0{index}:07:00Z",
             "resourceTelemetry": _telemetry(index)},
            trigger_source="ec2_systemd",
            mission_window_id=f"mw-2026-08-06T0{index}:07:00Z")
    return stage1.record_acceptance(
        value, resource_accepted=True, disk_accepted=True,
        isolated_restore_verified=True, restore_authority_approved=True)


def _armed(build_sha: str = SHA) -> dict:
    return stage1.arm(
        _accepted(build_sha), build_sha=build_sha,
        armed_at="2026-08-06T03:00:00Z")


def _decision(value: dict, *, enabled: bool = True,
              source: str = "ec2_systemd", qualified: bool = True,
              window: str = "mw-2026-08-06T03:07:00Z",
              current_sha: str = SHA, expected_sha: str = SHA,
              active: bool = False) -> dict:
    return stage1.formal_soak_start_eligibility(
        value, checkpoint_v2_enabled=enabled, trigger_source=source,
        qualified_natural_tick=qualified, mission_window_id=window,
        current_build_sha=current_sha, expected_build_sha=expected_sha,
        active_soak_exists=active,
        active_soak_id="soak-active" if active else None)


def test_disabled_unarmed_natural_is_blocked():
    result = _decision(stage1.empty_state(SHA), enabled=False)
    assert result["eligible"] is False
    assert "checkpoint_v2_disabled" in result["blockers"]
    assert "formal_soak_not_armed" in result["blockers"]


def test_disabled_stale_acceptance_is_blocked():
    result = _decision(_accepted(), enabled=False)
    assert result["eligible"] is False
    assert result["blockers"][0] == "checkpoint_v2_disabled"


def test_disabled_even_with_arm_is_blocked():
    result = _decision(_armed(), enabled=False)
    assert result["eligible"] is False
    assert result["blockers"] == ["checkpoint_v2_disabled"]


def test_resource_acceptance_false_with_arm_shape_is_blocked():
    value = _armed()
    value["resourceAcceptance"] = False
    result = _decision(value)
    assert "resource_acceptance_failed" in result["blockers"]


def test_authority_blocked_with_arm_shape_is_blocked():
    value = _armed()
    value["authorityPromotionBlocked"] = True
    result = _decision(value)
    assert "authority_promotion_blocked" in result["blockers"]


def test_technical_gates_without_arm_are_blocked():
    result = _decision(_accepted())
    assert result["eligible"] is False
    assert "formal_soak_not_armed" in result["blockers"]


def test_valid_arm_and_qualified_natural_window_start_exactly_once(
        monkeypatch):
    saved_soak = copy.deepcopy(scanner._SOAK)
    saved_history = copy.deepcopy(scanner._SOAK_HISTORY)
    saved_control = copy.deepcopy(scanner._SOAK_CONTROL)
    monkeypatch.setenv("RENDER_GIT_COMMIT", SHA)
    value = _armed()
    try:
        scanner._SOAK.clear()
        scanner._SOAK.update({
            **saved_soak, "soakId": None, "startedAt": None,
            "state": "not_started"})
        assert _decision(value)["eligible"] is True
        window = {"missionWindowId": "mw-2026-08-06T03:07:00Z"}
        scanner._activate_formal_soak({
            "startedAt": "2026-08-06T03:07:00Z",
            "startedBy": "ec2_systemd",
            "firstMissionWindowId": window["missionWindowId"],
            "startReason": "qualified_natural_window",
            "startTimeSource": "scheduled_window",
        }, window, rollover_armed=False)
        consumed = stage1.consume_arm(
            value, consumed_at="2026-08-06T03:07:01Z",
            mission_window_id=window["missionWindowId"],
            arm_id=value["armId"])
        first_id = scanner._SOAK["soakId"]
        replay = _decision(
            consumed, window=window["missionWindowId"], active=True)
        assert replay["eligible"] is False
        assert "active_soak_exists" in replay["blockers"]
        assert "mission_window_replayed" in replay["blockers"]
        assert scanner._SOAK["soakId"] == first_id
    finally:
        scanner._SOAK.clear(); scanner._SOAK.update(saved_soak)
        scanner._SOAK_HISTORY[:] = saved_history
        scanner._SOAK_CONTROL.clear(); scanner._SOAK_CONTROL.update(
            saved_control)


def test_manual_trigger_is_blocked():
    assert "trigger_not_qualified_natural" in _decision(
        _armed(), source="manual", qualified=False)["blockers"]


def test_diagnostic_trigger_is_blocked():
    assert "trigger_not_qualified_natural" in _decision(
        _armed(), source="diagnostic", qualified=False)["blockers"]


def test_workflow_rerun_is_blocked():
    assert "trigger_not_qualified_natural" in _decision(
        _armed(), source="github_schedule", qualified=False)["blockers"]


def test_consumed_arm_and_same_window_replay_are_single_use():
    value = _armed()
    window = "mw-2026-08-06T03:07:00Z"
    consumed = stage1.consume_arm(
        value, consumed_at="2026-08-06T03:07:01Z",
        mission_window_id=window, arm_id=value["armId"])
    result = _decision(consumed, window=window)
    assert result["eligible"] is False
    assert "formal_soak_not_armed" in result["blockers"]
    assert "mission_window_replayed" in result["blockers"]


def test_stale_arm_for_previous_sha_fails_closed():
    result = _decision(_armed(OLD_SHA), current_sha=SHA,
                       expected_sha=SHA)
    assert "identity_mismatch" in result["blockers"]


def test_arm_survives_process_restart_with_bounded_identity():
    value = _armed()
    restored = stage1.normalize(json.loads(json.dumps(value)), SHA)
    for key in ("armId", "armRequestedAt", "armRequestedByClass",
                "armTargetBuildSha", "armTargetBootPolicy",
                "armLifecycleVersion"):
        assert restored[key] == value[key]
    assert _decision(restored)["eligible"] is True


def test_kill_before_atomic_publish_loses_neither_arm_nor_audit():
    value = _armed()
    # Compute the transaction candidate, then model a process kill before the
    # candidate is published/persisted: durable input remains fully armed.
    candidate = stage1.consume_arm(
        value, consumed_at="2026-08-06T03:07:01Z",
        mission_window_id="mw-2026-08-06T03:07:00Z",
        arm_id=value["armId"])
    assert value["formalSoakArmed"] is True
    assert _decision(value)["eligible"] is True
    assert candidate["lastConsumedArm"]["armId"] == value["armId"]
    assert candidate["lastConsumedArm"]["missionWindowId"] == \
        "mw-2026-08-06T03:07:00Z"


def test_active_soak_blocks_replacement():
    result = _decision(_armed(), active=True)
    assert result["eligible"] is False
    assert "active_soak_exists" in result["blockers"]


def test_cross_sha_deploy_terminalizes_without_replacement():
    old = {
        "soakId": "soak-old", "buildShaFull": OLD_SHA,
        "startedAt": "2026-08-06T03:07:00Z", "state": "running",
        "processBootId": "old-boot", "completed72h": False,
        "heartbeats": [{"observedAt": "2026-08-06T03:37:00Z"}],
    }
    result = argus_runtime.soak_restore_decision(
        persisted=old, current_build_sha=SHA,
        boot_iso="2026-08-06T04:00:00Z", current_boot_id="new-boot")
    terminal = result["terminalSoak"]
    assert result["action"] == "terminalize_interrupted"
    assert terminal["soakId"] == old["soakId"]
    assert terminal["startedAt"] == old["startedAt"]
    assert terminal["heartbeats"] == old["heartbeats"]
    assert terminal["state"] == "interrupted"
    assert terminal["completed72h"] is False
    assert "newSoak" not in result


def test_disabled_projection_reports_legacy_only():
    saved_enabled = scanner._CHECKPOINT_V2_STAGE1_ENABLED
    saved_control = copy.deepcopy(scanner._CHECKPOINT_V2_STAGE1_CONTROL)
    try:
        scanner._CHECKPOINT_V2_STAGE1_ENABLED = False
        scanner._CHECKPOINT_V2_STAGE1_CONTROL.clear()
        scanner._CHECKPOINT_V2_STAGE1_CONTROL.update(
            stage1.empty_state(SHA))
        projection = scanner._formal_soak_public_projection()
        assert projection["checkpointMode"] == "legacy_only"
        assert "checkpoint_v2_disabled" in projection["blockers"]
    finally:
        scanner._CHECKPOINT_V2_STAGE1_ENABLED = saved_enabled
        scanner._CHECKPOINT_V2_STAGE1_CONTROL.clear()
        scanner._CHECKPOINT_V2_STAGE1_CONTROL.update(saved_control)


def test_active_projection_cannot_report_only_not_started():
    saved_soak = copy.deepcopy(scanner._SOAK)
    try:
        scanner._SOAK.update({
            "soakId": "soak-live", "startedAt": "2026-08-06T03:07:00Z",
            "state": "running", "completed72h": False})
        projection = scanner._formal_soak_public_projection()
        assert projection["activeRuntime"]["active"] is True
        assert projection["activeRuntime"]["state"] == "running"
        assert projection["activeRuntime"]["soakId"] == "soak-live"
    finally:
        scanner._SOAK.clear(); scanner._SOAK.update(saved_soak)


def test_historical_interrupted_soak_projection_is_immutable():
    saved_history = copy.deepcopy(scanner._SOAK_HISTORY)
    row = {"soakId": "soak-history",
           "startedAt": "2026-08-05T00:07:00Z",
           "terminalState": "interrupted", "completed72h": False}
    try:
        scanner._SOAK_HISTORY[:] = [copy.deepcopy(row)]
        before = copy.deepcopy(scanner._SOAK_HISTORY)
        projection = scanner._formal_soak_public_projection()
        assert projection["history"][0]["state"] == "interrupted"
        assert scanner._SOAK_HISTORY == before
    finally:
        scanner._SOAK_HISTORY[:] = saved_history


def test_ordinary_legacy_checkpoint_success_grants_no_start_authority():
    value = _accepted()
    value["legacyRestoreAuthority"] = True
    value["formalSoakArmed"] = False
    result = _decision(value, enabled=False)
    assert result["eligible"] is False
    assert "checkpoint_v2_disabled" in result["blockers"]
    assert "formal_soak_not_armed" in result["blockers"]
