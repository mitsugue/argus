import { useSyncExternalStore } from 'react';
import { createSharedPollingStore } from '../lib/sharedPollingStore';
import { validJapanSqCalendar, type JapanSqCalendar } from '../lib/japanSqCalendar';

type State = { data: JapanSqCalendar | null; loading: boolean; failed: boolean; checkedAt: number };
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
        const response = await fetch(base + '/api/argus/jp-sq-calendar', { cache: 'no-store', signal: controller.signal });
        if (!response.ok) throw new Error('calendar_fetch_failed');
        const data = await response.json();
        if (!validJapanSqCalendar(data)) throw new Error('calendar_invalid');
        if (!stopped) set({ data: data.status === 'UNAVAILABLE' ? get().data ?? data : data,
          loading: false, failed: data.status === 'UNAVAILABLE', checkedAt: Date.now() });
      } catch { if (!stopped) set({ ...get(), loading: false, failed: true, checkedAt: Date.now() }); }
      finally { window.clearTimeout(timeout); flight = null; }
    };
    retry = () => { void refresh(); };
    const visible = () => { if (document.visibilityState === 'visible') void refresh(); };
    const interval = window.setInterval(() => {
      set({ ...get(), checkedAt: Date.now() }); visible();
    }, 60_000);
    document.addEventListener('visibilitychange', visible); void refresh();
    return () => { stopped = true; flight?.abort(); window.clearInterval(interval);
      document.removeEventListener('visibilitychange', visible); retry = () => {}; };
  });
export function useJapanSqCalendar() {
  return { ...useSyncExternalStore(store.subscribe, store.getSnapshot, store.getSnapshot), retry: () => retry() };
}
