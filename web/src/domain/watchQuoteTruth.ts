import { marketInstrument } from './marketInstruments';
import {
  normalizeLiveQuote,
  quoteStatus,
  type DelayClass,
  type InstrumentType,
  type LiveQuote,
  type QuoteSession,
} from './liveQuote';
import type {
  JapanStockQuote,
  JapanWatchlistSnapshot,
  USStockQuote,
  USWatchlistSnapshot,
} from '../types/watch';

export type WatchQuoteStatus = 'live' | 'delayed' | 'unknown' | 'mock';
export type WatchSnapshotStatus = WatchQuoteStatus | 'partial' | 'mixed';

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

export interface WatchQuoteFreshness {
  delayClass?: DelayClass | string | null;
  sourceAgeMedianSec?: number | null;
  sourceAgeP95Sec?: number | null;
  sourceTimestampCoverage?: number | null;
  note?: string | null;
}

export type JapanTruthQuote = Omit<JapanStockQuote, 'status'> & QuoteTruthFields & {
  status: WatchQuoteStatus;
};
export type USTruthQuote = Omit<USStockQuote, 'status'> & QuoteTruthFields & {
  status: WatchQuoteStatus;
};
export type JapanTruthSnapshot = Omit<JapanWatchlistSnapshot, 'status' | 'stocks'> & {
  status: WatchSnapshotStatus;
  provider?: string;
  quoteFreshness?: WatchQuoteFreshness;
  stocks: JapanTruthQuote[];
};
export type USTruthSnapshot = Omit<USWatchlistSnapshot, 'status' | 'stocks'> & {
  status: WatchSnapshotStatus;
  quoteFreshness?: WatchQuoteFreshness;
  stocks: USTruthQuote[];
};

type RawQuote = (
  Omit<JapanStockQuote, 'status'> | Omit<USStockQuote, 'status'>
) & QuoteTruthFields & {
  status: WatchQuoteStatus;
};
type RawSnapshot = {
  status: WatchSnapshotStatus;
  asOf: string | null;
  provider?: string;
  quoteFreshness?: WatchQuoteFreshness;
  stocks: RawQuote[];
};

function snapshotStatus(
  rows: Array<{ status: WatchQuoteStatus }>,
  original: WatchSnapshotStatus,
): WatchSnapshotStatus {
  if (!rows.length) return original === 'mock' ? 'mock' : 'unknown';
  const statuses = new Set(rows.map((row) => row.status));
  if (statuses.size === 1) return rows[0]?.status ?? 'unknown';
  if (statuses.has('mock') || statuses.has('unknown')) return 'partial';
  return 'mixed';
}

export function normalizeWatchSnapshot(snapshot: RawSnapshot): RawSnapshot {
  const snapshotDelay = String(snapshot.quoteFreshness?.delayClass ?? '').toUpperCase();
  const snapshotRealtimeEvidence = snapshotDelay === 'LIVE';
  const provider = snapshot.provider ?? 'unknown';
  const receivedAt = new Date().toISOString();

  const stocks = snapshot.stocks.map((row) => {
    const definition = marketInstrument(row.symbol);
    const instrumentType: InstrumentType = definition?.instrumentType
      ?? row.instrumentType
      ?? 'STOCK';
    const quoteTruth = normalizeLiveQuote({
      ...row,
      provider: row.provider ?? row.source ?? provider,
      receivedAt: row.receivedAt ?? receivedAt,
      realtimeEvidence: row.realtimeEvidence ?? snapshotRealtimeEvidence,
    }, {
      symbol: row.symbol,
      instrumentType,
      provider,
      receivedAt,
    });
    return {
      ...row,
      provider: quoteTruth.provider,
      sourceTimestamp: quoteTruth.sourceTimestamp,
      receivedAt: quoteTruth.receivedAt,
      transportAgeSec: quoteTruth.transportAgeSec,
      ageSec: quoteTruth.ageSec,
      delayClass: quoteTruth.delayClass,
      session: quoteTruth.session,
      entitlement: quoteTruth.entitlement,
      instrumentType,
      quoteTruth,
      status: quoteStatus(quoteTruth.delayClass),
    };
  });

  return {
    ...snapshot,
    status: snapshotStatus(stocks, snapshot.status),
    stocks,
  };
}

export function normalizeJapanWatchSnapshot(
  snapshot: JapanWatchlistSnapshot,
): JapanTruthSnapshot {
  return normalizeWatchSnapshot(snapshot as RawSnapshot) as JapanTruthSnapshot;
}

export function normalizeUSWatchSnapshot(
  snapshot: USWatchlistSnapshot,
): USTruthSnapshot {
  return normalizeWatchSnapshot(snapshot as RawSnapshot) as USTruthSnapshot;
}
