// v13.5.38 — TACHIBANA LIVE owner-facing status + Japanese-equity live evidence.
//
// Reads the provenance-stamped evidence document the backend embeds as
// `marketView.japaneseLive` (argus_tachibana_live.current_evidence_safe).
// The indicator is truthful by construction: LIVE only when the backend
// reports current accepted evidence; an absent document renders UNAVAILABLE
// with the reason, never a fabricated state.
import { TACHIBANA_STATUS_GLOSSARY } from './glossary';

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
const liveListeners = new Set<() => void>();

export function setTachibanaLiveDocument(doc: unknown): void {
  const next = doc && typeof doc === 'object' && (doc as TachibanaLiveDocument).provider === 'TACHIBANA'
    ? (doc as TachibanaLiveDocument) : null;
  liveDocument = next;
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
/** Symbols with a priced CLOSED-session baseline (auth/date/price proven, market closed). */
export function tachibanaClosedRows(doc: TachibanaLiveDocument | null | undefined): Map<string, TachibanaLiveRow> {
  const out = new Map<string, TachibanaLiveRow>();
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
  const current = tachibanaCurrentRows(doc, nowMs);
  const symbols = [...current.keys()].sort().join('/');
  switch (view.status) {
    case 'LIVE':
      return { status: 'ok', detailJa: `LIVE — Tachibanaから更新中（${symbols}）` };
    case 'DEGRADED':
      return { status: 'warning', detailJa: `Tachibana 一部銘柄のみ現在値（${symbols || '—'}）` };
    case 'STALE':
      return { status: 'warning', detailJa: 'Tachibana 鮮度期限切れ（再取得待ち）' };
    case 'CLOSED': {
      const priced = view.rows.filter((r) => r.price !== null).map((r) => r.symbol).join('/');
      return { status: 'ok', detailJa: `Tachibana 接続確認済 · 市場クローズ（${priced || '—'}）` };
    }
    case 'AUTH_FAILED': {
      const boundary = (doc as { authBoundary?: unknown } | null | undefined)?.authBoundary;
      const code = typeof boundary === 'string' && boundary ? boundary : (doc?.lastErrorClass ?? 'AUTH');
      return { status: 'warning', detailJa: `Tachibana 認証失敗（${code}）` };
    }
    case 'MAINTENANCE':
      return { status: 'warning', detailJa: 'Tachibana メンテナンス中' };
    default:
      return { status: 'off', detailJa: doc?.lastErrorClass
        ? `Tachibana 未取得（${doc.lastErrorClass}）` : 'Tachibana 待機中（セッション外）' };
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
