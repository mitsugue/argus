import { useSyncExternalStore } from 'react';
import { deauthorizeVisibilityGuard, liveAuthorityState,
  scheduleLiveAuthorityExpiry } from '../domain/liveAuthority';
import { createSharedPollingStore } from '../lib/sharedPollingStore';

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
  asOf: '', engineVersion: 'visibility-guard-v1', visibilityLevel: 'minimal',
  blockedActions: ['ENTER', 'ADD'],
  warnings: [{ code: 'VISIBILITY_AUTHORITY_UNAVAILABLE',
    messageJa: '検知範囲を確認できないため新規・追加を停止' }],
  limitations: ['Visibility Guardを取得できません。'], structuralGapCount: 0,
  coverageLineJa: '検知範囲を確認できません。新規・追加は停止します。',
  confidenceCap: 0.25, reasonCodes: ['VISIBILITY_AUTHORITY_UNAVAILABLE'],
};

interface State { data: VisibilityGuard; authority: string; error: string | null; }

const visibilityGuardStore = createSharedPollingStore<State>(
  { data: FALLBACK, authority: 'unavailable', error: null },
  (setState, getState) => {
    const backend = import.meta.env.VITE_ARGUS_BACKEND_URL as string | undefined;
    if (!backend) {
      setState({ data: FALLBACK, authority: 'unavailable', error: null });
      return () => {};
    }
    const url = backend.replace(/\/$/, '') + '/api/argus/visibility-guard';
    let alive = true;
    let acquisition: Promise<void> | null = null;
    let cancelExpiry = () => {};
    const controllers = new Set<AbortController>();

    function acquire(task: () => Promise<void>) {
      if (acquisition) return acquisition;
      const current = task().finally(() => {
        if (acquisition === current) acquisition = null;
      });
      acquisition = current;
      return current;
    }

    function accept(data: VisibilityGuard) {
      cancelExpiry();
      const authority = liveAuthorityState(data.asOf, 'visibilityGuard');
      if (authority !== 'fresh') {
        setState({ data: deauthorizeVisibilityGuard(data,
          authority === 'expired' ? 'snapshot_expired' : 'invalid_as_of'),
        authority, error: null });
        return;
      }
      setState({ data, authority: 'fresh', error: null });
      cancelExpiry = scheduleLiveAuthorityExpiry(data.asOf, 'visibilityGuard', () => {
        const current = getState();
        if (current.authority !== 'fresh') return;
        setState({ data: deauthorizeVisibilityGuard(current.data, 'snapshot_expired'),
          authority: 'expired', error: null });
      });
    }

    function fail(message: string) {
      cancelExpiry();
      const current = getState();
      setState({ data: deauthorizeVisibilityGuard(current.data, 'refresh_failed'),
        authority: 'refresh_failed', error: message });
    }

    async function load() {
      const controller = new AbortController();
      controllers.add(controller);
      try {
        const response = await fetch(url, { signal: controller.signal });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const data = await response.json() as VisibilityGuard;
        if (!alive || !data || !data.visibilityLevel) return;
        accept(data);
      } catch (err: unknown) {
        if (alive) fail(err instanceof Error ? err.message : String(err));
      } finally {
        controllers.delete(controller);
      }
    }

    const retained = getState();
    if (retained.authority === 'fresh') accept(retained.data);
    const interval = window.setInterval(() => void acquire(load), 30_000);
    const onVisible = () => { if (!document.hidden) void acquire(load); };
    document.addEventListener('visibilitychange', onVisible);
    void acquire(load);
    return () => {
      alive = false;
      cancelExpiry();
      for (const controller of controllers) controller.abort();
      controllers.clear();
      window.clearInterval(interval);
      document.removeEventListener('visibilitychange', onVisible);
    };
  },
);

export function useVisibilityGuard(): VisibilityGuard | null {
  return useSyncExternalStore(
    visibilityGuardStore.subscribe, visibilityGuardStore.getSnapshot,
    visibilityGuardStore.getSnapshot).data;
}
