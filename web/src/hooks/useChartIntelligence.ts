import { useEffect, useMemo, useState } from 'react';
import type { ChartIntelligencePayload } from '../types/chartIntelligence';

const cache = new Map<string, { at: number; data: ChartIntelligencePayload }>();
const inflight = new Map<string, Promise<ChartIntelligencePayload>>();
const failedUntil = new Map<string, number>();
const STALE_MS = 30 * 60 * 1000;

interface Options {
  scope: 'market' | 'asset'; symbol?: string; market?: string;
  timeframe?: 'daily' | 'weekly'; enabled?: boolean;
}

function endpoint(options: Options) {
  const base = (import.meta.env.VITE_ARGUS_BACKEND_URL as string | undefined)?.replace(/\/$/, '');
  if (!base) return null;
  const params = new URLSearchParams({ scope: options.scope, timeframe: options.timeframe ?? 'daily' });
  if (options.symbol) params.set('symbol', options.symbol);
  if (options.market) params.set('market', options.market);
  return `${base}/api/argus/chart-intelligence?${params}`;
}

async function load(url: string, force = false) {
  if (!force && (failedUntil.get(url) ?? 0) > Date.now()) throw new Error('再試行待機中');
  const current = cache.get(url);
  if (!force && current && Date.now() - current.at < STALE_MS) return current.data;
  const pending = inflight.get(url);
  if (pending) return pending;
  const request = fetch(url, { method: 'GET', headers: { Accept: 'application/json' } })
    .then(async (response) => {
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json() as ChartIntelligencePayload;
      cache.set(url, { at: Date.now(), data });
      return data;
    }).catch((error) => {
      failedUntil.set(url, Date.now() + 5 * 60 * 1000);
      throw error;
    }).finally(() => inflight.delete(url));
  inflight.set(url, request);
  return request;
}

export function useChartIntelligence(options: Options) {
  const url = useMemo(() => endpoint(options), [options.scope, options.symbol,
    options.market, options.timeframe]);
  const initial = url ? cache.get(url)?.data ?? null : null;
  const [data, setData] = useState<ChartIntelligencePayload | null>(initial);
  const [dataUrl, setDataUrl] = useState<string | null>(initial ? url : null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (!url || options.enabled === false) return;
    let cancelled = false;
    const run = () => {
      if (document.visibilityState === 'hidden') return;
      setLoading(true);
      void load(url).then((value) => {
        if (!cancelled) { setData(value); setDataUrl(url); setError(null); }
      })
        .catch((reason: unknown) => { if (!cancelled) setError(reason instanceof Error ? reason.message : '取得失敗'); })
        .finally(() => { if (!cancelled) setLoading(false); });
    };
    run();
    // Hidden pages do not poll or fetch.  A single stale check occurs when the
    // page becomes visible again; shared cache prevents duplicate consumers.
    const visible = () => { if (document.visibilityState === 'visible') run(); };
    document.addEventListener('visibilitychange', visible);
    return () => { cancelled = true; document.removeEventListener('visibilitychange', visible); };
  }, [url, options.enabled]);
  // A failed or pending instrument switch must never render the previous
  // instrument under the new heading. Keep the cache, but fail closed until
  // the payload resolved for the exact current URL.
  return { data: dataUrl === url ? data : null, loading, error };
}
