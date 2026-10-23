import { scheduleVisibleInterval, subscribeInitialVisibleRead } from '../lib/pollingPolicy';
import { useEffect, useSyncExternalStore } from 'react';
import { sessionViewCheckpoint } from '../lib/sessionViewCheckpoint';

// FUTURE MAP (2026-10-04): external views written by the research side to the
// private store; the server validates them. The table changes without a
// restart: it is read on initial display and every five minutes while in
// front. An app switch retains the table without an extra read; hidden initial
// reads resume once. The table is replaced only when its version changed.
export type FutureMapRow = { id: string; periodLabel: string; start: string; end: string; view: string;
  reason: string | null; alt: string | null; level: { low: number; high: number } | null; tag: string;
  tone: 'red' | 'amber' | 'green' | 'grey'; agree: number; emphasis: boolean; changed: boolean;
  result: 'reached' | 'missed' | null; scoringStatus?: string; isNow: boolean; past: boolean;
  long?: boolean };
export type FutureMapDoc = {
  schemaVersion: 'argus-future-map-public-v1'; updatedAt: string; lastChangedAt?: string | null; today: string;
  rows: FutureMapRow[];
  /** 2026-10-23: the server picks the first rows and the long views; the card only lays them out. */
  leadIds?: string[]; outlookIds?: string[];
  status: { position: string; nextAlert: { date: string; label: string }; nextBottom: { date: string; label: string } };
  record: { scored: number; reached: number }; argusValidated: false; actionAuthority: false;
  scoring?: { resultVersion: string; status: string; lastError: string | null };
};

export function validFutureMap(value: unknown): value is FutureMapDoc {
  const v = value as FutureMapDoc;
  return !!v && v.schemaVersion === 'argus-future-map-public-v1' && v.actionAuthority === false && v.argusValidated === false
    && !!v.status && typeof v.status.position === 'string' && Array.isArray(v.rows)
    && v.rows.every(r => typeof r.id === 'string' && typeof r.view === 'string' && typeof r.tag === 'string');
}

export const FUTURE_MAP_POLL_MS = 5 * 60_000;

/** A new table only when the server's version (updatedAt or lastChangedAt), its day or its first rows changed. */
export function futureMapChanged(previous: FutureMapDoc | null, next: FutureMapDoc): boolean {
  return !previous || previous.updatedAt !== next.updatedAt
    || (previous.lastChangedAt ?? null) !== (next.lastChangedAt ?? null) || previous.today !== next.today
    || previous.scoring?.resultVersion !== next.scoring?.resultVersion
    || String(previous.leadIds) !== String(next.leadIds) || String(previous.outlookIds) !== String(next.outlookIds);
}

let current: FutureMapDoc | null = null;
/** For the loading console: 'loading' until the first read settles. */
export type FutureMapLoad = 'loading' | 'ready' | 'unavailable';
let load: FutureMapLoad = 'loading';
let flight: Promise<void> | null = null;
const listeners = new Set<() => void>();
const emit = () => {
  if (load !== 'loading' && sessionViewCheckpoint.keep('future-map', { current, load }))
    void sessionViewCheckpoint.flush();
  listeners.forEach(listener => listener());
};
sessionViewCheckpoint.bind('future-map', value => {
  const row = value as { current?: unknown; load?: unknown };
  if (!row || !['ready', 'unavailable'].includes(String(row.load))
    || !(row.current === null || validFutureMap(row.current))) return;
  current = row.current as FutureMapDoc | null; load = row.load as FutureMapLoad;
  listeners.forEach(listener => listener());
});

/** Read the table once; keep the last one when the read fails. */
export function refreshFutureMap(): Promise<void> {
  if (document.visibilityState !== 'visible') return Promise.resolve();
  const base = (import.meta.env.VITE_ARGUS_BACKEND_URL as string | undefined)?.replace(/\/$/, '') ?? '';
  if (!base) {                                                 // never leave the console waiting
    if (load === 'loading') { load = 'unavailable'; emit(); }
    return Promise.resolve();
  }
  if (flight) return flight;
  flight = fetch(`${base}/api/argus/future-map`, { cache: 'no-store' })
    .then(r => (r.ok ? r.json() : null))
    .then(body => {
      const valid = !!body && body.availability === 'AVAILABLE' && validFutureMap(body);
      const nextLoad: FutureMapLoad = valid || current ? 'ready' : 'unavailable';
      const changed = valid && futureMapChanged(current, body);
      if (changed) current = body;
      if (changed || nextLoad !== load) { load = nextLoad; emit(); }
    })
    .catch(() => {                                              // the last table stays
      const nextLoad: FutureMapLoad = current ? 'ready' : 'unavailable';
      if (nextLoad !== load) { load = nextLoad; emit(); }
    })
    .finally(() => { flight = null; });
  return flight;
}

let stopSync: (() => void) | null = null;
function startSync(): () => void {
  const visible = () => document.visibilityState === 'visible';
  const onVisibility = () => { if (visible()) void refreshFutureMap(); };
  const timer = scheduleVisibleInterval(() => { if (visible()) void refreshFutureMap(); }, FUTURE_MAP_POLL_MS);
  const stopInitialOnVisibility = subscribeInitialVisibleRead(onVisibility, sessionViewCheckpoint.hasRestored('future-map'));
  return () => { timer(); stopInitialOnVisibility(); };
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  if (!stopSync) stopSync = startSync();
  return () => {
    listeners.delete(listener);
    if (!listeners.size && stopSync) { stopSync(); stopSync = null; }
  };
}

export function useFutureMapLoad(): FutureMapLoad {
  const value = useSyncExternalStore(subscribe, () => load, () => load);
  useEffect(() => { if (!sessionViewCheckpoint.hasRestored('future-map')) void refreshFutureMap(); }, []);
  return value;
}

export function useFutureMap(): FutureMapDoc | null {
  const doc = useSyncExternalStore(subscribe, () => current, () => current);
  useEffect(() => { if (!sessionViewCheckpoint.hasRestored('future-map')) void refreshFutureMap(); }, []);
  return doc;
}

/** Test seam: forget the table and stop the shared sync. */
export function resetFutureMapForTest(): void {
  current = null; load = 'loading'; flight = null; listeners.clear();
  if (stopSync) { stopSync(); stopSync = null; }
}

export const futureMapSubscribeForTest = subscribe;
