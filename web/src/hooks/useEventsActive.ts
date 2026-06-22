import { useEffect, useState } from 'react';

// 24/7 event backbone — active events + status (v10.39). Polls every 30s while
// the app is open (cheap public reads; the real-time path is the ntfy push).
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

export function useEventsActive() {
  const [events, setEvents] = useState<ActiveEvent[]>([]);
  const [status, setStatus] = useState<EventBackboneStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const backend = import.meta.env.VITE_ARGUS_BACKEND_URL;

  useEffect(() => {
    let alive = true;
    const base = backend?.replace(/\/$/, '');
    async function load() {
      if (!base) { setLoading(false); return; }
      try {
        const [ea, st] = await Promise.all([
          fetch(`${base}/api/argus/events-active`).then((r) => r.json()),
          fetch(`${base}/api/argus/event-backbone-status`).then((r) => r.json()),
        ]);
        if (!alive) return;
        setEvents(Array.isArray(ea.events) ? ea.events : []);
        setStatus(st as EventBackboneStatus);
      } catch { /* keep last */ }
      finally { if (alive) setLoading(false); }
    }
    load();
    const t = window.setInterval(load, 30_000);
    return () => { alive = false; window.clearInterval(t); };
  }, [backend]);

  return { events, status, loading };
}
