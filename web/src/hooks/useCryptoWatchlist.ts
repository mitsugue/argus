import { useSyncExternalStore } from 'react';
import { cryptoQuoteDecisionUsable, scheduleLiveAuthorityExpiry } from '../domain/liveAuthority';
import { createSharedPollingStore, type SharedPollingStore } from '../lib/sharedPollingStore';
import type { CryptoQuote, CryptoWatchlistSnapshot } from '../types/crypto';

export type CryptoPhase = 'connecting' | 'live' | 'partial' | 'mock';

interface State {
  byId: Record<string, CryptoQuote>;
  phase: CryptoPhase;
  asOf: string | null;
  diagnosticById: Record<string, CryptoQuote>;
  error: string | null;
  authority: 'fresh' | 'unavailable' | 'expired' | 'refresh_failed';
}

const ATTEMPT_TIMEOUT_MS = 9_000;
const cryptoStores = new Map<string, SharedPollingStore<State>>();

function cryptoStore(key: string): SharedPollingStore<State> {
  const existing = cryptoStores.get(key);
  if (existing) return existing;
  const store = createSharedPollingStore<State>(
    { byId: {}, diagnosticById: {}, phase: 'connecting', asOf: null,
      error: null, authority: 'unavailable' },
    (setState, getState) => {
      if (!key) {
        setState({ byId: {}, diagnosticById: {}, phase: 'live', asOf: null,
          error: null, authority: 'unavailable' });
        return () => {};
      }
      const backend = import.meta.env.VITE_ARGUS_BACKEND_URL;
      if (!backend) {
        setState({ byId: {}, diagnosticById: {}, phase: 'mock', asOf: null,
          error: null, authority: 'unavailable' });
        return () => {};
      }
      const url = backend.replace(/\/$/, '')
        + '/api/argus/crypto-watchlist?ids=' + encodeURIComponent(key);
      let cancelled = false;
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

      function expire() {
        const current = getState();
        cancelExpiries();
        setState({ ...current, byId: {}, phase: 'partial', authority: 'expired' });
      }

      function accept(data: CryptoWatchlistSnapshot) {
        cancelExpiries();
        const diagnosticById: Record<string, CryptoQuote> = {};
        const byId: Record<string, CryptoQuote> = {};
        for (const quote of Array.isArray(data.quotes) ? data.quotes : []) {
          diagnosticById[quote.id] = quote;
          if (data.provider === 'coingecko' && cryptoQuoteDecisionUsable(quote)) {
            byId[quote.id] = { ...quote, decisionUsable: true };
          }
        }
        const allRequestedUsable = Object.keys(byId).length === key.split(',').length;
        setState({ byId, diagnosticById,
          phase: allRequestedUsable ? 'live' : Object.keys(diagnosticById).length ? 'partial' : 'mock',
          asOf: Object.values(byId).map((quote) => quote.sourceTimestamp ?? '')
            .sort().at(-1) || null,
          error: null, authority: allRequestedUsable ? 'fresh' : 'unavailable' });
        if (Object.keys(byId).length) {
          const cancels = Object.values(byId).map((quote) =>
            scheduleLiveAuthorityExpiry(quote.sourceTimestamp, 'cryptoQuote', expire));
          cancelExpiries = () => cancels.forEach((cancel) => cancel());
        }
      }

      function fail(message: string) {
        const current = getState();
        cancelExpiries();
        setState({ ...current, byId: {}, phase: 'partial', error: message,
          authority: 'refresh_failed' });
      }

      async function fetchOnce() {
        const controller = new AbortController();
        controllers.add(controller);
        const timer = window.setTimeout(() => controller.abort(), ATTEMPT_TIMEOUT_MS);
        try {
          const response = await fetch(url, { signal: controller.signal });
          if (!response.ok) throw new Error(`HTTP ${response.status}`);
          const data = await response.json() as CryptoWatchlistSnapshot;
          if (!cancelled) accept(data);
        } catch (err: unknown) {
          if (!cancelled) fail(err instanceof Error ? err.message : String(err));
        } finally {
          window.clearTimeout(timer);
          controllers.delete(controller);
        }
      }

      const retained = getState();
      if (retained.authority === 'fresh') accept({
        status: 'live', asOf: retained.asOf, provider: 'coingecko',
        quotes: Object.values(retained.diagnosticById),
      });
      const interval = window.setInterval(() => void acquire(fetchOnce), 30_000);
      const onVisible = () => { if (!document.hidden) void acquire(fetchOnce); };
      document.addEventListener('visibilitychange', onVisible);
      void acquire(fetchOnce);
      return () => {
        cancelled = true;
        cancelExpiries();
        for (const controller of controllers) controller.abort();
        controllers.clear();
        window.clearInterval(interval);
        document.removeEventListener('visibilitychange', onVisible);
      };
    },
  );
  cryptoStores.set(key, store);
  return store;
}

/**
 * Live USD quotes for the watched crypto assets via the backend
 * `/api/argus/crypto-watchlist?ids=…` (CoinGecko, keyless). `ids` are
 * CoinGecko ids (from each asset's `coingecko:<id>` memo). No mock prices on
 * failure — callers render the honest "not connected" placeholder instead.
 */
export function useCryptoWatchlist(ids: string[]): State {
  const key = ids.slice().sort().join(',');
  const store = cryptoStore(key);
  return useSyncExternalStore(store.subscribe, store.getSnapshot, store.getSnapshot);
}
