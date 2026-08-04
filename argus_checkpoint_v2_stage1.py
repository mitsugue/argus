"""Pure state machine for Checkpoint V2 Stage 1 formal-Soak suppression."""
from __future__ import annotations

import copy
import hashlib
from typing import Any, Dict, Mapping, Optional


SCHEMA = "argus-checkpoint-v2-stage1-control-v1"
REQUIRED_NATURAL_GENERATIONS = 3


class Stage1ControlError(RuntimeError):
    pass


def empty_state(build_sha: Optional[str] = None) -> Dict[str, Any]:
    return {
        "schemaVersion": SCHEMA,
        "buildSha": build_sha,
        "checkpointMode": "dual_write_validation",
        "formalSoakArmed": False,
        "formalSoakState": "not_started",
        "naturalGenerations": [],
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
    if isinstance(state, Mapping) and state.get("schemaVersion") == SCHEMA:
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
    result["naturalGenerations"] = rows[-4:]
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
    if not any(row.get("generationId") == generation_id for row in rows):
        rows.append({
            "generationId": generation_id,
            "triggerSource": "ec2_systemd",
            "missionWindowId": mission_window_id,
            "verified": True,
            "databaseBytes": result.get("databaseBytes"),
            "sourceSerializedBytes": result.get("sourceSerializedBytes"),
        })
    updated["naturalGenerations"] = rows[-4:]
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
    if len(updated["naturalGenerations"]) < REQUIRED_NATURAL_GENERATIONS:
        raise Stage1ControlError("three_natural_generations_required")
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
    if len(updated["naturalGenerations"]) < REQUIRED_NATURAL_GENERATIONS:
        raise Stage1ControlError("three_natural_generations_required")
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
