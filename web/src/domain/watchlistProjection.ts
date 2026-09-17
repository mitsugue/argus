import type { AssetItem } from '../types/assetItem';

/** Product reads only registration fields. The raw encrypted-backup records
 * remain in their original store, including retired portfolio fields. Never
 * persist this projection over those records. Unknown extensions are excluded.
 */
export function watchlistProjection(records: readonly AssetItem[]): AssetItem[] {
  return records.map(a => ({
    id: a.id, symbol: a.symbol, displayName: a.displayName,
    displayNameJa: a.displayNameJa, market: a.market, assetType: a.assetType,
    source: a.source, enabled: a.enabled, sortOrder: a.sortOrder,
    memo: a.memo, createdAt: a.createdAt, updatedAt: a.updatedAt,
  }));
}
