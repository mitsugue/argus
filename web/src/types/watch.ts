import type { ActionKey } from './action';
import type {
  DelayClass,
  InstrumentType,
  LiveQuote,
  QuoteSession,
} from '../domain/liveQuote';

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
  // Action Label Engine v0 (optional — present when /api/argus/action-labels is wired):
  confidence?: number;     // 0..1
  signalRisk?: 'low' | 'medium' | 'high';
  nextConditionJa?: string; // kept in data; not always rendered in the compact row
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
  volume?: number;                 // shares traded (live Twelve Data rows)
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

export type JpQuoteStatus = 'live' | 'delayed' | 'unknown' | 'mock';
export type WatchSnapshotStatus = JpQuoteStatus | 'partial' | 'mixed';

export interface QuoteTruthFields {
  provider?: string | null;
  source?: string | null;
  sourceTimestamp?: string | number | null;
  exchangeTs?: string | number | null;
  updateTime?: string | number | null;
  receivedAt?: string | null;
  ageSec?: number | null;
  transportAgeSec?: number | null;
  delayClass?: DelayClass | string | null;
  session?: QuoteSession | string | null;
  entitlement?: string | null;
  realtimeEvidence?: boolean | null;
  instrumentType?: InstrumentType;
  quoteTruth?: LiveQuote;
}

export interface JapanStockQuote extends QuoteTruthFields {
  symbol: string;
  name: string;
  price: number;
  changeAbs: number;
  changePct: number;
  volume: number;
  date: string | null;
  status: JpQuoteStatus;
  /** Big-money flow (moomoo bridge, v10.2): 大口純流入/全売買代金 (-1..+1). */
  flow?: { bigNetRatio: number } | null;
}

export interface JapanWatchlistSnapshot {
  // 'live' only when every row has runtime-proven source freshness.
  status: WatchSnapshotStatus;
  asOf: string | null;         // latest data date across stocks (freshness)
  provider?: string;
  quoteFreshness?: {
    delayClass?: DelayClass | string | null;
    sourceAgeMedianSec?: number | null;
    sourceAgeP95Sec?: number | null;
    sourceTimestampCoverage?: number | null;
    note?: string | null;
  };
  stocks: JapanStockQuote[];
}

// ── Live US watchlist (Twelve Data) ──────────────────────────────────
// Mirrors the backend /api/argus/us-watchlist shape. Same per-stock shape as
// Japan; top-level status is 'live' only when ALL target symbols are live.

export interface USStockQuote extends QuoteTruthFields {
  symbol: string;
  name: string;
  price: number;
  changeAbs: number;
  changePct: number;
  volume: number;
  date: string | null;
  status: JpQuoteStatus;
  flow?: { bigNetRatio: number } | null;
}

export interface USWatchlistSnapshot {
  status: WatchSnapshotStatus;
  asOf: string | null;
  provider?: string;
  quoteFreshness?: JapanWatchlistSnapshot['quoteFreshness'];
  stocks: USStockQuote[];
}
