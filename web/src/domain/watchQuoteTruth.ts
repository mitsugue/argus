import { marketInstrument } from './marketInstruments';
import {
  normalizeLiveQuote,
  quoteStatus,
  type InstrumentType,
} from './liveQuote';
import type {
  JapanStockQuote,
  JapanWatchlistSnapshot,
  USStockQuote,
  USWatchlistSnapshot,
  WatchSnapshotStatus,
} from '../types/watch';

type AnyQuote = JapanStockQuote | USStockQuote;
type AnySnapshot = JapanWatchlistSnapshot | USWatchlistSnapshot;

function snapshotStatus(rows: AnyQuote[], original: WatchSnapshotStatus): WatchSnapshotStatus {
  if (!rows.length) return original === 'mock' ? 'mock' : 'unknown';
  const statuses = new Set(rows.map((row) => row.status));
  if (statuses.size === 1) return rows[0]?.status ?? 'unknown';
  if (statuses.has('mock') || statuses.has('unknown')) return 'partial';
  return 'mixed';
}

export function normalizeWatchSnapshot<T extends AnySnapshot>(snapshot: T): T {
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
  } as T;
}
