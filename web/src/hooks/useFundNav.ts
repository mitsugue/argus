import { useSyncExternalStore } from 'react';
import { calendarDateExpiresAt, dailyFundNavDecisionUsable } from '../domain/liveQuote';
import { createSharedPollingStore, type SharedPollingStore } from '../lib/sharedPollingStore';
import type { AssetItem } from '../types/assetItem';

// 投信(基準価額) follow — daily NAV from 投信総合ライブラリー. A transport
// success does not renew the NAV date; stale/future/malformed rows are excluded
// from valuation authority and refresh failure clears decision prices.
export interface FundNav {
  code: string;
  name: string;
  navYen: number;
  changePct: number | null;
  date: string;
  status: string;
}

const MAX_NAV_AGE_DAYS = 7;

export function fundNavDecisionUsable(fund: FundNav, nowMs = Date.now()): boolean {
  return dailyFundNavDecisionUsable(fund, nowMs, MAX_NAV_AGE_DAYS);
}

/** Deterministic catalog match shared by Holdings, exposure, and FIRE views. */
export function fundNavForAsset(asset: AssetItem, funds: FundNav[]): FundNav | null {
  const symbol = asset.symbol.toUpperCase();
  const name = `${asset.displayName || ''} ${asset.displayNameJa || ''}`.toLowerCase();
  const matches = (keyword: string) =>
    symbol.includes(keyword) || name.includes(keyword.toLowerCase());
  for (const fund of funds) {
    if (!fundNavDecisionUsable(fund)) continue;
    const fundName = (fund.name || '').toLowerCase();
    if (fundName.includes('全世界')
      && (matches('ACWI') || name.includes('全世界') || name.includes('オルカン')
        || name.includes('オール'))) return fund;
    if (fundName.includes('s&p500')
      && (matches('SP500') || matches('S&P') || name.includes('米国'))) return fund;
    if (fundName.includes('国内')
      && (matches('N225') || matches('NIKKEI') || name.includes('国内')
        || name.includes('日経'))) return fund;
  }
  return null;
}

interface FundPayload { funds?: FundNav[]; }
interface State {
  funds: FundNav[];
  loading: boolean;
  error: string | null;
  authority: 'fresh' | 'unavailable' | 'expired' | 'refresh_failed';
}

const fundNavStores = new Map<string, SharedPollingStore<State>>();

function fundNavStore(codeKey: string): SharedPollingStore<State> {
  const existing = fundNavStores.get(codeKey);
  if (existing) return existing;
  const store = createSharedPollingStore<State>(
    { funds: [], loading: true, error: null, authority: 'unavailable' },
    (setState, getState) => {
      const backend = import.meta.env.VITE_ARGUS_BACKEND_URL as string | undefined;
      if (!backend) {
        setState({ funds: [], loading: false, error: null, authority: 'unavailable' });
        return () => {};
      }
      const query = codeKey ? `?codes=${encodeURIComponent(codeKey)}` : '';
      const url = `${backend.replace(/\/$/, '')}/api/argus/fund-nav${query}`;
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

      function expire() {
        cancelExpiry();
        const current = getState();
        setState({ ...current, funds: [], loading: false, authority: 'expired' });
      }

      function accept(payload: FundPayload) {
        cancelExpiry();
        const raw = Array.isArray(payload.funds) ? payload.funds : [];
        const funds = raw.filter((fund) => fundNavDecisionUsable(fund));
        if (!funds.length) {
          setState({ funds: [], loading: false, error: raw.length ? 'fund_nav_stale' : null,
            authority: 'unavailable' });
          return;
        }
        setState({ funds, loading: false, error: null, authority: 'fresh' });
        const deadline = Math.min(...funds.map((fund) =>
          calendarDateExpiresAt(fund.date, MAX_NAV_AGE_DAYS) ?? Date.now()));
        const delay = deadline - Date.now();
        if (delay <= 0) expire();
        else {
          const handle = window.setTimeout(expire, Math.min(delay + 1, 2_147_000_000));
          cancelExpiry = () => window.clearTimeout(handle);
        }
      }

      async function load() {
        const controller = new AbortController();
        controllers.add(controller);
        try {
          const response = await fetch(url, { signal: controller.signal });
          if (!response.ok) throw new Error(`HTTP ${response.status}`);
          const payload = await response.json() as FundPayload;
          if (alive) accept(payload);
        } catch (err: unknown) {
          if (!alive) return;
          cancelExpiry();
          setState({ funds: [], loading: false,
            error: err instanceof Error ? err.message : String(err),
            authority: 'refresh_failed' });
        } finally {
          controllers.delete(controller);
        }
      }

      const retained = getState();
      if (retained.authority === 'fresh') accept({ funds: retained.funds });
      const interval = window.setInterval(() => void acquire(load), 6 * 60 * 60_000);
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
  fundNavStores.set(codeKey, store);
  return store;
}

export function useFundNav(codes?: string[]): State {
  const codeKey = codes?.length ? codes.slice().sort().join(',') : '';
  const store = fundNavStore(codeKey);
  return useSyncExternalStore(store.subscribe, store.getSnapshot, store.getSnapshot);
}
