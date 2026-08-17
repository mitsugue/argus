import { useEffect, useState } from 'react';

// System health lamps (v10.51) — at-a-glance green/amber/red for the metered &
// important systems so a SILENT budget stop / bridge outage becomes visible.
// Public-safe: colors + coarse JA only (no dollar amounts — those are admin-only).
export type LampStatus = 'ok' | 'warning' | 'stopped' | 'off';
export interface HealthLamp {
  key: string;
  labelJa: string;
  status: LampStatus;
  detailJa: string;
}
export interface SystemHealth {
  asOf: string;
  overall: LampStatus;
  lamps: HealthLamp[];
  noteJa?: string;
}

export function useSystemHealth() {
  const [health, setHealth] = useState<SystemHealth | null>(null);
  const backend = import.meta.env.VITE_ARGUS_BACKEND_URL;

  useEffect(() => {
    let alive = true;
    const base = backend?.replace(/\/$/, '');
    async function load() {
      if (!base) return;
      try {
        const d = await fetch(`${base}/api/argus/system-health`).then((r) => r.json());
        if (alive && Array.isArray(d?.lamps)) setHealth(d as SystemHealth);
      } catch { /* keep last */ }
    }
    load();
    const t = window.setInterval(load, 30_000);
    return () => { alive = false; window.clearInterval(t); };
  }, [backend]);

  return health;
}
