import { useEffect, useState } from 'react';

// Mirrors the shape returned by /api/argus/rates (scanner.py). Kept in
// sync with the backend by convention — if backend fields change, update
// this type too.

export type FredStatus = 'live' | 'mock';

export interface FredSeriesPoint {
  seriesId: string;
  label: string;
  latestValue: number;
  previousValue: number;
  change: number;
  changeBp: number;
  latestDate: string;
  status: FredStatus;
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
  ratesPressure:  RatesPressureLabel;
  riskVolatility: RiskVolatilityLabel;
  summary:        string;
  status:         FredStatus;
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
export type ConnPhase = 'connecting' | 'live' | 'mock';

interface State {
  data: RatesSnapshot | null;
  error: string | null;
  loading: boolean;
  phase: ConnPhase;
  // 1-based attempt counter, so the UI can show "waking backend · try 2".
  attempt: number;
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
export function useRatesSnapshot(): State {
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
    const url = backend.replace(/\/$/, '') + '/api/argus/rates';
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
          const data = (await r.json()) as RatesSnapshot;
          if (cancelled) return;
          // Trust the payload's own status: a 200 can still carry mock
          // data if FRED failed on the backend side.
          setState({ data, error: null, loading: false, phase: data.status, attempt });
          return;
        } catch (err: unknown) {
          clearTimeout(timer);
          if (cancelled) return;
          const msg = err instanceof Error ? err.message : String(err);
          if (attempt < MAX_ATTEMPTS) {
            // Stay in "connecting" and wait before the next attempt.
            setState((s) => ({ ...s, error: msg, phase: 'connecting', loading: true, attempt }));
            await sleep(RETRY_DELAYS_MS[attempt - 1] ?? 6_000);
            continue;
          }
          // Every attempt exhausted → settle on the mock snapshot.
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
