import { useEffect, useState } from 'react';

// Calibration Ledger v4 — read-only model + status for the owner Calibration view.
export interface NamedMember { symbol: string; name: string; factorGroup: string | null }
export interface Cohorts {
  regimeSensorUniverseVersion?: string;
  tacticalBenchmarkVersion?: string;
  factorGroupVersion?: string;
  cohorts: Record<string, any>;
  contextVariables?: { noteJa?: string; variables?: Record<string, string> };
  layer1FactorGroupDemo?: { flatEqualSymbolWeighted?: number; equalGroupWeighted?: number } | null;
}
export interface Epochs { epochs: { epochId: string; status: string; recordCount?: number; includeInHeadlineMetrics: boolean }[] }
export interface Posture { outcome: { status: string; aggregateRiskAppetite: number | null; dispersion: number | null; dimensions: Record<string, any> }; inputsUsed: string[] }
export interface SyncStatus { lastStatus: string; privateStoreConfigured: boolean; symbolCount: number; lastSyncAt: string | null }

async function getJson<T>(base: string, path: string): Promise<T | null> {
  try {
    const r = await fetch(base.replace(/\/$/, '') + path);
    if (!r.ok) return null;
    return (await r.json()) as T;
  } catch { return null; }
}

export function useCalibration() {
  const [cohorts, setCohorts] = useState<Cohorts | null>(null);
  const [epochs, setEpochs] = useState<Epochs | null>(null);
  const [posture, setPosture] = useState<Posture | null>(null);
  const [sync, setSync] = useState<SyncStatus | null>(null);
  const backend = import.meta.env.VITE_ARGUS_BACKEND_URL;

  useEffect(() => {
    let alive = true;
    async function load() {
      if (!backend) return;
      const [c, e, p, s] = await Promise.all([
        getJson<Cohorts>(backend, '/api/argus/calibration/cohorts'),
        getJson<Epochs>(backend, '/api/argus/calibration/epochs'),
        getJson<Posture>(backend, '/api/argus/calibration/posture'),
        getJson<SyncStatus>(backend, '/api/argus/calibration/watchlist-sync-status'),
      ]);
      if (!alive) return;
      if (c) setCohorts(c); if (e) setEpochs(e); if (p) setPosture(p); if (s) setSync(s);
    }
    load();
    const t = window.setInterval(load, 5 * 60_000);
    return () => { alive = false; window.clearInterval(t); };
  }, [backend]);

  return { cohorts, epochs, posture, sync };
}
