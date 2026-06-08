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

interface State {
  data: RatesSnapshot | null;
  error: string | null;
  loading: boolean;
}

/**
 * Snapshot of US rates + VIX, normalized to action-relevant signals.
 *
 * Source of truth is the backend `/api/argus/rates` endpoint, which
 * wraps FRED. If `VITE_ARGUS_BACKEND_URL` is unset, OR the backend
 * is unreachable, OR FRED itself returns nothing, the hook falls back
 * to the mock snapshot above with `status === "mock"`. The UI can
 * surface that status so reviewers always know which mode they're in.
 */
export function useRatesSnapshot(): State {
  const [state, setState] = useState<State>({
    data: null,
    error: null,
    loading: true,
  });

  useEffect(() => {
    const backend = import.meta.env.VITE_ARGUS_BACKEND_URL;
    if (!backend) {
      setState({ data: MOCK_SNAPSHOT, error: null, loading: false });
      return;
    }
    const url = backend.replace(/\/$/, '') + '/api/argus/rates';
    let cancelled = false;
    const ctrl = new AbortController();
    fetch(url, { signal: ctrl.signal })
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json() as Promise<RatesSnapshot>;
      })
      .then((data) => {
        if (cancelled) return;
        setState({ data, error: null, loading: false });
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        const msg = err instanceof Error ? err.message : String(err);
        setState({ data: MOCK_SNAPSHOT, error: msg, loading: false });
      });
    return () => {
      cancelled = true;
      ctrl.abort();
    };
  }, []);

  return state;
}
