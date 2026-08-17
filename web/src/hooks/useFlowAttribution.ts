import { useSyncExternalStore } from 'react';
import { deauthorizeFlowRecords, liveAuthorityState,
  scheduleLiveAuthorityExpiry, type LiveAuthorityState } from '../domain/liveAuthority';
import { createSharedPollingStore } from '../lib/sharedPollingStore';

// V11.7.0 Big Money / Flow Attribution — evidence-based classification of WHO is
// likely behind a move (大口買い集め/買い戻し/個人追随/売り抜け/狼狽…), always in
// 可能性/推定 vocabulary. Direct evidence is separated from inference and the
// missing evidence is always visible. Context only — NEVER a trade instruction.

export interface FlowAttribution {
  schemaVersion: string;
  id: string;
  symbol: string;
  market: string;
  name?: string;
  asOf: string;
  changePct: number | null;
  volumeRatio: number | null;
  flowClass: string;
  flowClassJa: string;
  direction: 'inflow' | 'outflow' | 'mixed' | 'neutral' | 'unknown';
  confidence: number;
  evidenceScore: number;
  riskScore: number;
  directness: 'direct_evidence' | 'inferred' | 'weak_context' | 'insufficient';
  directnessJa: string;
  evidence: Record<string, string | null>;
  missingEvidence: string[];
  reasonCodes: string[];
  ownerReadableWhyJa: string;
  checkNextJa: string;
  actionImplication: 'investigate' | 'wait_for_confirmation' | 'avoid_chase'
    | 'monitor' | 'caution' | 'no_action';
  actionImplicationJa: string;
  sourceLimitNote: string;
  complianceNote: string;
  /** v11.10.0: JP records carry the supply/demand read as supporting evidence. */
  supplyDemand?: { rank: string; conditionJa: string; chips: string[];
    readabilityLabelJa: string; supportNoteJa: string; confidence: number };
}

export const FLOW_TONE: Record<string, string> = {
  inflow: 'var(--value-positive)', outflow: 'var(--value-negative)',
  mixed: 'var(--amber, #fbbf24)', neutral: 'var(--text-muted)', unknown: 'var(--text-faint)',
};
export const ACTION_TONE: Record<string, string> = {
  avoid_chase: 'var(--value-negative)', caution: 'var(--value-negative)',
  investigate: 'var(--accent)', wait_for_confirmation: 'var(--amber, #fbbf24)',
  monitor: 'var(--text-muted)', no_action: 'var(--text-faint)',
};

interface ListState {
  records: FlowAttribution[];
  loading: boolean;
  error: string | null;
  asOf: string | null;
  authority: LiveAuthorityState | 'unavailable' | 'refresh_failed';
}

interface FlowPayload { asOf?: string; records?: FlowAttribution[]; }

const POLL_MS = 5 * 60_000;
const flowAttributionStore = createSharedPollingStore<ListState>(
  { records: [], loading: true, error: null, asOf: null, authority: 'unavailable' },
  (setState, getState) => {
    const backend = import.meta.env.VITE_ARGUS_BACKEND_URL as string | undefined;
    if (!backend) {
      setState({ records: [], loading: false, error: null, asOf: null,
        authority: 'unavailable' });
      return () => {};
    }
    const url = `${backend.replace(/\/$/, '')}/api/argus/flow-attribution`;
    let alive = true;
    let acquisition: Promise<void> | null = null;
    let cancelExpiries = () => {};
    const controllers = new Set<AbortController>();

    function acquire(task: () => Promise<void>) {
      if (acquisition) return acquisition;
      const current = task().finally(() => {
        if (acquisition === current) acquisition = null;
      });
      acquisition = current;
      return current;
    }

    async function fetchPayload(): Promise<FlowPayload> {
      const controller = new AbortController();
      controllers.add(controller);
      try {
        const response = await fetch(url, { signal: controller.signal });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return await response.json() as FlowPayload;
      } finally {
        controllers.delete(controller);
      }
    }

    function expire(reason: 'snapshot_expired' | 'invalid_as_of' | 'refresh_failed',
                    error: string | null) {
      const current = getState();
      if (current.authority === 'unavailable') return;
      cancelExpiries();
      setState({ ...current, records: deauthorizeFlowRecords(current.records, reason),
        loading: false, error, authority: reason === 'refresh_failed'
          ? 'refresh_failed' : reason === 'invalid_as_of' ? 'invalid' : 'expired' });
    }

    function accept(payload: FlowPayload) {
      cancelExpiries();
      const raw = Array.isArray(payload.records) ? payload.records : [];
      const topState = liveAuthorityState(payload.asOf, 'flowAttribution');
      if (topState !== 'fresh') {
        const reason = topState === 'expired' ? 'snapshot_expired' : 'invalid_as_of';
        setState({ records: deauthorizeFlowRecords(raw, reason), loading: false,
          error: null, asOf: payload.asOf ?? null, authority: topState });
        return;
      }
      if (!raw.length) {
        setState({ records: [], loading: false, error: null,
          asOf: payload.asOf ?? null, authority: 'unavailable' });
        return;
      }
      const records = raw.map((record) => {
        const state = liveAuthorityState(record.asOf, 'flowAttribution');
        return state === 'fresh' ? record : deauthorizeFlowRecords(
          [record], state === 'expired' ? 'snapshot_expired' : 'invalid_as_of')[0];
      });
      setState({ records, loading: false, error: null,
        asOf: payload.asOf ?? null, authority: 'fresh' });
      const cancels = [payload.asOf, ...raw.map((record) => record.asOf)]
        .map((asOf) => scheduleLiveAuthorityExpiry(asOf, 'flowAttribution',
          () => expire('snapshot_expired', null)));
      cancelExpiries = () => cancels.forEach((cancel) => cancel());
    }

    async function load() {
      try {
        const payload = await fetchPayload();
        if (alive) accept(payload);
      } catch (err: unknown) {
        if (!alive) return;
        const message = err instanceof Error ? err.message : String(err);
        if (getState().records.length) expire('refresh_failed', message);
        else setState({ records: [], loading: false, error: message, asOf: null,
          authority: 'unavailable' });
      }
    }

    const retained = getState();
    if (retained.authority === 'fresh') {
      accept({ asOf: retained.asOf ?? undefined, records: retained.records });
    }
    const interval = window.setInterval(() => void acquire(load), POLL_MS);
    const onVisible = () => { if (!document.hidden) void acquire(load); };
    document.addEventListener('visibilitychange', onVisible);
    void acquire(load);
    return () => {
      alive = false;
      cancelExpiries();
      for (const controller of controllers) controller.abort();
      controllers.clear();
      window.clearInterval(interval);
      document.removeEventListener('visibilitychange', onVisible);
    };
  },
);

/** Today's material watchlist movers, classified (cached-only backend; 5-min poll). */
export function useFlowAttributionList(): ListState {
  return useSyncExternalStore(
    flowAttributionStore.subscribe, flowAttributionStore.getSnapshot,
    flowAttributionStore.getSnapshot);
}
