import { useEffect, useState } from 'react';

// v13.5.1 market-shock view: direct long-end rate sensing plus corroborated
// shock-theme news, classified server-side by the pure materiality engine.
// Read-only cached GET; explicit states, never silent absence.
export interface MarketShockEvent {
  eventId: string;
  eventClass: string;
  severity: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';
  baseSeverity: string;
  headlineJa: string;
  whyJa: string;
  evidence: Record<string, unknown>;
  crossMarket: { confirmed: boolean; signals: string[] };
  sources: Array<{ name: string; kind: string }>;
  asOf: string | null;
}

export interface MarketShockView {
  schemaVersion: string;
  generatedAt?: string;
  status: string;
  eventCount: number;
  events: MarketShockEvent[];
  longEnd?: Record<string, unknown>;
}

export interface MarketShockState {
  status: 'loading' | 'data' | 'error';
  view: MarketShockView | null;
}

let memory: MarketShockView | null = null;
let inflight: Promise<MarketShockView | null> | null = null;

function baseUrl() {
  return (import.meta.env.VITE_ARGUS_BACKEND_URL as string | undefined)
    ?.replace(/\/$/, '') ?? null;
}

async function fetchShock(): Promise<MarketShockView | null> {
  const base = baseUrl();
  if (!base) return null;
  const response = await fetch(`${base}/api/argus/market-shock`, {
    method: 'GET', cache: 'no-store', headers: { Accept: 'application/json' },
  });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  const body = await response.json() as MarketShockView;
  if (body.schemaVersion !== 'argus-market-shock-v1') {
    throw new Error('schema_incompatible');
  }
  return body;
}

export function useMarketShock(): MarketShockState {
  const [state, setState] = useState<MarketShockState>(() => (memory
    ? { status: 'data', view: memory }
    : { status: 'loading', view: null }));
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      if (!inflight) inflight = fetchShock().finally(() => { inflight = null; });
      try {
        const view = await inflight;
        if (!cancelled && view) {
          memory = view;
          setState({ status: 'data', view });
        } else if (!cancelled && !view) {
          setState({ status: 'error', view: memory });
        }
      } catch {
        if (!cancelled) setState({ status: memory ? 'data' : 'error', view: memory });
      }
    })();
    return () => { cancelled = true; };
  }, []);
  return state;
}
