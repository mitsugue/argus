"""Fixed public and authenticated operational diagnostic contracts.

The builders in this module deliberately accept scalar observations and build
new dictionaries from literals.  They never copy runtime dictionaries.  This
keeps future internal fields out of public responses by construction.
"""
from __future__ import annotations

import json
import math
import re
from datetime import datetime
from typing import Any, Mapping, Optional


PUBLIC_SCHEMA = "argus-public-diagnostics-v1"
PUBLIC_LIVENESS_SCHEMA = "argus-public-liveness-v1"
PUBLIC_READINESS_SCHEMA = "argus-public-readiness-v1"
OPERATIONAL_SCHEMA = "argus-operational-diagnostics-v1"

PUBLIC_MAX_BYTES = 8 * 1024
OPERATIONAL_MAX_BYTES = 512 * 1024
MAX_SAFE_INTEGER = 9_007_199_254_740_991

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_SEMVER_RE = re.compile(
    r"^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?$")
_CODE_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
_STATUS_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")

PUBLIC_LIVENESS = frozenset({"ok", "unavailable"})
PUBLIC_READINESS = frozenset({"ready", "not_ready"})
PUBLIC_OVERALL = frozenset({"ok", "degraded", "unavailable"})
PUBLIC_FRESHNESS = frozenset({"fresh", "aging", "stale", "unknown", "mixed"})


class DiagnosticsContractError(ValueError):
    """A diagnostics input or output did not satisfy the closed contract."""


def _timestamp(value: Any, *, optional: bool = False) -> Optional[str]:
    if value is None and optional:
        return None
    if not isinstance(value, str) or len(value) > 40:
        raise DiagnosticsContractError("timestamp_invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise DiagnosticsContractError("timestamp_invalid") from exc
    if parsed.tzinfo is None:
        raise DiagnosticsContractError("timestamp_invalid")
    return value


def _count(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not (
            0 <= value <= MAX_SAFE_INTEGER):
        raise DiagnosticsContractError("count_invalid")
    return value


def _number(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DiagnosticsContractError("number_invalid")
    result = float(value)
    if not math.isfinite(result) or result < 0 or result > MAX_SAFE_INTEGER:
        raise DiagnosticsContractError("number_invalid")
    return round(result, 6)


def _status(value: Any, *, default: str = "unknown") -> str:
    candidate = str(value or default).strip().lower()
    return candidate if _STATUS_RE.fullmatch(candidate) else default


def _code(value: Any, *, default: str = "UNKNOWN") -> str:
    candidate = str(value or default).strip().upper()
    return candidate if _CODE_RE.fullmatch(candidate) else default


def _sha(value: Any) -> Optional[str]:
    candidate = str(value or "").strip().lower()
    return candidate if _SHA_RE.fullmatch(candidate) else None


def _version(value: Any) -> str:
    candidate = str(value or "unknown").strip()
    return candidate if _SEMVER_RE.fullmatch(candidate) else "unknown"


def _enum(value: Any, allowed: frozenset[str], default: str) -> str:
    return value if isinstance(value, str) and value in allowed else default


def serialized_size(value: Mapping[str, Any]) -> int:
    return len(json.dumps(value, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"), allow_nan=False).encode("utf-8"))


def build_public_diagnostics(
        *, generated_at: str, backend_version: Any, build_sha: Any,
        liveness: Any, readiness: Any, overall: Any,
        freshness_overall: Any, source_counts: Mapping[str, Any],
        expected_disabled_count: Any) -> dict[str, Any]:
    """Build the exact recursive ``PublicDiagnosticsDTO v1`` allowlist."""
    result = {
        "schemaVersion": PUBLIC_SCHEMA,
        "generatedAt": _timestamp(generated_at),
        "service": {
            "liveness": _enum(liveness, PUBLIC_LIVENESS, "unavailable"),
            "readiness": _enum(readiness, PUBLIC_READINESS, "not_ready"),
            "overall": _enum(overall, PUBLIC_OVERALL, "unavailable"),
            "backendVersion": _version(backend_version),
            "buildSha": _sha(build_sha),
        },
        "freshness": {
            "overall": _enum(
                freshness_overall, PUBLIC_FRESHNESS, "unknown"),
            "sourceCounts": {
                "fresh": _count(source_counts.get("fresh", 0)),
                "aging": _count(source_counts.get("aging", 0)),
                "stale": _count(source_counts.get("stale", 0)),
                "unknown": _count(source_counts.get("unknown", 0)),
            },
            "expectedDisabledCount": _count(expected_disabled_count),
        },
        "recovery": {
            "mode": "LEGACY_ONLY",
            "measurement": "SHADOW_INCOMPLETE",
            "exactColdRecovery": "NOT_PROVEN",
            "hardRpoClaimPermitted": False,
        },
    }
    if serialized_size(result) > PUBLIC_MAX_BYTES:
        raise DiagnosticsContractError("public_diagnostics_too_large")
    return result


def public_diagnostics_fallback(generated_at: str) -> dict[str, Any]:
    """Literal fallback independent from the fallible primary builder."""
    return {
        "schemaVersion": PUBLIC_SCHEMA,
        "generatedAt": _timestamp(generated_at),
        "service": {
            "liveness": "unavailable",
            "readiness": "not_ready",
            "overall": "unavailable",
            "backendVersion": "unknown",
            "buildSha": None,
        },
        "freshness": {
            "overall": "unknown",
            "sourceCounts": {
                "fresh": 0, "aging": 0, "stale": 0, "unknown": 0,
            },
            "expectedDisabledCount": 0,
        },
        "recovery": {
            "mode": "LEGACY_ONLY",
            "measurement": "SHADOW_INCOMPLETE",
            "exactColdRecovery": "NOT_PROVEN",
            "hardRpoClaimPermitted": False,
        },
    }


def build_public_liveness(*, generated_at: str, backend_version: Any,
                          build_sha: Any) -> dict[str, Any]:
    result = {
        "schemaVersion": PUBLIC_LIVENESS_SCHEMA,
        "generatedAt": _timestamp(generated_at),
        "status": "ok",
        "backendVersion": _version(backend_version),
        "buildSha": _sha(build_sha),
    }
    if serialized_size(result) > PUBLIC_MAX_BYTES:
        raise DiagnosticsContractError("public_liveness_too_large")
    return result


def build_public_readiness(
        *, generated_at: str, backend_version: Any, build_sha: Any,
        ready: bool, reason_code: Any) -> dict[str, Any]:
    if type(ready) is not bool:
        raise DiagnosticsContractError("readiness_invalid")
    result = {
        "schemaVersion": PUBLIC_READINESS_SCHEMA,
        "generatedAt": _timestamp(generated_at),
        "ready": ready,
        "status": "ready" if ready else "not_ready",
        "reasonCode": _code(reason_code, default="NOT_READY"),
        "backendVersion": _version(backend_version),
        "buildSha": _sha(build_sha),
    }
    if serialized_size(result) > PUBLIC_MAX_BYTES:
        raise DiagnosticsContractError("public_readiness_too_large")
    return result


def build_operational_diagnostics(
        *, generated_at: str, backend_version: Any, build_sha: Any,
        ready: bool, readiness_code: Any, startup_state: Any,
        process_booted_at: Any, freshness: Mapping[str, Any],
        storage: Mapping[str, Any], durability: Mapping[str, Any],
        remote_journal: Mapping[str, Any], features: Mapping[str, Any],
        scheduler: Mapping[str, Any], registry: Mapping[str, Any],
        osint: Mapping[str, Any], cost_policy: Mapping[str, Any]) -> dict[str, Any]:
    """Build a bounded admin-only diagnostics DTO from reviewed scalars."""
    if type(ready) is not bool:
        raise DiagnosticsContractError("readiness_invalid")
    source_counts = freshness.get("sourceCounts") or {}
    checkpoint = durability.get("checkpoint") or {}
    result = {
        "schemaVersion": OPERATIONAL_SCHEMA,
        "generatedAt": _timestamp(generated_at),
        "service": {
            "ready": ready,
            "readinessCode": _code(readiness_code, default="NOT_READY"),
            "startupState": _status(startup_state),
            "backendVersion": _version(backend_version),
            "buildSha": _sha(build_sha),
            "processBootedAt": _timestamp(process_booted_at, optional=True),
        },
        "freshness": {
            "overall": _enum(
                freshness.get("overall"), PUBLIC_FRESHNESS, "unknown"),
            "sourceCounts": {
                "fresh": _count(source_counts.get("fresh", 0)),
                "aging": _count(source_counts.get("aging", 0)),
                "stale": _count(source_counts.get("stale", 0)),
                "unknown": _count(source_counts.get("unknown", 0)),
            },
            "expectedDisabledCount": _count(
                freshness.get("expectedDisabledCount", 0)),
        },
        "storage": {
            "productionMode": bool(storage.get("productionMode")),
            "valid": bool(storage.get("valid")),
            "runtimeVerified": bool(storage.get("runtimeVerified")),
            "statusCode": _code(storage.get("statusCode")),
            "checkpointBytes": _count(storage.get("checkpointBytes", 0)),
            "walBytes": _count(storage.get("walBytes", 0)),
        },
        "durability": {
            "integrityStatus": _status(durability.get("integrityStatus")),
            "journalCorruptCount": _count(
                durability.get("journalCorruptCount", 0)),
            "missionWalCorruptCount": _count(
                durability.get("missionWalCorruptCount", 0)),
            "writeCount": _count(durability.get("writeCount", 0)),
            "successCount": _count(durability.get("successCount", 0)),
            "failureCount": _count(durability.get("failureCount", 0)),
            "checkpoint": {
                "verified": bool(checkpoint.get("verified")),
                "readBackVerified": bool(checkpoint.get("readBackVerified")),
                "includedWalSequence": _count(
                    checkpoint.get("includedWalSequence", 0)),
                "verifiedAt": _timestamp(
                    checkpoint.get("verifiedAt"), optional=True),
            },
        },
        "remoteJournal": {
            "localCommittedCount": _count(
                remote_journal.get("localCommittedCount", 0)),
            "pendingCount": _count(remote_journal.get("pendingCount", 0)),
            "committedCount": _count(remote_journal.get("committedCount", 0)),
            "failedCount": _count(remote_journal.get("failedCount", 0)),
            "readBackVerified": bool(remote_journal.get("readBackVerified")),
            "walReadBackVerified": bool(
                remote_journal.get("walReadBackVerified")),
            "state": _status(remote_journal.get("state")),
            "remoteWalAppliedSequence": _count(
                remote_journal.get("remoteWalAppliedSequence", 0)),
            "verifiedWalSequence": _count(
                remote_journal.get("verifiedWalSequence", 0)),
            "errorPresent": bool(remote_journal.get("errorPresent")),
            "lastVerifiedAckAt": _timestamp(
                remote_journal.get("lastVerifiedAckAt"), optional=True),
        },
        "features": {
            "checkpointMode": _status(features.get("checkpointMode"),
                                       default="legacy_only"),
            "checkpointV2State": _status(features.get("checkpointV2State"),
                                          default="disabled"),
            "stage1Enabled": bool(features.get("stage1Enabled")),
            "soakArmed": bool(features.get("soakArmed")),
            "soakState": _status(features.get("soakState"),
                                  default="not_started"),
            "exactColdRecovery": "NOT_PROVEN",
            "hardRpoClaimPermitted": False,
        },
        "scheduler": {
            "missionCount": _count(scheduler.get("missionCount", 0)),
            "missionWindowCount": _count(
                scheduler.get("missionWindowCount", 0)),
            "foundationJobCount": _count(
                scheduler.get("foundationJobCount", 0)),
            "agentQueueDepth": _count(scheduler.get("agentQueueDepth", 0)),
        },
        "registry": {
            "stateCount": _count(registry.get("stateCount", 0)),
            "mutationCount": _count(registry.get("mutationCount", 0)),
            "validationErrorCount": _count(
                registry.get("validationErrorCount", 0)),
        },
        "osint": {
            "investigationCount": _count(osint.get("investigationCount", 0)),
            "memoryRecordCount": _count(osint.get("memoryRecordCount", 0)),
            "urlCacheCount": _count(osint.get("urlCacheCount", 0)),
            "canaryState": _status(osint.get("canaryState"),
                                    default="not_run"),
        },
        "costPolicy": {
            "mode": _code(cost_policy.get("mode"),
                           default="DETERMINISTIC"),
            "daySpentUsd": _number(cost_policy.get("daySpentUsd", 0.0)),
            "monthSpentUsd": _number(cost_policy.get("monthSpentUsd", 0.0)),
        },
    }
    if result["remoteJournal"]["localCommittedCount"] != (
            result["remoteJournal"]["pendingCount"] +
            result["remoteJournal"]["committedCount"]):
        raise DiagnosticsContractError("remote_journal_counts_inconsistent")
    if serialized_size(result) > OPERATIONAL_MAX_BYTES:
        raise DiagnosticsContractError("operational_diagnostics_too_large")
    return result


def operational_diagnostics_fallback(generated_at: str) -> dict[str, Any]:
    """Fixed authenticated failure body; contains no runtime/error details."""
    return {
        "schemaVersion": OPERATIONAL_SCHEMA,
        "generatedAt": _timestamp(generated_at),
        "status": "unavailable",
        "errorCode": "OPERATIONAL_DIAGNOSTICS_UNAVAILABLE",
    }
