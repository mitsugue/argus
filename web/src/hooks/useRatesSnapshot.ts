import { useSyncExternalStore } from 'react';
import { exactAuthorityEpoch } from '../domain/liveAuthority';
import {
  deauthorizeRatePoint, ratePointDecisionExpiresAt, ratePointDecisionUsable,
} from '../domain/rateAuthority';
import { createSharedPollingStore } from '../lib/sharedPollingStore';

// Mirrors the shape returned by /api/argus/rates (scanner.py). Kept in
// sync with the backend by convention — if backend fields change, update
// this type too.

export type FredStatus = 'live' | 'delayed' | 'stale' | 'unavailable' | 'mock';

export interface FredSeriesPoint {
  seriesId: string;
  label: string;
  latestValue: number | null;
  previousValue: number | null;
  change: number | null;
  changeBp: number | null;
  latestDate: string | null;
  status: FredStatus;
  sourceTimestamp?: string | null;
  observedAt?: string | null;
  receivedAt?: string | null;
  knownAt?: string | null;
  source?: string | null;
  selectedProvider?: string | null;
  freshness?: 'FRESH' | 'DELAYED' | 'STALE' | 'UNAVAILABLE' | string;
  completeness?: 'COMPLETE' | 'PARTIAL' | 'MISSING' | string;
  decisionUsable?: boolean;
}

export type RatesPressureLabel = 'High' | 'Medium' | 'Neutral' | 'Relief';
export type RiskVolatilityLabel = 'High' | 'Medium' | 'Low';

export interface RatesSnapshot {
  us10y:          FredSeriesPoint;
  us2y:           FredSeriesPoint;
  usReal10y:      FredSeriesPoint;
  vix:            FredSeriesPoint;
  /** USD/JPY (FRED DEXJPUS, daily). Additive v10.0 — Portfolio Exposure's
      JPY conversion. Optional so older cached payloads still typecheck. */
  usdJpy?:        FredSeriesPoint;
  hyOas?:         FredSeriesPoint;
  ratesPressure:  RatesPressureLabel;
  riskVolatility: RiskVolatilityLabel;
  summary:        string;
  status:         'live' | 'partial' | 'mock' | string;
  freshness?:     string;
  completeness?:  string;
  missingSeries?: string[];
}

// Mock fallback used when VITE_ARGUS_BACKEND_URL is unset (e.g. local
// development with no .env) or when the backend call fails for any
// reason. Matches the backend's _FRED_MOCK constants so dev and prod
// look the same shape.
const todayIso = new Date().toISOString().slice(0, 10);
function mkMock(seriesId: string, label: string, latest: number, prev: number): FredSeriesPoint {
  const change = +(latest - prev).toFixed(4);
  return {
    seriesId,
    label,
    latestValue: latest,
    previousValue: prev,
    change,
    changeBp: +(change * 100).toFixed(1),
    latestDate: todayIso,
    status: 'mock',
  };
}
const MOCK_SNAPSHOT: RatesSnapshot = {
  us10y:     mkMock('DGS10',  'US 10Y Treasury yield', 4.42, 4.30),
  us2y:      mkMock('DGS2',   'US 2Y Treasury yield',  4.65, 4.60),
  usReal10y: mkMock('DFII10', 'US 10Y real yield',     1.85, 1.82),
  vix:       mkMock('VIXCLS', 'VIX',                   17.4, 17.0),
  // The mock 10Y change of +12 bps lands in the spec's "High" pressure
  // bucket; VIX 17.4 lands in the "Low" volatility bucket.
  ratesPressure:  'High',
  riskVolatility: 'Low',
  summary:        '10Y 4.42% (+12bp), VIX 17.4. Pressure: High, Vol: Low.',
  status:         'mock',
};

// Connection phase, surfaced to the UI so a cold-starting backend reads
// as "connecting" rather than snapping straight to "mock":
//   connecting — a fetch attempt is in flight (incl. retries)
//   live       — backend answered with live FRED data
//   mock       — backend answered with mock data, OR all attempts failed
export type ConnPhase = 'connecting' | 'live' | 'partial' | 'mock';

export interface RatesState {
  data: RatesSnapshot | null;
  error: string | null;
  loading: boolean;
  phase: ConnPhase;
  // 1-based attempt counter, so the UI can show "waking backend · try 2".
  attempt: number;
  authority: 'fresh' | 'expired' | 'invalid' | 'unavailable' | 'refresh_failed';
}

// Render's free tier spins the backend down when idle; the first request
// after a sleep can take 30–60s while the dyno wakes. Rather than fall
// back to mock on that first miss, we retry a couple of times with a per-
// attempt timeout, staying in the "connecting" phase, and only settle on
// mock once every attempt is exhausted.
const MAX_ATTEMPTS = 3; // initial + 2 retries
const ATTEMPT_TIMEOUT_MS = 8_000; // abort a hung attempt so we can retry
const RETRY_DELAYS_MS = [3_000, 6_000]; // wait before attempt 2, then 3

function sleep(ms: number): Promise<void> {
  return new Promise((res) => setTimeout(res, ms));
}

const RATE_KEYS = ['us10y', 'us2y', 'usReal10y', 'vix', 'usdJpy', 'hyOas'] as const;

function pointAuthority(point: FredSeriesPoint | undefined, nowMs: number): RatesState['authority'] {
  if (!point) return 'unavailable';
  const deadline = ratePointDecisionExpiresAt(point);
  const knownAt = exactAuthorityEpoch(point.knownAt);
  if (deadline == null || knownAt == null || knownAt > nowMs) return 'invalid';
  return nowMs <= deadline ? 'fresh' : 'expired';
}

/** Retain diagnostics, but strip every rate number whose canonical source-time
 * proof is not currently decision-usable. */
export function projectRatesSnapshot(data: RatesSnapshot, nowMs = Date.now()): RatesSnapshot {
  const projected = { ...data };
  let usableCount = 0;
  for (const key of RATE_KEYS) {
    const point = data[key];
    if (!point) continue;
    if (ratePointDecisionUsable(point, nowMs)) {
      projected[key] = { ...point, decisionUsable: true };
      usableCount += 1;
    } else {
      projected[key] = deauthorizeRatePoint(point);
    }
  }
  const presentCount = RATE_KEYS.filter((key) => data[key] != null).length;
  return {
    ...projected,
    status: usableCount === presentCount && data.status === 'live'
      ? 'live' : usableCount > 0 ? 'partial' : 'mock',
    freshness: usableCount > 0 ? data.freshness ?? 'delayed' : 'unavailable',
    completeness: usableCount === presentCount ? data.completeness ?? 'complete'
      : usableCount > 0 ? 'partial' : 'missing',
  };
}

const INITIAL_STATE: RatesState = {
  data: null, error: null, loading: true, phase: 'connecting', attempt: 0,
  authority: 'unavailable',
};

const ratesStore = createSharedPollingStore<RatesState>(
  INITIAL_STATE,
  (setState, getState) => {
    const backend = import.meta.env.VITE_ARGUS_BACKEND_URL as string | undefined;
    let cancelled = false;
    let acquisition: Promise<void> | null = null;
    let cancelExpiry = () => {};
    const controllers = new Set<AbortController>();

    function acquire(task: () => Promise<void>) {
      if (acquisition) return acquisition;
      const current = task().finally(() => {
        if (acquisition === current) acquisition = null;
      });
      acquisition = current;
      return current;
    }

    function accept(raw: RatesSnapshot, attempt: number) {
      cancelExpiry();
      const nowMs = Date.now();
      const data = projectRatesSnapshot(raw, nowMs);
      const authority = pointAuthority(raw.usdJpy, nowMs);
      const phase: ConnPhase = data.status === 'live' ? 'live'
        : data.status === 'partial' ? 'partial' : 'mock';
      setState({ data, error: null, loading: false, phase, attempt, authority });

      const futureDeadlines = RATE_KEYS.map((key) => raw[key])
        .filter((point): point is FredSeriesPoint => !!point)
        .filter((point) => ratePointDecisionUsable(point, nowMs))
        .map((point) => ratePointDecisionExpiresAt(point))
        .filter((deadline): deadline is number => deadline != null && deadline >= nowMs);
      if (!futureDeadlines.length) return;
      const deadline = Math.min(...futureDeadlines);
      const handle = window.setTimeout(
        () => accept(raw, attempt),
        Math.min(Math.max(1, deadline - Date.now() + 1), 2_147_000_000),
      );
      cancelExpiry = () => window.clearTimeout(handle);
    }

    function failRefresh(message: string, loading: boolean) {
      cancelExpiry();
      const current = getState();
      setState({
        ...current,
        data: current.data ? projectRatesSnapshot({
          ...current.data,
          ...Object.fromEntries(RATE_KEYS.map((key) => [key,
            current.data?.[key] ? deauthorizeRatePoint(current.data[key]!) : undefined])),
        }, Date.now()) : null,
        error: message,
        loading,
        phase: current.data ? 'partial' : 'connecting',
        authority: 'refresh_failed',
      });
    }

    if (!backend) {
      accept(MOCK_SNAPSHOT, 0);
      return () => { cancelled = true; cancelExpiry(); };
    }
    const url = backend.replace(/\/$/, '') + '/api/argus/rates';

    async function fetchSnapshot(): Promise<RatesSnapshot> {
      const ctrl = new AbortController();
      controllers.add(ctrl);
      const timer = window.setTimeout(() => ctrl.abort(), ATTEMPT_TIMEOUT_MS);
      try {
        const response = await fetch(url, { signal: ctrl.signal });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return await response.json() as RatesSnapshot;
      } finally {
        window.clearTimeout(timer);
        controllers.delete(ctrl);
      }
    }

    async function run() {
      for (let attempt = 1; attempt <= MAX_ATTEMPTS; attempt++) {
        if (cancelled) return;
        setState((state) => ({ ...state, phase: 'connecting', loading: true,
          attempt, error: null }));
        try {
          const data = await fetchSnapshot();
          if (!cancelled) accept(data, attempt);
          return;
        } catch (error: unknown) {
          if (cancelled) return;
          const message = error instanceof Error ? error.message : String(error);
          failRefresh(message, attempt < MAX_ATTEMPTS);
          if (attempt < MAX_ATTEMPTS) {
            await sleep(RETRY_DELAYS_MS[attempt - 1] ?? 6_000);
            continue;
          }
          setState((state) => ({ ...state, data: projectRatesSnapshot(MOCK_SNAPSHOT),
            loading: false, phase: 'mock', attempt, authority: 'unavailable' }));
          return;
        }
      }
    }

    async function refresh() {
      if (cancelled || document.hidden) return;
      try {
        const data = await fetchSnapshot();
        if (!cancelled) accept(data, getState().attempt);
      } catch (error: unknown) {
        if (!cancelled) failRefresh(
          error instanceof Error ? error.message : String(error), false);
      }
    }

    const retained = getState();
    if (retained.data && retained.authority === 'fresh') {
      accept(retained.data, retained.attempt);
    }
    const interval = window.setInterval(() => void acquire(refresh), 60_000);
    const onVisible = () => {
      if (document.hidden) return;
      const current = getState();
      if (current.data) accept(current.data, current.attempt);
      void acquire(refresh);
    };
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

/**
 * Snapshot of US rates + VIX, normalized to action-relevant signals.
 *
 * Source of truth is the backend `/api/argus/rates` endpoint, which
 * wraps FRED. If `VITE_ARGUS_BACKEND_URL` is unset the hook serves the
 * mock snapshot immediately. Otherwise it attempts the fetch up to
 * MAX_ATTEMPTS times (covering Render cold starts), staying in the
 * `connecting` phase between tries, and only falls back to the mock
 * snapshot (`phase === "mock"`) once every attempt has failed. The UI
 * can surface `phase`/`attempt` so reviewers always know which mode
 * they're in — live, connecting, or mock.
 */
export function useRatesSnapshot(): RatesState {
  return useSyncExternalStore(
    ratesStore.subscribe, ratesStore.getSnapshot, ratesStore.getSnapshot);
}
