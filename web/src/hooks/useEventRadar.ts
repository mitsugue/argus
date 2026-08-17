import { useSyncExternalStore } from 'react';
import { deauthorizeEventRadar, liveAuthorityState,
  scheduleLiveAuthorityExpiry, type LiveAuthorityState } from '../domain/liveAuthority';
import { createSharedPollingStore } from '../lib/sharedPollingStore';
import type { EventsSnapshot } from '../types/events';

// connecting | live | partial | mock — same model as the other live hooks,
// plus "partial" (some official sources live, one or more failed).
export type ConnPhase = 'connecting' | 'live' | 'partial' | 'mock';

interface State {
  data: EventsSnapshot | null;
  error: string | null;
  loading: boolean;
  phase: ConnPhase;
  attempt: number;
  authority: LiveAuthorityState | 'unavailable' | 'refresh_failed';
}

// Minimal mock fallback — used only when VITE_ARGUS_BACKEND_URL is unset or
// every attempt fails. NOT a real calendar (escalation is left neutral).
const MOCK_SNAPSHOT: EventsSnapshot = {
  status: 'mock',
  asOf: null,
  timezone: 'Asia/Tokyo',
  sources: [
    { name: 'Federal Reserve', status: 'mock', lastUpdated: null },
    { name: 'Bureau of Labor Statistics', status: 'mock', lastUpdated: null },
    { name: 'Bureau of Economic Analysis', status: 'mock', lastUpdated: null },
    { name: 'Bank of Japan', status: 'mock', lastUpdated: null },
    { name: 'TreasuryDirect', status: 'mock', lastUpdated: null },
  ],
  // Absence of calendar authority cannot fabricate a CPI/BOJ D-day.
  events: [],
};

const MAX_ATTEMPTS = 3;
const ATTEMPT_TIMEOUT_MS = 8_000;
const RETRY_DELAYS_MS = [3_000, 6_000];
const REFRESH_INTERVAL_MS = 2 * 60_000;

function sleep(ms: number): Promise<void> {
  return new Promise((res) => setTimeout(res, ms));
}

/**
 * Official event calendar for ARGUS Event Radar from the backend
 * `/api/argus/events`. Falls back to MOCK_SNAPSHOT (`phase === "mock"`) when the
 * backend is unset or every attempt fails. The backend itself may report
 * `partial` (some official sources live, one or more failed) — surfaced as-is.
 */
const INITIAL_STATE: State = {
  data: null, error: null, loading: true, phase: 'connecting', attempt: 0,
  authority: 'unavailable',
};

const eventRadarStore = createSharedPollingStore<State>(
  INITIAL_STATE,
  (setState, getState) => {
    const backend = import.meta.env.VITE_ARGUS_BACKEND_URL;
    if (!backend) {
      setState({ data: MOCK_SNAPSHOT, error: null, loading: false, phase: 'mock',
        attempt: 0, authority: 'unavailable' });
      return () => {};
    }
    const url = backend.replace(/\/$/, '') + '/api/argus/events';
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

    async function fetchSnapshot(): Promise<EventsSnapshot> {
      const ctrl = new AbortController();
      controllers.add(ctrl);
      const timer = window.setTimeout(() => ctrl.abort(), ATTEMPT_TIMEOUT_MS);
      try {
        const response = await fetch(url, { signal: ctrl.signal });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return await response.json() as EventsSnapshot;
      } finally {
        window.clearTimeout(timer);
        controllers.delete(ctrl);
      }
    }

    function accept(data: EventsSnapshot, attempt: number) {
      cancelExpiry();
      if (data.status === 'mock') {
        setState({ data, error: null, loading: false, phase: 'mock', attempt,
          authority: 'unavailable' });
        return;
      }
      const authority = liveAuthorityState(data.asOf, 'eventRadar');
      if (authority !== 'fresh') {
        setState({ data: deauthorizeEventRadar(data,
          authority === 'expired' ? 'snapshot_expired' : 'invalid_as_of'),
        error: null, loading: false, phase: 'partial', attempt, authority });
        return;
      }
      setState({ data, error: null, loading: false, phase: data.status, attempt,
        authority: 'fresh' });
      cancelExpiry = scheduleLiveAuthorityExpiry(data.asOf, 'eventRadar', () => {
        const current = getState();
        if (!current.data || current.authority !== 'fresh') return;
        setState({ ...current,
          data: deauthorizeEventRadar(current.data, 'snapshot_expired'),
          phase: 'partial', authority: 'expired' });
      });
    }

    function failRefresh(message: string) {
      cancelExpiry();
      const current = getState();
      if (current.data && current.phase !== 'mock') {
        setState({ ...current,
          data: deauthorizeEventRadar(current.data, 'refresh_failed'),
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
          setState({ data: MOCK_SNAPSHOT, error: msg, loading: false, phase: 'mock',
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

    const retained = getState();
    if (retained.data && retained.authority === 'fresh') accept(retained.data, retained.attempt);
    const interval = window.setInterval(() => void acquire(refresh), REFRESH_INTERVAL_MS);
    const onVisible = () => { if (!document.hidden) void acquire(refresh); };
    document.addEventListener('visibilitychange', onVisible);
    void acquire(run);
    return () => {
      cancelled = true;
      cancelExpiry();
      for (const controller of controllers) controller.abort();
      controllers.clear();
      window.clearInterval(interval);
      document.removeEventListener('visibilitychange', onVisible);
    };
  },
);

export function useEventRadar(): State {
  return useSyncExternalStore(
    eventRadarStore.subscribe, eventRadarStore.getSnapshot, eventRadarStore.getSnapshot);
}
