import { useSyncExternalStore } from 'react';
import { createSharedPollingStore } from '../lib/sharedPollingStore';

// Important Events (important-events-v1, v10.138) — the owner-facing "why this
// macro event matters" feed for the Today command area. Beginner explanation +
// owner-relevance priority + what's blocked until release. No forecast/consensus
// is fabricated; impact = how strongly markets MAY move, not a direction.

export type EventImpact = 'critical' | 'high' | 'medium' | 'low';

export interface ImportantEvent {
  eventId: string;
  eventCode: string;
  title: string;
  date: string | null;
  jstTime: string | null;       // "YYYY-MM-DD HH:MM JST" or null for date-only
  eventTimeUtc: string | null;
  countdown: string;            // D-7 | D-3 | D-1 | D | D+1 | normal
  daysUntil: number | null;
  baseImpact: EventImpact;
  displayImpact: EventImpact;
  ownerRelevance: 'critical' | 'high' | 'medium' | 'normal';
  priorityScore: number;
  priorityReasons: string[];
  lifecycle: 'UPCOMING' | 'IMMINENT' | 'RELEASED' | 'REACTION_PENDING' | 'REACTION_CONFIRMED' | 'RESOLVED' | string;
  noviceEn: string;
  noviceJa: string;
  rationaleJa: string | null;
  linkedAssets: string[];
  actionUntilEn: string;
  actionUntilJa: string;
  source: string | null;
  sourceStatus: string;
  forecast: string;             // "UNAVAILABLE" until a verified source provides it
  previous: string;
  actual: string | null;
  releasedAt: string | null;
}

export interface ImportantEventsSnapshot {
  status: string;
  asOf: string;
  timezone: string;
  engineVersion: string;
  count: number;
  events: ImportantEvent[];
}

const REFRESH_INTERVAL_MS = 120_000;   // events move slowly; 2-min poll is plenty

interface State { data: ImportantEventsSnapshot | null; loading: boolean; }

const importantEventsStore = createSharedPollingStore<State>(
  { data: null, loading: true },
  (setState) => {
    const backend = import.meta.env.VITE_ARGUS_BACKEND_URL;
    if (!backend) {
      setState({ data: null, loading: false });
      return () => {};
    }
    const url = backend.replace(/\/$/, '') + '/api/argus/important-events';
    let cancelled = false;
    let acquisition: Promise<void> | null = null;
    const controllers = new Set<AbortController>();

    function fetchOnce(): Promise<void> {
      if (cancelled || document.hidden) return Promise.resolve();
      if (acquisition) return acquisition;
      const ctrl = new AbortController();
      controllers.add(ctrl);
      const timeout = window.setTimeout(() => ctrl.abort(), 12_000);
      const current = (async () => {
        try {
          const response = await fetch(url, { signal: ctrl.signal });
          if (!response.ok || cancelled) return;
          const data = (await response.json()) as ImportantEventsSnapshot;
          if (!cancelled) setState({ data, loading: false });
        } catch {
          if (!cancelled) setState((state) => ({ ...state, loading: false }));
        } finally {
          window.clearTimeout(timeout);
          controllers.delete(ctrl);
        }
      })().finally(() => {
        if (acquisition === current) acquisition = null;
      });
      acquisition = current;
      return current;
    }

    void fetchOnce();
    const timer = window.setInterval(() => void fetchOnce(), REFRESH_INTERVAL_MS);
    const onVisible = () => { if (!document.hidden) void fetchOnce(); };
    document.addEventListener('visibilitychange', onVisible);
    return () => {
      cancelled = true;
      for (const controller of controllers) controller.abort();
      controllers.clear();
      window.clearInterval(timer);
      document.removeEventListener('visibilitychange', onVisible);
    };
  },
);

export function useImportantEvents(): State {
  return useSyncExternalStore(
    importantEventsStore.subscribe,
    importantEventsStore.getSnapshot,
    importantEventsStore.getSnapshot,
  );
}
