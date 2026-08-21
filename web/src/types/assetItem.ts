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
  // Holdings (v10.0 Portfolio Exposure). Device-local only (localStorage) —
  // ARGUS never uploads position sizes anywhere.
  quantity?: number;   // shares / coins held
  avgCost?: number;    // average acquisition price (native currency)
  memo?: string;
  createdAt: number;
  updatedAt: number;
}

// Owner-facing groups, always displayed in this order.
export type GenreKey = 'jp' | 'us' | 'funds' | 'crypto';

export interface Genre { key: GenreKey; title: string; }

export const GENRES: Genre[] = [
  { key: 'jp', title: '日本株' },
  { key: 'us', title: '米国株' },
  { key: 'funds', title: '投資信託' },
  { key: 'crypto', title: '仮想通貨' },
];

export function genreOf(a: AssetItem): GenreKey {
  if (a.market === 'JP') return 'jp';
  if (a.market === 'US') return 'us';
  if (a.market === 'CRYPTO') return 'crypto';
  return 'funds'; // CORE / FUND / MANUAL / core_fund / manual_fund
}
