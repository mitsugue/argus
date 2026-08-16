import { useSyncExternalStore } from 'react';
import { deauthorizeActionSnapshot, liveAuthorityState,
  scheduleLiveAuthorityExpiry, type LiveAuthorityState } from '../domain/liveAuthority';
import { createSharedPollingStore, type SharedPollingStore } from '../lib/sharedPollingStore';
import type { ActionLabelsSnapshot } from '../types/actionLabels';

// connecting | live | partial | mock — same model as the other live hooks.
export type ConnPhase = 'connecting' | 'live' | 'partial' | 'mock';

interface State {
  data: ActionLabelsSnapshot | null;
  error: string | null;
  loading: boolean;
  phase: ConnPhase;
  attempt: number;
  authority: LiveAuthorityState | 'unavailable' | 'refresh_failed';
}

// Mock fallback — used only when VITE_ARGUS_BACKEND_URL is unset or every
// attempt fails. Empty labels → callers fall back to a neutral HOLD per row.
const MOCK_SNAPSHOT: ActionLabelsSnapshot = {
  status: 'mock',
  asOf: '',
  engineVersion: 'action-v0',
  marketPosture: { label: 'CAUTIOUS', rationaleJa: 'ライブデータ未取得のため中立。' },
  labels: [],
};

const MAX_ATTEMPTS = 3;
const ATTEMPT_TIMEOUT_MS = 8_000;
const RETRY_DELAYS_MS = [3_000, 6_000];

// Auto-refresh: when a cold Render dyno makes every initial attempt time out
// and we settle on mock, a later silent refresh recovers to live as soon as
// the server is warm — same cadence as the watchlist hooks. Failures keep the
// last good data instead of flashing back to "connecting"/mock.
const REFRESH_INTERVAL_MS = 15_000;  // top-page % + signals live (was 60s)

function sleep(ms: number): Promise<void> {
  return new Promise((res) => setTimeout(res, ms));
}

/**
 * Rule-based action labels from the backend `/api/argus/action-labels` (engine
 * v0). Falls back to MOCK_SNAPSHOT (`phase === "mock"`) when the backend is
 * unset or every attempt fails. The backend may report `partial` when some
 * source is missing but conservative labels can still be produced.
 *
 * Pass `params` with the user's actual JP/US symbols for DYNAMIC labels —
 * unknown symbols are classified conservatively (high-beta) server-side.
 * Without params (or with both lists empty) the curated default is used.
 */
const INITIAL_STATE: State = {
  data: null,
  error: null,
  loading: true,
  phase: 'connecting',
  attempt: 0,
  authority: 'unavailable',
};
const actionLabelStores = new Map<string, SharedPollingStore<State>>();

function actionLabelStore(jpKey: string, usKey: string): SharedPollingStore<State> {
  const queryKey = JSON.stringify([jpKey, usKey]);
  const existing = actionLabelStores.get(queryKey);
  if (existing) return existing;

  const store = createSharedPollingStore<State>(INITIAL_STATE, (setState, getState) => {
    const backend = import.meta.env.VITE_ARGUS_BACKEND_URL;
    if (!backend) {
      setState({ data: MOCK_SNAPSHOT, error: null, loading: false, phase: 'mock',
        attempt: 0, authority: 'unavailable' });
      return () => {};
    }
    const qs: string[] = [];
    if (jpKey) qs.push(`jp=${encodeURIComponent(jpKey)}`);
    if (usKey) qs.push(`us=${encodeURIComponent(usKey)}`);
    const url = backend.replace(/\/$/, '') + '/api/argus/action-labels'
      + (qs.length ? `?${qs.join('&')}` : '');
    let cancelled = false;
    let acquisition: Promise<void> | null = null;
    let cancelExpiry = () => {};
    const controllers = new Set<AbortController>();

    async function fetchSnapshot(): Promise<ActionLabelsSnapshot> {
      const ctrl = new AbortController();
      controllers.add(ctrl);
      const timer = window.setTimeout(() => ctrl.abort(), ATTEMPT_TIMEOUT_MS);
      try {
        const response = await fetch(url, { signal: ctrl.signal });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return await response.json() as ActionLabelsSnapshot;
      } finally {
        window.clearTimeout(timer);
        controllers.delete(ctrl);
      }
    }

    function acquire(task: () => Promise<void>): Promise<void> {
      if (acquisition) return acquisition;
      const current = task().finally(() => {
        if (acquisition === current) acquisition = null;
      });
      acquisition = current;
      return current;
    }

    function accept(data: ActionLabelsSnapshot, attempt: number) {
      cancelExpiry();
      if (data.status === 'mock') {
        setState({ data, error: null, loading: false, phase: 'mock', attempt,
          authority: 'unavailable' });
        return;
      }
      const authority = liveAuthorityState(data.asOf, 'actionLabels');
      if (authority !== 'fresh') {
        const reason = authority === 'expired' ? 'snapshot_expired' : 'invalid_as_of';
        setState({ data: deauthorizeActionSnapshot(data, reason), error: null,
          loading: false, phase: 'partial', attempt, authority });
        return;
      }
      setState({ data, error: null, loading: false, phase: data.status, attempt,
        authority: 'fresh' });
      cancelExpiry = scheduleLiveAuthorityExpiry(data.asOf, 'actionLabels', () => {
        const current = getState();
        if (!current.data || current.authority !== 'fresh') return;
        setState({ ...current,
          data: deauthorizeActionSnapshot(current.data, 'snapshot_expired'),
          phase: 'partial', authority: 'expired' });
      });
    }

    function failRefresh(message: string) {
      const current = getState();
      cancelExpiry();
      if (!current.data || current.phase === 'mock') return;
      setState({ ...current,
        data: deauthorizeActionSnapshot(current.data, 'refresh_failed'),
        error: message, loading: false, phase: 'partial', authority: 'refresh_failed' });
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

    // Silent background refresh — only swaps in fresh data, never degrades the
    // visible state on failure. Also recovers from mock to live once the
    // backend has warmed up.
    async function refresh() {
      if (cancelled || document.hidden) return;
      try {
        const data = await fetchSnapshot();
        if (cancelled) return;
        accept(data, getState().attempt);
      } catch (err: unknown) {
        if (!cancelled) failRefresh(err instanceof Error ? err.message : String(err));
      }
    }
    const retained = getState();
    if (retained.data && retained.authority === 'fresh') {
      accept(retained.data, retained.attempt);
    }
    const refreshTimer = window.setInterval(() => void acquire(refresh), REFRESH_INTERVAL_MS);
    // Returning to the tab after a while → refresh immediately, don't wait out
    // the remainder of the interval.
    const onVisible = () => {
      if (!document.hidden) void acquire(refresh);
    };
    document.addEventListener('visibilitychange', onVisible);

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
  actionLabelStores.set(queryKey, store);
  return store;
}

export function useActionLabels(params?: { jp?: string[]; us?: string[] }): State {
  const jpKey = params?.jp?.length ? params.jp.slice().sort().join(',') : '';
  const usKey = params?.us?.length ? params.us.slice().sort().join(',') : '';
  const store = actionLabelStore(jpKey, usKey);
  return useSyncExternalStore(store.subscribe, store.getSnapshot, store.getSnapshot);
}
