import { scheduleVisibleInterval, subscribeInitialVisibleRead } from '../lib/pollingPolicy';
import { useSyncExternalStore } from 'react';
import { createSharedPollingStore } from '../lib/sharedPollingStore';
import { validMarketBrief, type MarketBrief } from '../lib/marketBrief';
import { readableBriefEdition, readRecentEditorialEdition, retainEditorialEdition } from '../lib/presentationIntent';
export type { MarketBrief, MarketBriefFact } from '../lib/marketBrief';

type State = { brief: MarketBrief | null; error: boolean; loading: boolean };
let retry = () => {};
const store = createSharedPollingStore<State>({ brief: null, error: false, loading: true }, (set, get) => {
  let stopped = false; let flight: AbortController | null = null; let nextPollAt = 0;
  const base = (import.meta.env.VITE_ARGUS_BACKEND_URL as string | undefined)?.replace(/\/$/, '');
  const load = async () => {
    if (stopped || flight || document.visibilityState !== 'visible') return;
    const controller = new AbortController(); flight = controller;
    let historyAllowed = !!base;
    // History recovery has its own deadline: a timed-out current request must
    // not also abort the read that can recover the saved edition.
    const currentRequest = new AbortController();
    const cancelCurrent = () => currentRequest.abort();
    controller.signal.addEventListener('abort', cancelCurrent, { once: true });
    const timeout = window.setTimeout(cancelCurrent, 12_000);
    set({ ...get(), loading: true });
    try {
      if (!base) throw new Error('backend_missing');
      const response = await fetch(base + '/api/argus/market-brief',
        { cache: 'no-store', signal: currentRequest.signal, headers: { Accept: 'application/json' } });
      if (response.status === 401 || response.status === 403) historyAllowed = false;
      if (!response.ok) throw new Error('brief_fetch_failed');
      const brief: unknown = await response.json();
      if (!validMarketBrief(brief)) throw new Error('brief_invalid');
      let readable = retainEditorialEdition(brief, get().brief);
      const restoringHistory = !readableBriefEdition(readable);
      if (!stopped) set({ brief: readable, error: false, loading: restoringHistory });
      if (restoringHistory) {
        window.clearTimeout(timeout);
        const historyTimeout = window.setTimeout(() => controller.abort(), 12_000);
        try {
          const saved = await readRecentEditorialEdition(base, controller.signal);
          readable = retainEditorialEdition(readable, saved);
          if (!stopped) set({ brief: readable, error: false, loading: false });
        } catch { if (!stopped) set({ ...get(), error: true, loading: false }); }
        finally { window.clearTimeout(historyTimeout); }
      }
    } catch {
      window.clearTimeout(timeout);
      if (!stopped && historyAllowed && !readableBriefEdition(get().brief)) {
        const historyTimeout = window.setTimeout(() => controller.abort(), 12_000);
        try {
          const saved = await readRecentEditorialEdition(base!, controller.signal);
          if (!stopped && saved) set({ brief: saved, error: true, loading: false });
        } catch { /* The visible failure remains; never invent a view. */ }
        finally { window.clearTimeout(historyTimeout); }
      }
      if (!stopped) set({ ...get(), error: true, loading: false });
    }
    finally {
      controller.signal.removeEventListener('abort', cancelCurrent);
      window.clearTimeout(timeout); flight = null;
      nextPollAt = Date.now() + (get().error || !readableBriefEdition(get().brief) ? 30_000 : 5 * 60_000);
    }
  };
  retry = () => { void load(); };
  const visible = () => { if (document.visibilityState === 'visible') void load(); };
  const timer = scheduleVisibleInterval(() => { if (Date.now() >= nextPollAt) visible(); }, 30_000);
  const stopInitialVisible = subscribeInitialVisibleRead(visible); void load();
  return () => { stopped = true; flight?.abort(); timer();
    stopInitialVisible(); retry = () => {}; };
});
export function useMarketBrief() {
  return { ...useSyncExternalStore(store.subscribe, store.getSnapshot, store.getSnapshot), retry: () => retry() };
}
