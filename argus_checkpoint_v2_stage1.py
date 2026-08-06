"""Pure state machine for Checkpoint V2 Stage 1 formal-Soak suppression."""
from __future__ import annotations

import copy
import hashlib
from typing import Any, Dict, Mapping, Optional


SCHEMA = "argus-checkpoint-v2-stage1-control-v3"
LEGACY_SCHEMAS = {
    "argus-checkpoint-v2-stage1-control-v1",
    "argus-checkpoint-v2-stage1-control-v2",
}
FORMAL_SOAK_LIFECYCLE_VERSION = "formal-soak-v1"
FORMAL_SOAK_BOOT_POLICY = "same-build-qualified-natural-window"
REQUIRED_NATURAL_WINDOWS = 3
MAXIMUM_GENERATION_HISTORY = 12
MAXIMUM_ACCEPTED_PEAK_BYTES = 3 * 1024 * 1024 * 1024
MINIMUM_FREE_SPACE_RESERVE = 1024 * 1024 * 1024
MAXIMUM_MONOTONIC_RSS_GROWTH = 128 * 1024 * 1024

_START_BLOCKER_ORDER = (
    "checkpoint_v2_disabled",
    "formal_soak_not_armed",
    "resource_acceptance_failed",
    "authority_promotion_blocked",
    "disk_acceptance_missing",
    "isolated_restore_not_verified",
    "restore_authority_approval_missing",
    "validation_failure_unresolved",
    "active_soak_exists",
    "trigger_not_qualified_natural",
    "mission_window_replayed",
    "identity_mismatch",
    "arm_contract_invalid",
)


class Stage1ControlError(RuntimeError):
    pass


def resource_acceptance(state: Mapping[str, Any]) -> Dict[str, Any]:
    """Evaluate one latest physical generation per distinct natural window."""
    normalized = normalize(state, state.get("buildSha"))
    by_window: Dict[str, Mapping[str, Any]] = {}
    for row in normalized.get("naturalGenerations") or []:
        window_id = str(row.get("missionWindowId") or "")
        if window_id.startswith("mw-"):
            by_window[window_id] = row
    selected = list(by_window.values())[-REQUIRED_NATURAL_WINDOWS:]
    blockers = []
    rss_after = []
    for row in selected:
        telemetry = row.get("resourceTelemetry") or {}
        if telemetry.get("success") is not True:
            blockers.append("generation_telemetry_unverified")
            continue
        peak = telemetry.get("cgroupMemoryPeakBytes")
        if peak is None:
            peak = telemetry.get("processPeakRssBytes")
        if peak is None or int(peak) >= MAXIMUM_ACCEPTED_PEAK_BYTES:
            blockers.append("generation_peak_not_below_3gib")
        if int(telemetry.get("diskFreeAfterBytes") or 0) < \
                MINIMUM_FREE_SPACE_RESERVE:
            blockers.append("generation_disk_reserve_below_1gib")
        if int(telemetry.get("pendingGenerationCount") or 0) != 0:
            blockers.append("generation_pending_not_zero")
        if telemetry.get("newLegacyTempCount") not in (0, None):
            blockers.append("new_legacy_temp_after_baseline")
        after = telemetry.get("processRssAfterBytes")
        if after is not None:
            rss_after.append(int(after))
    if len(selected) < REQUIRED_NATURAL_WINDOWS:
        blockers.append("three_distinct_natural_windows_required")
    if len(rss_after) >= REQUIRED_NATURAL_WINDOWS and all(
            right > left for left, right in zip(rss_after, rss_after[1:])) \
            and rss_after[-1] - rss_after[0] > MAXIMUM_MONOTONIC_RSS_GROWTH:
        blockers.append("uncontrolled_monotonic_rss_growth")
    return {
        "passed": not blockers,
        "validationWindowCount": len(by_window),
        "generationCount": len(
            normalized.get("naturalGenerations") or []),
        "evaluatedGenerationCount": len(selected),
        "blockers": sorted(set(blockers)),
        "maximumAcceptedPeakBytes": MAXIMUM_ACCEPTED_PEAK_BYTES,
        "minimumFreeSpaceReserve": MINIMUM_FREE_SPACE_RESERVE,
    }


def empty_state(build_sha: Optional[str] = None) -> Dict[str, Any]:
    return {
        "schemaVersion": SCHEMA,
        "buildSha": build_sha,
        "checkpointMode": "dual_write_validation",
        "formalSoakArmed": False,
        "formalSoakState": "not_started",
        "naturalGenerations": [],
        "validationWindowIds": [],
        "validationWindowCount": 0,
        "generationCount": 0,
        "stage1EpochStartedAt": None,
        "resourceAcceptance": False,
        "diskAcceptance": False,
        "isolatedRestoreVerified": False,
        "restoreAuthorityApprovalRecorded": False,
        "v2RestoreAuthority": False,
        "legacyRestoreAuthority": True,
        "authorityPromotionBlocked": True,
        "lastValidationFailure": None,
        "armId": None,
        "armedAt": None,
        "armRequestedAt": None,
        "armRequestedByClass": None,
        "armTargetBuildSha": None,
        "armTargetBootPolicy": None,
        "armLifecycleVersion": None,
        "lastConsumedArm": None,
    }


def normalize(state: Optional[Mapping[str, Any]],
              build_sha: Optional[str] = None) -> Dict[str, Any]:
    result = empty_state(build_sha)
    if isinstance(state, Mapping) and state.get("schemaVersion") in (
            {SCHEMA} | LEGACY_SCHEMAS):
        for key in result:
            if key in state:
                result[key] = copy.deepcopy(state[key])
    if build_sha and result.get("buildSha") != build_sha:
        return empty_state(build_sha)
    rows = []
    seen = set()
    for row in result.get("naturalGenerations") or []:
        if not isinstance(row, Mapping):
            continue
        generation_id = str(row.get("generationId") or "")
        if not generation_id or generation_id in seen:
            continue
        if row.get("triggerSource") != "ec2_systemd" or \
                row.get("verified") is not True:
            continue
        seen.add(generation_id)
        rows.append(dict(row))
    result["schemaVersion"] = SCHEMA
    result["naturalGenerations"] = rows[-MAXIMUM_GENERATION_HISTORY:]
    window_ids = []
    for value in list(result.get("validationWindowIds") or []) + [
            row.get("missionWindowId") for row in rows]:
        value = str(value or "")
        if value.startswith("mw-") and value not in window_ids:
            window_ids.append(value)
    result["validationWindowIds"] = window_ids[-64:]
    result["validationWindowCount"] = len(window_ids)
    result["generationCount"] = max(
        int(result.get("generationCount") or 0), len(rows))
    if not result.get("stage1EpochStartedAt") and rows:
        result["stage1EpochStartedAt"] = rows[0].get("createdAt")
    return result


def record_generation(state: Mapping[str, Any], result: Mapping[str, Any],
                      *, trigger_source: str,
                      mission_window_id: Optional[str]) -> Dict[str, Any]:
    updated = normalize(state, state.get("buildSha"))
    if result.get("verified") is not True:
        return updated
    if trigger_source != "ec2_systemd":
        return updated
    generation_id = str(result.get("generationId") or "")
    if not generation_id:
        return updated
    rows = list(updated["naturalGenerations"])
    prior_ids = {str(row.get("generationId") or "") for row in rows}
    if not any(row.get("generationId") == generation_id for row in rows):
        rows.append({
            "generationId": generation_id,
            "triggerSource": "ec2_systemd",
            "missionWindowId": mission_window_id,
            "createdAt": result.get("createdAt") or
                (result.get("validation") or {}).get("createdAt"),
            "verified": True,
            "databaseBytes": result.get("databaseBytes"),
            "sourceSerializedBytes": result.get("sourceSerializedBytes"),
            "resourceTelemetry": copy.deepcopy(
                result.get("resourceTelemetry") or {}),
        })
    updated["naturalGenerations"] = rows[-MAXIMUM_GENERATION_HISTORY:]
    window_ids = list(updated.get("validationWindowIds") or [])
    if str(mission_window_id or "").startswith("mw-") and \
            mission_window_id not in window_ids:
        window_ids.append(mission_window_id)
    updated["validationWindowIds"] = window_ids[-64:]
    updated["validationWindowCount"] = len(window_ids)
    if generation_id not in prior_ids:
        updated["generationCount"] = int(
            updated.get("generationCount") or 0) + 1
    if not updated.get("stage1EpochStartedAt"):
        updated["stage1EpochStartedAt"] = rows[-1].get("createdAt")
    updated["lastValidationFailure"] = None
    return updated


def record_failure(state: Mapping[str, Any], classification: str,
                   details: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    updated = normalize(state, state.get("buildSha"))
    updated.update({
        "formalSoakArmed": False,
        "formalSoakState": "not_started",
        "authorityPromotionBlocked": True,
        "lastValidationFailure": {
            "classification": str(classification),
            "details": dict(details or {}),
        },
        "armId": None,
        "armedAt": None,
        "armRequestedAt": None,
        "armRequestedByClass": None,
        "armTargetBuildSha": None,
        "armTargetBootPolicy": None,
        "armLifecycleVersion": None,
    })
    return updated


def record_acceptance(state: Mapping[str, Any], *,
                      resource_accepted: bool, disk_accepted: bool,
                      isolated_restore_verified: bool,
                      restore_authority_approved: bool) -> Dict[str, Any]:
    updated = normalize(state, state.get("buildSha"))
    if int(updated.get("validationWindowCount") or 0) < \
            REQUIRED_NATURAL_WINDOWS:
        raise Stage1ControlError("three_distinct_natural_windows_required")
    updated.update({
        "resourceAcceptance": resource_accepted is True,
        "diskAcceptance": disk_accepted is True,
        "isolatedRestoreVerified": isolated_restore_verified is True,
        "restoreAuthorityApprovalRecorded":
            restore_authority_approved is True,
    })
    updated["authorityPromotionBlocked"] = not all(
        updated[key] for key in (
            "resourceAcceptance", "diskAcceptance",
            "isolatedRestoreVerified",
            "restoreAuthorityApprovalRecorded"))
    return updated


def arm(state: Mapping[str, Any], *, build_sha: str,
        armed_at: str, requested_by_class: str = "owner_admin",
        target_boot_policy: str = FORMAL_SOAK_BOOT_POLICY,
        lifecycle_version: str = FORMAL_SOAK_LIFECYCLE_VERSION) -> Dict[str, Any]:
    build_sha = str(build_sha or "").lower()
    if len(build_sha) != 40 or any(
            char not in "0123456789abcdef" for char in build_sha):
        raise Stage1ControlError("formal_soak_arm_build_identity_invalid")
    updated = normalize(state, build_sha)
    if int(updated.get("validationWindowCount") or 0) < \
            REQUIRED_NATURAL_WINDOWS:
        raise Stage1ControlError("three_distinct_natural_windows_required")
    if updated.get("authorityPromotionBlocked") is not False:
        raise Stage1ControlError("stage1_acceptance_incomplete")
    if resource_acceptance(updated).get("passed") is not True or \
            updated.get("resourceAcceptance") is not True:
        raise Stage1ControlError("stage1_resource_gate_failed")
    if updated.get("lastValidationFailure"):
        raise Stage1ControlError("validation_failure_unresolved")
    if updated.get("formalSoakArmed") is True:
        return updated
    arm_id = "checkpoint-v2-soak-arm-" + hashlib.sha256(
        f"{build_sha}|{armed_at}".encode("utf-8")).hexdigest()[:12]
    updated.update({
        "formalSoakArmed": True,
        "formalSoakState": "armed",
        "armId": arm_id,
        # ``armedAt`` remains as the backwards-compatible persisted alias.
        "armedAt": armed_at,
        "armRequestedAt": armed_at,
        "armRequestedByClass": str(requested_by_class)[:40],
        "armTargetBuildSha": build_sha,
        "armTargetBootPolicy": target_boot_policy,
        "armLifecycleVersion": lifecycle_version,
    })
    return updated


def formal_soak_start_eligibility(
        state: Mapping[str, Any], *, checkpoint_v2_enabled: bool,
        trigger_source: str, qualified_natural_tick: bool,
        mission_window_id: Optional[str], current_build_sha: Optional[str],
        active_soak_exists: bool, active_soak_id: Optional[str] = None,
        expected_build_sha: Optional[str] = None) -> Dict[str, Any]:
    """Return one fail-closed, public-safe Formal Soak start decision.

    Stage 1 being disabled is a blocker, never an authorization shortcut.
    The live resource gate is evaluated again so an accepted but stale state
    cannot arm or start a final acceptance clock.
    """
    normalized = normalize(state, state.get("buildSha"))
    resource_gate = resource_acceptance(normalized)
    blockers = set()
    if not checkpoint_v2_enabled:
        blockers.add("checkpoint_v2_disabled")
    if normalized.get("formalSoakArmed") is not True or \
            normalized.get("formalSoakState") != "armed" or \
            not normalized.get("armId"):
        blockers.add("formal_soak_not_armed")
    if normalized.get("resourceAcceptance") is not True or \
            resource_gate.get("passed") is not True:
        blockers.add("resource_acceptance_failed")
    if normalized.get("authorityPromotionBlocked") is not False:
        blockers.add("authority_promotion_blocked")
    if normalized.get("diskAcceptance") is not True:
        blockers.add("disk_acceptance_missing")
    if normalized.get("isolatedRestoreVerified") is not True:
        blockers.add("isolated_restore_not_verified")
    if normalized.get("restoreAuthorityApprovalRecorded") is not True:
        blockers.add("restore_authority_approval_missing")
    if normalized.get("lastValidationFailure"):
        blockers.add("validation_failure_unresolved")
    if active_soak_exists:
        blockers.add("active_soak_exists")
    window_id = str(mission_window_id or "")
    if trigger_source != "ec2_systemd" or not qualified_natural_tick or \
            not window_id.startswith("mw-") or window_id.startswith(
                "mw-manual-"):
        blockers.add("trigger_not_qualified_natural")
    last_consumed = normalized.get("lastConsumedArm") or {}
    if window_id and window_id == last_consumed.get("missionWindowId"):
        blockers.add("mission_window_replayed")
    current_sha = str(current_build_sha or "").lower()
    expected_sha = str(expected_build_sha or current_sha).lower()
    state_sha = str(normalized.get("buildSha") or "").lower()
    arm_sha = str(normalized.get("armTargetBuildSha") or "").lower()
    if not current_sha or len(current_sha) != 40 or expected_sha != current_sha \
            or state_sha != current_sha or arm_sha != current_sha:
        blockers.add("identity_mismatch")
    if normalized.get("armRequestedByClass") != "owner_admin" or \
            normalized.get("armTargetBootPolicy") != FORMAL_SOAK_BOOT_POLICY or \
            normalized.get("armLifecycleVersion") != \
            FORMAL_SOAK_LIFECYCLE_VERSION or \
            not normalized.get("armRequestedAt"):
        blockers.add("arm_contract_invalid")
    ordered = [item for item in _START_BLOCKER_ORDER if item in blockers]
    return {
        "eligible": not ordered,
        "blockers": ordered,
        "evidence": {
            "checkpointV2Enabled": bool(checkpoint_v2_enabled),
            "triggerSource": str(trigger_source)[:40],
            "missionWindowId": window_id[:96] or None,
            "currentBuildSha": current_sha or None,
            "expectedBuildSha": expected_sha or None,
            "stateBuildSha": state_sha or None,
            "armTargetBuildSha": arm_sha or None,
            "armId": str(normalized.get("armId") or "")[:80] or None,
            "armRequestedAt": normalized.get("armRequestedAt"),
            "armRequestedByClass": normalized.get("armRequestedByClass"),
            "armTargetBootPolicy": normalized.get("armTargetBootPolicy"),
            "armLifecycleVersion": normalized.get("armLifecycleVersion"),
            "resourceAcceptancePassed": resource_gate.get("passed") is True,
            "authorityPromotionBlocked": bool(
                normalized.get("authorityPromotionBlocked")),
            "activeSoak": bool(active_soak_exists),
            "activeSoakId": str(active_soak_id or "")[:80] or None,
        },
    }


def may_start_formal_soak(state: Mapping[str, Any], *,
                          trigger_source: str,
                          qualified_natural_tick: bool,
                          checkpoint_v2_enabled: bool = True,
                          mission_window_id: str = "mw-legacy-call",
                          current_build_sha: Optional[str] = None,
                          active_soak_exists: bool = False,
                          expected_build_sha: Optional[str] = None) -> bool:
    """Compatibility boolean backed by the central structured predicate."""
    build_sha = current_build_sha or state.get("buildSha")
    return formal_soak_start_eligibility(
        state, checkpoint_v2_enabled=checkpoint_v2_enabled,
        trigger_source=trigger_source,
        qualified_natural_tick=qualified_natural_tick,
        mission_window_id=mission_window_id,
        current_build_sha=build_sha,
        active_soak_exists=active_soak_exists,
        expected_build_sha=expected_build_sha or build_sha)["eligible"]


def consume_arm(state: Mapping[str, Any], *, consumed_at: Optional[str] = None,
                mission_window_id: Optional[str] = None,
                arm_id: Optional[str] = None) -> Dict[str, Any]:
    updated = normalize(state, state.get("buildSha"))
    current_arm_id = str(updated.get("armId") or "")
    if not current_arm_id or (arm_id and str(arm_id) != current_arm_id):
        raise Stage1ControlError("formal_soak_arm_identity_mismatch")
    updated["lastConsumedArm"] = {
        "armId": current_arm_id,
        "requestedAt": updated.get("armRequestedAt") or
            updated.get("armedAt"),
        "requestedByClass": updated.get("armRequestedByClass"),
        "targetBuildSha": updated.get("armTargetBuildSha"),
        "targetBootPolicy": updated.get("armTargetBootPolicy"),
        "lifecycleVersion": updated.get("armLifecycleVersion"),
        "consumedAt": consumed_at,
        "missionWindowId": mission_window_id,
    }
    updated.update({
        "formalSoakArmed": False,
        "formalSoakState": "started",
        "armId": None,
        "armedAt": None,
        "armRequestedAt": None,
        "armRequestedByClass": None,
        "armTargetBuildSha": None,
        "armTargetBootPolicy": None,
        "armLifecycleVersion": None,
    })
    return updated
