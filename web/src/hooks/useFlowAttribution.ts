import { useEffect, useState } from 'react';

// V11.7.0 Big Money / Flow Attribution — evidence-based classification of WHO is
// likely behind a move (大口買い集め/買い戻し/個人追随/売り抜け/狼狽…), always in
// 可能性/推定 vocabulary. Direct evidence is separated from inference and the
// missing evidence is always visible. Context only — NEVER a trade instruction.

export interface FlowAttribution {
  schemaVersion: string;
  id: string;
  symbol: string;
  market: string;
  name?: string;
  asOf: string;
  changePct: number | null;
  volumeRatio: number | null;
  flowClass: string;
  flowClassJa: string;
  direction: 'inflow' | 'outflow' | 'mixed' | 'neutral' | 'unknown';
  confidence: number;
  evidenceScore: number;
  riskScore: number;
  directness: 'direct_evidence' | 'inferred' | 'weak_context' | 'insufficient';
  directnessJa: string;
  evidence: Record<string, string | null>;
  missingEvidence: string[];
  reasonCodes: string[];
  ownerReadableWhyJa: string;
  checkNextJa: string;
  actionImplication: 'investigate' | 'wait_for_confirmation' | 'avoid_chase'
    | 'monitor' | 'caution' | 'no_action';
  actionImplicationJa: string;
  sourceLimitNote: string;
  complianceNote: string;
}

export const FLOW_TONE: Record<string, string> = {
  inflow: 'var(--value-positive)', outflow: 'var(--value-negative)',
  mixed: 'var(--amber, #fbbf24)', neutral: 'var(--text-muted)', unknown: 'var(--text-faint)',
};
export const ACTION_TONE: Record<string, string> = {
  avoid_chase: 'var(--value-negative)', caution: 'var(--value-negative)',
  investigate: 'var(--accent)', wait_for_confirmation: 'var(--amber, #fbbf24)',
  monitor: 'var(--text-muted)', no_action: 'var(--text-faint)',
};

interface ListState { records: FlowAttribution[]; loading: boolean; }

/** Today's material watchlist movers, classified (cached-only backend; 5-min poll). */
export function useFlowAttributionList(): ListState {
  const [state, setState] = useState<ListState>({ records: [], loading: true });
  useEffect(() => {
    const backend = import.meta.env.VITE_ARGUS_BACKEND_URL as string | undefined;
    if (!backend) { setState({ records: [], loading: false }); return; }
    let alive = true;
    const load = () => {
      fetch(`${backend.replace(/\/$/, '')}/api/argus/flow-attribution`)
        .then((r) => r.json())
        .then((d) => {
          if (!alive) return;
          setState({ records: (d.records ?? []) as FlowAttribution[], loading: false });
        })
        .catch(() => { if (alive) setState((s) => ({ ...s, loading: false })); });
    };
    load();
    const iv = setInterval(load, 5 * 60_000);
    return () => { alive = false; clearInterval(iv); };
  }, []);
  return state;
}
