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
    case 'AUTH_FAILED': return `認証失敗（${doc?.lastErrorClass ?? 'AUTH'}）`;
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
