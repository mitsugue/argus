import type { ChartIntelligencePayload } from '../types/chartIntelligence';

export const VERIFIED_SNAPSHOT_SCHEMA = 'argus-verified-view-snapshot-v1';
export const VERIFIED_VIEW_METHOD_VERSION =
  'verified-chart-view-v1:chart-intelligence-phase2-v1:market-context-replay-v2-standard-excursion';
const DB_NAME = 'argus-verified-snapshots';
const DB_VERSION = 1;
const SNAPSHOT_STORE = 'snapshots';
const DRAWING_STORE = 'drawing-state';
const MAX_SNAPSHOTS = 24;

export type SnapshotQuality = 'live' | 'partial' | 'stale';
export type SnapshotViewState =
  | 'NO_CACHE_LOADING'
  | 'CACHE_READY_REVALIDATING'
  | 'CURRENT_READY'
  | 'STALE_FALLBACK'
  | 'ERROR_WITH_CACHE'
  | 'ERROR_WITHOUT_CACHE';

export interface VerifiedSnapshot<T> {
  schemaVersion: string;
  snapshotId: string;
  kind: string;
  instrument: string;
  horizon: string;
  datasetHash: string;
  payloadHash: string;
  methodVersion: string;
  asOf: string;
  generatedAt: string;
  verifiedAt: string;
  quality: SnapshotQuality;
  sourceStatus: Record<string, string>;
  verificationStatus: 'verified';
  payload: T;
}

export interface SnapshotExpectation {
  kind: string;
  instrument: string;
  horizon: string;
  methodVersion: string;
}

interface SnapshotRecord {
  key: string;
  schemaVersion: string;
  verifiedAt: string;
  snapshot: VerifiedSnapshot<ChartIntelligencePayload>;
}

const qualityRank: Record<SnapshotQuality, number> = {
  stale: 0, partial: 1, live: 2,
};
const memory = new Map<string, VerifiedSnapshot<ChartIntelligencePayload>>();
let databasePromise: Promise<IDBDatabase | null> | null = null;

export function snapshotKey(expectation: Pick<SnapshotExpectation,
  'kind' | 'instrument' | 'horizon'>) {
  return `${expectation.kind.toLowerCase()}:${expectation.instrument.toUpperCase()}:` +
    expectation.horizon.toUpperCase();
}

function mark(name: string) {
  try { performance.mark(`argus-snapshot:${name}`); } catch { /* instrumentation only */ }
}

function sorted(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(sorted);
  if (value && typeof value === 'object') {
    return Object.fromEntries(Object.entries(value as Record<string, unknown>)
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([key, child]) => [key, sorted(child)]));
  }
  return value;
}

function canonical(value: unknown) {
  return JSON.stringify(sorted(value));
}

async function sha256(value: string) {
  const bytes = new TextEncoder().encode(value);
  const digest = await crypto.subtle.digest('SHA-256', bytes);
  return Array.from(new Uint8Array(digest))
    .map((byte) => byte.toString(16).padStart(2, '0')).join('');
}

export async function calculateSnapshotId(snapshot: Omit<
  VerifiedSnapshot<ChartIntelligencePayload>, 'snapshotId'> | VerifiedSnapshot<ChartIntelligencePayload>) {
  const value = snapshot as VerifiedSnapshot<ChartIntelligencePayload>;
  const identity = {
    schemaVersion: value.schemaVersion, kind: value.kind,
    instrument: value.instrument, horizon: value.horizon,
    datasetHash: value.datasetHash, payloadHash: value.payloadHash,
    methodVersion: value.methodVersion,
    asOf: value.asOf, generatedAt: value.generatedAt,
    verifiedAt: value.verifiedAt, quality: value.quality,
    sourceStatus: value.sourceStatus,
    verificationStatus: value.verificationStatus,
  };
  return `vs-${(await sha256(canonical(identity))).slice(0, 32)}`;
}

function portableNumber(value: unknown) {
  if (typeof value !== 'number' || !Number.isFinite(value)) return null;
  const text = value.toFixed(8).replace(/0+$/, '').replace(/\.$/, '');
  return text === '-0' || text === '' ? '0' : text;
}

export async function calculatePayloadHash(payload: ChartIntelligencePayload) {
  const material = (payload.indicators?.bars ?? []).map((bar) => ({
    date: String(bar.date ?? ''),
    open: portableNumber(bar.open), high: portableNumber(bar.high),
    low: portableNumber(bar.low), close: portableNumber(bar.close),
    volume: bar.volume == null ? null : portableNumber(bar.volume),
    availableFrom: String(bar.availableFrom ?? ''),
  }));
  return sha256(canonical(material));
}

function chartPayloadValid(payload: unknown, expectation: SnapshotExpectation,
                           datasetHash: string): boolean {
  if (!payload || typeof payload !== 'object') return false;
  const value = payload as ChartIntelligencePayload;
  const actual = value.instrumentMetadata?.symbol ?? value.symbol;
  if (actual?.toUpperCase() !== expectation.instrument.toUpperCase()) return false;
  if (/mock/i.test(value.status ?? '') || value.automaticAiCalls !== 0) return false;
  const bars = value.indicators?.bars;
  if (!Array.isArray(bars) || bars.length === 0) return false;
  let prior = '';
  const dates = new Set<string>();
  for (const bar of bars) {
    if (!bar || typeof bar.date !== 'string' || bar.date <= prior || dates.has(bar.date)) {
      return false;
    }
    if (![bar.open, bar.high, bar.low, bar.close].every(
      (number) => Number.isFinite(number) && number > 0)) return false;
    if (bar.high < Math.max(bar.open, bar.close) ||
        bar.low > Math.min(bar.open, bar.close)) return false;
    prior = bar.date; dates.add(bar.date);
  }
  const horizon = expectation.horizon.replace(/D$/i, '');
  const context = value.marketReplay?.contexts?.[horizon];
  return !!context && context.datasetHash === datasetHash;
}

export async function verifySnapshot(
  candidate: unknown, expectation: SnapshotExpectation, now = Date.now(),
): Promise<{ ok: true; snapshot: VerifiedSnapshot<ChartIntelligencePayload> } |
  { ok: false; reason: string }> {
  if (!candidate || typeof candidate !== 'object') return { ok: false, reason: 'malformed' };
  const value = candidate as Partial<VerifiedSnapshot<ChartIntelligencePayload>>;
  const required = ['schemaVersion', 'snapshotId', 'kind', 'instrument', 'horizon',
    'datasetHash', 'payloadHash', 'methodVersion', 'asOf', 'generatedAt', 'verifiedAt', 'quality',
    'sourceStatus', 'payload'] as const;
  if (required.some((key) => value[key] == null || value[key] === '')) {
    return { ok: false, reason: 'schema_missing_field' };
  }
  if (value.schemaVersion !== VERIFIED_SNAPSHOT_SCHEMA) {
    return { ok: false, reason: 'schema_incompatible' };
  }
  if (value.verificationStatus !== 'verified') {
    return { ok: false, reason: 'readback_unverified' };
  }
  if (value.kind?.toLowerCase() !== expectation.kind.toLowerCase()) {
    return { ok: false, reason: 'kind_mismatch' };
  }
  if (value.instrument?.toUpperCase() !== expectation.instrument.toUpperCase()) {
    return { ok: false, reason: 'instrument_mismatch' };
  }
  if (value.horizon?.toUpperCase() !== expectation.horizon.toUpperCase()) {
    return { ok: false, reason: 'horizon_mismatch' };
  }
  if (value.methodVersion !== expectation.methodVersion) {
    return { ok: false, reason: 'method_incompatible' };
  }
  if (!value.quality || !(value.quality in qualityRank) ||
      !value.sourceStatus || typeof value.sourceStatus !== 'object') {
    return { ok: false, reason: 'quality_or_source_invalid' };
  }
  if (Object.values(value.sourceStatus).some((status) => /mock/i.test(status))) {
    return { ok: false, reason: 'mock_source' };
  }
  const times = [value.asOf, value.generatedAt, value.verifiedAt]
    .map((item) => Date.parse(String(item)));
  if (times.some((time) => !Number.isFinite(time)) ||
      times.some((time) => time > now + 5 * 60_000)) {
    return { ok: false, reason: 'timestamp_invalid' };
  }
  if (!chartPayloadValid(value.payload, expectation, String(value.datasetHash))) {
    return { ok: false, reason: 'payload_invalid' };
  }
  const typed = value as VerifiedSnapshot<ChartIntelligencePayload>;
  if (await calculatePayloadHash(typed.payload) !== typed.payloadHash) {
    return { ok: false, reason: 'payload_hash_mismatch' };
  }
  if (await calculateSnapshotId(typed) !== typed.snapshotId) {
    return { ok: false, reason: 'snapshot_id_mismatch' };
  }
  return { ok: true, snapshot: typed };
}

export function shouldReplaceSnapshot(
  current: VerifiedSnapshot<ChartIntelligencePayload> | null,
  candidate: VerifiedSnapshot<ChartIntelligencePayload>,
) {
  if (!current) return true;
  if (current.snapshotId === candidate.snapshotId) return false;
  if (Date.parse(candidate.generatedAt) < Date.parse(current.generatedAt)) return false;
  return qualityRank[candidate.quality] >= qualityRank[current.quality];
}

function openDatabase(): Promise<IDBDatabase | null> {
  if (databasePromise) return databasePromise;
  databasePromise = new Promise((resolve) => {
    if (typeof indexedDB === 'undefined') { resolve(null); return; }
    let settled = false;
    try {
      const request = indexedDB.open(DB_NAME, DB_VERSION);
      request.onupgradeneeded = () => {
        const db = request.result;
        if (!db.objectStoreNames.contains(SNAPSHOT_STORE)) {
          db.createObjectStore(SNAPSHOT_STORE, { keyPath: 'key' });
        }
        if (!db.objectStoreNames.contains(DRAWING_STORE)) {
          db.createObjectStore(DRAWING_STORE, { keyPath: 'key' });
        }
      };
      request.onsuccess = () => {
        settled = true;
        request.result.onversionchange = () => request.result.close();
        resolve(request.result);
      };
      request.onerror = () => { settled = true; resolve(null); };
      request.onblocked = () => { if (!settled) resolve(null); };
    } catch { resolve(null); }
  });
  return databasePromise;
}

function requestValue<T>(request: IDBRequest<T>): Promise<T | null> {
  return new Promise((resolve) => {
    request.onsuccess = () => resolve(request.result ?? null);
    request.onerror = () => resolve(null);
  });
}

export function memorySnapshot(expectation: SnapshotExpectation) {
  return memory.get(snapshotKey(expectation)) ?? null;
}

export async function readVerifiedSnapshot(expectation: SnapshotExpectation) {
  mark('cache-lookup-start');
  const key = snapshotKey(expectation);
  const cached = memory.get(key);
  if (cached) { mark('cache-found-memory'); return cached; }
  const db = await openDatabase();
  if (!db) return null;
  try {
    const record = await requestValue(db.transaction(SNAPSHOT_STORE, 'readonly')
      .objectStore(SNAPSHOT_STORE).get(key)) as SnapshotRecord | null;
    const verified = await verifySnapshot(record?.snapshot, expectation);
    if (!verified.ok) {
      if (record) {
        try { db.transaction(SNAPSHOT_STORE, 'readwrite')
          .objectStore(SNAPSHOT_STORE).delete(key); } catch { /* best effort */ }
      }
      return null;
    }
    memory.set(key, verified.snapshot);
    mark('cache-found-indexeddb');
    return verified.snapshot;
  } catch { return null; }
}

async function collectGarbage(db: IDBDatabase) {
  try {
    const store = db.transaction(SNAPSHOT_STORE, 'readwrite').objectStore(SNAPSHOT_STORE);
    const records = await requestValue(store.getAll()) as SnapshotRecord[] | null;
    if (!records) return;
    const validSchema = records.filter((record) =>
      record.schemaVersion === VERIFIED_SNAPSHOT_SCHEMA)
      .sort((left, right) => right.verifiedAt.localeCompare(left.verifiedAt));
    const keep = new Set(validSchema.slice(0, MAX_SNAPSHOTS).map((record) => record.key));
    records.forEach((record) => {
      if (!keep.has(record.key)) store.delete(record.key);
    });
  } catch { /* capacity/transaction failure must not break memory cache */ }
}

export async function writeVerifiedSnapshot(
  candidate: unknown, expectation: SnapshotExpectation,
  current: VerifiedSnapshot<ChartIntelligencePayload> | null,
) {
  const verified = await verifySnapshot(candidate, expectation);
  if (!verified.ok || !shouldReplaceSnapshot(current, verified.snapshot)) {
    return current ?? (verified.ok ? verified.snapshot : null);
  }
  const key = snapshotKey(expectation);
  const db = await openDatabase();
  if (!db) {
    memory.set(key, verified.snapshot);
    return verified.snapshot;
  }
  try {
    const record: SnapshotRecord = {
      key, schemaVersion: VERIFIED_SNAPSHOT_SCHEMA,
      verifiedAt: verified.snapshot.verifiedAt, snapshot: verified.snapshot,
    };
    await new Promise<void>((resolve, reject) => {
      const transaction = db.transaction(SNAPSHOT_STORE, 'readwrite');
      transaction.objectStore(SNAPSHOT_STORE).put(record);
      transaction.oncomplete = () => resolve();
      transaction.onerror = () => reject(transaction.error);
      transaction.onabort = () => reject(transaction.error);
    });
    const readBack = await requestValue(db.transaction(SNAPSHOT_STORE, 'readonly')
      .objectStore(SNAPSHOT_STORE).get(key)) as SnapshotRecord | null;
    const readBackResult = await verifySnapshot(readBack?.snapshot, expectation);
    if (!readBackResult.ok ||
        readBackResult.snapshot.snapshotId !== verified.snapshot.snapshotId) {
      return current;
    }
    memory.set(key, readBackResult.snapshot);
    void collectGarbage(db);
    return readBackResult.snapshot;
  } catch {
    // IndexedDB was available but its write/read-back failed. Keep the last
    // verified pointer; only a genuinely unavailable database may use the
    // memory-only fallback above.
    return current;
  }
}

export async function readDrawingState<T>(key: string, fallback: T): Promise<T> {
  const db = await openDatabase();
  if (!db) return fallback;
  try {
    const record = await requestValue(db.transaction(DRAWING_STORE, 'readonly')
      .objectStore(DRAWING_STORE).get(key)) as { key: string; value: T } | null;
    return record?.value ?? fallback;
  } catch { return fallback; }
}

export async function writeDrawingState<T>(key: string, value: T) {
  const db = await openDatabase();
  if (!db) return false;
  try {
    await new Promise<void>((resolve, reject) => {
      const transaction = db.transaction(DRAWING_STORE, 'readwrite');
      transaction.objectStore(DRAWING_STORE).put({ key, value, schemaVersion: 1 });
      transaction.oncomplete = () => resolve();
      transaction.onerror = () => reject(transaction.error);
    });
    return true;
  } catch { return false; }
}

export function resetVerifiedSnapshotMemoryForTests() {
  memory.clear();
}
