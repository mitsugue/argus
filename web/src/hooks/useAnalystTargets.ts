import { useEffect, useState } from 'react';

// Analyst consensus target prices of watched stocks (owner 2026-10-04): the
// server fetches once a day; this reads the stored values once per page view.
export type AnalystTarget = { symbol: string; market: 'JP' | 'US'; mean: number; median: number | null;
  high: number | null; low: number | null; analysts: number; currency: string | null;
  priceAtFetch: number | null; gapPct: number | null; fetchedAt: string; source: string };
type Store = Record<string, AnalystTarget>;
let cache: { at: number; items: Store } | null = null;
let flight: Promise<Store> | null = null;
const TTL_MS = 30 * 60_000;

const valid = (row: unknown): row is AnalystTarget => {
  const r = row as AnalystTarget;
  return !!r && typeof r.symbol === 'string' && typeof r.mean === 'number' && Number.isFinite(r.mean)
    && typeof r.analysts === 'number' && typeof r.fetchedAt === 'string';
};

async function load(base: string): Promise<Store> {
  const response = await fetch(`${base}/api/argus/analyst-targets`, { cache: 'no-store' });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  const body = await response.json();
  if (body?.actionAuthority !== false || typeof body.items !== 'object' || !body.items) return {};
  return Object.fromEntries(Object.entries(body.items as Record<string, unknown>).filter(([, row]) => valid(row))) as Store;
}

export function useAnalystTargets(): Store {
  const base = (import.meta.env.VITE_ARGUS_BACKEND_URL as string | undefined)?.replace(/\/$/, '') ?? '';
  const [items, setItems] = useState<Store>(cache?.items ?? {});
  useEffect(() => {
    if (!base || (cache && Date.now() - cache.at < TTL_MS)) return;
    let live = true;
    flight ??= load(base).then(found => { cache = { at: Date.now(), items: found }; return found; })
      .finally(() => { flight = null; });
    flight.then(found => { if (live) setItems(found); }).catch(() => { /* the row simply stays absent */ });
    return () => { live = false; };
  }, [base]);
  return items;
}
