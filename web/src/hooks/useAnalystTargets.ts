import { useSyncExternalStore } from 'react';
import { createSharedPollingStore } from '../lib/sharedPollingStore';
import { scheduleVisibleInterval, subscribeInitialVisibleRead } from '../lib/pollingPolicy';
import { validAnalystTarget, type AnalystTarget } from '../domain/assetOutlook';
import { validAssetEarnings, type AssetEarnings } from '../domain/assetEarnings';
export type { AnalystTarget } from '../domain/assetOutlook';

export type AnalystTargetsState = {
  items: Record<string, AnalystTarget>;
  earnings: Record<string, AssetEarnings>;
  availability: Record<string, { status: string; lastAttemptAt?: string | null }>;
  loading: boolean; refreshFailed: boolean;
};
const store = createSharedPollingStore<AnalystTargetsState>(
  { items: {}, earnings: {}, availability: {}, loading: true, refreshFailed: false },
  (set, get) => {
    const base = (import.meta.env.VITE_ARGUS_BACKEND_URL as string | undefined)?.replace(/\/$/, '') ?? '';
    if (!base) { set({ ...get(), loading: false, refreshFailed: true }); return () => {}; }
    let alive = true;
    let flight: Promise<void> | null = null;
    const controller = new AbortController();
    async function load() {
      try {
        const response = await fetch(`${base}/api/argus/analyst-targets`, { cache: 'no-store', signal: controller.signal });
        if (!response.ok) throw new Error('analyst_snapshot_unavailable');
        const body = await response.json();
        if (body?.actionAuthority !== false || !body.items || typeof body.items !== 'object' || Array.isArray(body.items)) {
          throw new Error('analyst_snapshot_invalid');
        }
        const items = Object.fromEntries(Object.entries(body.items).filter(([key, row]) => validAnalystTarget(row, key)));
        const earnings = Object.fromEntries(Object.entries(body.earningsItems ?? {}).filter(([key, row]) => validAssetEarnings(row, key)));
        const availability = Object.fromEntries(Object.entries(body.availability ?? {}).filter(([, value]) =>
          value && typeof value === 'object' && typeof (value as { status?: unknown }).status === 'string'));
        if (alive) set({ items: items as Record<string, AnalystTarget>, earnings: earnings as Record<string, AssetEarnings>, availability: availability as AnalystTargetsState['availability'],
          loading: false, refreshFailed: !!body.lastError && body.lastError !== 'partial_target_fetch_failed' });
      } catch {
        if (alive) set({ ...get(), loading: false, refreshFailed: true });
      }
    }
    const acquire = () => { flight ??= load().finally(() => { flight = null; }); };
    // All cards share one cache read; no provider/AI request and no burst on app resume.
    const stopInterval = scheduleVisibleInterval(acquire, 5 * 60_000);
    const stopInitial = subscribeInitialVisibleRead(acquire);
    acquire();
    return () => { alive = false; controller.abort(); stopInterval(); stopInitial(); };
  },
);
export function useAnalystTargetState(): AnalystTargetsState {
  return useSyncExternalStore(store.subscribe, store.getSnapshot, store.getSnapshot);
}
export function useAnalystTargets(): Record<string, AnalystTarget> { return useAnalystTargetState().items; }
