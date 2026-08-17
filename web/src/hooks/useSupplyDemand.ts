import { useSyncExternalStore } from 'react';
import { deauthorizeSupplySignals, liveAuthorityState,
  scheduleLiveAuthorityExpiry, type LiveAuthorityState } from '../domain/liveAuthority';
import { createSharedPollingStore, type SharedPollingStore } from '../lib/sharedPollingStore';

// V11.10.0 Supply/Demand Intelligence (JP) — 「需給は良いのか悪いのか」に
// ランク+状態で答える。数値はエンジンが読み、生数値はevidence(UI折りたたみ)。
// 状態評価であり売買指示ではない。

export interface SupplyDemandSignal {
  schemaVersion: string;
  id: string;
  symbol: string;
  market: string;
  name?: string;
  asOf: string;
  dataDate: string | null;
  supplyDemandRank: 'S' | 'A' | 'B' | 'C' | 'D' | 'E' | 'Unknown';
  rankJa: string;
  /** v11.14.0: 水準は方向と別表示(改善中でも重い時はA/S不可) */
  supplyDemandLevel?: 'light' | 'normal' | 'heavy' | 'very_heavy' | 'unknown';
  levelJa?: string;
  rankCapReason?: string | null;
  condition: string;
  conditionJa: string;
  chips: string[];
  direction: 'improving' | 'worsening' | 'stable' | 'mixed' | 'unknown';
  confidence: number;
  readabilityLabelJa: string;
  ownerReadableWhyJa: string;
  checkNextJa: string;
  actionImplication: string;
  actionImplicationJa: string;
  directness: string;
  directnessJa: string;
  evidence: Record<string, unknown>;
  missingEvidence: string[];
  sourceLimitNote: string;
  complianceNote: string;
}

// v12.0.4 (owner request): C/Unknownがmuted/faintで「かなり暗い」— 全ランクを
// ダーク背景で読める明色に固定(状態の意味は不変・色だけ)。
export const RANK_TONE: Record<string, string> = {
  S: '#34d399', A: '#6ee7b7', B: '#67e8f9',
  C: '#e2e8f0', D: '#fbbf24', E: '#f87171',
  Unknown: '#94a3b8',
};

interface State {
  signals: SupplyDemandSignal[];
  loading: boolean;
  error: string | null;
  asOf: string | null;
  authority: LiveAuthorityState | 'unavailable' | 'refresh_failed';
}

interface SupplyPayload { asOf?: string; signals?: SupplyDemandSignal[]; }

const POLL_MS = 5 * 60_000;
const supplyStores = new Map<string, SharedPollingStore<State>>();

function supplyStore(extraSymbols: string): SharedPollingStore<State> {
  const existing = supplyStores.get(extraSymbols);
  if (existing) return existing;
  const store = createSharedPollingStore<State>(
    { signals: [], loading: true, error: null, asOf: null, authority: 'unavailable' },
    (setState, getState) => {
      const backend = import.meta.env.VITE_ARGUS_BACKEND_URL as string | undefined;
      if (!backend) {
        setState({ signals: [], loading: false, error: null, asOf: null,
          authority: 'unavailable' });
        return () => {};
      }
      const qs = extraSymbols ? `?symbols=${encodeURIComponent(extraSymbols)}` : '';
      const url = `${backend.replace(/\/$/, '')}/api/argus/supply-demand${qs}`;
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

      async function fetchPayload(): Promise<SupplyPayload> {
        const controller = new AbortController();
        controllers.add(controller);
        try {
          const response = await fetch(url, { signal: controller.signal });
          if (!response.ok) throw new Error(`HTTP ${response.status}`);
          return await response.json() as SupplyPayload;
        } finally {
          controllers.delete(controller);
        }
      }

      function expire(reason: 'snapshot_expired' | 'invalid_as_of' | 'refresh_failed',
                      error: string | null) {
        const current = getState();
        if (current.authority === 'unavailable') return;
        cancelExpiries();
        setState({ ...current, signals: deauthorizeSupplySignals(current.signals, reason),
          loading: false, error, authority: reason === 'refresh_failed'
            ? 'refresh_failed' : reason === 'invalid_as_of' ? 'invalid' : 'expired' });
      }

      function accept(payload: SupplyPayload) {
        cancelExpiries();
        const raw = Array.isArray(payload.signals) ? payload.signals : [];
        const topState = liveAuthorityState(payload.asOf, 'supplyDemand');
        if (topState !== 'fresh') {
          const reason = topState === 'expired' ? 'snapshot_expired' : 'invalid_as_of';
          setState({ signals: deauthorizeSupplySignals(raw, reason), loading: false,
            error: null, asOf: payload.asOf ?? null, authority: topState });
          return;
        }
        if (!raw.length) {
          setState({ signals: [], loading: false, error: null,
            asOf: payload.asOf ?? null, authority: 'unavailable' });
          return;
        }
        const signals = raw.map((signal) => {
          const state = liveAuthorityState(signal.asOf, 'supplyDemand');
          return state === 'fresh' ? signal : deauthorizeSupplySignals(
            [signal], state === 'expired' ? 'snapshot_expired' : 'invalid_as_of')[0];
        });
        setState({ signals, loading: false, error: null,
          asOf: payload.asOf ?? null, authority: 'fresh' });
        const cancels = [payload.asOf, ...raw.map((signal) => signal.asOf)]
          .map((asOf) => scheduleLiveAuthorityExpiry(asOf, 'supplyDemand',
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
          if (getState().signals.length) expire('refresh_failed', message);
          else setState({ signals: [], loading: false, error: message, asOf: null,
            authority: 'unavailable' });
        }
      }

      const retained = getState();
      if (retained.authority === 'fresh') {
        accept({ asOf: retained.asOf ?? undefined, signals: retained.signals });
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
  supplyStores.set(extraSymbols, store);
  return store;
}

/** v12.0.6 (owner: 保有銘柄の需給が出ない): extraSymbols = デバイスのウォッチリスト
 *  銘柄のカンマ結合(ソート済みの安定文字列)。サーバー固定リスト外の銘柄にも
 *  需給ランクを出す(サーバー側はcached-only・銘柄コードは保有情報ではない)。 */
export function useSupplyDemandList(extraSymbols?: string): State {
  const store = supplyStore(extraSymbols ?? '');
  return useSyncExternalStore(store.subscribe, store.getSnapshot, store.getSnapshot);
}
