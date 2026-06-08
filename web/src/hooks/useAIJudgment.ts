import { useEffect, useState } from 'react';
import type { AIJudgment } from '../types/aiJudgment';

// connecting | live | partial | mock | disabled. Reads the CACHED judgment only
// (GET) — never triggers an AI run (that is an admin-gated POST).
export type ConnPhase = 'connecting' | 'live' | 'partial' | 'mock' | 'disabled';

interface State {
  data: AIJudgment | null;
  error: string | null;
  loading: boolean;
  phase: ConnPhase;
  attempt: number;
}

const MOCK_SNAPSHOT: AIJudgment = {
  status: 'mock',
  asOf: '',
  engineVersion: 'ai-judge-v1',
  runMode: 'cached',
  models: { primary: null, checker: null },
  summaryJa: '',
  marketRiskJa: '',
  labels: [],
};

const MAX_ATTEMPTS = 3;
const ATTEMPT_TIMEOUT_MS = 8_000;
const RETRY_DELAYS_MS = [3_000, 6_000];

function sleep(ms: number): Promise<void> {
  return new Promise((res) => setTimeout(res, ms));
}

/**
 * Latest CACHED AI judgment from `/api/argus/ai-judgment` (engine v1). Read-only
 * and frontend-safe: it never triggers an expensive AI run. Returns the backend
 * status verbatim — including `disabled` when the layer is off.
 */
export function useAIJudgment(): State {
  const [state, setState] = useState<State>({
    data: null,
    error: null,
    loading: true,
    phase: 'connecting',
    attempt: 0,
  });

  useEffect(() => {
    const backend = import.meta.env.VITE_ARGUS_BACKEND_URL;
    if (!backend) {
      setState({ data: MOCK_SNAPSHOT, error: null, loading: false, phase: 'mock', attempt: 0 });
      return;
    }
    const url = backend.replace(/\/$/, '') + '/api/argus/ai-judgment';
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
          const data = (await r.json()) as AIJudgment;
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
    return () => {
      cancelled = true;
    };
  }, []);

  return state;
}
