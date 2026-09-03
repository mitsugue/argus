import { useSyncExternalStore } from 'react';
import {
  dynamicSnapshotIsEmpty, mergeHistoryRows, resolveFromCurated, rowFromPriceHistory,
} from '../domain/jpWatchFallback';
import { createSharedPollingStore, type SharedPollingStore } from '../lib/sharedPollingStore';
import type { JapanWatchlistSnapshot, JapanStockQuote } from '../types/watch';
import {
  normalizeJapanWatchSnapshot,
  type JapanTruthSnapshot,
} from '../domain/watchQuoteTruth';
import { quoteDecisionExpiresAt } from '../domain/liveQuote';

// Connection phase, surfaced to the UI so a cold-starting backend reads as
// "connecting" rather than snapping straight to "mock" — same model as
// useRatesSnapshot.
export type ConnPhase = 'connecting' | 'live' | 'delayed' | 'unknown' | 'partial' | 'mixed' | 'mock';

interface State {
  data: JapanTruthSnapshot | null;
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

// Auto-refresh: the moomoo bridge pushes quotes every ~15s (v10.10.1), so
// re-fetch on the same cadence while the tab is visible. Silent — keeps
// showing the last good data on a failed refresh instead of flashing back to
// "connecting"/mock. 15s × 2 endpoints ≈ 8 req/min — well inside the per-IP
// heavy-endpoint limit (30/min).
const REFRESH_INTERVAL_MS = 15_000;

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
const INITIAL_STATE: State = {
  data: null,
  error: null,
  loading: true,
  phase: 'connecting',
  attempt: 0,
};
const japanWatchlistStores = new Map<string, SharedPollingStore<State>>();

function japanWatchlistStore(symKey: string): SharedPollingStore<State> {
  const existing = japanWatchlistStores.get(symKey);
  if (existing) return existing;

  const store = createSharedPollingStore<State>(INITIAL_STATE, (setState, getState) => {
    const dynamic = symKey.length > 0;
    const fallback: JapanWatchlistSnapshot = dynamic
      ? { status: 'mock', asOf: null, stocks: [] }
      : MOCK_SNAPSHOT;
    const normalizedFallback = normalizeJapanWatchSnapshot(fallback);
    const backend = import.meta.env.VITE_ARGUS_BACKEND_URL;
    if (!backend) {
      setState({ data: normalizedFallback, error: null, loading: false, phase: 'mock', attempt: 0 });
      return () => {};
    }
    const base = backend.replace(/\/$/, '');
    const curatedUrl = base + '/api/argus/japan-watchlist';
    const url = curatedUrl + (dynamic ? `?symbols=${encodeURIComponent(symKey)}` : '');
    let cancelled = false;
    let acquisition: Promise<void> | null = null;
    let cancelExpiry = () => {};
    const controllers = new Set<AbortController>();

    function armExpiry(data: JapanTruthSnapshot) {
      cancelExpiry();
      const now = Date.now();
      const deadlines = data.stocks.map((row) => row.quoteTruth
        ? quoteDecisionExpiresAt(row.quoteTruth) : null)
        .filter((value): value is number => value != null);
      if (!deadlines.length) return;
      const delay = Math.min(...deadlines) - now;
      if (delay < 0) {
        const aged = normalizeJapanWatchSnapshot(data as unknown as JapanWatchlistSnapshot);
        setState((state) => ({ ...state, data: aged, phase: aged.status }));
        armExpiry(aged);
        return;
      }
      const handle = window.setTimeout(() => {
        const current = getState();
        if (!current.data) return;
        const aged = normalizeJapanWatchSnapshot(
          current.data as unknown as JapanWatchlistSnapshot);
        setState({ ...current, data: aged, phase: aged.status });
        armExpiry(aged);
      }, Math.max(1, Math.min(delay + 1, 2_147_000_000)));
      cancelExpiry = () => window.clearTimeout(handle);
    }

    function accept(data: JapanTruthSnapshot, attempt: number) {
      setState({ data, error: null, loading: false, phase: data.status, attempt });
      armExpiry(data);
    }

    function revalidateCurrent() {
      const current = getState();
      if (!current.data) return;
      const aged = normalizeJapanWatchSnapshot(
        current.data as unknown as JapanWatchlistSnapshot);
      setState({ ...current, data: aged, phase: aged.status, loading: false });
      armExpiry(aged);
    }

    async function fetchJson(target: string): Promise<JapanWatchlistSnapshot> {
      const ctrl = new AbortController();
      controllers.add(ctrl);
      const timer = window.setTimeout(() => ctrl.abort(), ATTEMPT_TIMEOUT_MS);
      try {
        const response = await fetch(target, { signal: ctrl.signal });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return (await response.json()) as JapanWatchlistSnapshot;
      } finally {
        window.clearTimeout(timer);
        controllers.delete(ctrl);
      }
    }

    async function fetchSnapshot(): Promise<JapanTruthSnapshot> {
      const dynamicSnapshot = await fetchJson(url);
      // v13.5.43: the dynamic public path is bridge/cache-only and answers an
      // EMPTY mock when nothing is cached; resolve the owner's symbols from the
      // curated J-Quants snapshot instead of showing 価格データ未取得.
      if (dynamic && dynamicSnapshotIsEmpty(dynamicSnapshot as unknown as Parameters<typeof dynamicSnapshotIsEmpty>[0])) {
        const requested = symKey.split(',');
        let resolved: JapanWatchlistSnapshot | null = null;
        try {
          const curated = await fetchJson(curatedUrl);
          resolved = resolveFromCurated(
            curated as unknown as Parameters<typeof resolveFromCurated>[0], requested,
          ) as unknown as JapanWatchlistSnapshot | null;
        } catch {
          // keep the truthful dynamic answer below
        }
        // v13.5.44: owner symbols the curated list does not carry resolve from
        // the cached daily history (real EOD close, labelled delayed/EOD).
        const covered = new Set((resolved?.stocks ?? []).map((r) => r.symbol.toUpperCase()));
        const missing = requested.filter((s) => !covered.has(s.toUpperCase())).slice(0, 8);
        const historyRows = (await Promise.all(missing.map(async (symbol) => {
          try {
            const history = await fetchJson(`${base}/api/argus/price-history?symbol=${encodeURIComponent(symbol)}&market=JP`);
            return rowFromPriceHistory(symbol, history as unknown as Parameters<typeof rowFromPriceHistory>[1]);
          } catch {
            return null;
          }
        }))).filter((row): row is NonNullable<typeof row> => row !== null);
        const merged = mergeHistoryRows(
          resolved as unknown as Parameters<typeof mergeHistoryRows>[0], historyRows, requested);
        if (merged) return normalizeJapanWatchSnapshot(merged as unknown as JapanWatchlistSnapshot);
      }
      return normalizeJapanWatchSnapshot(dynamicSnapshot);
    }

    function acquire(task: () => Promise<void>): Promise<void> {
      if (acquisition) return acquisition;
      const current = task().finally(() => {
        if (acquisition === current) acquisition = null;
      });
      acquisition = current;
      return current;
    }

    async function run() {
      for (let attempt = 1; attempt <= MAX_ATTEMPTS; attempt++) {
        if (cancelled) return;
        setState((s) => ({ ...s, phase: 'connecting', loading: true, attempt, error: null }));

        try {
          const data = await fetchSnapshot();
          if (cancelled) return;
          // Trust the payload's own status (a 200 can still be all-mock).
          accept(data, attempt);
          return;
        } catch (err: unknown) {
          if (cancelled) return;
          const msg = err instanceof Error ? err.message : String(err);
          if (attempt < MAX_ATTEMPTS) {
            setState((s) => ({ ...s, error: msg, phase: 'connecting', loading: true, attempt }));
            await sleep(RETRY_DELAYS_MS[attempt - 1] ?? 6_000);
            continue;
          }
          setState({ data: normalizedFallback, error: msg, loading: false, phase: 'mock', attempt });
          return;
        }
      }
    }

    // A failed refresh may retain the last observed values, but it must age their
    // source timestamps again.  In particular an old LIVE proof cannot remain
    // LIVE merely because the transport failed before a replacement arrived.
    async function refresh() {
      if (cancelled || document.hidden) return;
      try {
        const data = await fetchSnapshot();
        if (cancelled) return;
        setState((s) => ({ ...s, data, error: null, phase: data.status }));
        armExpiry(data);
      } catch (err: unknown) {
        if (cancelled) return;
        const msg = err instanceof Error ? err.message : String(err);
        setState((s) => {
          if (!s.data) return { ...s, error: msg };
          const aged = normalizeJapanWatchSnapshot(
            s.data as unknown as JapanWatchlistSnapshot,
          );
          return { ...s, data: aged, error: msg, phase: aged.status };
        });
      }
    }
    const refreshTimer = window.setInterval(() => void acquire(refresh), REFRESH_INTERVAL_MS);
    // Returning to the tab after a while → refresh immediately, don't wait out
    // the remainder of the interval.
    const onVisible = () => {
      if (!document.hidden) {
        revalidateCurrent();
        void acquire(refresh);
      }
    };
    document.addEventListener('visibilitychange', onVisible);

    if (getState().data) revalidateCurrent();
    void acquire(run);
    return () => {
      cancelled = true;
      cancelExpiry();
      for (const controller of controllers) controller.abort();
      controllers.clear();
      window.clearInterval(refreshTimer);
      document.removeEventListener('visibilitychange', onVisible);
    };
  });
  japanWatchlistStores.set(symKey, store);
  return store;
}

export function useJapanWatchlist(symbols?: string[]): State {
  const symKey = symbols && symbols.length ? symbols.slice().sort().join(',') : '';
  const store = japanWatchlistStore(symKey);
  return useSyncExternalStore(store.subscribe, store.getSnapshot, store.getSnapshot);
}
