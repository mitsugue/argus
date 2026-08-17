import { useEffect, useState } from 'react';

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

export function useImportantEvents(): State {
  const [state, setState] = useState<State>({ data: null, loading: true });

  useEffect(() => {
    const backend = import.meta.env.VITE_ARGUS_BACKEND_URL;
    if (!backend) { setState({ data: null, loading: false }); return; }
    const url = backend.replace(/\/$/, '') + '/api/argus/important-events';
    let cancelled = false;

    async function fetchOnce() {
      if (cancelled || document.hidden) return;
      const ctrl = new AbortController();
      const timer = setTimeout(() => ctrl.abort(), 12_000);
      try {
        const r = await fetch(url, { signal: ctrl.signal });
        clearTimeout(timer);
        if (!r.ok || cancelled) return;
        const data = (await r.json()) as ImportantEventsSnapshot;
        if (!cancelled) setState({ data, loading: false });
      } catch {
        clearTimeout(timer);
        if (!cancelled) setState((s) => ({ ...s, loading: false }));
      }
    }

    void fetchOnce();
    const t = setInterval(() => void fetchOnce(), REFRESH_INTERVAL_MS);
    const onVisible = () => { if (!document.hidden) void fetchOnce(); };
    document.addEventListener('visibilitychange', onVisible);
    return () => {
      cancelled = true;
      clearInterval(t);
      document.removeEventListener('visibilitychange', onVisible);
    };
  }, []);

  return state;
}
