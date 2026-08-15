"""Deterministic, non-authoritative exact cold-recovery proof evaluator.

This module evaluates a *pinned* package of immutable verifier output.  It does
not fetch objects, perform cryptography, replay state, select authority, read
the clock, inspect the environment, or change recovery behavior.  Generic
health and raw caller booleans are deliberately outside the evidence model.

``VerifiedRecoveryEvidence`` has no public value-taking constructor.  A later
trusted verifier adapter may use the module-private
``_trusted_evidence_from_verifier`` boundary after it has authenticated and
read back the referenced objects.  Python code in the same process can always
subvert private names, so this is an accidental-misuse boundary, not a process
security token.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import re
from typing import Any, Dict, Optional, Tuple

import argus_recovery_registry as registry


EVIDENCE_SCHEMA_VERSION = "argus-recovery-proof-evidence-v1"
PROOF_POLICY_SCHEMA_VERSION = "argus-recovery-proof-policy-v1"
PROOF_TRANSCRIPT_SCHEMA_VERSION = "argus-recovery-proof-transcript-v1"

DEFAULT_MAX_RECEIPT_AGE_SECONDS = 300
DEFAULT_HARD_RPO_TARGET_SECONDS = 1800
ABSOLUTE_MAX_SEGMENTS = 4096
ABSOLUTE_MAX_EXTERNAL_REFERENCES = 256
ABSOLUTE_MAX_STATE_COVERAGE = 512
ABSOLUTE_MAX_MUTATION_COVERAGE = 512
MAX_SAFE_INTEGER = 9_007_199_254_740_991

_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
_SHA_RE = re.compile(r"^[0-9a-f]{40}$", re.ASCII)
_GENERATION_RE = re.compile(r"^gen_[0-9a-f]{32}$", re.ASCII)
_MANIFEST_RE = re.compile(r"^manifest_[0-9a-f]{32}$", re.ASCII)
_POINTER_RE = re.compile(r"^pointer_[0-9a-f]{32}$", re.ASCII)
_FULL_RE = re.compile(r"^full_[0-9a-f]{32}$", re.ASCII)
_SEGMENT_RE = re.compile(r"^wal_[0-9a-f]{32}$", re.ASCII)
_RECEIPT_RE = re.compile(r"^receipt_[0-9a-f]{32}$", re.ASCII)
_EXTERNAL_RE = re.compile(r"^external_[a-z0-9][a-z0-9_.-]{0,126}$", re.ASCII)
_STABLE_ID_RE = re.compile(
    r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$", re.ASCII)
_TIMESTAMP_RE = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$",
    re.ASCII,
)


class _ValueEnum(str, Enum):
    def __str__(self) -> str:
        return self.value


class ProofStatus(_ValueEnum):
    PROVEN = "PROVEN"
    NOT_PROVEN = "NOT_PROVEN"


class RecoveryMode(_ValueEnum):
    FULL_PLUS_WAL = "FULL_PLUS_WAL"


class WalTailDeclaration(_ValueEnum):
    EXPLICIT_EMPTY = "EXPLICIT_EMPTY"
    SEGMENTS = "SEGMENTS"


class PredecessorKind(_ValueEnum):
    FULL_GENERATION = "FULL_GENERATION"
    WAL_SEGMENT = "WAL_SEGMENT"


class VerificationBoundary(_ValueEnum):
    TRUSTED_VERIFIER_OUTPUT = "TRUSTED_VERIFIER_OUTPUT"


class CoverageCompleteness(_ValueEnum):
    EXACT_COMPLETE = "EXACT_COMPLETE"
    INCOMPLETE = "INCOMPLETE"


class InstrumentationCoverage(_ValueEnum):
    COMPLETE_NO_GAPS = "COMPLETE_NO_GAPS"
    GAP_PRESENT = "GAP_PRESENT"


class ClockTrust(_ValueEnum):
    TRUSTED = "TRUSTED"
    UNTRUSTED = "UNTRUSTED"


class FreshnessPolicyVersion(_ValueEnum):
    EXPLICIT_UTC_SECONDS_V1 = "EXPLICIT_UTC_SECONDS_V1"


class ReasonCode(_ValueEnum):
    INVALID_NOW = "INVALID_NOW"
    INVALID_POLICY = "INVALID_POLICY"
    INVALID_EVIDENCE_STRUCTURE = "INVALID_EVIDENCE_STRUCTURE"
    CARDINALITY_EXCEEDED = "CARDINALITY_EXCEEDED"
    UNSUPPORTED_EVIDENCE_SCHEMA = "UNSUPPORTED_EVIDENCE_SCHEMA"
    INVALID_EVIDENCE_TYPES = "INVALID_EVIDENCE_TYPES"
    WRONG_MODE = "WRONG_MODE"
    MANIFEST_NOT_PINNED = "MANIFEST_NOT_PINNED"
    MANIFEST_READBACK_MISMATCH = "MANIFEST_READBACK_MISMATCH"
    MANIFEST_POINTER_CHANGED = "MANIFEST_POINTER_CHANGED"
    FULL_GENERATION_ID_MISMATCH = "FULL_GENERATION_ID_MISMATCH"
    FULL_GENERATION_DIGEST_MISMATCH = "FULL_GENERATION_DIGEST_MISMATCH"
    FULL_GENERATION_INCOMPATIBLE = "FULL_GENERATION_INCOMPATIBLE"
    FULL_GENERATION_BASELINE_MISMATCH = "FULL_GENERATION_BASELINE_MISMATCH"
    WAL_TAIL_RANGE_INVALID = "WAL_TAIL_RANGE_INVALID"
    WAL_GAP = "WAL_GAP"
    WAL_DUPLICATE = "WAL_DUPLICATE"
    WAL_OVERLAP = "WAL_OVERLAP"
    WAL_FORK = "WAL_FORK"
    WAL_REGRESSION = "WAL_REGRESSION"
    WAL_PREDECESSOR_MISMATCH = "WAL_PREDECESSOR_MISMATCH"
    WAL_AUTHENTICITY_INVALID = "WAL_AUTHENTICITY_INVALID"
    COMPATIBILITY_UNSUPPORTED = "COMPATIBILITY_UNSUPPORTED"
    REGISTRY_POLICY_MISMATCH = "REGISTRY_POLICY_MISMATCH"
    STATE_COVERAGE_INCOMPLETE = "STATE_COVERAGE_INCOMPLETE"
    MUTATION_COVERAGE_INCOMPLETE = "MUTATION_COVERAGE_INCOMPLETE"
    EXTERNAL_REFERENCE_INVALID = "EXTERNAL_REFERENCE_INVALID"
    RESTORE_ROOT_MISMATCH = "RESTORE_ROOT_MISMATCH"
    VERIFIER_RECEIPT_INVALID = "VERIFIER_RECEIPT_INVALID"
    VERIFIER_RECEIPT_STALE = "VERIFIER_RECEIPT_STALE"
    POINTER_VERIFICATION_WINDOW_INVALID = \
        "POINTER_VERIFICATION_WINDOW_INVALID"


class HardRpoReasonCode(_ValueEnum):
    PROOF_NOT_PROVEN = "PROOF_NOT_PROVEN"
    MUTATION_COVERAGE_INCOMPLETE = "MUTATION_COVERAGE_INCOMPLETE"
    INSTRUMENTATION_GAP = "INSTRUMENTATION_GAP"
    REMOTE_DURABLE_LAG_EXCEEDED = "REMOTE_DURABLE_LAG_EXCEEDED"
    CLOCK_EVIDENCE_INVALID = "CLOCK_EVIDENCE_INVALID"
    CLOCK_EVIDENCE_STALE = "CLOCK_EVIDENCE_STALE"


@dataclass(frozen=True)
class ExternalReferenceDeclaration:
    referenceId: str
    expectedDigest: str
    immutableLocatorDigest: str


@dataclass(frozen=True)
class AuthorityManifestEvidence:
    manifestId: str
    authorityEpoch: int
    generationId: str
    manifestDigest: str
    observedDigest: str
    pointerIdentity: str
    fullGenerationId: str
    fullGenerationDigest: str
    baselineWalSequence: int
    remoteCoveredHighWater: int
    stateRootAtT: str
    stateRootAtH: str
    walTail: WalTailDeclaration
    walSegmentIds: Tuple[str, ...]
    externalReferences: Tuple[ExternalReferenceDeclaration, ...]
    registryPolicyDigest: str
    reducerDigest: str
    stateSchemaDigest: str
    buildSha: str
    keyIdDigest: str
    verifiedAt: str
    authenticityReceiptDigest: str


@dataclass(frozen=True)
class ManifestReadbackEvidence:
    manifestId: str
    manifestDigest: str
    pointerIdentity: str
    authorityEpoch: int
    generationId: str
    observedAt: str
    readbackReceiptDigest: str


@dataclass(frozen=True)
class FullGenerationEvidence:
    fullGenerationId: str
    generationId: str
    expectedDigest: str
    observedDigest: str
    coversThroughSequence: int
    stateRoot: str
    reducerDigest: str
    stateSchemaDigest: str
    buildSha: str
    keyIdDigest: str
    verifiedAt: str
    authenticityReceiptDigest: str


@dataclass(frozen=True)
class WalSegmentEvidence:
    segmentId: str
    generationId: str
    expectedDigest: str
    observedDigest: str
    startSequence: int
    endSequence: int
    predecessorKind: PredecessorKind
    predecessorIdentity: str
    predecessorDigest: str
    startStateRoot: str
    endStateRoot: str
    reducerDigest: str
    stateSchemaDigest: str
    buildSha: str
    keyIdDigest: str
    verifiedAt: str
    authenticityReceiptDigest: str


@dataclass(frozen=True)
class StateCoverageEvidence:
    stateId: str
    generationId: str
    coveredThroughSequence: int
    completeness: CoverageCompleteness
    coverageDigest: str
    verificationReceiptDigest: str


@dataclass(frozen=True)
class MutationCoverageEvidence:
    mutationId: str
    generationId: str
    coveredThroughSequence: int
    completeness: CoverageCompleteness
    coverageDigest: str
    verificationReceiptDigest: str


@dataclass(frozen=True)
class ExternalReferenceEvidence:
    referenceId: str
    generationId: str
    expectedDigest: str
    observedDigest: str
    immutableLocatorDigest: str
    verifiedAt: str
    verificationReceiptDigest: str


@dataclass(frozen=True)
class IsolatedRestoreEvidence:
    generationId: str
    restoredThroughSequence: int
    stateRoot: str
    verifierBuildSha: str
    completedAt: str
    verificationReceiptDigest: str


@dataclass(frozen=True)
class HardRpoEvidence:
    mutationCoverage: CoverageCompleteness
    instrumentationCoverage: InstrumentationCoverage
    remoteDurableLagSeconds: int
    clockTrust: ClockTrust
    clockObservedAt: str
    clockReceiptDigest: str


@dataclass(frozen=True)
class VerifierReceiptEvidence:
    receiptId: str
    transcriptDigest: str
    manifestId: str
    generationId: str
    verifiedThroughSequence: int
    verifierBuildSha: str
    issuedAt: str


@dataclass(frozen=True, init=False)
class VerifiedRecoveryEvidence:
    """Immutable trusted verifier output; intentionally has no public init."""

    schemaVersion: str
    verificationBoundary: VerificationBoundary
    mode: RecoveryMode
    manifest: AuthorityManifestEvidence
    initialManifestReadback: ManifestReadbackEvidence
    finalManifestReadback: ManifestReadbackEvidence
    fullGeneration: FullGenerationEvidence
    walSegments: Tuple[WalSegmentEvidence, ...]
    stateCoverage: Tuple[StateCoverageEvidence, ...]
    mutationCoverage: Tuple[MutationCoverageEvidence, ...]
    externalReferences: Tuple[ExternalReferenceEvidence, ...]
    isolatedRestore: IsolatedRestoreEvidence
    hardRpoEvidence: HardRpoEvidence
    verificationTime: str
    verifierBuildSha: str
    verifierReceipt: VerifierReceiptEvidence


@dataclass(frozen=True)
class ProofPolicy:
    schemaVersion: str
    freshnessPolicyVersion: FreshnessPolicyVersion
    registryPolicyDigest: str
    supportedEvidenceSchemaVersions: Tuple[str, ...]
    supportedReducerDigests: Tuple[str, ...]
    supportedStateSchemaDigests: Tuple[str, ...]
    supportedBuildShas: Tuple[str, ...]
    supportedVerifierBuildShas: Tuple[str, ...]
    maxReceiptAgeSeconds: int
    maxFutureSkewSeconds: int
    hardRpoTargetSeconds: int
    maxSegments: int
    maxExternalReferences: int
    maxStateCoverageEntries: int
    maxMutationCoverageEntries: int


@dataclass(frozen=True)
class ProofTranscript:
    schemaVersion: str
    checkedPredicateIds: Tuple[str, ...]
    outcomeCodes: Tuple[str, ...]
    hardRpoOutcomeCodes: Tuple[str, ...]
    policySchemaVersion: str
    freshnessPolicyVersion: str
    evidenceDigest: str
    manifestIdentity: str
    generationId: str


@dataclass(frozen=True)
class ProofResult:
    status: ProofStatus
    hardRpoClaimPermitted: bool
    reasonCodes: Tuple[ReasonCode, ...]
    hardRpoReasonCodes: Tuple[HardRpoReasonCode, ...]
    transcript: ProofTranscript


PREDICATE_IDS = (
    "P00_CARDINALITY_BOUNDS",
    "P01_SUPPORTED_EVIDENCE_SCHEMA",
    "P02_EXACT_TYPES_AND_ENUMS",
    "P03_FULL_PLUS_WAL_MODE",
    "P04_MANIFEST_IDENTITY_PINNED",
    "P05_INITIAL_MANIFEST_READBACK_MATCHES",
    "P06_FINAL_POINTER_REREAD_STABLE",
    "P07_FULL_GENERATION_IDENTITY_MATCHES",
    "P08_FULL_GENERATION_DIGEST_VERIFIES",
    "P09_FULL_GENERATION_COMPATIBLE",
    "P10_FULL_GENERATION_COVERS_T",
    "P11_WAL_COVERS_T_PLUS_1_THROUGH_H",
    "P12_WAL_NO_GAP",
    "P13_WAL_NO_DUPLICATE",
    "P14_WAL_NO_OVERLAP",
    "P15_WAL_NO_FORK",
    "P16_WAL_NO_REGRESSION",
    "P17_WAL_PREDECESSOR_CHAIN_VALID",
    "P18_OBJECT_AND_SEGMENT_AUTHENTICITY_VALID",
    "P19_REDUCER_SCHEMA_BUILD_SUPPORTED",
    "P20_REGISTRY_POLICY_MATCHES",
    "P21_MUST_PRESERVE_STATE_COVERAGE",
    "P22_REQUIRED_MUTATION_COVERAGE",
    "P23_EXTERNAL_REFERENCES_VERIFY",
    "P24_ISOLATED_RESTORE_ROOT_MATCHES",
    "P25_VERIFIER_RECEIPT_FRESH",
    "P26_POINTER_STABLE_THROUGH_VERIFICATION",
)


def make_proof_policy(
        *, supportedReducerDigests: Tuple[str, ...],
        supportedStateSchemaDigests: Tuple[str, ...],
        supportedBuildShas: Tuple[str, ...],
        supportedVerifierBuildShas: Tuple[str, ...],
        maxReceiptAgeSeconds: int = DEFAULT_MAX_RECEIPT_AGE_SECONDS,
        maxFutureSkewSeconds: int = 0,
        hardRpoTargetSeconds: int = DEFAULT_HARD_RPO_TARGET_SECONDS,
        maxSegments: int = ABSOLUTE_MAX_SEGMENTS,
        maxExternalReferences: int = ABSOLUTE_MAX_EXTERNAL_REFERENCES,
        maxStateCoverageEntries: int = ABSOLUTE_MAX_STATE_COVERAGE,
        maxMutationCoverageEntries: int = ABSOLUTE_MAX_MUTATION_COVERAGE,
) -> ProofPolicy:
    """Build policy bound to Registry Core through its accepted digest API."""
    return ProofPolicy(
        schemaVersion=PROOF_POLICY_SCHEMA_VERSION,
        freshnessPolicyVersion=FreshnessPolicyVersion.EXPLICIT_UTC_SECONDS_V1,
        registryPolicyDigest=registry.registry_policy_sha256(),
        supportedEvidenceSchemaVersions=(EVIDENCE_SCHEMA_VERSION,),
        supportedReducerDigests=supportedReducerDigests,
        supportedStateSchemaDigests=supportedStateSchemaDigests,
        supportedBuildShas=supportedBuildShas,
        supportedVerifierBuildShas=supportedVerifierBuildShas,
        maxReceiptAgeSeconds=maxReceiptAgeSeconds,
        maxFutureSkewSeconds=maxFutureSkewSeconds,
        hardRpoTargetSeconds=hardRpoTargetSeconds,
        maxSegments=maxSegments,
        maxExternalReferences=maxExternalReferences,
        maxStateCoverageEntries=maxStateCoverageEntries,
        maxMutationCoverageEntries=maxMutationCoverageEntries,
    )


def _trusted_evidence_from_verifier(**values: Any) -> VerifiedRecoveryEvidence:
    """Internal adapter boundary; never pass raw request/caller fields here."""
    expected = tuple(field.name for field in fields(VerifiedRecoveryEvidence))
    if type(values) is not dict or set(values) != set(expected):
        raise TypeError("trusted_evidence_fields_invalid")
    instance = object.__new__(VerifiedRecoveryEvidence)
    for name in expected:
        object.__setattr__(instance, name, values[name])
    return instance


_ZERO_DIGEST = "0" * 64
_UNAVAILABLE_IDENTITY = "UNAVAILABLE"
_FIELD_NAMES = {
    cls: frozenset(field.name for field in fields(cls))
    for cls in (
        ExternalReferenceDeclaration,
        AuthorityManifestEvidence,
        ManifestReadbackEvidence,
        FullGenerationEvidence,
        WalSegmentEvidence,
        StateCoverageEvidence,
        MutationCoverageEvidence,
        ExternalReferenceEvidence,
        IsolatedRestoreEvidence,
        HardRpoEvidence,
        VerifierReceiptEvidence,
        VerifiedRecoveryEvidence,
        ProofPolicy,
        ProofTranscript,
    )
}


def _exact_fields(value: Any, expected_type: type) -> Optional[Dict[str, Any]]:
    if type(value) is not expected_type:
        return None
    try:
        raw = object.__getattribute__(value, "__dict__")
    except Exception:
        return None
    if type(raw) is not dict or frozenset(raw) != _FIELD_NAMES[expected_type]:
        return None
    return raw


def _valid_text(value: Any, *, maximum: int = 256) -> bool:
    return type(value) is str and 0 < len(value) <= maximum


def _valid_digest(value: Any, *, nonzero: bool = False) -> bool:
    return type(value) is str and _DIGEST_RE.fullmatch(value) is not None and (
        not nonzero or value != _ZERO_DIGEST)


def _valid_sha(value: Any) -> bool:
    return type(value) is str and _SHA_RE.fullmatch(value) is not None


def _valid_sequence(value: Any, *, positive: bool = False) -> bool:
    return type(value) is int and (value > 0 if positive else value >= 0) and \
        value <= MAX_SAFE_INTEGER


def _parse_timestamp(value: Any) -> Optional[datetime]:
    if type(value) is not str or _TIMESTAMP_RE.fullmatch(value) is None:
        return None
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc)
    except (ValueError, OverflowError):
        return None
    if parsed.strftime("%Y-%m-%dT%H:%M:%SZ") != value:
        return None
    return parsed


def _valid_timestamp(value: Any) -> bool:
    return _parse_timestamp(value) is not None


def _valid_enum(value: Any, enum_type: type) -> bool:
    return type(value) is enum_type


def _valid_tuple(
        value: Any, item_validator: Any, maximum: int,
        *, nonempty: bool = False) -> bool:
    if type(value) is not tuple or len(value) > maximum or (
            nonempty and not value):
        return False
    return all(item_validator(item) for item in value)


def _valid_external_declaration(value: Any) -> bool:
    raw = _exact_fields(value, ExternalReferenceDeclaration)
    return raw is not None and type(raw["referenceId"]) is str and \
        _EXTERNAL_RE.fullmatch(raw["referenceId"]) is not None and \
        _valid_digest(raw["expectedDigest"], nonzero=True) and \
        _valid_digest(raw["immutableLocatorDigest"], nonzero=True)


def _valid_manifest(value: Any) -> bool:
    raw = _exact_fields(value, AuthorityManifestEvidence)
    if raw is None:
        return False
    return (
        type(raw["manifestId"]) is str and
        _MANIFEST_RE.fullmatch(raw["manifestId"]) is not None and
        _valid_sequence(raw["authorityEpoch"], positive=True) and
        type(raw["generationId"]) is str and
        _GENERATION_RE.fullmatch(raw["generationId"]) is not None and
        _valid_digest(raw["manifestDigest"], nonzero=True) and
        _valid_digest(raw["observedDigest"], nonzero=True) and
        type(raw["pointerIdentity"]) is str and
        _POINTER_RE.fullmatch(raw["pointerIdentity"]) is not None and
        type(raw["fullGenerationId"]) is str and
        _FULL_RE.fullmatch(raw["fullGenerationId"]) is not None and
        _valid_digest(raw["fullGenerationDigest"], nonzero=True) and
        _valid_sequence(raw["baselineWalSequence"]) and
        _valid_sequence(raw["remoteCoveredHighWater"]) and
        _valid_digest(raw["stateRootAtT"], nonzero=True) and
        _valid_digest(raw["stateRootAtH"], nonzero=True) and
        _valid_enum(raw["walTail"], WalTailDeclaration) and
        _valid_tuple(
            raw["walSegmentIds"],
            lambda item: type(item) is str and
            _SEGMENT_RE.fullmatch(item) is not None,
            ABSOLUTE_MAX_SEGMENTS,
        ) and
        _valid_tuple(
            raw["externalReferences"], _valid_external_declaration,
            ABSOLUTE_MAX_EXTERNAL_REFERENCES,
        ) and
        _valid_digest(raw["registryPolicyDigest"], nonzero=True) and
        _valid_digest(raw["reducerDigest"], nonzero=True) and
        _valid_digest(raw["stateSchemaDigest"], nonzero=True) and
        _valid_sha(raw["buildSha"]) and
        _valid_digest(raw["keyIdDigest"], nonzero=True) and
        _valid_timestamp(raw["verifiedAt"]) and
        _valid_digest(raw["authenticityReceiptDigest"], nonzero=True)
    )


def _valid_manifest_readback(value: Any) -> bool:
    raw = _exact_fields(value, ManifestReadbackEvidence)
    return raw is not None and type(raw["manifestId"]) is str and \
        _MANIFEST_RE.fullmatch(raw["manifestId"]) is not None and \
        _valid_digest(raw["manifestDigest"], nonzero=True) and \
        type(raw["pointerIdentity"]) is str and \
        _POINTER_RE.fullmatch(raw["pointerIdentity"]) is not None and \
        _valid_sequence(raw["authorityEpoch"], positive=True) and \
        type(raw["generationId"]) is str and \
        _GENERATION_RE.fullmatch(raw["generationId"]) is not None and \
        _valid_timestamp(raw["observedAt"]) and \
        _valid_digest(raw["readbackReceiptDigest"], nonzero=True)


def _valid_full_generation(value: Any) -> bool:
    raw = _exact_fields(value, FullGenerationEvidence)
    return raw is not None and type(raw["fullGenerationId"]) is str and \
        _FULL_RE.fullmatch(raw["fullGenerationId"]) is not None and \
        type(raw["generationId"]) is str and \
        _GENERATION_RE.fullmatch(raw["generationId"]) is not None and \
        _valid_digest(raw["expectedDigest"], nonzero=True) and \
        _valid_digest(raw["observedDigest"], nonzero=True) and \
        _valid_sequence(raw["coversThroughSequence"]) and \
        _valid_digest(raw["stateRoot"], nonzero=True) and \
        _valid_digest(raw["reducerDigest"], nonzero=True) and \
        _valid_digest(raw["stateSchemaDigest"], nonzero=True) and \
        _valid_sha(raw["buildSha"]) and \
        _valid_digest(raw["keyIdDigest"], nonzero=True) and \
        _valid_timestamp(raw["verifiedAt"]) and \
        _valid_digest(raw["authenticityReceiptDigest"], nonzero=True)


def _valid_segment(value: Any) -> bool:
    raw = _exact_fields(value, WalSegmentEvidence)
    if raw is None:
        return False
    predecessor_kind = raw["predecessorKind"]
    predecessor_identity = raw["predecessorIdentity"]
    predecessor_valid = False
    if type(predecessor_kind) is PredecessorKind and \
            type(predecessor_identity) is str:
        if predecessor_kind is PredecessorKind.FULL_GENERATION:
            predecessor_valid = _FULL_RE.fullmatch(
                predecessor_identity) is not None
        elif predecessor_kind is PredecessorKind.WAL_SEGMENT:
            predecessor_valid = _SEGMENT_RE.fullmatch(
                predecessor_identity) is not None
    return (
        type(raw["segmentId"]) is str and
        _SEGMENT_RE.fullmatch(raw["segmentId"]) is not None and
        type(raw["generationId"]) is str and
        _GENERATION_RE.fullmatch(raw["generationId"]) is not None and
        _valid_digest(raw["expectedDigest"], nonzero=True) and
        _valid_digest(raw["observedDigest"], nonzero=True) and
        _valid_sequence(raw["startSequence"]) and
        _valid_sequence(raw["endSequence"]) and
        predecessor_valid and
        _valid_digest(raw["predecessorDigest"], nonzero=True) and
        _valid_digest(raw["startStateRoot"], nonzero=True) and
        _valid_digest(raw["endStateRoot"], nonzero=True) and
        _valid_digest(raw["reducerDigest"], nonzero=True) and
        _valid_digest(raw["stateSchemaDigest"], nonzero=True) and
        _valid_sha(raw["buildSha"]) and
        _valid_digest(raw["keyIdDigest"], nonzero=True) and
        _valid_timestamp(raw["verifiedAt"]) and
        _valid_digest(raw["authenticityReceiptDigest"], nonzero=True)
    )


def _valid_coverage(
        value: Any, expected_type: type, identity_field: str) -> bool:
    raw = _exact_fields(value, expected_type)
    return raw is not None and type(raw[identity_field]) is str and \
        _STABLE_ID_RE.fullmatch(raw[identity_field]) is not None and \
        type(raw["generationId"]) is str and \
        _GENERATION_RE.fullmatch(raw["generationId"]) is not None and \
        _valid_sequence(raw["coveredThroughSequence"]) and \
        _valid_enum(raw["completeness"], CoverageCompleteness) and \
        _valid_digest(raw["coverageDigest"], nonzero=True) and \
        _valid_digest(raw["verificationReceiptDigest"], nonzero=True)


def _valid_external_reference(value: Any) -> bool:
    raw = _exact_fields(value, ExternalReferenceEvidence)
    return raw is not None and type(raw["referenceId"]) is str and \
        _EXTERNAL_RE.fullmatch(raw["referenceId"]) is not None and \
        type(raw["generationId"]) is str and \
        _GENERATION_RE.fullmatch(raw["generationId"]) is not None and \
        _valid_digest(raw["expectedDigest"], nonzero=True) and \
        _valid_digest(raw["observedDigest"], nonzero=True) and \
        _valid_digest(raw["immutableLocatorDigest"], nonzero=True) and \
        _valid_timestamp(raw["verifiedAt"]) and \
        _valid_digest(raw["verificationReceiptDigest"], nonzero=True)


def _valid_restore(value: Any) -> bool:
    raw = _exact_fields(value, IsolatedRestoreEvidence)
    return raw is not None and type(raw["generationId"]) is str and \
        _GENERATION_RE.fullmatch(raw["generationId"]) is not None and \
        _valid_sequence(raw["restoredThroughSequence"]) and \
        _valid_digest(raw["stateRoot"], nonzero=True) and \
        _valid_sha(raw["verifierBuildSha"]) and \
        _valid_timestamp(raw["completedAt"]) and \
        _valid_digest(raw["verificationReceiptDigest"], nonzero=True)


def _valid_hard_rpo(value: Any) -> bool:
    raw = _exact_fields(value, HardRpoEvidence)
    return raw is not None and \
        _valid_enum(raw["mutationCoverage"], CoverageCompleteness) and \
        _valid_enum(
            raw["instrumentationCoverage"], InstrumentationCoverage) and \
        _valid_sequence(raw["remoteDurableLagSeconds"]) and \
        _valid_enum(raw["clockTrust"], ClockTrust) and \
        _valid_timestamp(raw["clockObservedAt"]) and \
        _valid_digest(raw["clockReceiptDigest"], nonzero=True)


def _valid_receipt(value: Any) -> bool:
    raw = _exact_fields(value, VerifierReceiptEvidence)
    return raw is not None and type(raw["receiptId"]) is str and \
        _RECEIPT_RE.fullmatch(raw["receiptId"]) is not None and \
        _valid_digest(raw["transcriptDigest"], nonzero=True) and \
        type(raw["manifestId"]) is str and \
        _MANIFEST_RE.fullmatch(raw["manifestId"]) is not None and \
        type(raw["generationId"]) is str and \
        _GENERATION_RE.fullmatch(raw["generationId"]) is not None and \
        _valid_sequence(raw["verifiedThroughSequence"]) and \
        _valid_sha(raw["verifierBuildSha"]) and \
        _valid_timestamp(raw["issuedAt"])


def _valid_evidence_structure(value: Any) -> bool:
    raw = _exact_fields(value, VerifiedRecoveryEvidence)
    if raw is None:
        return False
    return (
        _valid_text(raw["schemaVersion"], maximum=96) and
        _valid_enum(raw["verificationBoundary"], VerificationBoundary) and
        _valid_enum(raw["mode"], RecoveryMode) and
        _valid_manifest(raw["manifest"]) and
        _valid_manifest_readback(raw["initialManifestReadback"]) and
        _valid_manifest_readback(raw["finalManifestReadback"]) and
        _valid_full_generation(raw["fullGeneration"]) and
        _valid_tuple(
            raw["walSegments"], _valid_segment, ABSOLUTE_MAX_SEGMENTS) and
        _valid_tuple(
            raw["stateCoverage"],
            lambda item: _valid_coverage(
                item, StateCoverageEvidence, "stateId"),
            ABSOLUTE_MAX_STATE_COVERAGE,
        ) and
        _valid_tuple(
            raw["mutationCoverage"],
            lambda item: _valid_coverage(
                item, MutationCoverageEvidence, "mutationId"),
            ABSOLUTE_MAX_MUTATION_COVERAGE,
        ) and
        _valid_tuple(
            raw["externalReferences"], _valid_external_reference,
            ABSOLUTE_MAX_EXTERNAL_REFERENCES,
        ) and
        _valid_restore(raw["isolatedRestore"]) and
        _valid_hard_rpo(raw["hardRpoEvidence"]) and
        _valid_timestamp(raw["verificationTime"]) and
        _valid_sha(raw["verifierBuildSha"]) and
        _valid_receipt(raw["verifierReceipt"])
    )


def _valid_sorted_unique_text_tuple(
        value: Any, item_validator: Any, maximum: int) -> bool:
    return _valid_tuple(value, item_validator, maximum, nonempty=True) and \
        value == tuple(sorted(value)) and len(set(value)) == len(value)


def _valid_policy(value: Any) -> bool:
    raw = _exact_fields(value, ProofPolicy)
    if raw is None:
        return False
    positive_bounded = (
        ("maxReceiptAgeSeconds", MAX_SAFE_INTEGER),
        ("hardRpoTargetSeconds", MAX_SAFE_INTEGER),
        ("maxSegments", ABSOLUTE_MAX_SEGMENTS),
        ("maxExternalReferences", ABSOLUTE_MAX_EXTERNAL_REFERENCES),
        ("maxStateCoverageEntries", ABSOLUTE_MAX_STATE_COVERAGE),
        ("maxMutationCoverageEntries", ABSOLUTE_MAX_MUTATION_COVERAGE),
    )
    if any(not _valid_sequence(raw[name], positive=True) or
           raw[name] > maximum for name, maximum in positive_bounded):
        return False
    if not _valid_sequence(raw["maxFutureSkewSeconds"]):
        return False
    return (
        raw["schemaVersion"] == PROOF_POLICY_SCHEMA_VERSION and
        type(raw["freshnessPolicyVersion"]) is FreshnessPolicyVersion and
        _valid_digest(raw["registryPolicyDigest"], nonzero=True) and
        _valid_sorted_unique_text_tuple(
            raw["supportedEvidenceSchemaVersions"],
            lambda item: _valid_text(item, maximum=96), 8) and
        _valid_sorted_unique_text_tuple(
            raw["supportedReducerDigests"],
            lambda item: _valid_digest(item, nonzero=True), 64) and
        _valid_sorted_unique_text_tuple(
            raw["supportedStateSchemaDigests"],
            lambda item: _valid_digest(item, nonzero=True), 64) and
        _valid_sorted_unique_text_tuple(
            raw["supportedBuildShas"], _valid_sha, 64) and
        _valid_sorted_unique_text_tuple(
            raw["supportedVerifierBuildShas"], _valid_sha, 64)
    )


def _canonical_value(value: Any) -> Any:
    if isinstance(value, _ValueEnum):
        return value.value
    if type(value) in (str, int, bool) or value is None:
        return value
    if type(value) is tuple:
        return [_canonical_value(item) for item in value]
    if type(value) in _FIELD_NAMES:
        raw = object.__getattribute__(value, "__dict__")
        return {
            field.name: _canonical_value(raw[field.name])
            for field in fields(type(value))
        }
    raise TypeError("unsupported_canonical_value")


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        _canonical_value(value), ensure_ascii=False, allow_nan=False,
        sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")


def _manifest_contract_digest(manifest: AuthorityManifestEvidence) -> str:
    document = _canonical_value(manifest)
    for key in (
            "manifestDigest", "observedDigest", "verifiedAt",
            "authenticityReceiptDigest"):
        document.pop(key)
    return hashlib.sha256(json.dumps(
        document, ensure_ascii=False, allow_nan=False, sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")).hexdigest()


def _evidence_transcript_digest(evidence: VerifiedRecoveryEvidence) -> str:
    document = _canonical_value(evidence)
    document["verifierReceipt"]["transcriptDigest"] = _ZERO_DIGEST
    return hashlib.sha256(json.dumps(
        document, ensure_ascii=False, allow_nan=False, sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")).hexdigest()


def _ordered_reasons(values: Any) -> Tuple[ReasonCode, ...]:
    return tuple(sorted(set(values), key=lambda item: item.value))


def _ordered_hard_rpo_reasons(values: Any) -> Tuple[HardRpoReasonCode, ...]:
    return tuple(sorted(set(values), key=lambda item: item.value))


def _make_result(
        *, policy: Optional[ProofPolicy], evidenceDigest: str,
        manifestIdentity: str, generationId: str,
        reasons: Any, hardRpoReasons: Any) -> ProofResult:
    ordered = _ordered_reasons(reasons)
    ordered_hard_rpo = _ordered_hard_rpo_reasons(hardRpoReasons)
    status = ProofStatus.PROVEN if not ordered else ProofStatus.NOT_PROVEN
    hard_rpo_permitted = status is ProofStatus.PROVEN and \
        not ordered_hard_rpo
    if policy is None:
        policy_schema = _UNAVAILABLE_IDENTITY
        freshness_policy = _UNAVAILABLE_IDENTITY
    else:
        policy_schema = policy.schemaVersion
        freshness_policy = policy.freshnessPolicyVersion.value
    transcript = ProofTranscript(
        schemaVersion=PROOF_TRANSCRIPT_SCHEMA_VERSION,
        checkedPredicateIds=PREDICATE_IDS,
        outcomeCodes=tuple(item.value for item in ordered),
        hardRpoOutcomeCodes=tuple(
            item.value for item in ordered_hard_rpo),
        policySchemaVersion=policy_schema,
        freshnessPolicyVersion=freshness_policy,
        evidenceDigest=evidenceDigest,
        manifestIdentity=manifestIdentity,
        generationId=generationId,
    )
    return ProofResult(
        status=status,
        hardRpoClaimPermitted=hard_rpo_permitted,
        reasonCodes=ordered,
        hardRpoReasonCodes=ordered_hard_rpo,
        transcript=transcript,
    )


def _invalid_result(reason: ReasonCode) -> ProofResult:
    return _make_result(
        policy=None, evidenceDigest=_ZERO_DIGEST,
        manifestIdentity=_UNAVAILABLE_IDENTITY,
        generationId=_UNAVAILABLE_IDENTITY,
        reasons=(reason,),
        hardRpoReasons=(HardRpoReasonCode.PROOF_NOT_PROVEN,),
    )


def _readback_matches_manifest(
        readback: ManifestReadbackEvidence,
        manifest: AuthorityManifestEvidence) -> bool:
    return (
        readback.manifestId == manifest.manifestId and
        readback.manifestDigest == manifest.manifestDigest and
        readback.pointerIdentity == manifest.pointerIdentity and
        readback.authorityEpoch == manifest.authorityEpoch and
        readback.generationId == manifest.generationId
    )


def _required_state_ids() -> Tuple[str, ...]:
    return tuple(sorted(
        row.stateId for row in registry.states()
        if type(row.mustPreserveNow) is bool and row.mustPreserveNow))


def _required_mutation_ids() -> Tuple[str, ...]:
    return tuple(sorted(row.mutationId for row in registry.mutations()))


def _time_is_not_future(
        observed: datetime, now: datetime, skew_seconds: int) -> bool:
    return (observed - now).total_seconds() <= skew_seconds


def _time_is_fresh(
        observed: datetime, now: datetime, maximum_age: int,
        future_skew: int) -> bool:
    age = (now - observed).total_seconds()
    return -future_skew <= age <= maximum_age


def _verification_window_is_valid(
        *, initial: Optional[datetime], final: Optional[datetime],
        clock: Optional[datetime], receipt: Optional[datetime],
        verification_moments: Tuple[Optional[datetime], ...],
        now: datetime, policy: ProofPolicy, clock_trusted: bool) -> bool:
    """Validate the one explicit temporal window bound by the receipt."""
    if initial is None or final is None or clock is None or receipt is None or \
            not clock_trusted or \
            any(moment is None for moment in verification_moments):
        return False
    moments = tuple(
        moment for moment in verification_moments if moment is not None)
    final_to_receipt = (receipt - final).total_seconds()
    return (
        initial <= final <= receipt and
        initial <= clock <= receipt and
        all(initial <= moment <= final for moment in moments) and
        0 <= final_to_receipt <= policy.maxReceiptAgeSeconds and
        _time_is_fresh(
            final, now, policy.maxReceiptAgeSeconds,
            policy.maxFutureSkewSeconds) and
        _time_is_fresh(
            clock, now, policy.maxReceiptAgeSeconds,
            policy.maxFutureSkewSeconds) and
        _time_is_fresh(
            receipt, now, policy.maxReceiptAgeSeconds,
            policy.maxFutureSkewSeconds)
    )


def _evaluate_valid_evidence(
        evidence: VerifiedRecoveryEvidence, policy: ProofPolicy,
        now: datetime) -> ProofResult:
    reasons = set()
    hard_rpo_reasons = set()
    evidence_digest = _evidence_transcript_digest(evidence)
    manifest = evidence.manifest
    initial = evidence.initialManifestReadback
    final = evidence.finalManifestReadback
    full = evidence.fullGeneration
    segments = evidence.walSegments
    restore = evidence.isolatedRestore
    receipt = evidence.verifierReceipt
    hard = evidence.hardRpoEvidence
    t_sequence = manifest.baselineWalSequence
    h_sequence = manifest.remoteCoveredHighWater

    if (
            len(segments) > policy.maxSegments or
            len(manifest.walSegmentIds) > policy.maxSegments or
            len(manifest.externalReferences) >
            policy.maxExternalReferences or
            len(evidence.externalReferences) >
            policy.maxExternalReferences or
            len(evidence.stateCoverage) >
            policy.maxStateCoverageEntries or
            len(evidence.mutationCoverage) >
            policy.maxMutationCoverageEntries):
        reasons.add(ReasonCode.CARDINALITY_EXCEEDED)

    if evidence.schemaVersion not in policy.supportedEvidenceSchemaVersions:
        reasons.add(ReasonCode.UNSUPPORTED_EVIDENCE_SCHEMA)
    if evidence.verificationBoundary is not \
            VerificationBoundary.TRUSTED_VERIFIER_OUTPUT:
        reasons.add(ReasonCode.INVALID_EVIDENCE_TYPES)
    if evidence.mode is not RecoveryMode.FULL_PLUS_WAL:
        reasons.add(ReasonCode.WRONG_MODE)

    if (
            initial.manifestId != manifest.manifestId or
            initial.manifestDigest != manifest.manifestDigest):
        reasons.add(ReasonCode.MANIFEST_NOT_PINNED)
    if not _readback_matches_manifest(initial, manifest):
        reasons.add(ReasonCode.MANIFEST_READBACK_MISMATCH)
    if (
            final.pointerIdentity != initial.pointerIdentity or
            final.manifestId != initial.manifestId or
            final.manifestDigest != initial.manifestDigest):
        reasons.add(ReasonCode.MANIFEST_POINTER_CHANGED)

    if (
            full.fullGenerationId != manifest.fullGenerationId or
            full.generationId != manifest.generationId):
        reasons.add(ReasonCode.FULL_GENERATION_ID_MISMATCH)
    if not (
            full.expectedDigest == manifest.fullGenerationDigest ==
            full.observedDigest):
        reasons.add(ReasonCode.FULL_GENERATION_DIGEST_MISMATCH)
    if not (
            full.reducerDigest == manifest.reducerDigest and
            full.stateSchemaDigest == manifest.stateSchemaDigest and
            full.buildSha == manifest.buildSha and
            full.keyIdDigest == manifest.keyIdDigest):
        reasons.add(ReasonCode.FULL_GENERATION_INCOMPATIBLE)
    if not (
            full.coversThroughSequence == t_sequence and
            full.stateRoot == manifest.stateRootAtT):
        reasons.add(ReasonCode.FULL_GENERATION_BASELINE_MISMATCH)

    manifest_ids = manifest.walSegmentIds
    evidence_ids = tuple(segment.segmentId for segment in segments)
    if manifest.walTail is WalTailDeclaration.EXPLICIT_EMPTY:
        if not (t_sequence == h_sequence and not manifest_ids and
                not segments and
                manifest.stateRootAtT == manifest.stateRootAtH):
            reasons.add(ReasonCode.WAL_TAIL_RANGE_INVALID)
    elif manifest.walTail is WalTailDeclaration.SEGMENTS:
        if not (h_sequence > t_sequence and segments and
                manifest_ids == evidence_ids):
            reasons.add(ReasonCode.WAL_TAIL_RANGE_INVALID)
    else:
        reasons.add(ReasonCode.WAL_TAIL_RANGE_INVALID)

    if h_sequence < t_sequence:
        reasons.add(ReasonCode.WAL_REGRESSION)

    if len(set(evidence_ids)) != len(evidence_ids) or len(set(
            segment.expectedDigest for segment in segments)) != len(segments):
        reasons.add(ReasonCode.WAL_DUPLICATE)
    ranges = tuple(
        (segment.startSequence, segment.endSequence) for segment in segments)
    if len(set(ranges)) != len(ranges):
        reasons.add(ReasonCode.WAL_DUPLICATE)
    predecessors = tuple(
        (segment.predecessorKind, segment.predecessorIdentity)
        for segment in segments)
    if len(set(predecessors)) != len(predecessors):
        reasons.add(ReasonCode.WAL_FORK)

    expected_start = t_sequence + 1
    prior_end = t_sequence
    prior_identity = full.fullGenerationId
    prior_digest = full.expectedDigest
    prior_root = manifest.stateRootAtT
    prior_kind = PredecessorKind.FULL_GENERATION
    for index, segment in enumerate(segments):
        if segment.startSequence > expected_start:
            reasons.add(ReasonCode.WAL_GAP)
        if segment.startSequence <= prior_end:
            reasons.add(ReasonCode.WAL_OVERLAP)
        if (
                segment.endSequence < segment.startSequence or
                segment.endSequence <= prior_end or
                segment.endSequence > h_sequence):
            reasons.add(ReasonCode.WAL_REGRESSION)
        if not (
                segment.predecessorKind is prior_kind and
                segment.predecessorIdentity == prior_identity and
                segment.predecessorDigest == prior_digest):
            reasons.add(ReasonCode.WAL_PREDECESSOR_MISMATCH)
        if not (
                segment.expectedDigest == segment.observedDigest and
                segment.generationId == manifest.generationId and
                segment.keyIdDigest == manifest.keyIdDigest and
                segment.startStateRoot == prior_root):
            reasons.add(ReasonCode.WAL_AUTHENTICITY_INVALID)
        expected_start = segment.endSequence + 1
        prior_end = segment.endSequence
        prior_identity = segment.segmentId
        prior_digest = segment.expectedDigest
        prior_root = segment.endStateRoot
        prior_kind = PredecessorKind.WAL_SEGMENT
        if index == len(segments) - 1 and \
                segment.endStateRoot != manifest.stateRootAtH:
            reasons.add(ReasonCode.WAL_AUTHENTICITY_INVALID)
    if segments and prior_end != h_sequence:
        reasons.add(ReasonCode.WAL_GAP)
    if not segments and t_sequence != h_sequence:
        reasons.add(ReasonCode.WAL_GAP)

    if not (
            manifest.manifestDigest == _manifest_contract_digest(manifest) and
            manifest.observedDigest == manifest.manifestDigest):
        reasons.add(ReasonCode.WAL_AUTHENTICITY_INVALID)
    if any(not (
            segment.reducerDigest == manifest.reducerDigest and
            segment.stateSchemaDigest == manifest.stateSchemaDigest and
            segment.buildSha == manifest.buildSha)
            for segment in segments):
        reasons.add(ReasonCode.COMPATIBILITY_UNSUPPORTED)
    if not (
            manifest.reducerDigest in policy.supportedReducerDigests and
            manifest.stateSchemaDigest in policy.supportedStateSchemaDigests and
            manifest.buildSha in policy.supportedBuildShas and
            full.reducerDigest in policy.supportedReducerDigests and
            full.stateSchemaDigest in policy.supportedStateSchemaDigests and
            full.buildSha in policy.supportedBuildShas and
            evidence.verifierBuildSha in policy.supportedVerifierBuildShas and
            restore.verifierBuildSha in policy.supportedVerifierBuildShas and
            receipt.verifierBuildSha in policy.supportedVerifierBuildShas):
        reasons.add(ReasonCode.COMPATIBILITY_UNSUPPORTED)

    current_registry_digest = registry.registry_policy_sha256()
    if not (
            policy.registryPolicyDigest == current_registry_digest and
            manifest.registryPolicyDigest == policy.registryPolicyDigest):
        reasons.add(ReasonCode.REGISTRY_POLICY_MISMATCH)

    required_states = _required_state_ids()
    state_ids = tuple(row.stateId for row in evidence.stateCoverage)
    state_valid = (
        len(state_ids) == len(set(state_ids)) and
        tuple(sorted(state_ids)) == required_states and
        all(
            row.generationId == manifest.generationId and
            row.coveredThroughSequence == h_sequence and
            row.completeness is CoverageCompleteness.EXACT_COMPLETE
            for row in evidence.stateCoverage)
    )
    if not state_valid:
        reasons.add(ReasonCode.STATE_COVERAGE_INCOMPLETE)

    required_mutations = _required_mutation_ids()
    mutation_ids = tuple(row.mutationId for row in evidence.mutationCoverage)
    mutation_valid = (
        len(mutation_ids) == len(set(mutation_ids)) and
        tuple(sorted(mutation_ids)) == required_mutations and
        all(
            row.generationId == manifest.generationId and
            row.coveredThroughSequence == h_sequence and
            row.completeness is CoverageCompleteness.EXACT_COMPLETE
            for row in evidence.mutationCoverage) and
        hard.mutationCoverage is CoverageCompleteness.EXACT_COMPLETE and
        hard.instrumentationCoverage is
        InstrumentationCoverage.COMPLETE_NO_GAPS
    )
    if not mutation_valid:
        reasons.add(ReasonCode.MUTATION_COVERAGE_INCOMPLETE)

    declarations = manifest.externalReferences
    declaration_ids = tuple(row.referenceId for row in declarations)
    external_ids = tuple(row.referenceId for row in evidence.externalReferences)
    declarations_unique = len(declaration_ids) == len(set(declaration_ids))
    evidence_unique = len(external_ids) == len(set(external_ids))
    external_by_id = {
        row.referenceId: row for row in evidence.externalReferences
    } if evidence_unique else {}
    external_valid = declarations_unique and evidence_unique and \
        set(declaration_ids) == set(external_ids)
    if external_valid:
        for declaration in declarations:
            observed = external_by_id[declaration.referenceId]
            if not (
                    observed.generationId == manifest.generationId and
                    observed.expectedDigest == declaration.expectedDigest ==
                    observed.observedDigest and
                    observed.immutableLocatorDigest ==
                    declaration.immutableLocatorDigest):
                external_valid = False
                break
    if not external_valid:
        reasons.add(ReasonCode.EXTERNAL_REFERENCE_INVALID)

    if not (
            restore.generationId == manifest.generationId and
            restore.restoredThroughSequence == h_sequence and
            restore.stateRoot == manifest.stateRootAtH):
        reasons.add(ReasonCode.RESTORE_ROOT_MISMATCH)

    receipt_time = _parse_timestamp(receipt.issuedAt)
    clock_time = _parse_timestamp(hard.clockObservedAt)
    verification_time = _parse_timestamp(evidence.verificationTime)
    if not (
            receipt.transcriptDigest == evidence_digest and
            receipt.manifestId == manifest.manifestId and
            receipt.generationId == manifest.generationId and
            receipt.verifiedThroughSequence == h_sequence and
            receipt.verifierBuildSha == evidence.verifierBuildSha and
            evidence.verificationTime == receipt.issuedAt and
            receipt_time is not None and verification_time is not None and
            clock_time is not None):
        reasons.add(ReasonCode.VERIFIER_RECEIPT_INVALID)
    if receipt_time is not None and not _time_is_fresh(
            receipt_time, now, policy.maxReceiptAgeSeconds,
            policy.maxFutureSkewSeconds):
        reasons.add(ReasonCode.VERIFIER_RECEIPT_STALE)

    initial_time = _parse_timestamp(initial.observedAt)
    final_time = _parse_timestamp(final.observedAt)
    verification_moments = (
        _parse_timestamp(manifest.verifiedAt),
        _parse_timestamp(full.verifiedAt),
        _parse_timestamp(restore.completedAt),
    ) + tuple(
        _parse_timestamp(segment.verifiedAt) for segment in segments) + tuple(
        _parse_timestamp(reference.verifiedAt)
        for reference in evidence.externalReferences)
    time_window_valid = _verification_window_is_valid(
        initial=initial_time, final=final_time, clock=clock_time,
        receipt=receipt_time, verification_moments=verification_moments,
        now=now, policy=policy,
        clock_trusted=hard.clockTrust is ClockTrust.TRUSTED,
    )
    if not time_window_valid or not _readback_matches_manifest(
            final, manifest):
        reasons.add(ReasonCode.POINTER_VERIFICATION_WINDOW_INVALID)

    if reasons:
        hard_rpo_reasons.add(HardRpoReasonCode.PROOF_NOT_PROVEN)
    if not mutation_valid:
        hard_rpo_reasons.add(
            HardRpoReasonCode.MUTATION_COVERAGE_INCOMPLETE)
    if hard.instrumentationCoverage is not \
            InstrumentationCoverage.COMPLETE_NO_GAPS:
        hard_rpo_reasons.add(HardRpoReasonCode.INSTRUMENTATION_GAP)
    if hard.remoteDurableLagSeconds > policy.hardRpoTargetSeconds:
        hard_rpo_reasons.add(
            HardRpoReasonCode.REMOTE_DURABLE_LAG_EXCEEDED)
    if hard.clockTrust is not ClockTrust.TRUSTED or clock_time is None or \
            not _time_is_not_future(
                clock_time, now, policy.maxFutureSkewSeconds):
        hard_rpo_reasons.add(HardRpoReasonCode.CLOCK_EVIDENCE_INVALID)
    if clock_time is None or not _time_is_fresh(
            clock_time, now, policy.maxReceiptAgeSeconds,
            policy.maxFutureSkewSeconds):
        hard_rpo_reasons.add(HardRpoReasonCode.CLOCK_EVIDENCE_STALE)

    return _make_result(
        policy=policy,
        evidenceDigest=evidence_digest,
        manifestIdentity=manifest.manifestId,
        generationId=manifest.generationId,
        reasons=reasons,
        hardRpoReasons=hard_rpo_reasons,
    )


def evaluate_recovery_proof(
        evidence: Any, policy: Any, explicitNow: Any) -> ProofResult:
    """Evaluate one pinned evidence package; total, deterministic, fail closed."""
    try:
        now = _parse_timestamp(explicitNow)
        if now is None:
            return _invalid_result(ReasonCode.INVALID_NOW)
        if not _valid_policy(policy):
            return _invalid_result(ReasonCode.INVALID_POLICY)
        if not _valid_evidence_structure(evidence):
            return _invalid_result(ReasonCode.INVALID_EVIDENCE_STRUCTURE)
        return _evaluate_valid_evidence(evidence, policy, now)
    except Exception:
        return _invalid_result(ReasonCode.INVALID_EVIDENCE_STRUCTURE)


def proof_result_document(result: Any) -> Dict[str, Any]:
    """Return the intentionally minimal canonical external result."""
    if type(result) is not ProofResult or type(result.status) is not ProofStatus \
            or type(result.hardRpoClaimPermitted) is not bool:
        return {
            "status": ProofStatus.NOT_PROVEN.value,
            "hardRpoClaimPermitted": False,
        }
    return {
        "status": result.status.value,
        "hardRpoClaimPermitted": result.hardRpoClaimPermitted,
    }


def proof_transcript_document(result: Any) -> Dict[str, Any]:
    """Return a bounded audit transcript without errors, state, or secrets."""
    if type(result) is not ProofResult or type(result.transcript) is not \
            ProofTranscript:
        result = _invalid_result(ReasonCode.INVALID_EVIDENCE_STRUCTURE)
    return _canonical_value(result.transcript)


def proof_transcript_canonical_bytes(result: Any) -> bytes:
    return json.dumps(
        proof_transcript_document(result), ensure_ascii=False, allow_nan=False,
        sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
