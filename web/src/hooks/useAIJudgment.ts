import { useSyncExternalStore } from 'react';
import { deauthorizeAIJudgment, liveAuthorityState,
  scheduleLiveAuthorityExpiry, type LiveAuthorityState } from '../domain/liveAuthority';
import { createSharedPollingStore } from '../lib/sharedPollingStore';
import type { AIJudgment } from '../types/aiJudgment';

// connecting | live | partial | mock | disabled. Reads the CACHED judgment only
// (GET) — never triggers an AI run (that is an admin-gated POST).
export type ConnPhase = 'connecting' | 'live' | 'partial' | 'mock' | 'disabled'
  | 'missing_keys' | 'no_cached_result' | 'not_run_yet';

interface State {
  data: AIJudgment | null;
  error: string | null;
  loading: boolean;
  phase: ConnPhase;
  attempt: number;
  authority: LiveAuthorityState | 'unavailable' | 'refresh_failed';
}

const MOCK_SNAPSHOT: AIJudgment = {
  status: 'mock',
  asOf: '',
  engineVersion: 'ai-judge-v1',
  runMode: 'cached',
  models: { primary: null, checker: null },
  summaryJa: '',
  marketRiskJa: '',
  labels: [],
};

const MAX_ATTEMPTS = 3;
const ATTEMPT_TIMEOUT_MS = 8_000;
const RETRY_DELAYS_MS = [3_000, 6_000];
const REFRESH_INTERVAL_MS = 5 * 60_000;

function sleep(ms: number): Promise<void> {
  return new Promise((res) => setTimeout(res, ms));
}

/**
 * Latest CACHED AI judgment from `/api/argus/ai-judgment` (engine v1). Read-only
 * and frontend-safe: it never triggers an expensive AI run. Returns the backend
 * status verbatim — including `disabled` when the layer is off.
 */
const INITIAL_STATE: State = {
  data: null, error: null, loading: true, phase: 'connecting', attempt: 0,
  authority: 'unavailable',
};

const aiJudgmentStore = createSharedPollingStore<State>(
  INITIAL_STATE,
  (setState, getState) => {
    const backend = import.meta.env.VITE_ARGUS_BACKEND_URL;
    if (!backend) {
      setState({ data: MOCK_SNAPSHOT, error: null, loading: false, phase: 'mock',
        attempt: 0, authority: 'unavailable' });
      return () => {};
    }
    const url = backend.replace(/\/$/, '') + '/api/argus/ai-judgment';
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

    async function fetchSnapshot(): Promise<AIJudgment> {
      const ctrl = new AbortController();
      controllers.add(ctrl);
      const timer = window.setTimeout(() => ctrl.abort(), ATTEMPT_TIMEOUT_MS);
      try {
        const response = await fetch(url, { signal: ctrl.signal });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return await response.json() as AIJudgment;
      } finally {
        window.clearTimeout(timer);
        controllers.delete(ctrl);
      }
    }

    function accept(data: AIJudgment, attempt: number) {
      cancelExpiry();
      if (!['live', 'partial'].includes(data.status)) {
        setState({ data, error: null, loading: false, phase: data.status,
          attempt, authority: 'unavailable' });
        return;
      }
      const timestampState = liveAuthorityState(data.asOf, 'aiJudgment');
      const authority = data.freshness === 'stale' ? 'expired' : timestampState;
      if (authority !== 'fresh') {
        const reason = authority === 'expired' ? 'snapshot_expired' : 'invalid_as_of';
        setState({ data: deauthorizeAIJudgment(data, reason), error: null,
          loading: false, phase: 'partial', attempt, authority });
        return;
      }
      setState({ data, error: null, loading: false, phase: data.status,
        attempt, authority: 'fresh' });
      cancelExpiry = scheduleLiveAuthorityExpiry(data.asOf, 'aiJudgment', () => {
        const current = getState();
        if (!current.data || current.authority !== 'fresh') return;
        setState({ ...current,
          data: deauthorizeAIJudgment(current.data, 'snapshot_expired'),
          phase: 'partial', authority: 'expired' });
      });
    }

    function failRefresh(message: string) {
      const current = getState();
      cancelExpiry();
      if (!current.data || !['live', 'partial'].includes(current.phase)) return;
      setState({ ...current,
        data: deauthorizeAIJudgment(current.data, 'refresh_failed'),
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
    if (retained.data && retained.authority === 'fresh') {
      accept(retained.data, retained.attempt);
    }
    const refreshTimer = window.setInterval(
      () => void acquire(refresh), REFRESH_INTERVAL_MS);
    const onVisible = () => { if (!document.hidden) void acquire(refresh); };
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
  },
);

export function useAIJudgment(): State {
  return useSyncExternalStore(
    aiJudgmentStore.subscribe, aiJudgmentStore.getSnapshot,
    aiJudgmentStore.getSnapshot);
}
