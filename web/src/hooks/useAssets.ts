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
  move: (id: string, dir: -1 | 1) => void;
  toggle: (id: string) => void;
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
      return [...cur, mk(a.market, a.assetType, a.source, symbol, displayName, a.displayNameJa, { memo: a.memo })];
    });
    return created;
  }, []);

  const remove = useCallback((id: string) => setAssets((cur) => cur.filter((x) => x.id !== id)), []);

  const move = useCallback((id: string, dir: -1 | 1) => {
    setAssets((cur) => {
      const i = cur.findIndex((x) => x.id === id);
      const j = i + dir;
      if (i < 0 || j < 0 || j >= cur.length) return cur;
      const next = cur.slice();
      [next[i], next[j]] = [next[j], next[i]];
      return next.map((x, k) => ({ ...x, sortOrder: k }));
    });
  }, []);

  const toggle = useCallback((id: string) =>
    setAssets((cur) => cur.map((x) => (x.id === id ? { ...x, enabled: !x.enabled, updatedAt: now() } : x))), []);

  const reset = useCallback(() => setAssets(defaults()), []);

  return { assets, add, remove, move, toggle, reset };
}
