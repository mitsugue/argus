import { useEffect, useState } from 'react';

// Market News feed (news-v2, v10.12) — Finnhub general headlines with
// market-moving keywords flagged. Refreshes every 5 min while visible
// (server caches 10 min, so this stays well inside the free tier).

export interface MarketNewsItem {
  headline: string;
  /** Auto-translated headline (Gemini flash, v10.14) — absent on failure. */
  headlineJa?: string;
  source: string;
  url: string;
  datetime: number | null;   // unix seconds
  major: boolean;
  /** market/finance-relevant (v10.169) — noise (sports/unrelated) is false. */
  relevant?: boolean;
  /** source-trust tier (v10.169). */
  tier?: 'wire' | 'aggregator' | 'official';
  /** corroboration level (v10.170): official | corroborated (>=2 indep families) | single. */
  corroboration?: 'official' | 'corroborated' | 'single';
}

export interface MarketNews {
  status: 'live' | 'unavailable' | 'missing_key';
  asOf: string;
  items: MarketNewsItem[];
  noteJa: string;
}

const REFRESH_INTERVAL_MS = 5 * 60_000;

interface State {
  data: MarketNews | null;
  loading: boolean;
}

export function useMarketNews(): State {
  const [state, setState] = useState<State>({ data: null, loading: true });

  useEffect(() => {
    const backend = import.meta.env.VITE_ARGUS_BACKEND_URL;
    if (!backend) {
      setState({ data: null, loading: false });
      return;
    }
    const url = backend.replace(/\/$/, '') + '/api/argus/market-news';
    let cancelled = false;

    async function fetchOnce() {
      if (cancelled || document.hidden) return;
      const ctrl = new AbortController();
      const timer = setTimeout(() => ctrl.abort(), 8_000);
      try {
        const r = await fetch(url, { signal: ctrl.signal });
        clearTimeout(timer);
        if (!r.ok || cancelled) return;
        const data = (await r.json()) as MarketNews;
        if (!cancelled) setState({ data, loading: false });
      } catch {
        clearTimeout(timer);
        if (!cancelled) setState((s) => ({ ...s, loading: false }));
      }
    }

    void fetchOnce();
    const t = setInterval(() => void fetchOnce(), REFRESH_INTERVAL_MS);
    const onVisible = () => { if (!document.hidden) void fetchOnce(); };
    document.addEventListener('visibilitychange', onVisible);
    return () => {
      cancelled = true;
      clearInterval(t);
      document.removeEventListener('visibilitychange', onVisible);
    };
  }, []);

  return state;
}
