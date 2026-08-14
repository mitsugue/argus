"""Recovery Phase A registries (shadow metadata; never recovery authority).

This module deliberately contains declarations and validation only.  Importing it
must not read or write durable state, select a checkpoint, or alter a mutation.
Unknowns are kept explicit and conservative so later FullGeneration/WAL work
cannot silently treat an unproved state as disposable.
"""

from dataclasses import asdict, dataclass
from enum import Enum
import re
from typing import Any, Dict, Iterable, List, Optional, Tuple


REGISTRY_SCHEMA = "argus-authoritative-state-registry-v1"
MUTATION_REGISTRY_SCHEMA = "argus-mutation-class-registry-v1"
_STABLE_ID_RE = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$")


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


# Public telemetry is an affirmative registry capability.  INTERNAL metadata
# may be opted in when its identifier/count semantics are explicitly reviewed;
# security, owner, secret and client boundaries can never be opted in.
PUBLIC_TELEMETRY_COMPATIBLE_PRIVACY = frozenset({
    PrivacyClass.PUBLIC_METADATA,
    PrivacyClass.INTERNAL,
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
class StateDefinition:
    stateId: str
    name: str
    classification: Classification
    mustPreserveNow: bool
    currentStorageKind: StorageKind
    currentRecoveryCoverage: RecoveryCoverage
    mutationDomain: str
    privacyClass: PrivacyClass
    containsSecret: bool
    containsOwnerPrivateData: bool
    allowedInTelemetry: bool
    intendedFutureDurability: FutureDurability
    stateNature: StateNature
    requiredRebuildInputs: Tuple[str, ...]
    reducerExpectation: ReducerExpectation
    evidenceOwnerModule: str
    notes: str
    rebuildProofAccepted: bool = False
    reacquisitionContractAccepted: bool = False
    ephemeralFullWalReason: Optional[str] = None
    checkpointKeys: Tuple[str, ...] = ()


def _s(state_id: str, name: str, classification: Classification,
       storage: StorageKind, coverage: RecoveryCoverage, domain: str,
       privacy: PrivacyClass, future: FutureDurability, nature: StateNature,
       reducer: ReducerExpectation, owner: str, notes: str, *,
       keys: Tuple[str, ...] = (), inputs: Tuple[str, ...] = (),
       private: bool = False, secret: bool = False,
       telemetry: bool = False, preserve: Optional[bool] = None,
       proof: bool = False, contract: bool = False) -> StateDefinition:
    # The explicit default is conservative and is materialized into every row.
    if preserve is None:
        preserve = classification != Classification.E
    return StateDefinition(
        state_id, name, classification, bool(preserve), storage, coverage,
        domain, privacy, bool(secret), bool(private), bool(telemetry), future,
        nature, tuple(inputs), reducer, owner, notes,
        rebuildProofAccepted=bool(proof),
        reacquisitionContractAccepted=bool(contract), checkpointKeys=tuple(keys))


def state_allows_public_telemetry(row: StateDefinition) -> bool:
    """Return the one fail-closed state identifier authorization decision."""
    return bool(
        isinstance(row, StateDefinition) and
        row.allowedInTelemetry is True and
        row.privacyClass in PUBLIC_TELEMETRY_COMPATIBLE_PRIVACY and
        row.containsSecret is False and
        row.containsOwnerPrivateData is False)


_STATES: Tuple[StateDefinition, ...] = tuple(sorted((
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
       ReducerExpectation.REQUIRED, "scanner.py", "Build-scoped control; no authority change in Phase A.", keys=("soak", "soakHistory", "soakControl", "soakLastPersistAt"), telemetry=True),
    _s("backend.stage1_control", "Checkpoint V2 Stage1 control", Classification.A,
       StorageKind.CHECKPOINT_SECTION, RecoveryCoverage.LEGACY_FULL, "control",
       PrivacyClass.SECURITY_SENSITIVE, FutureDurability.FULL_PLUS_WAL, StateNature.CONTROL,
       ReducerExpectation.REQUIRED, "scanner.py", "Stage1 remains disabled and non-authoritative.", keys=("checkpointV2Stage1Control",), telemetry=False),
    _s("backend.missions", "Research missions", Classification.A,
       StorageKind.CHECKPOINT_SECTION, RecoveryCoverage.ENCRYPTED_OVERLAY_WHEN_CONFIGURED, "mission",
       PrivacyClass.INTERNAL, FutureDurability.FULL_PLUS_WAL, StateNature.SOURCE,
       ReducerExpectation.REQUIRED, "scanner.py", "Current WAL covers only some mission transitions.", keys=("missions",), telemetry=True),
    _s("backend.mission_windows", "Mission scheduling windows", Classification.A,
       StorageKind.CHECKPOINT_SECTION, RecoveryCoverage.ENCRYPTED_OVERLAY_WHEN_CONFIGURED, "mission",
       PrivacyClass.INTERNAL, FutureDurability.FULL_PLUS_WAL, StateNature.CONTROL,
       ReducerExpectation.REQUIRED, "scanner.py", "Window transitions are not fully redo-logged.", keys=("missionWindows",), telemetry=True),
    _s("backend.forecasts", "Decision forecasts", Classification.B,
       StorageKind.CHECKPOINT_SECTION, RecoveryCoverage.ENCRYPTED_OVERLAY_WHEN_CONFIGURED, "decision",
       PrivacyClass.INTERNAL, FutureDurability.FULL_PLUS_WAL, StateNature.SOURCE,
       ReducerExpectation.REQUIRED, "scanner.py", "Forward-live issuance history.", keys=("forecasts",), telemetry=True),
    _s("backend.outcomes", "Forecast outcomes", Classification.B,
       StorageKind.CHECKPOINT_SECTION, RecoveryCoverage.ENCRYPTED_OVERLAY_WHEN_CONFIGURED, "decision",
       PrivacyClass.INTERNAL, FutureDurability.FULL_PLUS_WAL, StateNature.SOURCE,
       ReducerExpectation.REQUIRED, "scanner.py", "Outcome observations and resolution state.", keys=("outcomes",), telemetry=True),
    _s("backend.incidents", "Durability and operational incidents", Classification.B,
       StorageKind.CHECKPOINT_SECTION, RecoveryCoverage.ENCRYPTED_OVERLAY_WHEN_CONFIGURED, "operations",
       PrivacyClass.INTERNAL, FutureDurability.FULL_PLUS_WAL, StateNature.SOURCE,
       ReducerExpectation.REQUIRED, "scanner.py", "Operational evidence.", keys=("incidents",), telemetry=True),
    _s("backend.ops_journal", "Operational journal and metadata", Classification.A,
       StorageKind.CHECKPOINT_SECTION, RecoveryCoverage.ENCRYPTED_OVERLAY_WHEN_CONFIGURED, "journal",
       PrivacyClass.INTERNAL, FutureDurability.FULL_PLUS_WAL, StateNature.SOURCE,
       ReducerExpectation.REQUIRED, "scanner.py/argus_state_journal.py", "Includes journal rows, metadata and compacted proof.", keys=("opsJournal", "opsJournalMeta", "opsJournalCompacted"), telemetry=True),
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
       ReducerExpectation.REQUIRED, "argus_research_benchmark*.py", "One-shot/holdout consumption must survive.", keys=("formalResearchBenchmark", "formalResearchBenchmarkV2"), telemetry=True),
    _s("backend.foundation_jobs", "Foundation job lifecycle", Classification.A,
       StorageKind.CHECKPOINT_SECTION, RecoveryCoverage.PARTIAL, "foundation",
       PrivacyClass.INTERNAL, FutureDurability.FULL_PLUS_WAL, StateNature.CONTROL,
       ReducerExpectation.REQUIRED, "argus_foundation_jobs.py", "Also has a local same-volume sidecar.", keys=("foundationJobs",), telemetry=True),
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
       ReducerExpectation.REQUIRED, "argus_market_ledger.py", "Observations/import/rollback receipts are authority.", keys=("marketLedger",), telemetry=True),
    _s("market.ledger_derived", "Market Ledger metrics, turning points and backtests", Classification.C,
       StorageKind.CHECKPOINT_SECTION, RecoveryCoverage.LEGACY_FULL, "market-data",
       PrivacyClass.INTERNAL, FutureDurability.REBUILD_AFTER_PROOF, StateNature.DERIVED,
       ReducerExpectation.REQUIRED, "argus_market_ledger.py", "No accepted hash-equal rebuild proof; preserve now.", keys=("marketLedger",), inputs=("exact observations", "method/build/schema", "detection timestamps"), telemetry=True),
    _s("market.chart_intelligence", "Chart intelligence", Classification.C,
       StorageKind.CHECKPOINT_SECTION, RecoveryCoverage.LEGACY_FULL, "market-analytics",
       PrivacyClass.PUBLIC_METADATA, FutureDurability.REBUILD_AFTER_PROOF, StateNature.DERIVED,
       ReducerExpectation.REQUIRED, "argus_chart_intelligence.py", "Preserve until exact-input/hash rebuild drill passes.", keys=("chartIntelligence",), inputs=("exact OHLCV", "ledger/events", "method/build/schema"), telemetry=True),
    _s("market.today_source", "Today intelligence short-selling source history", Classification.B,
       StorageKind.CHECKPOINT_SECTION, RecoveryCoverage.LEGACY_FULL, "market-data",
       PrivacyClass.INTERNAL, FutureDurability.FULL_PLUS_WAL, StateNature.SOURCE,
       ReducerExpectation.REQUIRED, "argus_today_intelligence.py", "Revision-bearing source rows.", keys=("todayIntelligence",), telemetry=True),
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
       ReducerExpectation.REQUIRED, "scanner.py", "Stable job IDs but volatile dedupe state.", telemetry=True),
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
       ReducerExpectation.REQUIRED, "scanner.py", "Cross-store writes are not atomic.", telemetry=True),
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
       ReducerExpectation.REQUIRED, "argus_learning_memory*.py", "Owner semantics and exact inputs/version are not yet proved.", inputs=("exact event cohorts", "method/build/schema"), telemetry=True),
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
       ReducerExpectation.UNRESOLVED, "scanner.py", "Audit intent and restart-reset policy require owner decision.", telemetry=True),
    _s("secondary.legacy_predictions", "Legacy predictions.jsonl", Classification.F,
       StorageKind.EC2_DISK, RecoveryCoverage.LOCAL_ONLY, "legacy-prediction",
       PrivacyClass.OWNER_PRIVATE, FutureDurability.UNRESOLVED, StateNature.SOURCE,
       ReducerExpectation.UNRESOLVED, "argus_ledger.py/render.yaml", "Must preserve until the later Prediction Ledger phase decides authority.", private=True, telemetry=False),
    _s("secondary.event_backbone", "24/7 event backbone", Classification.B,
       StorageKind.MEMORY_ONLY, RecoveryCoverage.EXTERNAL_BEST_EFFORT, "events",
       PrivacyClass.INTERNAL, FutureDurability.FULL_PLUS_WAL, StateNature.SOURCE,
       ReducerExpectation.REQUIRED, "scanner.py/argus_event_store.py", "First detection/lifecycle/dossier can precede async snapshot.", telemetry=True),
    _s("secondary.tdnet_timing", "TDnet timing and causality evidence", Classification.F,
       StorageKind.MEMORY_ONLY, RecoveryCoverage.NONE, "events",
       PrivacyClass.INTERNAL, FutureDurability.UNRESOLVED, StateNature.SOURCE,
       ReducerExpectation.UNRESOLVED, "scanner.py", "Non-reacquirable timing evidence; business authority unresolved.", telemetry=True),
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
class MutationDefinition:
    mutationClass: str
    stableId: str
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
       policy: PayloadTelemetryPolicy, notes: str) -> MutationDefinition:
    return MutationDefinition(mid, mid, tuple(targets), criticality, source,
                              reducer, route, coverage, future, sync, privacy,
                              policy, notes)


_MUTATIONS: Tuple[MutationDefinition, ...] = tuple(sorted((
    _m("core.ops_journal_transition", ("backend.ops_journal", "backend.ops_sequence_allocator"), MutationCriticality.EXACT_REQUIRED, "journal", True, "mission WAL inside tick; direct checkpoint outside tick", WalCoverage.PARTIAL, FutureMutationTreatment.WAL, True, PrivacyClass.INTERNAL, PayloadTelemetryPolicy.METADATA_ONLY, "Only selected aggregate patches are replayable."),
    _m("core.mission_transition", ("backend.missions", "backend.mission_artifacts", "backend.agent_queue"), MutationCriticality.EXACT_REQUIRED, "mission", True, "mission WAL then checkpoint", WalCoverage.PARTIAL, FutureMutationTreatment.WAL, True, PrivacyClass.INTERNAL, PayloadTelemetryPolicy.METADATA_ONLY, "Current payload covers a bounded transition state, not the whole tick."),
    _m("core.batch_cursor", ("backend.mission_durability",), MutationCriticality.EXACT_REQUIRED, "mission", True, "mission WAL then checkpoint", WalCoverage.PARTIAL, FutureMutationTreatment.WAL, True, PrivacyClass.SECURITY_SENSITIVE, PayloadTelemetryPolicy.METADATA_ONLY, "Cursor is present but chain/generation guarantees are absent."),
    _m("control.soak_stage1", ("backend.soak_state", "backend.stage1_control"), MutationCriticality.EXACT_REQUIRED, "control", True, "journal/direct checkpoint", WalCoverage.PARTIAL, FutureMutationTreatment.WAL, True, PrivacyClass.SECURITY_SENSITIVE, PayloadTelemetryPolicy.METADATA_ONLY, "No authority enablement in Phase A."),
    _m("market.ledger_update", ("market.ledger_source", "market.ledger_derived"), MutationCriticality.SOURCE_FACT, "market-data", True, "checkpoint; journal carries hashes/counts", WalCoverage.NOT_DURABLE_FOR_EXACT_REPLAY, FutureMutationTreatment.WAL, True, PrivacyClass.INTERNAL, PayloadTelemetryPolicy.METADATA_ONLY, "Future record must carry source facts or immutable source references."),
    _m("market.analytics_refresh", ("market.chart_intelligence", "market.today_source", "market.today_derived", "market.replay_receipts", "market.replay_contexts"), MutationCriticality.SOURCE_FACT, "market-analytics", True, "checkpoint; journal carries hashes", WalCoverage.NOT_DURABLE_FOR_EXACT_REPLAY, FutureMutationTreatment.WAL, False, PrivacyClass.PUBLIC_METADATA, PayloadTelemetryPolicy.METADATA_ONLY, "Rebuild proof does not yet exist."),
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
), key=lambda row: row.mutationClass))


def mutation_allows_public_telemetry(
        row: MutationDefinition,
        state_index: Optional[Dict[str, StateDefinition]] = None) -> bool:
    """Return the one fail-closed mutation identifier authorization decision."""
    states_by_id = state_by_id() if state_index is None else state_index
    return bool(
        isinstance(row, MutationDefinition) and
        row.privacyClass == PrivacyClass.PUBLIC_METADATA and
        row.payloadTelemetryPolicy == PayloadTelemetryPolicy.METADATA_ONLY and
        row.targetStateIds and
        all(target in states_by_id and
            state_allows_public_telemetry(states_by_id[target])
            for target in row.targetStateIds))


def states() -> Tuple[StateDefinition, ...]:
    return _STATES


def mutations() -> Tuple[MutationDefinition, ...]:
    return _MUTATIONS


def state_by_id() -> Dict[str, StateDefinition]:
    return {row.stateId: row for row in _STATES}


def mutation_by_class() -> Dict[str, MutationDefinition]:
    return {row.mutationClass: row for row in _MUTATIONS}


def _serialize_dataclass(row: Any) -> Dict[str, Any]:
    value = asdict(row)
    for key, item in tuple(value.items()):
        if isinstance(item, Enum):
            value[key] = item.value
        elif isinstance(item, tuple):
            value[key] = list(item)
    return value


def registry_document() -> Dict[str, Any]:
    return {"schemaVersion": REGISTRY_SCHEMA,
            "states": [_serialize_dataclass(row) for row in _STATES]}


def mutation_registry_document() -> Dict[str, Any]:
    return {"schemaVersion": MUTATION_REGISTRY_SCHEMA,
            "mutations": [_serialize_dataclass(row) for row in _MUTATIONS]}


def validate_registry(state_rows: Optional[Iterable[StateDefinition]] = None,
                      mutation_rows: Optional[Iterable[MutationDefinition]] = None
                      ) -> List[str]:
    state_rows = tuple(_STATES if state_rows is None else state_rows)
    mutation_rows = tuple(_MUTATIONS if mutation_rows is None else mutation_rows)
    errors: List[str] = []
    ids = [row.stateId for row in state_rows]
    if ids != sorted(ids):
        errors.append("state_registry_not_sorted")
    if len(ids) != len(set(ids)):
        errors.append("duplicate_state_id")
    for row in state_rows:
        prefix = row.stateId or "<empty>"
        if not _STABLE_ID_RE.fullmatch(str(row.stateId or "")):
            errors.append(f"{prefix}:invalid_state_id")
        if not all(str(value or "").strip() for value in (
                row.name, row.mutationDomain, row.evidenceOwnerModule,
                row.notes)):
            errors.append(f"{prefix}:required_metadata_missing")
        if not isinstance(row.classification, Classification):
            errors.append(f"{prefix}:unknown_classification")
            continue
        enum_fields = (
            ("currentStorageKind", row.currentStorageKind, StorageKind),
            ("currentRecoveryCoverage", row.currentRecoveryCoverage, RecoveryCoverage),
            ("privacyClass", row.privacyClass, PrivacyClass),
            ("intendedFutureDurability", row.intendedFutureDurability, FutureDurability),
            ("stateNature", row.stateNature, StateNature),
            ("reducerExpectation", row.reducerExpectation, ReducerExpectation),
        )
        for name, value, kind in enum_fields:
            if not isinstance(value, kind):
                errors.append(f"{prefix}:invalid_{name}")
        if row.classification in (Classification.A, Classification.B,
                                  Classification.F) and not row.mustPreserveNow:
            errors.append(f"{prefix}:must_preserve_required")
        if row.classification == Classification.C and not row.rebuildProofAccepted \
                and not row.mustPreserveNow:
            errors.append(f"{prefix}:unproved_rebuild_cannot_omit")
        if row.classification == Classification.C and (
                row.intendedFutureDurability != FutureDurability.REBUILD_AFTER_PROOF
                or not row.requiredRebuildInputs):
            errors.append(f"{prefix}:rebuild_contract_incomplete")
        if row.classification == Classification.D and \
                not row.reacquisitionContractAccepted and not row.mustPreserveNow:
            errors.append(f"{prefix}:uncontracted_reacquisition_cannot_omit")
        if row.classification == Classification.D and (
                row.intendedFutureDurability !=
                FutureDurability.REACQUIRE_AFTER_CONTRACT or
                not row.requiredRebuildInputs):
            errors.append(f"{prefix}:reacquisition_contract_incomplete")
        if row.classification == Classification.F and \
                row.intendedFutureDurability != FutureDurability.UNRESOLVED:
            errors.append(f"{prefix}:unresolved_state_must_remain_unresolved")
        if row.classification == Classification.E and \
                row.intendedFutureDurability == FutureDurability.FULL_PLUS_WAL and \
                not str(row.ephemeralFullWalReason or "").strip():
            errors.append(f"{prefix}:ephemeral_full_wal_reason_required")
        if row.allowedInTelemetry is True and not \
                state_allows_public_telemetry(row):
            errors.append(f"{prefix}:incompatible_public_telemetry")
    mids = [row.mutationClass for row in mutation_rows]
    if mids != sorted(mids):
        errors.append("mutation_registry_not_sorted")
    if len(mids) != len(set(mids)):
        errors.append("duplicate_mutation_class")
    state_ids = set(ids)
    state_index = {row.stateId: row for row in state_rows}
    for row in mutation_rows:
        prefix = row.mutationClass or "<empty>"
        if not _STABLE_ID_RE.fullmatch(str(row.mutationClass or "")) or \
                row.stableId != row.mutationClass:
            errors.append(f"{prefix}:invalid_mutation_stable_id")
        if not all(str(value or "").strip() for value in (
                row.sourceFamily, row.currentPersistenceRoute, row.notes)):
            errors.append(f"{prefix}:required_metadata_missing")
        if not row.targetStateIds:
            errors.append(f"{prefix}:mutation_targets_required")
        for target in row.targetStateIds:
            if target not in state_ids:
                errors.append(f"{prefix}:unknown_target:{target}")
        for name, value, kind in (
                ("criticality", row.criticality, MutationCriticality),
                ("currentWalCoverage", row.currentWalCoverage, WalCoverage),
                ("futureTreatment", row.futureTreatment, FutureMutationTreatment),
                ("privacyClass", row.privacyClass, PrivacyClass),
                ("payloadTelemetryPolicy", row.payloadTelemetryPolicy,
                 PayloadTelemetryPolicy)):
            if not isinstance(value, kind):
                errors.append(f"{prefix}:invalid_{name}")
        if row.privacyClass == PrivacyClass.PUBLIC_METADATA and \
                row.payloadTelemetryPolicy == \
                PayloadTelemetryPolicy.METADATA_ONLY and not \
                mutation_allows_public_telemetry(row, state_index):
            errors.append(f"{prefix}:public_mutation_targets_nonpublic_state")
    return sorted(set(errors))


def unregistered_state_ids(observed_state_ids: Iterable[str]) -> Tuple[str, ...]:
    """Fail-loud discovery helper for tests/diagnostics, never startup authority."""
    known = set(state_by_id())
    return tuple(sorted({str(value) for value in observed_state_ids
                         if str(value) not in known}))


def registry_summary() -> Dict[str, Any]:
    classification_counts = {row.value: 0 for row in Classification}
    coverage_counts = {row.value: 0 for row in WalCoverage}
    for row in _STATES:
        classification_counts[row.classification.value] += 1
    for row in _MUTATIONS:
        coverage_counts[row.currentWalCoverage.value] += 1
    errors = validate_registry()
    return {
        "schemaVersion": REGISTRY_SCHEMA,
        "stateCount": len(_STATES),
        "classificationCounts": classification_counts,
        "mustPreserveCount": sum(1 for row in _STATES if row.mustPreserveNow),
        "unresolvedStateIds": [row.stateId for row in _STATES
                               if row.classification == Classification.F],
        "mutationSchemaVersion": MUTATION_REGISTRY_SCHEMA,
        "mutationClassCount": len(_MUTATIONS),
        "currentWalCoverageCounts": coverage_counts,
        "validationStatus": "valid" if not errors else "invalid",
        "validationErrors": errors,
        "shadowOnly": True,
    }


REGISTRY_VALIDATION_ERRORS = tuple(validate_registry())
