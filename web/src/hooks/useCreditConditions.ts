import { useSyncExternalStore } from 'react';
import { createSharedPollingStore } from '../lib/sharedPollingStore';
import { scheduleVisibleInterval, subscribeInitialVisibleRead } from '../lib/pollingPolicy';

type Document = Record<string, unknown>;
type State = { document: Document | null; readFailed: boolean; denied: boolean };
const object = (value: unknown): value is Document => !!value && typeof value === 'object' && !Array.isArray(value);
export function validCreditConditions(value: unknown): value is Document {
  return object(value) && value.schemaVersion === 'credit-conditions-v1' && value.actionAuthority === false
    && typeof value.snapshotId === 'string' && /^[a-f0-9]{64}$/.test(value.snapshotId)
    && object(value.dimensions) && Array.isArray(value.evidence) && value.evidence.length <= 512 && value.evidence.every(object)
    && Array.isArray(value.sourceHealth) && value.sourceHealth.length <= 10 && value.sourceHealth.every(object);
}
let nextReadAt = 0;
// All consumers share one small, memory-only official-data projection. Navigation
// does not start collection or AI, and does not restart a fresh read every time.
export const creditConditionsStore = createSharedPollingStore<State>({ document: null, readFailed: false, denied: false }, (set, get) => {
  let stopped = false; let flight: AbortController | null = null;
  const base = (import.meta.env.VITE_ARGUS_BACKEND_URL as string | undefined)?.replace(/\/$/, '');
  const load = async () => {
    if (stopped || flight || document.visibilityState !== 'visible' || Date.now() < nextReadAt) return;
    const controller = new AbortController(); flight = controller;
    const timeout = window.setTimeout(() => controller.abort(), 12_000);
    try {
      if (!base) throw new Error('backend_missing');
      const response = await fetch(base + '/api/argus/credit-conditions', { cache: 'no-store', signal: controller.signal, headers: { Accept: 'application/json' } });
      if (response.status === 401 || response.status === 403) {
        if (!stopped) set({ document: null, readFailed: true, denied: true });
        return;
      }
      if (!response.ok) throw new Error('credit_read_failed');
      const value: unknown = await response.json();
      if (!validCreditConditions(value)) throw new Error('credit_read_invalid');
      const evidenceIds = new Set(Object.values(value.dimensions as Document).flatMap(row => object(row) && Array.isArray(row.evidenceIds) ? row.evidenceIds : []));
      const saved = { ...value, evidence: (value.evidence as Document[]).filter(row => evidenceIds.has(row.observationId) || row.metric === 'published_analysis').slice(0, 12),
        collectionStatus: object(value.worker) && value.worker.status === 'FAILED' ? 'FAILED' : undefined };
      if (!stopped) set({ document: saved, readFailed: false, denied: false });
    } catch { if (!stopped) set({ ...get(), readFailed: true }); }
    finally {
      window.clearTimeout(timeout); flight = null;
      if (!stopped) nextReadAt = Date.now() + (get().readFailed ? 60_000 : 5 * 60_000);
    }
  };
  const visible = () => { void load(); };
  const stopInterval = scheduleVisibleInterval(visible, 60_000);
  const stopVisible = subscribeInitialVisibleRead(visible); void load();
  return () => { stopped = true; flight?.abort(); stopInterval(); stopVisible(); };
});
export function useCreditConditions() {
  return useSyncExternalStore(creditConditionsStore.subscribe, creditConditionsStore.getSnapshot, creditConditionsStore.getSnapshot);
}
