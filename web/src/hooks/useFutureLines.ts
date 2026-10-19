import { useEffect, useState } from 'react';
import { scheduleVisibleInterval, subscribeInitialVisibleRead } from '../lib/pollingPolicy';
import { validFutureLines, type FutureLinesDoc } from '../lib/futureLines';

// Future lines (2026-10-19): read on display and every 15 minutes while in
// front; the last valid document stays when a read fails.
let current: FutureLinesDoc | null = null;
export type FutureLinesState = { doc: FutureLinesDoc | null; status: 'loading' | 'ready' | 'unavailable' };

export function useFutureLines(): FutureLinesState {
  const [state, setState] = useState<FutureLinesState>({ doc: current, status: current ? 'ready' : 'loading' });
  useEffect(() => {
    let alive = true;
    const base = (import.meta.env.VITE_ARGUS_BACKEND_URL as string | undefined)?.replace(/\/$/, '') ?? '';
    const read = async () => {
      if (!base || document.visibilityState !== 'visible') { if (!current && alive) setState({ doc: null, status: 'unavailable' }); return; }
      try {
        const r = await fetch(`${base}/api/argus/future-lines`, { cache: 'no-store' });
        const body: unknown = r.ok ? await r.json() : null;
        if (validFutureLines(body)) current = body;
      } catch { /* keep the last valid document */ }
      if (alive) setState({ doc: current, status: current ? 'ready' : 'unavailable' });
    };
    void read();
    const stop = subscribeInitialVisibleRead(() => { void read(); }, false);
    const timer = scheduleVisibleInterval(() => { void read(); }, 15 * 60_000);
    return () => { alive = false; stop(); timer(); };
  }, []);
  return state;
}
