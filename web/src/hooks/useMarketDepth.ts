import { useEffect, useState } from 'react';

// Market Depth capability report (v10.196) — GET /api/argus/market-depth, 60s poll.
// Honest per-capability status; never claims a depth ARGUS hasn't proven.
export interface DepthCapability {
  status: 'live' | 'partial' | 'testing' | 'requires_contract' | 'unavailable';
  provider?: string;
  labelJa?: string;
  latency?: number | null;
  freshness?: string | null;
  coverage?: string | null;
  lastSuccess?: string | null;
  limitations?: string;
  affectsActionLevel?: boolean;
  probed?: boolean;                       // true = backed by a real measurement (実測)
  sample?: Record<string, number> | null; // e.g. VWAP values per symbol
}
export interface MarketDepth {
  asOf: string;
  engineVersion: string;
  capabilities: Record<string, DepthCapability>;
  summary?: { live?: number; total?: number; jpRealtimeProven?: boolean; sessionOpen?: boolean };
  note?: string;
}

export function useMarketDepth(): MarketDepth | null {
  const [data, setData] = useState<MarketDepth | null>(null);
  useEffect(() => {
    const backend = import.meta.env.VITE_ARGUS_BACKEND_URL as string | undefined;
    if (!backend) return;
    let alive = true;
    const url = backend.replace(/\/$/, '') + '/api/argus/market-depth';
    const load = () => fetch(url).then((r) => r.json())
      .then((d) => { if (alive && d && d.capabilities) setData(d as MarketDepth); })
      .catch(() => { /* keep last */ });
    load();
    const iv = setInterval(load, 60_000);
    return () => { alive = false; clearInterval(iv); };
  }, []);
  return data;
}
