import { useEffect, useState } from 'react';
import type { DashboardEventsResponse } from '../lib/dashboardEventState';

// ARGUS V11.4.1 — the unified top-card event feed. GET /api/argus/dashboard-events
// is public cache-only (no LLM, no provider fetch). Returns null until first load /
// on error so consumers can fall back to the legacy important-events + macro hooks.

export function useDashboardEvents(pollMs = 120_000): DashboardEventsResponse | null {
  const [data, setData] = useState<DashboardEventsResponse | null>(null);
  useEffect(() => {
    const backend = import.meta.env.VITE_ARGUS_BACKEND_URL as string | undefined;
    if (!backend) return;
    let alive = true;
    const url = backend.replace(/\/$/, '') + '/api/argus/dashboard-events?limit=8';
    const load = () => fetch(url)
      .then((r) => r.json())
      .then((d) => {
        if (alive && d && d.schemaVersion === 'dashboard-event-summary-v1' && Array.isArray(d.items)) {
          setData(d as DashboardEventsResponse);
        }
      })
      .catch(() => { /* keep last; consumers fall back */ });
    load();
    const iv = window.setInterval(() => { if (!document.hidden) load(); }, pollMs);
    const onVis = () => { if (!document.hidden) load(); };
    document.addEventListener('visibilitychange', onVis);
    return () => { alive = false; window.clearInterval(iv); document.removeEventListener('visibilitychange', onVis); };
  }, [pollMs]);
  return data;
}
