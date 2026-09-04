"""Pure, constraint-only Risk Discipline kernel for ARGUS Round 2.

The kernel is deliberately incapable of choosing a portfolio action.  It
normalizes bounded risk evidence into one content-addressed constraint, while
deduplicating engines that describe the same primitive factor.  It performs no
I/O and all time is supplied by the caller.
"""
from __future__ import annotations

import argus_fastdate  # v13.5.52: lock-free strptime (no _strptime._cache_lock)
import copy
import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping


INPUT_SCHEMA_VERSION = "argus-risk-discipline-input-v1"
KERNEL_SCHEMA_VERSION = "argus-risk-kernel-v1"

SOURCE_KINDS = (
    "MARKET",
    "SHO",
    "SCENARIO",
    "EVENT",
    "PORTFOLIO",
    "CONCENTRATION",
    "DISCIPLINE",
)
CONSTRAINTS = ("NONE", "BLOCK_BUY", "WAIT_REQUIRED", "REDUCE_RISK", "EXIT_RISK")
STATUSES = ("ACTIVE", "INACTIVE", "MISSING", "CONFLICT")
SEVERITIES = ("NONE", "LOW", "MEDIUM", "HIGH", "CRITICAL", "UNKNOWN")
KERNEL_STATUSES = ("READY", "DATA_GATED")

MAX_CONTRIBUTIONS = 32
MAX_EVIDENCE_REFS_PER_FACTOR = 8
MAX_REASON_CODES = 16
MAX_CANONICAL_BODY_BYTES = 64 * 1024

_KERNEL_SEAL = object()


class _VerifiedRiskKernel(dict):
    """Runtime capability returned only by the canonical kernel builder."""

    __slots__ = ("_authority_seal", "_body_digest")

_INPUT_KEYS = {
    "schemaVersion",
    "subject",
    "asOf",
    "informationCutoffAt",
    "policy",
    "contributions",
}
_SUBJECT_KEYS = {"kind", "instrumentId", "market"}
_POLICY_KEYS = {"policyId", "policySha256"}
_CONTRIBUTION_KEYS = {
    "evidenceRef",
    "primitiveFactorId",
    "sourceKind",
    "constraint",
    "status",
    "severity",
    "confidenceCapBps",
    "observedAt",
}
_KERNEL_KEYS = {
    "schemaVersion",
    "riskKernelId",
    "privacyClass",
    "subject",
    "asOf",
    "informationCutoffAt",
    "policy",
    "status",
    "constraint",
    "confidenceCapBps",
    "primitiveFactors",
    "missingReasonCodes",
    "conflictReasonCodes",
    "finalActionAuthority",
}
_FACTOR_KEYS = {
    "primitiveFactorId",
    "status",
    "constraint",
    "severity",
    "confidenceCapBps",
    "evidenceRefs",
}

_ID_RE = re.compile(r"[a-z0-9][a-z0-9._:-]{0,95}\Z")
_INSTRUMENT_RE = re.compile(r"[A-Z0-9][A-Z0-9._:-]{0,31}\Z")
_EVIDENCE_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:@/-]{0,95}\Z")
_SHA64_RE = re.compile(r"[0-9a-f]{64}\Z")
_KERNEL_ID_RE = re.compile(r"rk-[0-9a-f]{64}\Z")
_UTC_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z\Z")

_CONSTRAINT_PRECEDENCE = {
    "NONE": 0,
    "BLOCK_BUY": 1,
    "WAIT_REQUIRED": 2,
    "REDUCE_RISK": 3,
    "EXIT_RISK": 4,
}
_SEVERITY_PRECEDENCE = {
    "NONE": 0,
    "UNKNOWN": 1,
    "LOW": 2,
    "MEDIUM": 3,
    "HIGH": 4,
    "CRITICAL": 5,
}


class RiskDisciplineValidationError(ValueError):
    """Raised when a Risk Discipline input or kernel violates the contract."""


def _fail(path: str, message: str) -> None:
    raise RiskDisciplineValidationError(f"{path}: {message}")


def _exact_mapping(value: Any, keys: set[str], path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail(path, "must be an object")
    actual = set(value.keys())
    if actual != keys:
        _fail(
            path,
            f"keys must be exact; missing={sorted(keys - actual)}, extra={sorted(actual - keys)}",
        )
    return value


def _utc(value: Any, path: str) -> datetime:
    if not isinstance(value, str) or not _UTC_RE.fullmatch(value):
        _fail(path, "must be an exact UTC timestamp with whole-second precision")
    try:
        return argus_fastdate.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise RiskDisciplineValidationError(f"{path}: invalid UTC timestamp") from exc


def _canonical_json_bytes(value: Any) -> bytes:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise RiskDisciplineValidationError("kernel is not canonical JSON") from exc
    if len(encoded) > MAX_CANONICAL_BODY_BYTES:
        _fail("kernel", f"canonical body exceeds {MAX_CANONICAL_BODY_BYTES} bytes")
    return encoded


def _body_from_kernel(kernel_or_body: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        key: copy.deepcopy(value)
        for key, value in kernel_or_body.items()
        if key != "riskKernelId"
    }


def compute_risk_kernel_id(kernel_or_body: Mapping[str, Any]) -> str:
    """Return the content address over the canonical kernel body."""
    return "rk-" + hashlib.sha256(
        _canonical_json_bytes(_body_from_kernel(kernel_or_body))
    ).hexdigest()


def _validate_subject(value: Any, path: str = "subject") -> Mapping[str, Any]:
    subject = _exact_mapping(value, _SUBJECT_KEYS, path)
    if subject["kind"] != "ASSET":
        _fail(f"{path}.kind", "must equal ASSET")
    if (
        not isinstance(subject["instrumentId"], str)
        or not _INSTRUMENT_RE.fullmatch(subject["instrumentId"])
    ):
        _fail(f"{path}.instrumentId", "must be a normalized bounded identifier")
    if subject["market"] not in ("JP", "US", "CRYPTO", "FUND"):
        _fail(f"{path}.market", "unknown market")
    return subject


def _validate_policy(value: Any, path: str = "policy") -> Mapping[str, Any]:
    policy = _exact_mapping(value, _POLICY_KEYS, path)
    if not isinstance(policy["policyId"], str) or not _ID_RE.fullmatch(policy["policyId"]):
        _fail(f"{path}.policyId", "malformed policy identifier")
    if (
        not isinstance(policy["policySha256"], str)
        or not _SHA64_RE.fullmatch(policy["policySha256"])
    ):
        _fail(f"{path}.policySha256", "must be a lowercase SHA-256")
    return policy


def _validate_bps(value: Any, path: str, *, nullable: bool) -> None:
    if nullable and value is None:
        return
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 10_000:
        _fail(path, "must be an integer from 0 through 10000")


def _validate_request(request: Any) -> Mapping[str, Any]:
    top = _exact_mapping(request, _INPUT_KEYS, "request")
    if top["schemaVersion"] != INPUT_SCHEMA_VERSION:
        _fail("schemaVersion", f"must equal {INPUT_SCHEMA_VERSION}")
    _validate_subject(top["subject"])
    as_of = _utc(top["asOf"], "asOf")
    cutoff = _utc(top["informationCutoffAt"], "informationCutoffAt")
    if cutoff > as_of:
        _fail("informationCutoffAt", "cannot be later than asOf")
    _validate_policy(top["policy"])

    contributions = top["contributions"]
    if not isinstance(contributions, list):
        _fail("contributions", "must be an array")
    if len(contributions) > MAX_CONTRIBUTIONS:
        _fail("contributions", f"must contain at most {MAX_CONTRIBUTIONS} rows")
    for index, raw in enumerate(contributions):
        path = f"contributions[{index}]"
        item = _exact_mapping(raw, _CONTRIBUTION_KEYS, path)
        if (
            not isinstance(item["evidenceRef"], str)
            or not _EVIDENCE_RE.fullmatch(item["evidenceRef"])
            or "://" in item["evidenceRef"]
        ):
            _fail(f"{path}.evidenceRef", "must be a bounded non-URL reference")
        if (
            not isinstance(item["primitiveFactorId"], str)
            or not _ID_RE.fullmatch(item["primitiveFactorId"])
        ):
            _fail(f"{path}.primitiveFactorId", "malformed primitive factor identifier")
        if item["sourceKind"] not in SOURCE_KINDS:
            _fail(f"{path}.sourceKind", "unknown source kind")
        if item["constraint"] not in CONSTRAINTS:
            _fail(f"{path}.constraint", "unknown constraint")
        if item["status"] not in STATUSES:
            _fail(f"{path}.status", "unknown contribution status")
        if item["severity"] not in SEVERITIES:
            _fail(f"{path}.severity", "unknown severity")
        _validate_bps(item["confidenceCapBps"], f"{path}.confidenceCapBps", nullable=True)
        if _utc(item["observedAt"], f"{path}.observedAt") > cutoff:
            _fail(f"{path}.observedAt", "cannot be later than informationCutoffAt")
        if item["status"] != "ACTIVE" and item["constraint"] != "NONE":
            _fail(f"{path}.constraint", "non-active evidence cannot carry a constraint")
    return top


def _reason_for_factor(prefix: str, primitive_factor_id: str) -> str:
    value = f"risk_{prefix}.{primitive_factor_id}"
    return value[:96]


def build_risk_kernel(request: Any) -> Dict[str, Any]:
    """Build a deterministic constraint-only kernel from validated evidence.

    Multiple rows with the same ``primitiveFactorId`` represent one fact.  A
    repeated identical constraint is deduplicated; contradictory active rows
    become a conflict instead of a vote.
    """
    top = _validate_request(request)
    grouped: Dict[str, List[Mapping[str, Any]]] = {}
    for row in top["contributions"]:
        grouped.setdefault(row["primitiveFactorId"], []).append(row)

    factors: List[Dict[str, Any]] = []
    missing: List[str] = []
    conflicts: List[str] = []
    for factor_id in sorted(grouped):
        rows = grouped[factor_id]
        active = [row for row in rows if row["status"] == "ACTIVE"]
        active_constraints = {row["constraint"] for row in active}
        has_declared_conflict = any(row["status"] == "CONFLICT" for row in rows)
        has_active_disagreement = len(active_constraints) > 1

        if has_declared_conflict or has_active_disagreement:
            status = "CONFLICT"
            constraint = "NONE"
            conflicts.append(_reason_for_factor("conflict", factor_id))
        elif active:
            status = "ACTIVE"
            constraint = next(iter(active_constraints))
        elif any(row["status"] == "MISSING" for row in rows):
            status = "MISSING"
            constraint = "NONE"
            missing.append(_reason_for_factor("missing", factor_id))
        else:
            status = "INACTIVE"
            constraint = "NONE"

        relevant = active if status == "ACTIVE" else rows
        caps = [row["confidenceCapBps"] for row in relevant if row["confidenceCapBps"] is not None]
        cap = min(caps) if caps else None
        severity = max(
            (row["severity"] for row in relevant),
            key=lambda item: _SEVERITY_PRECEDENCE[item],
            default="UNKNOWN",
        )
        refs = sorted({row["evidenceRef"] for row in rows})
        if len(refs) > MAX_EVIDENCE_REFS_PER_FACTOR:
            _fail(
                f"primitiveFactors.{factor_id}.evidenceRefs",
                f"must contain at most {MAX_EVIDENCE_REFS_PER_FACTOR} unique references",
            )
        factors.append(
            {
                "primitiveFactorId": factor_id,
                "status": status,
                "constraint": constraint,
                "severity": severity,
                "confidenceCapBps": cap,
                "evidenceRefs": refs,
            }
        )

    if not factors:
        missing.append("risk_evidence_empty")

    data_gated = bool(missing or conflicts)
    active_constraints = [
        factor["constraint"] for factor in factors if factor["status"] == "ACTIVE"
    ]
    constraint = max(
        active_constraints,
        key=lambda item: _CONSTRAINT_PRECEDENCE[item],
        default="NONE",
    )
    if data_gated and _CONSTRAINT_PRECEDENCE[constraint] < _CONSTRAINT_PRECEDENCE["WAIT_REQUIRED"]:
        constraint = "WAIT_REQUIRED"

    active_caps = [
        factor["confidenceCapBps"]
        for factor in factors
        if factor["status"] == "ACTIVE" and factor["confidenceCapBps"] is not None
    ]
    confidence_cap = min(active_caps) if active_caps else 10_000
    if data_gated:
        confidence_cap = min(confidence_cap, 2_500)

    body: Dict[str, Any] = {
        "schemaVersion": KERNEL_SCHEMA_VERSION,
        "privacyClass": "DEVICE_LOCAL_DERIVED",
        "subject": copy.deepcopy(top["subject"]),
        "asOf": top["asOf"],
        "informationCutoffAt": top["informationCutoffAt"],
        "policy": copy.deepcopy(top["policy"]),
        "status": "DATA_GATED" if data_gated else "READY",
        "constraint": constraint,
        "confidenceCapBps": confidence_cap,
        "primitiveFactors": factors,
        "missingReasonCodes": sorted(set(missing))[:MAX_REASON_CODES],
        "conflictReasonCodes": sorted(set(conflicts))[:MAX_REASON_CODES],
        "finalActionAuthority": False,
    }
    kernel = _VerifiedRiskKernel({"riskKernelId": compute_risk_kernel_id(body), **body})
    validate_risk_kernel(kernel)
    kernel._authority_seal = _KERNEL_SEAL
    kernel._body_digest = hashlib.sha256(_canonical_json_bytes(kernel)).hexdigest()
    return kernel


def is_verifier_issued_risk_kernel(value: Any) -> bool:
    """Return whether the kernel is an unmodified canonical-builder result."""
    return bool(
        isinstance(value, _VerifiedRiskKernel)
        and getattr(value, "_authority_seal", None) is _KERNEL_SEAL
        and getattr(value, "_body_digest", None)
        == hashlib.sha256(_canonical_json_bytes(value)).hexdigest()
    )


def validate_risk_kernel(value: Any) -> None:
    """Strictly validate a produced kernel, including its content address."""
    top = _exact_mapping(value, _KERNEL_KEYS, "kernel")
    if top["schemaVersion"] != KERNEL_SCHEMA_VERSION:
        _fail("schemaVersion", f"must equal {KERNEL_SCHEMA_VERSION}")
    if (
        not isinstance(top["riskKernelId"], str)
        or not _KERNEL_ID_RE.fullmatch(top["riskKernelId"])
    ):
        _fail("riskKernelId", "must be rk- followed by a lowercase SHA-256")
    if top["privacyClass"] != "DEVICE_LOCAL_DERIVED":
        _fail("privacyClass", "must equal DEVICE_LOCAL_DERIVED")
    _validate_subject(top["subject"], "kernel.subject")
    as_of = _utc(top["asOf"], "kernel.asOf")
    cutoff = _utc(top["informationCutoffAt"], "kernel.informationCutoffAt")
    if cutoff > as_of:
        _fail("kernel.informationCutoffAt", "cannot be later than asOf")
    _validate_policy(top["policy"], "kernel.policy")
    if top["status"] not in KERNEL_STATUSES:
        _fail("kernel.status", "unknown kernel status")
    if top["constraint"] not in CONSTRAINTS:
        _fail("kernel.constraint", "unknown constraint")
    _validate_bps(top["confidenceCapBps"], "kernel.confidenceCapBps", nullable=False)
    if top["finalActionAuthority"] is not False:
        _fail("kernel.finalActionAuthority", "must be false")

    factors = top["primitiveFactors"]
    if not isinstance(factors, list) or len(factors) > MAX_CONTRIBUTIONS:
        _fail("kernel.primitiveFactors", f"must be an array of at most {MAX_CONTRIBUTIONS}")
    factor_ids: List[str] = []
    for index, raw in enumerate(factors):
        path = f"kernel.primitiveFactors[{index}]"
        factor = _exact_mapping(raw, _FACTOR_KEYS, path)
        factor_id = factor["primitiveFactorId"]
        if not isinstance(factor_id, str) or not _ID_RE.fullmatch(factor_id):
            _fail(f"{path}.primitiveFactorId", "malformed primitive factor identifier")
        factor_ids.append(factor_id)
        if factor["status"] not in STATUSES:
            _fail(f"{path}.status", "unknown factor status")
        if factor["constraint"] not in CONSTRAINTS:
            _fail(f"{path}.constraint", "unknown constraint")
        if factor["status"] != "ACTIVE" and factor["constraint"] != "NONE":
            _fail(f"{path}.constraint", "non-active factor cannot carry a constraint")
        if factor["severity"] not in SEVERITIES:
            _fail(f"{path}.severity", "unknown severity")
        _validate_bps(factor["confidenceCapBps"], f"{path}.confidenceCapBps", nullable=True)
        refs = factor["evidenceRefs"]
        if (
            not isinstance(refs, list)
            or not refs
            or len(refs) > MAX_EVIDENCE_REFS_PER_FACTOR
            or refs != sorted(set(refs))
            or any(
                not isinstance(ref, str)
                or not _EVIDENCE_RE.fullmatch(ref)
                or "://" in ref
                for ref in refs
            )
        ):
            _fail(f"{path}.evidenceRefs", "must be a bounded sorted unique reference array")
    if factor_ids != sorted(set(factor_ids)):
        _fail("kernel.primitiveFactors", "must be sorted and unique by primitiveFactorId")

    for field in ("missingReasonCodes", "conflictReasonCodes"):
        codes = top[field]
        if (
            not isinstance(codes, list)
            or len(codes) > MAX_REASON_CODES
            or codes != sorted(set(codes))
            or any(not isinstance(code, str) or not _ID_RE.fullmatch(code) for code in codes)
        ):
            _fail(f"kernel.{field}", "must be a bounded sorted unique reason-code array")
    expected_missing = [
        _reason_for_factor("missing", factor["primitiveFactorId"])
        for factor in factors if factor["status"] == "MISSING"
    ]
    expected_conflicts = [
        _reason_for_factor("conflict", factor["primitiveFactorId"])
        for factor in factors if factor["status"] == "CONFLICT"
    ]
    if not factors:
        expected_missing.append("risk_evidence_empty")
    expected_missing = sorted(set(expected_missing))[:MAX_REASON_CODES]
    expected_conflicts = sorted(set(expected_conflicts))[:MAX_REASON_CODES]
    if top["missingReasonCodes"] != expected_missing or \
            top["conflictReasonCodes"] != expected_conflicts:
        _fail("kernel.reasonCodes", "must exactly match summarized factor status")
    data_gated = bool(expected_missing or expected_conflicts)
    expected_status = "DATA_GATED" if data_gated else "READY"
    if top["status"] != expected_status:
        _fail("kernel.status", "must be derived from factor missing/conflict state")
    active_constraints = [
        factor["constraint"] for factor in factors
        if factor["status"] == "ACTIVE"
    ]
    expected_constraint = max(
        active_constraints,
        key=lambda item: _CONSTRAINT_PRECEDENCE[item],
        default="NONE",
    )
    if data_gated and _CONSTRAINT_PRECEDENCE[expected_constraint] < \
            _CONSTRAINT_PRECEDENCE["WAIT_REQUIRED"]:
        expected_constraint = "WAIT_REQUIRED"
    if top["constraint"] != expected_constraint:
        _fail("kernel.constraint", "must be derived from active unique factors")
    active_caps = [
        factor["confidenceCapBps"] for factor in factors
        if factor["status"] == "ACTIVE"
        and factor["confidenceCapBps"] is not None
    ]
    expected_cap = min(active_caps) if active_caps else 10_000
    if data_gated:
        expected_cap = min(expected_cap, 2_500)
    if top["confidenceCapBps"] != expected_cap:
        _fail("kernel.confidenceCapBps", "must be derived from active/data-gated factors")
    expected = compute_risk_kernel_id(top)
    if top["riskKernelId"] != expected:
        _fail("riskKernelId", "does not match the canonical kernel body")


__all__ = [
    "CONSTRAINTS",
    "INPUT_SCHEMA_VERSION",
    "KERNEL_SCHEMA_VERSION",
    "RiskDisciplineValidationError",
    "build_risk_kernel",
    "compute_risk_kernel_id",
    "is_verifier_issued_risk_kernel",
    "validate_risk_kernel",
]
