import { useEffect, useState } from 'react';
import type { USWatchlistSnapshot, USStockQuote } from '../types/watch';

// connecting | live | mock — same model as useJapanWatchlist / useRatesSnapshot.
export type ConnPhase = 'connecting' | 'live' | 'mock';

interface State {
  data: USWatchlistSnapshot | null;
  error: string | null;
  loading: boolean;
  phase: ConnPhase;
  attempt: number;
}

// Mock fallback — values mirror the backend's _US_WATCHLIST mocks (NOT real
// quotes). Used when VITE_ARGUS_BACKEND_URL is unset or every attempt fails.
function mk(symbol: string, name: string, price: number, changeAbs: number, changePct: number, volume: number): USStockQuote {
  return { symbol, name, price, changeAbs, changePct, volume, date: null, status: 'mock' };
}
const MOCK_SNAPSHOT: USWatchlistSnapshot = {
  status: 'mock',
  asOf: null,
  provider: 'twelvedata',
  stocks: [
    mk('NVDA', 'NVIDIA', 142.30, -1.32, -0.92, 240_000_000),
    mk('AAPL', 'Apple', 218.40, -0.74, -0.34, 52_000_000),
    mk('TSLA', 'Tesla', 178.20, -5.74, -3.12, 98_000_000),
    mk('META', 'Meta Platforms', 487.10, 3.78, 0.78, 14_000_000),
  ],
};

// Render's free tier sleeps the backend; the first request after idle can take
// 30–60s. Retry a couple of times with a per-attempt timeout, staying in
// "connecting", and settle on mock only once every attempt fails.
const MAX_ATTEMPTS = 3;
const ATTEMPT_TIMEOUT_MS = 8_000;
const RETRY_DELAYS_MS = [3_000, 6_000];

function sleep(ms: number): Promise<void> {
  return new Promise((res) => setTimeout(res, ms));
}

/**
 * Live snapshot of the watched US names (price / change / volume / date) from
 * the backend `/api/argus/us-watchlist` (Twelve Data). Falls back to
 * MOCK_SNAPSHOT (`phase === "mock"`) when the backend is unset or every attempt
 * fails. Mirrors useJapanWatchlist's connecting/live/mock model.
 */
export function useUSWatchlist(): State {
  const [state, setState] = useState<State>({
    data: null,
    error: null,
    loading: true,
    phase: 'connecting',
    attempt: 0,
  });

  useEffect(() => {
    const backend = import.meta.env.VITE_ARGUS_BACKEND_URL;
    if (!backend) {
      setState({ data: MOCK_SNAPSHOT, error: null, loading: false, phase: 'mock', attempt: 0 });
      return;
    }
    const url = backend.replace(/\/$/, '') + '/api/argus/us-watchlist';
    let cancelled = false;

    async function run() {
      for (let attempt = 1; attempt <= MAX_ATTEMPTS; attempt++) {
        if (cancelled) return;
        setState((s) => ({ ...s, phase: 'connecting', loading: true, attempt, error: null }));

        const ctrl = new AbortController();
        const timer = setTimeout(() => ctrl.abort(), ATTEMPT_TIMEOUT_MS);
        try {
          const r = await fetch(url, { signal: ctrl.signal });
          clearTimeout(timer);
          if (!r.ok) throw new Error(`HTTP ${r.status}`);
          const data = (await r.json()) as USWatchlistSnapshot;
          if (cancelled) return;
          setState({ data, error: null, loading: false, phase: data.status, attempt });
          return;
        } catch (err: unknown) {
          clearTimeout(timer);
          if (cancelled) return;
          const msg = err instanceof Error ? err.message : String(err);
          if (attempt < MAX_ATTEMPTS) {
            setState((s) => ({ ...s, error: msg, phase: 'connecting', loading: true, attempt }));
            await sleep(RETRY_DELAYS_MS[attempt - 1] ?? 6_000);
            continue;
          }
          setState({ data: MOCK_SNAPSHOT, error: msg, loading: false, phase: 'mock', attempt });
          return;
        }
      }
    }

    void run();
    return () => {
      cancelled = true;
    };
  }, []);

  return state;
}
