import { useEffect, useState } from 'react';

// Unified operational status of every self-scoring loop (#5, v10.36).
// One-shot fetch with a light 5-min refresh while the Guide is open.
export interface LedgerRow {
  id: string;
  labelJa: string;
  status: 'healthy' | 'stale' | 'empty' | 'unknown';
  lastUpdated: string | null;
  lastSuccessAt?: string | null;
  ageMin?: number | null;
  sampleCount: number | null;
  tradingDays: number | null;
  hitRate: number | null;
  nextRunJa: string;
  trigger: string;
  staleWeekdays?: number | null;
  truthStatus?: string;
  models?: { primary: string | null; checker: string | null };
  noteJa: string;
}
export interface LedgerHealth {
  asOf: string;
  engineVersion: string;
  ledgers: LedgerRow[];
}

export function useLedgerHealth() {
  const [data, setData] = useState<LedgerHealth | null>(null);
  const [error, setError] = useState<string | null>(null);
  const backend = import.meta.env.VITE_ARGUS_BACKEND_URL;

  useEffect(() => {
    let alive = true;
    async function load() {
      if (!backend) { setError('backend not configured'); return; }
      try {
        const r = await fetch(backend.replace(/\/$/, '') + '/api/argus/ledger-health');
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const d = (await r.json()) as LedgerHealth;
        if (alive) { setData(d); setError(null); }
      } catch (e) {
        if (alive) setError(String(e));
      }
    }
    load();
    const t = window.setInterval(load, 5 * 60_000);
    return () => { alive = false; window.clearInterval(t); };
  }, [backend]);

  return { data, error };
}
