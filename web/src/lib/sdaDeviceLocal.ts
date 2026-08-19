import {
  buildPredictionLedgerV2Adapter,
  validatePredictionLedgerV2Adapter,
  validateSingleDecisionAuthorityResultV2,
  type PredictionLedgerSdaAdapterV2,
  type SingleDecisionAuthorityResultV2,
} from '../domain/singleDecisionAuthority';

export const DEVICE_LOCAL_SDA_LEDGER_KEY = 'argus.sda.deviceLedger.v1';
export const DEVICE_LOCAL_SDA_LEDGER_SCHEMA_VERSION = 'argus-device-local-sda-ledger-v1';
export const DEVICE_LOCAL_SDA_ENTRY_SCHEMA_VERSION = 'argus-device-local-sda-entry-v1';
export const MAX_DEVICE_LOCAL_SDA_ENTRIES = 128;
export const MAX_DEVICE_LOCAL_SDA_LEDGER_BYTES = 1024 * 1024;

type OwnerRiskBand = 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL' | 'UNKNOWN';

export interface LocalOwnerRiskEvidence {
  positionState: 'HELD' | 'NOT_HELD' | 'UNKNOWN';
  flaggedPositionRisk: unknown;
  positionRiskKnown: boolean;
  concentrationWeightPct: number | null | undefined;
}

export interface LocalOwnerRiskBands {
  positionRiskBand: OwnerRiskBand;
  concentrationBand: OwnerRiskBand;
}

const normalizedBand = (value: unknown): OwnerRiskBand => {
  const upper = String(value ?? '').trim().toUpperCase();
  return ['LOW', 'MEDIUM', 'HIGH', 'CRITICAL'].includes(upper)
    ? upper as Exclude<OwnerRiskBand, 'UNKNOWN'> : 'UNKNOWN';
};

/** Derive only coarse owner bands; raw position values never cross this boundary. */
export function deriveLocalOwnerRiskBands(
  evidence: LocalOwnerRiskEvidence,
): LocalOwnerRiskBands {
  if (evidence.positionState === 'UNKNOWN') {
    return { positionRiskBand: 'UNKNOWN', concentrationBand: 'UNKNOWN' };
  }
  if (evidence.positionState === 'NOT_HELD') {
    return { positionRiskBand: 'LOW', concentrationBand: 'LOW' };
  }
  const flagged = normalizedBand(evidence.flaggedPositionRisk);
  const hasFlaggedEvidence = evidence.flaggedPositionRisk != null
    && String(evidence.flaggedPositionRisk).trim() !== '';
  const positionRiskBand = flagged !== 'UNKNOWN' ? flagged
    : !hasFlaggedEvidence && evidence.positionRiskKnown ? 'LOW' : 'UNKNOWN';
  const weight = evidence.concentrationWeightPct;
  const concentrationBand: OwnerRiskBand = typeof weight !== 'number'
    || !Number.isFinite(weight) || weight < 0 ? 'UNKNOWN'
    : weight >= 40 ? 'CRITICAL'
    : weight >= 25 ? 'HIGH'
    : weight >= 15 ? 'MEDIUM' : 'LOW';
  return { positionRiskBand, concentrationBand };
}

export interface DeviceLocalSdaLedgerEntry {
  schemaVersion: typeof DEVICE_LOCAL_SDA_ENTRY_SCHEMA_VERSION;
  privacyClass: 'DEVICE_LOCAL_DERIVED';
  adapterId: string;
  result: SingleDecisionAuthorityResultV2;
  adapter: PredictionLedgerSdaAdapterV2;
}

export interface DeviceLocalSdaLedgerDocument {
  schemaVersion: typeof DEVICE_LOCAL_SDA_LEDGER_SCHEMA_VERSION;
  privacyClass: 'DEVICE_LOCAL_DERIVED';
  appendMode: 'APPEND_ONLY';
  retention: 'BOUNDED_TAIL';
  entries: DeviceLocalSdaLedgerEntry[];
}

export interface DeviceLocalStorage {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
}

export interface DeviceLocalSdaLedgerRead {
  status: 'OK' | 'EMPTY' | 'CORRUPT' | 'STORAGE_UNAVAILABLE';
  entries: DeviceLocalSdaLedgerEntry[];
}

export interface DeviceLocalSdaLedgerAppend {
  status: 'APPENDED' | 'DUPLICATE' | 'INVALID_RECORD' | 'ENTRY_TOO_LARGE'
    | 'CORRUPT' | 'STORAGE_UNAVAILABLE';
  entryCount: number;
  evictedCount: number;
}

const DOCUMENT_KEYS = Object.freeze([
  'schemaVersion', 'privacyClass', 'appendMode', 'retention', 'entries',
]);
const ENTRY_KEYS = Object.freeze([
  'schemaVersion', 'privacyClass', 'adapterId', 'result', 'adapter',
]);
const FORBIDDEN_PRIVATE_KEYS = new Set([
  'quantity', 'avgcost', 'averagecost', 'costbasis', 'positionvalue',
  'pnl', 'pnlpct', 'pl', 'plpct', 'ownercontext', 'rawownercontext',
  'positionstate', 'positionriskband', 'concentrationband', 'addpermission',
  'rawportfolio', 'rawposition', 'privateraw',
]);

const isRecord = (value: unknown): value is Record<string, unknown> =>
  value !== null && typeof value === 'object' && !Array.isArray(value);

const hasExactKeys = (value: unknown, keys: readonly string[]): value is Record<string, unknown> =>
  isRecord(value) && Object.keys(value).sort().join('\u0000') === [...keys].sort().join('\u0000');

const containsPrivateRawField = (value: unknown): boolean => {
  if (Array.isArray(value)) return value.some(containsPrivateRawField);
  if (!isRecord(value)) return false;
  return Object.entries(value).some(([key, child]) => {
    const normalized = key.replace(/[_-]/g, '').toLowerCase();
    return FORBIDDEN_PRIVATE_KEYS.has(normalized) || normalized.startsWith('raw')
      || containsPrivateRawField(child);
  });
};

const canonicalJson = (value: unknown): string => {
  if (value === null || typeof value === 'boolean' || typeof value === 'string') {
    return JSON.stringify(value);
  }
  if (typeof value === 'number') {
    if (!Number.isFinite(value)) throw new TypeError('non_finite_number');
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(',')}]`;
  if (!isRecord(value)) throw new TypeError('non_json_value');
  return `{${Object.keys(value).sort().map((key) =>
    `${JSON.stringify(key)}:${canonicalJson(value[key])}`).join(',')}}`;
};

const byteLength = (value: string): number => new TextEncoder().encode(value).byteLength;

const clone = <T>(value: T): T => JSON.parse(JSON.stringify(value)) as T;

const defaultStorage = (): DeviceLocalStorage | null => {
  try {
    return typeof globalThis.localStorage === 'undefined' ? null : globalThis.localStorage;
  } catch {
    return null;
  }
};

const emptyDocument = (): DeviceLocalSdaLedgerDocument => ({
  schemaVersion: DEVICE_LOCAL_SDA_LEDGER_SCHEMA_VERSION,
  privacyClass: 'DEVICE_LOCAL_DERIVED',
  appendMode: 'APPEND_ONLY',
  retention: 'BOUNDED_TAIL',
  entries: [],
});

const buildEntry = (
  result: SingleDecisionAuthorityResultV2,
  adapter: PredictionLedgerSdaAdapterV2,
): DeviceLocalSdaLedgerEntry | null => {
  try {
    if (!validateSingleDecisionAuthorityResultV2(result).ok
      || containsPrivateRawField(result) || containsPrivateRawField(adapter)) return null;
    const expectedAdapter = buildPredictionLedgerV2Adapter(result);
    if (canonicalJson(adapter) !== canonicalJson(expectedAdapter)) return null;
    return {
      schemaVersion: DEVICE_LOCAL_SDA_ENTRY_SCHEMA_VERSION,
      privacyClass: 'DEVICE_LOCAL_DERIVED',
      adapterId: expectedAdapter.adapterId,
      result: clone(result),
      adapter: clone(expectedAdapter),
    };
  } catch {
    return null;
  }
};

export function verifyDeviceLocalSdaLedgerEntry(value: unknown): value is DeviceLocalSdaLedgerEntry {
  if (!hasExactKeys(value, ENTRY_KEYS)
    || value.schemaVersion !== DEVICE_LOCAL_SDA_ENTRY_SCHEMA_VERSION
    || value.privacyClass !== 'DEVICE_LOCAL_DERIVED'
    || typeof value.adapterId !== 'string'
    || !isRecord(value.result) || !isRecord(value.adapter)
    || containsPrivateRawField(value)) return false;
  const result = value.result as unknown as SingleDecisionAuthorityResultV2;
  const adapter = value.adapter as unknown as PredictionLedgerSdaAdapterV2;
  return validateSingleDecisionAuthorityResultV2(result).ok
    && validatePredictionLedgerV2Adapter(adapter, result).ok
    && adapter.adapterId === value.adapterId;
}

export function verifyDeviceLocalSdaLedgerDocument(
  value: unknown,
): value is DeviceLocalSdaLedgerDocument {
  if (!hasExactKeys(value, DOCUMENT_KEYS)
    || value.schemaVersion !== DEVICE_LOCAL_SDA_LEDGER_SCHEMA_VERSION
    || value.privacyClass !== 'DEVICE_LOCAL_DERIVED'
    || value.appendMode !== 'APPEND_ONLY' || value.retention !== 'BOUNDED_TAIL'
    || !Array.isArray(value.entries)
    || value.entries.length > MAX_DEVICE_LOCAL_SDA_ENTRIES) return false;
  const ids = new Set<string>();
  for (const entry of value.entries) {
    if (!verifyDeviceLocalSdaLedgerEntry(entry) || ids.has(entry.adapterId)) return false;
    ids.add(entry.adapterId);
  }
  try {
    return byteLength(canonicalJson(value)) <= MAX_DEVICE_LOCAL_SDA_LEDGER_BYTES;
  } catch {
    return false;
  }
}

// Bytes already fully verified this session (or produced by this module after
// verification) are not cryptographically re-verified. Any byte difference —
// including external writes to storage — misses this cache and takes the full
// verification path, so nothing is ever trusted without having been verified
// against those exact bytes.
const verifiedByStorage = new WeakMap<DeviceLocalStorage, {
  raw: string;
  document: DeviceLocalSdaLedgerDocument;
}>();

const loadDocument = (storage: DeviceLocalStorage): {
  status: DeviceLocalSdaLedgerRead['status'];
  document: DeviceLocalSdaLedgerDocument | null;
} => {
  let raw: string | null;
  try {
    raw = storage.getItem(DEVICE_LOCAL_SDA_LEDGER_KEY);
  } catch {
    return { status: 'STORAGE_UNAVAILABLE', document: null };
  }
  if (raw == null) return { status: 'EMPTY', document: emptyDocument() };
  const verified = verifiedByStorage.get(storage);
  if (verified && verified.raw === raw) return { status: 'OK', document: verified.document };
  if (byteLength(raw) > MAX_DEVICE_LOCAL_SDA_LEDGER_BYTES) {
    return { status: 'CORRUPT', document: null };
  }
  try {
    const parsed = JSON.parse(raw) as unknown;
    if (!verifyDeviceLocalSdaLedgerDocument(parsed)) {
      return { status: 'CORRUPT', document: null };
    }
    verifiedByStorage.set(storage, { raw, document: parsed });
    return { status: 'OK', document: parsed };
  } catch {
    return { status: 'CORRUPT', document: null };
  }
};

export function readDeviceLocalSdaLedger(
  storage: DeviceLocalStorage | null = defaultStorage(),
): DeviceLocalSdaLedgerRead {
  if (storage == null) return { status: 'STORAGE_UNAVAILABLE', entries: [] };
  const loaded = loadDocument(storage);
  return {
    status: loaded.status,
    entries: loaded.document == null ? [] : clone(loaded.document.entries),
  };
}

export function appendDeviceLocalSdaLedger(
  result: SingleDecisionAuthorityResultV2,
  adapter: PredictionLedgerSdaAdapterV2,
  storage: DeviceLocalStorage | null = defaultStorage(),
): DeviceLocalSdaLedgerAppend {
  const entry = buildEntry(result, adapter);
  if (entry == null) return { status: 'INVALID_RECORD', entryCount: 0, evictedCount: 0 };
  if (storage == null) return { status: 'STORAGE_UNAVAILABLE', entryCount: 0, evictedCount: 0 };
  const loaded = loadDocument(storage);
  if (loaded.status === 'STORAGE_UNAVAILABLE') {
    return { status: 'STORAGE_UNAVAILABLE', entryCount: 0, evictedCount: 0 };
  }
  if (loaded.status === 'CORRUPT' || loaded.document == null) {
    return { status: 'CORRUPT', entryCount: 0, evictedCount: 0 };
  }
  const prior = loaded.document.entries.find((row) => row.adapterId === entry.adapterId);
  if (prior) {
    return canonicalJson(prior) === canonicalJson(entry)
      ? { status: 'DUPLICATE', entryCount: loaded.document.entries.length, evictedCount: 0 }
      : { status: 'CORRUPT', entryCount: loaded.document.entries.length, evictedCount: 0 };
  }
  const entries = [...loaded.document.entries, entry];
  let evictedCount = 0;
  while (entries.length > MAX_DEVICE_LOCAL_SDA_ENTRIES) {
    entries.shift();
    evictedCount += 1;
  }
  let next = { ...emptyDocument(), entries };
  let encoded = canonicalJson(next);
  while (byteLength(encoded) > MAX_DEVICE_LOCAL_SDA_LEDGER_BYTES && entries.length > 1) {
    entries.shift();
    evictedCount += 1;
    next = { ...emptyDocument(), entries };
    encoded = canonicalJson(next);
  }
  if (byteLength(encoded) > MAX_DEVICE_LOCAL_SDA_LEDGER_BYTES) {
    return { status: 'ENTRY_TOO_LARGE', entryCount: loaded.document.entries.length, evictedCount: 0 };
  }
  try {
    storage.setItem(DEVICE_LOCAL_SDA_LEDGER_KEY, encoded);
  } catch {
    return {
      status: 'STORAGE_UNAVAILABLE',
      entryCount: loaded.document.entries.length,
      evictedCount: 0,
    };
  }
  verifiedByStorage.set(storage, { raw: encoded, document: next });
  return { status: 'APPENDED', entryCount: entries.length, evictedCount };
}
