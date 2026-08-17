import { useEffect, useMemo, useState } from 'react';
import type { CryptoQuote, CryptoWatchlistSnapshot } from '../types/crypto';

export type CryptoPhase = 'connecting' | 'live' | 'partial' | 'mock';

interface State {
  byId: Record<string, CryptoQuote>;
  phase: CryptoPhase;
  asOf: string | null;
}

const ATTEMPT_TIMEOUT_MS = 9_000;

/**
 * Live USD quotes for the watched crypto assets via the backend
 * `/api/argus/crypto-watchlist?ids=…` (CoinGecko, keyless). `ids` are
 * CoinGecko ids (from each asset's `coingecko:<id>` memo). No mock prices on
 * failure — callers render the honest "not connected" placeholder instead.
 */
export function useCryptoWatchlist(ids: string[]): State {
  const key = useMemo(() => ids.slice().sort().join(','), [ids]);
  const [state, setState] = useState<State>({ byId: {}, phase: 'connecting', asOf: null });

  useEffect(() => {
    if (!key) {
      setState({ byId: {}, phase: 'live', asOf: null });
      return;
    }
    const backend = import.meta.env.VITE_ARGUS_BACKEND_URL;
    if (!backend) {
      setState({ byId: {}, phase: 'mock', asOf: null });
      return;
    }
    const url = backend.replace(/\/$/, '') +
      '/api/argus/crypto-watchlist?ids=' + encodeURIComponent(key);
    let cancelled = false;
    const fetchOnce = async () => {
      const ctrl = new AbortController();
      const timer = setTimeout(() => ctrl.abort(), ATTEMPT_TIMEOUT_MS);
      setState((s) => ({ ...s, phase: 'connecting' }));
      try {
        const r = await fetch(url, { signal: ctrl.signal });
        clearTimeout(timer);
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const data = (await r.json()) as CryptoWatchlistSnapshot;
        if (cancelled) return;
        const byId: Record<string, CryptoQuote> = {};
        for (const q of data.quotes) byId[q.id] = q;
        setState({ byId, phase: data.status, asOf: data.asOf });
      } catch {
        clearTimeout(timer);
        if (!cancelled) setState((s) => (Object.keys(s.byId).length ? s : { byId: {}, phase: 'mock', asOf: null }));
      }
    };
    void fetchOnce();
    // Live refresh every 30s (crypto is 24/7) — was fetch-once-on-mount (frozen).
    const iv = setInterval(() => void fetchOnce(), 30_000);
    return () => { cancelled = true; clearInterval(iv); };
  }, [key]);

  return state;
}
