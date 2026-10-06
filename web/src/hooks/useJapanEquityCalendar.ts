import { subscribeInitialVisibleRead } from '../lib/pollingPolicy';
import { useSyncExternalStore } from 'react';
import { createSharedPollingStore } from '../lib/sharedPollingStore';
import { CALENDAR_VISIBLE_MS, isPageVisible } from '../lib/pollingPolicy';
import { validEquityCalendar, type EquityCalendar } from '../lib/japanEquityCalendar';

type State = { data: EquityCalendar | null; loading: boolean; failed: boolean; checkedAt: number };
let retry = () => {};
const store = createSharedPollingStore<State>({ data: null, loading: true, failed: false, checkedAt: 0 },
  (set, get) => {
    let stopped = false; let flight: AbortController | null = null;
    const base = (import.meta.env.VITE_ARGUS_BACKEND_URL as string | undefined)?.replace(/\/$/, '');
    const refresh = async () => {
      if (stopped || flight) return;
      const controller = new AbortController(); flight = controller;
      const timeout = window.setTimeout(() => controller.abort(), 12_000);
      set({ ...get(), loading: true, checkedAt: Date.now() });
      try {
        if (!base) throw new Error('backend_missing');
        const response = await fetch(base + '/api/argus/jp-equity-calendar', { cache: 'no-store', signal: controller.signal });
        if (!response.ok) throw new Error('calendar_fetch_failed');
        const data = await response.json();
        if (!validEquityCalendar(data)) throw new Error('calendar_invalid');
        if (!stopped) set({ data,
          loading: false, failed: false, checkedAt: Date.now() });
      } catch { if (!stopped) set({ ...get(), loading: false, failed: true, checkedAt: Date.now() }); }
      finally { window.clearTimeout(timeout); flight = null; }
    };
    retry = () => { void refresh(); };
    const visible = () => { if (document.visibilityState === 'visible') void refresh(); };
    const interval = window.setInterval(() => {
      if (!isPageVisible()) return;
      set({ ...get(), checkedAt: Date.now() }); visible();
    }, CALENDAR_VISIBLE_MS);
    const stopInitialVisible = subscribeInitialVisibleRead(visible); void refresh();
    return () => { stopped = true; flight?.abort(); window.clearInterval(interval);
      stopInitialVisible(); retry = () => {}; };
  });
export function useJapanEquityCalendar() {
  return { ...useSyncExternalStore(store.subscribe, store.getSnapshot, store.getSnapshot), retry: () => retry() };
}
