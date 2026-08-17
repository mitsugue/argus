import { useEffect, useState } from 'react';
import type { CostPolicyPayload, MarketLedgerPayload } from '../types/marketLedger';

type Snapshot = { ledger: MarketLedgerPayload | null; cost: CostPolicyPayload | null; loading: boolean; error: string | null };
let cache: Snapshot = { ledger: null, cost: null, loading: false, error: null };
let fetchedAt = 0;
let inFlight: Promise<Snapshot> | null = null;
const listeners = new Set<(s: Snapshot) => void>();
const STALE_MS = 15 * 60 * 1000;
const apiUrl = (path: string) => `${String(import.meta.env.VITE_ARGUS_BACKEND_URL ?? '').replace(/\/$/, '')}${path}`;

const publish = (next: Snapshot) => { cache = next; listeners.forEach((fn) => fn(cache)); };

export async function refreshMarketLedger(force = false): Promise<Snapshot> {
  if (!force && cache.ledger && Date.now() - fetchedAt < STALE_MS) return cache;
  if (inFlight) return inFlight;
  publish({ ...cache, loading: true, error: null });
  inFlight = Promise.all([
    fetch(apiUrl('/api/argus/market-ledger'), { cache: 'no-store' }),
    fetch(apiUrl('/api/argus/cost-policy'), { cache: 'no-store' }),
  ]).then(async ([lr, cr]) => {
    if (!lr.ok || !cr.ok) throw new Error(`HTTP ${lr.status}/${cr.status}`);
    const next = { ledger: await lr.json() as MarketLedgerPayload,
      cost: await cr.json() as CostPolicyPayload, loading: false, error: null };
    fetchedAt = Date.now(); publish(next); return next;
  }).catch((error: unknown) => {
    const next = { ...cache, loading: false, error: error instanceof Error ? error.message : 'fetch_failed' };
    publish(next); return next;
  }).finally(() => { inFlight = null; });
  return inFlight;
}

export function cachedMarketLedger(): MarketLedgerPayload | null { return cache.ledger; }

export function useMarketLedger(): Snapshot {
  const [snapshot, setSnapshot] = useState(cache);
  useEffect(() => {
    listeners.add(setSnapshot);
    const refresh = () => { if (!document.hidden) void refreshMarketLedger(); };
    refresh();
    const timer = window.setInterval(refresh, STALE_MS);
    document.addEventListener('visibilitychange', refresh);
    return () => { listeners.delete(setSnapshot); window.clearInterval(timer); document.removeEventListener('visibilitychange', refresh); };
  }, []);
  return snapshot;
}
