import { useEffect, useState } from 'react';
import type { CatalystsSnapshot } from '../types/catalysts';

export type ConnPhase = 'connecting' | 'live' | 'partial' | 'mock';

interface State {
  data: CatalystsSnapshot | null;
  error: string | null;
  loading: boolean;
  phase: ConnPhase;
  attempt: number;
}

const MOCK_SNAPSHOT: CatalystsSnapshot = {
  status: 'mock', asOf: '', engineVersion: 'catalyst-v1', horizonDays: 90,
  sources: [
    { name: 'SEC EDGAR', status: 'unavailable' },
    { name: 'Finnhub', status: 'unavailable' },
    { name: 'J-Quants', status: 'unavailable' },
    { name: 'TDnet Add-on', status: 'pending_addon' },
  ],
  items: [],
};

const MAX_ATTEMPTS = 3;
const ATTEMPT_TIMEOUT_MS = 8_000;
const RETRY_DELAYS_MS = [3_000, 6_000];

function sleep(ms: number): Promise<void> {
  return new Promise((res) => setTimeout(res, ms));
}

/**
 * Corporate Catalyst Layer from `/api/argus/catalysts` (engine v1) — company-
 * specific earnings/filings/news/disclosures. Read-only, frontend-safe. Falls
 * back to MOCK_SNAPSHOT when the backend is unset or every attempt fails.
 */
export function useCatalysts(): State {
  const [state, setState] = useState<State>({
    data: null, error: null, loading: true, phase: 'connecting', attempt: 0,
  });

  useEffect(() => {
    const backend = import.meta.env.VITE_ARGUS_BACKEND_URL;
    if (!backend) {
      setState({ data: MOCK_SNAPSHOT, error: null, loading: false, phase: 'mock', attempt: 0 });
      return;
    }
    const url = backend.replace(/\/$/, '') + '/api/argus/catalysts';
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
          const data = (await r.json()) as CatalystsSnapshot;
          if (cancelled) return;
          setState({ data, error: null, loading: false, phase: data.status, attempt });
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
