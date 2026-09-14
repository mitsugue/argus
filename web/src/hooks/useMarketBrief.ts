import { useSyncExternalStore } from 'react';
import { createSharedPollingStore } from '../lib/sharedPollingStore';
import { validMarketBrief, type MarketBrief } from '../lib/marketBrief';
import { editorialEdition, readRecentEditorialEdition, retainEditorialEdition } from '../lib/presentationIntent';
export type { MarketBrief, MarketBriefFact } from '../lib/marketBrief';

type State = { brief: MarketBrief | null; error: boolean; loading: boolean };
let retry = () => {};
const store = createSharedPollingStore<State>({ brief: null, error: false, loading: true }, (set, get) => {
  let stopped = false; let flight: AbortController | null = null; let nextPollAt = 0;
  const base = (import.meta.env.VITE_ARGUS_BACKEND_URL as string | undefined)?.replace(/\/$/, '');
  const load = async () => {
    if (stopped || flight) return;
    const controller = new AbortController(); flight = controller;
    const timeout = window.setTimeout(() => controller.abort(), 12_000);
    set({ ...get(), loading: true });
    try {
      if (!base) throw new Error('backend_missing');
      const response = await fetch(base + '/api/argus/market-brief',
        { cache: 'no-store', signal: controller.signal, headers: { Accept: 'application/json' } });
      if (!response.ok) throw new Error('brief_fetch_failed');
      const brief: unknown = await response.json();
      if (!validMarketBrief(brief)) throw new Error('brief_invalid');
      let readable = retainEditorialEdition(brief, get().brief);
      const restoringHistory = !editorialEdition(readable);
      if (!stopped) set({ brief: readable, error: false, loading: restoringHistory });
      if (restoringHistory) {
        try {
          const saved = await readRecentEditorialEdition(base, controller.signal);
          readable = retainEditorialEdition(readable, saved);
          if (!stopped) set({ brief: readable, error: false, loading: false });
        } catch { if (!stopped) set({ ...get(), loading: false }); }
      }
    } catch { if (!stopped) set({ ...get(), error: true, loading: false }); }
    finally {
      window.clearTimeout(timeout); flight = null;
      nextPollAt = Date.now() + (get().error || !editorialEdition(get().brief) ? 30_000 : 5 * 60_000);
    }
  };
  retry = () => { void load(); };
  const visible = () => { if (document.visibilityState === 'visible') void load(); };
  const timer = window.setInterval(() => { if (Date.now() >= nextPollAt) visible(); }, 30_000);
  document.addEventListener('visibilitychange', visible); void load();
  return () => { stopped = true; flight?.abort(); window.clearInterval(timer);
    document.removeEventListener('visibilitychange', visible); retry = () => {}; };
});
export function useMarketBrief() {
  return { ...useSyncExternalStore(store.subscribe, store.getSnapshot, store.getSnapshot), retry: () => retry() };
}
