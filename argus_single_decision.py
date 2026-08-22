"""Deterministic Single Decision Authority v2.

This is a pure final-action authority over a closed, owner-local context.  It
accepts only verifier-issued evidence bundles for Market Truth, Prediction
Ledger, SHO and the constraint-only Risk Kernel.  Reference strings and
caller booleans are never authority.  AI and legacy challenges are retained
as dissent provenance only and cannot select or override the action.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from types import MappingProxyType
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import argus_decision_ledger as decision_ledger
import argus_market_clock
import argus_market_data_truth as market_truth
import argus_sho as sho_authority
from argus_risk_discipline import (
    KERNEL_SCHEMA_VERSION,
    RiskDisciplineValidationError,
    build_risk_kernel,
    is_verifier_issued_risk_kernel,
    validate_risk_kernel,
)


INPUT_SCHEMA_VERSION = "single-decision-authority-input-v2"
RESULT_SCHEMA_VERSION = "single-decision-authority-v2"
OWNER_CONTEXT_SCHEMA_VERSION = "owner-decision-context-v1"
SEVEN_SIGN_SCHEMA_VERSION = "seven-sign-v1"
LEDGER_ADAPTER_SCHEMA_VERSION = "argus-prediction-ledger-sda-adapter-v2"
VERIFIED_EVIDENCE_SCHEMA_VERSION = "verified-decision-evidence-bundle-v1"
AUTHORITY_POLICY_ID = "single-decision-authority-v2"
AUTHORITY_POLICY_SHA256 = "bbd5da4bb68fed291908ff574f36a3c1c4b20bb48cf86d6a837eecf98353ea31"
SINGLE_DECISION_AUTHORITY_V2_POLICY = MappingProxyType(
    {"policyId": AUTHORITY_POLICY_ID, "policySha256": AUTHORITY_POLICY_SHA256}
)

PRIMARY_ACTIONS = ("BUY", "HOLD", "WAIT", "REDUCE", "EXIT")
REFERENCE_STATUSES = ("AVAILABLE", "MISSING", "CONFLICT", "STALE")
SHO_STATES = (
    "FRAGILE",
    "DOWNSIDE_TRIGGERED",
    "SELL_OFF_ACTIVE",
    "REVERSAL_EARLY",
    "TECHNICAL_REBOUND",
    "RECOVERY_TEST",
    "CONFIRMED_ADVANCE",
    "FALSE_RALLY",
    "MIXED",
)
BUY_ELIGIBLE_SHO_STATES = (
    "REVERSAL_EARLY",
    "TECHNICAL_REBOUND",
    "RECOVERY_TEST",
    "CONFIRMED_ADVANCE",
)
SHO_VALIDATION_STATUSES = ("VALIDATED", "UNVALIDATED", "DATA_GATED", "CONFLICT")
QUALITY_STATUSES = ("COMPLETE", "PARTIAL", "MISSING", "CONFLICT")
FRESHNESS_STATUSES = ("FRESH", "DELAYED", "STALE", "UNKNOWN")
CONTEXT_STATUSES = ("ACTIVE", "INACTIVE", "MISSING", "CONFLICT")
CONTEXT_CONSTRAINTS = ("NONE", "WAIT_REQUIRED")
SEVEN_CALIBRATION_STATUSES = ("VALIDATED", "SHADOW", "DATA_GATED", "MISSING")

MAX_CONTEXT_EVIDENCE = 16
MAX_CHALLENGE_EVIDENCE = 8
MAX_PRIMITIVE_FACTOR_IDS = 48
MAX_EVIDENCE_REFS = 48
MAX_REASON_CODES = 24
MAX_TARGETS = 4
MAX_CANONICAL_BODY_BYTES = 128 * 1024
MIN_SEVEN_SIGN_SAMPLE_SIZE = 30
# Production calibration is a closed registry, not a caller assertion.  It is
# intentionally empty until a separately verified, immutable OOS calibration
# artifact is approved and pinned here.
VERIFIED_SEVEN_SIGN_CALIBRATIONS = MappingProxyType({})
# A production BUY can only be enabled by a repository-pinned, independently
# verified SHO artifact identity.  Round 2 intentionally has no such entry:
# canonical SHO remains UNVALIDATED/DATA_GATED until a future code review pins
# an immutable validation artifact here.
VERIFIED_SHO_BUY_ARTIFACTS = MappingProxyType({})

_BUNDLE_SEAL = object()
_RESULT_SEAL = object()


class _VerifiedDecisionEvidenceBundle(dict):
    """Runtime capability issued only by ``verify_decision_evidence``."""

    __slots__ = ("_authority_seal", "_bundle_id", "_body_digest", "_sho_buy_eligible")


class _VerifiedSingleDecisionResult(dict):
    """Runtime result capability bound to one verified evidence bundle."""

    __slots__ = ("_authority_seal", "_bundle_id", "_body_digest")

_INPUT_KEYS = {
    "schemaVersion",
    "subject",
    "decisionAt",
    "informationCutoffAt",
    "authorityPolicy",
    "marketTruth",
    "predictionLedger",
    "sho",
    "riskKernel",
    "contextEvidence",
    "quality",
    "ownerContext",
    "challengeEvidence",
    "sevenSignCalibration",
}
_SUBJECT_KEYS = {"kind", "instrumentId", "market", "horizon"}
_POLICY_KEYS = {"policyId", "policySha256"}
_OWNER_KEYS = {
    "schemaVersion",
    "privacyClass",
    "asOf",
    "positionState",
    "positionRiskBand",
    "concentrationBand",
    "addPermission",
}
_MARKET_TRUTH_KEYS = {
    "status",
    "schemaVersion",
    "snapshotId",
    "observationId",
    "observedAt",
    "knownAt",
    "policyId",
    "policySha256",
}
_PREDICTION_LEDGER_KEYS = {
    "status",
    "schemaVersion",
    "contextId",
    "mode",
    "asOf",
    "policyId",
    "policySha256",
}
_SHO_KEYS = {
    "status",
    "schemaVersion",
    "artifactId",
    "asOf",
    "policyId",
    "policySha256",
    "state",
    "validationStatus",
    "primitiveFactorIds",
    "targets",
    "invalidation",
}
_TARGET_KEYS = {"targetId", "value", "unit", "sourceRef"}
_INVALIDATION_KEYS = {"invalidationId", "value", "unit", "sourceRef"}
_CONTEXT_KEYS = {
    "evidenceRef",
    "primitiveFactorId",
    "sourceKind",
    "constraint",
    "status",
    "observedAt",
}
_QUALITY_KEYS = {
    "status",
    "freshness",
    "missingReasonCodes",
    "conflictReasonCodes",
}
_CHALLENGE_KEYS = {
    "challengeId",
    "sourceKind",
    "status",
    "asOf",
    "proposedAction",
    "dissentReasonCodes",
    "evidenceRefs",
}
_CALIBRATION_KEYS = {
    "status",
    "artifactId",
    "policyId",
    "policySha256",
    "expectancyBpsByLevel",
    "sampleSizeByLevel",
    "outOfSample",
    "holdoutImmutable",
}

_RESULT_KEYS = {
    "schemaVersion",
    "decisionId",
    "verifiedEvidenceBundleId",
    "status",
    "subject",
    "issuedAt",
    "informationCutoffAt",
    "primaryAction",
    "confidence",
    "guidance",
    "targets",
    "invalidation",
    "nextReviewConditionCodes",
    "freshness",
    "missingReasonCodes",
    "conflictReasonCodes",
    "dissentReasonCodes",
    "evidenceRefs",
    "primitiveFactorIds",
    "identities",
    "sevenSign",
}
_CONFIDENCE_KEYS = {"valueBps", "status"}
_GUIDANCE_KEYS = {"position", "riskConstraint"}
_IDENTITIES_KEYS = {
    "authorityPolicyId",
    "authorityPolicySha256",
    "marketTruth",
    "predictionLedger",
    "sho",
    "risk",
}
_MARKET_IDENTITY_KEYS = {"status", "snapshotId", "observationId"}
_PREDICTION_IDENTITY_KEYS = {"status", "contextId"}
_SHO_IDENTITY_KEYS = {"status", "artifactId"}
_RISK_IDENTITY_KEYS = {"status", "riskKernelId"}
_SEVEN_RESULT_KEYS = {
    "schemaVersion",
    "status",
    "candidateLevel",
    "productionLevel",
    "policyId",
    "policySha256",
    "calibrationArtifactId",
    "reasonCodes",
}

_ADAPTER_KEYS = {
    "schemaVersion",
    "adapterId",
    "recordType",
    "appendMode",
    "mutatesExistingRows",
    "decisionId",
    "verifiedEvidenceBundleId",
    "issuedAt",
    "informationCutoffAt",
    "subject",
    "authorityPolicyRef",
    "marketTruthRef",
    "predictionLedgerRef",
    "shoRef",
    "riskRef",
    "singleDecisionRef",
    "sevenSignRef",
    "primaryAction",
    "confidenceBps",
    "targets",
    "invalidation",
    "missingReasonCodes",
    "conflictReasonCodes",
    "dissentReasonCodes",
    "evidenceRefs",
    "primitiveFactorIds",
}

_ID_RE = re.compile(r"[a-z0-9][a-z0-9._:-]{0,95}\Z")
_ARTIFACT_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:@/-]{0,127}\Z")
_INSTRUMENT_RE = re.compile(r"[A-Z0-9][A-Z0-9._:-]{0,31}\Z")
_SOURCE_REF_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:@/-]{0,95}\Z")
_SHA64_RE = re.compile(r"[0-9a-f]{64}\Z")
_UTC_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z\Z")
_DECIMAL_RE = re.compile(r"-?(?:0|[1-9][0-9]{0,12})(?:\.[0-9]{1,8})?\Z")
_DECISION_ID_RE = re.compile(r"sda-[0-9a-f]{64}\Z")
_ADAPTER_ID_RE = re.compile(r"pla-[0-9a-f]{64}\Z")
_BUNDLE_ID_RE = re.compile(r"vdeb-[0-9a-f]{64}\Z")


class SingleDecisionValidationError(ValueError):
    """Raised when a v2 authority value violates its closed contract."""


def _fail(path: str, message: str) -> None:
    raise SingleDecisionValidationError(f"{path}: {message}")


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
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise SingleDecisionValidationError(f"{path}: invalid UTC timestamp") from exc


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
        raise SingleDecisionValidationError("value is not canonical JSON") from exc
    if len(encoded) > MAX_CANONICAL_BODY_BYTES:
        _fail("value", f"canonical body exceeds {MAX_CANONICAL_BODY_BYTES} bytes")
    return encoded


def _hash_id(prefix: str, body: Mapping[str, Any]) -> str:
    return prefix + hashlib.sha256(_canonical_json_bytes(body)).hexdigest()


def _body_without(value: Mapping[str, Any], key: str) -> Dict[str, Any]:
    return {name: copy.deepcopy(item) for name, item in value.items() if name != key}


def compute_single_decision_id(result_or_body: Mapping[str, Any]) -> str:
    return _hash_id("sda-", _body_without(result_or_body, "decisionId"))


def compute_prediction_adapter_id(adapter_or_body: Mapping[str, Any]) -> str:
    return _hash_id("pla-", _body_without(adapter_or_body, "adapterId"))


def _identifier(value: Any, path: str, *, nullable: bool = False) -> None:
    if nullable and value is None:
        return
    if not isinstance(value, str) or not _ID_RE.fullmatch(value):
        _fail(path, "malformed bounded identifier")


def _artifact_identifier(value: Any, path: str, *, nullable: bool = False) -> None:
    if nullable and value is None:
        return
    if (
        not isinstance(value, str)
        or not _ARTIFACT_ID_RE.fullmatch(value)
        or "://" in value
    ):
        _fail(path, "malformed bounded non-URL artifact reference")


def _sha(value: Any, path: str, *, nullable: bool = False) -> None:
    if nullable and value is None:
        return
    if not isinstance(value, str) or not _SHA64_RE.fullmatch(value):
        _fail(path, "must be a lowercase SHA-256")


def _bps(value: Any, path: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 10_000:
        _fail(path, "must be an integer from 0 through 10000")


def _canonical_decimal(value: Any, path: str) -> None:
    if not isinstance(value, str) or not _DECIMAL_RE.fullmatch(value):
        _fail(path, "must be a canonical finite decimal string")
    if value == "-0" or ("." in value and value.endswith("0")):
        _fail(path, "must not contain negative zero or trailing fractional zeroes")
    try:
        decimal = Decimal(value)
    except InvalidOperation as exc:
        raise SingleDecisionValidationError(f"{path}: invalid decimal") from exc
    if not decimal.is_finite() or abs(decimal) > Decimal("1000000000000"):
        _fail(path, "decimal is outside the bounded domain")


def _canonical_strings(
    value: Any,
    path: str,
    *,
    cap: int,
    pattern: re.Pattern[str] = _ID_RE,
) -> List[str]:
    if not isinstance(value, list) or len(value) > cap:
        _fail(path, f"must be an array of at most {cap}")
    if any(not isinstance(item, str) or not pattern.fullmatch(item) for item in value):
        _fail(path, "contains a malformed identifier")
    if value != sorted(set(value)):
        _fail(path, "must be sorted and duplicate-free")
    return value


def _validate_policy(value: Any, path: str) -> Mapping[str, Any]:
    policy = _exact_mapping(value, _POLICY_KEYS, path)
    _identifier(policy["policyId"], f"{path}.policyId")
    _sha(policy["policySha256"], f"{path}.policySha256")
    return policy


def _validate_canonical_authority_policy(value: Any, path: str) -> Mapping[str, Any]:
    policy = _validate_policy(value, path)
    if dict(policy) != dict(SINGLE_DECISION_AUTHORITY_V2_POLICY):
        _fail(path, "must equal the repository-pinned SDA v2 policy")
    return policy


def _canonical_sha(value: Any) -> str:
    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


def _verified_bundle_digest(value: Mapping[str, Any]) -> str:
    return _canonical_sha(value)


def _bundle_is_current(value: Any) -> bool:
    return bool(
        isinstance(value, _VerifiedDecisionEvidenceBundle)
        and getattr(value, "_authority_seal", None) is _BUNDLE_SEAL
        and isinstance(getattr(value, "_bundle_id", None), str)
        and _BUNDLE_ID_RE.fullmatch(value._bundle_id)
        and value._body_digest == _verified_bundle_digest(value)
    )


def _result_is_current(value: Any) -> bool:
    return bool(
        isinstance(value, _VerifiedSingleDecisionResult)
        and getattr(value, "_authority_seal", None) is _RESULT_SEAL
        and isinstance(getattr(value, "_bundle_id", None), str)
        and _BUNDLE_ID_RE.fullmatch(value._bundle_id)
        and value.get("verifiedEvidenceBundleId") == value._bundle_id
        and value._body_digest == _verified_bundle_digest(value)
    )


def _validate_subject(value: Any, path: str = "subject") -> Mapping[str, Any]:
    subject = _exact_mapping(value, _SUBJECT_KEYS, path)
    if subject["kind"] != "ASSET":
        _fail(f"{path}.kind", "must equal ASSET")
    if (
        not isinstance(subject["instrumentId"], str)
        or not _INSTRUMENT_RE.fullmatch(subject["instrumentId"])
    ):
        _fail(f"{path}.instrumentId", "malformed normalized instrument identifier")
    if subject["market"] not in ("JP", "US", "CRYPTO", "FUND"):
        _fail(f"{path}.market", "unknown market")
    if subject["horizon"] not in (
        "INTRADAY",
        "ONE_DAY",
        "FIVE_DAY",
        "TWENTY_DAY",
        "LONG_TERM",
    ):
        _fail(f"{path}.horizon", "unknown horizon")
    return subject


def _validate_owner(value: Any, decision_at: datetime) -> Mapping[str, Any]:
    owner = _exact_mapping(value, _OWNER_KEYS, "ownerContext")
    if owner["schemaVersion"] != OWNER_CONTEXT_SCHEMA_VERSION:
        _fail("ownerContext.schemaVersion", f"must equal {OWNER_CONTEXT_SCHEMA_VERSION}")
    if owner["privacyClass"] != "DEVICE_LOCAL":
        _fail("ownerContext.privacyClass", "must equal DEVICE_LOCAL")
    if _utc(owner["asOf"], "ownerContext.asOf") > decision_at:
        _fail("ownerContext.asOf", "cannot be later than decisionAt")
    if owner["positionState"] not in ("HELD", "NOT_HELD", "UNKNOWN"):
        _fail("ownerContext.positionState", "unknown value")
    for field in ("positionRiskBand", "concentrationBand"):
        if owner[field] not in ("LOW", "MEDIUM", "HIGH", "CRITICAL", "UNKNOWN"):
            _fail(f"ownerContext.{field}", "unknown value")
    if owner["addPermission"] not in ("ALLOWED", "BLOCKED", "UNKNOWN"):
        _fail("ownerContext.addPermission", "unknown value")
    return owner


def _optional_exact_timestamp(value: Any, path: str, cutoff: datetime) -> None:
    if value is None:
        return
    if _utc(value, path) > cutoff:
        _fail(path, "cannot be later than informationCutoffAt")


def _validate_market_truth(value: Any, cutoff: datetime) -> Mapping[str, Any]:
    ref = _exact_mapping(value, _MARKET_TRUTH_KEYS, "marketTruth")
    if ref["status"] not in REFERENCE_STATUSES:
        _fail("marketTruth.status", "unknown reference status")
    _identifier(ref["schemaVersion"], "marketTruth.schemaVersion", nullable=True)
    _artifact_identifier(ref["snapshotId"], "marketTruth.snapshotId", nullable=True)
    _artifact_identifier(ref["observationId"], "marketTruth.observationId", nullable=True)
    _optional_exact_timestamp(ref["observedAt"], "marketTruth.observedAt", cutoff)
    _optional_exact_timestamp(ref["knownAt"], "marketTruth.knownAt", cutoff)
    _identifier(ref["policyId"], "marketTruth.policyId", nullable=True)
    _sha(ref["policySha256"], "marketTruth.policySha256", nullable=True)
    if ref["status"] == "AVAILABLE":
        required = (
            "schemaVersion",
            "snapshotId",
            "observationId",
            "observedAt",
            "knownAt",
            "policyId",
            "policySha256",
        )
        if any(ref[field] is None for field in required):
            _fail("marketTruth", "AVAILABLE requires complete artifact identity and PIT timestamps")
        if _utc(ref["observedAt"], "marketTruth.observedAt") > _utc(
            ref["knownAt"], "marketTruth.knownAt"
        ):
            _fail("marketTruth.knownAt", "cannot be earlier than observedAt")
    elif ref["status"] == "MISSING" and any(
        ref[field] is not None
        for field in ("snapshotId", "observationId", "observedAt", "knownAt")
    ):
        _fail("marketTruth", "MISSING cannot claim an artifact or observation")
    return ref


def _validate_prediction_ledger(value: Any, cutoff: datetime) -> Mapping[str, Any]:
    ref = _exact_mapping(value, _PREDICTION_LEDGER_KEYS, "predictionLedger")
    if ref["status"] not in REFERENCE_STATUSES:
        _fail("predictionLedger.status", "unknown reference status")
    _identifier(ref["schemaVersion"], "predictionLedger.schemaVersion", nullable=True)
    _artifact_identifier(ref["contextId"], "predictionLedger.contextId", nullable=True)
    if ref["mode"] not in ("FORWARD_LIVE", None):
        _fail("predictionLedger.mode", "must equal FORWARD_LIVE when present")
    _optional_exact_timestamp(ref["asOf"], "predictionLedger.asOf", cutoff)
    _identifier(ref["policyId"], "predictionLedger.policyId", nullable=True)
    _sha(ref["policySha256"], "predictionLedger.policySha256", nullable=True)
    if ref["status"] == "AVAILABLE" and any(
        ref[field] is None
        for field in ("schemaVersion", "contextId", "mode", "asOf", "policyId", "policySha256")
    ):
        _fail("predictionLedger", "AVAILABLE requires complete forward-live identity")
    if ref["status"] == "MISSING" and any(
        ref[field] is not None for field in ("contextId", "mode", "asOf")
    ):
        _fail("predictionLedger", "MISSING cannot claim a ledger context")
    return ref


def _validate_target(value: Any, path: str, *, invalidation: bool) -> None:
    keys = _INVALIDATION_KEYS if invalidation else _TARGET_KEYS
    item = _exact_mapping(value, keys, path)
    identity_key = "invalidationId" if invalidation else "targetId"
    _identifier(item[identity_key], f"{path}.{identity_key}")
    _canonical_decimal(item["value"], f"{path}.value")
    if item["unit"] not in ("PRICE", "PERCENT", "RATIO", "NONE"):
        _fail(f"{path}.unit", "unknown unit")
    _artifact_identifier(item["sourceRef"], f"{path}.sourceRef")


def _validate_sho(value: Any, cutoff: datetime) -> Mapping[str, Any]:
    ref = _exact_mapping(value, _SHO_KEYS, "sho")
    if ref["status"] not in REFERENCE_STATUSES:
        _fail("sho.status", "unknown reference status")
    _identifier(ref["schemaVersion"], "sho.schemaVersion", nullable=True)
    _artifact_identifier(ref["artifactId"], "sho.artifactId", nullable=True)
    _optional_exact_timestamp(ref["asOf"], "sho.asOf", cutoff)
    _identifier(ref["policyId"], "sho.policyId", nullable=True)
    _sha(ref["policySha256"], "sho.policySha256", nullable=True)
    if ref["state"] not in (*SHO_STATES, None):
        _fail("sho.state", "unknown SHO state")
    if ref["validationStatus"] not in (*SHO_VALIDATION_STATUSES, None):
        _fail("sho.validationStatus", "unknown validation status")
    primitive_ids = _canonical_strings(
        ref["primitiveFactorIds"],
        "sho.primitiveFactorIds",
        cap=MAX_PRIMITIVE_FACTOR_IDS,
    )
    targets = ref["targets"]
    if not isinstance(targets, list) or len(targets) > MAX_TARGETS:
        _fail("sho.targets", f"must be an array of at most {MAX_TARGETS}")
    for index, target in enumerate(targets):
        _validate_target(target, f"sho.targets[{index}]", invalidation=False)
    target_ids = [target["targetId"] for target in targets]
    if target_ids != sorted(set(target_ids)):
        _fail("sho.targets", "must be sorted and unique by targetId")
    if ref["invalidation"] is not None:
        _validate_target(ref["invalidation"], "sho.invalidation", invalidation=True)

    if ref["status"] == "AVAILABLE":
        if any(
            ref[field] is None
            for field in (
                "schemaVersion",
                "artifactId",
                "asOf",
                "policyId",
                "policySha256",
                "state",
                "validationStatus",
            )
        ):
            _fail("sho", "AVAILABLE requires complete artifact identity and state")
    elif ref["status"] == "MISSING":
        if any(
            ref[field] is not None
            for field in ("artifactId", "asOf", "state", "validationStatus")
        ) or primitive_ids or targets or ref["invalidation"] is not None:
            _fail("sho", "MISSING cannot claim state, factors, targets, or invalidation")
    return ref


def _validate_context_evidence(value: Any, cutoff: datetime) -> List[Mapping[str, Any]]:
    if not isinstance(value, list) or not 1 <= len(value) <= MAX_CONTEXT_EVIDENCE:
        _fail(
            "contextEvidence",
            f"must contain between 1 and {MAX_CONTEXT_EVIDENCE} bounded rows",
        )
    rows: List[Mapping[str, Any]] = []
    identities: List[Tuple[str, str]] = []
    for index, raw in enumerate(value):
        path = f"contextEvidence[{index}]"
        item = _exact_mapping(raw, _CONTEXT_KEYS, path)
        _artifact_identifier(item["evidenceRef"], f"{path}.evidenceRef")
        _identifier(item["primitiveFactorId"], f"{path}.primitiveFactorId")
        if item["sourceKind"] not in ("SCENARIO", "EVENT"):
            _fail(f"{path}.sourceKind", "must be SCENARIO or EVENT")
        if item["constraint"] not in CONTEXT_CONSTRAINTS:
            _fail(f"{path}.constraint", "context can only be NONE or WAIT_REQUIRED")
        if item["status"] not in CONTEXT_STATUSES:
            _fail(f"{path}.status", "unknown context status")
        if item["status"] != "ACTIVE" and item["constraint"] != "NONE":
            _fail(f"{path}.constraint", "non-active context cannot carry a constraint")
        if _utc(item["observedAt"], f"{path}.observedAt") > cutoff:
            _fail(f"{path}.observedAt", "cannot be later than informationCutoffAt")
        rows.append(item)
        identities.append((item["primitiveFactorId"], item["evidenceRef"]))
    if identities != sorted(set(identities)):
        _fail("contextEvidence", "must be sorted and unique by factor and evidence reference")
    return rows


def _validate_quality(value: Any) -> Mapping[str, Any]:
    quality = _exact_mapping(value, _QUALITY_KEYS, "quality")
    if quality["status"] not in QUALITY_STATUSES:
        _fail("quality.status", "unknown value")
    if quality["freshness"] not in FRESHNESS_STATUSES:
        _fail("quality.freshness", "unknown value")
    missing = _canonical_strings(
        quality["missingReasonCodes"], "quality.missingReasonCodes", cap=MAX_REASON_CODES
    )
    conflicts = _canonical_strings(
        quality["conflictReasonCodes"], "quality.conflictReasonCodes", cap=MAX_REASON_CODES
    )
    if quality["status"] == "COMPLETE" and (missing or conflicts):
        _fail("quality.status", "COMPLETE cannot carry missing or conflict reasons")
    if quality["status"] in ("PARTIAL", "MISSING") and not missing:
        _fail("quality.missingReasonCodes", "partial or missing quality requires a reason")
    if quality["status"] == "CONFLICT" and not conflicts:
        _fail("quality.conflictReasonCodes", "conflict quality requires a reason")
    return quality


def _validate_challenges(value: Any, decision_at: datetime) -> List[Mapping[str, Any]]:
    if not isinstance(value, list) or len(value) > MAX_CHALLENGE_EVIDENCE:
        _fail("challengeEvidence", f"must be an array of at most {MAX_CHALLENGE_EVIDENCE}")
    rows: List[Mapping[str, Any]] = []
    challenge_ids: List[str] = []
    for index, raw in enumerate(value):
        path = f"challengeEvidence[{index}]"
        item = _exact_mapping(raw, _CHALLENGE_KEYS, path)
        _identifier(item["challengeId"], f"{path}.challengeId")
        if item["sourceKind"] not in ("AI", "LEGACY"):
            _fail(f"{path}.sourceKind", "must be AI or LEGACY")
        if item["status"] not in ("AVAILABLE", "MISSING"):
            _fail(f"{path}.status", "must be AVAILABLE or MISSING")
        if _utc(item["asOf"], f"{path}.asOf") > decision_at:
            _fail(f"{path}.asOf", "cannot be later than decisionAt")
        if item["proposedAction"] not in (*PRIMARY_ACTIONS, None):
            _fail(f"{path}.proposedAction", "must use the closed five-action vocabulary")
        _canonical_strings(
            item["dissentReasonCodes"], f"{path}.dissentReasonCodes", cap=MAX_REASON_CODES
        )
        _canonical_strings(
            item["evidenceRefs"],
            f"{path}.evidenceRefs",
            cap=MAX_EVIDENCE_REFS,
            pattern=_SOURCE_REF_RE,
        )
        if item["status"] == "MISSING" and (
            item["proposedAction"] is not None
            or item["dissentReasonCodes"]
            or item["evidenceRefs"]
        ):
            _fail(path, "MISSING challenge cannot propose an action or claim evidence")
        rows.append(item)
        challenge_ids.append(item["challengeId"])
    if challenge_ids != sorted(set(challenge_ids)):
        _fail("challengeEvidence", "must be sorted and unique by challengeId")
    return rows


def _validate_calibration(value: Any) -> Mapping[str, Any]:
    calibration = _exact_mapping(value, _CALIBRATION_KEYS, "sevenSignCalibration")
    if calibration["status"] not in SEVEN_CALIBRATION_STATUSES:
        _fail("sevenSignCalibration.status", "unknown value")
    _artifact_identifier(
        calibration["artifactId"], "sevenSignCalibration.artifactId", nullable=True
    )
    _identifier(calibration["policyId"], "sevenSignCalibration.policyId", nullable=True)
    _sha(calibration["policySha256"], "sevenSignCalibration.policySha256", nullable=True)
    expectancy = calibration["expectancyBpsByLevel"]
    samples = calibration["sampleSizeByLevel"]
    if expectancy is not None and (
        not isinstance(expectancy, list)
        or len(expectancy) != 7
        or any(
            isinstance(item, bool) or not isinstance(item, int) or not -100_000 <= item <= 100_000
            for item in expectancy
        )
    ):
        _fail("sevenSignCalibration.expectancyBpsByLevel", "must be seven bounded integers or null")
    if samples is not None and (
        not isinstance(samples, list)
        or len(samples) != 7
        or any(
            isinstance(item, bool) or not isinstance(item, int) or not 0 <= item <= 1_000_000_000
            for item in samples
        )
    ):
        _fail("sevenSignCalibration.sampleSizeByLevel", "must be seven non-negative integers or null")
    if not isinstance(calibration["outOfSample"], bool):
        _fail("sevenSignCalibration.outOfSample", "must be boolean")
    if not isinstance(calibration["holdoutImmutable"], bool):
        _fail("sevenSignCalibration.holdoutImmutable", "must be boolean")
    if calibration["status"] == "VALIDATED" and any(
        calibration[field] is None
        for field in (
            "artifactId",
            "policyId",
            "policySha256",
            "expectancyBpsByLevel",
            "sampleSizeByLevel",
        )
    ):
        _fail("sevenSignCalibration", "VALIDATED requires complete calibration identity and arrays")
    if calibration["status"] == "MISSING" and (
        any(
            calibration[field] is not None
            for field in (
                "artifactId",
                "policyId",
                "policySha256",
                "expectancyBpsByLevel",
                "sampleSizeByLevel",
            )
        )
        or calibration["outOfSample"]
        or calibration["holdoutImmutable"]
    ):
        _fail("sevenSignCalibration", "MISSING cannot claim a calibration artifact")
    return calibration


def validate_single_decision_input_v2(value: Any) -> None:
    """Strictly validate the complete v2 authority envelope."""
    top = _exact_mapping(value, _INPUT_KEYS, "input")
    if top["schemaVersion"] != INPUT_SCHEMA_VERSION:
        _fail("schemaVersion", f"must equal {INPUT_SCHEMA_VERSION}")
    subject = _validate_subject(top["subject"])
    decision_at = _utc(top["decisionAt"], "decisionAt")
    cutoff = _utc(top["informationCutoffAt"], "informationCutoffAt")
    if cutoff > decision_at:
        _fail("informationCutoffAt", "cannot be later than decisionAt")
    _validate_canonical_authority_policy(top["authorityPolicy"], "authorityPolicy")
    _validate_market_truth(top["marketTruth"], cutoff)
    _validate_prediction_ledger(top["predictionLedger"], cutoff)
    _validate_sho(top["sho"], cutoff)
    try:
        validate_risk_kernel(top["riskKernel"])
    except RiskDisciplineValidationError as exc:
        raise SingleDecisionValidationError(f"riskKernel: {exc}") from exc
    risk = top["riskKernel"]
    risk_subject = risk["subject"]
    if (
        risk_subject["kind"] != subject["kind"]
        or risk_subject["instrumentId"] != subject["instrumentId"]
        or risk_subject["market"] != subject["market"]
    ):
        _fail("riskKernel.subject", "must match the authority subject")
    if risk["informationCutoffAt"] != top["informationCutoffAt"]:
        _fail("riskKernel.informationCutoffAt", "must equal the authority information cutoff")
    if _utc(risk["asOf"], "riskKernel.asOf") > decision_at:
        _fail("riskKernel.asOf", "cannot be later than decisionAt")
    _validate_context_evidence(top["contextEvidence"], cutoff)
    _validate_quality(top["quality"])
    _validate_owner(top["ownerContext"], decision_at)
    _validate_challenges(top["challengeEvidence"], decision_at)
    _validate_calibration(top["sevenSignCalibration"])
    _canonical_json_bytes(top)


def _latest_session_daily_authority(
    observation: Mapping[str, Any],
    subject: Mapping[str, Any],
    cutoff: str,
) -> bool:
    """The official close of the LATEST COMPLETED session is the current
    daily-authority fact for that market (owner spec 2026-08-22: SHO's daily
    thinking — a close stands until a newer session actually trades), so a
    DELAYED/STALE freshness label from wall-clock age does not by itself
    disqualify it. Any older session remains stale evidence.
    """
    market = str(subject.get("market") or "")
    clock_market = {"JP": argus_market_clock.JP_EQUITY,
                    "US": argus_market_clock.US_EQUITY}.get(market)
    if clock_market is None:
        return False
    try:
        cutoff_dt = datetime.strptime(
            cutoff, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        target = argus_market_clock.latest_completed_session_date(
            clock_market, cutoff_dt)
    except (TypeError, ValueError):
        return False
    observed = str(observation.get("observedAt") or "")[:10]
    return len(observed) == 10 and observed == target.isoformat()


def _market_truth_reference_from_artifact(
    artifact: Any,
    *,
    subject: Mapping[str, Any],
    cutoff: str,
) -> Dict[str, Any]:
    if not market_truth.is_builder_issued_decision_snapshot(artifact):
        _fail(
            "artifacts.marketTruthSnapshot",
            "must be an unmodified canonical-builder artifact",
        )
    valid, reason = market_truth.verify_decision_snapshot(artifact)
    if not valid:
        _fail("artifacts.marketTruthSnapshot", f"canonical verifier rejected artifact: {reason}")
    if artifact.get("decisionAt") != cutoff:
        _fail("artifacts.marketTruthSnapshot.decisionAt", "must equal informationCutoffAt")
    selections = [
        row for row in artifact.get("selections", [])
        if row.get("instrumentId") == subject["instrumentId"]
        and row.get("market") == subject["market"]
    ]
    if len(selections) != 1:
        _fail("artifacts.marketTruthSnapshot", "must contain exactly one selected subject fact")
    selection = selections[0]
    selected = selection.get("selected")
    observation = selected.get("observation") if isinstance(selected, Mapping) else None
    if not isinstance(observation, Mapping) or selected.get("selectionEligible") is not True:
        _fail("artifacts.marketTruthSnapshot", "subject has no authoritative selected observation")
    if selection.get("completeness") != market_truth.COMPLETE:
        _fail("artifacts.marketTruthSnapshot", "subject selection must be COMPLETE and FRESH")
    if selection.get("freshness") != market_truth.FRESH and not \
            _latest_session_daily_authority(observation, subject, cutoff):
        _fail("artifacts.marketTruthSnapshot", "subject selection must be COMPLETE and FRESH")
    return {
        "status": "AVAILABLE",
        "schemaVersion": artifact["schemaVersion"],
        "snapshotId": artifact["snapshotId"],
        "observationId": observation["observationId"],
        "observedAt": observation["observedAt"],
        "knownAt": observation["knownAt"],
        "policyId": market_truth.AUTHORITY_POLICY_ID,
        "policySha256": _canonical_sha(market_truth.repository_authority_policy()),
    }


def _prediction_reference_from_artifact(
    artifact: Any,
    *,
    market_ref: Mapping[str, Any],
    cutoff: str,
) -> Dict[str, Any]:
    if not decision_ledger.is_builder_issued_prediction_record(artifact):
        _fail(
            "artifacts.predictionLedgerRecord",
            "must be an unmodified canonical-builder artifact",
        )
    if not decision_ledger.verify_prediction_record_v2(artifact):
        _fail("artifacts.predictionLedgerRecord", "canonical verifier rejected artifact")
    if artifact.get("mode") != "forward_live":
        _fail("artifacts.predictionLedgerRecord.mode", "must equal forward_live")
    issued_at = artifact.get("issuedAt")
    if _utc(issued_at, "artifacts.predictionLedgerRecord.issuedAt") > _utc(
        cutoff, "informationCutoffAt"
    ):
        _fail("artifacts.predictionLedgerRecord.issuedAt", "cannot be after the cutoff")
    truth_ref = artifact.get("truthRef") or {}
    if truth_ref.get("snapshotId") != market_ref["snapshotId"] or \
            truth_ref.get("sourceId") != market_ref["observationId"] or \
            truth_ref.get("knownAt") != market_ref["knownAt"]:
        _fail("artifacts.predictionLedgerRecord.truthRef", "must bind the verified Market Truth fact")
    policy = artifact.get("evaluationPolicy")
    return {
        "status": "AVAILABLE",
        "schemaVersion": artifact["schemaVersion"],
        "contextId": artifact["id"],
        "mode": "FORWARD_LIVE",
        "asOf": issued_at,
        "policyId": policy["policyId"],
        "policySha256": _canonical_sha(policy),
    }


def _sho_reference_from_artifact(
    artifact: Any,
    *,
    subject: Mapping[str, Any],
    cutoff: str,
) -> Tuple[Dict[str, Any], bool]:
    if not sho_authority.is_builder_issued_reversal_artifact(artifact):
        _fail(
            "artifacts.shoArtifact",
            "must be an unmodified canonical-builder artifact",
        )
    try:
        admitted = sho_authority.validate_reversal_artifact(artifact)
    except (TypeError, ValueError) as exc:
        _fail("artifacts.shoArtifact", f"canonical verifier rejected artifact: {exc}")
    if admitted.get("informationCutoff") != cutoff:
        _fail("artifacts.shoArtifact.informationCutoff", "must equal informationCutoffAt")
    if admitted.get("analysisInstrument") != subject["instrumentId"]:
        _fail("artifacts.shoArtifact.analysisInstrument", "must equal the authority subject")
    axis = admitted["reversalAxis"]
    factors = admitted["evidence"]
    primitive_ids = sorted(
        f"sho.{re.sub(r'(?<!^)(?=[A-Z])', '_', name).lower()}"
        for name, row in factors.items()
        if isinstance(row, Mapping) and row.get("status") == "AVAILABLE"
    )
    registry_key = "|".join((
        admitted["artifactId"],
        sho_authority.SHO_REGISTRY_SHA256,
        admitted["canonicalRfcSha256"],
    ))
    buy_eligible = bool(
        axis.get("validationStatus") == "VALIDATED"
        and axis.get("state") in BUY_ELIGIBLE_SHO_STATES
        and registry_key in VERIFIED_SHO_BUY_ARTIFACTS
    )
    return ({
        "status": "AVAILABLE",
        "schemaVersion": admitted["schemaVersion"],
        "artifactId": admitted["artifactId"],
        "asOf": cutoff,
        "policyId": sho_authority.SHO_REGISTRY_VERSION,
        "policySha256": sho_authority.SHO_REGISTRY_SHA256,
        "state": axis["state"],
        "validationStatus": axis["validationStatus"],
        "primitiveFactorIds": primitive_ids,
        "targets": [],
        "invalidation": None,
    }, buy_eligible)


MISSING_MARKET_TRUTH_REFERENCE: Mapping[str, Any] = MappingProxyType({
    "status": "MISSING", "schemaVersion": None, "snapshotId": None,
    "observationId": None, "observedAt": None, "knownAt": None,
    "policyId": None, "policySha256": None,
})
MISSING_PREDICTION_LEDGER_REFERENCE: Mapping[str, Any] = MappingProxyType({
    "status": "MISSING", "schemaVersion": None, "contextId": None,
    "mode": None, "asOf": None, "policyId": None, "policySha256": None,
})
MISSING_SHO_REFERENCE: Mapping[str, Any] = MappingProxyType({
    "status": "MISSING", "schemaVersion": None, "artifactId": None,
    "asOf": None, "policyId": None, "policySha256": None, "state": None,
    "validationStatus": None, "primitiveFactorIds": (), "targets": (),
    "invalidation": None,
})


def _missing_reference(template: Mapping[str, Any]) -> Dict[str, Any]:
    out = dict(template)
    for key, value in out.items():
        if isinstance(value, tuple):
            out[key] = list(value)
    return out


def _degraded_market_truth_reference(artifact: Any, *, subject: Mapping[str, Any],
                                     cutoff: str) -> Optional[Dict[str, Any]]:
    """A verified snapshot whose subject selection is COMPLETE but no longer
    FRESH yields an honest STALE reference (identity preserved, authority
    withheld). Anything else stays MISSING."""
    if not market_truth.is_builder_issued_decision_snapshot(artifact):
        return None
    valid, _reason = market_truth.verify_decision_snapshot(artifact)
    if not valid or artifact.get("decisionAt") != cutoff:
        return None
    selections = [
        row for row in artifact.get("selections", [])
        if row.get("instrumentId") == subject.get("instrumentId")
        and row.get("market") == subject.get("market")
    ]
    if len(selections) != 1:
        return None
    selection = selections[0]
    selected = selection.get("selected")
    observation = selected.get("observation") if isinstance(selected, Mapping) else None
    if not isinstance(observation, Mapping) or selected.get("selectionEligible") is not True:
        return None
    if selection.get("completeness") != market_truth.COMPLETE:
        return None
    if _latest_session_daily_authority(observation, subject, cutoff):
        return None  # acceptable daily authority — the AVAILABLE path owns it
    return {
        "status": "STALE",
        "schemaVersion": artifact["schemaVersion"],
        "snapshotId": artifact["snapshotId"],
        "observationId": observation["observationId"],
        "observedAt": observation["observedAt"],
        "knownAt": observation["knownAt"],
        "policyId": market_truth.AUTHORITY_POLICY_ID,
        "policySha256": _canonical_sha(market_truth.repository_authority_policy()),
    }


def canonical_artifact_references(
    *,
    subject: Mapping[str, Any],
    cutoff: str,
    market_truth_artifact: Any = None,
    prediction_ledger_artifact: Any = None,
    sho_artifact: Any = None,
) -> Dict[str, Any]:
    """Serving-layer seam: the verified reference dicts a device-side SDA input
    may carry for these canonical artifacts.

    This is the backend half of the "canonical artifact resolver" boundary the
    TypeScript authority deliberately refuses to fake (its
    ``canonical_artifact_resolver_unavailable`` guard). Each reference is
    exactly what :func:`verify_decision_evidence` recomputes for the artifact;
    a verification failure fails closed to a MISSING (or, for a merely no
    longer FRESH market snapshot, STALE) reference with the failure reason
    preserved. No owner context is read and no action is produced here.
    """
    failures: Dict[str, str] = {}
    market_ref = _missing_reference(MISSING_MARKET_TRUTH_REFERENCE)
    if market_truth_artifact is not None:
        try:
            market_ref = dict(_market_truth_reference_from_artifact(
                market_truth_artifact, subject=subject, cutoff=cutoff))
        except ValueError as exc:
            degraded = _degraded_market_truth_reference(
                market_truth_artifact, subject=subject, cutoff=cutoff)
            if degraded is not None:
                market_ref = degraded
                failures["marketTruth"] = "subject_selection_not_fresh"
            else:
                failures["marketTruth"] = str(exc)
    prediction_ref = _missing_reference(MISSING_PREDICTION_LEDGER_REFERENCE)
    if prediction_ledger_artifact is not None:
        if market_ref.get("status") == "AVAILABLE":
            try:
                prediction_ref = dict(_prediction_reference_from_artifact(
                    prediction_ledger_artifact, market_ref=market_ref,
                    cutoff=cutoff))
            except ValueError as exc:
                failures["predictionLedger"] = str(exc)
        else:
            failures["predictionLedger"] = "market_truth_reference_unavailable"
    sho_ref = _missing_reference(MISSING_SHO_REFERENCE)
    sho_buy_eligible = False
    if sho_artifact is not None:
        try:
            built_sho, sho_buy_eligible = _sho_reference_from_artifact(
                sho_artifact, subject=subject, cutoff=cutoff)
            sho_ref = dict(built_sho)
        except ValueError as exc:
            failures["sho"] = str(exc)
    return {
        "marketTruth": market_ref,
        "predictionLedger": prediction_ref,
        "sho": sho_ref,
        "shoBuyEligible": bool(sho_buy_eligible),
        "verificationFailures": failures,
    }


def verify_decision_evidence(
    value: Any,
    *,
    market_truth_artifact: Any = None,
    prediction_ledger_artifact: Any = None,
    sho_artifact: Any = None,
) -> Mapping[str, Any]:
    """Resolve and verify every authority-relevant artifact exactly once.

    This boundary issues a runtime capability; a lookalike mapping, even with
    internally consistent hashes, is not executable by the final reducer.
    """
    if not isinstance(value, Mapping):
        _fail("input", "must be an object")
    if not is_verifier_issued_risk_kernel(value.get("riskKernel")):
        _fail("riskKernel", "must be an unmodified canonical-builder artifact")
    normalized = copy.deepcopy(dict(value))
    supplied_policy = normalized.get("authorityPolicy")
    if supplied_policy is None:
        normalized["authorityPolicy"] = dict(SINGLE_DECISION_AUTHORITY_V2_POLICY)
    elif dict(_validate_canonical_authority_policy(
            supplied_policy, "authorityPolicy")) != dict(SINGLE_DECISION_AUTHORITY_V2_POLICY):
        _fail("authorityPolicy", "does not match repository authority")
    validate_single_decision_input_v2(normalized)

    artifacts = (
        ("marketTruth", market_truth_artifact),
        ("predictionLedger", prediction_ledger_artifact),
        ("sho", sho_artifact),
    )
    for name, artifact in artifacts:
        status = normalized[name]["status"]
        if status == "AVAILABLE" and artifact is None:
            _fail(f"artifacts.{name}", "backing canonical artifact is required")
        if status != "AVAILABLE" and artifact is not None:
            _fail(f"artifacts.{name}", "cannot back a non-AVAILABLE reference")

    verification: Dict[str, Any] = {
        "schemaVersion": VERIFIED_EVIDENCE_SCHEMA_VERSION,
        "authorityPolicy": dict(SINGLE_DECISION_AUTHORITY_V2_POLICY),
        "marketTruth": None,
        "predictionLedger": None,
        "sho": None,
        "riskKernelId": normalized["riskKernel"]["riskKernelId"],
    }
    sho_buy_eligible = False
    if market_truth_artifact is not None:
        expected_market = _market_truth_reference_from_artifact(
            market_truth_artifact,
            subject=normalized["subject"],
            cutoff=normalized["informationCutoffAt"],
        )
        if normalized["marketTruth"] != expected_market:
            _fail("marketTruth", "does not exactly match the verified canonical artifact")
        verification["marketTruth"] = expected_market["snapshotId"]
    if prediction_ledger_artifact is not None:
        expected_prediction = _prediction_reference_from_artifact(
            prediction_ledger_artifact,
            market_ref=normalized["marketTruth"],
            cutoff=normalized["informationCutoffAt"],
        )
        if normalized["predictionLedger"] != expected_prediction:
            _fail("predictionLedger", "does not exactly match the verified canonical artifact")
        verification["predictionLedger"] = expected_prediction["contextId"]
    if sho_artifact is not None:
        expected_sho, sho_buy_eligible = _sho_reference_from_artifact(
            sho_artifact,
            subject=normalized["subject"],
            cutoff=normalized["informationCutoffAt"],
        )
        if normalized["sho"] != expected_sho:
            _fail("sho", "does not exactly match the verified canonical artifact")
        verification["sho"] = expected_sho["artifactId"]

    if all(normalized[name]["status"] == "AVAILABLE" for name, _ in artifacts):
        if normalized["quality"] != {
            "status": "COMPLETE",
            "freshness": "FRESH",
            "missingReasonCodes": [],
            "conflictReasonCodes": [],
        }:
            _fail("quality", "must be derived as COMPLETE/FRESH from verified artifacts")

    identity_body = {"input": normalized, "verification": verification}
    bundle_id = _hash_id("vdeb-", identity_body)
    bundle = _VerifiedDecisionEvidenceBundle(copy.deepcopy(normalized))
    bundle._authority_seal = _BUNDLE_SEAL
    bundle._bundle_id = bundle_id
    bundle._sho_buy_eligible = sho_buy_eligible
    bundle._body_digest = _verified_bundle_digest(bundle)
    return bundle


def _unique_bounded(items: Iterable[str], cap: int) -> List[str]:
    return sorted(set(items))[:cap]


def _reference_reason(prefix: str, status: str) -> Tuple[List[str], List[str]]:
    if status == "AVAILABLE":
        return [], []
    if status == "CONFLICT":
        return [], [f"{prefix}_conflict"]
    return [f"{prefix}_{status.lower()}"], []


def _owner_is_unknown(owner: Mapping[str, Any]) -> bool:
    return any(
        owner[field] == "UNKNOWN"
        for field in (
            "positionState",
            "positionRiskBand",
            "concentrationBand",
            "addPermission",
        )
    )


def _select_primary_action(
    top: Mapping[str, Any], *, data_gated: bool, sho_buy_eligible: bool
) -> str:
    owner = top["ownerContext"]
    held = owner["positionState"] == "HELD"
    if data_gated:
        return "WAIT"

    constraint = top["riskKernel"]["constraint"]
    if constraint == "EXIT_RISK":
        return "EXIT" if held else "WAIT"
    if constraint == "REDUCE_RISK":
        return "REDUCE" if held else "WAIT"
    if constraint == "WAIT_REQUIRED":
        return "WAIT"
    if constraint == "BLOCK_BUY":
        return "HOLD" if held else "WAIT"
    sho = top["sho"]
    buy_ready = (
        sho["validationStatus"] == "VALIDATED"
        and sho_buy_eligible
        and sho["state"] in BUY_ELIGIBLE_SHO_STATES
        and owner["addPermission"] == "ALLOWED"
    )
    if buy_ready:
        return "BUY"
    return "HOLD" if held else "WAIT"


def _seven_candidate(action: str, top: Mapping[str, Any], *, data_gated: bool) -> Optional[int]:
    if data_gated:
        return None
    if action == "EXIT":
        return 1
    if action == "REDUCE":
        return 2
    if action == "WAIT":
        defensive = top["riskKernel"]["constraint"] in (
            "BLOCK_BUY",
            "WAIT_REQUIRED",
            "REDUCE_RISK",
            "EXIT_RISK",
        )
        return 3 if defensive else 4
    if action == "HOLD":
        return 4
    state = top["sho"]["state"]
    if state == "CONFIRMED_ADVANCE":
        return 7
    if state in ("TECHNICAL_REBOUND", "RECOVERY_TEST"):
        return 6
    return 5


def _seven_sign_projection(
    action: str,
    top: Mapping[str, Any],
    *,
    data_gated: bool,
) -> Dict[str, Any]:
    calibration = top["sevenSignCalibration"]
    candidate = _seven_candidate(action, top, data_gated=data_gated)
    reasons: List[str] = []
    status = "DATA_GATED"
    production: Optional[int] = None

    if data_gated:
        reasons.append("decision_data_gated")
    elif calibration["status"] == "SHADOW":
        status = "SHADOW"
        reasons.append("calibration_shadow")
    elif calibration["status"] != "VALIDATED":
        reasons.append(f"calibration_{calibration['status'].lower()}")
    else:
        expectancy = calibration["expectancyBpsByLevel"]
        samples = calibration["sampleSizeByLevel"]
        monotonic = all(
            expectancy[index] <= expectancy[index + 1] for index in range(6)
        )
        adequate = all(sample >= MIN_SEVEN_SIGN_SAMPLE_SIZE for sample in samples)
        if not monotonic:
            reasons.append("calibration_non_monotonic")
        if not adequate:
            reasons.append("calibration_sample_insufficient")
        if not calibration["outOfSample"]:
            reasons.append("calibration_not_out_of_sample")
        if not calibration["holdoutImmutable"]:
            reasons.append("calibration_holdout_mutable")
        calibration_key = "|".join((
            calibration["artifactId"], calibration["policyId"],
            calibration["policySha256"],
        ))
        if calibration_key not in VERIFIED_SEVEN_SIGN_CALIBRATIONS:
            reasons.append("calibration_artifact_not_verified")
        if not reasons:
            status = "PRODUCTION"
            production = candidate

    return {
        "schemaVersion": SEVEN_SIGN_SCHEMA_VERSION,
        "status": status,
        "candidateLevel": candidate,
        "productionLevel": production,
        "policyId": calibration["policyId"],
        "policySha256": calibration["policySha256"],
        "calibrationArtifactId": calibration["artifactId"],
        "reasonCodes": sorted(set(reasons)),
    }


def _position_guidance(action: str) -> str:
    return {
        "BUY": "ENTER_OR_ADD",
        "HOLD": "MAINTAIN",
        "WAIT": "NO_ACTION",
        "REDUCE": "REDUCE_EXPOSURE",
        "EXIT": "EXIT_POSITION",
    }[action]


def _result_from_valid_input(top: _VerifiedDecisionEvidenceBundle) -> Dict[str, Any]:
    missing: List[str] = list(top["quality"]["missingReasonCodes"])
    conflicts: List[str] = list(top["quality"]["conflictReasonCodes"])
    for name, ref in (
        ("market_truth", top["marketTruth"]),
        ("prediction_ledger", top["predictionLedger"]),
        ("sho", top["sho"]),
    ):
        ref_missing, ref_conflicts = _reference_reason(name, ref["status"])
        missing.extend(ref_missing)
        conflicts.extend(ref_conflicts)
    missing.extend(top["riskKernel"]["missingReasonCodes"])
    conflicts.extend(top["riskKernel"]["conflictReasonCodes"])
    owner_unknown = _owner_is_unknown(top["ownerContext"])
    if owner_unknown:
        missing.append("owner_context_unknown")
    if top["quality"]["status"] != "COMPLETE":
        missing.append(f"quality_{top['quality']['status'].lower()}")
    if top["quality"]["freshness"] != "FRESH":
        missing.append(f"freshness_{top['quality']['freshness'].lower()}")

    data_gated = bool(
        missing
        or conflicts
        or top["riskKernel"]["status"] != "READY"
        or top["marketTruth"]["status"] != "AVAILABLE"
        or top["predictionLedger"]["status"] != "AVAILABLE"
        or top["sho"]["status"] != "AVAILABLE"
        or owner_unknown
    )
    action = _select_primary_action(
        top,
        data_gated=data_gated,
        sho_buy_eligible=top._sho_buy_eligible,
    )
    base_confidence = {
        "BUY": 7_000,
        "HOLD": 6_000,
        "WAIT": 4_500,
        "REDUCE": 7_000,
        "EXIT": 8_000,
    }[action]
    confidence = min(base_confidence, top["riskKernel"]["confidenceCapBps"])
    if data_gated:
        confidence = min(confidence, 2_500)

    risk_refs = [
        evidence_ref
        for factor in top["riskKernel"]["primitiveFactors"]
        for evidence_ref in factor["evidenceRefs"]
    ]
    context_refs = [row["evidenceRef"] for row in top["contextEvidence"]]
    challenge_refs = [
        evidence_ref
        for challenge in top["challengeEvidence"]
        for evidence_ref in challenge["evidenceRefs"]
    ]
    target_refs = [target["sourceRef"] for target in top["sho"]["targets"]]
    if top["sho"]["invalidation"] is not None:
        target_refs.append(top["sho"]["invalidation"]["sourceRef"])

    dissent: List[str] = []
    for row in top["contextEvidence"]:
        if row["status"] == "MISSING":
            dissent.append(f"context_missing_advisory.{row['primitiveFactorId']}")
        elif row["status"] == "CONFLICT":
            dissent.append(f"context_conflict_advisory.{row['primitiveFactorId']}")
        if row["constraint"] != "NONE":
            dissent.append("context_constraint_advisory_only")
    for challenge in top["challengeEvidence"]:
        dissent.extend(challenge["dissentReasonCodes"])
        if challenge["proposedAction"] is not None:
            dissent.append(f"{challenge['sourceKind'].lower()}_proposed_action_ignored")

    primitive_ids = _unique_bounded(
        [factor["primitiveFactorId"] for factor in top["riskKernel"]["primitiveFactors"]]
        + list(top["sho"]["primitiveFactorIds"])
        + [row["primitiveFactorId"] for row in top["contextEvidence"]],
        MAX_PRIMITIVE_FACTOR_IDS,
    )
    missing = _unique_bounded(missing, MAX_REASON_CODES)
    conflicts = _unique_bounded(conflicts, MAX_REASON_CODES)
    next_review = _unique_bounded(
        [f"resolve.{code}" for code in missing + conflicts]
        + (["risk_reassessment"] if top["riskKernel"]["constraint"] != "NONE" else [])
        + (["sho_revalidation"] if top["sho"]["validationStatus"] != "VALIDATED" else []),
        MAX_REASON_CODES,
    )

    body: Dict[str, Any] = {
        "schemaVersion": RESULT_SCHEMA_VERSION,
        "verifiedEvidenceBundleId": top._bundle_id,
        "status": "DATA_GATED" if data_gated else "EVALUATED",
        "subject": copy.deepcopy(top["subject"]),
        "issuedAt": top["decisionAt"],
        "informationCutoffAt": top["informationCutoffAt"],
        "primaryAction": action,
        "confidence": {"valueBps": confidence, "status": "BOUNDED"},
        "guidance": {
            "position": _position_guidance(action),
            "riskConstraint": top["riskKernel"]["constraint"],
        },
        "targets": copy.deepcopy(top["sho"]["targets"]),
        "invalidation": copy.deepcopy(top["sho"]["invalidation"]),
        "nextReviewConditionCodes": next_review,
        "freshness": top["quality"]["freshness"],
        "missingReasonCodes": missing,
        "conflictReasonCodes": conflicts,
        "dissentReasonCodes": _unique_bounded(dissent, MAX_REASON_CODES),
        "evidenceRefs": _unique_bounded(
            risk_refs + context_refs + challenge_refs + target_refs,
            MAX_EVIDENCE_REFS,
        ),
        "primitiveFactorIds": primitive_ids,
        "identities": {
            "authorityPolicyId": top["authorityPolicy"]["policyId"],
            "authorityPolicySha256": top["authorityPolicy"]["policySha256"],
            "marketTruth": {
                "status": top["marketTruth"]["status"],
                "snapshotId": top["marketTruth"]["snapshotId"],
                "observationId": top["marketTruth"]["observationId"],
            },
            "predictionLedger": {
                "status": top["predictionLedger"]["status"],
                "contextId": top["predictionLedger"]["contextId"],
            },
            "sho": {
                "status": top["sho"]["status"],
                "artifactId": top["sho"]["artifactId"],
            },
            "risk": {
                "status": top["riskKernel"]["status"],
                "riskKernelId": top["riskKernel"]["riskKernelId"],
            },
        },
        "sevenSign": _seven_sign_projection(action, top, data_gated=data_gated),
    }
    result = _VerifiedSingleDecisionResult(
        {"decisionId": compute_single_decision_id(body), **body}
    )
    result._authority_seal = _RESULT_SEAL
    result._bundle_id = top._bundle_id
    result._body_digest = _verified_bundle_digest(result)
    validate_single_decision_result_v2(result)
    return result


def _invalid_result() -> Dict[str, Any]:
    body: Dict[str, Any] = {
        "schemaVersion": RESULT_SCHEMA_VERSION,
        "verifiedEvidenceBundleId": None,
        "status": "DATA_GATED",
        "subject": None,
        "issuedAt": None,
        "informationCutoffAt": None,
        "primaryAction": "WAIT",
        "confidence": {"valueBps": 0, "status": "BOUNDED"},
        "guidance": {"position": "NO_ACTION", "riskConstraint": "WAIT_REQUIRED"},
        "targets": [],
        "invalidation": None,
        "nextReviewConditionCodes": ["resolve.input_invalid"],
        "freshness": "UNKNOWN",
        "missingReasonCodes": ["input_invalid"],
        "conflictReasonCodes": [],
        "dissentReasonCodes": [],
        "evidenceRefs": [],
        "primitiveFactorIds": [],
        "identities": {
            "authorityPolicyId": None,
            "authorityPolicySha256": None,
            "marketTruth": {"status": "MISSING", "snapshotId": None, "observationId": None},
            "predictionLedger": {"status": "MISSING", "contextId": None},
            "sho": {"status": "MISSING", "artifactId": None},
            "risk": {"status": "DATA_GATED", "riskKernelId": None},
        },
        "sevenSign": {
            "schemaVersion": SEVEN_SIGN_SCHEMA_VERSION,
            "status": "DATA_GATED",
            "candidateLevel": None,
            "productionLevel": None,
            "policyId": None,
            "policySha256": None,
            "calibrationArtifactId": None,
            "reasonCodes": ["decision_data_gated"],
        },
    }
    return {"decisionId": compute_single_decision_id(body), **body}


def evaluate_single_decision_authority(value: Any) -> Dict[str, Any]:
    """Evaluate only a verifier-issued bundle; raw mappings always fail closed."""
    if not _bundle_is_current(value):
        return copy.deepcopy(_invalid_result())
    try:
        validate_single_decision_input_v2(value)
    except (SingleDecisionValidationError, RiskDisciplineValidationError, TypeError, ValueError):
        return copy.deepcopy(_invalid_result())
    return _result_from_valid_input(value)


def _validate_result_subject(value: Any) -> None:
    if value is not None:
        _validate_subject(value, "result.subject")


def _validate_result_identifiers(value: Any, path: str, *, cap: int) -> None:
    _canonical_strings(value, path, cap=cap, pattern=_SOURCE_REF_RE)


def validate_single_decision_result_v2(value: Any) -> None:
    """Validate the v2 result and its deterministic content address."""
    result = _exact_mapping(value, _RESULT_KEYS, "result")
    if result["schemaVersion"] != RESULT_SCHEMA_VERSION:
        _fail("result.schemaVersion", f"must equal {RESULT_SCHEMA_VERSION}")
    if not isinstance(result["decisionId"], str) or not _DECISION_ID_RE.fullmatch(result["decisionId"]):
        _fail("result.decisionId", "malformed content address")
    bundle_id = result["verifiedEvidenceBundleId"]
    if bundle_id is not None and (
        not isinstance(bundle_id, str) or not _BUNDLE_ID_RE.fullmatch(bundle_id)
    ):
        _fail("result.verifiedEvidenceBundleId", "malformed verified bundle identity")
    if result["status"] not in ("EVALUATED", "DATA_GATED"):
        _fail("result.status", "unknown result status")
    _validate_result_subject(result["subject"])
    if result["issuedAt"] is not None:
        issued = _utc(result["issuedAt"], "result.issuedAt")
        cutoff = _utc(result["informationCutoffAt"], "result.informationCutoffAt")
        if cutoff > issued:
            _fail("result.informationCutoffAt", "cannot be later than issuedAt")
    elif result["informationCutoffAt"] is not None:
        _fail("result.informationCutoffAt", "must be null when issuedAt is null")
    if result["primaryAction"] not in PRIMARY_ACTIONS:
        _fail("result.primaryAction", "unknown action")
    if result["status"] == "DATA_GATED" and result["primaryAction"] != "WAIT":
        _fail("result.primaryAction", "DATA_GATED must fail closed to WAIT")
    confidence = _exact_mapping(result["confidence"], _CONFIDENCE_KEYS, "result.confidence")
    _bps(confidence["valueBps"], "result.confidence.valueBps")
    if confidence["status"] != "BOUNDED":
        _fail("result.confidence.status", "must equal BOUNDED")
    guidance = _exact_mapping(result["guidance"], _GUIDANCE_KEYS, "result.guidance")
    expected_guidance = _position_guidance(result["primaryAction"])
    if guidance["position"] != expected_guidance:
        _fail("result.guidance.position", "is inconsistent with primaryAction")
    if guidance["riskConstraint"] not in (
        "NONE",
        "BLOCK_BUY",
        "WAIT_REQUIRED",
        "REDUCE_RISK",
        "EXIT_RISK",
    ):
        _fail("result.guidance.riskConstraint", "unknown constraint")
    if not isinstance(result["targets"], list) or len(result["targets"]) > MAX_TARGETS:
        _fail("result.targets", f"must contain at most {MAX_TARGETS}")
    for index, target in enumerate(result["targets"]):
        _validate_target(target, f"result.targets[{index}]", invalidation=False)
    if result["invalidation"] is not None:
        _validate_target(result["invalidation"], "result.invalidation", invalidation=True)
    for field in (
        "nextReviewConditionCodes",
        "missingReasonCodes",
        "conflictReasonCodes",
        "dissentReasonCodes",
        "primitiveFactorIds",
    ):
        _canonical_strings(result[field], f"result.{field}", cap=MAX_PRIMITIVE_FACTOR_IDS)
    _validate_result_identifiers(result["evidenceRefs"], "result.evidenceRefs", cap=MAX_EVIDENCE_REFS)
    if result["freshness"] not in FRESHNESS_STATUSES:
        _fail("result.freshness", "unknown freshness")

    identities = _exact_mapping(result["identities"], _IDENTITIES_KEYS, "result.identities")
    _identifier(identities["authorityPolicyId"], "result.identities.authorityPolicyId", nullable=True)
    _sha(
        identities["authorityPolicySha256"],
        "result.identities.authorityPolicySha256",
        nullable=True,
    )
    if result["status"] == "EVALUATED" and (
        bundle_id is None
        or identities["authorityPolicyId"] != AUTHORITY_POLICY_ID
        or identities["authorityPolicySha256"] != AUTHORITY_POLICY_SHA256
    ):
        _fail("result.identities", "EVALUATED result must bind verified canonical authority")
    if bundle_id is None and result["subject"] is not None:
        _fail("result.verifiedEvidenceBundleId", "non-invalid result requires verified evidence")
    market = _exact_mapping(
        identities["marketTruth"], _MARKET_IDENTITY_KEYS, "result.identities.marketTruth"
    )
    prediction = _exact_mapping(
        identities["predictionLedger"],
        _PREDICTION_IDENTITY_KEYS,
        "result.identities.predictionLedger",
    )
    sho = _exact_mapping(identities["sho"], _SHO_IDENTITY_KEYS, "result.identities.sho")
    risk = _exact_mapping(identities["risk"], _RISK_IDENTITY_KEYS, "result.identities.risk")
    if market["status"] not in REFERENCE_STATUSES:
        _fail("result.identities.marketTruth.status", "unknown reference status")
    _artifact_identifier(market["snapshotId"], "result.identities.marketTruth.snapshotId", nullable=True)
    _artifact_identifier(
        market["observationId"], "result.identities.marketTruth.observationId", nullable=True
    )
    if prediction["status"] not in REFERENCE_STATUSES:
        _fail("result.identities.predictionLedger.status", "unknown reference status")
    _artifact_identifier(
        prediction["contextId"], "result.identities.predictionLedger.contextId", nullable=True
    )
    if sho["status"] not in REFERENCE_STATUSES:
        _fail("result.identities.sho.status", "unknown reference status")
    _artifact_identifier(sho["artifactId"], "result.identities.sho.artifactId", nullable=True)
    if risk["status"] not in ("READY", "DATA_GATED"):
        _fail("result.identities.risk.status", "unknown risk status")
    if risk["riskKernelId"] is not None and (
        not isinstance(risk["riskKernelId"], str)
        or not re.fullmatch(r"rk-[0-9a-f]{64}", risk["riskKernelId"])
    ):
        _fail("result.identities.risk.riskKernelId", "malformed risk content address")

    seven = _exact_mapping(result["sevenSign"], _SEVEN_RESULT_KEYS, "result.sevenSign")
    if seven["schemaVersion"] != SEVEN_SIGN_SCHEMA_VERSION:
        _fail("result.sevenSign.schemaVersion", f"must equal {SEVEN_SIGN_SCHEMA_VERSION}")
    if seven["status"] not in ("PRODUCTION", "SHADOW", "DATA_GATED"):
        _fail("result.sevenSign.status", "unknown value")
    for field in ("candidateLevel", "productionLevel"):
        level = seven[field]
        if level is not None and (isinstance(level, bool) or not isinstance(level, int) or not 1 <= level <= 7):
            _fail(f"result.sevenSign.{field}", "must be an integer 1 through 7 or null")
    if seven["status"] != "PRODUCTION" and seven["productionLevel"] is not None:
        _fail("result.sevenSign.productionLevel", "must be null outside PRODUCTION")
    if seven["status"] == "PRODUCTION" and seven["productionLevel"] != seven["candidateLevel"]:
        _fail("result.sevenSign.productionLevel", "must equal the candidate in PRODUCTION")
    allowed_levels = {
        "BUY": {5, 6, 7},
        "HOLD": {4},
        "WAIT": {3, 4},
        "REDUCE": {2},
        "EXIT": {1},
    }[result["primaryAction"]]
    if seven["candidateLevel"] is not None and seven["candidateLevel"] not in allowed_levels:
        _fail("result.sevenSign.candidateLevel", "is semantically inconsistent with primaryAction")
    _identifier(seven["policyId"], "result.sevenSign.policyId", nullable=True)
    _sha(seven["policySha256"], "result.sevenSign.policySha256", nullable=True)
    _artifact_identifier(
        seven["calibrationArtifactId"],
        "result.sevenSign.calibrationArtifactId",
        nullable=True,
    )
    _canonical_strings(seven["reasonCodes"], "result.sevenSign.reasonCodes", cap=MAX_REASON_CODES)
    expected_id = compute_single_decision_id(result)
    if result["decisionId"] != expected_id:
        _fail("result.decisionId", "does not match the canonical result body")


def build_data_gated_input_v2(
    *,
    subject: Mapping[str, Any],
    decision_at: str,
    information_cutoff_at: str,
    authority_policy: Optional[Mapping[str, Any]] = None,
    owner_context: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Build the minimum honest input when exact upstream artifacts are absent."""
    _validate_subject(subject)
    decision_time = _utc(decision_at, "decisionAt")
    cutoff = _utc(information_cutoff_at, "informationCutoffAt")
    if cutoff > decision_time:
        _fail("informationCutoffAt", "cannot be later than decisionAt")
    policy = _validate_canonical_authority_policy(
        authority_policy or SINGLE_DECISION_AUTHORITY_V2_POLICY,
        "authorityPolicy",
    )
    policy_value = {
        "policyId": policy["policyId"],
        "policySha256": policy["policySha256"],
    }
    if owner_context is None:
        owner_context = {
            "schemaVersion": OWNER_CONTEXT_SCHEMA_VERSION,
            "privacyClass": "DEVICE_LOCAL",
            "asOf": decision_at,
            "positionState": "UNKNOWN",
            "positionRiskBand": "UNKNOWN",
            "concentrationBand": "UNKNOWN",
            "addPermission": "UNKNOWN",
        }
    _validate_owner(owner_context, decision_time)
    risk_subject = {
        "kind": subject["kind"],
        "instrumentId": subject["instrumentId"],
        "market": subject["market"],
    }
    risk_kernel = build_risk_kernel(
        {
            "schemaVersion": "argus-risk-discipline-input-v1",
            "subject": risk_subject,
            "asOf": decision_at,
            "informationCutoffAt": information_cutoff_at,
            "policy": copy.deepcopy(policy_value),
            "contributions": [
                {
                    "evidenceRef": "discipline:risk-missing",
                    "primitiveFactorId": "risk.required_evidence",
                    "sourceKind": "DISCIPLINE",
                    "constraint": "NONE",
                    "status": "MISSING",
                    "severity": "UNKNOWN",
                    "confidenceCapBps": 2500,
                    "observedAt": information_cutoff_at,
                }
            ],
        }
    )
    value: Dict[str, Any] = {
        "schemaVersion": INPUT_SCHEMA_VERSION,
        "subject": copy.deepcopy(subject),
        "decisionAt": decision_at,
        "informationCutoffAt": information_cutoff_at,
        "authorityPolicy": copy.deepcopy(policy_value),
        "marketTruth": {
            "status": "MISSING",
            "schemaVersion": None,
            "snapshotId": None,
            "observationId": None,
            "observedAt": None,
            "knownAt": None,
            "policyId": None,
            "policySha256": None,
        },
        "predictionLedger": {
            "status": "MISSING",
            "schemaVersion": None,
            "contextId": None,
            "mode": None,
            "asOf": None,
            "policyId": None,
            "policySha256": None,
        },
        "sho": {
            "status": "MISSING",
            "schemaVersion": None,
            "artifactId": None,
            "asOf": None,
            "policyId": None,
            "policySha256": None,
            "state": None,
            "validationStatus": None,
            "primitiveFactorIds": [],
            "targets": [],
            "invalidation": None,
        },
        "riskKernel": risk_kernel,
        "contextEvidence": [
            {
                "evidenceRef": "context:missing",
                "primitiveFactorId": "context.required_evidence",
                "sourceKind": "SCENARIO",
                "constraint": "NONE",
                "status": "MISSING",
                "observedAt": information_cutoff_at,
            }
        ],
        "quality": {
            "status": "MISSING",
            "freshness": "UNKNOWN",
            "missingReasonCodes": [
                "market_truth_missing",
                "prediction_ledger_missing",
                "risk_evidence_missing",
                "scenario_event_missing",
                "sho_evidence_missing",
            ],
            "conflictReasonCodes": [],
        },
        "ownerContext": copy.deepcopy(owner_context),
        "challengeEvidence": [],
        "sevenSignCalibration": {
            "status": "MISSING",
            "artifactId": None,
            "policyId": None,
            "policySha256": None,
            "expectancyBpsByLevel": None,
            "sampleSizeByLevel": None,
            "outOfSample": False,
            "holdoutImmutable": False,
        },
    }
    return verify_decision_evidence(value)


def build_prediction_ledger_v2_adapter(result: Any) -> Dict[str, Any]:
    """Return one append-only v2 binding row; existing ledger rows are untouched."""
    if not _result_is_current(result):
        _fail("result", "must come from the verified SDA admission path")
    validate_single_decision_result_v2(result)
    identities = result["identities"]
    seven = result["sevenSign"]
    body: Dict[str, Any] = {
        "schemaVersion": LEDGER_ADAPTER_SCHEMA_VERSION,
        "recordType": "canonical_decision_binding",
        "appendMode": "APPEND_ONLY",
        "mutatesExistingRows": False,
        "decisionId": result["decisionId"],
        "verifiedEvidenceBundleId": result["verifiedEvidenceBundleId"],
        "issuedAt": result["issuedAt"],
        "informationCutoffAt": result["informationCutoffAt"],
        "subject": copy.deepcopy(result["subject"]),
        "authorityPolicyRef": {
            "policyId": identities["authorityPolicyId"],
            "policySha256": identities["authorityPolicySha256"],
        },
        "marketTruthRef": copy.deepcopy(identities["marketTruth"]),
        "predictionLedgerRef": copy.deepcopy(identities["predictionLedger"]),
        "shoRef": copy.deepcopy(identities["sho"]),
        "riskRef": copy.deepcopy(identities["risk"]),
        "singleDecisionRef": {
            "schemaVersion": result["schemaVersion"],
            "decisionId": result["decisionId"],
        },
        "sevenSignRef": {
            "schemaVersion": seven["schemaVersion"],
            "status": seven["status"],
            "policyId": seven["policyId"],
            "policySha256": seven["policySha256"],
            "calibrationArtifactId": seven["calibrationArtifactId"],
            "candidateLevel": seven["candidateLevel"],
            "productionLevel": seven["productionLevel"],
        },
        "primaryAction": result["primaryAction"],
        "confidenceBps": result["confidence"]["valueBps"],
        "targets": copy.deepcopy(result["targets"]),
        "invalidation": copy.deepcopy(result["invalidation"]),
        "missingReasonCodes": copy.deepcopy(result["missingReasonCodes"]),
        "conflictReasonCodes": copy.deepcopy(result["conflictReasonCodes"]),
        "dissentReasonCodes": copy.deepcopy(result["dissentReasonCodes"]),
        "evidenceRefs": copy.deepcopy(result["evidenceRefs"]),
        "primitiveFactorIds": copy.deepcopy(result["primitiveFactorIds"]),
    }
    adapter = {"adapterId": compute_prediction_adapter_id(body), **body}
    if set(adapter) != _ADAPTER_KEYS or not _ADAPTER_ID_RE.fullmatch(adapter["adapterId"]):
        _fail("adapter", "internal adapter contract error")
    return copy.deepcopy(adapter)


__all__ = [
    "AUTHORITY_POLICY_ID",
    "AUTHORITY_POLICY_SHA256",
    "INPUT_SCHEMA_VERSION",
    "LEDGER_ADAPTER_SCHEMA_VERSION",
    "OWNER_CONTEXT_SCHEMA_VERSION",
    "PRIMARY_ACTIONS",
    "RESULT_SCHEMA_VERSION",
    "SEVEN_SIGN_SCHEMA_VERSION",
    "SINGLE_DECISION_AUTHORITY_V2_POLICY",
    "VERIFIED_EVIDENCE_SCHEMA_VERSION",
    "MISSING_MARKET_TRUTH_REFERENCE",
    "MISSING_PREDICTION_LEDGER_REFERENCE",
    "MISSING_SHO_REFERENCE",
    "SingleDecisionValidationError",
    "build_data_gated_input_v2",
    "canonical_artifact_references",
    "build_prediction_ledger_v2_adapter",
    "compute_prediction_adapter_id",
    "compute_single_decision_id",
    "evaluate_single_decision_authority",
    "verify_decision_evidence",
    "validate_single_decision_input_v2",
    "validate_single_decision_result_v2",
]
