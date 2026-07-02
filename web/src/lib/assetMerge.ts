// Per-item watchlist merge (sync-v2, v11.3.3). sync-v1 applied the WHOLE remote
// payload last-writer-wins, so two devices adding different symbols clobbered
// each other and a never-synced device was blocked forever by the join gate.
// This merge is symmetric and non-destructive: union by item id, newer
// updatedAt wins per item, deletions propagate via tombstones (id → deletedAt).
// Re-merging the same inputs is a no-op, so devices converge instead of looping.
import type { AssetItem } from '../types/assetItem';

export type Tombstones = Record<string, number>;

const TOMB_KEY = 'argus.assetTombstones.v1';
const TOMB_TTL_MS = 30 * 86_400_000; // tombstones older than 30d are pruned

export function loadTombstones(): Tombstones {
  try {
    const raw = localStorage.getItem(TOMB_KEY);
    const t = raw ? (JSON.parse(raw) as Tombstones) : {};
    return typeof t === 'object' && t ? t : {};
  } catch { return {}; }
}

export function saveTombstones(t: Tombstones): void {
  try { localStorage.setItem(TOMB_KEY, JSON.stringify(t)); } catch { /* ignore */ }
}

/** Record a deletion so it propagates to other devices instead of resurrecting. */
export function recordTombstone(id: string): void {
  const t = loadTombstones();
  t[id] = Date.now();
  saveTombstones(prune(t));
}

function prune(t: Tombstones): Tombstones {
  const cutoff = Date.now() - TOMB_TTL_MS;
  const out: Tombstones = {};
  for (const [id, at] of Object.entries(t)) {
    if (typeof at === 'number' && at > cutoff) out[id] = at;
  }
  return out;
}

/** Canonical fingerprint — merge results are compared by content, not reference. */
function fingerprint(items: AssetItem[]): string {
  const rows = [...items]
    .sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0))
    .map((a) => [a.id, a.updatedAt, a.enabled, a.sortOrder, a.quantity ?? null, a.avgCost ?? null, a.memo ?? null]);
  return JSON.stringify(rows);
}

export interface MergeResult {
  items: AssetItem[];
  tombstones: Tombstones;
  localChanged: boolean;   // merged result differs from what this device had
  remoteChanged: boolean;  // merged result differs from the remote copy → push it
}

export function mergeAssets(
  local: AssetItem[], remote: AssetItem[],
  localTombs: Tombstones, remoteTombs: Tombstones,
): MergeResult {
  // tombstones: union, newest deletion time wins
  const tombs: Tombstones = { ...localTombs };
  for (const [id, at] of Object.entries(remoteTombs)) {
    if (typeof at === 'number' && at > (tombs[id] ?? 0)) tombs[id] = at;
  }
  const pruned = prune(tombs);

  const byId = new Map<string, AssetItem>();
  for (const it of [...local, ...remote]) {
    if (!it || typeof it.id !== 'string') continue;
    const prev = byId.get(it.id);
    if (!prev || (it.updatedAt ?? 0) > (prev.updatedAt ?? 0)) byId.set(it.id, it);
  }
  const items: AssetItem[] = [];
  for (const it of byId.values()) {
    const deletedAt = pruned[it.id] ?? 0;
    // an item edited/re-added AFTER its deletion wins over the tombstone
    if (deletedAt > (it.updatedAt ?? 0)) continue;
    items.push(it);
  }
  items.sort((a, b) => a.sortOrder - b.sortOrder);

  return {
    items,
    tombstones: pruned,
    localChanged: fingerprint(items) !== fingerprint(local),
    remoteChanged: fingerprint(items) !== fingerprint(remote),
  };
}
