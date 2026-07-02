import { useEffect, useState } from 'react';

// US whole-market movers (v10.62) — top gainers/losers beyond the watchlist,
// from Alpha Vantage (free, price-filtered). status=missing_key until the owner
// sets ALPHAVANTAGE_API_KEY on Render.
export interface MoverRow {
  symbol: string; price: number; changePct: number; name?: string;
  /** Mover Cause ladder chip (v11.3.3) — attached from the cause store when available. */
  cause?: { causeStatus?: string; causeStatusJa?: string; bestLeadJa?: string };
}
export interface MarketMovers {
  status: 'live' | 'missing_key' | 'unavailable' | 'warming';
  asOf: string | null;
  /** Effective data timestamp (fetch − delay) for delayed feeds (v10.190). */
  dataAsOf?: string | null;
  delayMin?: number;
  provider?: string;
  gainers: MoverRow[];
  losers: MoverRow[];
}

export function useMarketMovers(path = '/api/argus/market-movers') {
  const [data, setData] = useState<MarketMovers | null>(null);
  const backend = import.meta.env.VITE_ARGUS_BACKEND_URL;
  useEffect(() => {
    let alive = true;
    const base = backend?.replace(/\/$/, '');
    async function load() {
      if (!base) return;
      try {
        const d = await fetch(`${base}${path}`).then((r) => r.json());
        if (alive && Array.isArray(d?.gainers)) setData(d as MarketMovers);
      } catch { /* keep last */ }
    }
    load();
    const t = window.setInterval(load, 15 * 60 * 1000);
    return () => { alive = false; window.clearInterval(t); };
  }, [backend, path]);
  return data;
}
