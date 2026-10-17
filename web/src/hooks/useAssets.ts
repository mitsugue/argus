import {
  createContext, createElement, useCallback, useContext, useEffect, useMemo, useRef, useState,
  type ReactNode,
} from 'react';
import type { AssetItem, AssetMarket, AssetType, AssetSource, HoldingUpdate } from '../types/assetItem';
import { markLocalEdit } from '../lib/vault';
import { watchlistProjection } from '../domain/watchlistProjection';
import { recordTombstone } from '../lib/assetMerge';
import { stageRegistrationChanges, commitRegistrationChanges, cancelStagedRegistration, setWatchlistSyncState } from '../lib/watchlistAutoSync';

import { OWNER_AUTH_REQUIRED } from '../lib/ownerSession';
import { stageAccountRegistrations, commitAccountRegistrations, cancelAccountRegistrations } from '../lib/accountWatchlistSync';

const STORAGE_KEY = 'argus.assets.v1';
const MAX_ASSETS = 50;

let _seq = 0;
const now = () => Date.now();
const mkId = (market: string, symbol: string) => `${market.toLowerCase()}-${symbol.toLowerCase()}`;

function mk(
  market: AssetMarket, assetType: AssetType, source: AssetSource,
  symbol: string, displayName: string, displayNameJa: string | undefined,
  extra: Partial<AssetItem> = {},
): AssetItem {
  const t = now();
  return {
    id: mkId(market, symbol), symbol, displayName, displayNameJa,
    market, assetType, source, enabled: true, sortOrder: _seq++,
    createdAt: t, updatedAt: t, ...extra,
  };
}

// Default seed. JP names in Japanese (8058 = 三菱商事, verified — NOT 三菱重工).
// SYNC SAFETY (v11.3.3): a fresh/evicted device seeds these with updatedAt=0 so
// the per-item merge NEVER lets a factory copy beat another device's real item,
// holdings, or deletion tombstone. reset() alone stamps fresh times (it must win
// over the tombstones it just recorded).
function seedZero(items: AssetItem[]): AssetItem[] {
  return items.map((a) => ({ ...a, createdAt: 0, updatedAt: 0 }));
}

function defaults(): AssetItem[] {
  return [
    mk('JP', 'jp_equity', 'jquants', '8058', '三菱商事', '三菱商事'),
    mk('JP', 'jp_equity', 'jquants', '9984', 'ソフトバンクグループ', 'ソフトバンクグループ'),
    mk('JP', 'jp_equity', 'jquants', '5801', '古河電気工業', '古河電気工業'),
    mk('JP', 'jp_equity', 'jquants', '5803', 'フジクラ', 'フジクラ'),
    mk('JP', 'jp_equity', 'jquants', '6584', '三櫻工業', '三櫻工業'),
    mk('JP', 'jp_equity', 'jquants', '285A', 'キオクシアホールディングス', 'キオクシアホールディングス'),
    mk('JP', 'jp_equity', 'jquants', '9501', '東京電力ホールディングス', '東京電力ホールディングス'),
    mk('US', 'us_equity', 'twelvedata', 'NVDA', 'NVIDIA', undefined),
    mk('US', 'us_equity', 'twelvedata', 'AAPL', 'Apple', undefined),
    mk('US', 'us_equity', 'twelvedata', 'TSLA', 'Tesla', undefined),
    mk('US', 'us_equity', 'twelvedata', 'META', 'Meta Platforms', undefined),
    mk('CORE', 'manual_fund', 'manual', 'EMAXIS-ACWI', 'eMAXIS Slim 全世界株式', 'eMAXIS Slim 全世界株式', { memo: '長期コア(積立)' }),
    mk('CORE', 'manual_fund', 'manual', 'EMAXIS-SP500', 'eMAXIS Slim 米国株式(S&P500)', 'eMAXIS Slim 米国株式(S&P500)', { memo: '長期コア(積立)' }),
    mk('CRYPTO', 'crypto', 'manual', 'BTC', 'Bitcoin', undefined, { memo: 'coingecko:bitcoin' }),
    mk('CRYPTO', 'crypto', 'manual', 'ETH', 'Ethereum', undefined, { memo: 'coingecko:ethereum' }),
  ];
}

function load(): AssetItem[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return seedZero(defaults());
    const parsed = JSON.parse(raw) as AssetItem[];
    if (!Array.isArray(parsed)) return seedZero(defaults());
    _seq = Math.max(_seq, ...parsed.map((a) => a.sortOrder + 1));
    return parsed;
  } catch {
    return seedZero(defaults());
  }
}

function persist(items: AssetItem[], expected: AssetItem[]): boolean {
  try {
    const existingRaw = localStorage.getItem(STORAGE_KEY);
    if (existingRaw !== null) {
      const existing = JSON.parse(existingRaw);
      if (!Array.isArray(existing) || existing.some(x => !x || typeof x.id !== 'string'
        || typeof x.symbol !== 'string' || typeof x.market !== 'string')) return false;
      // A stale tab must not replace a registration or archived field written
      // by another tab/restore since this view was loaded.
      if (JSON.stringify(existing) !== JSON.stringify(expected)) return false;
    }
    localStorage.setItem(STORAGE_KEY, JSON.stringify(items));
    return true;
  } catch {
    return false;
  }
}

export interface UseAssets {
  assets: AssetItem[];
  /** Recovery-only raw records; never feed active analysis or AI. */
  archivedAssets: AssetItem[];
  add: (a: { market: AssetMarket; assetType: AssetType; source: AssetSource; symbol: string; displayName: string; displayNameJa?: string; memo?: string }, options?: { restoreOnly?: boolean }) => string | null;
  remove: (id: string) => void;
  reorderGenre: (orderedIds: string[]) => void;
  toggle: (id: string) => void;
  /** Compatibility for explicit restoration of legacy portfolio backups only.
      Product screens must not use this to enter new holdings. */
  updateHolding: (id: string, h: HoldingUpdate) => void;
  reset: () => void;
}

const AssetsContext = createContext<UseAssets | null>(null);

function useAssetsStore(): UseAssets {
  const [assets, setAssets] = useState<AssetItem[]>(() => (typeof window === 'undefined' ? [] : load()));

  const firstPersist = useRef(true);
  const registrationEdit = useRef(false);
  const restoredKeys = useRef(new Set<string>());
  const lastPersisted = useRef(assets);
  useEffect(() => {
    if (firstPersist.current) {
      firstPersist.current = false;
      if (persist(assets, lastPersisted.current)) lastPersisted.current = assets;
      else setWatchlistSyncState({ kind: 'error', message: '端末への保存を確認できません。元の記録を保持しています' });
      return;
    }
    if (assets === lastPersisted.current) return;
    let pendingKey: string | null = null;
    let accountKey: string | null = null;
    try {
      accountKey = stageAccountRegistrations(lastPersisted.current, assets);
      if (registrationEdit.current && !OWNER_AUTH_REQUIRED) pendingKey = stageRegistrationChanges(lastPersisted.current, assets, restoredKeys.current);
      if (!persist(assets, lastPersisted.current)) {
        cancelStagedRegistration(pendingKey);
        cancelAccountRegistrations(accountKey);
        throw Error('local_save_failed');
      }
      lastPersisted.current = assets;
      registrationEdit.current = false;
      restoredKeys.current.clear();
      markLocalEdit();
      commitRegistrationChanges(pendingKey);
      commitAccountRegistrations(accountKey);
    } catch {
      setWatchlistSyncState({ kind: 'error', message: '端末への保存を確認できません。他の画面の変更や空き容量を確認し、再読み込みしてください' });
    }
  }, [assets]);

  // Another device pushed newer data and the sync loop applied it to
  // localStorage → reload our in-memory copy.
  useEffect(() => {
    const onSynced = () => {
      firstPersist.current = true; registrationEdit.current = false; restoredKeys.current.clear();
      const restored = load(); lastPersisted.current = restored; setAssets(restored);
    };
    window.addEventListener('argus:data-synced', onSynced);
    return () => window.removeEventListener('argus:data-synced', onSynced);
  }, []);

  const add: UseAssets['add'] = useCallback((a, options) => {
    const symbol = a.symbol.trim();
    const displayName = a.displayName.trim();
    if (!symbol || !displayName) return null;            // validate non-empty
    const id = mkId(a.market, symbol);
    let created: string | null = id;
    const identity = `${a.market}:${symbol.toUpperCase()}`;
    if (options?.restoreOnly) restoredKeys.current.add(identity);
    else { registrationEdit.current = true; restoredKeys.current.delete(identity); }
    setAssets((cur) => {
      if (cur.length >= MAX_ASSETS) { created = null; return cur; }     // cap
      if (cur.some((x) => x.id === id)) { created = null; return cur; } // dedupe
      const item = mk(a.market, a.assetType, a.source, symbol, displayName, a.displayNameJa, { memo: a.memo });
      // New items float to the TOP of their genre: give the smallest sortOrder
      // (groups are sorted by sortOrder ascending).
      item.sortOrder = (cur.length ? Math.min(...cur.map((x) => x.sortOrder)) : 0) - 1;
      return [...cur, item];
    });
    return created;
  }, []);

  const remove = useCallback((id: string) => {
    registrationEdit.current = true;
    const item = lastPersisted.current.find(x => x.id === id);
    if (item) restoredKeys.current.delete(`${item.market}:${item.symbol.trim().toUpperCase()}`);
    recordTombstone(id);   // deletion must propagate to other devices (sync-v2)
    setAssets((cur) => cur.filter((x) => x.id !== id));
  }, []);

  // Reassign sortOrder for a genre's items in the given new order, reusing that
  // genre's existing sortOrder slots so other genres stay put.
  const reorderGenre = useCallback((orderedIds: string[]) => {
    setAssets((cur) => {
      const idset = new Set(orderedIds);
      const slots = cur.filter((a) => idset.has(a.id)).map((a) => a.sortOrder).sort((x, y) => x - y);
      const pos = new Map<string, number>();
      orderedIds.forEach((id, i) => pos.set(id, slots[i] ?? i));
      return cur.map((a) => (idset.has(a.id) ? { ...a, sortOrder: pos.get(a.id)!, updatedAt: now() } : a));
    });
  }, []);

  const toggle = useCallback((id: string) => {
    registrationEdit.current = true;
    const item = lastPersisted.current.find(x => x.id === id);
    if (item) restoredKeys.current.delete(`${item.market}:${item.symbol.trim().toUpperCase()}`);
    setAssets((cur) => cur.map((x) => (x.id === id ? { ...x, enabled: !x.enabled, updatedAt: now() } : x)));
  }, []);

  const updateHolding: UseAssets['updateHolding'] = useCallback((id, h) =>
    setAssets((cur) => { const items = cur.map((x) => {
      if (x.id !== id) return x;
      const next = { ...x };
      const setNum = (key: 'quantity' | 'avgCost', v: number | null | undefined) => {
        if (v == null || !Number.isFinite(v) || v < 0) delete next[key];
        else next[key] = v;
      };
      if ('quantity' in h) setNum('quantity', h.quantity);
      if ('avgCost' in h) setNum('avgCost', h.avgCost);
      for (const key of ['purchaseReason', 'holdingPeriod'] as const) {
        if (!(key in h)) continue;
        const value = h[key];
        if (value == null || !value.trim()) delete next[key];
        else if (value.length <= (key === 'purchaseReason' ? 1000 : 160)) next[key] = value.trim();
      }
      const unchanged = (['quantity', 'avgCost', 'purchaseReason', 'holdingPeriod'] as const)
        .every(key => next[key] === x[key]);
      return unchanged ? x : { ...next, updatedAt: now() };
    }); return items.every((item, index) => item === cur[index]) ? cur : items; }), []);

  const reset = useCallback(() => {
    registrationEdit.current = true; restoredKeys.current.clear();
    setAssets((cur) => {
    // reset = deliberate wipe: tombstone everything current so the old items
    // don't resurrect from another device. defaults() are created AFTER the
    // tombstones (newer updatedAt), so the seed list itself survives merges.
    cur.forEach((x) => recordTombstone(x.id));
    return defaults();
  }); }, []);

  const watchlist = useMemo(() => watchlistProjection(assets), [assets]);
  return { assets: watchlist, archivedAssets: assets, add, remove, reorderGenre, toggle, updateHolding, reset };
}

/**
 * One application-owned lifecycle for the protected asset store. Consumers
 * read the same in-memory value instead of mounting independent persistence
 * and argus:data-synced listeners.
 */
export function AssetsProvider({ children }: { children: ReactNode }) {
  const value = useAssetsStore();
  return createElement(AssetsContext.Provider, { value }, children);
}

export function useAssets(): UseAssets {
  const value = useContext(AssetsContext);
  if (!value) throw new Error('useAssets must be used within AssetsProvider');
  return value;
}
