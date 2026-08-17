import { useEffect, useState } from 'react';
import type { MarketRegimeSnapshot } from '../types/marketRegime';

export type RegimePhase = 'connecting' | 'live' | 'partial' | 'mock';

interface State {
  data: MarketRegimeSnapshot | null;
  error: string | null;
  loading: boolean;
  phase: RegimePhase;
  attempt: number;
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

function sleep(ms: number): Promise<void> {
  return new Promise((res) => setTimeout(res, ms));
}

export function useMarketRegime(): State {
  const [state, setState] = useState<State>({
    data: null, error: null, loading: true, phase: 'connecting', attempt: 0,
  });

  useEffect(() => {
    const backend = import.meta.env.VITE_ARGUS_BACKEND_URL;
    if (!backend) {
      setState({ data: MOCK_SNAPSHOT, error: null, loading: false, phase: 'mock', attempt: 0 });
      return;
    }
    const url = backend.replace(/\/$/, '') + '/api/argus/market-regime';
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
          const data = (await r.json()) as MarketRegimeSnapshot;
          if (cancelled) return;
          const phase: RegimePhase = data.status === 'live' ? 'live' : data.status === 'partial' ? 'partial' : 'mock';
          setState({ data, error: null, loading: false, phase, attempt });
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
          setState({ data: MOCK_SNAPSHOT, error: msg, loading: false, phase: 'mock', attempt });
          return;
        }
      }
    }

    void run();
    return () => { cancelled = true; };
  }, []);

  return state;
}
