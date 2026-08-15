// Round 2A — inactive DecisionEvidenceBundle -> Single Decision Authority contract.
//
// This module is intentionally isolated from hooks, routes, UI, storage, networking,
// recovery and scanner code.  It defines a closed evidence envelope and the future
// five-action vocabulary, but its only runtime authority result is INACTIVE/null.

export const DECISION_EVIDENCE_SCHEMA_VERSION = 'decision-evidence-bundle-v1' as const;
export const SINGLE_DECISION_AUTHORITY_SCHEMA_VERSION = 'single-decision-authority-v1' as const;
export const OWNER_DECISION_CONTEXT_SCHEMA_VERSION = 'owner-decision-context-v1' as const;

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

/** No input, flag, caller action or caller boolean can make this return authority. */
export function evaluateSingleDecisionAuthority(
  _input: SingleDecisionAuthorityInput,
): InactiveDecisionAuthorityResult {
  return INACTIVE_RESULT;
}

export const singleDecisionAuthority: SingleDecisionAuthority = Object.freeze({
  status: 'INACTIVE' as const,
  evaluate: evaluateSingleDecisionAuthority,
});
