import { useEffect, useState } from 'react';

// EventCard v2 (v11) — GET /api/argus/events/cards, 120s poll. The canonical research
// object with epistemic discipline surfaced: corroboration, trigger role, and what's
// missing. Mirrors the useMarketDepth fetch pattern.

export interface EventCard {
  schemaVersion?: string;
  cardId?: string;
  eventType?: string;
  headline?: string;
  summaryJa?: string;
  directAssets?: string[];
  corroborationLevel?: string;
  triggerRole?: string;
  missingConfirmations?: string[];
  confidenceRaw?: number;
  confidenceFinal?: number;
  decisionImpact?: { canAffectTodayCall?: boolean; postureDelta?: string; downgradeReasonJa?: string };
}
export interface EventCardsResponse {
  schemaVersion?: string;
  count?: number;
  items?: EventCard[];
}

export function useEventCards(): EventCardsResponse | null {
  const [data, setData] = useState<EventCardsResponse | null>(null);
  useEffect(() => {
    const backend = import.meta.env.VITE_ARGUS_BACKEND_URL as string | undefined;
    if (!backend) return;
    let alive = true;
    const url = backend.replace(/\/$/, '') + '/api/argus/events/cards?limit=12';
    const load = () => fetch(url).then((r) => r.json())
      .then((d) => { if (alive && d && d.schemaVersion) setData(d as EventCardsResponse); })
      .catch(() => { /* keep last */ });
    load();
    const iv = setInterval(load, 120_000);
    return () => { alive = false; clearInterval(iv); };
  }, []);
  return data;
}
