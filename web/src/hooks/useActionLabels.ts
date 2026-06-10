import { useEffect, useState } from 'react';
import type { ActionLabelsSnapshot } from '../types/actionLabels';

// connecting | live | partial | mock — same model as the other live hooks.
export type ConnPhase = 'connecting' | 'live' | 'partial' | 'mock';

interface State {
  data: ActionLabelsSnapshot | null;
  error: string | null;
  loading: boolean;
  phase: ConnPhase;
  attempt: number;
}

// Mock fallback — used only when VITE_ARGUS_BACKEND_URL is unset or every
// attempt fails. Empty labels → callers fall back to a neutral HOLD per row.
const MOCK_SNAPSHOT: ActionLabelsSnapshot = {
  status: 'mock',
  asOf: '',
  engineVersion: 'action-v0',
  marketPosture: { label: 'CAUTIOUS', rationaleJa: 'ライブデータ未取得のため中立。' },
  labels: [],
};

const MAX_ATTEMPTS = 3;
const ATTEMPT_TIMEOUT_MS = 8_000;
const RETRY_DELAYS_MS = [3_000, 6_000];

function sleep(ms: number): Promise<void> {
  return new Promise((res) => setTimeout(res, ms));
}

/**
 * Rule-based action labels from the backend `/api/argus/action-labels` (engine
 * v0). Falls back to MOCK_SNAPSHOT (`phase === "mock"`) when the backend is
 * unset or every attempt fails. The backend may report `partial` when some
 * source is missing but conservative labels can still be produced.
 *
 * Pass `params` with the user's actual JP/US symbols for DYNAMIC labels —
 * unknown symbols are classified conservatively (high-beta) server-side.
 * Without params (or with both lists empty) the curated default is used.
 */
export function useActionLabels(params?: { jp?: string[]; us?: string[] }): State {
  const jpKey = params?.jp?.length ? params.jp.slice().sort().join(',') : '';
  const usKey = params?.us?.length ? params.us.slice().sort().join(',') : '';
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
    const qs: string[] = [];
    if (jpKey) qs.push(`jp=${encodeURIComponent(jpKey)}`);
    if (usKey) qs.push(`us=${encodeURIComponent(usKey)}`);
    const url = backend.replace(/\/$/, '') + '/api/argus/action-labels'
      + (qs.length ? `?${qs.join('&')}` : '');
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
          const data = (await r.json()) as ActionLabelsSnapshot;
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
  }, [jpKey, usKey]);

  return state;
}
