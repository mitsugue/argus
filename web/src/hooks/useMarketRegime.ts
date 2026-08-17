import { useSyncExternalStore } from 'react';
import { deauthorizeMarketRegime, liveAuthorityState,
  scheduleLiveAuthorityExpiry, type LiveAuthorityState } from '../domain/liveAuthority';
import { createSharedPollingStore } from '../lib/sharedPollingStore';
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

// Mock fallback so the page always renders if the backend URL is unset or every
// attempt fails. NOT real scoring — clearly marked mock.
const MOCK_SNAPSHOT: MarketRegimeSnapshot = {
  status: 'mock',
  asOf: '',
  engineVersion: 'regime-v1',
  regime: {
    label: 'CAUTIOUS',
    growthValueAxis: -0.2,
    riskDurationAxis: -0.15,
    summaryJa: '方向感は限定的で、慎重なスタンス（mock）。',
    confidence: 0.2,
  },
  ratesBackdrop: {
    us10y: 4.42, us2y: 4.65, real10y: 1.85, vix: 17.4, hyOas: 3.1,
    posture: 'neutral', rationaleJa: '金利・VIX・信用スプレッドはおおむね中立圏（mock）。',
  },
  rotationGroups: [
    { id: 'us-growth', label: 'US Growth', assets: ['QQQ', 'XLK'], role: 'Risk', score: -0.3, momentum1d: null, momentum5d: null, momentum20d: null, status: 'outflow', available: true, rationaleJa: 'US Growth から資金流出の傾向（mock）。' },
    { id: 'defensive', label: 'Defensive / Gold', assets: ['XLU', 'GLD'], role: 'Defensive', score: 0.35, momentum1d: null, momentum5d: null, momentum20d: null, status: 'inflow', available: true, rationaleJa: 'Defensive / Gold に資金流入の傾向（mock）。' },
    { id: 'duration', label: 'Duration / Bonds', assets: ['TLT'], role: 'Duration', score: 0.1, momentum1d: null, momentum5d: null, momentum20d: null, status: 'neutral', available: true, rationaleJa: 'Duration / Bonds は中立（mock）。' },
  ],
  topRotations: [
    { label: 'Growth -> Defensive', direction: 'outflow', score: 0.65, evidenceJa: 'グロースからディフェンシブへ資金がシフト（mock）。' },
  ],
  matrix: {
    x: -0.2, y: -0.15, xLabel: 'Growth vs Defensive', yLabel: 'Risk vs Duration',
    points: [
      { label: 'US Growth', x: 0.2, y: 0.3 },
      { label: 'Defensive / Gold', x: -0.4, y: -0.1 },
      { label: 'Duration / Bonds', x: -0.5, y: -0.6 },
    ],
    rationaleJa: '横軸グロース対ディフェンシブ、縦軸リスク対デュレーション（mock）。',
  },
  supportingEvidence: ['mock fallback — backend unavailable.'],
  sourceStatuses: { fred: 'mock', twelveData: 'unavailable', jquants: 'unavailable', manualFallback: 'mock' },
  dataLimitations: [
    'Mock fallback — the live regime engine was unreachable.',
    'ETF rotation is a proxy for capital flow, not direct capital flow.',
  ],
};

const MAX_ATTEMPTS = 3;
const ATTEMPT_TIMEOUT_MS = 9_000;
const RETRY_DELAYS_MS = [3_000, 6_000];
const REFRESH_INTERVAL_MS = 60_000;

function sleep(ms: number): Promise<void> {
  return new Promise((res) => setTimeout(res, ms));
}

const INITIAL_STATE: State = {
  data: null, error: null, loading: true, phase: 'connecting', attempt: 0,
  authority: 'unavailable',
};

const marketRegimeStore = createSharedPollingStore<State>(
  INITIAL_STATE,
  (setState, getState) => {
    const backend = import.meta.env.VITE_ARGUS_BACKEND_URL;
    if (!backend) {
      setState({ data: MOCK_SNAPSHOT, error: null, loading: false, phase: 'mock',
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

    // The shared store intentionally retains its snapshot with zero subscribers.
    // Revalidate it synchronously on remount so an expired value is never exposed
    // during the first asynchronous refresh, and re-arm its evidence deadline.
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

export function useMarketRegime(): State {
  return useSyncExternalStore(
    marketRegimeStore.subscribe, marketRegimeStore.getSnapshot,
    marketRegimeStore.getSnapshot);
}
