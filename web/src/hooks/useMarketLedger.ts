import { useSyncExternalStore } from 'react';
import { createSharedPollingStore } from '../lib/sharedPollingStore';
import type { CostPolicyPayload, MarketLedgerPayload } from '../types/marketLedger';

export type MarketLedgerSnapshot = {
  ledger: MarketLedgerPayload | null; cost: CostPolicyPayload | null;
  loading: boolean; error: string | null;
  fetchedAtMs: number | null; sessionExpired: boolean;
};
let cache: MarketLedgerSnapshot = {
  ledger: null, cost: null, loading: false, error: null,
  fetchedAtMs: null, sessionExpired: true,
};
let inFlight: Promise<MarketLedgerSnapshot> | null = null;
const STALE_MS = 15 * 60 * 1000;
const SESSION_SNAPSHOT_MAX_AGE_MS = 20 * 60 * 1000;
let sessionExpiryTimer: number | null = null;
const apiUrl = (path: string) => `${String(import.meta.env.VITE_ARGUS_BACKEND_URL ?? '').replace(/\/$/, '')}${path}`;

const marketLedgerStore = createSharedPollingStore<MarketLedgerSnapshot>(cache, () => {
  const refresh = () => { if (!document.hidden) void refreshMarketLedger(); };
  scheduleSessionExpiry(cache);
  refresh();
  const timer = window.setInterval(refresh, STALE_MS);
  document.addEventListener('visibilitychange', refresh);
  return () => {
    window.clearInterval(timer);
    if (sessionExpiryTimer != null) window.clearTimeout(sessionExpiryTimer);
    sessionExpiryTimer = null;
    document.removeEventListener('visibilitychange', refresh);
  };
});

const publish = (next: MarketLedgerSnapshot) => {
  cache = next;
  marketLedgerStore.setSnapshot(next);
};

function earliestSessionExpiry(
  ledger: MarketLedgerPayload | null,
  fetchedAtMs: number | null,
): number | null {
  const calendar = ledger?.phase3?.calendar;
  const sessionExpiries = ['JP', 'US'].map((market) => Date.parse(
    calendar?.[market]?.sessionValidUntil ?? '')).filter(Number.isFinite);
  const serverAsOfMs = Date.parse(ledger?.phase3?.asOf ?? ledger?.asOf ?? '');
  if (!sessionExpiries.length || !Number.isFinite(serverAsOfMs)
      || fetchedAtMs == null || !Number.isFinite(fetchedAtMs)) return null;
  return Math.min(...sessionExpiries,
    serverAsOfMs + SESSION_SNAPSHOT_MAX_AGE_MS,
    fetchedAtMs + SESSION_SNAPSHOT_MAX_AGE_MS);
}

function scheduleSessionExpiry(snapshot: MarketLedgerSnapshot): void {
  if (sessionExpiryTimer != null) window.clearTimeout(sessionExpiryTimer);
  sessionExpiryTimer = null;
  const expiresAt = earliestSessionExpiry(snapshot.ledger, snapshot.fetchedAtMs);
  if (expiresAt == null || expiresAt <= Date.now()) return;
  sessionExpiryTimer = window.setTimeout(() => {
    sessionExpiryTimer = null;
    if (cache.ledger !== snapshot.ledger) return;
    publish({ ...cache, sessionExpired: true });
    if (!document.hidden) void refreshMarketLedger(true);
  }, Math.min(expiresAt - Date.now() + 10, 2_147_000_000));
}

export async function refreshMarketLedger(force = false): Promise<MarketLedgerSnapshot> {
  if (!force && cache.ledger && !cache.sessionExpired && cache.fetchedAtMs != null
      && Date.now() - cache.fetchedAtMs < STALE_MS) {
    // A prior last-subscriber cleanup cancels the timer. Re-arm it on every
    // cache hit so unmount/remount cannot retain MORNING/REGULAR past expiry.
    scheduleSessionExpiry(cache);
    return cache;
  }
  if (inFlight) return inFlight;
  publish({ ...cache, loading: true, error: null });
  inFlight = Promise.all([
    fetch(apiUrl('/api/argus/market-ledger'), { cache: 'no-store' }),
    fetch(apiUrl('/api/argus/cost-policy'), { cache: 'no-store' }),
  ]).then(async ([lr, cr]) => {
    if (!lr.ok || !cr.ok) throw new Error(`HTTP ${lr.status}/${cr.status}`);
    const ledger = await lr.json() as MarketLedgerPayload;
    const receivedAtMs = Date.now();
    const expiresAt = earliestSessionExpiry(ledger, receivedAtMs);
    const next: MarketLedgerSnapshot = {
      ledger, cost: await cr.json() as CostPolicyPayload,
      loading: false, error: null, fetchedAtMs: receivedAtMs,
      sessionExpired: expiresAt == null || expiresAt <= receivedAtMs,
    };
    publish(next); scheduleSessionExpiry(next); return next;
  }).catch((error: unknown) => {
    if (sessionExpiryTimer != null) window.clearTimeout(sessionExpiryTimer);
    sessionExpiryTimer = null;
    const next = { ...cache, loading: false, sessionExpired: true,
      error: error instanceof Error ? error.message : 'fetch_failed' };
    publish(next); return next;
  }).finally(() => { inFlight = null; });
  return inFlight;
}

export function cachedMarketLedger(): MarketLedgerPayload | null { return cache.ledger; }

export function useMarketLedger(): MarketLedgerSnapshot {
  return useSyncExternalStore(
    marketLedgerStore.subscribe,
    marketLedgerStore.getSnapshot,
    marketLedgerStore.getSnapshot,
  );
}
