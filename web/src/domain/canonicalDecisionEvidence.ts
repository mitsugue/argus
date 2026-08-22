/**
 * Canonical decision-evidence resolver — the reviewed device half of the
 * backend canonical-artifact boundary (v13.5.13, owner spec 2026-08-22 §1/§17).
 *
 * The backend route /api/argus/decision-evidence publishes, per subject, the
 * marketTruth / predictionLedger / sho reference dicts produced by
 * argus_single_decision.canonical_artifact_references — the same builders
 * verify_decision_evidence recomputes server-side. The browser cannot re-run
 * those verifiers, so this module is the explicit trust seam: it validates the
 * payload's shape, repository-pinned policy identities, and cutoff age, then
 * registers the exact reference objects with the Single Decision Authority.
 * Anything that fails a check resolves to null and the caller keeps the
 * data-gated stub path (fail closed, never a fabricated AVAILABLE).
 */
import {
  registerCanonicalArtifactReference,
  type ArtifactReferenceStatus,
  type DecisionQualityV2,
  type MarketTruthReferenceV2,
  type PredictionLedgerReferenceV2,
  type ShoReferenceV2,
  type ShoState,
  type ShoValidationStatus,
} from './singleDecisionAuthority';

export const DECISION_EVIDENCE_SCHEMA_VERSION = 'argus-decision-evidence-v1';

// Repository-pinned policy identities (Python authority modules are the
// source of truth; a drifted backend payload is rejected, which fails closed
// to the data-gated path).
const MARKET_TRUTH_POLICY = Object.freeze({
  policyId: 'repo-market-provider-priority-v1',
  policySha256: 'c848e2537828a74ecb0914d374d5755ac5b79a3e99e4791b496e514ee8103bf3',
});
const SHO_POLICY = Object.freeze({
  policyId: 'sho-jp-canonical-2026.08-round2-v1',
  policySha256: '0ddae6123f70dd858d5135528768fa9b6cea561f31f47201b8e882c978cbf532',
});
const PREDICTION_POLICY = Object.freeze({
  policyId: 'argus-calibration-three-class-v1',
  policySha256: '62ab147263dfb674301c0dc6585df4c1ffda02cb07380b3d9f94a870ec056379',
});

// Evidence older than this cannot set the decision cutoff — the backend TTL is
// 120s, so a stale payload means the pipe itself is stale.
const MAX_EVIDENCE_AGE_MS = 10 * 60 * 1000;

const REFERENCE_STATUSES: ReadonlySet<string> =
  new Set(['AVAILABLE', 'MISSING', 'CONFLICT', 'STALE']);
const SHO_STATES: ReadonlySet<string> = new Set([
  'FRAGILE', 'DOWNSIDE_TRIGGERED', 'SELL_OFF_ACTIVE', 'REVERSAL_EARLY',
  'TECHNICAL_REBOUND', 'RECOVERY_TEST', 'CONFIRMED_ADVANCE', 'FALSE_RALLY',
  'MIXED']);
const SHO_VALIDATIONS: ReadonlySet<string> =
  new Set(['VALIDATED', 'UNVALIDATED', 'DATA_GATED', 'CONFLICT']);
const QUALITY_STATUSES: ReadonlySet<string> =
  new Set(['COMPLETE', 'PARTIAL', 'MISSING', 'CONFLICT']);
const FRESHNESS_STATUSES: ReadonlySet<string> =
  new Set(['FRESH', 'DELAYED', 'STALE', 'UNKNOWN']);
const UTC_RE = /^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$/;

export interface ResolvedDecisionEvidence {
  informationCutoffAt: string;
  marketTruth: MarketTruthReferenceV2;
  predictionLedger: PredictionLedgerReferenceV2;
  sho: ShoReferenceV2;
  quality: DecisionQualityV2;
}

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value);
const nullableString = (value: unknown): string | null =>
  typeof value === 'string' && value.length > 0 ? value : value === null ? null : null;
const exactUtc = (value: unknown): value is string =>
  typeof value === 'string' && UTC_RE.test(value) && Number.isFinite(Date.parse(value));

function referenceStatus(value: unknown): ArtifactReferenceStatus | null {
  return typeof value === 'string' && REFERENCE_STATUSES.has(value)
    ? value as ArtifactReferenceStatus : null;
}

function resolveMarketTruth(raw: unknown, cutoffMs: number): MarketTruthReferenceV2 | null {
  if (!isRecord(raw)) return null;
  const status = referenceStatus(raw.status);
  if (!status) return null;
  const reference: MarketTruthReferenceV2 = {
    status,
    schemaVersion: nullableString(raw.schemaVersion),
    snapshotId: nullableString(raw.snapshotId),
    observationId: nullableString(raw.observationId),
    observedAt: nullableString(raw.observedAt),
    knownAt: nullableString(raw.knownAt),
    policyId: nullableString(raw.policyId),
    policySha256: nullableString(raw.policySha256),
  };
  if (status === 'AVAILABLE') {
    if (reference.policyId !== MARKET_TRUTH_POLICY.policyId
        || reference.policySha256 !== MARKET_TRUTH_POLICY.policySha256) return null;
    if (!exactUtc(reference.observedAt) || !exactUtc(reference.knownAt)) return null;
    if (Date.parse(reference.knownAt) > cutoffMs
        || Date.parse(reference.observedAt) > Date.parse(reference.knownAt)) return null;
    if (!reference.schemaVersion || !reference.snapshotId
        || !reference.observationId) return null;
  }
  return reference;
}

function resolvePredictionLedger(raw: unknown): PredictionLedgerReferenceV2 | null {
  if (!isRecord(raw)) return null;
  const status = referenceStatus(raw.status);
  if (!status) return null;
  const mode = raw.mode === 'FORWARD_LIVE' ? 'FORWARD_LIVE' as const
    : raw.mode === null || raw.mode === undefined ? null : undefined;
  if (mode === undefined) return null;
  const reference: PredictionLedgerReferenceV2 = {
    status,
    schemaVersion: nullableString(raw.schemaVersion),
    contextId: nullableString(raw.contextId),
    mode,
    asOf: nullableString(raw.asOf),
    policyId: nullableString(raw.policyId),
    policySha256: nullableString(raw.policySha256),
  };
  if (status === 'AVAILABLE') {
    if (reference.policyId !== PREDICTION_POLICY.policyId
        || reference.policySha256 !== PREDICTION_POLICY.policySha256) return null;
    if (reference.mode !== 'FORWARD_LIVE' || !reference.schemaVersion
        || !reference.contextId || !exactUtc(reference.asOf)) return null;
  }
  return reference;
}

function resolveSho(raw: unknown): ShoReferenceV2 | null {
  if (!isRecord(raw)) return null;
  const status = referenceStatus(raw.status);
  if (!status) return null;
  const state = typeof raw.state === 'string' && SHO_STATES.has(raw.state)
    ? raw.state as ShoState : raw.state === null || raw.state === undefined
      ? null : undefined;
  const validation = typeof raw.validationStatus === 'string'
    && SHO_VALIDATIONS.has(raw.validationStatus)
    ? raw.validationStatus as ShoValidationStatus
    : raw.validationStatus === null || raw.validationStatus === undefined
      ? null : undefined;
  if (state === undefined || validation === undefined) return null;
  const primitiveIds = Array.isArray(raw.primitiveFactorIds)
    ? raw.primitiveFactorIds.filter((item): item is string =>
      typeof item === 'string') : [];
  const reference: ShoReferenceV2 = {
    status,
    schemaVersion: nullableString(raw.schemaVersion),
    artifactId: nullableString(raw.artifactId),
    asOf: nullableString(raw.asOf),
    policyId: nullableString(raw.policyId),
    policySha256: nullableString(raw.policySha256),
    state,
    validationStatus: validation,
    primitiveFactorIds: [...primitiveIds].sort(),
    targets: [],
    invalidation: null,
  };
  if (status === 'AVAILABLE') {
    if (reference.policyId !== SHO_POLICY.policyId
        || reference.policySha256 !== SHO_POLICY.policySha256) return null;
    if (!reference.schemaVersion || !reference.artifactId
        || !exactUtc(reference.asOf) || reference.state === null
        || reference.validationStatus === null) return null;
  }
  return reference;
}

function resolveQuality(raw: unknown): DecisionQualityV2 | null {
  if (!isRecord(raw)) return null;
  const status = typeof raw.status === 'string' && QUALITY_STATUSES.has(raw.status)
    ? raw.status as DecisionQualityV2['status'] : null;
  const freshness = typeof raw.freshness === 'string'
    && FRESHNESS_STATUSES.has(raw.freshness)
    ? raw.freshness as DecisionQualityV2['freshness'] : null;
  if (!status || !freshness) return null;
  const codes = (value: unknown): string[] => Array.isArray(value)
    ? [...new Set(value.filter((item): item is string =>
      typeof item === 'string' && /^[a-z0-9][a-z0-9._:-]{0,95}$/.test(item)))].sort()
    : [];
  return {
    status,
    freshness,
    missingReasonCodes: codes(raw.missingReasonCodes),
    conflictReasonCodes: codes(raw.conflictReasonCodes),
  };
}

/**
 * Validate one backend evidence entry and register its references with the
 * authority. Returns null (fail closed) on any shape/pin/age violation.
 */
export function resolveCanonicalArtifactReferences(
  entry: unknown,
  nowMs: number,
): ResolvedDecisionEvidence | null {
  if (!isRecord(entry)) return null;
  const cutoff = entry.informationCutoffAt;
  if (!exactUtc(cutoff)) return null;
  const cutoffMs = Date.parse(cutoff);
  if (cutoffMs > nowMs || nowMs - cutoffMs > MAX_EVIDENCE_AGE_MS) return null;
  const marketTruth = resolveMarketTruth(entry.marketTruth, cutoffMs);
  const predictionLedger = resolvePredictionLedger(entry.predictionLedger);
  const sho = resolveSho(entry.sho);
  const quality = resolveQuality(entry.quality);
  if (!marketTruth || !predictionLedger || !sho || !quality) return null;
  // Python parity: verified artifacts must derive COMPLETE/FRESH quality —
  // a payload claiming all-AVAILABLE with degraded quality is incoherent.
  const allAvailable = [marketTruth, predictionLedger, sho]
    .every((reference) => reference.status === 'AVAILABLE');
  if (allAvailable && (quality.status !== 'COMPLETE'
      || quality.freshness !== 'FRESH'
      || quality.missingReasonCodes.length > 0
      || quality.conflictReasonCodes.length > 0)) return null;
  registerCanonicalArtifactReference(marketTruth);
  registerCanonicalArtifactReference(predictionLedger);
  registerCanonicalArtifactReference(sho);
  return { informationCutoffAt: cutoff, marketTruth, predictionLedger, sho, quality };
}
