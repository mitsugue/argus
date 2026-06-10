import { useEffect, useState } from 'react';

// Running accuracy summary written by the prediction-ledger GitHub Action to
// the repo's `ledger` BRANCH (public, versioned, no backend involved). 404
// until the first scored day exists — callers hide the section gracefully.

export interface LedgerAgg {
  days: number;
  n: number;
  hitRate: number | null;
  brierMean: number | null;
}

export interface LedgerSummary {
  updated: string;
  engineVersion: string;
  overall: LedgerAgg | null;
  byPosture: Record<string, LedgerAgg>;
  byVixZone: Record<string, LedgerAgg>;
  aiDirectional: { n: number; hits: number; hitRate: number | null };
  /** ledger-v2 (v10.5): asset-class calibration + the posture call's record. */
  classes?: { n: number; hits: number; hitRate: number | null; brierMean: number | null;
              byClass: Record<string, { n: number; hits: number; hitRate: number | null }> };
  posture?: { n: number; hits: number; hitRate: number | null;
              byPosture: Record<string, { n: number; hits: number; hitRate: number | null }> };
  noteJa: string;
}

const LEDGER_URL = 'https://raw.githubusercontent.com/mitsugue/argus/ledger/ledger/summary.json';

interface State {
  data: LedgerSummary | null;
  loading: boolean;
}

export function useLedgerSummary(): State {
  const [state, setState] = useState<State>({ data: null, loading: true });

  useEffect(() => {
    let cancelled = false;
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 8_000);
    (async () => {
      try {
        const r = await fetch(`${LEDGER_URL}?cb=${Date.now()}`, { signal: ctrl.signal });
        clearTimeout(timer);
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const data = (await r.json()) as LedgerSummary;
        if (!cancelled) setState({ data, loading: false });
      } catch {
        clearTimeout(timer);
        if (!cancelled) setState({ data: null, loading: false });
      }
    })();
    return () => { cancelled = true; clearTimeout(timer); };
  }, []);

  return state;
}
