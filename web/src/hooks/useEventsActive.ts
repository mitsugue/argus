import { useSyncExternalStore } from 'react';
import { createSharedPollingStore } from '../lib/sharedPollingStore';

// 24/7 event backbone — active events + status (v10.39). Polls every 15s while
// the app is open (matches the bridge push cadence) so the list updates live;
// the ntfy push is the off-app path.
export interface ActiveEvent {
  eventId: string;
  eventType: string;
  symbol: string;
  nameJa?: string | null;
  market: string;
  session: string;
  severity: number;
  lifecycleState: string;
  recommendedPosture: string;
  reasonJa?: string | null;
  detectedAt?: string | null;
}
export interface EventBackboneStatus {
  enabled: boolean;
  activeCount: number;
  ntfyConfigured: boolean;
  sessionJp: boolean;
  sessionUs: boolean;
  lastDetectionAt: string | null;
  lastEventAt: string | null;
}

interface EventsActiveState {
  events: ActiveEvent[];
  status: EventBackboneStatus | null;
  loading: boolean;
}

// Asset intelligence is mounted in more than one surface. One shared lifecycle
// prevents duplicate reads, and pausing while the page is backgrounded avoids
// paying for a 15-second read that cannot be seen. Returning to the tab fetches
// immediately, so the event view never waits for the next scheduled interval.
const eventsActiveStore = createSharedPollingStore<EventsActiveState>(
  { events: [], status: null, loading: true },
  (setState) => {
    const backend = import.meta.env.VITE_ARGUS_BACKEND_URL as string | undefined;
    const base = backend?.replace(/\/$/, '');
    let cancelled = false;
    let inFlight = false;
    let controller: AbortController | null = null;

    async function load() {
      if (cancelled || document.hidden || inFlight) return;
      if (!base) {
        setState((current) => ({ ...current, loading: false }));
        return;
      }
      inFlight = true;
      controller = new AbortController();
      try {
        const response = await fetch(`${base}/api/argus/events-active`, { signal: controller.signal });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const payload = await response.json();
        if (!cancelled) {
          setState({ events: Array.isArray(payload.events) ? payload.events : [],
            status: payload as EventBackboneStatus, loading: false });
        }
      } catch { /* keep the last successful event view */ }
      finally {
        controller = null;
        inFlight = false;
        if (!cancelled) setState((current) => ({ ...current, loading: false }));
      }
    }

    const onVisible = () => { if (!document.hidden) void load(); };
    document.addEventListener('visibilitychange', onVisible);
    void load();
    const timer = window.setInterval(() => void load(), 15_000);
    return () => {
      cancelled = true;
      controller?.abort();
      window.clearInterval(timer);
      document.removeEventListener('visibilitychange', onVisible);
    };
  },
);

export function useEventsActive() {
  return useSyncExternalStore(
    eventsActiveStore.subscribe,
    eventsActiveStore.getSnapshot,
    eventsActiveStore.getSnapshot,
  );
}
