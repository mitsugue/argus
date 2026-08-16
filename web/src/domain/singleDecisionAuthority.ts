// Round 2 — DecisionEvidenceBundle compatibility plus active Single Decision Authority v2.
//
// This module is intentionally isolated from hooks, routes, UI, storage, networking,
// recovery and scanner code. It retains the frozen v1 preflight contract under
// explicit compatibility exports and provides a pure deterministic v2 authority.

export const DECISION_EVIDENCE_SCHEMA_VERSION = 'decision-evidence-bundle-v1' as const;
export const SINGLE_DECISION_AUTHORITY_SCHEMA_VERSION = 'single-decision-authority-v1' as const;
export const OWNER_DECISION_CONTEXT_SCHEMA_VERSION = 'owner-decision-context-v1' as const;
export const RISK_DISCIPLINE_INPUT_SCHEMA_VERSION = 'argus-risk-discipline-input-v1' as const;
export const RISK_KERNEL_SCHEMA_VERSION = 'argus-risk-kernel-v1' as const;
export const SINGLE_DECISION_AUTHORITY_INPUT_V2_SCHEMA_VERSION = 'single-decision-authority-input-v2' as const;
export const SINGLE_DECISION_AUTHORITY_V2_SCHEMA_VERSION = 'single-decision-authority-v2' as const;
export const SEVEN_SIGN_SCHEMA_VERSION = 'seven-sign-v1' as const;
export const PREDICTION_LEDGER_SDA_ADAPTER_V2_SCHEMA_VERSION = 'argus-prediction-ledger-sda-adapter-v2' as const;
/** SHA-256 of the closed v2 action/precedence/owner/AI policy descriptor. */
export const SINGLE_DECISION_AUTHORITY_V2_POLICY = Object.freeze({
  policyId: 'single-decision-authority-v2',
  policySha256: 'bbd5da4bb68fed291908ff574f36a3c1c4b20bb48cf86d6a837eecf98353ea31',
} as const);

export const PRIMARY_ACTIONS = Object.freeze(
  ['BUY', 'HOLD', 'WAIT', 'REDUCE', 'EXIT'] as const,
);
export type PrimaryAction = (typeof PRIMARY_ACTIONS)[number];

export const MAX_FACTS = 32;
export const MAX_MISSING_REASON_CODES = 12;
export const MAX_CONFLICT_REASON_CODES = 12;
export const MAX_SUPPORTING_FACT_REFS = 8;
export const MAX_CANONICAL_BODY_BYTES = 64 * 1024;
const MAX_SAFE_INTEGER = 9_007_199_254_740_991;
const MAX_ABS_DECIMAL = 1_000_000_000_000;

export type DecisionMarket = 'JP' | 'US' | 'CRYPTO' | 'FUND';
export type DecisionHorizon = 'INTRADAY' | 'ONE_DAY' | 'FIVE_DAY' | 'TWENTY_DAY' | 'LONG_TERM';
export type DecisionFactKind =
  | 'PRICE_STATE'
  | 'MARKET_STATE'
  | 'FLOW_STATE'
  | 'TREND_STATE'
  | 'EVENT_STATE'
  | 'DISCLOSURE_STATE'
  | 'DATA_QUALITY'
  | 'VISIBILITY'
  | 'CALIBRATION'
  | 'RISK_FLAG'
  | 'POLICY_CONSTRAINT'
  | 'LEGACY_SIGNAL';
export type DecisionFactRole =
  | 'OBSERVATION'
  | 'DERIVED_SIGNAL'
  | 'POLICY_CONSTRAINT'
  | 'MISSINGNESS';
export type DecisionFactValueType = 'BOOL' | 'INTEGER' | 'DECIMAL' | 'ENUM' | 'TIMESTAMP';
export type DecisionFactUnit =
  | 'NONE'
  | 'PERCENT'
  | 'BASIS_POINTS'
  | 'COUNT'
  | 'RATIO_BPS'
  | 'CURRENCY_MINOR'
  | 'PRICE'
  | 'SECONDS'
  | 'MILLISECONDS'
  | 'BYTES';
export type DecisionFactFreshness = 'FRESH' | 'DELAYED' | 'STALE' | 'UNKNOWN';
export type DecisionFactQuality = 'VERIFIED' | 'SUPPORTED' | 'UNRESOLVED' | 'CONFLICT' | 'UNAVAILABLE';

export interface DecisionEvidenceFact {
  factId: string;
  kind: DecisionFactKind;
  role: DecisionFactRole;
  valueType: DecisionFactValueType;
  /** DECIMAL is a canonical decimal string; floats are never accepted. */
  value: boolean | number | string;
  unit: DecisionFactUnit;
  observedAt: string;
  freshness: DecisionFactFreshness;
  quality: DecisionFactQuality;
  sourceRef: string;
}

export interface DecisionEvidenceBundle {
  schemaVersion: typeof DECISION_EVIDENCE_SCHEMA_VERSION;
  bundleId: string;
  privacyClass: 'PUBLIC_EVIDENCE';
  subject: {
    kind: 'ASSET';
    instrumentId: string;
    market: DecisionMarket;
  };
  horizon: DecisionHorizon;
  asOf: string;
  informationCutoffAt: string;
  identities: {
    producerBuildSha: string;
    evidencePolicyId: string;
    evidencePolicySha256: string;
    generationId: string;
  };
  facts: DecisionEvidenceFact[];
  missingReasonCodes: string[];
  conflictReasonCodes: string[];
}

/**
 * The only owner truth the future authority may receive.  This object is made
 * locally after public evidence arrives and must never be sent to the server.
 * Quantity, cost basis, price paid, return and P/L are intentionally absent.
 */
export interface OwnerDecisionContext {
  schemaVersion: typeof OWNER_DECISION_CONTEXT_SCHEMA_VERSION;
  privacyClass: 'DEVICE_LOCAL';
  asOf: string;
  positionState: 'HELD' | 'NOT_HELD' | 'UNKNOWN';
  positionRiskBand: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL' | 'UNKNOWN';
  concentrationBand: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL' | 'UNKNOWN';
  addPermission: 'ALLOWED' | 'BLOCKED' | 'UNKNOWN';
}

export interface SingleDecisionAuthorityInput {
  evidenceBundle: DecisionEvidenceBundle;
  ownerContext: OwnerDecisionContext;
}

export interface InactiveDecisionAuthorityResult {
  schemaVersion: typeof SINGLE_DECISION_AUTHORITY_SCHEMA_VERSION;
  status: 'INACTIVE';
  primaryAction: null;
  decisionId: null;
  evidenceBundleId: null;
  authorityPolicyId: null;
  supportingFactIds: readonly [];
  blockingReasonCodes: readonly ['authority_inactive'];
}

export interface SingleDecisionAuthority {
  readonly status: 'INACTIVE';
  evaluate(input: SingleDecisionAuthorityInput): InactiveDecisionAuthorityResult;
}

export interface ContractValidationResult {
  ok: boolean;
  errors: readonly string[];
}

const TOP_KEYS = [
  'schemaVersion', 'bundleId', 'privacyClass', 'subject', 'horizon', 'asOf', 'informationCutoffAt',
  'identities', 'facts', 'missingReasonCodes', 'conflictReasonCodes',
] as const;
const SUBJECT_KEYS = ['kind', 'instrumentId', 'market'] as const;
const IDENTITY_KEYS = [
  'producerBuildSha', 'evidencePolicyId', 'evidencePolicySha256', 'generationId',
] as const;
const FACT_KEYS = [
  'factId', 'kind', 'role', 'valueType', 'value', 'unit', 'observedAt',
  'freshness', 'quality', 'sourceRef',
] as const;
const OWNER_KEYS = [
  'schemaVersion', 'privacyClass', 'asOf', 'positionState', 'positionRiskBand',
  'concentrationBand', 'addPermission',
] as const;

const MARKETS = new Set<DecisionMarket>(['JP', 'US', 'CRYPTO', 'FUND']);
const HORIZONS = new Set<DecisionHorizon>(['INTRADAY', 'ONE_DAY', 'FIVE_DAY', 'TWENTY_DAY', 'LONG_TERM']);
const FACT_KINDS = new Set<DecisionFactKind>([
  'PRICE_STATE', 'MARKET_STATE', 'FLOW_STATE', 'TREND_STATE', 'EVENT_STATE',
  'DISCLOSURE_STATE', 'DATA_QUALITY', 'VISIBILITY', 'CALIBRATION', 'RISK_FLAG',
  'POLICY_CONSTRAINT', 'LEGACY_SIGNAL',
]);
const FACT_ROLES = new Set<DecisionFactRole>([
  'OBSERVATION', 'DERIVED_SIGNAL', 'POLICY_CONSTRAINT', 'MISSINGNESS',
]);
const VALUE_TYPES = new Set<DecisionFactValueType>(['BOOL', 'INTEGER', 'DECIMAL', 'ENUM', 'TIMESTAMP']);
const FACT_UNITS = new Set<DecisionFactUnit>([
  'NONE', 'PERCENT', 'BASIS_POINTS', 'COUNT', 'RATIO_BPS', 'CURRENCY_MINOR',
  'PRICE', 'SECONDS', 'MILLISECONDS', 'BYTES',
]);
const FRESHNESS_VALUES = new Set<DecisionFactFreshness>(['FRESH', 'DELAYED', 'STALE', 'UNKNOWN']);
const QUALITY_VALUES = new Set<DecisionFactQuality>(['VERIFIED', 'SUPPORTED', 'UNRESOLVED', 'CONFLICT', 'UNAVAILABLE']);

const BUNDLE_ID_RE = /^deb-[0-9a-f]{64}$/;
const SHA40_RE = /^[0-9a-f]{40}$/;
const SHA64_RE = /^[0-9a-f]{64}$/;
const INSTRUMENT_RE = /^[A-Z0-9][A-Z0-9._:-]{0,31}$/;
const IDENTIFIER_RE = /^[a-z0-9][a-z0-9._:-]{0,63}$/;
const FACT_ID_RE = /^[a-z0-9][a-z0-9._:-]{0,63}$/;
const SOURCE_REF_RE = /^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,95}$/;
const REASON_RE = /^[a-z0-9][a-z0-9._:-]{0,63}$/;
const ENUM_RE = /^[A-Z][A-Z0-9_:-]{0,31}$/;
const DECIMAL_RE = /^-?(?:0|[1-9][0-9]{0,12})(?:\.[0-9]{1,8})?$/;
const UTC_RE = /^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$/;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function hasExactKeys(value: unknown, expected: readonly string[]): value is Record<string, unknown> {
  if (!isRecord(value)) return false;
  const actual = Object.keys(value).sort();
  return actual.length === expected.length
    && actual.every((key, index) => key === [...expected].sort()[index]);
}

function isExactUtc(value: unknown): value is string {
  if (typeof value !== 'string' || !UTC_RE.test(value)) return false;
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) && new Date(parsed).toISOString().replace('.000Z', 'Z') === value;
}

function validateReasonCodes(
  value: unknown,
  path: string,
  cap: number,
  errors: string[],
): value is string[] {
  if (!Array.isArray(value)) {
    errors.push(`${path}: must be an array`);
    return false;
  }
  if (value.length > cap) errors.push(`${path}: exceeds cap ${cap}`);
  if (!value.every((code) => typeof code === 'string' && REASON_RE.test(code))) {
    errors.push(`${path}: malformed reason code`);
    return false;
  }
  const canonical = [...new Set(value)].sort();
  if (JSON.stringify(canonical) !== JSON.stringify(value)) {
    errors.push(`${path}: must be sorted and duplicate-free`);
  }
  return true;
}

function validateDecimal(value: unknown): boolean {
  if (typeof value !== 'string' || !DECIMAL_RE.test(value)) return false;
  if (value === '-0' || (value.includes('.') && value.endsWith('0'))) return false;
  const numeric = Number(value);
  return Number.isFinite(numeric) && Math.abs(numeric) <= MAX_ABS_DECIMAL;
}

function validateFact(
  value: unknown,
  index: number,
  cutoffMs: number,
  errors: string[],
): value is DecisionEvidenceFact {
  const path = `facts[${index}]`;
  if (!hasExactKeys(value, FACT_KEYS)) {
    errors.push(`${path}: keys must be exact`);
    return false;
  }
  let valid = true;
  const fail = (field: string, message: string) => {
    valid = false;
    errors.push(`${path}.${field}: ${message}`);
  };
  if (typeof value.factId !== 'string' || !FACT_ID_RE.test(value.factId)) fail('factId', 'malformed');
  if (!FACT_KINDS.has(value.kind as DecisionFactKind)) fail('kind', 'unknown');
  if (!FACT_ROLES.has(value.role as DecisionFactRole)) fail('role', 'unknown');
  if (!VALUE_TYPES.has(value.valueType as DecisionFactValueType)) fail('valueType', 'unknown');
  if (!FACT_UNITS.has(value.unit as DecisionFactUnit)) fail('unit', 'unknown');
  if (!FRESHNESS_VALUES.has(value.freshness as DecisionFactFreshness)) fail('freshness', 'unknown');
  if (!QUALITY_VALUES.has(value.quality as DecisionFactQuality)) fail('quality', 'unknown');
  if (typeof value.sourceRef !== 'string' || !SOURCE_REF_RE.test(value.sourceRef)
      || value.sourceRef.includes('://')) fail('sourceRef', 'must be a bounded identifier, not a URL');
  if (!isExactUtc(value.observedAt) || Date.parse(value.observedAt) > cutoffMs) {
    fail('observedAt', 'must be exact UTC and not later than the information cutoff');
  }
  if (value.valueType === 'BOOL' && typeof value.value !== 'boolean') fail('value', 'BOOL requires boolean');
  if (value.valueType === 'INTEGER'
      && (!Number.isSafeInteger(value.value) || Math.abs(value.value as number) > MAX_SAFE_INTEGER)) {
    fail('value', 'INTEGER requires a safe integer');
  }
  if (value.valueType === 'DECIMAL' && !validateDecimal(value.value)) fail('value', 'invalid canonical decimal');
  if (value.valueType === 'ENUM'
      && (typeof value.value !== 'string' || !ENUM_RE.test(value.value))) fail('value', 'invalid enum token');
  if (value.valueType === 'TIMESTAMP'
      && (!isExactUtc(value.value) || Date.parse(value.value) > cutoffMs)) {
    fail('value', 'invalid timestamp scalar');
  }
  return valid;
}

export function validateDecisionEvidenceBundle(value: unknown): ContractValidationResult {
  const errors: string[] = [];
  if (!hasExactKeys(value, TOP_KEYS)) {
    return { ok: false, errors: Object.freeze(['bundle: keys must be exact']) };
  }
  if (value.schemaVersion !== DECISION_EVIDENCE_SCHEMA_VERSION) errors.push('schemaVersion: mismatch');
  if (typeof value.bundleId !== 'string' || !BUNDLE_ID_RE.test(value.bundleId)) errors.push('bundleId: malformed');
  if (value.privacyClass !== 'PUBLIC_EVIDENCE') errors.push('privacyClass: must be PUBLIC_EVIDENCE');
  if (!hasExactKeys(value.subject, SUBJECT_KEYS)) {
    errors.push('subject: keys must be exact');
  } else {
    if (value.subject.kind !== 'ASSET') errors.push('subject.kind: only ASSET is defined');
    if (typeof value.subject.instrumentId !== 'string' || !INSTRUMENT_RE.test(value.subject.instrumentId)) {
      errors.push('subject.instrumentId: malformed');
    }
    if (!MARKETS.has(value.subject.market as DecisionMarket)) errors.push('subject.market: unknown');
  }
  if (!HORIZONS.has(value.horizon as DecisionHorizon)) errors.push('horizon: unknown');
  const asOfValid = isExactUtc(value.asOf);
  const cutoffValid = isExactUtc(value.informationCutoffAt);
  if (!asOfValid) errors.push('asOf: invalid UTC timestamp');
  if (!cutoffValid) errors.push('informationCutoffAt: invalid UTC timestamp');
  const asOfMs = asOfValid ? Date.parse(value.asOf as string) : Number.NaN;
  const cutoffMs = cutoffValid ? Date.parse(value.informationCutoffAt as string) : Number.NaN;
  if (asOfValid && cutoffValid && cutoffMs > asOfMs) errors.push('informationCutoffAt: later than asOf');

  if (!hasExactKeys(value.identities, IDENTITY_KEYS)) {
    errors.push('identities: keys must be exact');
  } else {
    if (typeof value.identities.producerBuildSha !== 'string'
        || !SHA40_RE.test(value.identities.producerBuildSha)) errors.push('identities.producerBuildSha: malformed');
    if (typeof value.identities.evidencePolicyId !== 'string'
        || !IDENTIFIER_RE.test(value.identities.evidencePolicyId)) errors.push('identities.evidencePolicyId: malformed');
    if (typeof value.identities.evidencePolicySha256 !== 'string'
        || !SHA64_RE.test(value.identities.evidencePolicySha256)) errors.push('identities.evidencePolicySha256: malformed');
    if (typeof value.identities.generationId !== 'string'
        || !IDENTIFIER_RE.test(value.identities.generationId)) errors.push('identities.generationId: malformed');
  }

  if (!Array.isArray(value.facts)) {
    errors.push('facts: must be an array');
  } else {
    if (value.facts.length > MAX_FACTS) errors.push(`facts: exceeds cap ${MAX_FACTS}`);
    value.facts.forEach((fact, index) => validateFact(fact, index, cutoffMs, errors));
    const ids = value.facts.map((fact) => isRecord(fact) ? fact.factId : null);
    const canonicalIds = [...new Set(ids)].sort();
    if (JSON.stringify(ids) !== JSON.stringify(canonicalIds)) errors.push('facts: must be sorted and duplicate-free');
  }
  const missingReasonCodes = value.missingReasonCodes;
  const conflictReasonCodes = value.conflictReasonCodes;
  const missingValid = validateReasonCodes(
    missingReasonCodes, 'missingReasonCodes', MAX_MISSING_REASON_CODES, errors);
  const conflictsValid = validateReasonCodes(
    conflictReasonCodes, 'conflictReasonCodes', MAX_CONFLICT_REASON_CODES, errors);
  if (Array.isArray(value.facts) && value.facts.length === 0
      && missingValid && missingReasonCodes.length === 0
      && conflictsValid && conflictReasonCodes.length === 0) {
    errors.push('bundle: requires a fact or explicit missing/conflict reason');
  }
  if (errors.length === 0) {
    const { bundleId: _bundleId, ...body } = value;
    if (new TextEncoder().encode(stableJson(body as unknown as JsonValue)).byteLength
        > MAX_CANONICAL_BODY_BYTES) errors.push(`bundle: canonical body exceeds ${MAX_CANONICAL_BODY_BYTES} bytes`);
  }
  return { ok: errors.length === 0, errors: Object.freeze(errors) };
}

export function validateOwnerDecisionContext(value: unknown): ContractValidationResult {
  const errors: string[] = [];
  if (!hasExactKeys(value, OWNER_KEYS)) {
    return { ok: false, errors: Object.freeze(['ownerContext: keys must be exact']) };
  }
  if (value.schemaVersion !== OWNER_DECISION_CONTEXT_SCHEMA_VERSION) errors.push('schemaVersion: mismatch');
  if (value.privacyClass !== 'DEVICE_LOCAL') errors.push('privacyClass: must be DEVICE_LOCAL');
  if (!isExactUtc(value.asOf)) errors.push('asOf: invalid UTC timestamp');
  if (!['HELD', 'NOT_HELD', 'UNKNOWN'].includes(value.positionState as string)) errors.push('positionState: unknown');
  if (!['LOW', 'MEDIUM', 'HIGH', 'CRITICAL', 'UNKNOWN'].includes(value.positionRiskBand as string)) {
    errors.push('positionRiskBand: unknown');
  }
  if (!['LOW', 'MEDIUM', 'HIGH', 'CRITICAL', 'UNKNOWN'].includes(value.concentrationBand as string)) {
    errors.push('concentrationBand: unknown');
  }
  if (!['ALLOWED', 'BLOCKED', 'UNKNOWN'].includes(value.addPermission as string)) errors.push('addPermission: unknown');
  return { ok: errors.length === 0, errors: Object.freeze(errors) };
}

type JsonValue = null | boolean | number | string | JsonValue[] | { [key: string]: JsonValue };

function stableJson(value: JsonValue): string {
  if (value === null || typeof value === 'boolean' || typeof value === 'number'
      || typeof value === 'string') return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(stableJson).join(',')}]`;
  return `{${Object.keys(value).sort().map((key) =>
    `${JSON.stringify(key)}:${stableJson(value[key])}`).join(',')}}`;
}

export function canonicalDecisionEvidenceBodyJson(bundle: DecisionEvidenceBundle): string {
  const validation = validateDecisionEvidenceBundle(bundle);
  if (!validation.ok) throw new TypeError(validation.errors.join('; '));
  const { bundleId: _bundleId, ...body } = bundle;
  return stableJson(body as unknown as JsonValue);
}

function hex(bytes: Uint8Array): string {
  return [...bytes].map((byte) => byte.toString(16).padStart(2, '0')).join('');
}

export async function computeDecisionEvidenceBundleId(bundle: DecisionEvidenceBundle): Promise<string> {
  const data = new TextEncoder().encode(canonicalDecisionEvidenceBodyJson(bundle));
  const digest = await globalThis.crypto.subtle.digest('SHA-256', data);
  return `deb-${hex(new Uint8Array(digest))}`;
}

export async function verifyDecisionEvidenceBundleId(bundle: DecisionEvidenceBundle): Promise<boolean> {
  const validation = validateDecisionEvidenceBundle(bundle);
  return validation.ok && bundle.bundleId === await computeDecisionEvidenceBundleId(bundle);
}

const INACTIVE_RESULT: InactiveDecisionAuthorityResult = Object.freeze({
  schemaVersion: SINGLE_DECISION_AUTHORITY_SCHEMA_VERSION,
  status: 'INACTIVE' as const,
  primaryAction: null,
  decisionId: null,
  evidenceBundleId: null,
  authorityPolicyId: null,
  supportingFactIds: Object.freeze([]) as readonly [],
  blockingReasonCodes: Object.freeze(['authority_inactive']) as readonly ['authority_inactive'],
});

/** Explicit v1 compatibility: no input can make the preflight stub return authority. */
export function evaluateInactiveSingleDecisionAuthorityV1(
  _input: SingleDecisionAuthorityInput,
): InactiveDecisionAuthorityResult {
  return INACTIVE_RESULT;
}

export const inactiveSingleDecisionAuthorityV1: SingleDecisionAuthority = Object.freeze({
  status: 'INACTIVE' as const,
  evaluate: evaluateInactiveSingleDecisionAuthorityV1,
});

// ---------------------------------------------------------------------------
// Active v2: constraint-only Risk Kernel

export type RiskSourceKind =
  | 'MARKET' | 'SHO' | 'SCENARIO' | 'EVENT' | 'PORTFOLIO' | 'CONCENTRATION' | 'DISCIPLINE';
export type RiskConstraint = 'NONE' | 'BLOCK_BUY' | 'WAIT_REQUIRED' | 'REDUCE_RISK' | 'EXIT_RISK';
export type RiskContributionStatus = 'ACTIVE' | 'INACTIVE' | 'MISSING' | 'CONFLICT';
export type RiskSeverity = 'NONE' | 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL' | 'UNKNOWN';

export interface ArtifactPolicyRef {
  policyId: string;
  policySha256: string;
}

export interface RiskContributionV1 {
  evidenceRef: string;
  primitiveFactorId: string;
  sourceKind: RiskSourceKind;
  constraint: RiskConstraint;
  status: RiskContributionStatus;
  severity: RiskSeverity;
  confidenceCapBps: number | null;
  observedAt: string;
}

export interface RiskDisciplineInputV1 {
  schemaVersion: typeof RISK_DISCIPLINE_INPUT_SCHEMA_VERSION;
  subject: { kind: 'ASSET'; instrumentId: string; market: DecisionMarket };
  asOf: string;
  informationCutoffAt: string;
  policy: ArtifactPolicyRef;
  contributions: RiskContributionV1[];
}

export interface RiskPrimitiveFactorV1 {
  primitiveFactorId: string;
  status: RiskContributionStatus;
  constraint: RiskConstraint;
  severity: RiskSeverity;
  confidenceCapBps: number | null;
  evidenceRefs: string[];
}

export interface RiskKernelV1 {
  schemaVersion: typeof RISK_KERNEL_SCHEMA_VERSION;
  riskKernelId: string;
  privacyClass: 'DEVICE_LOCAL_DERIVED';
  subject: { kind: 'ASSET'; instrumentId: string; market: DecisionMarket };
  asOf: string;
  informationCutoffAt: string;
  policy: ArtifactPolicyRef;
  status: 'READY' | 'DATA_GATED';
  constraint: RiskConstraint;
  confidenceCapBps: number;
  primitiveFactors: RiskPrimitiveFactorV1[];
  missingReasonCodes: string[];
  conflictReasonCodes: string[];
  finalActionAuthority: false;
}

const V2_ID_RE = /^[a-z0-9][a-z0-9._:-]{0,95}$/;
const V2_ARTIFACT_ID_RE = /^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,127}$/;
const RISK_KERNEL_ID_RE = /^rk-[0-9a-f]{64}$/;
const DECISION_ID_RE = /^sda-[0-9a-f]{64}$/;
const ADAPTER_ID_RE = /^pla-[0-9a-f]{64}$/;
const VERIFIED_BUNDLE_ID_RE = /^vdeb-[0-9a-f]{64}$/;

interface VerifiedBundleRuntimeState {
  readonly bundleId: string;
  readonly canonicalInput: string;
  readonly shoBuyEligible: boolean;
}

interface VerifiedResultRuntimeState {
  readonly bundleId: string;
  readonly canonicalResult: string;
}

const VERIFIED_RISK_KERNELS = new WeakMap<object, string>();
const VERIFIED_DECISION_BUNDLES = new WeakMap<object, VerifiedBundleRuntimeState>();
const VERIFIED_DECISION_RESULTS = new WeakMap<object, VerifiedResultRuntimeState>();
const RISK_INPUT_KEYS = [
  'schemaVersion', 'subject', 'asOf', 'informationCutoffAt', 'policy', 'contributions',
] as const;
const V2_POLICY_KEYS = ['policyId', 'policySha256'] as const;
const RISK_CONTRIBUTION_KEYS = [
  'evidenceRef', 'primitiveFactorId', 'sourceKind', 'constraint', 'status', 'severity',
  'confidenceCapBps', 'observedAt',
] as const;
const RISK_KERNEL_KEYS = [
  'schemaVersion', 'riskKernelId', 'privacyClass', 'subject', 'asOf',
  'informationCutoffAt', 'policy', 'status', 'constraint', 'confidenceCapBps',
  'primitiveFactors', 'missingReasonCodes', 'conflictReasonCodes', 'finalActionAuthority',
] as const;
const RISK_FACTOR_KEYS = [
  'primitiveFactorId', 'status', 'constraint', 'severity', 'confidenceCapBps', 'evidenceRefs',
] as const;
const RISK_SOURCE_KINDS = new Set<RiskSourceKind>([
  'MARKET', 'SHO', 'SCENARIO', 'EVENT', 'PORTFOLIO', 'CONCENTRATION', 'DISCIPLINE',
]);
const RISK_CONSTRAINTS = new Set<RiskConstraint>([
  'NONE', 'BLOCK_BUY', 'WAIT_REQUIRED', 'REDUCE_RISK', 'EXIT_RISK',
]);
const RISK_STATUSES = new Set<RiskContributionStatus>([
  'ACTIVE', 'INACTIVE', 'MISSING', 'CONFLICT',
]);
const RISK_SEVERITIES = new Set<RiskSeverity>([
  'NONE', 'LOW', 'MEDIUM', 'HIGH', 'CRITICAL', 'UNKNOWN',
]);
const RISK_CONSTRAINT_PRECEDENCE: Record<RiskConstraint, number> = {
  NONE: 0, BLOCK_BUY: 1, WAIT_REQUIRED: 2, REDUCE_RISK: 3, EXIT_RISK: 4,
};
const RISK_SEVERITY_PRECEDENCE: Record<RiskSeverity, number> = {
  NONE: 0, UNKNOWN: 1, LOW: 2, MEDIUM: 3, HIGH: 4, CRITICAL: 5,
};

function deepClone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

/** Small synchronous SHA-256 used only over bounded canonical JSON. */
function sha256HexSync(input: string): string {
  const bytes = new TextEncoder().encode(input);
  const paddedLength = Math.ceil((bytes.length + 9) / 64) * 64;
  const padded = new Uint8Array(paddedLength);
  padded.set(bytes);
  padded[bytes.length] = 0x80;
  const bitLength = bytes.length * 8;
  const high = Math.floor(bitLength / 0x1_0000_0000);
  const low = bitLength >>> 0;
  const view = new DataView(padded.buffer);
  view.setUint32(paddedLength - 8, high, false);
  view.setUint32(paddedLength - 4, low, false);

  const k = [
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
    0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
    0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
    0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
    0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
    0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
  ];
  const rotateRight = (value: number, count: number) =>
    ((value >>> count) | (value << (32 - count))) >>> 0;
  const state = [
    0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a,
    0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19,
  ];
  const words = new Uint32Array(64);
  for (let offset = 0; offset < paddedLength; offset += 64) {
    for (let index = 0; index < 16; index += 1) {
      words[index] = view.getUint32(offset + index * 4, false);
    }
    for (let index = 16; index < 64; index += 1) {
      const s0 = rotateRight(words[index - 15], 7)
        ^ rotateRight(words[index - 15], 18) ^ (words[index - 15] >>> 3);
      const s1 = rotateRight(words[index - 2], 17)
        ^ rotateRight(words[index - 2], 19) ^ (words[index - 2] >>> 10);
      words[index] = (words[index - 16] + s0 + words[index - 7] + s1) >>> 0;
    }
    let [a, b, c, d, e, f, g, h] = state;
    for (let index = 0; index < 64; index += 1) {
      const sigma1 = rotateRight(e, 6) ^ rotateRight(e, 11) ^ rotateRight(e, 25);
      const choose = (e & f) ^ (~e & g);
      const temp1 = (h + sigma1 + choose + k[index] + words[index]) >>> 0;
      const sigma0 = rotateRight(a, 2) ^ rotateRight(a, 13) ^ rotateRight(a, 22);
      const majority = (a & b) ^ (a & c) ^ (b & c);
      const temp2 = (sigma0 + majority) >>> 0;
      h = g;
      g = f;
      f = e;
      e = (d + temp1) >>> 0;
      d = c;
      c = b;
      b = a;
      a = (temp1 + temp2) >>> 0;
    }
    state[0] = (state[0] + a) >>> 0;
    state[1] = (state[1] + b) >>> 0;
    state[2] = (state[2] + c) >>> 0;
    state[3] = (state[3] + d) >>> 0;
    state[4] = (state[4] + e) >>> 0;
    state[5] = (state[5] + f) >>> 0;
    state[6] = (state[6] + g) >>> 0;
    state[7] = (state[7] + h) >>> 0;
  }
  return state.map((word) => word.toString(16).padStart(8, '0')).join('');
}

function validateV2Policy(value: unknown, path: string, errors: string[]): value is ArtifactPolicyRef {
  if (!hasExactKeys(value, V2_POLICY_KEYS)) {
    errors.push(`${path}: keys must be exact`);
    return false;
  }
  if (typeof value.policyId !== 'string' || !V2_ID_RE.test(value.policyId)) {
    errors.push(`${path}.policyId: malformed`);
  }
  if (typeof value.policySha256 !== 'string' || !SHA64_RE.test(value.policySha256)) {
    errors.push(`${path}.policySha256: malformed`);
  }
  return errors.length === 0;
}

function validateRiskSubject(value: unknown, path: string, errors: string[]): boolean {
  if (!hasExactKeys(value, SUBJECT_KEYS)) {
    errors.push(`${path}: keys must be exact`);
    return false;
  }
  if (value.kind !== 'ASSET') errors.push(`${path}.kind: must equal ASSET`);
  if (typeof value.instrumentId !== 'string' || !INSTRUMENT_RE.test(value.instrumentId)) {
    errors.push(`${path}.instrumentId: malformed`);
  }
  if (!MARKETS.has(value.market as DecisionMarket)) errors.push(`${path}.market: unknown`);
  return true;
}

function isBps(value: unknown, nullable = false): boolean {
  return (nullable && value === null)
    || (Number.isInteger(value) && (value as number) >= 0 && (value as number) <= 10_000);
}

export function validateRiskDisciplineInput(value: unknown): ContractValidationResult {
  const errors: string[] = [];
  if (!hasExactKeys(value, RISK_INPUT_KEYS)) {
    return { ok: false, errors: Object.freeze(['request: keys must be exact']) };
  }
  if (value.schemaVersion !== RISK_DISCIPLINE_INPUT_SCHEMA_VERSION) errors.push('schemaVersion: mismatch');
  validateRiskSubject(value.subject, 'subject', errors);
  if (!isExactUtc(value.asOf)) errors.push('asOf: invalid UTC timestamp');
  if (!isExactUtc(value.informationCutoffAt)) errors.push('informationCutoffAt: invalid UTC timestamp');
  if (isExactUtc(value.asOf) && isExactUtc(value.informationCutoffAt)
      && Date.parse(value.informationCutoffAt) > Date.parse(value.asOf)) {
    errors.push('informationCutoffAt: later than asOf');
  }
  validateV2Policy(value.policy, 'policy', errors);
  if (!Array.isArray(value.contributions) || value.contributions.length > 32) {
    errors.push('contributions: must be an array of at most 32');
  } else {
    value.contributions.forEach((raw, index) => {
      const path = `contributions[${index}]`;
      if (!hasExactKeys(raw, RISK_CONTRIBUTION_KEYS)) {
        errors.push(`${path}: keys must be exact`);
        return;
      }
      if (typeof raw.evidenceRef !== 'string' || !SOURCE_REF_RE.test(raw.evidenceRef)
          || raw.evidenceRef.includes('://')) errors.push(`${path}.evidenceRef: malformed`);
      if (typeof raw.primitiveFactorId !== 'string' || !V2_ID_RE.test(raw.primitiveFactorId)) {
        errors.push(`${path}.primitiveFactorId: malformed`);
      }
      if (!RISK_SOURCE_KINDS.has(raw.sourceKind as RiskSourceKind)) errors.push(`${path}.sourceKind: unknown`);
      if (!RISK_CONSTRAINTS.has(raw.constraint as RiskConstraint)) errors.push(`${path}.constraint: unknown`);
      if (!RISK_STATUSES.has(raw.status as RiskContributionStatus)) errors.push(`${path}.status: unknown`);
      if (!RISK_SEVERITIES.has(raw.severity as RiskSeverity)) errors.push(`${path}.severity: unknown`);
      if (!isBps(raw.confidenceCapBps, true)) errors.push(`${path}.confidenceCapBps: invalid`);
      if (!isExactUtc(raw.observedAt) || (isExactUtc(value.informationCutoffAt)
          && Date.parse(raw.observedAt) > Date.parse(value.informationCutoffAt))) {
        errors.push(`${path}.observedAt: later than cutoff or malformed`);
      }
      if (raw.status !== 'ACTIVE' && raw.constraint !== 'NONE') {
        errors.push(`${path}.constraint: non-active evidence cannot constrain`);
      }
    });
  }
  return { ok: errors.length === 0, errors: Object.freeze(errors) };
}

export function computeRiskKernelId(kernelOrBody: RiskKernelV1 | Omit<RiskKernelV1, 'riskKernelId'>): string {
  const { riskKernelId: _ignored, ...body } = kernelOrBody as RiskKernelV1;
  return `rk-${sha256HexSync(stableJson(body as unknown as JsonValue))}`;
}

export function buildRiskKernel(request: RiskDisciplineInputV1): RiskKernelV1 {
  const validation = validateRiskDisciplineInput(request);
  if (!validation.ok) throw new TypeError(validation.errors.join('; '));
  const grouped = new Map<string, RiskContributionV1[]>();
  request.contributions.forEach((row) => {
    grouped.set(row.primitiveFactorId, [...(grouped.get(row.primitiveFactorId) ?? []), row]);
  });
  const missing: string[] = [];
  const conflicts: string[] = [];
  const factors: RiskPrimitiveFactorV1[] = [...grouped.keys()].sort().map((factorId) => {
    const rows = grouped.get(factorId) ?? [];
    const active = rows.filter((row) => row.status === 'ACTIVE');
    const activeConstraints = [...new Set(active.map((row) => row.constraint))];
    let status: RiskContributionStatus;
    let constraint: RiskConstraint;
    if (rows.some((row) => row.status === 'CONFLICT') || activeConstraints.length > 1) {
      status = 'CONFLICT';
      constraint = 'NONE';
      conflicts.push(`risk_conflict.${factorId}`.slice(0, 96));
    } else if (active.length > 0) {
      status = 'ACTIVE';
      [constraint] = activeConstraints;
    } else if (rows.some((row) => row.status === 'MISSING')) {
      status = 'MISSING';
      constraint = 'NONE';
      missing.push(`risk_missing.${factorId}`.slice(0, 96));
    } else {
      status = 'INACTIVE';
      constraint = 'NONE';
    }
    const relevant = status === 'ACTIVE' ? active : rows;
    const caps = relevant.map((row) => row.confidenceCapBps)
      .filter((cap): cap is number => cap !== null);
    const severity = relevant.reduce<RiskSeverity>((current, row) =>
      RISK_SEVERITY_PRECEDENCE[row.severity] > RISK_SEVERITY_PRECEDENCE[current]
        ? row.severity : current, 'UNKNOWN');
    const evidenceRefs = [...new Set(rows.map((row) => row.evidenceRef))].sort();
    if (evidenceRefs.length > 8) throw new TypeError(`primitiveFactors.${factorId}: too many refs`);
    return {
      primitiveFactorId: factorId,
      status,
      constraint,
      severity,
      confidenceCapBps: caps.length > 0 ? Math.min(...caps) : null,
      evidenceRefs,
    };
  });
  if (factors.length === 0) missing.push('risk_evidence_empty');
  const dataGated = missing.length > 0 || conflicts.length > 0;
  const activeConstraints = factors.filter((factor) => factor.status === 'ACTIVE')
    .map((factor) => factor.constraint);
  let constraint = activeConstraints.reduce<RiskConstraint>((current, candidate) =>
    RISK_CONSTRAINT_PRECEDENCE[candidate] > RISK_CONSTRAINT_PRECEDENCE[current]
      ? candidate : current, 'NONE');
  if (dataGated && RISK_CONSTRAINT_PRECEDENCE[constraint] < RISK_CONSTRAINT_PRECEDENCE.WAIT_REQUIRED) {
    constraint = 'WAIT_REQUIRED';
  }
  const activeCaps = factors.filter((factor) => factor.status === 'ACTIVE')
    .map((factor) => factor.confidenceCapBps).filter((cap): cap is number => cap !== null);
  let confidenceCapBps = activeCaps.length > 0 ? Math.min(...activeCaps) : 10_000;
  if (dataGated) confidenceCapBps = Math.min(confidenceCapBps, 2_500);
  const body: Omit<RiskKernelV1, 'riskKernelId'> = {
    schemaVersion: RISK_KERNEL_SCHEMA_VERSION,
    privacyClass: 'DEVICE_LOCAL_DERIVED',
    subject: deepClone(request.subject),
    asOf: request.asOf,
    informationCutoffAt: request.informationCutoffAt,
    policy: deepClone(request.policy),
    status: dataGated ? 'DATA_GATED' : 'READY',
    constraint,
    confidenceCapBps,
    primitiveFactors: factors,
    missingReasonCodes: [...new Set(missing)].sort().slice(0, 16),
    conflictReasonCodes: [...new Set(conflicts)].sort().slice(0, 16),
    finalActionAuthority: false,
  };
  const kernel: RiskKernelV1 = { riskKernelId: computeRiskKernelId(body), ...body };
  const kernelValidation = validateRiskKernel(kernel);
  if (!kernelValidation.ok) throw new TypeError(kernelValidation.errors.join('; '));
  const admitted = deepClone(kernel);
  VERIFIED_RISK_KERNELS.set(admitted, stableJson(admitted as unknown as JsonValue));
  return admitted;
}

export function validateRiskKernel(value: unknown): ContractValidationResult {
  const errors: string[] = [];
  if (!hasExactKeys(value, RISK_KERNEL_KEYS)) {
    return { ok: false, errors: Object.freeze(['kernel: keys must be exact']) };
  }
  if (value.schemaVersion !== RISK_KERNEL_SCHEMA_VERSION) errors.push('kernel.schemaVersion: mismatch');
  if (typeof value.riskKernelId !== 'string' || !RISK_KERNEL_ID_RE.test(value.riskKernelId)) {
    errors.push('kernel.riskKernelId: malformed');
  }
  if (value.privacyClass !== 'DEVICE_LOCAL_DERIVED') errors.push('kernel.privacyClass: mismatch');
  validateRiskSubject(value.subject, 'kernel.subject', errors);
  if (!isExactUtc(value.asOf)) errors.push('kernel.asOf: invalid');
  if (!isExactUtc(value.informationCutoffAt)) errors.push('kernel.informationCutoffAt: invalid');
  if (isExactUtc(value.asOf) && isExactUtc(value.informationCutoffAt)
      && Date.parse(value.informationCutoffAt) > Date.parse(value.asOf)) {
    errors.push('kernel.informationCutoffAt: later than asOf');
  }
  validateV2Policy(value.policy, 'kernel.policy', errors);
  if (!['READY', 'DATA_GATED'].includes(value.status as string)) errors.push('kernel.status: unknown');
  if (!RISK_CONSTRAINTS.has(value.constraint as RiskConstraint)) errors.push('kernel.constraint: unknown');
  if (!isBps(value.confidenceCapBps)) errors.push('kernel.confidenceCapBps: invalid');
  if (value.finalActionAuthority !== false) errors.push('kernel.finalActionAuthority: must be false');
  if (!Array.isArray(value.primitiveFactors) || value.primitiveFactors.length > 32) {
    errors.push('kernel.primitiveFactors: invalid');
  } else {
    const ids: unknown[] = [];
    value.primitiveFactors.forEach((raw, index) => {
      const path = `kernel.primitiveFactors[${index}]`;
      if (!hasExactKeys(raw, RISK_FACTOR_KEYS)) {
        errors.push(`${path}: keys must be exact`);
        return;
      }
      ids.push(raw.primitiveFactorId);
      if (typeof raw.primitiveFactorId !== 'string' || !V2_ID_RE.test(raw.primitiveFactorId)) {
        errors.push(`${path}.primitiveFactorId: malformed`);
      }
      if (!RISK_STATUSES.has(raw.status as RiskContributionStatus)) errors.push(`${path}.status: unknown`);
      if (!RISK_CONSTRAINTS.has(raw.constraint as RiskConstraint)) errors.push(`${path}.constraint: unknown`);
      if (raw.status !== 'ACTIVE' && raw.constraint !== 'NONE') errors.push(`${path}.constraint: invalid`);
      if (!RISK_SEVERITIES.has(raw.severity as RiskSeverity)) errors.push(`${path}.severity: unknown`);
      if (!isBps(raw.confidenceCapBps, true)) errors.push(`${path}.confidenceCapBps: invalid`);
      if (!Array.isArray(raw.evidenceRefs) || raw.evidenceRefs.length > 8
          || !raw.evidenceRefs.every((ref) => typeof ref === 'string' && SOURCE_REF_RE.test(ref)
            && !ref.includes('://'))
          || JSON.stringify(raw.evidenceRefs) !== JSON.stringify([...new Set(raw.evidenceRefs)].sort())) {
        errors.push(`${path}.evidenceRefs: invalid`);
      }
    });
    if (JSON.stringify(ids) !== JSON.stringify([...new Set(ids)].sort())) {
      errors.push('kernel.primitiveFactors: must be sorted and unique');
    }
  }
  validateReasonCodes(value.missingReasonCodes, 'kernel.missingReasonCodes', 16, errors);
  validateReasonCodes(value.conflictReasonCodes, 'kernel.conflictReasonCodes', 16, errors);
  if (value.status === 'READY'
      && ((value.missingReasonCodes as unknown[]).length > 0
        || (value.conflictReasonCodes as unknown[]).length > 0)) errors.push('kernel.status: inconsistent');
  if (value.status === 'DATA_GATED'
      && !['WAIT_REQUIRED', 'REDUCE_RISK', 'EXIT_RISK'].includes(value.constraint as string)) {
    errors.push('kernel.constraint: DATA_GATED must fail closed');
  }
  if (errors.length === 0 && value.riskKernelId !== computeRiskKernelId(value as unknown as RiskKernelV1)) {
    errors.push('kernel.riskKernelId: content address mismatch');
  }
  return { ok: errors.length === 0, errors: Object.freeze(errors) };
}

// ---------------------------------------------------------------------------
// Active v2: exact input and output contracts

export type ArtifactReferenceStatus = 'AVAILABLE' | 'MISSING' | 'CONFLICT' | 'STALE';
export type ShoState =
  | 'FRAGILE' | 'DOWNSIDE_TRIGGERED' | 'SELL_OFF_ACTIVE' | 'REVERSAL_EARLY'
  | 'TECHNICAL_REBOUND' | 'RECOVERY_TEST' | 'CONFIRMED_ADVANCE' | 'FALSE_RALLY' | 'MIXED';
export type ShoValidationStatus = 'VALIDATED' | 'UNVALIDATED' | 'DATA_GATED' | 'CONFLICT';

export interface DecisionSubjectV2 {
  kind: 'ASSET';
  instrumentId: string;
  market: DecisionMarket;
  horizon: DecisionHorizon;
}

export interface MarketTruthReferenceV2 {
  status: ArtifactReferenceStatus;
  schemaVersion: string | null;
  snapshotId: string | null;
  observationId: string | null;
  observedAt: string | null;
  knownAt: string | null;
  policyId: string | null;
  policySha256: string | null;
}

export interface PredictionLedgerReferenceV2 {
  status: ArtifactReferenceStatus;
  schemaVersion: string | null;
  contextId: string | null;
  mode: 'FORWARD_LIVE' | null;
  asOf: string | null;
  policyId: string | null;
  policySha256: string | null;
}

export interface DecisionTargetV2 {
  targetId: string;
  value: string;
  unit: 'PRICE' | 'PERCENT' | 'RATIO' | 'NONE';
  sourceRef: string;
}

export interface DecisionInvalidationV2 {
  invalidationId: string;
  value: string;
  unit: 'PRICE' | 'PERCENT' | 'RATIO' | 'NONE';
  sourceRef: string;
}

export interface ShoReferenceV2 {
  status: ArtifactReferenceStatus;
  schemaVersion: string | null;
  artifactId: string | null;
  asOf: string | null;
  policyId: string | null;
  policySha256: string | null;
  state: ShoState | null;
  validationStatus: ShoValidationStatus | null;
  primitiveFactorIds: string[];
  targets: DecisionTargetV2[];
  invalidation: DecisionInvalidationV2 | null;
}

export interface ContextEvidenceV2 {
  evidenceRef: string;
  primitiveFactorId: string;
  sourceKind: 'SCENARIO' | 'EVENT';
  constraint: 'NONE' | 'WAIT_REQUIRED';
  status: 'ACTIVE' | 'INACTIVE' | 'MISSING' | 'CONFLICT';
  observedAt: string;
}

export interface DecisionQualityV2 {
  status: 'COMPLETE' | 'PARTIAL' | 'MISSING' | 'CONFLICT';
  freshness: DecisionFactFreshness;
  missingReasonCodes: string[];
  conflictReasonCodes: string[];
}

export interface ChallengeEvidenceV2 {
  challengeId: string;
  sourceKind: 'AI' | 'LEGACY';
  status: 'AVAILABLE' | 'MISSING';
  asOf: string;
  proposedAction: PrimaryAction | null;
  dissentReasonCodes: string[];
  evidenceRefs: string[];
}

export interface SevenSignCalibrationV1 {
  status: 'VALIDATED' | 'SHADOW' | 'DATA_GATED' | 'MISSING';
  artifactId: string | null;
  policyId: string | null;
  policySha256: string | null;
  expectancyBpsByLevel: number[] | null;
  sampleSizeByLevel: number[] | null;
  outOfSample: boolean;
  holdoutImmutable: boolean;
}

export interface SingleDecisionAuthorityInputV2 {
  schemaVersion: typeof SINGLE_DECISION_AUTHORITY_INPUT_V2_SCHEMA_VERSION;
  subject: DecisionSubjectV2;
  decisionAt: string;
  informationCutoffAt: string;
  authorityPolicy: ArtifactPolicyRef;
  marketTruth: MarketTruthReferenceV2;
  predictionLedger: PredictionLedgerReferenceV2;
  sho: ShoReferenceV2;
  riskKernel: RiskKernelV1;
  contextEvidence: ContextEvidenceV2[];
  quality: DecisionQualityV2;
  ownerContext: OwnerDecisionContext;
  challengeEvidence: ChallengeEvidenceV2[];
  sevenSignCalibration: SevenSignCalibrationV1;
}

export interface SevenSignProjectionV1 {
  schemaVersion: typeof SEVEN_SIGN_SCHEMA_VERSION;
  status: 'PRODUCTION' | 'SHADOW' | 'DATA_GATED';
  candidateLevel: number | null;
  productionLevel: number | null;
  policyId: string | null;
  policySha256: string | null;
  calibrationArtifactId: string | null;
  reasonCodes: string[];
}

export interface SingleDecisionAuthorityResultV2 {
  schemaVersion: typeof SINGLE_DECISION_AUTHORITY_V2_SCHEMA_VERSION;
  decisionId: string;
  verifiedEvidenceBundleId: string | null;
  status: 'EVALUATED' | 'DATA_GATED';
  subject: DecisionSubjectV2 | null;
  issuedAt: string | null;
  informationCutoffAt: string | null;
  primaryAction: PrimaryAction;
  confidence: { valueBps: number; status: 'BOUNDED' };
  guidance: {
    position: 'ENTER_OR_ADD' | 'MAINTAIN' | 'NO_ACTION' | 'REDUCE_EXPOSURE' | 'EXIT_POSITION';
    riskConstraint: RiskConstraint;
  };
  targets: DecisionTargetV2[];
  invalidation: DecisionInvalidationV2 | null;
  nextReviewConditionCodes: string[];
  freshness: DecisionFactFreshness;
  missingReasonCodes: string[];
  conflictReasonCodes: string[];
  dissentReasonCodes: string[];
  evidenceRefs: string[];
  primitiveFactorIds: string[];
  identities: {
    authorityPolicyId: string | null;
    authorityPolicySha256: string | null;
    marketTruth: { status: ArtifactReferenceStatus; snapshotId: string | null; observationId: string | null };
    predictionLedger: { status: ArtifactReferenceStatus; contextId: string | null };
    sho: { status: ArtifactReferenceStatus; artifactId: string | null };
    risk: { status: 'READY' | 'DATA_GATED'; riskKernelId: string | null };
  };
  sevenSign: SevenSignProjectionV1;
}

export interface PredictionLedgerSdaAdapterV2 {
  schemaVersion: typeof PREDICTION_LEDGER_SDA_ADAPTER_V2_SCHEMA_VERSION;
  adapterId: string;
  recordType: 'canonical_decision_binding';
  appendMode: 'APPEND_ONLY';
  mutatesExistingRows: false;
  decisionId: string;
  verifiedEvidenceBundleId: string;
  issuedAt: string | null;
  informationCutoffAt: string | null;
  subject: DecisionSubjectV2 | null;
  authorityPolicyRef: { policyId: string | null; policySha256: string | null };
  marketTruthRef: SingleDecisionAuthorityResultV2['identities']['marketTruth'];
  predictionLedgerRef: SingleDecisionAuthorityResultV2['identities']['predictionLedger'];
  shoRef: SingleDecisionAuthorityResultV2['identities']['sho'];
  riskRef: SingleDecisionAuthorityResultV2['identities']['risk'];
  singleDecisionRef: { schemaVersion: typeof SINGLE_DECISION_AUTHORITY_V2_SCHEMA_VERSION; decisionId: string };
  sevenSignRef: {
    schemaVersion: typeof SEVEN_SIGN_SCHEMA_VERSION;
    status: SevenSignProjectionV1['status'];
    policyId: string | null;
    policySha256: string | null;
    calibrationArtifactId: string | null;
    candidateLevel: number | null;
    productionLevel: number | null;
  };
  primaryAction: PrimaryAction;
  confidenceBps: number;
  targets: DecisionTargetV2[];
  invalidation: DecisionInvalidationV2 | null;
  missingReasonCodes: string[];
  conflictReasonCodes: string[];
  dissentReasonCodes: string[];
  evidenceRefs: string[];
  primitiveFactorIds: string[];
}

const SDA_INPUT_KEYS = [
  'schemaVersion', 'subject', 'decisionAt', 'informationCutoffAt', 'authorityPolicy',
  'marketTruth', 'predictionLedger', 'sho', 'riskKernel', 'contextEvidence', 'quality',
  'ownerContext', 'challengeEvidence', 'sevenSignCalibration',
] as const;
const SDA_SUBJECT_KEYS = ['kind', 'instrumentId', 'market', 'horizon'] as const;
const MARKET_TRUTH_KEYS = [
  'status', 'schemaVersion', 'snapshotId', 'observationId', 'observedAt', 'knownAt',
  'policyId', 'policySha256',
] as const;
const PREDICTION_LEDGER_KEYS = [
  'status', 'schemaVersion', 'contextId', 'mode', 'asOf', 'policyId', 'policySha256',
] as const;
const SHO_KEYS = [
  'status', 'schemaVersion', 'artifactId', 'asOf', 'policyId', 'policySha256', 'state',
  'validationStatus', 'primitiveFactorIds', 'targets', 'invalidation',
] as const;
const TARGET_KEYS = ['targetId', 'value', 'unit', 'sourceRef'] as const;
const INVALIDATION_KEYS = ['invalidationId', 'value', 'unit', 'sourceRef'] as const;
const CONTEXT_KEYS = [
  'evidenceRef', 'primitiveFactorId', 'sourceKind', 'constraint', 'status', 'observedAt',
] as const;
const DECISION_QUALITY_KEYS = [
  'status', 'freshness', 'missingReasonCodes', 'conflictReasonCodes',
] as const;
const CHALLENGE_KEYS = [
  'challengeId', 'sourceKind', 'status', 'asOf', 'proposedAction',
  'dissentReasonCodes', 'evidenceRefs',
] as const;
const CALIBRATION_KEYS = [
  'status', 'artifactId', 'policyId', 'policySha256', 'expectancyBpsByLevel',
  'sampleSizeByLevel', 'outOfSample', 'holdoutImmutable',
] as const;
const SDA_RESULT_KEYS = [
  'schemaVersion', 'decisionId', 'verifiedEvidenceBundleId', 'status', 'subject', 'issuedAt', 'informationCutoffAt',
  'primaryAction', 'confidence', 'guidance', 'targets', 'invalidation',
  'nextReviewConditionCodes', 'freshness', 'missingReasonCodes', 'conflictReasonCodes',
  'dissentReasonCodes', 'evidenceRefs', 'primitiveFactorIds', 'identities', 'sevenSign',
] as const;
const SDA_CONFIDENCE_KEYS = ['valueBps', 'status'] as const;
const SDA_GUIDANCE_KEYS = ['position', 'riskConstraint'] as const;
const SDA_IDENTITIES_KEYS = [
  'authorityPolicyId', 'authorityPolicySha256', 'marketTruth', 'predictionLedger', 'sho', 'risk',
] as const;
const SDA_MARKET_IDENTITY_KEYS = ['status', 'snapshotId', 'observationId'] as const;
const SDA_PREDICTION_IDENTITY_KEYS = ['status', 'contextId'] as const;
const SDA_SHO_IDENTITY_KEYS = ['status', 'artifactId'] as const;
const SDA_RISK_IDENTITY_KEYS = ['status', 'riskKernelId'] as const;
const SEVEN_RESULT_KEYS = [
  'schemaVersion', 'status', 'candidateLevel', 'productionLevel', 'policyId', 'policySha256',
  'calibrationArtifactId', 'reasonCodes',
] as const;
const SDA_ADAPTER_KEYS = [
  'schemaVersion', 'adapterId', 'recordType', 'appendMode', 'mutatesExistingRows',
  'decisionId', 'verifiedEvidenceBundleId', 'issuedAt', 'informationCutoffAt', 'subject',
  'authorityPolicyRef', 'marketTruthRef', 'predictionLedgerRef', 'shoRef', 'riskRef',
  'singleDecisionRef', 'sevenSignRef', 'primaryAction', 'confidenceBps', 'targets',
  'invalidation', 'missingReasonCodes', 'conflictReasonCodes', 'dissentReasonCodes',
  'evidenceRefs', 'primitiveFactorIds',
] as const;
const REFERENCE_STATUSES = new Set<ArtifactReferenceStatus>([
  'AVAILABLE', 'MISSING', 'CONFLICT', 'STALE',
]);
const SHO_STATES = new Set<ShoState>([
  'FRAGILE', 'DOWNSIDE_TRIGGERED', 'SELL_OFF_ACTIVE', 'REVERSAL_EARLY',
  'TECHNICAL_REBOUND', 'RECOVERY_TEST', 'CONFIRMED_ADVANCE', 'FALSE_RALLY', 'MIXED',
]);
const BUY_ELIGIBLE_SHO_STATES = new Set<ShoState>([
  'REVERSAL_EARLY', 'TECHNICAL_REBOUND', 'RECOVERY_TEST', 'CONFIRMED_ADVANCE',
]);
const SHO_VALIDATION_STATUSES = new Set<ShoValidationStatus>([
  'VALIDATED', 'UNVALIDATED', 'DATA_GATED', 'CONFLICT',
]);

function validateNullableId(value: unknown, path: string, errors: string[]): void {
  if (value !== null && (typeof value !== 'string' || !V2_ID_RE.test(value))) {
    errors.push(`${path}: malformed`);
  }
}

function validateNullableArtifact(value: unknown, path: string, errors: string[]): void {
  if (value !== null && (typeof value !== 'string' || !V2_ARTIFACT_ID_RE.test(value)
      || value.includes('://'))) errors.push(`${path}: malformed`);
}

function validateNullableSha(value: unknown, path: string, errors: string[]): void {
  if (value !== null && (typeof value !== 'string' || !SHA64_RE.test(value))) {
    errors.push(`${path}: malformed`);
  }
}

function validateCanonicalStringsV2(
  value: unknown,
  path: string,
  cap: number,
  errors: string[],
  pattern: RegExp = V2_ID_RE,
): value is string[] {
  if (!Array.isArray(value) || value.length > cap) {
    errors.push(`${path}: must be an array of at most ${cap}`);
    return false;
  }
  if (!value.every((item) => typeof item === 'string' && pattern.test(item))) {
    errors.push(`${path}: malformed identifier`);
    return false;
  }
  if (JSON.stringify(value) !== JSON.stringify([...new Set(value)].sort())) {
    errors.push(`${path}: must be sorted and duplicate-free`);
  }
  return true;
}

function validateDecisionSubjectV2(value: unknown, path: string, errors: string[]): boolean {
  if (!hasExactKeys(value, SDA_SUBJECT_KEYS)) {
    errors.push(`${path}: keys must be exact`);
    return false;
  }
  if (value.kind !== 'ASSET') errors.push(`${path}.kind: must equal ASSET`);
  if (typeof value.instrumentId !== 'string' || !INSTRUMENT_RE.test(value.instrumentId)) {
    errors.push(`${path}.instrumentId: malformed`);
  }
  if (!MARKETS.has(value.market as DecisionMarket)) errors.push(`${path}.market: unknown`);
  if (!HORIZONS.has(value.horizon as DecisionHorizon)) errors.push(`${path}.horizon: unknown`);
  return true;
}

function validatePittedTimestamp(
  value: unknown,
  path: string,
  cutoffMs: number,
  errors: string[],
  nullable = true,
): boolean {
  if (nullable && value === null) return true;
  if (!isExactUtc(value) || Date.parse(value) > cutoffMs) {
    errors.push(`${path}: malformed or later than information cutoff`);
    return false;
  }
  return true;
}

function validateDecisionTargetV2(
  value: unknown,
  path: string,
  errors: string[],
  invalidation: boolean,
): boolean {
  const keys = invalidation ? INVALIDATION_KEYS : TARGET_KEYS;
  if (!hasExactKeys(value, keys)) {
    errors.push(`${path}: keys must be exact`);
    return false;
  }
  const id = invalidation ? value.invalidationId : value.targetId;
  if (typeof id !== 'string' || !V2_ID_RE.test(id)) errors.push(`${path}: malformed identifier`);
  if (!validateDecimal(value.value)) errors.push(`${path}.value: invalid canonical decimal`);
  if (!['PRICE', 'PERCENT', 'RATIO', 'NONE'].includes(value.unit as string)) {
    errors.push(`${path}.unit: unknown`);
  }
  if (typeof value.sourceRef !== 'string' || !V2_ARTIFACT_ID_RE.test(value.sourceRef)
      || value.sourceRef.includes('://')) errors.push(`${path}.sourceRef: malformed`);
  return true;
}

export function validateSingleDecisionAuthorityInputV2(value: unknown): ContractValidationResult {
  const errors: string[] = [];
  if (!hasExactKeys(value, SDA_INPUT_KEYS)) {
    return { ok: false, errors: Object.freeze(['input: keys must be exact']) };
  }
  if (value.schemaVersion !== SINGLE_DECISION_AUTHORITY_INPUT_V2_SCHEMA_VERSION) {
    errors.push('schemaVersion: mismatch');
  }
  validateDecisionSubjectV2(value.subject, 'subject', errors);
  const decisionValid = isExactUtc(value.decisionAt);
  const cutoffValid = isExactUtc(value.informationCutoffAt);
  if (!decisionValid) errors.push('decisionAt: invalid UTC timestamp');
  if (!cutoffValid) errors.push('informationCutoffAt: invalid UTC timestamp');
  const decisionMs = decisionValid ? Date.parse(value.decisionAt as string) : Number.NaN;
  const cutoffMs = cutoffValid ? Date.parse(value.informationCutoffAt as string) : Number.NaN;
  if (decisionValid && cutoffValid && cutoffMs > decisionMs) {
    errors.push('informationCutoffAt: later than decisionAt');
  }
  validateV2Policy(value.authorityPolicy, 'authorityPolicy', errors);
  if (isRecord(value.authorityPolicy)
      && (value.authorityPolicy.policyId !== SINGLE_DECISION_AUTHORITY_V2_POLICY.policyId
        || value.authorityPolicy.policySha256 !== SINGLE_DECISION_AUTHORITY_V2_POLICY.policySha256)) {
    errors.push('authorityPolicy: must equal repository-pinned SDA v2 policy');
  }

  if (!hasExactKeys(value.marketTruth, MARKET_TRUTH_KEYS)) {
    errors.push('marketTruth: keys must be exact');
  } else {
    const ref = value.marketTruth;
    if (!REFERENCE_STATUSES.has(ref.status as ArtifactReferenceStatus)) errors.push('marketTruth.status: unknown');
    validateNullableId(ref.schemaVersion, 'marketTruth.schemaVersion', errors);
    validateNullableArtifact(ref.snapshotId, 'marketTruth.snapshotId', errors);
    validateNullableArtifact(ref.observationId, 'marketTruth.observationId', errors);
    validatePittedTimestamp(ref.observedAt, 'marketTruth.observedAt', cutoffMs, errors);
    validatePittedTimestamp(ref.knownAt, 'marketTruth.knownAt', cutoffMs, errors);
    validateNullableId(ref.policyId, 'marketTruth.policyId', errors);
    validateNullableSha(ref.policySha256, 'marketTruth.policySha256', errors);
    const required = [
      ref.schemaVersion, ref.snapshotId, ref.observationId, ref.observedAt, ref.knownAt,
      ref.policyId, ref.policySha256,
    ];
    if (ref.status === 'AVAILABLE' && required.some((item) => item === null)) {
      errors.push('marketTruth: AVAILABLE requires complete identity');
    }
    if (ref.status === 'AVAILABLE' && isExactUtc(ref.observedAt) && isExactUtc(ref.knownAt)
        && Date.parse(ref.observedAt) > Date.parse(ref.knownAt)) {
      errors.push('marketTruth.knownAt: earlier than observedAt');
    }
    if (ref.status === 'MISSING'
        && [ref.snapshotId, ref.observationId, ref.observedAt, ref.knownAt]
          .some((item) => item !== null)) errors.push('marketTruth: MISSING claims artifact data');
  }

  if (!hasExactKeys(value.predictionLedger, PREDICTION_LEDGER_KEYS)) {
    errors.push('predictionLedger: keys must be exact');
  } else {
    const ref = value.predictionLedger;
    if (!REFERENCE_STATUSES.has(ref.status as ArtifactReferenceStatus)) {
      errors.push('predictionLedger.status: unknown');
    }
    validateNullableId(ref.schemaVersion, 'predictionLedger.schemaVersion', errors);
    validateNullableArtifact(ref.contextId, 'predictionLedger.contextId', errors);
    if (ref.mode !== null && ref.mode !== 'FORWARD_LIVE') errors.push('predictionLedger.mode: invalid');
    validatePittedTimestamp(ref.asOf, 'predictionLedger.asOf', cutoffMs, errors);
    validateNullableId(ref.policyId, 'predictionLedger.policyId', errors);
    validateNullableSha(ref.policySha256, 'predictionLedger.policySha256', errors);
    if (ref.status === 'AVAILABLE'
        && [ref.schemaVersion, ref.contextId, ref.mode, ref.asOf, ref.policyId, ref.policySha256]
          .some((item) => item === null)) errors.push('predictionLedger: AVAILABLE requires complete identity');
    if (ref.status === 'MISSING' && [ref.contextId, ref.mode, ref.asOf].some((item) => item !== null)) {
      errors.push('predictionLedger: MISSING claims a context');
    }
  }

  if (!hasExactKeys(value.sho, SHO_KEYS)) {
    errors.push('sho: keys must be exact');
  } else {
    const ref = value.sho;
    if (!REFERENCE_STATUSES.has(ref.status as ArtifactReferenceStatus)) errors.push('sho.status: unknown');
    validateNullableId(ref.schemaVersion, 'sho.schemaVersion', errors);
    validateNullableArtifact(ref.artifactId, 'sho.artifactId', errors);
    validatePittedTimestamp(ref.asOf, 'sho.asOf', cutoffMs, errors);
    validateNullableId(ref.policyId, 'sho.policyId', errors);
    validateNullableSha(ref.policySha256, 'sho.policySha256', errors);
    if (ref.state !== null && !SHO_STATES.has(ref.state as ShoState)) errors.push('sho.state: unknown');
    if (ref.validationStatus !== null
        && !SHO_VALIDATION_STATUSES.has(ref.validationStatus as ShoValidationStatus)) {
      errors.push('sho.validationStatus: unknown');
    }
    validateCanonicalStringsV2(ref.primitiveFactorIds, 'sho.primitiveFactorIds', 48, errors);
    if (!Array.isArray(ref.targets) || ref.targets.length > 4) {
      errors.push('sho.targets: must be an array of at most 4');
    } else {
      ref.targets.forEach((target, index) => validateDecisionTargetV2(
        target, `sho.targets[${index}]`, errors, false));
      const targetIds = ref.targets.map((target) => isRecord(target) ? target.targetId : null);
      if (JSON.stringify(targetIds) !== JSON.stringify([...new Set(targetIds)].sort())) {
        errors.push('sho.targets: must be sorted and unique');
      }
    }
    if (ref.invalidation !== null) validateDecisionTargetV2(ref.invalidation, 'sho.invalidation', errors, true);
    if (ref.status === 'AVAILABLE'
        && [ref.schemaVersion, ref.artifactId, ref.asOf, ref.policyId, ref.policySha256,
          ref.state, ref.validationStatus].some((item) => item === null)) {
      errors.push('sho: AVAILABLE requires complete identity and state');
    }
    if (ref.status === 'MISSING'
        && ([ref.artifactId, ref.asOf, ref.state, ref.validationStatus].some((item) => item !== null)
          || (Array.isArray(ref.primitiveFactorIds) && ref.primitiveFactorIds.length > 0)
          || (Array.isArray(ref.targets) && ref.targets.length > 0)
          || ref.invalidation !== null)) errors.push('sho: MISSING claims evidence');
  }

  const riskValidation = validateRiskKernel(value.riskKernel);
  errors.push(...riskValidation.errors.map((error) => `riskKernel: ${error}`));
  if (riskValidation.ok && isRecord(value.riskKernel) && isRecord(value.riskKernel.subject)
      && isRecord(value.subject)) {
    if (value.riskKernel.subject.kind !== value.subject.kind
        || value.riskKernel.subject.instrumentId !== value.subject.instrumentId
        || value.riskKernel.subject.market !== value.subject.market) {
      errors.push('riskKernel.subject: does not match authority subject');
    }
    if (value.riskKernel.informationCutoffAt !== value.informationCutoffAt) {
      errors.push('riskKernel.informationCutoffAt: does not match authority cutoff');
    }
    if (!isExactUtc(value.riskKernel.asOf) || Date.parse(value.riskKernel.asOf) > decisionMs) {
      errors.push('riskKernel.asOf: later than decisionAt');
    }
  }

  if (!Array.isArray(value.contextEvidence)
      || value.contextEvidence.length < 1 || value.contextEvidence.length > 16) {
    errors.push('contextEvidence: must contain 1 through 16 rows');
  } else {
    const identities: string[] = [];
    value.contextEvidence.forEach((raw, index) => {
      const path = `contextEvidence[${index}]`;
      if (!hasExactKeys(raw, CONTEXT_KEYS)) {
        errors.push(`${path}: keys must be exact`);
        return;
      }
      if (typeof raw.evidenceRef !== 'string' || !V2_ARTIFACT_ID_RE.test(raw.evidenceRef)
          || raw.evidenceRef.includes('://')) errors.push(`${path}.evidenceRef: malformed`);
      if (typeof raw.primitiveFactorId !== 'string' || !V2_ID_RE.test(raw.primitiveFactorId)) {
        errors.push(`${path}.primitiveFactorId: malformed`);
      }
      if (!['SCENARIO', 'EVENT'].includes(raw.sourceKind as string)) errors.push(`${path}.sourceKind: unknown`);
      if (!['NONE', 'WAIT_REQUIRED'].includes(raw.constraint as string)) errors.push(`${path}.constraint: unknown`);
      if (!['ACTIVE', 'INACTIVE', 'MISSING', 'CONFLICT'].includes(raw.status as string)) {
        errors.push(`${path}.status: unknown`);
      }
      if (raw.status !== 'ACTIVE' && raw.constraint !== 'NONE') errors.push(`${path}.constraint: invalid`);
      validatePittedTimestamp(raw.observedAt, `${path}.observedAt`, cutoffMs, errors, false);
      identities.push(`${String(raw.primitiveFactorId)}\u0000${String(raw.evidenceRef)}`);
    });
    if (JSON.stringify(identities) !== JSON.stringify([...new Set(identities)].sort())) {
      errors.push('contextEvidence: must be sorted and unique');
    }
  }

  if (!hasExactKeys(value.quality, DECISION_QUALITY_KEYS)) {
    errors.push('quality: keys must be exact');
  } else {
    const quality = value.quality;
    if (!['COMPLETE', 'PARTIAL', 'MISSING', 'CONFLICT'].includes(quality.status as string)) {
      errors.push('quality.status: unknown');
    }
    if (!FRESHNESS_VALUES.has(quality.freshness as DecisionFactFreshness)) errors.push('quality.freshness: unknown');
    validateCanonicalStringsV2(quality.missingReasonCodes, 'quality.missingReasonCodes', 24, errors);
    validateCanonicalStringsV2(quality.conflictReasonCodes, 'quality.conflictReasonCodes', 24, errors);
    if (quality.status === 'COMPLETE' && (Array.isArray(quality.missingReasonCodes)
        && quality.missingReasonCodes.length > 0 || Array.isArray(quality.conflictReasonCodes)
        && quality.conflictReasonCodes.length > 0)) errors.push('quality.status: COMPLETE carries reasons');
    if (['PARTIAL', 'MISSING'].includes(quality.status as string)
        && Array.isArray(quality.missingReasonCodes) && quality.missingReasonCodes.length === 0) {
      errors.push('quality.missingReasonCodes: required');
    }
    if (quality.status === 'CONFLICT' && Array.isArray(quality.conflictReasonCodes)
        && quality.conflictReasonCodes.length === 0) errors.push('quality.conflictReasonCodes: required');
  }

  const ownerValidation = validateOwnerDecisionContext(value.ownerContext);
  errors.push(...ownerValidation.errors.map((error) => `ownerContext: ${error}`));
  if (ownerValidation.ok && isRecord(value.ownerContext)
      && (!isExactUtc(value.ownerContext.asOf) || Date.parse(value.ownerContext.asOf) > decisionMs)) {
    errors.push('ownerContext.asOf: later than decisionAt');
  }

  if (!Array.isArray(value.challengeEvidence) || value.challengeEvidence.length > 8) {
    errors.push('challengeEvidence: must be an array of at most 8');
  } else {
    const ids: unknown[] = [];
    value.challengeEvidence.forEach((raw, index) => {
      const path = `challengeEvidence[${index}]`;
      if (!hasExactKeys(raw, CHALLENGE_KEYS)) {
        errors.push(`${path}: keys must be exact`);
        return;
      }
      ids.push(raw.challengeId);
      if (typeof raw.challengeId !== 'string' || !V2_ID_RE.test(raw.challengeId)) {
        errors.push(`${path}.challengeId: malformed`);
      }
      if (!['AI', 'LEGACY'].includes(raw.sourceKind as string)) errors.push(`${path}.sourceKind: unknown`);
      if (!['AVAILABLE', 'MISSING'].includes(raw.status as string)) errors.push(`${path}.status: unknown`);
      if (!isExactUtc(raw.asOf) || Date.parse(raw.asOf) > decisionMs) errors.push(`${path}.asOf: invalid`);
      if (raw.proposedAction !== null && !PRIMARY_ACTIONS.includes(raw.proposedAction as PrimaryAction)) {
        errors.push(`${path}.proposedAction: unknown`);
      }
      validateCanonicalStringsV2(raw.dissentReasonCodes, `${path}.dissentReasonCodes`, 24, errors);
      validateCanonicalStringsV2(raw.evidenceRefs, `${path}.evidenceRefs`, 48, errors, SOURCE_REF_RE);
      if (raw.status === 'MISSING' && (raw.proposedAction !== null
          || Array.isArray(raw.dissentReasonCodes) && raw.dissentReasonCodes.length > 0
          || Array.isArray(raw.evidenceRefs) && raw.evidenceRefs.length > 0)) {
        errors.push(`${path}: MISSING challenge claims evidence`);
      }
    });
    if (JSON.stringify(ids) !== JSON.stringify([...new Set(ids)].sort())) {
      errors.push('challengeEvidence: must be sorted and unique');
    }
  }

  if (!hasExactKeys(value.sevenSignCalibration, CALIBRATION_KEYS)) {
    errors.push('sevenSignCalibration: keys must be exact');
  } else {
    const calibration = value.sevenSignCalibration;
    if (!['VALIDATED', 'SHADOW', 'DATA_GATED', 'MISSING'].includes(calibration.status as string)) {
      errors.push('sevenSignCalibration.status: unknown');
    }
    validateNullableArtifact(calibration.artifactId, 'sevenSignCalibration.artifactId', errors);
    validateNullableId(calibration.policyId, 'sevenSignCalibration.policyId', errors);
    validateNullableSha(calibration.policySha256, 'sevenSignCalibration.policySha256', errors);
    const expectancy = calibration.expectancyBpsByLevel;
    if (expectancy !== null && (!Array.isArray(expectancy) || expectancy.length !== 7
        || !expectancy.every((item) => Number.isInteger(item) && item >= -100_000 && item <= 100_000))) {
      errors.push('sevenSignCalibration.expectancyBpsByLevel: invalid');
    }
    const samples = calibration.sampleSizeByLevel;
    if (samples !== null && (!Array.isArray(samples) || samples.length !== 7
        || !samples.every((item) => Number.isInteger(item) && item >= 0 && item <= 1_000_000_000))) {
      errors.push('sevenSignCalibration.sampleSizeByLevel: invalid');
    }
    if (typeof calibration.outOfSample !== 'boolean') errors.push('sevenSignCalibration.outOfSample: invalid');
    if (typeof calibration.holdoutImmutable !== 'boolean') errors.push('sevenSignCalibration.holdoutImmutable: invalid');
    if (calibration.status === 'VALIDATED'
        && [calibration.artifactId, calibration.policyId, calibration.policySha256,
          expectancy, samples].some((item) => item === null)) {
      errors.push('sevenSignCalibration: VALIDATED requires complete identity and arrays');
    }
    if (calibration.status === 'MISSING'
        && ([calibration.artifactId, calibration.policyId, calibration.policySha256,
          expectancy, samples].some((item) => item !== null)
          || calibration.outOfSample !== false || calibration.holdoutImmutable !== false)) {
      errors.push('sevenSignCalibration: MISSING claims calibration');
    }
  }

  if (errors.length === 0
      && new TextEncoder().encode(stableJson(value as unknown as JsonValue)).byteLength > 128 * 1024) {
    errors.push('input: canonical body exceeds 131072 bytes');
  }
  return { ok: errors.length === 0, errors: Object.freeze(errors) };
}

function uniqueBounded(items: string[], cap: number): string[] {
  return [...new Set(items)].sort().slice(0, cap);
}

function ownerContextIsUnknown(owner: OwnerDecisionContext): boolean {
  return owner.positionState === 'UNKNOWN' || owner.positionRiskBand === 'UNKNOWN'
    || owner.concentrationBand === 'UNKNOWN' || owner.addPermission === 'UNKNOWN';
}

export type VerifiedDecisionEvidenceBundleV2 = SingleDecisionAuthorityInputV2;

/**
 * Admit an ordinary frontend request only after runtime verification.
 *
 * The browser has no canonical Market Truth/Ledger/SHO store or accepted
 * verifier.  Consequently it may issue an opaque capability only for the
 * explicit non-authoritative/missing-artifact path.  AVAILABLE references
 * must be resolved by the backend canonical boundary in a future, separately
 * reviewed integration; a plain object can never activate them here.
 */
export function verifyDecisionEvidence(
  value: unknown,
): VerifiedDecisionEvidenceBundleV2 {
  if (!isRecord(value)) throw new TypeError('input: must be an object');
  if (!Object.prototype.hasOwnProperty.call(value, 'authorityPolicy')) {
    value.authorityPolicy = deepClone(SINGLE_DECISION_AUTHORITY_V2_POLICY);
  }
  const validation = validateSingleDecisionAuthorityInputV2(value);
  if (!validation.ok) throw new TypeError(validation.errors.join('; '));
  const input = value as unknown as SingleDecisionAuthorityInputV2;
  if ([input.marketTruth, input.predictionLedger, input.sho]
    .some((reference) => reference.status === 'AVAILABLE')) {
    throw new TypeError('canonical_artifact_resolver_unavailable');
  }
  const riskSeal = VERIFIED_RISK_KERNELS.get(input.riskKernel);
  if (riskSeal == null || riskSeal !== stableJson(input.riskKernel as unknown as JsonValue)) {
    throw new TypeError('risk_kernel_not_verifier_issued');
  }
  const verification = {
    schemaVersion: 'verified-decision-evidence-bundle-v1',
    authorityPolicy: SINGLE_DECISION_AUTHORITY_V2_POLICY,
    marketTruth: null,
    predictionLedger: null,
    sho: null,
    riskKernelId: input.riskKernel.riskKernelId,
  } as const;
  const canonicalInput = stableJson(input as unknown as JsonValue);
  const bundleId = `vdeb-${sha256HexSync(stableJson({
    input, verification,
  } as unknown as JsonValue))}`;
  VERIFIED_DECISION_BUNDLES.set(input, {
    bundleId,
    canonicalInput,
    shoBuyEligible: false,
  });
  return input;
}

function referenceReasons(
  prefix: string,
  status: ArtifactReferenceStatus,
): { missing: string[]; conflicts: string[] } {
  if (status === 'AVAILABLE') return { missing: [], conflicts: [] };
  if (status === 'CONFLICT') return { missing: [], conflicts: [`${prefix}_conflict`] };
  return { missing: [`${prefix}_${status.toLowerCase()}`], conflicts: [] };
}

function selectPrimaryActionV2(
  input: SingleDecisionAuthorityInputV2,
  dataGated: boolean,
  shoBuyEligible: boolean,
): PrimaryAction {
  const held = input.ownerContext.positionState === 'HELD';
  if (dataGated) return 'WAIT';
  switch (input.riskKernel.constraint) {
    case 'EXIT_RISK': return held ? 'EXIT' : 'WAIT';
    case 'REDUCE_RISK': return held ? 'REDUCE' : 'WAIT';
    case 'WAIT_REQUIRED': return 'WAIT';
    case 'BLOCK_BUY': return held ? 'HOLD' : 'WAIT';
    default: break;
  }
  const buyReady = input.sho.validationStatus === 'VALIDATED'
    && shoBuyEligible
    && input.sho.state !== null
    && BUY_ELIGIBLE_SHO_STATES.has(input.sho.state)
    && input.ownerContext.addPermission === 'ALLOWED';
  if (buyReady) return 'BUY';
  return held ? 'HOLD' : 'WAIT';
}

function sevenCandidateV2(
  action: PrimaryAction,
  input: SingleDecisionAuthorityInputV2,
  dataGated: boolean,
): number | null {
  if (dataGated) return null;
  if (action === 'EXIT') return 1;
  if (action === 'REDUCE') return 2;
  if (action === 'WAIT') {
    const defensive = input.riskKernel.constraint !== 'NONE';
    return defensive ? 3 : 4;
  }
  if (action === 'HOLD') return 4;
  if (input.sho.state === 'CONFIRMED_ADVANCE') return 7;
  if (input.sho.state === 'TECHNICAL_REBOUND' || input.sho.state === 'RECOVERY_TEST') return 6;
  return 5;
}

function sevenSignProjectionV2(
  action: PrimaryAction,
  input: SingleDecisionAuthorityInputV2,
  dataGated: boolean,
): SevenSignProjectionV1 {
  const calibration = input.sevenSignCalibration;
  const candidateLevel = sevenCandidateV2(action, input, dataGated);
  const reasons: string[] = [];
  let status: SevenSignProjectionV1['status'] = 'DATA_GATED';
  let productionLevel: number | null = null;
  if (dataGated) {
    reasons.push('decision_data_gated');
  } else if (calibration.status === 'SHADOW') {
    status = 'SHADOW';
    reasons.push('calibration_shadow');
  } else if (calibration.status !== 'VALIDATED') {
    reasons.push(`calibration_${calibration.status.toLowerCase()}`);
  } else {
    const expectancy = calibration.expectancyBpsByLevel as number[];
    const samples = calibration.sampleSizeByLevel as number[];
    const monotonic = expectancy.slice(0, 6).every((item, index) => item <= expectancy[index + 1]);
    const adequate = samples.every((sample) => sample >= 30);
    if (!monotonic) reasons.push('calibration_non_monotonic');
    if (!adequate) reasons.push('calibration_sample_insufficient');
    if (!calibration.outOfSample) reasons.push('calibration_not_out_of_sample');
    if (!calibration.holdoutImmutable) reasons.push('calibration_holdout_mutable');
    // Production promotion is closed over pinned, independently verified
    // calibration identities. The registry remains empty until such an
    // artifact is approved; caller-supplied booleans never grant authority.
    const verifiedCalibrationIdentities = Object.freeze(new Set<string>());
    const calibrationKey = [
      calibration.artifactId, calibration.policyId, calibration.policySha256,
    ].join('|');
    if (!verifiedCalibrationIdentities.has(calibrationKey)) {
      reasons.push('calibration_artifact_not_verified');
    }
    if (reasons.length === 0) {
      status = 'PRODUCTION';
      productionLevel = candidateLevel;
    }
  }
  return {
    schemaVersion: SEVEN_SIGN_SCHEMA_VERSION,
    status,
    candidateLevel,
    productionLevel,
    policyId: calibration.policyId,
    policySha256: calibration.policySha256,
    calibrationArtifactId: calibration.artifactId,
    reasonCodes: uniqueBounded(reasons, 24),
  };
}

function positionGuidanceV2(action: PrimaryAction): SingleDecisionAuthorityResultV2['guidance']['position'] {
  return {
    BUY: 'ENTER_OR_ADD', HOLD: 'MAINTAIN', WAIT: 'NO_ACTION',
    REDUCE: 'REDUCE_EXPOSURE', EXIT: 'EXIT_POSITION',
  }[action] as SingleDecisionAuthorityResultV2['guidance']['position'];
}

export function computeSingleDecisionId(
  resultOrBody: SingleDecisionAuthorityResultV2 | Omit<SingleDecisionAuthorityResultV2, 'decisionId'>,
): string {
  const { decisionId: _ignored, ...body } = resultOrBody as SingleDecisionAuthorityResultV2;
  return `sda-${sha256HexSync(stableJson(body as unknown as JsonValue))}`;
}

function resultFromValidInputV2(
  input: SingleDecisionAuthorityInputV2,
  runtime: VerifiedBundleRuntimeState,
): SingleDecisionAuthorityResultV2 {
  const missing = [...input.quality.missingReasonCodes];
  const conflicts = [...input.quality.conflictReasonCodes];
  ([
    ['market_truth', input.marketTruth.status],
    ['prediction_ledger', input.predictionLedger.status],
    ['sho', input.sho.status],
  ] as [string, ArtifactReferenceStatus][]).forEach(([prefix, status]) => {
    const reasons = referenceReasons(prefix, status);
    missing.push(...reasons.missing);
    conflicts.push(...reasons.conflicts);
  });
  missing.push(...input.riskKernel.missingReasonCodes);
  conflicts.push(...input.riskKernel.conflictReasonCodes);
  const ownerUnknown = ownerContextIsUnknown(input.ownerContext);
  if (ownerUnknown) missing.push('owner_context_unknown');
  if (input.quality.status !== 'COMPLETE') missing.push(`quality_${input.quality.status.toLowerCase()}`);
  if (input.quality.freshness !== 'FRESH') {
    missing.push(`freshness_${input.quality.freshness.toLowerCase()}`);
  }
  const dataGated = missing.length > 0 || conflicts.length > 0
    || input.riskKernel.status !== 'READY'
    || input.marketTruth.status !== 'AVAILABLE'
    || input.predictionLedger.status !== 'AVAILABLE'
    || input.sho.status !== 'AVAILABLE'
    || ownerUnknown;
  const primaryAction = selectPrimaryActionV2(input, dataGated, runtime.shoBuyEligible);
  const confidenceBase: Record<PrimaryAction, number> = {
    BUY: 7_000, HOLD: 6_000, WAIT: 4_500, REDUCE: 7_000, EXIT: 8_000,
  };
  let confidence = Math.min(confidenceBase[primaryAction], input.riskKernel.confidenceCapBps);
  if (dataGated) confidence = Math.min(confidence, 2_500);

  const riskRefs = input.riskKernel.primitiveFactors.flatMap((factor) => factor.evidenceRefs);
  const contextRefs = input.contextEvidence.map((row) => row.evidenceRef);
  const challengeRefs = input.challengeEvidence.flatMap((row) => row.evidenceRefs);
  const targetRefs = input.sho.targets.map((target) => target.sourceRef);
  if (input.sho.invalidation) targetRefs.push(input.sho.invalidation.sourceRef);
  const dissent: string[] = [];
  input.contextEvidence.forEach((row) => {
    if (row.status === 'MISSING') {
      dissent.push(`context_missing_advisory.${row.primitiveFactorId}`);
    }
    if (row.status === 'CONFLICT') {
      dissent.push(`context_conflict_advisory.${row.primitiveFactorId}`);
    }
    if (row.constraint !== 'NONE') dissent.push('context_constraint_advisory_only');
  });
  input.challengeEvidence.forEach((challenge) => {
    dissent.push(...challenge.dissentReasonCodes);
    if (challenge.proposedAction !== null) {
      dissent.push(`${challenge.sourceKind.toLowerCase()}_proposed_action_ignored`);
    }
  });
  const primitiveFactorIds = uniqueBounded([
    ...input.riskKernel.primitiveFactors.map((factor) => factor.primitiveFactorId),
    ...input.sho.primitiveFactorIds,
    ...input.contextEvidence.map((row) => row.primitiveFactorId),
  ], 48);
  const canonicalMissing = uniqueBounded(missing, 24);
  const canonicalConflicts = uniqueBounded(conflicts, 24);
  const nextReviewConditionCodes = uniqueBounded([
    ...canonicalMissing.map((reason) => `resolve.${reason}`),
    ...canonicalConflicts.map((reason) => `resolve.${reason}`),
    ...(input.riskKernel.constraint !== 'NONE' ? ['risk_reassessment'] : []),
    ...(input.sho.validationStatus !== 'VALIDATED' ? ['sho_revalidation'] : []),
  ], 24);
  const body: Omit<SingleDecisionAuthorityResultV2, 'decisionId'> = {
    schemaVersion: SINGLE_DECISION_AUTHORITY_V2_SCHEMA_VERSION,
    verifiedEvidenceBundleId: runtime.bundleId,
    status: dataGated ? 'DATA_GATED' : 'EVALUATED',
    subject: deepClone(input.subject),
    issuedAt: input.decisionAt,
    informationCutoffAt: input.informationCutoffAt,
    primaryAction,
    confidence: { valueBps: confidence, status: 'BOUNDED' },
    guidance: { position: positionGuidanceV2(primaryAction), riskConstraint: input.riskKernel.constraint },
    targets: deepClone(input.sho.targets),
    invalidation: deepClone(input.sho.invalidation),
    nextReviewConditionCodes,
    freshness: input.quality.freshness,
    missingReasonCodes: canonicalMissing,
    conflictReasonCodes: canonicalConflicts,
    dissentReasonCodes: uniqueBounded(dissent, 24),
    evidenceRefs: uniqueBounded([...riskRefs, ...contextRefs, ...challengeRefs, ...targetRefs], 48),
    primitiveFactorIds,
    identities: {
      authorityPolicyId: input.authorityPolicy.policyId,
      authorityPolicySha256: input.authorityPolicy.policySha256,
      marketTruth: {
        status: input.marketTruth.status,
        snapshotId: input.marketTruth.snapshotId,
        observationId: input.marketTruth.observationId,
      },
      predictionLedger: {
        status: input.predictionLedger.status,
        contextId: input.predictionLedger.contextId,
      },
      sho: { status: input.sho.status, artifactId: input.sho.artifactId },
      risk: { status: input.riskKernel.status, riskKernelId: input.riskKernel.riskKernelId },
    },
    sevenSign: sevenSignProjectionV2(primaryAction, input, dataGated),
  };
  const result: SingleDecisionAuthorityResultV2 = {
    decisionId: computeSingleDecisionId(body), ...body,
  };
  const validation = validateSingleDecisionAuthorityResultV2(result);
  if (!validation.ok) throw new TypeError(validation.errors.join('; '));
  VERIFIED_DECISION_RESULTS.set(result, {
    bundleId: runtime.bundleId,
    canonicalResult: stableJson(result as unknown as JsonValue),
  });
  return result;
}

function invalidSingleDecisionResultV2(): SingleDecisionAuthorityResultV2 {
  const body: Omit<SingleDecisionAuthorityResultV2, 'decisionId'> = {
    schemaVersion: SINGLE_DECISION_AUTHORITY_V2_SCHEMA_VERSION,
    verifiedEvidenceBundleId: null,
    status: 'DATA_GATED',
    subject: null,
    issuedAt: null,
    informationCutoffAt: null,
    primaryAction: 'WAIT',
    confidence: { valueBps: 0, status: 'BOUNDED' },
    guidance: { position: 'NO_ACTION', riskConstraint: 'WAIT_REQUIRED' },
    targets: [],
    invalidation: null,
    nextReviewConditionCodes: ['resolve.input_invalid'],
    freshness: 'UNKNOWN',
    missingReasonCodes: ['input_invalid'],
    conflictReasonCodes: [],
    dissentReasonCodes: [],
    evidenceRefs: [],
    primitiveFactorIds: [],
    identities: {
      authorityPolicyId: null,
      authorityPolicySha256: null,
      marketTruth: { status: 'MISSING', snapshotId: null, observationId: null },
      predictionLedger: { status: 'MISSING', contextId: null },
      sho: { status: 'MISSING', artifactId: null },
      risk: { status: 'DATA_GATED', riskKernelId: null },
    },
    sevenSign: {
      schemaVersion: SEVEN_SIGN_SCHEMA_VERSION,
      status: 'DATA_GATED',
      candidateLevel: null,
      productionLevel: null,
      policyId: null,
      policySha256: null,
      calibrationArtifactId: null,
      reasonCodes: ['decision_data_gated'],
    },
  };
  return { decisionId: computeSingleDecisionId(body), ...body };
}

/** Active v2 final-action authority. Invalid input is never thrown to the caller. */
export function evaluateSingleDecisionAuthority(value: unknown): SingleDecisionAuthorityResultV2 {
  if (!isRecord(value)) return deepClone(invalidSingleDecisionResultV2());
  const runtime = VERIFIED_DECISION_BUNDLES.get(value);
  if (runtime == null || runtime.canonicalInput !== stableJson(value as unknown as JsonValue)) {
    return deepClone(invalidSingleDecisionResultV2());
  }
  const validation = validateSingleDecisionAuthorityInputV2(value);
  if (!validation.ok) return deepClone(invalidSingleDecisionResultV2());
  return resultFromValidInputV2(value as unknown as SingleDecisionAuthorityInputV2, runtime);
}

export interface SingleDecisionAuthorityV2 {
  readonly status: 'ACTIVE_V2';
  evaluate(value: unknown): SingleDecisionAuthorityResultV2;
}

export const singleDecisionAuthority: SingleDecisionAuthorityV2 = Object.freeze({
  status: 'ACTIVE_V2' as const,
  evaluate: evaluateSingleDecisionAuthority,
});

export function validateSingleDecisionAuthorityResultV2(value: unknown): ContractValidationResult {
  const errors: string[] = [];
  if (!hasExactKeys(value, SDA_RESULT_KEYS)) {
    return { ok: false, errors: Object.freeze(['result: keys must be exact']) };
  }
  if (value.schemaVersion !== SINGLE_DECISION_AUTHORITY_V2_SCHEMA_VERSION) {
    errors.push('result.schemaVersion: mismatch');
  }
  if (typeof value.decisionId !== 'string' || !DECISION_ID_RE.test(value.decisionId)) {
    errors.push('result.decisionId: malformed');
  }
  if (value.verifiedEvidenceBundleId !== null
      && (typeof value.verifiedEvidenceBundleId !== 'string'
        || !VERIFIED_BUNDLE_ID_RE.test(value.verifiedEvidenceBundleId))) {
    errors.push('result.verifiedEvidenceBundleId: malformed');
  }
  if (!['EVALUATED', 'DATA_GATED'].includes(value.status as string)) errors.push('result.status: unknown');
  if (value.subject !== null) validateDecisionSubjectV2(value.subject, 'result.subject', errors);
  if (value.issuedAt !== null) {
    if (!isExactUtc(value.issuedAt)) errors.push('result.issuedAt: invalid');
    if (!isExactUtc(value.informationCutoffAt)) errors.push('result.informationCutoffAt: invalid');
    if (isExactUtc(value.issuedAt) && isExactUtc(value.informationCutoffAt)
        && Date.parse(value.informationCutoffAt) > Date.parse(value.issuedAt)) {
      errors.push('result.informationCutoffAt: later than issuedAt');
    }
  } else if (value.informationCutoffAt !== null) {
    errors.push('result.informationCutoffAt: must be null with null issuedAt');
  }
  if (!PRIMARY_ACTIONS.includes(value.primaryAction as PrimaryAction)) errors.push('result.primaryAction: unknown');
  if (value.status === 'DATA_GATED' && value.primaryAction !== 'WAIT') {
    errors.push('result.primaryAction: DATA_GATED must WAIT');
  }
  if (value.status === 'EVALUATED'
      && (value.verifiedEvidenceBundleId === null
        || !isRecord(value.identities)
        || value.identities.authorityPolicyId !== SINGLE_DECISION_AUTHORITY_V2_POLICY.policyId
        || value.identities.authorityPolicySha256 !== SINGLE_DECISION_AUTHORITY_V2_POLICY.policySha256)) {
    errors.push('result.identities: EVALUATED result lacks verified canonical authority');
  }
  if (value.verifiedEvidenceBundleId === null && value.subject !== null) {
    errors.push('result.verifiedEvidenceBundleId: non-invalid result requires verified evidence');
  }
  if (!hasExactKeys(value.confidence, SDA_CONFIDENCE_KEYS)) {
    errors.push('result.confidence: keys must be exact');
  } else {
    if (!isBps(value.confidence.valueBps)) errors.push('result.confidence.valueBps: invalid');
    if (value.confidence.status !== 'BOUNDED') errors.push('result.confidence.status: invalid');
  }
  if (!hasExactKeys(value.guidance, SDA_GUIDANCE_KEYS)) {
    errors.push('result.guidance: keys must be exact');
  } else {
    if (PRIMARY_ACTIONS.includes(value.primaryAction as PrimaryAction)
        && value.guidance.position !== positionGuidanceV2(value.primaryAction as PrimaryAction)) {
      errors.push('result.guidance.position: inconsistent');
    }
    if (!RISK_CONSTRAINTS.has(value.guidance.riskConstraint as RiskConstraint)) {
      errors.push('result.guidance.riskConstraint: unknown');
    }
  }
  if (!Array.isArray(value.targets) || value.targets.length > 4) {
    errors.push('result.targets: invalid');
  } else {
    value.targets.forEach((target, index) =>
      validateDecisionTargetV2(target, `result.targets[${index}]`, errors, false));
  }
  if (value.invalidation !== null) {
    validateDecisionTargetV2(value.invalidation, 'result.invalidation', errors, true);
  }
  for (const field of [
    'nextReviewConditionCodes', 'missingReasonCodes', 'conflictReasonCodes',
    'dissentReasonCodes', 'primitiveFactorIds',
  ] as const) validateCanonicalStringsV2(value[field], `result.${field}`, 48, errors);
  validateCanonicalStringsV2(value.evidenceRefs, 'result.evidenceRefs', 48, errors, SOURCE_REF_RE);
  if (!FRESHNESS_VALUES.has(value.freshness as DecisionFactFreshness)) errors.push('result.freshness: unknown');

  if (!hasExactKeys(value.identities, SDA_IDENTITIES_KEYS)) {
    errors.push('result.identities: keys must be exact');
  } else {
    const identities = value.identities;
    validateNullableId(identities.authorityPolicyId, 'result.identities.authorityPolicyId', errors);
    validateNullableSha(identities.authorityPolicySha256, 'result.identities.authorityPolicySha256', errors);
    if (!hasExactKeys(identities.marketTruth, SDA_MARKET_IDENTITY_KEYS)) {
      errors.push('result.identities.marketTruth: keys must be exact');
    } else {
      if (!REFERENCE_STATUSES.has(identities.marketTruth.status as ArtifactReferenceStatus)) {
        errors.push('result.identities.marketTruth.status: unknown');
      }
      validateNullableArtifact(identities.marketTruth.snapshotId, 'result.identities.marketTruth.snapshotId', errors);
      validateNullableArtifact(
        identities.marketTruth.observationId, 'result.identities.marketTruth.observationId', errors);
    }
    if (!hasExactKeys(identities.predictionLedger, SDA_PREDICTION_IDENTITY_KEYS)) {
      errors.push('result.identities.predictionLedger: keys must be exact');
    } else {
      if (!REFERENCE_STATUSES.has(identities.predictionLedger.status as ArtifactReferenceStatus)) {
        errors.push('result.identities.predictionLedger.status: unknown');
      }
      validateNullableArtifact(
        identities.predictionLedger.contextId, 'result.identities.predictionLedger.contextId', errors);
    }
    if (!hasExactKeys(identities.sho, SDA_SHO_IDENTITY_KEYS)) {
      errors.push('result.identities.sho: keys must be exact');
    } else {
      if (!REFERENCE_STATUSES.has(identities.sho.status as ArtifactReferenceStatus)) {
        errors.push('result.identities.sho.status: unknown');
      }
      validateNullableArtifact(identities.sho.artifactId, 'result.identities.sho.artifactId', errors);
    }
    if (!hasExactKeys(identities.risk, SDA_RISK_IDENTITY_KEYS)) {
      errors.push('result.identities.risk: keys must be exact');
    } else {
      if (!['READY', 'DATA_GATED'].includes(identities.risk.status as string)) {
        errors.push('result.identities.risk.status: unknown');
      }
      if (identities.risk.riskKernelId !== null
          && (typeof identities.risk.riskKernelId !== 'string'
            || !RISK_KERNEL_ID_RE.test(identities.risk.riskKernelId))) {
        errors.push('result.identities.risk.riskKernelId: malformed');
      }
    }
  }
  if (!hasExactKeys(value.sevenSign, SEVEN_RESULT_KEYS)) {
    errors.push('result.sevenSign: keys must be exact');
  } else {
    const seven = value.sevenSign;
    if (seven.schemaVersion !== SEVEN_SIGN_SCHEMA_VERSION) errors.push('result.sevenSign.schemaVersion: mismatch');
    if (!['PRODUCTION', 'SHADOW', 'DATA_GATED'].includes(seven.status as string)) {
      errors.push('result.sevenSign.status: unknown');
    }
    for (const field of ['candidateLevel', 'productionLevel'] as const) {
      const level = seven[field];
      if (level !== null && (!Number.isInteger(level) || (level as number) < 1 || (level as number) > 7)) {
        errors.push(`result.sevenSign.${field}: invalid`);
      }
    }
    if (seven.status !== 'PRODUCTION' && seven.productionLevel !== null) {
      errors.push('result.sevenSign.productionLevel: must be null outside PRODUCTION');
    }
    if (seven.status === 'PRODUCTION' && seven.productionLevel !== seven.candidateLevel) {
      errors.push('result.sevenSign.productionLevel: inconsistent');
    }
    const allowed: Record<PrimaryAction, number[]> = {
      BUY: [5, 6, 7], HOLD: [4], WAIT: [3, 4], REDUCE: [2], EXIT: [1],
    };
    if (PRIMARY_ACTIONS.includes(value.primaryAction as PrimaryAction)
        && seven.candidateLevel !== null
        && !allowed[value.primaryAction as PrimaryAction].includes(seven.candidateLevel as number)) {
      errors.push('result.sevenSign.candidateLevel: semantically inconsistent');
    }
    validateNullableId(seven.policyId, 'result.sevenSign.policyId', errors);
    validateNullableSha(seven.policySha256, 'result.sevenSign.policySha256', errors);
    validateNullableArtifact(
      seven.calibrationArtifactId, 'result.sevenSign.calibrationArtifactId', errors);
    validateCanonicalStringsV2(seven.reasonCodes, 'result.sevenSign.reasonCodes', 24, errors);
  }
  if (errors.length === 0
      && value.decisionId !== computeSingleDecisionId(value as unknown as SingleDecisionAuthorityResultV2)) {
    errors.push('result.decisionId: content address mismatch');
  }
  return { ok: errors.length === 0, errors: Object.freeze(errors) };
}

export interface DataGatedInputV2Options {
  subject: DecisionSubjectV2;
  decisionAt: string;
  informationCutoffAt: string;
  authorityPolicy?: ArtifactPolicyRef;
  ownerContext?: OwnerDecisionContext;
}

/** Minimum honest integration envelope while exact upstream artifacts are absent. */
export function buildDataGatedInputV2(options: DataGatedInputV2Options): SingleDecisionAuthorityInputV2 {
  const subjectErrors: string[] = [];
  validateDecisionSubjectV2(options.subject, 'subject', subjectErrors);
  const authorityPolicy = options.authorityPolicy ?? SINGLE_DECISION_AUTHORITY_V2_POLICY;
  validateV2Policy(authorityPolicy, 'authorityPolicy', subjectErrors);
  if (authorityPolicy.policyId !== SINGLE_DECISION_AUTHORITY_V2_POLICY.policyId
      || authorityPolicy.policySha256 !== SINGLE_DECISION_AUTHORITY_V2_POLICY.policySha256) {
    subjectErrors.push('authorityPolicy: must equal repository-pinned SDA v2 policy');
  }
  if (!isExactUtc(options.decisionAt)) subjectErrors.push('decisionAt: invalid');
  if (!isExactUtc(options.informationCutoffAt)) subjectErrors.push('informationCutoffAt: invalid');
  if (isExactUtc(options.decisionAt) && isExactUtc(options.informationCutoffAt)
      && Date.parse(options.informationCutoffAt) > Date.parse(options.decisionAt)) {
    subjectErrors.push('informationCutoffAt: later than decisionAt');
  }
  if (subjectErrors.length > 0) throw new TypeError(subjectErrors.join('; '));
  const ownerContext: OwnerDecisionContext = options.ownerContext ?? {
    schemaVersion: OWNER_DECISION_CONTEXT_SCHEMA_VERSION,
    privacyClass: 'DEVICE_LOCAL',
    asOf: options.decisionAt,
    positionState: 'UNKNOWN',
    positionRiskBand: 'UNKNOWN',
    concentrationBand: 'UNKNOWN',
    addPermission: 'UNKNOWN',
  };
  const riskKernel = buildRiskKernel({
    schemaVersion: RISK_DISCIPLINE_INPUT_SCHEMA_VERSION,
    subject: {
      kind: options.subject.kind,
      instrumentId: options.subject.instrumentId,
      market: options.subject.market,
    },
    asOf: options.decisionAt,
    informationCutoffAt: options.informationCutoffAt,
    policy: deepClone(authorityPolicy),
    contributions: [{
      evidenceRef: 'discipline:risk-missing',
      primitiveFactorId: 'risk.required_evidence',
      sourceKind: 'DISCIPLINE',
      constraint: 'NONE',
      status: 'MISSING',
      severity: 'UNKNOWN',
      confidenceCapBps: 2500,
      observedAt: options.informationCutoffAt,
    }],
  });
  const input: SingleDecisionAuthorityInputV2 = {
    schemaVersion: SINGLE_DECISION_AUTHORITY_INPUT_V2_SCHEMA_VERSION,
    subject: deepClone(options.subject),
    decisionAt: options.decisionAt,
    informationCutoffAt: options.informationCutoffAt,
    authorityPolicy: deepClone(authorityPolicy),
    marketTruth: {
      status: 'MISSING', schemaVersion: null, snapshotId: null, observationId: null,
      observedAt: null, knownAt: null, policyId: null, policySha256: null,
    },
    predictionLedger: {
      status: 'MISSING', schemaVersion: null, contextId: null, mode: null, asOf: null,
      policyId: null, policySha256: null,
    },
    sho: {
      status: 'MISSING', schemaVersion: null, artifactId: null, asOf: null,
      policyId: null, policySha256: null, state: null, validationStatus: null,
      primitiveFactorIds: [], targets: [], invalidation: null,
    },
    riskKernel,
    contextEvidence: [{
      evidenceRef: 'context:missing',
      primitiveFactorId: 'context.required_evidence',
      sourceKind: 'SCENARIO',
      constraint: 'NONE',
      status: 'MISSING',
      observedAt: options.informationCutoffAt,
    }],
    quality: {
      status: 'MISSING',
      freshness: 'UNKNOWN',
      missingReasonCodes: [
        'market_truth_missing', 'prediction_ledger_missing', 'risk_evidence_missing',
        'scenario_event_missing', 'sho_evidence_missing',
      ],
      conflictReasonCodes: [],
    },
    ownerContext: deepClone(ownerContext),
    challengeEvidence: [],
    sevenSignCalibration: {
      status: 'MISSING', artifactId: null, policyId: null, policySha256: null,
      expectancyBpsByLevel: null, sampleSizeByLevel: null,
      outOfSample: false, holdoutImmutable: false,
    },
  };
  return verifyDecisionEvidence(input);
}

export function computePredictionLedgerAdapterId(
  adapterOrBody: PredictionLedgerSdaAdapterV2 | Omit<PredictionLedgerSdaAdapterV2, 'adapterId'>,
): string {
  const { adapterId: _ignored, ...body } = adapterOrBody as PredictionLedgerSdaAdapterV2;
  return `pla-${sha256HexSync(stableJson(body as unknown as JsonValue))}`;
}

function predictionLedgerAdapterBody(
  result: SingleDecisionAuthorityResultV2,
): Omit<PredictionLedgerSdaAdapterV2, 'adapterId'> {
  if (result.verifiedEvidenceBundleId === null) {
    throw new TypeError('result: verified evidence bundle identity required');
  }
  return {
    schemaVersion: PREDICTION_LEDGER_SDA_ADAPTER_V2_SCHEMA_VERSION,
    recordType: 'canonical_decision_binding',
    appendMode: 'APPEND_ONLY',
    mutatesExistingRows: false,
    decisionId: result.decisionId,
    verifiedEvidenceBundleId: result.verifiedEvidenceBundleId,
    issuedAt: result.issuedAt,
    informationCutoffAt: result.informationCutoffAt,
    subject: deepClone(result.subject),
    authorityPolicyRef: {
      policyId: result.identities.authorityPolicyId,
      policySha256: result.identities.authorityPolicySha256,
    },
    marketTruthRef: deepClone(result.identities.marketTruth),
    predictionLedgerRef: deepClone(result.identities.predictionLedger),
    shoRef: deepClone(result.identities.sho),
    riskRef: deepClone(result.identities.risk),
    singleDecisionRef: {
      schemaVersion: result.schemaVersion,
      decisionId: result.decisionId,
    },
    sevenSignRef: {
      schemaVersion: result.sevenSign.schemaVersion,
      status: result.sevenSign.status,
      policyId: result.sevenSign.policyId,
      policySha256: result.sevenSign.policySha256,
      calibrationArtifactId: result.sevenSign.calibrationArtifactId,
      candidateLevel: result.sevenSign.candidateLevel,
      productionLevel: result.sevenSign.productionLevel,
    },
    primaryAction: result.primaryAction,
    confidenceBps: result.confidence.valueBps,
    targets: deepClone(result.targets),
    invalidation: deepClone(result.invalidation),
    missingReasonCodes: deepClone(result.missingReasonCodes),
    conflictReasonCodes: deepClone(result.conflictReasonCodes),
    dissentReasonCodes: deepClone(result.dissentReasonCodes),
    evidenceRefs: deepClone(result.evidenceRefs),
    primitiveFactorIds: deepClone(result.primitiveFactorIds),
  };
}

export function validatePredictionLedgerV2Adapter(
  value: unknown,
  result?: SingleDecisionAuthorityResultV2,
): ContractValidationResult {
  const errors: string[] = [];
  if (!hasExactKeys(value, SDA_ADAPTER_KEYS)) {
    return { ok: false, errors: Object.freeze(['adapter: keys must be exact']) };
  }
  if (value.schemaVersion !== PREDICTION_LEDGER_SDA_ADAPTER_V2_SCHEMA_VERSION
      || value.recordType !== 'canonical_decision_binding'
      || value.appendMode !== 'APPEND_ONLY' || value.mutatesExistingRows !== false) {
    errors.push('adapter: authority or append contract mismatch');
  }
  if (typeof value.adapterId !== 'string' || !ADAPTER_ID_RE.test(value.adapterId)
      || value.adapterId !== computePredictionLedgerAdapterId(
        value as unknown as PredictionLedgerSdaAdapterV2)) {
    errors.push('adapter.adapterId: content address mismatch');
  }
  if (typeof value.verifiedEvidenceBundleId !== 'string'
      || !VERIFIED_BUNDLE_ID_RE.test(value.verifiedEvidenceBundleId)) {
    errors.push('adapter.verifiedEvidenceBundleId: malformed');
  }
  if (result !== undefined) {
    const resultValidation = validateSingleDecisionAuthorityResultV2(result);
    if (!resultValidation.ok) errors.push(...resultValidation.errors.map((item) => `result: ${item}`));
    try {
      const expectedBody = predictionLedgerAdapterBody(result);
      const { adapterId: _ignored, ...actualBody } = value as unknown as PredictionLedgerSdaAdapterV2;
      if (stableJson(actualBody as unknown as JsonValue)
          !== stableJson(expectedBody as unknown as JsonValue)) {
        errors.push('adapter: does not bind the supplied SDA result');
      }
    } catch (error) {
      errors.push(`adapter: ${String(error)}`);
    }
  }
  return { ok: errors.length === 0, errors: Object.freeze(errors) };
}

/** Build one append-only binding row; no existing Prediction Ledger row is mutated. */
export function buildPredictionLedgerV2Adapter(
  result: SingleDecisionAuthorityResultV2,
): PredictionLedgerSdaAdapterV2 {
  const runtime = VERIFIED_DECISION_RESULTS.get(result);
  if (runtime == null
      || runtime.bundleId !== result.verifiedEvidenceBundleId
      || runtime.canonicalResult !== stableJson(result as unknown as JsonValue)) {
    throw new TypeError('result: must come from the verified SDA admission path');
  }
  const validation = validateSingleDecisionAuthorityResultV2(result);
  if (!validation.ok) throw new TypeError(validation.errors.join('; '));
  const body = predictionLedgerAdapterBody(result);
  return { adapterId: computePredictionLedgerAdapterId(body), ...body };
}
