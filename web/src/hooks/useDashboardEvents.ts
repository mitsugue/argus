import { useSyncExternalStore } from 'react';
import { liveAuthorityState, scheduleLiveAuthorityExpiry } from '../domain/liveAuthority';
import type { DashboardEventsResponse } from '../lib/dashboardEventState';
import { createSharedPollingStore, type SharedPollingStore } from '../lib/sharedPollingStore';

// Unified display feed. Stale or failed data returns null so consumers fall
// through to the separately bounded important-events source; an old nonempty
// feed can never remain the preferred public surface indefinitely.
interface State { data: DashboardEventsResponse | null; authority: string; }

const stores = new Map<number, SharedPollingStore<State>>();

function dashboardEventsStore(pollMs: number): SharedPollingStore<State> {
  const existing = stores.get(pollMs);
  if (existing) return existing;
  const store = createSharedPollingStore<State>(
    { data: null, authority: 'unavailable' },
    (setState, getState) => {
      const backend = import.meta.env.VITE_ARGUS_BACKEND_URL as string | undefined;
      if (!backend) return () => {};
      const url = backend.replace(/\/$/, '') + '/api/argus/dashboard-events?limit=8';
      let alive = true;
      let acquisition: Promise<void> | null = null;
      let cancelExpiry = () => {};
      const controllers = new Set<AbortController>();

      function acquire(task: () => Promise<void>) {
        if (acquisition) return acquisition;
        const current = task().finally(() => {
          if (acquisition === current) acquisition = null;
        });
        acquisition = current;
        return current;
      }

      function accept(data: DashboardEventsResponse) {
        cancelExpiry();
        const authority = liveAuthorityState(data.asOf, 'dashboardEvents');
        if (authority !== 'fresh') {
          setState({ data: null, authority });
          return;
        }
        setState({ data, authority: 'fresh' });
        cancelExpiry = scheduleLiveAuthorityExpiry(data.asOf, 'dashboardEvents',
          () => setState({ data: null, authority: 'expired' }));
      }

      async function load() {
        const controller = new AbortController();
        controllers.add(controller);
        try {
          const response = await fetch(url, { signal: controller.signal });
          if (!response.ok) throw new Error(`HTTP ${response.status}`);
          const data = await response.json() as DashboardEventsResponse;
          if (!alive) return;
          if (!data || data.schemaVersion !== 'dashboard-event-summary-v1'
              || !Array.isArray(data.items)) throw new Error('invalid_dashboard_events');
          accept(data);
        } catch {
          if (alive) {
            cancelExpiry();
            setState({ data: null, authority: 'refresh_failed' });
          }
        } finally {
          controllers.delete(controller);
        }
      }

      const retained = getState();
      if (retained.data && retained.authority === 'fresh') accept(retained.data);
      const interval = window.setInterval(() => void acquire(load), pollMs);
      const onVisible = () => { if (!document.hidden) void acquire(load); };
      document.addEventListener('visibilitychange', onVisible);
      void acquire(load);
      return () => {
        alive = false;
        cancelExpiry();
        for (const controller of controllers) controller.abort();
        controllers.clear();
        window.clearInterval(interval);
        document.removeEventListener('visibilitychange', onVisible);
      };
    },
  );
  stores.set(pollMs, store);
  return store;
}

export function useDashboardEvents(pollMs = 120_000): DashboardEventsResponse | null {
  const store = dashboardEventsStore(pollMs);
  return useSyncExternalStore(store.subscribe, store.getSnapshot, store.getSnapshot).data;
}
