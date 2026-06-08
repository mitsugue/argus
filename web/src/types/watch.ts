import type { ActionKey } from './action';

// Watched name — what the user manually tracks. Distinct from action
// alerts (which are aggregated per asset class). Each row carries the
// scanner's AI action label so the user can scan urgency in one glance.

interface WatchBase {
  symbol: string;
  name: string;
  price: number;
  changePct: number;       // daily change %
  changeAbs: number;       // daily change in price units
  earningsDate?: string;   // ISO YYYY-MM-DD
  newsHeadline?: string;
  newsSource?: string;
  action: ActionKey;
  reason?: string;         // short scanner note backing the action
  updatedAt: number;
}

export interface WatchJP extends WatchBase {
  market: 'JP';
  volume: number;                  // shares traded today
  vwapDeltaPct?: number;           // price vs session VWAP, % (absent for live J-Quants rows — daily bars carry no VWAP)
  marginLong?: number;             // 信用買い残, units of 1k shares
  marginShort?: number;            // 信用売り残, units of 1k shares
  jsfBorrowed?: number;            // 日証金 借入残, units of 1k shares
  jsfLent?: number;                // 日証金 貸出残, units of 1k shares
}

export interface WatchUS extends WatchBase {
  market: 'US';
  premarketPct?: number;           // pre-market % change
  afterHoursPct?: number;          // after-hours % change
  guidance?: 'beat' | 'inline' | 'miss';
  sectorTrend?: 'up' | 'flat' | 'down';
  rateSensitivity?: 'low' | 'med' | 'high';
}

export type WatchEntry = WatchJP | WatchUS;

// ── Live Japan watchlist (J-Quants) ──────────────────────────────────
// Mirrors the backend /api/argus/japan-watchlist shape. Kept in sync by
// convention — if the endpoint's fields change, update this too.

export type JpQuoteStatus = 'live' | 'mock';

export interface JapanStockQuote {
  symbol: string;
  name: string;
  price: number;
  changeAbs: number;
  changePct: number;
  volume: number;
  date: string | null;
  status: JpQuoteStatus;
}

export interface JapanWatchlistSnapshot {
  status: JpQuoteStatus;       // 'live' if any stock is live, else 'mock'
  asOf: string | null;         // latest data date across stocks (freshness)
  stocks: JapanStockQuote[];
}
