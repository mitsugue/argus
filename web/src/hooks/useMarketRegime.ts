import { scheduleVisibleInterval, subscribeInitialVisibleRead } from '../lib/pollingPolicy';
import { useSyncExternalStore } from 'react';
import { deauthorizeMarketRegime, liveAuthorityState,
  scheduleLiveAuthorityExpiry, type LiveAuthorityState } from '../domain/liveAuthority';
import { createSharedPollingStore } from '../lib/sharedPollingStore';
import { CALENDAR_VISIBLE_MS } from '../lib/pollingPolicy';
import type { MarketRegimeSnapshot } from '../types/marketRegime';

export type RegimePhase = 'connecting' | 'live' | 'partial' | 'mock';

interface State {
  data: MarketRegimeSnapshot | null;
  error: string | null;
  loading: boolean;
  phase: RegimePhase;
  attempt: number;
  authority: LiveAuthorityState | 'unavailable' | 'refresh_failed';
}

// 2026-10-27 (owner): no made-up regime. With the backend unset or every attempt
// failed the data stays empty (phase 'mock'), so no fixed label reaches a decision.

const MAX_ATTEMPTS = 3;
const ATTEMPT_TIMEOUT_MS = 9_000;
const RETRY_DELAYS_MS = [3_000, 6_000];
const REFRESH_INTERVAL_MS = CALENDAR_VISIBLE_MS;  // visible-page cadence (was 60s)

function sleep(ms: number): Promise<void> {
  return new Promise((res) => setTimeout(res, ms));
}

const INITIAL_STATE: State = {
  data: null, error: null, loading: true, phase: 'connecting', attempt: 0,
  authority: 'unavailable',
};

const marketRegimeStore = createSharedPollingStore<State>(
  INITIAL_STATE,
  (setState, getState, restored) => {
    const backend = import.meta.env.VITE_ARGUS_BACKEND_URL;
    if (!backend) {
      setState({ data: null, error: null, loading: false, phase: 'mock',
        attempt: 0, authority: 'unavailable' });
      return () => {};
    }
    const url = backend.replace(/\/$/, '') + '/api/argus/market-regime';
    let cancelled = false;
    let acquisition: Promise<void> | null = null;
    let cancelExpiry = () => {};
    const controllers = new Set<AbortController>();

    function acquire(task: () => Promise<void>): Promise<void> {
      if (acquisition) return acquisition;
      const current = task().finally(() => {
        if (acquisition === current) acquisition = null;
      });
      acquisition = current;
      return current;
    }

    async function fetchSnapshot(): Promise<MarketRegimeSnapshot> {
      const ctrl = new AbortController();
      controllers.add(ctrl);
      const timer = window.setTimeout(() => ctrl.abort(), ATTEMPT_TIMEOUT_MS);
      try {
        const response = await fetch(url, { signal: ctrl.signal });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return await response.json() as MarketRegimeSnapshot;
      } finally {
        window.clearTimeout(timer);
        controllers.delete(ctrl);
      }
    }

    function accept(data: MarketRegimeSnapshot, attempt: number) {
      cancelExpiry();
      const authority = liveAuthorityState(data.asOf, 'marketRegime');
      if (authority !== 'fresh') {
        const reason = authority === 'expired' ? 'snapshot_expired' : 'invalid_as_of';
        setState({ data: deauthorizeMarketRegime(data, reason), error: null,
          loading: false, phase: 'partial', attempt, authority });
        return;
      }
      const phase: RegimePhase = data.status === 'live' ? 'live'
        : data.status === 'partial' ? 'partial' : 'mock';
      setState({ data, error: null, loading: false, phase, attempt, authority: 'fresh' });
      cancelExpiry = scheduleLiveAuthorityExpiry(data.asOf, 'marketRegime', () => {
        const current = getState();
        if (!current.data || current.authority !== 'fresh') return;
        setState({ ...current,
          data: deauthorizeMarketRegime(current.data, 'snapshot_expired'),
          phase: 'partial', authority: 'expired' });
      });
    }

    function failRefresh(message: string) {
      const current = getState();
      cancelExpiry();
      if (current.data && current.phase !== 'mock') {
        setState({ ...current,
          data: deauthorizeMarketRegime(current.data, 'refresh_failed'),
          error: message, loading: false, phase: 'partial', authority: 'refresh_failed' });
      }
    }

    async function run() {
      for (let attempt = 1; attempt <= MAX_ATTEMPTS; attempt++) {
        if (cancelled) return;
        setState((s) => ({ ...s, phase: 'connecting', loading: true, attempt, error: null }));
        try {
          const data = await fetchSnapshot();
          if (cancelled) return;
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
          setState({ data: null, error: msg, loading: false, phase: 'mock',
            attempt, authority: 'unavailable' });
          return;
        }
      }
    }

    async function refresh() {
      if (cancelled || document.hidden) return;
      try {
        const data = await fetchSnapshot();
        if (!cancelled) accept(data, getState().attempt);
      } catch (err: unknown) {
        if (!cancelled) failRefresh(err instanceof Error ? err.message : String(err));
      }
    }

    // The shared store intentionally retains its snapshot with zero subscribers.
    // Revalidate it synchronously on remount so an expired value is never exposed
    // during the first asynchronous refresh, and re-arm its evidence deadline.
    const retained = getState();
    if (retained.data && retained.authority === 'fresh') {
      accept(retained.data, retained.attempt);
    }
    const refreshTimer = scheduleVisibleInterval(
      () => void acquire(refresh), REFRESH_INTERVAL_MS);
    const onVisible = () => { if (!document.hidden) void acquire(refresh); };
    const stopInitialOnVisible = subscribeInitialVisibleRead(onVisible, restored);
    if (!restored) void acquire(run);
    return () => {
      cancelled = true;
      cancelExpiry();
      for (const controller of controllers) controller.abort();
      controllers.clear();
      refreshTimer();
      stopInitialOnVisible();
    };
  },
  "polling:useMarketRegime");

export function useMarketRegime(): State {
  return useSyncExternalStore(
    marketRegimeStore.subscribe, marketRegimeStore.getSnapshot,
    marketRegimeStore.getSnapshot);
}
