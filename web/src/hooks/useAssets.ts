import { useCallback, useEffect, useState } from 'react';
import type { AssetItem, AssetMarket, AssetType, AssetSource } from '../types/assetItem';

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
    if (!raw) return defaults();
    const parsed = JSON.parse(raw) as AssetItem[];
    if (!Array.isArray(parsed) || parsed.length === 0) return defaults();
    _seq = Math.max(_seq, ...parsed.map((a) => a.sortOrder + 1));
    return parsed;
  } catch {
    return defaults();
  }
}

function persist(items: AssetItem[]) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(items));
  } catch {
    /* ignore quota / private-mode errors */
  }
}

export interface UseAssets {
  assets: AssetItem[];
  add: (a: { market: AssetMarket; assetType: AssetType; source: AssetSource; symbol: string; displayName: string; displayNameJa?: string; memo?: string }) => string | null;
  remove: (id: string) => void;
  reorderGenre: (orderedIds: string[]) => void;
  toggle: (id: string) => void;
  /** Set/clear one asset's holding (quantity & average cost). Pass
      null/undefined to clear a field. Device-local only — never uploaded. */
  updateHolding: (id: string, h: { quantity?: number | null; avgCost?: number | null }) => void;
  reset: () => void;
}

export function useAssets(): UseAssets {
  const [assets, setAssets] = useState<AssetItem[]>(() => (typeof window === 'undefined' ? [] : load()));

  useEffect(() => { persist(assets); }, [assets]);

  const add: UseAssets['add'] = useCallback((a) => {
    const symbol = a.symbol.trim();
    const displayName = a.displayName.trim();
    if (!symbol || !displayName) return null;            // validate non-empty
    const id = mkId(a.market, symbol);
    let created: string | null = id;
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

  const remove = useCallback((id: string) => setAssets((cur) => cur.filter((x) => x.id !== id)), []);

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

  const toggle = useCallback((id: string) =>
    setAssets((cur) => cur.map((x) => (x.id === id ? { ...x, enabled: !x.enabled, updatedAt: now() } : x))), []);

  const updateHolding: UseAssets['updateHolding'] = useCallback((id, h) =>
    setAssets((cur) => cur.map((x) => {
      if (x.id !== id) return x;
      const next = { ...x, updatedAt: now() };
      const setNum = (key: 'quantity' | 'avgCost', v: number | null | undefined) => {
        if (v == null || !Number.isFinite(v) || v < 0) delete next[key];
        else next[key] = v;
      };
      if ('quantity' in h) setNum('quantity', h.quantity);
      if ('avgCost' in h) setNum('avgCost', h.avgCost);
      return next;
    })), []);

  const reset = useCallback(() => setAssets(defaults()), []);

  return { assets, add, remove, reorderGenre, toggle, updateHolding, reset };
}
