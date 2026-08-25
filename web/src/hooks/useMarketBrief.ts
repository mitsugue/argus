// v13.5.34 — MARKET SITUATION BRIEF (Today-top NOW/WHY/NEXT card).
// Read-only evidence for the human reader; sdaAuthority is false by
// construction and nothing here feeds the decision engine.
import React from 'react';

export interface MarketBriefFact {
  text: string;
  priority: 'P0' | 'P1' | 'P2' | 'P3';
  source: string;
  verification: 'VERIFIED' | 'CORROBORATED' | 'UNCONFIRMED';
}

export interface MarketBrief {
  schemaVersion: string;
  generatedAt: string;
  hasCritical?: boolean;
  now: string;
  why: string;
  next: string;
  aiText: { nowJa: string; whyJa: string; nextJa: string } | null;
  aiModel: string | null;
  chips: { chart: string; news: string; nextEvent: string; mainRisk: string };
  facts: MarketBriefFact[];
  noteJa: string;
  sdaAuthority: false;
  status?: string;
}

const REFRESH_MS = 5 * 60 * 1000;

function baseUrl() {
  return (import.meta.env.VITE_ARGUS_BACKEND_URL as string | undefined)
    ?.replace(/\/$/, '') ?? null;
}

export function useMarketBrief(): { brief: MarketBrief | null; error: boolean } {
  const [brief, setBrief] = React.useState<MarketBrief | null>(null);
  const [error, setError] = React.useState(false);
  React.useEffect(() => {
    let cancelled = false;
    const base = baseUrl();
    if (!base) { setError(true); return undefined; }
    const load = async () => {
      try {
        const response = await fetch(`${base}/api/argus/market-brief`,
          { cache: 'no-store', headers: { Accept: 'application/json' } });
        if (!response.ok) throw new Error(String(response.status));
        const body = await response.json() as MarketBrief;
        if (!cancelled && body && body.schemaVersion) {
          setBrief(body);
          setError(false);
        }
      } catch {
        if (!cancelled) setError(true);
      }
    };
    void load();
    const timer = window.setInterval(() => { void load(); }, REFRESH_MS);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, []);
  return { brief, error };
}
