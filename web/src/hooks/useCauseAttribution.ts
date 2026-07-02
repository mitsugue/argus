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
  news?: {
    time?: string | null; titleJa: string; source?: string; cls: NewsClass; sentiment?: string | null;
    // v11.5.1: Japanese-first display fields (displayTitleJa is never raw English).
    displayTitleJa?: string; titleOriginal?: string;
    translationStatus?: 'translated' | 'not_needed' | 'pending' | 'failed';
    assoc?: { via: string; term?: string; relationJa?: string; corroboration?: string };  // association link (v10.183)
  }[];
  explanationJa?: string;   // cached AI explanation (v11.3.3: admin-generated only)
  explanationStatus?: 'cached' | 'not_generated' | 'pending' | 'disabled' | 'budget_limited' | 'error';
  explanationGeneratedAt?: string | null;
  unverifiedAssumptions?: string[];
  whatWouldConfirmJa?: string;
  whatWouldRefuteJa?: string;
  explanationNoteJa?: string;
  /** Mover Cause ladder (v11.3.3; freshness/marketConfirmation added v11.3.4). */
  moverCause?: {
    causeStatus?: string; causeStatusJa?: string;
    bestLeadJa?: string; whyNotConfirmedJa?: string; checkedJa?: string;
    nextChecksJa?: string[]; impactCommentJa?: string; confidence?: number;
    explanationJa?: string | null;
    explanationStatus?: 'cached' | 'pending' | 'not_generated';
    freshness?: { lastEvidenceRefreshAt?: string; evidenceAgeSec?: number; isStale?: boolean;
                  staleReasonJa?: string; nextAutoCheckAt?: string | null };
    marketConfirmation?: { status?: string; volumeRatio?: number | null;
                           relativeToIndexPct?: number | null; peerBasketMovePct?: number | null;
                           vwapDistancePct?: number | null; window?: string };
    topCandidates?: { titleJa?: string; category?: string; timingRelation?: string;
                      corroborationLevel?: string; confidence?: number; source?: string }[];
  };
}

export type NewsClass = 'CONFIRMED' | 'LIKELY_RELATED' | 'BACKGROUND' | 'UNCONFIRMED';

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
