"""Recovery Phase A registries (shadow metadata; never recovery authority).

This module deliberately contains declarations and validation only.  Importing it
must not read or write durable state, select a checkpoint, or alter a mutation.
Unknowns are kept explicit and conservative so later FullGeneration/WAL work
cannot silently treat an unproved state as disposable.
"""

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
import re
from typing import Any, Dict, Optional, Tuple


REGISTRY_SCHEMA = "argus-authoritative-state-registry-v1"
MUTATION_REGISTRY_SCHEMA = "argus-mutation-class-registry-v1"
REGISTRY_POLICY_SCHEMA = "argus-recovery-registry-policy-v1"
_STABLE_ID_RE = re.compile(
    r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$", re.ASCII)
_TOKEN_RE = re.compile(r"^[a-z][a-z0-9_-]*$", re.ASCII)
_CHECKPOINT_KEY_RE = re.compile(r"^[A-Za-z][A-Za-z0-9]{0,63}$", re.ASCII)
_USE_BUILTIN = object()

_MAX_REGISTRY_ROWS = 512
_MAX_STABLE_ID = 128
_MAX_NAME = 160
_MAX_DOMAIN = 64
_MAX_OWNER_MODULE = 256
_MAX_NOTES = 1024
_MAX_TUPLE_ITEMS = 64
_MAX_TUPLE_TEXT = 160


class _ValueEnum(str, Enum):
    def __str__(self) -> str:
        return self.value


class Classification(_ValueEnum):
    A = "A_AUTHORITATIVE_NON_REACQUIRABLE"
    B = "B_AUTHORITATIVE_SOURCE_FACTS"
    C = "C_DETERMINISTIC_RECOMPUTABLE"
    D = "D_REACQUIRABLE_WITH_CONTRACT"
    E = "E_CACHE_EPHEMERAL"
    F = "F_UNKNOWN_OWNER_SEMANTICS_REQUIRED"


class StorageKind(_ValueEnum):
    CHECKPOINT_SECTION = "CHECKPOINT_SECTION"
    LOCAL_WAL = "LOCAL_WAL"
    LOCAL_SIDECAR = "LOCAL_SIDECAR"
    LOCAL_TEMP = "LOCAL_TEMP"
    MEMORY_ONLY = "MEMORY_ONLY"
    PUBLIC_GIT = "PUBLIC_GIT"
    PRIVATE_GIT = "PRIVATE_GIT"
    EC2_DISK = "EC2_DISK"
    CLIENT_STORAGE = "CLIENT_STORAGE"
    CLIENT_VAULT = "CLIENT_VAULT"
    ENV_SECRET = "ENV_SECRET"


class RecoveryCoverage(_ValueEnum):
    LEGACY_FULL = "LEGACY_FULL"
    ENCRYPTED_OVERLAY_WHEN_CONFIGURED = "ENCRYPTED_OVERLAY_WHEN_CONFIGURED"
    LOCAL_ONLY = "LOCAL_ONLY"
    PARTIAL = "PARTIAL"
    EXTERNAL_BEST_EFFORT = "EXTERNAL_BEST_EFFORT"
    INDEPENDENT_DURABLE = "INDEPENDENT_DURABLE"
    CLIENT_BOUNDARY = "CLIENT_BOUNDARY"
    NONE = "NONE"
    UNKNOWN = "UNKNOWN"


class PrivacyClass(_ValueEnum):
    PUBLIC_METADATA = "PUBLIC_METADATA"
    INTERNAL = "INTERNAL"
    OWNER_PRIVATE = "OWNER_PRIVATE"
    SECURITY_SENSITIVE = "SECURITY_SENSITIVE"
    SECRET = "SECRET"
    CLIENT_PRIVATE = "CLIENT_PRIVATE"
    CLIENT_OPAQUE = "CLIENT_OPAQUE"


# Registry Core is stricter than the superseded PR: only exact PUBLIC_METADATA
# may opt in.  INTERNAL is never an unauthenticated literal identifier.
PUBLIC_TELEMETRY_COMPATIBLE_PRIVACY = frozenset({
    PrivacyClass.PUBLIC_METADATA,
})


class FutureDurability(_ValueEnum):
    FULL_PLUS_WAL = "FULL_PLUS_WAL"
    IMMUTABLE_EXTERNAL_REF = "IMMUTABLE_EXTERNAL_REF"
    REBUILD_AFTER_PROOF = "REBUILD_AFTER_PROOF"
    REACQUIRE_AFTER_CONTRACT = "REACQUIRE_AFTER_CONTRACT"
    EPHEMERAL = "EPHEMERAL"
    UNRESOLVED = "UNRESOLVED"


class StateNature(_ValueEnum):
    SOURCE = "SOURCE"
    DERIVED = "DERIVED"
    MIXED = "MIXED"
    CONTROL = "CONTROL"
    CACHE = "CACHE"
    EXTERNAL_REFERENCE = "EXTERNAL_REFERENCE"


class ReducerExpectation(_ValueEnum):
    REQUIRED = "REQUIRED"
    EXTERNAL_REFERENCE = "EXTERNAL_REFERENCE"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    UNRESOLVED = "UNRESOLVED"


@dataclass(frozen=True)
class StateDeclaration:
    stateId: str
    humanName: str
    classification: Classification
    mustPreserveNow: bool
    currentStorageKind: StorageKind
    currentRecoveryCoverage: RecoveryCoverage
    mutationDomain: str
    privacyClass: PrivacyClass
    containsSecret: bool
    containsOwnerPrivateData: bool
    intendedFutureDurability: FutureDurability
    sourceDerivedStatus: StateNature
    rebuildRequirements: Tuple[str, ...]
    mutationRegistryExpectation: ReducerExpectation
    evidenceOwnerModule: str
    checkpointKeys: Tuple[str, ...]
    notes: str
    ephemeralRetentionReason: Optional[str] = None
    allowedInTelemetry: bool = False


def _s(state_id: str, name: str, classification: Classification,
       storage: StorageKind, coverage: RecoveryCoverage, domain: str,
       privacy: PrivacyClass, future: FutureDurability, nature: StateNature,
       reducer: ReducerExpectation, owner: str, notes: str, *,
       keys: Tuple[str, ...] = (), inputs: Tuple[str, ...] = (),
       private: bool = False, secret: bool = False,
       telemetry: bool = False, preserve: Any = _USE_BUILTIN,
       retention_reason: Optional[str] = None) -> StateDeclaration:
    """Construct a declaration without coercing any caller-supplied value.

    The only interpreted value is the private sentinel used when ``preserve``
    is omitted.  Unknown classifications default to preserve-now; explicit
    ``None`` remains invalid and is reported by ``validate_registry``.
    """
    if preserve is _USE_BUILTIN:
        preserve = False if type(classification) is Classification and \
            classification is Classification.E else True
    return StateDeclaration(
        state_id, name, classification, preserve, storage, coverage,
        domain, privacy, secret, private, future, nature, inputs, reducer,
        owner, keys, notes, retention_reason, telemetry)


def state_allows_public_telemetry(row: Any) -> bool:
    """Return the one fail-closed state identifier authorization decision."""
    return (
        type(row) is StateDeclaration and
        type(row.allowedInTelemetry) is bool and
        row.allowedInTelemetry is True and
        type(row.privacyClass) is PrivacyClass and
        row.privacyClass is PrivacyClass.PUBLIC_METADATA and
        type(row.containsSecret) is bool and
        row.containsSecret is False and
        type(row.containsOwnerPrivateData) is bool and
        row.containsOwnerPrivateData is False)


_STATES: Tuple[StateDeclaration, ...] = tuple(sorted((
    _s("backend.schema_identity", "Checkpoint schema identity", Classification.A,
       StorageKind.CHECKPOINT_SECTION, RecoveryCoverage.LEGACY_FULL, "durability",
       PrivacyClass.PUBLIC_METADATA, FutureDurability.FULL_PLUS_WAL, StateNature.CONTROL,
       ReducerExpectation.REQUIRED, "scanner.py/argus_persistent_storage.py", "Reader compatibility must be explicit and generation-bound.", keys=("schemaVersion",), telemetry=True),
    _s("backend.integrity_hashes", "Checkpoint section hashes and local seal", Classification.E,
       StorageKind.CHECKPOINT_SECTION, RecoveryCoverage.LEGACY_FULL, "durability",
       PrivacyClass.PUBLIC_METADATA, FutureDurability.EPHEMERAL, StateNature.DERIVED,
       ReducerExpectation.NOT_APPLICABLE, "scanner.py/argus_persistent_storage.py", "Recomputed from retained state; future artifacts need their own authenticated hashes.", keys=("marketLedgerStateHash", "chartIntelligenceStateHash", "todayIntelligenceStateHash", "marketReplayStateHash", "verifiedViewSnapshotsStateHash", "assetChartReportsStateHash", "localCheckpointIntegrity"), telemetry=True, preserve=False),
    _s("backend.term_overlay", "OSINT learned term overlay", Classification.A,
       StorageKind.CHECKPOINT_SECTION, RecoveryCoverage.LEGACY_FULL, "osint",
       PrivacyClass.OWNER_PRIVATE, FutureDurability.FULL_PLUS_WAL, StateNature.SOURCE,
       ReducerExpectation.REQUIRED, "scanner.py", "Owner/adaptive terms are not reacquirable.", keys=("termOverlay",), private=True, telemetry=False),
    _s("backend.learned_memory", "Bounded learned OSINT memory", Classification.B,
       StorageKind.CHECKPOINT_SECTION, RecoveryCoverage.LEGACY_FULL, "osint",
       PrivacyClass.PUBLIC_METADATA, FutureDurability.FULL_PLUS_WAL, StateNature.SOURCE,
       ReducerExpectation.REQUIRED, "scanner.py", "Only public-safe records enter the legacy checkpoint.", keys=("memory",), telemetry=True),
    _s("backend.url_cache", "Verified URL metadata cache", Classification.D,
       StorageKind.CHECKPOINT_SECTION, RecoveryCoverage.LEGACY_FULL, "osint",
       PrivacyClass.INTERNAL, FutureDurability.REACQUIRE_AFTER_CONTRACT, StateNature.CACHE,
       ReducerExpectation.REQUIRED, "scanner.py", "No accepted point-in-time/provider revision contract; preserve for now. URL content is never recovery telemetry.", keys=("urlCache",), inputs=("provider entitlement", "point-in-time revision contract"), telemetry=False),
    _s("backend.checkpoint_histories", "Canary, RPS, baseline and benchmark histories", Classification.B,
       StorageKind.CHECKPOINT_SECTION, RecoveryCoverage.LEGACY_FULL, "control",
       PrivacyClass.PUBLIC_METADATA, FutureDurability.FULL_PLUS_WAL, StateNature.MIXED,
       ReducerExpectation.REQUIRED, "scanner.py", "Acceptance and calibration evidence.", keys=("canaryLast", "rpsHistory", "baselineRuns", "benchmarkRuns", "checkpointFailureHistory"), telemetry=True),
    _s("backend.soak_state", "Soak state, history and control", Classification.A,
       StorageKind.CHECKPOINT_SECTION, RecoveryCoverage.PARTIAL, "control",
       PrivacyClass.INTERNAL, FutureDurability.FULL_PLUS_WAL, StateNature.CONTROL,
       ReducerExpectation.REQUIRED, "scanner.py", "Build-scoped control; no authority change in Phase A.", keys=("soak", "soakHistory", "soakControl", "soakLastPersistAt"), telemetry=False),
    _s("backend.stage1_control", "Checkpoint V2 Stage1 control", Classification.A,
       StorageKind.CHECKPOINT_SECTION, RecoveryCoverage.LEGACY_FULL, "control",
       PrivacyClass.SECURITY_SENSITIVE, FutureDurability.FULL_PLUS_WAL, StateNature.CONTROL,
       ReducerExpectation.REQUIRED, "scanner.py", "Stage1 remains disabled and non-authoritative.", keys=("checkpointV2Stage1Control",), telemetry=False),
    _s("backend.missions", "Research missions", Classification.A,
       StorageKind.CHECKPOINT_SECTION, RecoveryCoverage.ENCRYPTED_OVERLAY_WHEN_CONFIGURED, "mission",
       PrivacyClass.INTERNAL, FutureDurability.FULL_PLUS_WAL, StateNature.SOURCE,
       ReducerExpectation.REQUIRED, "scanner.py", "Current WAL covers only some mission transitions.", keys=("missions",), telemetry=False),
    _s("backend.mission_windows", "Mission scheduling windows", Classification.A,
       StorageKind.CHECKPOINT_SECTION, RecoveryCoverage.ENCRYPTED_OVERLAY_WHEN_CONFIGURED, "mission",
       PrivacyClass.INTERNAL, FutureDurability.FULL_PLUS_WAL, StateNature.CONTROL,
       ReducerExpectation.REQUIRED, "scanner.py", "Window transitions are not fully redo-logged.", keys=("missionWindows",), telemetry=False),
    _s("backend.forecasts", "Decision forecasts", Classification.B,
       StorageKind.CHECKPOINT_SECTION, RecoveryCoverage.ENCRYPTED_OVERLAY_WHEN_CONFIGURED, "decision",
       PrivacyClass.INTERNAL, FutureDurability.FULL_PLUS_WAL, StateNature.SOURCE,
       ReducerExpectation.REQUIRED, "scanner.py", "Forward-live issuance history.", keys=("forecasts",), telemetry=False),
    _s("backend.outcomes", "Forecast outcomes", Classification.B,
       StorageKind.CHECKPOINT_SECTION, RecoveryCoverage.ENCRYPTED_OVERLAY_WHEN_CONFIGURED, "decision",
       PrivacyClass.INTERNAL, FutureDurability.FULL_PLUS_WAL, StateNature.SOURCE,
       ReducerExpectation.REQUIRED, "scanner.py", "Outcome observations and resolution state.", keys=("outcomes",), telemetry=False),
    _s("backend.incidents", "Durability and operational incidents", Classification.B,
       StorageKind.CHECKPOINT_SECTION, RecoveryCoverage.ENCRYPTED_OVERLAY_WHEN_CONFIGURED, "operations",
       PrivacyClass.INTERNAL, FutureDurability.FULL_PLUS_WAL, StateNature.SOURCE,
       ReducerExpectation.REQUIRED, "scanner.py", "Operational evidence.", keys=("incidents",), telemetry=False),
    _s("backend.ops_journal", "Operational journal and metadata", Classification.A,
       StorageKind.CHECKPOINT_SECTION, RecoveryCoverage.ENCRYPTED_OVERLAY_WHEN_CONFIGURED, "journal",
       PrivacyClass.INTERNAL, FutureDurability.FULL_PLUS_WAL, StateNature.SOURCE,
       ReducerExpectation.REQUIRED, "scanner.py/argus_state_journal.py", "Includes journal rows, metadata and compacted proof.", keys=("opsJournal", "opsJournalMeta", "opsJournalCompacted"), telemetry=False),
    _s("backend.ops_sequence_allocator", "Aggregate sequence allocator", Classification.A,
       StorageKind.CHECKPOINT_SECTION, RecoveryCoverage.ENCRYPTED_OVERLAY_WHEN_CONFIGURED, "journal",
       PrivacyClass.SECURITY_SENSITIVE, FutureDurability.FULL_PLUS_WAL, StateNature.CONTROL,
       ReducerExpectation.REQUIRED, "scanner.py/argus_remote_journal.py", "Prevents sequence/idempotency reuse.", keys=("opsSequenceByAggregate",), telemetry=False),
    _s("backend.mission_artifacts", "Postmortems, reports and challenger runs", Classification.A,
       StorageKind.CHECKPOINT_SECTION, RecoveryCoverage.ENCRYPTED_OVERLAY_WHEN_CONFIGURED, "mission",
       PrivacyClass.INTERNAL, FutureDurability.FULL_PLUS_WAL, StateNature.SOURCE,
       ReducerExpectation.REQUIRED, "scanner.py", "Non-reacquirable research artifacts; content/model output is never telemetry.", keys=("postmortems", "periodicReports", "challengerRuns"), telemetry=False),
    _s("backend.agent_queue", "OSINT agent queue", Classification.A,
       StorageKind.CHECKPOINT_SECTION, RecoveryCoverage.ENCRYPTED_OVERLAY_WHEN_CONFIGURED, "queue",
       PrivacyClass.OWNER_PRIVATE, FutureDurability.FULL_PLUS_WAL, StateNature.CONTROL,
       ReducerExpectation.REQUIRED, "scanner.py", "Accepted work must not silently disappear.", keys=("agentQueue",), private=True, telemetry=False),
    _s("backend.remote_ack_cycle", "Legacy Remote Journal ACK and cycle", Classification.A,
       StorageKind.CHECKPOINT_SECTION, RecoveryCoverage.PARTIAL, "durability",
       PrivacyClass.SECURITY_SENSITIVE, FutureDurability.FULL_PLUS_WAL, StateNature.CONTROL,
       ReducerExpectation.REQUIRED, "scanner.py", "Legacy ACK is not exact remote WAL durability.", keys=("remoteAck", "remoteJournalCycle"), telemetry=False),
    _s("backend.remote_recovery_required", "Recovery anti-downgrade marker", Classification.A,
       StorageKind.CHECKPOINT_SECTION, RecoveryCoverage.LEGACY_FULL, "security",
       PrivacyClass.SECURITY_SENSITIVE, FutureDurability.FULL_PLUS_WAL, StateNature.CONTROL,
       ReducerExpectation.REQUIRED, "scanner.py", "Present only after keyed mode is configured.", keys=("remoteRecoveryRequired",), telemetry=False),
    _s("backend.formal_benchmarks", "Formal benchmark and holdout state", Classification.A,
       StorageKind.CHECKPOINT_SECTION, RecoveryCoverage.LEGACY_FULL, "benchmark",
       PrivacyClass.INTERNAL, FutureDurability.FULL_PLUS_WAL, StateNature.CONTROL,
       ReducerExpectation.REQUIRED, "argus_research_benchmark*.py", "One-shot/holdout consumption must survive.", keys=("formalResearchBenchmark", "formalResearchBenchmarkV2"), telemetry=False),
    _s("backend.foundation_jobs", "Foundation job lifecycle", Classification.A,
       StorageKind.CHECKPOINT_SECTION, RecoveryCoverage.PARTIAL, "foundation",
       PrivacyClass.INTERNAL, FutureDurability.FULL_PLUS_WAL, StateNature.CONTROL,
       ReducerExpectation.REQUIRED, "argus_foundation_jobs.py", "Also has a local same-volume sidecar.", keys=("foundationJobs",), telemetry=False),
    _s("backend.cost_policy", "Cost usage, events and run guards", Classification.A,
       StorageKind.CHECKPOINT_SECTION, RecoveryCoverage.LEGACY_FULL, "ai-control",
       PrivacyClass.SECURITY_SENSITIVE, FutureDurability.FULL_PLUS_WAL, StateNature.CONTROL,
       ReducerExpectation.REQUIRED, "argus_cost_policy.py", "Prevents duplicate/over-budget model use.", keys=("costPolicy",), telemetry=False),
    _s("backend.mission_durability", "Mission WAL cursor and receipt projection", Classification.A,
       StorageKind.CHECKPOINT_SECTION, RecoveryCoverage.ENCRYPTED_OVERLAY_WHEN_CONFIGURED, "durability",
       PrivacyClass.SECURITY_SENSITIVE, FutureDurability.FULL_PLUS_WAL, StateNature.CONTROL,
       ReducerExpectation.REQUIRED, "scanner.py/argus_tick_durability.py", "Scalar cursor is not a redo log.", keys=("missionTickDurability",), telemetry=False),
    _s("backend.local_wal", "Legacy mission tick WAL", Classification.A,
       StorageKind.LOCAL_WAL, RecoveryCoverage.LOCAL_ONLY, "durability",
       PrivacyClass.SECURITY_SENSITIVE, FutureDurability.FULL_PLUS_WAL, StateNature.SOURCE,
       ReducerExpectation.REQUIRED, "argus_tick_durability.py", "Local-only and incomplete; Phase A does not change it.", telemetry=False),
    _s("backend.receipt_queue", "Remote receipt queue and cursor", Classification.A,
       StorageKind.LOCAL_SIDECAR, RecoveryCoverage.LOCAL_ONLY, "durability",
       PrivacyClass.SECURITY_SENSITIVE, FutureDurability.FULL_PLUS_WAL, StateNature.CONTROL,
       ReducerExpectation.REQUIRED, "argus_remote_receipt_queue.py", "Same-volume fsynced intent queue.", telemetry=False),
    _s("backend.nonce_authority", "Recovery nonce monotonic authority", Classification.A,
       StorageKind.LOCAL_SIDECAR, RecoveryCoverage.PARTIAL, "security",
       PrivacyClass.SECURITY_SENSITIVE, FutureDurability.FULL_PLUS_WAL, StateNature.CONTROL,
       ReducerExpectation.REQUIRED, "argus_remote_nonce_anchor.py", "Anti-reuse anchor/state/history; dormant while encryption is unconfigured.", telemetry=False),
    _s("security.recovery_keys", "Recovery root keys", Classification.A,
       StorageKind.ENV_SECRET, RecoveryCoverage.NONE, "security",
       PrivacyClass.SECRET, FutureDurability.IMMUTABLE_EXTERNAL_REF, StateNature.EXTERNAL_REFERENCE,
       ReducerExpectation.EXTERNAL_REFERENCE, "deployment configuration", "Never checkpoint, log or export key material.", secret=True, telemetry=False),
    _s("market.ledger_source", "Market Ledger source facts and import receipts", Classification.B,
       StorageKind.CHECKPOINT_SECTION, RecoveryCoverage.LEGACY_FULL, "market-data",
       PrivacyClass.INTERNAL, FutureDurability.FULL_PLUS_WAL, StateNature.SOURCE,
       ReducerExpectation.REQUIRED, "argus_market_ledger.py", "Observations/import/rollback receipts are authority.", keys=("marketLedger",), telemetry=False),
    _s("market.ledger_derived", "Market Ledger metrics, turning points and backtests", Classification.C,
       StorageKind.CHECKPOINT_SECTION, RecoveryCoverage.LEGACY_FULL, "market-data",
       PrivacyClass.INTERNAL, FutureDurability.REBUILD_AFTER_PROOF, StateNature.DERIVED,
       ReducerExpectation.REQUIRED, "argus_market_ledger.py", "No accepted hash-equal rebuild proof; preserve now.", keys=("marketLedger",), inputs=("exact observations", "method/build/schema", "detection timestamps"), telemetry=False),
    _s("market.chart_intelligence", "Chart intelligence", Classification.C,
       StorageKind.CHECKPOINT_SECTION, RecoveryCoverage.LEGACY_FULL, "market-analytics",
       PrivacyClass.PUBLIC_METADATA, FutureDurability.REBUILD_AFTER_PROOF, StateNature.DERIVED,
       ReducerExpectation.REQUIRED, "argus_chart_intelligence.py", "Preserve until exact-input/hash rebuild drill passes.", keys=("chartIntelligence",), inputs=("exact OHLCV", "ledger/events", "method/build/schema"), telemetry=True),
    _s("market.today_source", "Today intelligence short-selling source history", Classification.B,
       StorageKind.CHECKPOINT_SECTION, RecoveryCoverage.LEGACY_FULL, "market-data",
       PrivacyClass.INTERNAL, FutureDurability.FULL_PLUS_WAL, StateNature.SOURCE,
       ReducerExpectation.REQUIRED, "argus_today_intelligence.py", "Revision-bearing source rows.", keys=("todayIntelligence",), telemetry=False),
    _s("market.today_derived", "Today intelligence snapshots and outcomes", Classification.C,
       StorageKind.CHECKPOINT_SECTION, RecoveryCoverage.LEGACY_FULL, "market-analytics",
       PrivacyClass.PUBLIC_METADATA, FutureDurability.REBUILD_AFTER_PROOF, StateNature.DERIVED,
       ReducerExpectation.REQUIRED, "argus_today_intelligence.py", "No accepted exact rebuild proof.", keys=("todayIntelligence",), inputs=("exact bars", "short rows", "comparison rows", "method/build/schema"), telemetry=True),
    _s("market.replay_receipts", "Market replay history receipts", Classification.B,
       StorageKind.CHECKPOINT_SECTION, RecoveryCoverage.LEGACY_FULL, "market-analytics",
       PrivacyClass.PUBLIC_METADATA, FutureDurability.FULL_PLUS_WAL, StateNature.SOURCE,
       ReducerExpectation.REQUIRED, "argus_market_replay.py", "Compact dataset/outcome/calibration evidence.", keys=("marketReplay",), telemetry=True),
    _s("market.replay_contexts", "Market replay contexts", Classification.C,
       StorageKind.CHECKPOINT_SECTION, RecoveryCoverage.LEGACY_FULL, "market-analytics",
       PrivacyClass.PUBLIC_METADATA, FutureDurability.REBUILD_AFTER_PROOF, StateNature.DERIVED,
       ReducerExpectation.REQUIRED, "argus_market_replay.py", "Preserve until exact-input rebuild proof.", keys=("marketReplay",), inputs=("exact bars", "ledger", "chart", "calibration", "method/build/schema"), telemetry=True),
    _s("market.verified_views", "Verified published view snapshots", Classification.B,
       StorageKind.CHECKPOINT_SECTION, RecoveryCoverage.LEGACY_FULL, "publication",
       PrivacyClass.PUBLIC_METADATA, FutureDurability.FULL_PLUS_WAL, StateNature.MIXED,
       ReducerExpectation.REQUIRED, "argus_verified_snapshot.py", "Publication identity/timestamps are source facts.", keys=("verifiedViewSnapshots",), telemetry=True),
    _s("market.asset_reports", "Asset chart reports", Classification.F,
       StorageKind.CHECKPOINT_SECTION, RecoveryCoverage.LEGACY_FULL, "market-analytics",
       PrivacyClass.PUBLIC_METADATA, FutureDurability.UNRESOLVED, StateNature.MIXED,
       ReducerExpectation.UNRESOLVED, "argus_asset_chart_cache.py", "Called a durable cache, but publication/audit semantics need owner decision.", keys=("assetChartReports",), telemetry=True),
    _s("secondary.osint_investigation_store", "Latest OSINT investigations", Classification.A,
       StorageKind.MEMORY_ONLY, RecoveryCoverage.NONE, "osint",
       PrivacyClass.INTERNAL, FutureDurability.FULL_PLUS_WAL, StateNature.SOURCE,
       ReducerExpectation.REQUIRED, "scanner.py", "Stochastic/provider as-of results cannot be reproduced exactly; content is never telemetry.", telemetry=False),
    _s("secondary.url_and_agent_work", "URL and agent work queues", Classification.A,
       StorageKind.MEMORY_ONLY, RecoveryCoverage.PARTIAL, "queue",
       PrivacyClass.OWNER_PRIVATE, FutureDurability.FULL_PLUS_WAL, StateNature.CONTROL,
       ReducerExpectation.REQUIRED, "scanner.py", "Accepted work can be lost.", private=True, telemetry=False),
    _s("secondary.decision_jobs", "Decision ledger jobs", Classification.A,
       StorageKind.MEMORY_ONLY, RecoveryCoverage.NONE, "decision",
       PrivacyClass.INTERNAL, FutureDurability.FULL_PLUS_WAL, StateNature.CONTROL,
       ReducerExpectation.REQUIRED, "scanner.py", "Stable job IDs but volatile dedupe state.", telemetry=False),
    _s("secondary.owner_intelligence", "Owner aliases, feedback and entity profiles", Classification.A,
       StorageKind.LOCAL_TEMP, RecoveryCoverage.EXTERNAL_BEST_EFFORT, "owner-intel",
       PrivacyClass.OWNER_PRIVATE, FutureDurability.FULL_PLUS_WAL, StateNature.SOURCE,
       ReducerExpectation.REQUIRED, "scanner.py", "Some private Git writes are best effort/non-transactional.", private=True, telemetry=False),
    _s("secondary.intelligence_facts", "Intel, patrol, official, macro, mover and event facts", Classification.B,
       StorageKind.LOCAL_TEMP, RecoveryCoverage.EXTERNAL_BEST_EFFORT, "intelligence",
       PrivacyClass.INTERNAL, FutureDurability.FULL_PLUS_WAL, StateNature.SOURCE,
       ReducerExpectation.REQUIRED, "scanner.py/.github/workflows", "Normalized facts and publication receipts have asynchronous ledger RPO; source text is never telemetry.", telemetry=False),
    _s("secondary.accepted_queues", "News translation and mover-explain queues", Classification.A,
       StorageKind.LOCAL_TEMP, RecoveryCoverage.PARTIAL, "queue",
       PrivacyClass.INTERNAL, FutureDurability.FULL_PLUS_WAL, StateNature.CONTROL,
       ReducerExpectation.REQUIRED, "scanner.py", "Cross-store writes are not atomic.", telemetry=False),
    _s("secondary.ai_results", "AI results and pre-analysis receipts", Classification.B,
       StorageKind.LOCAL_TEMP, RecoveryCoverage.EXTERNAL_BEST_EFFORT, "ai",
       PrivacyClass.OWNER_PRIVATE, FutureDurability.FULL_PLUS_WAL, StateNature.SOURCE,
       ReducerExpectation.REQUIRED, "scanner.py", "Never permitted in recovery telemetry.", private=True, telemetry=False),
    _s("secondary.ai_gate_cost_security", "AI gate, cost and security counters", Classification.A,
       StorageKind.MEMORY_ONLY, RecoveryCoverage.PARTIAL, "ai-control",
       PrivacyClass.SECURITY_SENSITIVE, FutureDurability.FULL_PLUS_WAL, StateNature.CONTROL,
       ReducerExpectation.REQUIRED, "scanner.py", "Crash ordering can consume a run without exact accounting.", telemetry=False),
    _s("secondary.learning_materialization", "Learning-memory materialization", Classification.C,
       StorageKind.LOCAL_TEMP, RecoveryCoverage.EXTERNAL_BEST_EFFORT, "learning",
       PrivacyClass.INTERNAL, FutureDurability.REBUILD_AFTER_PROOF, StateNature.DERIVED,
       ReducerExpectation.REQUIRED, "argus_learning_memory*.py", "Owner semantics and exact inputs/version are not yet proved.", inputs=("exact event cohorts", "method/build/schema"), telemetry=False),
    _s("secondary.legacy_scan_state", "Legacy scan/TOP3 state", Classification.F,
       StorageKind.LOCAL_TEMP, RecoveryCoverage.NONE, "legacy-scan",
       PrivacyClass.OWNER_PRIVATE, FutureDurability.UNRESOLVED, StateNature.MIXED,
       ReducerExpectation.UNRESOLVED, "scanner.py", "May contain broker-derived/account-adjacent decisions; owner disposition required.", private=True, telemetry=False),
    _s("secondary.buy_candidates", "AI buy candidates/latest view", Classification.F,
       StorageKind.LOCAL_TEMP, RecoveryCoverage.EXTERNAL_BEST_EFFORT, "ai",
       PrivacyClass.OWNER_PRIVATE, FutureDurability.UNRESOLVED, StateNature.MIXED,
       ReducerExpectation.UNRESOLVED, "scanner.py", "Exact model output is not reproducible; product authority unresolved.", private=True, telemetry=False),
    _s("secondary.sweep_cooldown", "Sweep, cooldown and patrol scheduling state", Classification.F,
       StorageKind.LOCAL_TEMP, RecoveryCoverage.PARTIAL, "operations",
       PrivacyClass.INTERNAL, FutureDurability.UNRESOLVED, StateNature.CONTROL,
       ReducerExpectation.UNRESOLVED, "scanner.py", "Audit intent and restart-reset policy require owner decision.", telemetry=False),
    _s("secondary.legacy_predictions", "Legacy predictions.jsonl", Classification.F,
       StorageKind.EC2_DISK, RecoveryCoverage.LOCAL_ONLY, "legacy-prediction",
       PrivacyClass.OWNER_PRIVATE, FutureDurability.UNRESOLVED, StateNature.SOURCE,
       ReducerExpectation.UNRESOLVED, "argus_ledger.py/render.yaml", "Must preserve until the later Prediction Ledger phase decides authority.", private=True, telemetry=False),
    _s("secondary.event_backbone", "24/7 event backbone", Classification.B,
       StorageKind.MEMORY_ONLY, RecoveryCoverage.EXTERNAL_BEST_EFFORT, "events",
       PrivacyClass.INTERNAL, FutureDurability.FULL_PLUS_WAL, StateNature.SOURCE,
       ReducerExpectation.REQUIRED, "scanner.py/argus_event_store.py", "First detection/lifecycle/dossier can precede async snapshot.", telemetry=False),
    _s("secondary.tdnet_timing", "TDnet timing and causality evidence", Classification.F,
       StorageKind.MEMORY_ONLY, RecoveryCoverage.NONE, "events",
       PrivacyClass.INTERNAL, FutureDurability.UNRESOLVED, StateNature.SOURCE,
       ReducerExpectation.UNRESOLVED, "scanner.py", "Non-reacquirable timing evidence; business authority unresolved.", telemetry=False),
    _s("external.private_git_objects", "Private Git membership, Layer2B, Decision Value, entity and vault objects", Classification.A,
       StorageKind.PRIVATE_GIT, RecoveryCoverage.INDEPENDENT_DURABLE, "external-private",
       PrivacyClass.OWNER_PRIVATE, FutureDurability.IMMUTABLE_EXTERNAL_REF, StateNature.EXTERNAL_REFERENCE,
       ReducerExpectation.EXTERNAL_REFERENCE, "scanner.py", "Keep commit/object identity; writes are not one atomic generation.", private=True, telemetry=False),
    _s("external.public_ledger_originals", "Public ledger original snapshots", Classification.B,
       StorageKind.PUBLIC_GIT, RecoveryCoverage.INDEPENDENT_DURABLE, "external-public",
       PrivacyClass.PUBLIC_METADATA, FutureDurability.IMMUTABLE_EXTERNAL_REF, StateNature.EXTERNAL_REFERENCE,
       ReducerExpectation.EXTERNAL_REFERENCE, ".github/workflows", "Future generation must bind immutable commit identities.", telemetry=True),
    _s("external.ec2_build_identity", "EC2 build identity anti-regression state", Classification.A,
       StorageKind.EC2_DISK, RecoveryCoverage.INDEPENDENT_DURABLE, "deployment",
       PrivacyClass.SECURITY_SENSITIVE, FutureDurability.IMMUTABLE_EXTERNAL_REF, StateNature.EXTERNAL_REFERENCE,
       ReducerExpectation.EXTERNAL_REFERENCE, "deployment scripts", "Separate deployment authority; metadata is not recovery payload.", telemetry=False),
    _s("client.core_private_state", "Client holdings, trades, research, judgment, snapshots, audit, FIRE and tombstones", Classification.A,
       StorageKind.CLIENT_STORAGE, RecoveryCoverage.CLIENT_BOUNDARY, "client",
       PrivacyClass.CLIENT_PRIVATE, FutureDurability.IMMUTABLE_EXTERNAL_REF, StateNature.SOURCE,
       ReducerExpectation.EXTERNAL_REFERENCE, "web/src", "Must never become server FullGeneration plaintext.", private=True, telemetry=False),
    _s("client.vault_ciphertext", "Opaque client vault ciphertext", Classification.A,
       StorageKind.CLIENT_VAULT, RecoveryCoverage.EXTERNAL_BEST_EFFORT, "client",
       PrivacyClass.CLIENT_OPAQUE, FutureDurability.IMMUTABLE_EXTERNAL_REF, StateNature.EXTERNAL_REFERENCE,
       ReducerExpectation.EXTERNAL_REFERENCE, "web/src/lib/vault.ts/scanner.py", "Ciphertext remains separate; no passphrase/plaintext on backend.", private=True, telemetry=False),
    _s("client.risk_lines", "Client risk lines", Classification.F,
       StorageKind.CLIENT_STORAGE, RecoveryCoverage.CLIENT_BOUNDARY, "client",
       PrivacyClass.CLIENT_PRIVATE, FutureDurability.UNRESOLVED, StateNature.SOURCE,
       ReducerExpectation.UNRESOLVED, "web/src", "Explicit client recovery gap; no backend move in Phase A.", private=True, telemetry=False),
    _s("client.replay_drawings", "Client replay drawings", Classification.F,
       StorageKind.CLIENT_STORAGE, RecoveryCoverage.CLIENT_BOUNDARY, "client",
       PrivacyClass.CLIENT_PRIVATE, FutureDurability.UNRESOLVED, StateNature.SOURCE,
       ReducerExpectation.UNRESOLVED, "web/src", "Explicit client recovery gap.", private=True, telemetry=False),
    _s("client.pasted_research", "Client pasted research", Classification.F,
       StorageKind.CLIENT_STORAGE, RecoveryCoverage.CLIENT_BOUNDARY, "client",
       PrivacyClass.CLIENT_PRIVATE, FutureDurability.UNRESOLVED, StateNature.SOURCE,
       ReducerExpectation.UNRESOLVED, "web/src", "Explicit client recovery gap; private content never telemetry.", private=True, telemetry=False),
    _s("client.dismissed_gaps", "Client dismissed-gap decisions", Classification.F,
       StorageKind.CLIENT_STORAGE, RecoveryCoverage.CLIENT_BOUNDARY, "client",
       PrivacyClass.CLIENT_PRIVATE, FutureDurability.UNRESOLVED, StateNature.SOURCE,
       ReducerExpectation.UNRESOLVED, "web/src", "Explicit client recovery gap.", private=True, telemetry=False),
    _s("client.browser_caches", "Browser caches and preferences", Classification.E,
       StorageKind.CLIENT_STORAGE, RecoveryCoverage.CLIENT_BOUNDARY, "client",
       PrivacyClass.CLIENT_PRIVATE, FutureDurability.EPHEMERAL, StateNature.CACHE,
       ReducerExpectation.NOT_APPLICABLE, "web/src", "Explicitly non-authoritative; not server recovery state.", private=True, telemetry=False, preserve=False),
), key=lambda row: row.stateId))


class MutationCriticality(_ValueEnum):
    EXACT_REQUIRED = "EXACT_REQUIRED"
    SOURCE_FACT = "SOURCE_FACT"
    CONDITIONAL = "CONDITIONAL"


class WalCoverage(_ValueEnum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    INDEPENDENT_DURABLE_SOURCE = "INDEPENDENT_DURABLE_SOURCE"
    NOT_DURABLE_FOR_EXACT_REPLAY = "NOT_DURABLE_FOR_EXACT_REPLAY"
    UNKNOWN = "UNKNOWN"


class FutureMutationTreatment(_ValueEnum):
    WAL = "WAL"
    IMMUTABLE_EXTERNAL_REF = "IMMUTABLE_EXTERNAL_REF"


class PayloadTelemetryPolicy(_ValueEnum):
    METADATA_ONLY = "METADATA_ONLY"
    AGGREGATE_REDACTED = "AGGREGATE_REDACTED"
    FORBIDDEN = "FORBIDDEN"


@dataclass(frozen=True)
class MutationDeclaration:
    mutationId: str
    targetStateIds: Tuple[str, ...]
    criticality: MutationCriticality
    sourceFamily: str
    deterministicReducerExpected: bool
    currentPersistenceRoute: str
    currentWalCoverage: WalCoverage
    futureTreatment: FutureMutationTreatment
    syncDurabilityCandidate: bool
    privacyClass: PrivacyClass
    payloadTelemetryPolicy: PayloadTelemetryPolicy
    notes: str


def _m(mid: str, targets: Tuple[str, ...], criticality: MutationCriticality,
       source: str, reducer: bool, route: str, coverage: WalCoverage,
       future: FutureMutationTreatment, sync: bool, privacy: PrivacyClass,
       policy: PayloadTelemetryPolicy, notes: str) -> MutationDeclaration:
    """Construct a mutation declaration without coercing any value."""
    return MutationDeclaration(mid, targets, criticality, source, reducer,
                               route, coverage, future, sync, privacy, policy,
                               notes)


_MUTATIONS: Tuple[MutationDeclaration, ...] = tuple(sorted((
    _m("core.ops_journal_transition", ("backend.ops_journal", "backend.ops_sequence_allocator"), MutationCriticality.EXACT_REQUIRED, "journal", True, "mission WAL inside tick; direct checkpoint outside tick", WalCoverage.PARTIAL, FutureMutationTreatment.WAL, True, PrivacyClass.INTERNAL, PayloadTelemetryPolicy.METADATA_ONLY, "Only selected aggregate patches are replayable."),
    _m("core.mission_transition", ("backend.missions", "backend.mission_artifacts", "backend.agent_queue"), MutationCriticality.EXACT_REQUIRED, "mission", True, "mission WAL then checkpoint", WalCoverage.PARTIAL, FutureMutationTreatment.WAL, True, PrivacyClass.INTERNAL, PayloadTelemetryPolicy.METADATA_ONLY, "Current payload covers a bounded transition state, not the whole tick."),
    _m("core.batch_cursor", ("backend.mission_durability",), MutationCriticality.EXACT_REQUIRED, "mission", True, "mission WAL then checkpoint", WalCoverage.PARTIAL, FutureMutationTreatment.WAL, True, PrivacyClass.SECURITY_SENSITIVE, PayloadTelemetryPolicy.METADATA_ONLY, "Cursor is present but chain/generation guarantees are absent."),
    _m("control.soak_stage1", ("backend.soak_state", "backend.stage1_control"), MutationCriticality.EXACT_REQUIRED, "control", True, "journal/direct checkpoint", WalCoverage.PARTIAL, FutureMutationTreatment.WAL, True, PrivacyClass.SECURITY_SENSITIVE, PayloadTelemetryPolicy.METADATA_ONLY, "No authority enablement in Phase A."),
    _m("market.ledger_update", ("market.ledger_source", "market.ledger_derived"), MutationCriticality.SOURCE_FACT, "market-data", True, "checkpoint; journal carries hashes/counts", WalCoverage.NOT_DURABLE_FOR_EXACT_REPLAY, FutureMutationTreatment.WAL, True, PrivacyClass.INTERNAL, PayloadTelemetryPolicy.METADATA_ONLY, "Future record must carry source facts or immutable source references."),
    _m("market.analytics_refresh", ("market.chart_intelligence", "market.today_source", "market.today_derived", "market.replay_receipts", "market.replay_contexts"), MutationCriticality.SOURCE_FACT, "market-analytics", True, "checkpoint; journal carries hashes", WalCoverage.NOT_DURABLE_FOR_EXACT_REPLAY, FutureMutationTreatment.WAL, False, PrivacyClass.INTERNAL, PayloadTelemetryPolicy.METADATA_ONLY, "Mixed source/derived refresh includes non-public source state; rebuild proof does not yet exist."),
    _m("market.verified_view_publish", ("market.verified_views",), MutationCriticality.SOURCE_FACT, "publication", True, "checkpoint only", WalCoverage.NOT_DURABLE_FOR_EXACT_REPLAY, FutureMutationTreatment.WAL, True, PrivacyClass.PUBLIC_METADATA, PayloadTelemetryPolicy.METADATA_ONLY, "Published identity and pointer changes require exact ordering."),
    _m("market.asset_report_update", ("market.asset_reports",), MutationCriticality.CONDITIONAL, "market-analytics", True, "checkpoint only", WalCoverage.UNKNOWN, FutureMutationTreatment.WAL, False, PrivacyClass.PUBLIC_METADATA, PayloadTelemetryPolicy.METADATA_ONLY, "F: authority semantics unresolved, so preserve."),
    _m("deployment.build_identity_update", ("external.ec2_build_identity",), MutationCriticality.EXACT_REQUIRED, "deployment", True, "EC2-local independently verified file", WalCoverage.INDEPENDENT_DURABLE_SOURCE, FutureMutationTreatment.IMMUTABLE_EXTERNAL_REF, True, PrivacyClass.SECURITY_SENSITIVE, PayloadTelemetryPolicy.METADATA_ONLY, "Separate deployment authority; future recovery binds identity references only."),
    _m("osint.investigation_update", ("backend.term_overlay", "backend.learned_memory", "secondary.osint_investigation_store"), MutationCriticality.EXACT_REQUIRED, "osint", False, "checkpoint/local memory", WalCoverage.NOT_DURABLE_FOR_EXACT_REPLAY, FutureMutationTreatment.WAL, True, PrivacyClass.INTERNAL, PayloadTelemetryPolicy.METADATA_ONLY, "Provider/model as-of results are not deterministic replay inputs."),
    _m("osint.accepted_work", ("backend.agent_queue", "secondary.url_and_agent_work"), MutationCriticality.EXACT_REQUIRED, "queue", True, "checkpoint or memory only", WalCoverage.PARTIAL, FutureMutationTreatment.WAL, True, PrivacyClass.OWNER_PRIVATE, PayloadTelemetryPolicy.FORBIDDEN, "Only byte/count/latency aggregates are allowed."),
    _m("owner.intelligence_update", ("backend.term_overlay", "secondary.owner_intelligence"), MutationCriticality.EXACT_REQUIRED, "owner-intel", True, "memory/local temp/private Git best effort", WalCoverage.UNKNOWN, FutureMutationTreatment.WAL, True, PrivacyClass.OWNER_PRIVATE, PayloadTelemetryPolicy.FORBIDDEN, "Acknowledged owner edits require one future authority transaction."),
    _m("decision.job_update", ("secondary.decision_jobs", "backend.forecasts", "backend.outcomes"), MutationCriticality.EXACT_REQUIRED, "decision", True, "memory/journal/checkpoint depending path", WalCoverage.PARTIAL, FutureMutationTreatment.WAL, True, PrivacyClass.INTERNAL, PayloadTelemetryPolicy.METADATA_ONLY, "Job creation is volatile; outcome transitions are partly covered."),
    _m("benchmark.lifecycle", ("backend.formal_benchmarks",), MutationCriticality.EXACT_REQUIRED, "benchmark", True, "direct checkpoint", WalCoverage.NOT_DURABLE_FOR_EXACT_REPLAY, FutureMutationTreatment.WAL, True, PrivacyClass.INTERNAL, PayloadTelemetryPolicy.METADATA_ONLY, "One-shot consumption must be logged before acknowledgement."),
    _m("foundation.lifecycle", ("backend.foundation_jobs",), MutationCriticality.EXACT_REQUIRED, "foundation", True, "local sidecar plus checkpoint", WalCoverage.NOT_DURABLE_FOR_EXACT_REPLAY, FutureMutationTreatment.WAL, True, PrivacyClass.INTERNAL, PayloadTelemetryPolicy.METADATA_ONLY, "Same-volume sidecar is not independent cold durability."),
    _m("ai.result_and_cost", ("backend.cost_policy", "secondary.ai_results", "secondary.ai_gate_cost_security"), MutationCriticality.EXACT_REQUIRED, "ai", False, "memory/local temp/checkpoint", WalCoverage.NOT_DURABLE_FOR_EXACT_REPLAY, FutureMutationTreatment.WAL, True, PrivacyClass.OWNER_PRIVATE, PayloadTelemetryPolicy.FORBIDDEN, "Never export prompt/output/content."),
    _m("intelligence.fact_update", ("secondary.intelligence_facts", "secondary.event_backbone", "secondary.tdnet_timing"), MutationCriticality.SOURCE_FACT, "intelligence", False, "local temp/memory then async Git", WalCoverage.NOT_DURABLE_FOR_EXACT_REPLAY, FutureMutationTreatment.WAL, True, PrivacyClass.INTERNAL, PayloadTelemetryPolicy.METADATA_ONLY, "First-seen and provider facts can be revised or lost."),
    _m("queue.accepted_work", ("secondary.accepted_queues",), MutationCriticality.EXACT_REQUIRED, "queue", True, "local temp", WalCoverage.NOT_DURABLE_FOR_EXACT_REPLAY, FutureMutationTreatment.WAL, True, PrivacyClass.INTERNAL, PayloadTelemetryPolicy.METADATA_ONLY, "Accepted request queues are not remotely durable."),
    _m("security.nonce_reservation", ("backend.nonce_authority", "backend.remote_recovery_required"), MutationCriticality.EXACT_REQUIRED, "security", True, "fsynced local nonce anchor plus keyed overlay when configured", WalCoverage.NOT_DURABLE_FOR_EXACT_REPLAY, FutureMutationTreatment.WAL, True, PrivacyClass.SECURITY_SENSITIVE, PayloadTelemetryPolicy.METADATA_ONLY, "Never records nonce/key material; production keyed mode is currently unconfigured."),
    _m("learning.materialization", ("secondary.learning_materialization",), MutationCriticality.CONDITIONAL, "learning", True, "local temp then async Git", WalCoverage.NOT_DURABLE_FOR_EXACT_REPLAY, FutureMutationTreatment.WAL, False, PrivacyClass.INTERNAL, PayloadTelemetryPolicy.METADATA_ONLY, "C remains preserved until proof."),
    _m("legacy.scan_update", ("secondary.legacy_scan_state", "secondary.buy_candidates", "secondary.sweep_cooldown"), MutationCriticality.CONDITIONAL, "legacy", False, "local temp", WalCoverage.UNKNOWN, FutureMutationTreatment.WAL, False, PrivacyClass.OWNER_PRIVATE, PayloadTelemetryPolicy.FORBIDDEN, "F: owner semantics required."),
    _m("legacy.prediction_update", ("secondary.legacy_predictions",), MutationCriticality.CONDITIONAL, "legacy-prediction", False, "EC2 predictions.jsonl", WalCoverage.NOT_DURABLE_FOR_EXACT_REPLAY, FutureMutationTreatment.WAL, True, PrivacyClass.OWNER_PRIVATE, PayloadTelemetryPolicy.FORBIDDEN, "Disposition deferred to Prediction Ledger."),
    _m("external.private_git_write", ("external.private_git_objects", "client.vault_ciphertext"), MutationCriticality.EXACT_REQUIRED, "external-private", False, "private Git object", WalCoverage.INDEPENDENT_DURABLE_SOURCE, FutureMutationTreatment.IMMUTABLE_EXTERNAL_REF, True, PrivacyClass.OWNER_PRIVATE, PayloadTelemetryPolicy.FORBIDDEN, "Successful immutable/object writes need identities bound by future manifests."),
    _m("external.public_ledger_write", ("external.public_ledger_originals",), MutationCriticality.SOURCE_FACT, "external-public", False, "public Git ledger", WalCoverage.INDEPENDENT_DURABLE_SOURCE, FutureMutationTreatment.IMMUTABLE_EXTERNAL_REF, False, PrivacyClass.PUBLIC_METADATA, PayloadTelemetryPolicy.METADATA_ONLY, "Future manifests bind exact commits; Phase A does not change writers."),
    _m("durability.receipt_ack", ("backend.remote_ack_cycle", "backend.receipt_queue"), MutationCriticality.EXACT_REQUIRED, "durability", True, "Git readback plus local fsynced queue/checkpoint", WalCoverage.INDEPENDENT_DURABLE_SOURCE, FutureMutationTreatment.IMMUTABLE_EXTERNAL_REF, True, PrivacyClass.SECURITY_SENSITIVE, PayloadTelemetryPolicy.METADATA_ONLY, "Legacy compact ACK health is not exact cold recovery proof."),
    _m("startup.restore_transition", ("backend.foundation_jobs", "backend.soak_state", "backend.mission_durability"), MutationCriticality.EXACT_REQUIRED, "startup", True, "startup restore/checkpoint", WalCoverage.UNKNOWN, FutureMutationTreatment.WAL, True, PrivacyClass.SECURITY_SENSITIVE, PayloadTelemetryPolicy.METADATA_ONLY, "Restore may terminalize interrupted jobs/Soak."),
    _m("client.local_mutation", ("client.core_private_state", "client.risk_lines", "client.replay_drawings", "client.pasted_research", "client.dismissed_gaps", "client.browser_caches"), MutationCriticality.CONDITIONAL, "client", False, "client storage only", WalCoverage.UNKNOWN, FutureMutationTreatment.IMMUTABLE_EXTERNAL_REF, False, PrivacyClass.CLIENT_PRIVATE, PayloadTelemetryPolicy.FORBIDDEN, "Explicit boundary only; backend never receives plaintext."),
), key=lambda row: row.mutationId))


def states() -> Tuple[StateDeclaration, ...]:
    return _STATES


def mutations() -> Tuple[MutationDeclaration, ...]:
    return _MUTATIONS


def state_by_id() -> Dict[str, StateDeclaration]:
    return {row.stateId: row for row in _STATES}


def mutation_by_id() -> Dict[str, MutationDeclaration]:
    return {row.mutationId: row for row in _MUTATIONS}


def mutation_by_class() -> Dict[str, MutationDeclaration]:
    """Compatibility spelling for audited inventory tooling."""
    return mutation_by_id()


def mutation_allows_public_telemetry(
        row: Any, state_index: Any = _USE_BUILTIN) -> bool:
    """Fail-closed mutation-identifier authorization; never payload policy."""
    if type(row) is not MutationDeclaration:
        return False
    states_by_id = state_by_id() if state_index is _USE_BUILTIN else state_index
    if type(states_by_id) is not dict or \
            type(row.privacyClass) is not PrivacyClass or \
            row.privacyClass is not PrivacyClass.PUBLIC_METADATA or \
            type(row.payloadTelemetryPolicy) is not PayloadTelemetryPolicy or \
            row.payloadTelemetryPolicy is not PayloadTelemetryPolicy.METADATA_ONLY or \
            type(row.targetStateIds) is not tuple or not row.targetStateIds:
        return False
    for target in row.targetStateIds:
        if type(target) is not str:
            return False
        target_row = states_by_id.get(target)
        if not state_allows_public_telemetry(target_row):
            return False
    return True


def _prefix(kind: str, index: int, value: Any) -> str:
    if type(value) is str and 0 < len(value) <= _MAX_STABLE_ID and \
            _STABLE_ID_RE.fullmatch(value):
        return value
    return f"{kind}[{index}]"


def _validate_text(errors: set[str], prefix: str, field: str, value: Any,
                   limit: int, *, ascii_only: bool = False,
                   pattern: Any = None) -> bool:
    if type(value) is not str:
        errors.add(f"{prefix}:{field}:not_exact_str")
        return False
    if not value or value != value.strip():
        errors.add(f"{prefix}:{field}:empty_or_untrimmed")
        return False
    if len(value) > limit:
        errors.add(f"{prefix}:{field}:too_long")
        return False
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        errors.add(f"{prefix}:{field}:control_character")
        return False
    if ascii_only and not value.isascii():
        errors.add(f"{prefix}:{field}:non_ascii")
        return False
    if pattern is not None and pattern.fullmatch(value) is None:
        errors.add(f"{prefix}:{field}:invalid_format")
        return False
    return True


def _validate_bool(errors: set[str], prefix: str, field: str,
                   value: Any) -> bool:
    if type(value) is not bool:
        errors.add(f"{prefix}:{field}:not_exact_bool")
        return False
    return True


def _validate_enum(errors: set[str], prefix: str, field: str, value: Any,
                   expected: type[Enum]) -> bool:
    if type(value) is not expected:
        errors.add(f"{prefix}:{field}:not_exact_enum")
        return False
    return True


def _validate_string_tuple(errors: set[str], prefix: str, field: str,
                           value: Any, *, item_limit: int = _MAX_TUPLE_TEXT,
                           pattern: Any = None, required: bool = False) -> bool:
    if type(value) is not tuple:
        errors.add(f"{prefix}:{field}:not_exact_tuple")
        return False
    if required and not value:
        errors.add(f"{prefix}:{field}:required")
    if len(value) > _MAX_TUPLE_ITEMS:
        errors.add(f"{prefix}:{field}:too_many_items")
        return False
    valid = True
    exact_items = []
    for item_index, item in enumerate(value):
        if not _validate_text(
                errors, prefix, f"{field}[{item_index}]", item, item_limit,
                ascii_only=pattern is not None, pattern=pattern):
            valid = False
        elif type(item) is str:
            exact_items.append(item)
    if len(exact_items) != len(set(exact_items)):
        errors.add(f"{prefix}:{field}:duplicate_item")
        valid = False
    return valid and (len(value) > 0 or not required)


def _validate_state_row(errors: set[str], row: StateDeclaration,
                        index: int) -> None:
    prefix = _prefix("state", index, row.stateId)
    state_id_valid = _validate_text(
        errors, prefix, "stateId", row.stateId, _MAX_STABLE_ID,
        ascii_only=True, pattern=_STABLE_ID_RE)
    if state_id_valid:
        prefix = row.stateId
    _validate_text(errors, prefix, "humanName", row.humanName, _MAX_NAME)
    classification_valid = _validate_enum(
        errors, prefix, "classification", row.classification, Classification)
    preserve_valid = _validate_bool(
        errors, prefix, "mustPreserveNow", row.mustPreserveNow)
    _validate_enum(errors, prefix, "currentStorageKind",
                   row.currentStorageKind, StorageKind)
    _validate_enum(errors, prefix, "currentRecoveryCoverage",
                   row.currentRecoveryCoverage, RecoveryCoverage)
    _validate_text(errors, prefix, "mutationDomain", row.mutationDomain,
                   _MAX_DOMAIN, ascii_only=True, pattern=_TOKEN_RE)
    privacy_valid = _validate_enum(
        errors, prefix, "privacyClass", row.privacyClass, PrivacyClass)
    secret_valid = _validate_bool(
        errors, prefix, "containsSecret", row.containsSecret)
    private_valid = _validate_bool(
        errors, prefix, "containsOwnerPrivateData",
        row.containsOwnerPrivateData)
    telemetry_valid = _validate_bool(
        errors, prefix, "allowedInTelemetry", row.allowedInTelemetry)
    future_valid = _validate_enum(
        errors, prefix, "intendedFutureDurability",
        row.intendedFutureDurability, FutureDurability)
    _validate_enum(errors, prefix, "sourceDerivedStatus",
                   row.sourceDerivedStatus, StateNature)
    rebuild_valid = _validate_string_tuple(
        errors, prefix, "rebuildRequirements", row.rebuildRequirements)
    reducer_valid = _validate_enum(
        errors, prefix, "mutationRegistryExpectation",
        row.mutationRegistryExpectation, ReducerExpectation)
    _validate_text(errors, prefix, "evidenceOwnerModule",
                   row.evidenceOwnerModule, _MAX_OWNER_MODULE,
                   ascii_only=True)
    _validate_string_tuple(
        errors, prefix, "checkpointKeys", row.checkpointKeys,
        item_limit=64, pattern=_CHECKPOINT_KEY_RE)
    _validate_text(errors, prefix, "notes", row.notes, _MAX_NOTES)
    if row.ephemeralRetentionReason is not None:
        _validate_text(errors, prefix, "ephemeralRetentionReason",
                       row.ephemeralRetentionReason, _MAX_NOTES)

    if classification_valid and preserve_valid and future_valid:
        classification = row.classification
        future = row.intendedFutureDurability
        if classification in (Classification.A, Classification.B):
            if row.mustPreserveNow is not True:
                errors.add(f"{prefix}:classification_must_preserve")
            if future not in (FutureDurability.FULL_PLUS_WAL,
                              FutureDurability.IMMUTABLE_EXTERNAL_REF):
                errors.add(f"{prefix}:classification_future_incompatible")
        elif classification is Classification.C:
            if row.mustPreserveNow is not True:
                errors.add(f"{prefix}:v1_rebuild_state_must_preserve")
            if future is not FutureDurability.REBUILD_AFTER_PROOF or \
                    not rebuild_valid or not row.rebuildRequirements:
                errors.add(f"{prefix}:rebuild_contract_incomplete")
            if reducer_valid and row.mutationRegistryExpectation is not \
                    ReducerExpectation.REQUIRED:
                errors.add(f"{prefix}:rebuild_reducer_required")
        elif classification is Classification.D:
            if row.mustPreserveNow is not True:
                errors.add(f"{prefix}:v1_reacquirable_state_must_preserve")
            if future is not FutureDurability.REACQUIRE_AFTER_CONTRACT or \
                    not rebuild_valid or not row.rebuildRequirements:
                errors.add(f"{prefix}:reacquisition_contract_incomplete")
        elif classification is Classification.E:
            if future is FutureDurability.EPHEMERAL:
                if row.mustPreserveNow is not False:
                    errors.add(f"{prefix}:ephemeral_state_must_not_preserve")
            elif future is FutureDurability.FULL_PLUS_WAL:
                if row.mustPreserveNow is not True:
                    errors.add(f"{prefix}:retained_cache_must_preserve")
                reason = row.ephemeralRetentionReason
                if type(reason) is not str or not reason.strip():
                    errors.add(f"{prefix}:retained_cache_reason_required")
            else:
                errors.add(f"{prefix}:classification_future_incompatible")
        elif classification is Classification.F:
            if row.mustPreserveNow is not True:
                errors.add(f"{prefix}:classification_must_preserve")
            if future is not FutureDurability.UNRESOLVED:
                errors.add(f"{prefix}:unresolved_state_must_remain_unresolved")
            if reducer_valid and row.mutationRegistryExpectation is not \
                    ReducerExpectation.UNRESOLVED:
                errors.add(f"{prefix}:unresolved_reducer_must_remain_unresolved")

    if privacy_valid and secret_valid and private_valid:
        if row.privacyClass is PrivacyClass.PUBLIC_METADATA and \
                (row.containsSecret is not False or
                 row.containsOwnerPrivateData is not False):
            errors.add(f"{prefix}:public_metadata_contains_private_content")
        if row.privacyClass is PrivacyClass.SECRET and \
                row.containsSecret is not True:
            errors.add(f"{prefix}:secret_privacy_requires_secret_flag")
        if row.privacyClass in (
                PrivacyClass.OWNER_PRIVATE, PrivacyClass.CLIENT_PRIVATE,
                PrivacyClass.CLIENT_OPAQUE) and \
                row.containsOwnerPrivateData is not True:
            errors.add(f"{prefix}:private_privacy_requires_private_flag")
    if telemetry_valid and row.allowedInTelemetry is True and \
            not state_allows_public_telemetry(row):
        errors.add(f"{prefix}:incompatible_public_telemetry")


def _validate_mutation_row(errors: set[str], row: MutationDeclaration,
                           index: int,
                           state_index: Dict[str, StateDeclaration]) -> None:
    prefix = _prefix("mutation", index, row.mutationId)
    mutation_id_valid = _validate_text(
        errors, prefix, "mutationId", row.mutationId, _MAX_STABLE_ID,
        ascii_only=True, pattern=_STABLE_ID_RE)
    if mutation_id_valid:
        prefix = row.mutationId
    targets_valid = _validate_string_tuple(
        errors, prefix, "targetStateIds", row.targetStateIds,
        item_limit=_MAX_STABLE_ID, pattern=_STABLE_ID_RE, required=True)
    _validate_enum(errors, prefix, "criticality", row.criticality,
                   MutationCriticality)
    _validate_text(errors, prefix, "sourceFamily", row.sourceFamily,
                   _MAX_DOMAIN, ascii_only=True, pattern=_TOKEN_RE)
    _validate_bool(errors, prefix, "deterministicReducerExpected",
                   row.deterministicReducerExpected)
    _validate_text(errors, prefix, "currentPersistenceRoute",
                   row.currentPersistenceRoute, _MAX_OWNER_MODULE,
                   ascii_only=True)
    _validate_enum(errors, prefix, "currentWalCoverage",
                   row.currentWalCoverage, WalCoverage)
    _validate_enum(errors, prefix, "futureTreatment",
                   row.futureTreatment, FutureMutationTreatment)
    _validate_bool(errors, prefix, "syncDurabilityCandidate",
                   row.syncDurabilityCandidate)
    privacy_valid = _validate_enum(
        errors, prefix, "privacyClass", row.privacyClass, PrivacyClass)
    policy_valid = _validate_enum(
        errors, prefix, "payloadTelemetryPolicy",
        row.payloadTelemetryPolicy, PayloadTelemetryPolicy)
    _validate_text(errors, prefix, "notes", row.notes, _MAX_NOTES)

    if targets_valid:
        for target in row.targetStateIds:
            if target not in state_index:
                errors.add(f"{prefix}:unknown_target:{target}")
    if privacy_valid and policy_valid and \
            row.privacyClass is PrivacyClass.PUBLIC_METADATA and \
            row.payloadTelemetryPolicy is PayloadTelemetryPolicy.METADATA_ONLY and \
            not mutation_allows_public_telemetry(row, state_index):
        errors.add(f"{prefix}:public_mutation_targets_nonpublic_state")


def validate_registry(state_rows: Any = _USE_BUILTIN,
                      mutation_rows: Any = _USE_BUILTIN) -> Tuple[str, ...]:
    """Validate every input value without coercion or arbitrary iteration."""
    states_value = _STATES if state_rows is _USE_BUILTIN else state_rows
    mutations_value = _MUTATIONS if mutation_rows is _USE_BUILTIN else mutation_rows
    errors: set[str] = set()

    if type(states_value) is not tuple:
        errors.add("state_registry:not_exact_tuple")
        states_value = ()
    elif len(states_value) > _MAX_REGISTRY_ROWS:
        errors.add("state_registry:too_many_rows")
        states_value = ()
    if type(mutations_value) is not tuple:
        errors.add("mutation_registry:not_exact_tuple")
        mutations_value = ()
    elif len(mutations_value) > _MAX_REGISTRY_ROWS:
        errors.add("mutation_registry:too_many_rows")
        mutations_value = ()

    exact_states = []
    for index, row in enumerate(states_value):
        if type(row) is not StateDeclaration:
            errors.add(f"state[{index}]:not_exact_StateDeclaration")
            continue
        exact_states.append(row)
        _validate_state_row(errors, row, index)

    state_ids = [row.stateId for row in exact_states
                 if type(row.stateId) is str]
    if len(state_ids) == len(exact_states) and state_ids != sorted(state_ids):
        errors.add("state_registry:not_sorted")
    if len(state_ids) != len(set(state_ids)):
        errors.add("state_registry:duplicate_state_id")
    state_index = {row.stateId: row for row in exact_states
                   if type(row.stateId) is str}

    exact_mutations = []
    for index, row in enumerate(mutations_value):
        if type(row) is not MutationDeclaration:
            errors.add(f"mutation[{index}]:not_exact_MutationDeclaration")
            continue
        exact_mutations.append(row)
        _validate_mutation_row(errors, row, index, state_index)

    mutation_ids = [row.mutationId for row in exact_mutations
                    if type(row.mutationId) is str]
    if len(mutation_ids) == len(exact_mutations) and \
            mutation_ids != sorted(mutation_ids):
        errors.add("mutation_registry:not_sorted")
    if len(mutation_ids) != len(set(mutation_ids)):
        errors.add("mutation_registry:duplicate_mutation_id")
    return tuple(sorted(errors))


def _serialize_state(row: StateDeclaration) -> Dict[str, Any]:
    return {
        "stateId": row.stateId,
        "humanName": row.humanName,
        "classification": row.classification.value,
        "mustPreserveNow": row.mustPreserveNow,
        "currentStorageKind": row.currentStorageKind.value,
        "currentRecoveryCoverage": row.currentRecoveryCoverage.value,
        "mutationDomain": row.mutationDomain,
        "privacyClass": row.privacyClass.value,
        "containsSecret": row.containsSecret,
        "containsOwnerPrivateData": row.containsOwnerPrivateData,
        "allowedInTelemetry": row.allowedInTelemetry,
        "intendedFutureDurability": row.intendedFutureDurability.value,
        "sourceDerivedStatus": row.sourceDerivedStatus.value,
        "rebuildRequirements": list(row.rebuildRequirements),
        "mutationRegistryExpectation": row.mutationRegistryExpectation.value,
        "evidenceOwnerModule": row.evidenceOwnerModule,
        "checkpointKeys": list(row.checkpointKeys),
        "notes": row.notes,
        "ephemeralRetentionReason": row.ephemeralRetentionReason,
    }


def _serialize_mutation(row: MutationDeclaration) -> Dict[str, Any]:
    return {
        "mutationId": row.mutationId,
        "targetStateIds": list(row.targetStateIds),
        "criticality": row.criticality.value,
        "sourceFamily": row.sourceFamily,
        "deterministicReducerExpected": row.deterministicReducerExpected,
        "currentPersistenceRoute": row.currentPersistenceRoute,
        "currentWalCoverage": row.currentWalCoverage.value,
        "futureTreatment": row.futureTreatment.value,
        "syncDurabilityCandidate": row.syncDurabilityCandidate,
        "privacyClass": row.privacyClass.value,
        "payloadTelemetryPolicy": row.payloadTelemetryPolicy.value,
        "notes": row.notes,
    }


def state_registry_document() -> Dict[str, Any]:
    return {
        "schemaVersion": REGISTRY_SCHEMA,
        "authoritative": False,
        "states": [_serialize_state(row) for row in _STATES],
    }


def mutation_registry_document() -> Dict[str, Any]:
    return {
        "schemaVersion": MUTATION_REGISTRY_SCHEMA,
        "authoritative": False,
        "mutations": [_serialize_mutation(row) for row in _MUTATIONS],
    }


def _policy_contract_document() -> Dict[str, Any]:
    return {
        "schemaVersion": REGISTRY_POLICY_SCHEMA,
        "exactTypeSemantics": True,
        "publicTelemetryPrivacyClasses": [
            PrivacyClass.PUBLIC_METADATA.value],
        "classificationFutureDurability": {
            Classification.A.value: [
                FutureDurability.FULL_PLUS_WAL.value,
                FutureDurability.IMMUTABLE_EXTERNAL_REF.value],
            Classification.B.value: [
                FutureDurability.FULL_PLUS_WAL.value,
                FutureDurability.IMMUTABLE_EXTERNAL_REF.value],
            Classification.C.value: [
                FutureDurability.REBUILD_AFTER_PROOF.value],
            Classification.D.value: [
                FutureDurability.REACQUIRE_AFTER_CONTRACT.value],
            Classification.E.value: [
                FutureDurability.EPHEMERAL.value,
                FutureDurability.FULL_PLUS_WAL.value],
            Classification.F.value: [
                FutureDurability.UNRESOLVED.value],
        },
        "v1MustPreserveClassifications": [
            member.value for member in (
                Classification.A, Classification.B, Classification.C,
                Classification.D, Classification.F)],
        "publicMutationRequirements": {
            "privacyClass": PrivacyClass.PUBLIC_METADATA.value,
            "payloadTelemetryPolicy":
                PayloadTelemetryPolicy.METADATA_ONLY.value,
            "allTargetsPublicTelemetrySafe": True,
        },
    }


def registry_document() -> Dict[str, Any]:
    """Combined declaration/policy document; internal only in PR A."""
    return {
        "schemaVersion": REGISTRY_POLICY_SCHEMA,
        "authoritative": False,
        "stateRegistry": state_registry_document(),
        "mutationRegistry": mutation_registry_document(),
        "policyContract": _policy_contract_document(),
    }


def registry_policy_canonical_bytes() -> bytes:
    return json.dumps(
        registry_document(), ensure_ascii=False, allow_nan=False,
        sort_keys=True, separators=(",", ":")).encode("utf-8")


def registry_policy_sha256() -> str:
    return hashlib.sha256(registry_policy_canonical_bytes()).hexdigest()


def registered_checkpoint_keys() -> Tuple[str, ...]:
    return tuple(sorted({key for row in _STATES for key in row.checkpointKeys}))


def unregistered_state_ids(observed_state_ids: Any) -> Tuple[str, ...]:
    """Test/discovery helper.  It is never a startup or recovery authority."""
    if type(observed_state_ids) is not tuple:
        return ("<invalid_observed_state_ids_container>",)
    if len(observed_state_ids) > _MAX_REGISTRY_ROWS or any(
            type(value) is not str for value in observed_state_ids):
        return ("<invalid_observed_state_ids>",)
    known = set(state_by_id())
    return tuple(sorted({value for value in observed_state_ids
                         if value not in known}))


def unregistered_checkpoint_keys(observed_checkpoint_keys: Any) -> Tuple[str, ...]:
    """Literal top-level checkpoint tripwire helper for tests only."""
    if type(observed_checkpoint_keys) is not tuple:
        return ("<invalid_checkpoint_inventory_container>",)
    if len(observed_checkpoint_keys) > _MAX_REGISTRY_ROWS or any(
            type(value) is not str for value in observed_checkpoint_keys):
        return ("<invalid_checkpoint_inventory>",)
    known = set(registered_checkpoint_keys())
    return tuple(sorted({value for value in observed_checkpoint_keys
                         if value not in known}))


def registry_summary() -> Dict[str, Any]:
    classification_counts = {row.value: 0 for row in Classification}
    privacy_counts = {row.value: 0 for row in PrivacyClass}
    coverage_counts = {row.value: 0 for row in WalCoverage}
    for row in _STATES:
        classification_counts[row.classification.value] += 1
        privacy_counts[row.privacyClass.value] += 1
    for row in _MUTATIONS:
        coverage_counts[row.currentWalCoverage.value] += 1
    errors = validate_registry()
    return {
        "schemaVersion": REGISTRY_POLICY_SCHEMA,
        "stateCount": len(_STATES),
        "classificationCounts": classification_counts,
        "mustPreserveCount": sum(
            1 for row in _STATES if row.mustPreserveNow),
        "privacyCounts": privacy_counts,
        "telemetrySafeStateCount": sum(
            1 for row in _STATES if state_allows_public_telemetry(row)),
        "unresolvedStateIds": [
            row.stateId for row in _STATES
            if row.classification is Classification.F],
        "mutationClassCount": len(_MUTATIONS),
        "telemetrySafeMutationCount": sum(
            1 for row in _MUTATIONS
            if mutation_allows_public_telemetry(row)),
        "currentWalCoverageCounts": coverage_counts,
        "registryPolicySha256": registry_policy_sha256(),
        "validationStatus": "valid" if not errors else "invalid",
        "validationErrors": list(errors),
        "shadowOnly": True,
    }


REGISTRY_VALIDATION_ERRORS = validate_registry()
REGISTRY_POLICY_SHA256 = registry_policy_sha256()
