import { useEffect, useState } from 'react';

// Cause Attribution (cause-attribution-v1, v10.117). For a material move, the
// backend returns an integrity-checked cause stack: immediate trigger (or none),
// cause probabilities (sum to 1, UNKNOWN non-zero), contagion scope, positioning
// probabilities (no named institution), and what would change the conclusion.

export interface CauseStack {
  schemaVersion: string;
  symbol: string;
  market: string;
  changePct: number | null;
  asOf: string;
  immediateTrigger: { cause: string; confidence: number; evidenceIds: string[] } | null;
  causeProbabilities: Record<string, number>;
  alternativeExplanations: { cause: string; probability: number }[];
  unknownShare: number;
  overallConfidence: number;
  contagion: { scope: string; peersDown?: number; peersTotal?: number; noteJa?: string };
  positioning: { probabilities: Record<string, number>; noteJa?: string };
  preEvent: {
    preEventDeRiskingProbability: number;
    badResultConfirmed: boolean;
    actionOverride: string;
    nextEvidenceRequired: string;
  };
  dataLimitations: string[];
  noteJa: string;
}

interface State { data: CauseStack | null; loading: boolean; }

export function useCauseAttribution(symbol: string | null, market = 'JP'): State {
  const [state, setState] = useState<State>({ data: null, loading: !!symbol });
  useEffect(() => {
    const backend = import.meta.env.VITE_ARGUS_BACKEND_URL;
    if (!backend || !symbol) { setState({ data: null, loading: false }); return; }
    const url = `${backend.replace(/\/$/, '')}/api/argus/cause-attribution?symbol=${encodeURIComponent(symbol)}&market=${market}`;
    let cancelled = false;
    (async () => {
      const ctrl = new AbortController();
      const t = setTimeout(() => ctrl.abort(), 15_000);
      try {
        const r = await fetch(url, { signal: ctrl.signal });
        clearTimeout(t);
        if (!r.ok || cancelled) return;
        const d = (await r.json()) as CauseStack;
        if (!cancelled && d.schemaVersion === 'cause-attribution-v1') setState({ data: d, loading: false });
        else if (!cancelled) setState({ data: null, loading: false });
      } catch { clearTimeout(t); if (!cancelled) setState((s) => ({ ...s, loading: false })); }
    })();
    return () => { cancelled = true; };
  }, [symbol, market]);
  return state;
}
