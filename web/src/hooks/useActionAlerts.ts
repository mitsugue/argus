import { useSyncExternalStore } from 'react';
import { deauthorizeActionAlerts, liveAuthorityState,
  scheduleLiveAuthorityExpiry, type LiveAuthorityState } from '../domain/liveAuthority';
import { createSharedPollingStore } from '../lib/sharedPollingStore';
import { actionAlerts as MOCK_CARDS } from '../mock/dashboard';
import type { AssetActionCard } from '../types/dashboard';
import type { ActionKey } from '../types/action';

// Legacy per-asset-class posture evidence from /api/argus/action-alerts (alerts-v1).
// Backend action strings remain for compatibility but never become SDA authority.
export type ConnPhase = 'connecting' | 'live' | 'partial' | 'mock';

const TO_KEY: Record<string, ActionKey> = {
  EXIT: 'EXIT', TRIM: 'TRIM', WAIT: 'WAIT',
  'WAIT FOR PULLBACK': 'WAIT_FOR_PULLBACK', 'BUY DIP': 'BUY_DIP',
  ADD: 'ADD', HOLD: 'HOLD',
};

interface BackendCard {
  assetClass: string; displayName: string; action: string;
  confidence: 'low' | 'med' | 'high'; risk: 'low' | 'med' | 'high';
  reasonJa: string; dataPoints: string[]; nextConditionJa: string;
  status: 'live' | 'partial';
  authorityRole?: 'EVIDENCE_ONLY';
  finalDecisionAuthorityActive?: false;
}

interface Snapshot {
  status: ConnPhase; asOf: string; engineVersion: string;
  posture: string; cards: BackendCard[];
  authorityRole?: 'EVIDENCE_ONLY';
  finalDecisionAuthorityActive?: false;
}

interface State {
  cards: AssetActionCard[];
  posture: string | null;
  phase: ConnPhase;
  loading: boolean;
  asOf: string | null;
  error: string | null;
  authority: LiveAuthorityState | 'unavailable' | 'refresh_failed';
}

const SAFE_FALLBACK = deauthorizeActionAlerts(MOCK_CARDS, 'refresh_failed');
const INITIAL_STATE: State = {
  cards: SAFE_FALLBACK, posture: 'EVENT_WAIT', phase: 'connecting', loading: true,
  asOf: null, error: null, authority: 'unavailable',
};

const actionAlertsStore = createSharedPollingStore<State>(
  INITIAL_STATE,
  (setState, getState) => {
    const backend = import.meta.env.VITE_ARGUS_BACKEND_URL;
    if (!backend) {
      setState({ cards: SAFE_FALLBACK, posture: 'EVENT_WAIT', phase: 'mock',
        loading: false, asOf: null, error: null, authority: 'unavailable' });
      return () => {};
    }
    const url = backend.replace(/\/$/, '') + '/api/argus/action-alerts';
    let cancelled = false;
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

    function expire(reason: 'snapshot_expired' | 'invalid_as_of' | 'refresh_failed',
                    message: string | null) {
      cancelExpiry();
      const current = getState();
      setState({ ...current,
        cards: deauthorizeActionAlerts(current.cards, reason), posture: 'EVENT_WAIT',
        phase: current.phase === 'mock' ? 'mock' : 'partial', loading: false,
        error: message, authority: reason === 'refresh_failed' ? 'refresh_failed'
          : reason === 'invalid_as_of' ? 'invalid' : 'expired' });
    }

    function accept(data: Snapshot) {
      cancelExpiry();
      const cards: AssetActionCard[] = (Array.isArray(data.cards) ? data.cards : []).map((c) => ({
        assetClass: c.assetClass as AssetActionCard['assetClass'],
        displayName: c.displayName,
        action: TO_KEY[c.action] ?? 'WAIT',
        confidence: c.confidence,
        risk: c.risk,
        reason: c.reasonJa,
        dataPoints: c.dataPoints,
        nextCondition: c.nextConditionJa,
        authorityRole: 'EVIDENCE_ONLY',
        finalDecisionAuthorityActive: false,
      }));
      const authority = liveAuthorityState(data.asOf, 'actionAlerts');
      if (authority !== 'fresh') {
        setState({ cards: deauthorizeActionAlerts(cards,
          authority === 'expired' ? 'snapshot_expired' : 'invalid_as_of'),
        posture: 'EVENT_WAIT', phase: 'partial', loading: false, asOf: data.asOf,
        error: null, authority });
        return;
      }
      setState({ cards, posture: data.posture, phase: data.status, loading: false,
        asOf: data.asOf, error: null, authority: 'fresh' });
      cancelExpiry = scheduleLiveAuthorityExpiry(data.asOf, 'actionAlerts',
        () => expire('snapshot_expired', null));
    }

    async function load() {
      const ctrl = new AbortController();
      controllers.add(ctrl);
      const timer = window.setTimeout(() => ctrl.abort(), 9_000);
      try {
        const r = await fetch(url, { signal: ctrl.signal });
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const d = (await r.json()) as Snapshot;
        if (!cancelled) accept(d);
      } catch (err: unknown) {
        if (!cancelled) expire('refresh_failed', err instanceof Error ? err.message : String(err));
      } finally {
        window.clearTimeout(timer);
        controllers.delete(ctrl);
      }
    }

    const retained = getState();
    if (retained.authority === 'fresh') {
      const state = liveAuthorityState(retained.asOf, 'actionAlerts');
      if (state === 'fresh') {
        cancelExpiry = scheduleLiveAuthorityExpiry(retained.asOf, 'actionAlerts',
          () => expire('snapshot_expired', null));
      } else {
        expire(state === 'expired' ? 'snapshot_expired' : 'invalid_as_of', null);
      }
    }
    const interval = window.setInterval(() => void acquire(load), 30_000);
    const onVisible = () => { if (!document.hidden) void acquire(load); };
    document.addEventListener('visibilitychange', onVisible);
    void acquire(load);
    return () => {
      cancelled = true;
      cancelExpiry();
      for (const controller of controllers) controller.abort();
      controllers.clear();
      window.clearInterval(interval);
      document.removeEventListener('visibilitychange', onVisible);
    };
  },
);

export function useActionAlerts(): State {
  return useSyncExternalStore(
    actionAlertsStore.subscribe, actionAlertsStore.getSnapshot, actionAlertsStore.getSnapshot);
}
