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
