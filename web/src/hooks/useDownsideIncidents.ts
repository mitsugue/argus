import { useEffect, useState } from 'react';

// Downside Incident Response (downside-v1, v10.98) — when a held/watched name
// drops materially, the backend classifies the incident (cause buckets, action
// override, missing data, next condition) so the UI never shows a bare "急落".
// Refreshes every 60s while visible (server caches 60s).

export interface CauseBucket {
  cause: string;
  probability: number;   // 0..1, buckets sum to 1
  evidenceIds: string[];
}

export interface DownsideIncident {
  incidentId: string;
  symbol: string;
  market: 'JP' | 'US' | string;
  assetName: string;
  changePct: number | null;
  incidentType: string;
  severity: 'low' | 'medium' | 'high' | 'critical';
  holderImpact: string;
  currentAction: string;
  actionOverride: string;
  causeBuckets: CauseBucket[];
  reasonJa: string;
  missingData: string[];
  nextConditionJa: string;
  doNotDoJa: string;
  nextReviewAt: string | null;
  isHeld: boolean;
  ownerState?: string;       // watch | active | held | protected | null
  priority?: string;         // low | normal | high
  status: 'live' | 'partial';
  dedupKey?: string;
}

export interface JpOverlay {
  globalRegime: string;
  jpIntradayOverlay: 'NORMAL' | 'CAUTION' | 'RISK_OFF_WATCH' | string;
  holderRiskOverlay: 'NONE' | 'REVIEW_REQUIRED' | string;
  flags: string[];
  displayJa: string;
  reasonJa: string;
}

export interface DownsideSnapshot {
  status: 'live' | 'partial';
  asOf: string;
  engineVersion: string;
  incidents: DownsideIncident[];
  activeCount: number;
  ownerAffected: boolean;
  globalRegime: string;
  jpIntradayOverlay: string;
  holderRiskOverlay: string;
  overlay: JpOverlay;
  dataLimitations: string[];
  noteJa: string;
}

const REFRESH_INTERVAL_MS = 60_000;

interface State {
  data: DownsideSnapshot | null;
  loading: boolean;
}

export function useDownsideIncidents(): State {
  const [state, setState] = useState<State>({ data: null, loading: true });

  useEffect(() => {
    const backend = import.meta.env.VITE_ARGUS_BACKEND_URL;
    if (!backend) {
      setState({ data: null, loading: false });
      return;
    }
    const url = backend.replace(/\/$/, '') + '/api/argus/downside-incidents';
    let cancelled = false;

    async function fetchOnce() {
      if (cancelled || document.hidden) return;
      const ctrl = new AbortController();
      const timer = setTimeout(() => ctrl.abort(), 12_000);
      try {
        const r = await fetch(url, { signal: ctrl.signal });
        clearTimeout(timer);
        if (!r.ok || cancelled) return;
        const data = (await r.json()) as DownsideSnapshot;
        if (!cancelled) setState({ data, loading: false });
      } catch {
        clearTimeout(timer);
        if (!cancelled) setState((s) => ({ ...s, loading: false }));
      }
    }

    void fetchOnce();
    const t = setInterval(() => void fetchOnce(), REFRESH_INTERVAL_MS);
    const onVisible = () => { if (!document.hidden) void fetchOnce(); };
    document.addEventListener('visibilitychange', onVisible);
    return () => {
      cancelled = true;
      clearInterval(t);
      document.removeEventListener('visibilitychange', onVisible);
    };
  }, []);

  return state;
}
