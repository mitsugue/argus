import { useEffect, useState } from 'react';
import type { JapanWatchlistSnapshot, JapanStockQuote } from '../types/watch';

// Connection phase, surfaced to the UI so a cold-starting backend reads as
// "connecting" rather than snapping straight to "mock" — same model as
// useRatesSnapshot.
export type ConnPhase = 'connecting' | 'live' | 'partial' | 'mock';

interface State {
  data: JapanWatchlistSnapshot | null;
  error: string | null;
  loading: boolean;
  phase: ConnPhase;
  attempt: number;
}

// Mock fallback (used when VITE_ARGUS_BACKEND_URL is unset, the backend is
// unreachable, or J-Quants returns nothing). Values mirror the backend's
// _JP_WATCHLIST mocks so dev and prod look the same shape — NOT real quotes.
function mk(symbol: string, name: string, price: number, changeAbs: number, changePct: number, volume: number): JapanStockQuote {
  return { symbol, name, price, changeAbs, changePct, volume, date: null, status: 'mock' };
}
const MOCK_SNAPSHOT: JapanWatchlistSnapshot = {
  status: 'mock',
  asOf: null,
  stocks: [
    // 8058 = 三菱商事 (Mitsubishi Corporation) — NOT Mitsubishi Heavy (7011).
    mk('8058', 'Mitsubishi Corporation', 2900, 26, 0.90, 9_800_000),
    mk('9984', 'SoftBank Group', 9800, -180, -1.80, 8_100_000),
    mk('5801', 'Furukawa Electric', 6400, 120, 1.91, 3_200_000),
    mk('5803', 'Fujikura', 7200, 210, 3.01, 11_500_000),
    mk('6584', 'Sanoh Industrial', 1480, -8, -0.54, 410_000),
    mk('285A', 'Kioxia Holdings', 1820, 35, 1.96, 5_600_000),
    mk('9501', 'Tokyo Electric Power', 720, -4, -0.55, 14_200_000),
  ],
};

// Render's free tier spins the backend down when idle; the first request after
// a sleep can take 30–60s. Retry a couple of times with a per-attempt timeout,
// staying in "connecting", and only settle on mock once every attempt fails.
const MAX_ATTEMPTS = 3;
const ATTEMPT_TIMEOUT_MS = 8_000;
const RETRY_DELAYS_MS = [3_000, 6_000];

// Auto-refresh: the moomoo bridge pushes quotes every ~60s, so re-fetch on the
// same cadence while the tab is visible. Silent — keeps showing the last good
// data on a failed refresh instead of flashing back to "connecting"/mock.
const REFRESH_INTERVAL_MS = 60_000;

function sleep(ms: number): Promise<void> {
  return new Promise((res) => setTimeout(res, ms));
}

/**
 * Live snapshot of the watched Japan names (price / change / volume / date),
 * sourced from the backend `/api/argus/japan-watchlist` (J-Quants).
 *
 * Pass `symbols` (the user's actual JP assets) for a DYNAMIC fetch — the
 * backend resolves names from the J-Quants master and omits failed rows.
 * Without `symbols` (or with an empty list) the curated default is fetched.
 * Dynamic mode falls back to an EMPTY mock (no fake prices); the curated mode
 * keeps the legacy plausible-mock so the shell still renders offline.
 */
export function useJapanWatchlist(symbols?: string[]): State {
  const symKey = symbols && symbols.length ? symbols.slice().sort().join(',') : '';
  const [state, setState] = useState<State>({
    data: null,
    error: null,
    loading: true,
    phase: 'connecting',
    attempt: 0,
  });

  useEffect(() => {
    const dynamic = symKey.length > 0;
    const fallback: JapanWatchlistSnapshot = dynamic
      ? { status: 'mock', asOf: null, stocks: [] }
      : MOCK_SNAPSHOT;
    const backend = import.meta.env.VITE_ARGUS_BACKEND_URL;
    if (!backend) {
      setState({ data: fallback, error: null, loading: false, phase: 'mock', attempt: 0 });
      return;
    }
    const url = backend.replace(/\/$/, '') + '/api/argus/japan-watchlist'
      + (dynamic ? `?symbols=${encodeURIComponent(symKey)}` : '');
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
          const data = (await r.json()) as JapanWatchlistSnapshot;
          if (cancelled) return;
          // Trust the payload's own status (a 200 can still be all-mock).
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
          setState({ data: fallback, error: msg, loading: false, phase: 'mock', attempt });
          return;
        }
      }
    }

    // Silent background refresh — only swaps in fresh data, never degrades the
    // visible state on failure.
    async function refresh() {
      if (cancelled || document.hidden) return;
      const ctrl = new AbortController();
      const timer = setTimeout(() => ctrl.abort(), ATTEMPT_TIMEOUT_MS);
      try {
        const r = await fetch(url, { signal: ctrl.signal });
        clearTimeout(timer);
        if (!r.ok || cancelled) return;
        const data = (await r.json()) as JapanWatchlistSnapshot;
        if (cancelled) return;
        setState((s) => ({ ...s, data, error: null, phase: data.status }));
      } catch {
        clearTimeout(timer);
      }
    }
    const refreshTimer = setInterval(() => void refresh(), REFRESH_INTERVAL_MS);
    // Returning to the tab after a while → refresh immediately, don't wait out
    // the remainder of the interval.
    const onVisible = () => {
      if (!document.hidden) void refresh();
    };
    document.addEventListener('visibilitychange', onVisible);

    void run();
    return () => {
      cancelled = true;
      clearInterval(refreshTimer);
      document.removeEventListener('visibilitychange', onVisible);
    };
  }, [symKey]);

  return state;
}
