import { useEffect, useState } from 'react';

// V11.6.0 Institutional Intelligence — formal public-signal records built from the
// C.A.O.S. mesh (backend, cached-only). Context, never trade instructions.

export interface InstitutionalSignal {
  id: string;
  sourceName: string;
  sourceType: string;
  sourceTier: 'primary' | 'high' | 'medium' | 'low';
  region: string;
  publishedAt?: string | null;
  headline: string;
  summary?: string;
  url?: string | null;
  tickers: string[];
  relatedEvents: string[];
  stance: 'bullish' | 'bearish' | 'neutral' | 'mixed' | 'conditional' | 'unknown';
  stanceJa: string;
  claimType: string;
  claimTypeJa: string;
  impactHorizon: string;
  confidence: number;
  importance: number;
  affectedAssets: string[];
  ownerAssetHit: boolean;
  directness: 'direct_cause' | 'related_signal' | 'background' | 'weak_context';
  directnessJa: string;
  headlineOnly: boolean;
  freshness: string;
  ownerReadableWhy: string;
  checkNextJa: string;
  actionImplication: string;
  actionImplicationJa: string;
  complianceNote: string;
}

export interface RegimeTheme { count: number; example?: string | null }

export interface InstitutionalSignalsResponse {
  schemaVersion: string;
  asOf: string;
  count: number;
  signals: InstitutionalSignal[];
  regimeThemes: Record<string, RegimeTheme>;
  disclaimerJa: string;
  disclaimerEn: string;
}

const REFRESH_MS = 5 * 60_000;

export function useInstitutionalSignals(symbol?: string) {
  const [data, setData] = useState<InstitutionalSignalsResponse | null>(null);

  useEffect(() => {
    const backend = import.meta.env.VITE_ARGUS_BACKEND_URL;
    if (!backend) return;
    const url = backend.replace(/\/$/, '') + '/api/argus/institutional-intel/signals'
      + (symbol ? `?symbol=${encodeURIComponent(symbol)}` : '');
    let cancelled = false;

    async function load() {
      if (cancelled || document.hidden) return;
      const ctrl = new AbortController();
      const timer = setTimeout(() => ctrl.abort(), 8_000);
      try {
        const r = await fetch(url, { signal: ctrl.signal });
        clearTimeout(timer);
        if (!r.ok || cancelled) return;
        const d = (await r.json()) as InstitutionalSignalsResponse;
        if (!cancelled) setData(d);
      } catch {
        clearTimeout(timer);
      }
    }

    void load();
    const t = setInterval(() => void load(), REFRESH_MS);
    const onVis = () => { if (!document.hidden) void load(); };
    document.addEventListener('visibilitychange', onVis);
    return () => {
      cancelled = true;
      clearInterval(t);
      document.removeEventListener('visibilitychange', onVis);
    };
  }, [symbol]);

  return { data };
}

// shared chip styling helpers (spec labels: Bullish/Bearish/Mixed/Conditional/
// Background/Direct catalyst/Related signal/Headline-only)
export const STANCE_LABEL: Record<string, string> = {
  bullish: 'Bullish', bearish: 'Bearish', neutral: 'Neutral', mixed: 'Mixed',
  conditional: 'Conditional', unknown: '—',
};
export const STANCE_TONE: Record<string, string> = {
  bullish: 'var(--value-positive, #34d399)', bearish: 'var(--value-negative, #f87171)',
  neutral: 'var(--text-faint)', mixed: 'var(--amber, #fbbf24)',
  conditional: 'var(--amber, #fbbf24)', unknown: 'var(--text-faint)',
};
export const DIRECTNESS_LABEL: Record<string, string> = {
  direct_cause: 'Direct catalyst', related_signal: 'Related signal',
  background: 'Background', weak_context: 'Background',
};
