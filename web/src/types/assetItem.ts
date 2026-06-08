// Unified asset model (v9.2.0). One model for JP/US equities, core/manual funds,
// and crypto — replacing the fixed JP/US split. User config (add/remove/reorder/
// enabled) is persisted in localStorage (per browser/device; no cross-device
// sync yet). Distinct from the legacy types/asset.ts (old bubble tree).

export type AssetMarket = 'JP' | 'US' | 'CRYPTO' | 'FUND' | 'CORE' | 'MANUAL';
export type AssetType =
  | 'jp_equity'
  | 'us_equity'
  | 'crypto'
  | 'listed_etf'
  | 'core_fund'
  | 'manual_fund';
export type AssetSource = 'jquants' | 'twelvedata' | 'coingecko' | 'manual' | 'mock';

export interface AssetItem {
  id: string;               // stable id, e.g. "jp-8058", "us-NVDA", "core-emaxis"
  symbol: string;
  displayName: string;
  displayNameJa?: string;
  market: AssetMarket;
  assetType: AssetType;
  source: AssetSource;
  enabled: boolean;
  sortOrder: number;
  // Optional core/fund fields (manual, no live NAV in v9.2.0).
  monthlyContribution?: number;
  targetAllocation?: number;
  currentAllocation?: number;
  memo?: string;
  createdAt: number;
  updatedAt: number;
}

export const ASSET_TAB = ['All', 'Japan', 'US', 'Core', 'Crypto'] as const;
export type AssetTab = (typeof ASSET_TAB)[number];

export function tabMatches(tab: AssetTab, a: AssetItem): boolean {
  switch (tab) {
    case 'All': return true;
    case 'Japan': return a.market === 'JP';
    case 'US': return a.market === 'US';
    case 'Core': return a.market === 'CORE' || a.market === 'FUND' || a.assetType === 'core_fund' || a.assetType === 'manual_fund';
    case 'Crypto': return a.market === 'CRYPTO';
  }
}
