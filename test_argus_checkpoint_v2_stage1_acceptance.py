"""Checkpoint V2 Stage 1 control-plane acceptance closure contracts."""
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

import argus_checkpoint_v2
import argus_checkpoint_v2_stage1 as stage1
import argus_runtime
import scanner


SHA = "b" * 40
BOOT_1 = "boot-old"
BOOT_2 = "boot-new"
STARTED = "2026-08-04T00:07:00Z"
RESTARTED = "2026-08-05T00:00:00Z"


def running_soak():
    return {
        "soakId": "soak-bbbbbbb-window", "buildSha": SHA[:7],
        "buildShaFull": SHA, "appVersion": "13.4.0",
        "processBootId": BOOT_1,
        "processBootedAt": "2026-08-04T00:00:00Z",
        "startedAt": STARTED, "state": "soak_in_progress",
        "completed72h": False,
        "heartbeats": [{"observedAt": "2026-08-04T23:37:00Z"}],
        "lastHeartbeatAt": "2026-08-04T23:37:00Z",
        "interruptions": [], "interruptionCount": 0,
    }


def test_running_old_boot_terminalizes_without_rewriting_identity():
    old = running_soak()
    decision = argus_runtime.soak_restore_decision(
        persisted=old, current_build_sha=SHA, boot_iso=RESTARTED,
        last_persist_at="2026-08-04T23:40:00Z",
        current_boot_id=BOOT_2)
    terminal = decision["terminalSoak"]
    assert decision["action"] == "terminalize_interrupted"
    assert decision["interruptionClass"] == "boot_discontinuity"
    assert terminal["soakId"] == old["soakId"]
    assert terminal["startedAt"] == old["startedAt"]
    assert terminal["heartbeats"] == old["heartbeats"]
    assert terminal["state"] == "interrupted"
    assert terminal["completed72h"] is False
    assert decision["previousSoakSummary"]["lifecycleRelation"] == \
        "same_build_boot_discontinuity"
    assert old["state"] == "soak_in_progress"


def test_planned_class_requires_matching_durable_marker():
    marker = {
        "durable": True, "interruptionClass": "planned_owner_restart",
        "soakId": "soak-bbbbbbb-window", "sourceBootId": BOOT_1,
    }
    planned = argus_runtime.soak_restore_decision(
        persisted=running_soak(), current_build_sha=SHA,
        boot_iso=RESTARTED, current_boot_id=BOOT_2,
        planned_restart_marker=marker)
    assert planned["interruptionClass"] == "planned_owner_restart"

    forged = copy.deepcopy(marker)
    forged["durable"] = False
    unplanned = argus_runtime.soak_restore_decision(
        persisted=running_soak(), current_build_sha=SHA,
        boot_iso=RESTARTED, current_boot_id=BOOT_2,
        planned_restart_marker=forged)
    assert unplanned["interruptionClass"] == "boot_discontinuity"


def test_terminalized_soak_is_idempotent_and_never_resumed():
    first = argus_runtime.soak_restore_decision(
        persisted=running_soak(), current_build_sha=SHA,
        boot_iso=RESTARTED, current_boot_id=BOOT_2)
    second = argus_runtime.soak_restore_decision(
        persisted=first["terminalSoak"], current_build_sha=SHA,
        boot_iso="2026-08-05T01:00:00Z", current_boot_id="boot-three")
    assert second["action"] == "preserve_terminal"
    assert second["previousSoakSummary"]["soakId"] == \
        running_soak()["soakId"]
    assert second["previousSoakSummary"]["startedAt"] == STARTED
    assert second["previousSoakSummary"]["terminalState"] == "interrupted"


def telemetry(after, *, peak=2 * 1024 ** 3, free=2 * 1024 ** 3):
    return {
        "success": True, "processRssBeforeBytes": after - 1024,
        "processPeakRssBytes": peak, "processRssAfterBytes": after,
        "processRssDeltaBytes": 1024,
        "cgroupMemoryCurrentBeforeBytes": after - 1024,
        "cgroupMemoryCurrentAfterBytes": after,
        "cgroupMemoryPeakBytes": peak,
        "generationBytes": 1024, "rowCount": 4, "sectionCount": 2,
        "durationMs": 12.5, "diskFreeBeforeBytes": free + 1024,
        "diskFreeAfterBytes": free, "pendingGenerationCount": 0,
        "writerLockWaitMs": 0.1,
        "legacyTempBaselineCount": 1, "legacyTempAfterCount": 1,
        "newLegacyTempCount": 0,
    }


def test_resource_gate_uses_three_distinct_windows_and_bounded_growth():
    state = stage1.empty_state(SHA)
    for index in range(3):
        state = stage1.record_generation(
            state, {
                "verified": True, "generationId": f"gen-{index}",
                "createdAt": f"2026-08-05T0{index}:00:00Z",
                "resourceTelemetry": telemetry(500_000_000 + index * 1024),
            }, trigger_source="ec2_systemd",
            mission_window_id=f"mw-{index}")
    gate = stage1.resource_acceptance(state)
    assert gate["passed"] is True
    assert gate["validationWindowCount"] == 3
    assert gate["generationCount"] == 3


def test_resource_gate_rejects_peak_disk_pending_and_monotonic_growth():
    state = stage1.empty_state(SHA)
    values = [400_000_000, 500_000_000, 700_000_000]
    for index, after in enumerate(values):
        row = telemetry(after)
        if index == 2:
            row.update({"cgroupMemoryPeakBytes": 3 * 1024 ** 3,
                        "diskFreeAfterBytes": 100,
                        "pendingGenerationCount": 1})
        state = stage1.record_generation(
            state, {"verified": True, "generationId": f"gen-{index}",
                    "resourceTelemetry": row},
            trigger_source="ec2_systemd", mission_window_id=f"mw-{index}")
    blockers = stage1.resource_acceptance(state)["blockers"]
    assert "generation_peak_not_below_3gib" in blockers
    assert "generation_disk_reserve_below_1gib" in blockers
    assert "generation_pending_not_zero" in blockers
    assert "uncontrolled_monotonic_rss_growth" in blockers


def test_resource_gate_rejects_new_legacy_temp_after_baseline():
    state = stage1.empty_state(SHA)
    for index in range(3):
        row = telemetry(500_000_000 + index)
        if index == 2:
            row.update({"legacyTempAfterCount": 2,
                        "newLegacyTempCount": 1})
        state = stage1.record_generation(
            state, {"verified": True, "generationId": f"gen-{index}",
                    "resourceTelemetry": row},
            trigger_source="ec2_systemd", mission_window_id=f"mw-{index}")
    assert "new_legacy_temp_after_baseline" in \
        stage1.resource_acceptance(state)["blockers"]


def test_generation_manifest_contains_public_safe_resource_telemetry(tmp_path):
    result = argus_checkpoint_v2.write_generation(
        str(tmp_path / "v2"), {"memory": [{"id": "safe"}]},
        source_generation="legacy", validation_context={
            "triggerSource": "ec2_systemd", "missionWindowId": "mw-one",
            "natural": True})
    telemetry_value = result["resourceTelemetry"]
    for field in (
            "processRssBeforeBytes", "processPeakRssBytes",
            "processRssAfterBytes", "processRssDeltaBytes",
            "cgroupMemoryCurrentBeforeBytes",
            "cgroupMemoryCurrentAfterBytes", "cgroupMemoryPeakBytes",
            "generationBytes", "rowCount", "sectionCount", "durationMs",
            "diskFreeBeforeBytes", "diskFreeAfterBytes",
            "pendingGenerationCount", "writerLockWaitMs", "success"):
        assert field in telemetry_value
    manifest = json.loads((tmp_path / "v2" /
                           argus_checkpoint_v2.MANIFEST_NAME).read_text())
    assert manifest["stage1Validation"]["resourceTelemetry"]["success"] is True
    assert "path" not in json.dumps(telemetry_value).lower()
    assert "symbol" not in json.dumps(telemetry_value).lower()


def test_remote_journal_epochs_ignore_lifetime_lag_for_current_gate():
    saved_journal = copy.deepcopy(scanner._OPS_JOURNAL)
    saved_ack = copy.deepcopy(scanner._REMOTE_ACK)
    saved_cycle = copy.deepcopy(scanner._REMOTE_CYCLE)
    saved_control = copy.deepcopy(scanner._CHECKPOINT_V2_STAGE1_CONTROL)
    saved_soak = copy.deepcopy(scanner._SOAK)
    try:
        scanner._OPS_JOURNAL[:] = []
        scanner._REMOTE_ACK.update({"ackedKeys": [],
                                    "maxObservedLagSec": 7528})
        scanner._REMOTE_CYCLE.update({
            "remoteDurabilityState": "verified", "readBackVerified": True,
            "walReadBackVerified": True, "verifiedWalSequence": 9,
            "remoteWalAppliedSequence": 9,
            "receiptCommitSha": "a" * 40})
        scanner._CHECKPOINT_V2_STAGE1_CONTROL[
            "stage1EpochStartedAt"] = "2026-08-05T00:00:00Z"
        scanner._SOAK["previousSoak"] = {"startedAt": STARTED}
        value = scanner._remote_journal_diagnostics(
            "2026-08-05T01:00:00Z")
        assert value["lifetimeMaxPendingAgeSeconds"] == 7528
        assert value["checkpointV2Stage1MaxPendingAgeSeconds"] == 0
        assert value["currentPendingCount"] == 0
        assert value["exactReceiptVerified"] is True
    finally:
        scanner._OPS_JOURNAL[:] = saved_journal
        scanner._REMOTE_ACK.clear(); scanner._REMOTE_ACK.update(saved_ack)
        scanner._REMOTE_CYCLE.clear(); scanner._REMOTE_CYCLE.update(saved_cycle)
        scanner._CHECKPOINT_V2_STAGE1_CONTROL.clear()
        scanner._CHECKPOINT_V2_STAGE1_CONTROL.update(saved_control)
        scanner._SOAK.clear(); scanner._SOAK.update(saved_soak)
