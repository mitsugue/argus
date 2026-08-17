import { useEffect, useState } from 'react';

// C.A.O.S. Watchtower status (v11.5.3) — per-source freshness + asset-class
// coverage. Public cache-only endpoint; refreshes every 5 min while visible.

export interface WatchtowerSource {
  sourceId: string;
  name: string;
  assetClasses: string[];
  sourceTier: string;
  rightsClass: string;
  isDiscoveryLayer?: boolean;
  status: 'live' | 'partial' | 'stale' | 'error' | 'not_configured' | 'requires_contract' | 'disabled';
  lastCheckAt?: string | null;
  newestPublishedAt?: string | null;
  newestAgeHours?: number | null;
  itemsToday?: number;
  successRate24h?: number | null;
  limitationsJa?: string[];
}

export interface WatchtowerCoverage {
  totalSources: number;
  liveSources: number;
  newestItemAgeHours: number | null;
  status: 'live' | 'partial' | 'missing';
}

/** v11.5.5: compact patrol-liveness proof carried on the status payload. */
export interface PatrolHealthRef {
  status: 'healthy' | 'degraded' | 'stale' | 'error' | 'not_ready';
  lastPatrolAt?: string | null;
  lastDeepSweepAt?: string | null;
  baselineSweeps24h?: number;
  deepSweeps24h?: number;
  emptyDeepSweepRuns24h?: number;
  oldPrimaryViolations?: number;
  baselineOnly?: boolean;
}

export interface WatchtowerStatus {
  schemaVersion: string;
  asOf: string;
  lastRefreshAt?: string | null;
  patrolHealth?: PatrolHealthRef | null;
  sources: WatchtowerSource[];
  coverageByAssetClass: Record<string, WatchtowerCoverage>;
  alerts: { severity: string; messageJa: string }[];
  noteJa?: string;
}

const REFRESH_INTERVAL_MS = 5 * 60_000;

export function useWatchtowerStatus(): { data: WatchtowerStatus | null } {
  const [data, setData] = useState<WatchtowerStatus | null>(null);

  useEffect(() => {
    const backend = import.meta.env.VITE_ARGUS_BACKEND_URL;
    if (!backend) return;
    const url = backend.replace(/\/$/, '') + '/api/argus/caos-watchtower/status';
    let cancelled = false;

    async function fetchOnce() {
      if (cancelled || document.hidden) return;
      const ctrl = new AbortController();
      const timer = setTimeout(() => ctrl.abort(), 8_000);
      try {
        const r = await fetch(url, { signal: ctrl.signal });
        clearTimeout(timer);
        if (!r.ok || cancelled) return;
        const d = (await r.json()) as WatchtowerStatus;
        if (!cancelled) setData(d);
      } catch {
        clearTimeout(timer);
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

  return { data };
}
