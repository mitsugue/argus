// v13.5.43 — dynamic JP watchlist fallback.
//
// The public read-only `/api/argus/japan-watchlist?symbols=…` path serves only
// bridge/cache quotes for the requested symbols and returns an EMPTY `mock`
// snapshot when none are cached (production after 15:30 JST: moomoo has no JP
// entitlement, so it is always empty).  The curated snapshot (no `symbols`)
// carries the J-Quants end-of-day rows.  When the dynamic answer is empty we
// resolve the requested symbols from the curated rows; symbols the curated
// list does not carry stay absent (truthful 未取得, never fabricated).
export interface JpWatchRowLike { symbol: string; status?: string; [key: string]: unknown }
export interface JpWatchSnapshotLike { status: string; asOf?: string | null; stocks: JpWatchRowLike[]; [key: string]: unknown }

export function dynamicSnapshotIsEmpty(snapshot: JpWatchSnapshotLike | null | undefined): boolean {
  if (!snapshot || !Array.isArray(snapshot.stocks)) return true;
  return snapshot.stocks.length === 0 || snapshot.stocks.every((row) => row.status === 'mock');
}

/**
 * Resolve `requested` symbols from the curated snapshot.  Returns null when the
 * curated snapshot covers none of them (caller keeps the truthful empty state).
 */
export function resolveFromCurated<T extends JpWatchSnapshotLike>(
  curated: T | null | undefined, requested: readonly string[],
): T | null {
  if (!curated || !Array.isArray(curated.stocks) || requested.length === 0) return null;
  const wanted = new Set(requested.map((s) => s.toUpperCase()));
  const rows = curated.stocks.filter((row) => wanted.has(String(row.symbol ?? '').toUpperCase())
    && row.status !== 'mock');
  if (rows.length === 0) return null;
  const statuses = new Set(rows.map((row) => row.status ?? curated.status));
  const status = statuses.size === 1 ? [...statuses][0] as string : 'mixed';
  return { ...curated, status, stocks: rows, resolvedFromCurated: true, requestedCount: requested.length };
}

// ── v13.5.44: EOD row from the cached daily history ─────────────────────────
//
// `/api/argus/price-history` serves the cached J-Quants daily closes (newest
// first) for symbols the backend already warmed.  For an owner symbol the
// curated snapshot does not carry, the latest close is real end-of-day
// evidence, labelled delayed/EOD and sourced jquants — never a live claim.
export interface PriceHistoryLike { symbol?: string; available?: boolean; dates?: string[]; closes?: number[] }

export function rowFromPriceHistory(symbol: string, history: PriceHistoryLike | null | undefined): JpWatchRowLike | null {
  if (!history || history.available !== true) return null;
  const closes = Array.isArray(history.closes) ? history.closes : [];
  const dates = Array.isArray(history.dates) ? history.dates : [];
  const last = closes[0];
  if (typeof last !== 'number' || !Number.isFinite(last) || last <= 0) return null;
  const prev = closes[1];
  const changeAbs = typeof prev === 'number' && Number.isFinite(prev) ? last - prev : 0;
  const changePct = typeof prev === 'number' && Number.isFinite(prev) && prev > 0 ? ((last / prev) - 1) * 100 : 0;
  return {
    symbol: symbol.toUpperCase(), name: symbol.toUpperCase(), price: last,
    changeAbs: Math.round(changeAbs * 100) / 100, changePct: Math.round(changePct * 100) / 100,
    volume: 0, volumeUnavailable: true,
    date: typeof dates[0] === 'string' ? dates[0].slice(0, 10) : null,
    status: 'delayed', source: 'jquants', provider: 'jquants', delayClass: 'EOD',
    resolvedFromHistory: true,
  };
}

/** Merge history-derived rows for symbols still missing; keeps existing rows first. */
export function mergeHistoryRows<T extends JpWatchSnapshotLike>(
  snapshot: T | null | undefined, rows: JpWatchRowLike[], requested: readonly string[],
): T | null {
  const base: JpWatchSnapshotLike = snapshot && Array.isArray(snapshot.stocks)
    ? snapshot : { status: 'mock', asOf: null, stocks: [] };
  const have = new Set(base.stocks.map((r) => String(r.symbol ?? '').toUpperCase()));
  const extra = rows.filter((r) => r && !have.has(String(r.symbol ?? '').toUpperCase()));
  if (extra.length === 0) return (snapshot as T) ?? null;
  const stocks = [...base.stocks, ...extra];
  const statuses = new Set(stocks.map((r) => r.status ?? 'delayed'));
  const status = statuses.size === 1 ? [...statuses][0] as string : 'mixed';
  const asOf = stocks.map((r) => (r as { date?: string | null }).date ?? null)
    .filter((d): d is string => typeof d === 'string').sort().at(-1) ?? base.asOf ?? null;
  return { ...base, status, asOf, stocks, requestedCount: requested.length, historyRowCount: extra.length } as unknown as T;
}
