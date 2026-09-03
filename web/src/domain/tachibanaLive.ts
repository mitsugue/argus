// v13.5.38 — TACHIBANA LIVE owner-facing status + Japanese-equity live evidence.
//
// Reads the provenance-stamped evidence document the backend embeds as
// `marketView.japaneseLive` (argus_tachibana_live.current_evidence_safe).
// The indicator is truthful by construction: LIVE only when the backend
// reports current accepted evidence; an absent document renders UNAVAILABLE
// with the reason, never a fabricated state.
import { TACHIBANA_STATUS_GLOSSARY } from './glossary';

export type TachibanaStatus =
  | 'LIVE' | 'DEGRADED' | 'STALE' | 'UNAVAILABLE' | 'AUTH_FAILED' | 'MAINTENANCE' | 'DISABLED';

export interface TachibanaLiveRow {
  symbol: string;
  price: number | null;
  previousClose: number | null;
  changeAbs: number | null;
  changePct: number | null;
  volume: number | null;
  vwap: number | null;
  bestBid: number | null;
  bestAsk: number | null;
  bidQty: number | null;
  askQty: number | null;
  freshness: string;
  sourceTimestamp: string | null;
  receivedAt: string | null;
  marketStatus: string | null;
}

export interface TachibanaLiveDocument {
  schemaVersion?: string;
  provider?: string;
  authority?: string;
  status?: string;
  enabled?: boolean;
  shadowOnly?: boolean;
  authoritative?: boolean;
  providerHealth?: string | null;
  marketPhase?: string | null;
  lastErrorClass?: string | null;
  updatedAt?: string | null;
  asOf?: string | null;
  symbols?: Record<string, Partial<Record<keyof TachibanaLiveRow, unknown>> & { provider?: string }>;
}

export interface TachibanaLiveView {
  label: 'TACHIBANA LIVE';
  status: TachibanaStatus;
  statusJa: string;
  glossaryKey: string;
  reasonJa: string;
  authorityJa: string;
  present: boolean;
  updatedAt: string | null;
  marketPhase: string | null;
  rows: TachibanaLiveRow[];
}

export const TACHIBANA_STATUS_JA: Record<TachibanaStatus, string> = {
  LIVE: 'ライブ', DEGRADED: '一部', STALE: '古い', UNAVAILABLE: '欠測',
  AUTH_FAILED: '認証失敗', MAINTENANCE: 'メンテナンス', DISABLED: '無効',
};

const STATUSES: ReadonlySet<string> = new Set(
  ['LIVE', 'DEGRADED', 'STALE', 'UNAVAILABLE', 'AUTH_FAILED', 'MAINTENANCE', 'DISABLED']);

const num = (value: unknown): number | null =>
  typeof value === 'number' && Number.isFinite(value) ? value : null;
const str = (value: unknown): string | null => (typeof value === 'string' ? value : null);

function reasonFor(status: TachibanaStatus, doc: TachibanaLiveDocument | null, present: boolean): string {
  if (!present) return '未接続（バックエンド配線待ち）';
  switch (status) {
    case 'LIVE': return '現在の受理済み市場証拠あり（参考表示・売買権限なし）';
    case 'DEGRADED': return '一部銘柄のみ現在値';
    case 'STALE': return '鮮度期限切れ';
    case 'AUTH_FAILED': return `認証失敗（${(doc as { authBoundary?: string } | null)?.authBoundary ?? doc?.lastErrorClass ?? 'AUTH'}）`;
    case 'MAINTENANCE': return 'プロバイダーメンテナンス中';
    case 'DISABLED': return '提供元は無効化中';
    default: return doc?.lastErrorClass ? `未取得（${doc.lastErrorClass}）` : '未取得（セッション外）';
  }
}

export function tachibanaLiveView(doc: TachibanaLiveDocument | null | undefined): TachibanaLiveView {
  const present = !!doc && typeof doc === 'object' && doc.provider === 'TACHIBANA';
  const rawStatus = present ? String(doc!.status ?? '') : '';
  const status: TachibanaStatus = STATUSES.has(rawStatus) ? (rawStatus as TachibanaStatus) : 'UNAVAILABLE';
  const rows: TachibanaLiveRow[] = [];
  if (present && doc!.symbols && typeof doc!.symbols === 'object') {
    for (const [symbol, raw] of Object.entries(doc!.symbols)) {
      if (!raw || raw.provider !== 'TACHIBANA') continue;   // provenance is mandatory
      rows.push({
        symbol,
        price: num(raw.price), previousClose: num(raw.previousClose),
        changeAbs: num(raw.changeAbs), changePct: num(raw.changePct),
        volume: num(raw.volume), vwap: num(raw.vwap),
        bestBid: num(raw.bestBid), bestAsk: num(raw.bestAsk),
        bidQty: num(raw.bidQty), askQty: num(raw.askQty),
        freshness: str(raw.freshness) ?? 'UNAVAILABLE',
        sourceTimestamp: str(raw.sourceTimestamp), receivedAt: str(raw.receivedAt),
        marketStatus: str(raw.marketStatus),
      });
    }
    rows.sort((a, b) => a.symbol.localeCompare(b.symbol));
  }
  // LIVE is never shown on the strength of a connection alone: it needs at
  // least one row with a current price and FRESH freshness.
  const hasCurrent = rows.some((r) => r.price !== null && r.freshness === 'FRESH');
  const shown: TachibanaStatus = status === 'LIVE' && !hasCurrent ? 'UNAVAILABLE' : status;
  return {
    label: 'TACHIBANA LIVE',
    status: shown,
    statusJa: TACHIBANA_STATUS_JA[shown],
    glossaryKey: TACHIBANA_STATUS_GLOSSARY[shown] ?? '',
    reasonJa: reasonFor(shown, present ? doc! : null, present),
    authorityJa: 'シャドー（参考証拠・売買判断を上書きしない）',
    present,
    updatedAt: present ? (str(doc!.updatedAt) ?? null) : null,
    marketPhase: present ? (str(doc!.marketPhase) ?? null) : null,
    rows,
  };
}

export function formatJpy(value: number | null): string {
  if (value === null) return '—';
  return value.toLocaleString('ja-JP', { maximumFractionDigits: 1 });
}

export function formatPct(value: number | null): string {
  if (value === null) return '—';
  const sign = value > 0 ? '+' : '';
  return `${sign}${value.toFixed(2)}%`;
}

// ── v13.5.39: Tachibana as the owner-visible realtime JP source ─────────────
//
// The decision-evidence poller publishes the latest evidence document into a
// tiny module store; JP quote consumers overlay it onto watchlist rows.  A
// row is replaced only when Tachibana carries a current FRESH price for that
// symbol; every other row keeps its existing (truthfully labeled) source.
import { normalizeLiveQuote } from './liveQuote';
import type { LiveQuote } from './liveQuote';

let liveDocument: TachibanaLiveDocument | null = null;
let liveDocumentRevision = 0;

export function setTachibanaLiveDocument(doc: unknown): void {
  const next = doc && typeof doc === 'object' && (doc as TachibanaLiveDocument).provider === 'TACHIBANA'
    ? (doc as TachibanaLiveDocument) : null;
  liveDocument = next;
  liveDocumentRevision += 1;
}

export function getTachibanaLiveDocument(): TachibanaLiveDocument | null {
  return liveDocument;
}

export function tachibanaLiveRevision(): number {
  return liveDocumentRevision;
}

export interface OverlayableJpRow {
  symbol: string;
  price?: number | null;
  changeAbs?: number | null;
  changePct?: number | null;
  volume?: number | null;
  status?: string;
  provider?: string | null;
  source?: string | null;
  sourceTimestamp?: string | number | null;
  receivedAt?: string | null;
  delayClass?: string | null;
  entitlement?: string | null;
  realtimeEvidence?: boolean | null;
  instrumentType?: string;
  quoteTruth?: LiveQuote;
  [key: string]: unknown;
}

export interface OverlayableJpSnapshot {
  stocks: OverlayableJpRow[];
  status?: string;
  [key: string]: unknown;
}

/** Symbols for which the document carries a current, FRESH, priced row. */
export function tachibanaCurrentRows(
  doc: TachibanaLiveDocument | null | undefined, nowMs = Date.now(),
): Map<string, TachibanaLiveRow> {
  const out = new Map<string, TachibanaLiveRow>();
  const view = tachibanaLiveView(doc);
  if (view.status !== 'LIVE' && view.status !== 'DEGRADED') return out;
  for (const row of view.rows) {
    if (row.price === null || row.freshness !== 'FRESH' || !row.sourceTimestamp) continue;
    const age = (nowMs - Date.parse(row.sourceTimestamp)) / 1000;
    if (!Number.isFinite(age) || age < -5 || age > 60) continue;
    out.set(row.symbol.toUpperCase(), row);
  }
  return out;
}

/**
 * Overlay current Tachibana evidence onto a normalized JP watchlist snapshot.
 * Replaced rows carry provider/source `tachibana`, `delayClass: LIVE` proven
 * through `realtimeEvidence` + a ≤60 s exchange timestamp, and a rebuilt
 * `quoteTruth`.  Rows without current Tachibana evidence are untouched.
 */
export function overlayTachibanaLive<T extends OverlayableJpSnapshot>(
  snapshot: T | null | undefined,
  doc: TachibanaLiveDocument | null | undefined = liveDocument,
  nowMs = Date.now(),
): T | null | undefined {
  if (!snapshot || !Array.isArray(snapshot.stocks)) return snapshot;
  const current = tachibanaCurrentRows(doc, nowMs);
  if (current.size === 0) return snapshot;
  let replaced = 0;
  const stocks = snapshot.stocks.map((row) => {
    const live = current.get(String(row.symbol ?? '').toUpperCase());
    if (!live) return row;
    const receivedAt = live.receivedAt ?? new Date(nowMs).toISOString();
    const raw = {
      ...row,
      price: live.price,
      changeAbs: live.changeAbs ?? row.changeAbs ?? null,
      changePct: live.changePct ?? row.changePct ?? null,
      volume: live.volume ?? row.volume ?? null,
      provider: 'tachibana',
      source: 'tachibana',
      sourceTimestamp: live.sourceTimestamp,
      exchangeTs: live.sourceTimestamp,
      receivedAt,
      delayClass: 'LIVE',
      entitlement: 'realtime',
      realtimeEvidence: true,
      session: live.marketStatus === 'OPEN' ? 'regular' : row.session,
      status: 'live',
    };
    const quoteTruth = normalizeLiveQuote(raw as Parameters<typeof normalizeLiveQuote>[0], {
      symbol: row.symbol,
      instrumentType: (row.instrumentType as 'STOCK' | 'ETF' | undefined) ?? 'STOCK',
      provider: 'tachibana',
      receivedAt,
      nowMs,
    });
    // If the proof did not survive normalization (e.g. timestamp drift) keep
    // the original row rather than showing a false LIVE.
    if (quoteTruth.delayClass !== 'LIVE') return row;
    replaced += 1;
    return {
      ...raw,
      quoteTruth,
      ageSec: quoteTruth.ageSec,
      transportAgeSec: quoteTruth.transportAgeSec,
      tachibanaLive: true,
    };
  });
  if (replaced === 0) return snapshot;
  const allLive = stocks.every((row) => row.status === 'live');
  return {
    ...snapshot,
    stocks,
    status: allLive ? 'live' : (snapshot.status === 'live' ? 'live' : 'mixed'),
    tachibanaLiveCount: replaced,
  };
}
