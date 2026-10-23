// v13.5.38 — TACHIBANA LIVE owner-facing status + Japanese-equity live evidence.
//
// Reads the provenance-stamped evidence document the backend embeds as
// `marketView.japaneseLive` (argus_tachibana_live.current_evidence_safe).
// The indicator is truthful by construction: LIVE only when the backend
// reports current accepted evidence; an absent document renders UNAVAILABLE
// with the reason, never a fabricated state.
import { TACHIBANA_STATUS_GLOSSARY } from './glossary';
import { exactAuthorityEpoch } from './liveAuthority';

export type TachibanaStatus =
  | 'LIVE' | 'DEGRADED' | 'STALE' | 'CLOSED' | 'UNAVAILABLE' | 'AUTH_FAILED' | 'MAINTENANCE' | 'DISABLED';

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
  sourceTimestampPrecision?: string | null;
  realtimeClassification?: string | null;
  receivedAt: string | null;
  marketStatus: string | null;
}

export interface TachibanaLiveDocument {
  schemaVersion?: string;
  provider?: string;
  authority?: string;
  status?: string;
  enabled?: boolean;
  displayApproved?: boolean;
  mode?: string;
  shadowOnly?: boolean;
  authoritative?: boolean;
  providerHealth?: string | null;
  marketPhase?: string | null;
  lastErrorClass?: string | null;
  updatedAt?: string | null;
  asOf?: string | null;
  /** Cache-read time only; never substitutes for a trade or receipt time. */
  readAt?: string | null;
  cashSessionOpen?: boolean;
  quoteRequestedSymbols?: string[];
  priceRecordsRetained?: boolean;
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
  LIVE: 'ライブ', DEGRADED: '一部', STALE: '古い', CLOSED: '市場クローズ', UNAVAILABLE: '欠測',
  AUTH_FAILED: '認証失敗', MAINTENANCE: 'メンテナンス', DISABLED: '無効',
};

const STATUSES: ReadonlySet<string> = new Set(
  ['LIVE', 'DEGRADED', 'STALE', 'CLOSED', 'UNAVAILABLE', 'AUTH_FAILED', 'MAINTENANCE', 'DISABLED']);

const num = (value: unknown): number | null =>
  typeof value === 'number' && Number.isFinite(value) ? value : null;
const str = (value: unknown): string | null => (typeof value === 'string' ? value : null);

function reasonFor(status: TachibanaStatus, doc: TachibanaLiveDocument | null, present: boolean): string {
  if (!present) return '未接続（バックエンド配線待ち）';
  switch (status) {
    case 'LIVE': return '現在の受理済み市場証拠あり（参考表示・売買権限なし）';
    case 'DEGRADED': return '一部銘柄のみ現在値';
    case 'STALE': return '鮮度期限切れ';
    case 'CLOSED': return '接続確認済（認証・日付・価格 PASS）· 市場クローズ中は更新なし';
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
        sourceTimestampPrecision: str(raw.sourceTimestampPrecision),
        realtimeClassification: str(raw.realtimeClassification),
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
let liveDocumentObservedAt: number | null = null;
const liveListeners = new Set<() => void>();

export function setTachibanaLiveDocument(doc: unknown): void {
  let next = doc && typeof doc === 'object' && (doc as TachibanaLiveDocument).provider === 'TACHIBANA'
    ? (doc as TachibanaLiveDocument) : null;
  const times = [next?.readAt, next?.updatedAt].map((stamp) => exactAuthorityEpoch(stamp))
    .filter((stamp): stamp is number => stamp != null && stamp <= Date.now());
  const observedAt = times.length ? Math.max(...times) : null;
  // A slow analysis response cannot roll back the newer cached price read.
  if (next && liveDocumentObservedAt != null
      && (observedAt == null || observedAt < liveDocumentObservedAt)) return;
  if (next?.enabled === true && next.displayApproved === true && next.mode === 'DISPLAY'
      && liveDocument?.enabled === true && liveDocument.displayApproved === true
      && liveDocument.mode === 'DISPLAY') {
    const failed = ['AUTH_FAILED', 'UNAVAILABLE', 'MAINTENANCE'].includes(next.status ?? '');
    const requested = next.quoteRequestedSymbols;
    if (failed || Array.isArray(requested)) {
      const symbols = new Map(Object.entries(liveDocument.symbols ?? {}));
      if (!failed && Array.isArray(requested)) for (const symbol of requested.slice(0, 50)) symbols.delete(symbol);
      for (const [symbol, row] of Object.entries(next.symbols ?? {})) symbols.set(symbol, row);
      const safe = [...symbols].filter(([symbol]) => /^(?:101|[0-9][0-9A-Z]{3})$/.test(symbol)).slice(0, 51);
      next = { ...next, symbols: Object.fromEntries(safe), priceRecordsRetained: failed && safe.length > 0 };
    }
  }
  liveDocument = next;
  liveDocumentObservedAt = observedAt;
  liveDocumentRevision += 1;
  for (const listener of liveListeners) listener();
}

export function subscribeTachibanaLive(listener: () => void): () => void {
  liveListeners.add(listener);
  return () => { liveListeners.delete(listener); };
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

/** Board evidence carried on an overlaid JP row (reference only, no execution). */
export interface TachibanaBoard {
  price: number | null; vwap: number | null; bestBid: number | null; bestAsk: number | null;
  bidQty: number | null; askQty: number | null; volume: number | null;
  sourceTimestamp: string | null; marketStatus: string | null;
}

export function tachibanaBoardOf(row: TachibanaLiveRow): TachibanaBoard {
  return {
    price: row.price, vwap: row.vwap, bestBid: row.bestBid, bestAsk: row.bestAsk,
    bidQty: row.bidQty, askQty: row.askQty, volume: row.volume,
    sourceTimestamp: row.sourceTimestamp, marketStatus: row.marketStatus,
  };
}

export interface OverlayableJpSnapshot {
  stocks: OverlayableJpRow[];
  status?: string;
  [key: string]: unknown;
}

/**
 * Same admission as the server's row_trade_current (owner decision 2026-10-22):
 * receipt within 15 s, and the stated trade time within 15 s — or, for a
 * minute-precision time ("HH:MM"), within its minute + 15 s (75 s from the
 * minute start). The trade time is never replaced by the receipt time.
 */
export function tachibanaTradeTimeCurrent(
  sourceTimestamp: string | null | undefined, precision: string | null | undefined,
  receivedAt: string | null | undefined, nowMs: number,
): boolean {
  if (precision === 'UNAVAILABLE' || !sourceTimestamp || !receivedAt) return false;
  const source = Date.parse(sourceTimestamp);
  const received = Date.parse(receivedAt);
  if (!Number.isFinite(source) || !Number.isFinite(received) || !Number.isFinite(nowMs)) return false;
  const minute = precision === 'MINUTE';
  if (minute && source % 60_000 !== 0) return false;
  const age = nowMs - source;
  const receiptAge = nowMs - received;
  return receiptAge >= 0 && receiptAge <= 15_000 && age >= 0 && age <= (minute ? 75_000 : 15_000);
}

/** Symbols for which the document carries a current, FRESH, priced row. */
export function tachibanaCurrentRows(
  doc: TachibanaLiveDocument | null | undefined, nowMs = Date.now(),
): Map<string, TachibanaLiveRow> {
  const out = new Map<string, TachibanaLiveRow>();
  if (doc?.displayApproved !== true || doc.mode === "SHADOW") return out;
  const view = tachibanaLiveView(doc);
  if (view.status !== 'LIVE' && view.status !== 'DEGRADED') return out;
  for (const row of view.rows) {
    if (row.price === null || row.freshness !== 'FRESH' || !row.sourceTimestamp) continue;
    if (!tachibanaTradeTimeCurrent(row.sourceTimestamp, row.sourceTimestampPrecision, row.receivedAt, nowMs)
        || row.marketStatus !== 'OPEN') continue;
    out.set(row.symbol.toUpperCase(), row);
  }
  return out;
}

/** Latest received PRICE values for display, independent from LIVE eligibility.
 * Minute-precision or unchanged trades keep their own time and never inherit
 * a new trade time from receipt. These rows have no decision authority.
 */
export function tachibanaPriceReferenceRows(
  doc: TachibanaLiveDocument | null | undefined, nowMs = Date.now(),
): Map<string, TachibanaLiveRow> {
  const out = new Map<string, TachibanaLiveRow>();
  if (doc?.enabled !== true || doc.displayApproved !== true || doc.mode !== 'DISPLAY'
      || doc.authoritative === true || doc.shadowOnly !== true) return out;
  const view = tachibanaLiveView(doc);
  if (!Number.isFinite(nowMs) || (!['LIVE', 'DEGRADED', 'STALE', 'CLOSED'].includes(view.status)
      && doc.priceRecordsRetained !== true)) return out;
  const day = (epoch: number) => new Date(epoch).toLocaleDateString('en-CA', { timeZone: 'Asia/Tokyo' });
  for (const row of view.rows) {
    const source = exactAuthorityEpoch(row.sourceTimestamp);
    const received = exactAuthorityEpoch(row.receivedAt);
    const closedWithoutTradeTime = row.marketStatus === 'CLOSED' && row.sourceTimestamp == null
      && row.sourceTimestampPrecision === 'UNAVAILABLE';
    if (row.price == null || row.price <= 0 || !['OPEN', 'CLOSED'].includes(row.marketStatus ?? '')
        || row.realtimeClassification !== 'CURRENT_MARKET_SNAPSHOT'
        || received == null || received > nowMs || day(received) !== day(nowMs)) continue;
    if (!closedWithoutTradeTime && (!['MINUTE', 'SECOND'].includes(row.sourceTimestampPrecision ?? '')
        || source == null || source > nowMs || source > received || day(source) !== day(nowMs))) continue;
    if (row.sourceTimestampPrecision === 'MINUTE' && source != null && source % 60_000 !== 0) continue;
    out.set(row.symbol.toUpperCase(), row);
  }
  return out;
}

/** Change only the existing JP quote reader's cadence; no extra reader. */
export function tachibanaQuoteReadInterval(doc: TachibanaLiveDocument | null | undefined, normalMs: number): number {
  return doc?.provider === 'TACHIBANA' && doc.enabled === true && doc.displayApproved === true
    && doc.mode === 'DISPLAY' && doc.cashSessionOpen === true
    && !['AUTH_FAILED', 'MAINTENANCE', 'DISABLED'].includes(doc.status ?? '')
    ? 10_000 : normalMs;
}

export function tachibanaPriceTime(row: TachibanaLiveRow): string {
  if (!row.sourceTimestamp) return '価格時刻不明';
  const minute = row.sourceTimestampPrecision === 'MINUTE';
  return new Date(row.sourceTimestamp).toLocaleTimeString('ja-JP', {
    timeZone: 'Asia/Tokyo', hour: '2-digit', minute: '2-digit', ...(minute ? {} : { second: '2-digit' }),
  }) + (minute ? '（分精度）' : '');
}

/**
 * Overlay current Tachibana evidence onto a normalized JP watchlist snapshot.
 * Replaced rows carry provider/source `tachibana`, `delayClass: LIVE` proven
 * through `realtimeEvidence` + a ≤60 s exchange timestamp, and a rebuilt
 * `quoteTruth`.  Rows without current Tachibana evidence are untouched.
 */
/** Symbols with a priced CLOSED-session baseline (auth/date/price proven, market closed). */
export function tachibanaClosedRows(doc: TachibanaLiveDocument | null | undefined): Map<string, TachibanaLiveRow> {
  const out = new Map<string, TachibanaLiveRow>();
  if (doc?.displayApproved !== true || doc.mode === "SHADOW") return out;
  const view = tachibanaLiveView(doc);
  if (view.status !== 'CLOSED') return out;
  for (const row of view.rows) if (row.price !== null) out.set(row.symbol.toUpperCase(), row);
  return out;
}

export function overlayTachibanaLive<T extends OverlayableJpSnapshot>(
  snapshot: T | null | undefined,
  doc: TachibanaLiveDocument | null | undefined = liveDocument,
  nowMs = Date.now(),
): T | null | undefined {
  if (!snapshot || !Array.isArray(snapshot.stocks)) return snapshot;
  const current = tachibanaCurrentRows(doc, nowMs);
  const closed = tachibanaClosedRows(doc);
  if (current.size === 0 && closed.size === 0) return snapshot;
  let replaced = 0;
  let boards = 0;
  const stocks = snapshot.stocks.map((row) => {
    const key = String(row.symbol ?? '').toUpperCase();
    const live = current.get(key);
    if (!live) {
      // CLOSED baseline: attach the board as reference evidence only — the
      // row keeps its own price/provider/freshness (no false LIVE).
      const closedRow = closed.get(key);
      if (!closedRow) return row;
      boards += 1;
      return { ...row, tachibana: tachibanaBoardOf(closedRow), tachibanaMarketStatus: closedRow.marketStatus ?? 'CLOSED' };
    }
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
      tachibana: tachibanaBoardOf(live),
    };
  });
  if (replaced === 0 && boards === 0) return snapshot;
  if (replaced === 0) return { ...snapshot, stocks, tachibanaBoardCount: boards };
  const allLive = stocks.every((row) => row.status === 'live');
  return {
    ...snapshot,
    stocks,
    status: allLive ? 'live' : (snapshot.status === 'live' ? 'live' : 'mixed'),
    tachibanaLiveCount: replaced,
    tachibanaBoardCount: boards,
  };
}

// ── v13.5.40: JP realtime health lamp + logo follow Tachibana ───────────────
//
// The backend's `jp_realtime` lamp still describes the retired moomoo JP path.
// Once Tachibana is enabled it is the JP realtime source, so the lamp (and the
// overall beacon derived from the lamps) is recomputed from the evidence
// document.  Absent or disabled document → the backend lamp is left untouched.
export type HealthLampStatus = 'ok' | 'warning' | 'stopped' | 'off';
export interface OverlayableHealthLamp {
  key: string; labelJa: string; status: HealthLampStatus; detailJa: string;
}
export interface OverlayableSystemHealth {
  asOf: string; overall: HealthLampStatus; lamps: OverlayableHealthLamp[]; noteJa?: string;
}

export const JP_REALTIME_LAMP_KEY = 'jp_realtime';

export function tachibanaJpRealtimeLamp(
  doc: TachibanaLiveDocument | null | undefined, nowMs = Date.now(),
): { status: HealthLampStatus; detailJa: string } | null {
  const view = tachibanaLiveView(doc);
  if (!view.present || view.status === 'DISABLED' || doc?.enabled === false) return null;
  // 2026-10-23: 一目で読める短い一語にする。銘柄の一覧は出さない。
  // DEGRADED は取引の少ない銘柄が直近の分に約定せず古い値のままの時にも起きるため、
  // 現在値の行が1つでもあれば緑にする(どの値を使うかの判定は変えない)。
  const current = tachibanaCurrentRows(doc, nowMs);
  switch (view.status) {
    case 'LIVE':
      return { status: 'ok', detailJa: '立花 更新中' };
    case 'DEGRADED':
      return current.size > 0
        ? { status: 'ok', detailJa: '立花 更新中' }
        : { status: 'warning', detailJa: '立花 更新待ち' };
    case 'STALE':
      return { status: 'warning', detailJa: '立花 更新待ち' };
    case 'CLOSED':
      return { status: 'ok', detailJa: '立花 閉場中' };
    case 'AUTH_FAILED': {
      const boundary = (doc as { authBoundary?: unknown } | null | undefined)?.authBoundary;
      const code = typeof boundary === 'string' && boundary ? boundary : (doc?.lastErrorClass ?? 'AUTH');
      return { status: 'warning', detailJa: `立花 認証失敗（${code}）` };
    }
    case 'MAINTENANCE':
      return { status: 'warning', detailJa: '立花 保守中' };
    default:
      return { status: 'off', detailJa: '立花 待機中' };
  }
}

const LAMP_SEVERITY: Record<HealthLampStatus, number> = { off: 0, ok: 1, warning: 2, stopped: 3 };

export function overallFromLamps(lamps: readonly OverlayableHealthLamp[]): HealthLampStatus {
  let worst: HealthLampStatus = 'off';
  for (const lamp of lamps) {
    if (LAMP_SEVERITY[lamp.status] > LAMP_SEVERITY[worst]) worst = lamp.status;
  }
  return worst;
}

export function applyTachibanaHealthOverlay<T extends OverlayableSystemHealth>(
  health: T | null | undefined,
  doc: TachibanaLiveDocument | null | undefined = liveDocument,
  nowMs = Date.now(),
): T | null | undefined {
  if (!health || !Array.isArray(health.lamps)) return health;
  const lamp = tachibanaJpRealtimeLamp(doc, nowMs);
  if (!lamp) return health;
  let found = false;
  const lamps = health.lamps.map((row) => {
    if (row.key !== JP_REALTIME_LAMP_KEY) return row;
    found = true;
    return { ...row, status: lamp.status, detailJa: lamp.detailJa };
  });
  if (!found) lamps.push({ key: JP_REALTIME_LAMP_KEY, labelJa: 'JP realtime', ...lamp });
  return { ...health, lamps, overall: overallFromLamps(lamps), tachibanaOverlay: true };
}

// ── v13.5.42: chart current point ───────────────────────────────────────────
export interface TachibanaCurrentPoint {
  symbol: string; price: number; source: 'TACHIBANA';
  state: 'LIVE' | 'CLOSED' | 'DELAYED' | 'STALE'; sourceTimestamp: string | null; freshness: string;
}

/** Current price point for a chart marker: LIVE when current, CLOSED for the closed-session baseline. */
export function tachibanaCurrentPoint(
  symbol: string, doc: TachibanaLiveDocument | null | undefined = liveDocument, nowMs = Date.now(),
): TachibanaCurrentPoint | null {
  const key = symbol.toUpperCase();
  const live = tachibanaCurrentRows(doc, nowMs).get(key);
  if (live && live.price !== null) {
    return { symbol: key, price: live.price, source: 'TACHIBANA', state: 'LIVE',
      sourceTimestamp: live.sourceTimestamp, freshness: live.freshness };
  }
  const closed = tachibanaClosedRows(doc).get(key);
  if (closed && closed.price !== null) {
    return { symbol: key, price: closed.price, source: 'TACHIBANA', state: 'CLOSED',
      sourceTimestamp: closed.sourceTimestamp, freshness: closed.freshness };
  }
  return null;
}
