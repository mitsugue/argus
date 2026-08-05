"""Pure state machine for Checkpoint V2 Stage 1 formal-Soak suppression."""
from __future__ import annotations

import copy
import hashlib
from typing import Any, Dict, Mapping, Optional


SCHEMA = "argus-checkpoint-v2-stage1-control-v2"
LEGACY_SCHEMA = "argus-checkpoint-v2-stage1-control-v1"
REQUIRED_NATURAL_WINDOWS = 3
MAXIMUM_GENERATION_HISTORY = 12
MAXIMUM_ACCEPTED_PEAK_BYTES = 3 * 1024 * 1024 * 1024
MINIMUM_FREE_SPACE_RESERVE = 1024 * 1024 * 1024
MAXIMUM_MONOTONIC_RSS_GROWTH = 128 * 1024 * 1024


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
    }


def normalize(state: Optional[Mapping[str, Any]],
              build_sha: Optional[str] = None) -> Dict[str, Any]:
    result = empty_state(build_sha)
    if isinstance(state, Mapping) and state.get("schemaVersion") in (
            SCHEMA, LEGACY_SCHEMA):
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
        armed_at: str) -> Dict[str, Any]:
    updated = normalize(state, build_sha)
    if int(updated.get("validationWindowCount") or 0) < \
            REQUIRED_NATURAL_WINDOWS:
        raise Stage1ControlError("three_distinct_natural_windows_required")
    if updated.get("authorityPromotionBlocked") is not False:
        raise Stage1ControlError("stage1_acceptance_incomplete")
    if updated.get("lastValidationFailure"):
        raise Stage1ControlError("validation_failure_unresolved")
    if updated.get("formalSoakArmed") is True:
        return updated
    arm_id = "checkpoint-v2-soak-arm-" + hashlib.sha256(
        f"{build_sha}|{armed_at}".encode("utf-8")).hexdigest()[:12]
    updated.update({"formalSoakArmed": True, "armedAt": armed_at,
                    "armId": arm_id, "formalSoakState": "armed"})
    return updated


def may_start_formal_soak(state: Mapping[str, Any], *,
                          trigger_source: str,
                          qualified_natural_tick: bool) -> bool:
    normalized = normalize(state, state.get("buildSha"))
    return bool(
        trigger_source == "ec2_systemd" and qualified_natural_tick and
        normalized.get("formalSoakArmed") is True and
        normalized.get("formalSoakState") == "armed" and
        normalized.get("authorityPromotionBlocked") is False)


def consume_arm(state: Mapping[str, Any]) -> Dict[str, Any]:
    updated = normalize(state, state.get("buildSha"))
    updated.update({"formalSoakArmed": False,
                    "formalSoakState": "started",
                    "armId": None, "armedAt": None})
    return updated
