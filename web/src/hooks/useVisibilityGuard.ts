import { useEffect, useState } from 'react';

// Visibility Risk Guard (v10.195) — GET /api/argus/visibility-guard, 30s poll.
// Tells the UI what ARGUS can't see, whether to cap confidence / block ENTER, and
// carries a calm "検知≠安全" coverage line. Structural gaps are context; only
// situational degradation drops the level.
export interface VisibilityWarning { code: string; messageJa: string; }
export interface VisibilityGuard {
  asOf: string;
  engineVersion: string;
  visibilityLevel: 'full' | 'reduced' | 'minimal';
  blockedActions: ('ENTER' | 'ADD')[];
  warnings: VisibilityWarning[];
  limitations: string[];
  structuralGapCount: number;
  coverageLineJa: string;
  confidenceCap: number | null;
  reasonCodes: string[];
}

const FALLBACK: VisibilityGuard = {
  asOf: '', engineVersion: 'visibility-guard-v1', visibilityLevel: 'full',
  blockedActions: [], warnings: [], limitations: [], structuralGapCount: 0,
  coverageLineJa: '', confidenceCap: null, reasonCodes: [],
};

export function useVisibilityGuard(): VisibilityGuard | null {
  const [data, setData] = useState<VisibilityGuard | null>(null);
  useEffect(() => {
    const backend = import.meta.env.VITE_ARGUS_BACKEND_URL as string | undefined;
    if (!backend) { setData(FALLBACK); return; }
    let alive = true;
    const url = backend.replace(/\/$/, '') + '/api/argus/visibility-guard';
    const load = () => fetch(url).then((r) => r.json())
      .then((d) => { if (alive && d && d.visibilityLevel) setData(d as VisibilityGuard); })
      .catch(() => { /* keep last value */ });
    load();
    const iv = setInterval(load, 30_000);
    return () => { alive = false; clearInterval(iv); };
  }, []);
  return data;
}
