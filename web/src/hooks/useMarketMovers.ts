import { useEffect, useState } from 'react';

// US whole-market movers (v10.62) — top gainers/losers beyond the watchlist,
// from Alpha Vantage (free, price-filtered). status=missing_key until the owner
// sets ALPHAVANTAGE_API_KEY on Render.
export interface MoverRow { symbol: string; price: number; changePct: number; }
export interface MarketMovers {
  status: 'live' | 'missing_key' | 'unavailable';
  asOf: string | null;
  gainers: MoverRow[];
  losers: MoverRow[];
}

export function useMarketMovers() {
  const [data, setData] = useState<MarketMovers | null>(null);
  const backend = import.meta.env.VITE_ARGUS_BACKEND_URL;
  useEffect(() => {
    let alive = true;
    const base = backend?.replace(/\/$/, '');
    async function load() {
      if (!base) return;
      try {
        const d = await fetch(`${base}/api/argus/market-movers`).then((r) => r.json());
        if (alive && Array.isArray(d?.gainers)) setData(d as MarketMovers);
      } catch { /* keep last */ }
    }
    load();
    const t = window.setInterval(load, 15 * 60 * 1000);
    return () => { alive = false; window.clearInterval(t); };
  }, [backend]);
  return data;
}
