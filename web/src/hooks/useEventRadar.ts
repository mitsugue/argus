import { useEffect, useState } from 'react';
import type { EventsSnapshot } from '../types/events';

// connecting | live | partial | mock — same model as the other live hooks,
// plus "partial" (some official sources live, one or more failed).
export type ConnPhase = 'connecting' | 'live' | 'partial' | 'mock';

interface State {
  data: EventsSnapshot | null;
  error: string | null;
  loading: boolean;
  phase: ConnPhase;
  attempt: number;
}

// Minimal mock fallback — used only when VITE_ARGUS_BACKEND_URL is unset or
// every attempt fails. NOT a real calendar (escalation is left neutral).
const MOCK_SNAPSHOT: EventsSnapshot = {
  status: 'mock',
  asOf: null,
  timezone: 'Asia/Tokyo',
  sources: [
    { name: 'Federal Reserve', status: 'mock', lastUpdated: null },
    { name: 'Bureau of Labor Statistics', status: 'mock', lastUpdated: null },
    { name: 'Bureau of Economic Analysis', status: 'mock', lastUpdated: null },
    { name: 'Bank of Japan', status: 'mock', lastUpdated: null },
    { name: 'TreasuryDirect', status: 'mock', lastUpdated: null },
  ],
  events: [
    {
      id: 'us-cpi-mock', title: 'US CPI (Consumer Price Index)', category: 'inflation',
      country: 'US', source: 'Bureau of Labor Statistics', impact: 'high',
      eventTimeUtc: null, eventDate: null, localTimeJst: null, daysUntil: 0,
      escalation: 'normal',
      rationaleJa: 'インフレ再加速は米金利上昇とグロース株のバリュエーション圧迫につながるため、発表前後の指数・金利・為替を確認する。',
      linkedAssets: ['US10Y', 'USDJPY', 'QQQ'], status: 'mock',
    },
    {
      id: 'jp-boj-mock', title: 'BOJ Monetary Policy Meeting', category: 'central_bank',
      country: 'JP', source: 'Bank of Japan', impact: 'high',
      eventTimeUtc: null, eventDate: null, localTimeJst: null, daysUntil: 0,
      escalation: 'normal',
      rationaleJa: '円金利・ドル円・日本株グロース/輸出株の地合いに影響するため、会合前後は円高・金利上昇・銀行株/輸出株の反応を見る。',
      linkedAssets: ['USDJPY', 'JP10Y', '9984'], status: 'mock',
    },
  ],
};

const MAX_ATTEMPTS = 3;
const ATTEMPT_TIMEOUT_MS = 8_000;
const RETRY_DELAYS_MS = [3_000, 6_000];

function sleep(ms: number): Promise<void> {
  return new Promise((res) => setTimeout(res, ms));
}

/**
 * Official event calendar for ARGUS Event Radar from the backend
 * `/api/argus/events`. Falls back to MOCK_SNAPSHOT (`phase === "mock"`) when the
 * backend is unset or every attempt fails. The backend itself may report
 * `partial` (some official sources live, one or more failed) — surfaced as-is.
 */
export function useEventRadar(): State {
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
    const url = backend.replace(/\/$/, '') + '/api/argus/events';
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
          const data = (await r.json()) as EventsSnapshot;
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
