import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  applyTachibanaHealthOverlay, getTachibanaLiveDocument, subscribeTachibanaLive, tachibanaLiveRevision,
} from '../domain/tachibanaLive';

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

export interface PublicDiagnostics {
  schemaVersion: 'argus-public-diagnostics-v1';
  generatedAt: string;
  service: {
    liveness: 'ok' | 'unavailable';
    readiness: 'ready' | 'not_ready';
    overall: 'ok' | 'degraded' | 'unavailable';
    backendVersion: string;
    buildSha: string | null;
  };
  freshness: {
    overall: 'fresh' | 'aging' | 'stale' | 'unknown' | 'mixed';
    sourceCounts: { fresh: number; aging: number; stale: number; unknown: number };
    expectedDisabledCount: number;
  };
  recovery: {
    mode: 'LEGACY_ONLY';
    measurement: 'SHADOW_INCOMPLETE';
    exactColdRecovery: 'NOT_PROVEN';
    hardRpoClaimPermitted: false;
  };
  systemHealth: SystemHealth;
}

interface DiagnosticsState {
  diagnostics: PublicDiagnostics | null;
  loading: boolean;
  failed: boolean;
}

let state: DiagnosticsState = { diagnostics: null, loading: false, failed: false };
let inFlight: Promise<void> | null = null;
const listeners = new Set<(next: DiagnosticsState) => void>();

function publish(next: DiagnosticsState) {
  state = next;
  for (const listener of listeners) listener(state);
}

function loadDiagnostics(backend: string | undefined, force = false): Promise<void> {
  if (inFlight) return inFlight;
  if (state.diagnostics && !force) return Promise.resolve();
  const base = backend?.replace(/\/$/, '');
  if (!base) {
    publish({ ...state, loading: false, failed: true });
    return Promise.resolve();
  }
  publish({ ...state, loading: true, failed: false });
  inFlight = fetch(`${base}/api/argus/data-quality/status`)
    .then((response) => {
      if (!response.ok) throw new Error('public_diagnostics_unavailable');
      return response.json() as Promise<PublicDiagnostics>;
    })
    .then((value) => {
      if (value.schemaVersion !== 'argus-public-diagnostics-v1'
        || !Array.isArray(value.systemHealth?.lamps)) {
        throw new Error('public_diagnostics_schema_invalid');
      }
      publish({ diagnostics: value, loading: false, failed: false });
    })
    .catch(() => publish({ ...state, loading: false, failed: true }))
    .finally(() => { inFlight = null; });
  return inFlight;
}

/**
 * One request-backed public diagnostics store. It deliberately has no timer:
 * AppShell health consumes the canonical diagnostics snapshot without restoring
 * the retired persistent /system-health polling loop.
 */
export function usePublicDiagnostics() {
  const backend = import.meta.env.VITE_ARGUS_BACKEND_URL as string | undefined;
  const [snapshot, setSnapshot] = useState(state);
  useEffect(() => {
    const listener = (next: DiagnosticsState) => setSnapshot(next);
    listeners.add(listener);
    void loadDiagnostics(backend);
    return () => { listeners.delete(listener); };
  }, [backend]);
  const refresh = useCallback(() => loadDiagnostics(backend, true), [backend]);
  return { ...snapshot, refresh };
}

export function useSystemHealth() {
  const backendHealth = usePublicDiagnostics().diagnostics?.systemHealth ?? null;
  // v13.5.40: the JP realtime lamp + overall beacon follow the Tachibana
  // evidence document published by the decision-evidence poller.
  const [revision, setRevision] = useState(tachibanaLiveRevision());
  useEffect(() => subscribeTachibanaLive(() => setRevision(tachibanaLiveRevision())), []);
  return useMemo(
    () => applyTachibanaHealthOverlay(backendHealth, getTachibanaLiveDocument()) ?? null,
    [backendHealth, revision]);
}
