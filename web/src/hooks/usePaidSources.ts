import { useEffect, useState } from 'react';

// Paid-source connection status (v11.1) — GET /api/argus/provider-diagnostics/public.
// Public-safe: configured booleans + live/partial/missing ONLY (no secrets, no detail).
export interface PaidProvider { provider: string; configured: boolean; status: string; }
export interface PaidSources {
  asOf?: string;
  providers?: PaidProvider[];
  summary?: { live?: number; configured?: number; total?: number };
}

export function usePaidSources(): PaidSources | null {
  const [d, setD] = useState<PaidSources | null>(null);
  useEffect(() => {
    const backend = import.meta.env.VITE_ARGUS_BACKEND_URL as string | undefined;
    if (!backend) return;
    let alive = true;
    const url = backend.replace(/\/$/, '') + '/api/argus/provider-diagnostics/public';
    const load = () => fetch(url).then((r) => r.json())
      .then((j) => { if (alive && j && j.providers) setD(j as PaidSources); })
      .catch(() => { /* keep last */ });
    load();
    const iv = setInterval(load, 120_000);
    return () => { alive = false; clearInterval(iv); };
  }, []);
  return d;
}
