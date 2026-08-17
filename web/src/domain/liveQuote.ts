export type InstrumentType = 'INDEX' | 'ETF' | 'STOCK' | 'FUND' | 'CRYPTO';
export type DelayClass = 'LIVE' | '15m' | '20m' | 'EOD' | 'T-1' | 'UNKNOWN' | 'OFFLINE';
export type QuoteSession = 'PRE' | 'REGULAR' | 'AFTER' | 'CLOSED' | 'UNKNOWN';

export interface LiveQuote {
  symbol: string;
  instrumentType: InstrumentType;
  provider: string;
  price: number | null;
  previousClose: number | null;
  change: number | null;
  changePct: number | null;
  sourceTimestamp: string | null;
  receivedAt: string | null;
  ageSec: number | null;
  transportAgeSec: number | null;
  delayClass: DelayClass;
  session: QuoteSession;
  entitlement: string;
}

export interface RawQuoteTruth {
  symbol?: string;
  price?: number | null;
  changeAbs?: number | null;
  changePct?: number | null;
  status?: string | null;
  date?: string | null;
  provider?: string | null;
  source?: string | null;
  sourceTimestamp?: string | number | null;
  exchangeTs?: string | number | null;
  updateTime?: string | number | null;
  receivedAt?: string | null;
  ageSec?: number | null;
  transportAgeSec?: number | null;
  delayClass?: string | null;
  session?: string | null;
  entitlement?: string | null;
  realtimeEvidence?: boolean | null;
}

const DELAY_CLASSES = new Set<DelayClass>([
  'LIVE', '15m', '20m', 'EOD', 'T-1', 'UNKNOWN', 'OFFLINE',
]);
const QUOTE_SESSIONS = new Set<QuoteSession>([
  'PRE', 'REGULAR', 'AFTER', 'CLOSED', 'UNKNOWN',
]);

function finite(value: unknown): number | null {
  if (value == null || value === '' || typeof value === 'boolean') return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

function isoTimestamp(value: string | number | null | undefined): string | null {
  if (value == null || value === '') return null;
  if (typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value)) return value;
  const numeric = typeof value === 'number' ? value : Number(value);
  const raw = Number.isFinite(numeric)
    ? new Date(numeric < 10_000_000_000 ? numeric * 1000 : numeric)
    : new Date(String(value));
  return Number.isNaN(raw.getTime()) ? null : raw.toISOString();
}

function exactAgeSec(timestamp: string | null, nowMs: number): number | null {
  if (!timestamp || /^\d{4}-\d{2}-\d{2}$/.test(timestamp)) return null;
  const ms = Date.parse(timestamp);
  return Number.isFinite(ms) ? Math.max(0, Math.round((nowMs - ms) / 1000)) : null;
}

function tokyoTradingDate(nowMs: number): string {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Tokyo',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).formatToParts(new Date(nowMs));
  const byType = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  return `${byType.year}-${byType.month}-${byType.day}`;
}

function normalizedDelay(value: string | null | undefined): DelayClass | null {
  if (!value) return null;
  const exact = value === 'live' ? 'LIVE' : value;
  return DELAY_CLASSES.has(exact as DelayClass) ? exact as DelayClass : null;
}

function normalizedSession(value: string | null | undefined): QuoteSession {
  const upper = String(value ?? '').toUpperCase();
  return QUOTE_SESSIONS.has(upper as QuoteSession) ? upper as QuoteSession : 'UNKNOWN';
}

function classifyDelay(
  raw: RawQuoteTruth,
  provider: string,
  sourceTimestamp: string | null,
  nowMs: number,
): DelayClass {
  if (String(raw.status ?? '').toLowerCase() === 'mock') return 'OFFLINE';

  const declared = normalizedDelay(raw.delayClass);
  const providerKey = provider.toLowerCase();
  const entitlement = String(raw.entitlement ?? 'unknown').toLowerCase();
  const sourceAgeSec = exactAgeSec(sourceTimestamp, nowMs);
  if (declared) {
    // A LIVE label is a claim, not evidence. Older/partial backend payloads may
    // carry the word without the source timestamp fields introduced by the
    // LiveQuote contract, so fail closed unless the complete proof is present.
    if (declared === 'LIVE') {
      return raw.realtimeEvidence === true && sourceAgeSec != null && sourceAgeSec <= 60
        ? 'LIVE'
        : 'UNKNOWN';
    }
    return declared;
  }

  if (providerKey.includes('jquants') || providerKey.includes('j-quants')) {
    const date = sourceTimestamp?.slice(0, 10);
    return date && date < tokyoTradingDate(nowMs) ? 'T-1' : 'EOD';
  }
  if (providerKey.includes('fund') || providerKey.includes('投信')) return 'EOD';
  if (providerKey.includes('yahoo')) return '20m';

  if (providerKey.includes('moomoo')) {
    if (entitlement.includes('delay') || (sourceAgeSec != null && sourceAgeSec >= 600)) {
      return '15m';
    }
    // A transport heartbeat is not a market timestamp. Runtime classification
    // must be supplied by the backend after evaluating the quote-set p95.
    if (raw.realtimeEvidence === true && sourceAgeSec != null && sourceAgeSec <= 60) {
      return 'LIVE';
    }
    return 'UNKNOWN';
  }

  if (String(raw.status ?? '').toLowerCase() === 'delayed') return 'UNKNOWN';
  return 'UNKNOWN';
}

export function normalizeLiveQuote(
  raw: RawQuoteTruth,
  options: {
    symbol: string;
    instrumentType: InstrumentType;
    provider?: string | null;
    receivedAt?: string | null;
    nowMs?: number;
  },
): LiveQuote {
  const nowMs = options.nowMs ?? Date.now();
  const provider = String(raw.provider ?? raw.source ?? options.provider ?? 'unknown');
  const sourceTimestamp = isoTimestamp(
    raw.sourceTimestamp ?? raw.exchangeTs ?? raw.updateTime ?? raw.date,
  );
  const sourceAgeSec = exactAgeSec(sourceTimestamp, nowMs);
  const transportAgeSec = finite(raw.transportAgeSec ?? raw.ageSec);
  const price = finite(raw.price);
  const change = finite(raw.changeAbs);
  const changePct = finite(raw.changePct);
  const previousClose = price != null && change != null ? price - change : null;

  return {
    symbol: options.symbol,
    instrumentType: options.instrumentType,
    provider,
    price,
    previousClose,
    change,
    changePct,
    sourceTimestamp,
    receivedAt: isoTimestamp(raw.receivedAt ?? options.receivedAt),
    ageSec: sourceAgeSec,
    transportAgeSec,
    delayClass: classifyDelay(raw, provider, sourceTimestamp, nowMs),
    session: normalizedSession(raw.session),
    entitlement: String(raw.entitlement ?? 'unknown'),
  };
}

export function quoteStatus(delayClass: DelayClass): 'live' | 'delayed' | 'unknown' | 'mock' {
  if (delayClass === 'LIVE') return 'live';
  if (delayClass === 'OFFLINE') return 'mock';
  if (delayClass === 'UNKNOWN') return 'unknown';
  return 'delayed';
}

export function quoteAsOf(quote: LiveQuote): string {
  if (!quote.sourceTimestamp) return 'asOf 未検証';
  if (/^\d{4}-\d{2}-\d{2}$/.test(quote.sourceTimestamp)) {
    return `asOf ${quote.sourceTimestamp} (日付のみ)`;
  }
  return `asOf ${new Date(quote.sourceTimestamp).toLocaleString('ja-JP', {
    timeZone: 'Asia/Tokyo',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })} JST`;
}

export function quoteAge(quote: LiveQuote): string {
  if (quote.ageSec == null) return 'age 未検証';
  if (quote.ageSec < 60) return `age ${quote.ageSec}s`;
  return `age ${Math.floor(quote.ageSec / 60)}m`;
}
