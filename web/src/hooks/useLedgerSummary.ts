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
  /** ledger-v3 (v10.9): 3-layer × 1/3/5-trading-day horizons. */
  layers?: Record<string, { byHorizon: Record<string, {
    n: number; hits: number; hitRate: number | null; brierMean: number | null; days: number;
  }> }>;
  noteJa: string;
}

/** closepin-v1 (v10.11): same-day 14:30-pin → 15:30-close scoring. */
export interface ClosepinSummary {
  updated: string;
  overall: { days: number; n: number; hitRate: number | null; brierMean: number | null } | null;
  byPosture: Record<string, { days: number; n: number; hitRate: number | null; brierMean: number | null }>;
  byLayer: Record<string, { n: number; hits: number; hitRate: number | null }>;
  byMember: Record<string, { n: number; hits: number; hitRate: number | null }>;
  noteJa: string;
}

const LEDGER_URL = 'https://raw.githubusercontent.com/mitsugue/argus/ledger/ledger/summary.json';
const CLOSEPIN_URL = 'https://raw.githubusercontent.com/mitsugue/argus/ledger/ledger/closepin/summary.json';

interface State {
  data: LedgerSummary | null;
  closepin: ClosepinSummary | null;
  loading: boolean;
}

export function useLedgerSummary(): State {
  const [state, setState] = useState<State>({ data: null, closepin: null, loading: true });

  useEffect(() => {
    let cancelled = false;
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 8_000);
    const grab = async <T,>(url: string): Promise<T | null> => {
      try {
        const r = await fetch(`${url}?cb=${Date.now()}`, { signal: ctrl.signal });
        return r.ok ? ((await r.json()) as T) : null;   // 404 until first data
      } catch { return null; }
    };
    (async () => {
      const [data, closepin] = await Promise.all([
        grab<LedgerSummary>(LEDGER_URL), grab<ClosepinSummary>(CLOSEPIN_URL)]);
      clearTimeout(timer);
      if (!cancelled) setState({ data, closepin, loading: false });
    })();
    return () => { cancelled = true; clearTimeout(timer); };
  }, []);

  return state;
}
