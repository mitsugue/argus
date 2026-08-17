// Complete device-data backup. This is the only export contract allowed to
// advance global backup protection; narrower portfolio exports are separate.

import { BACKUP_CONTRACT_VERSION, patchBackupMeta } from './backupMeta';
export { BACKUP_CONTRACT_VERSION } from './backupMeta';

// v11.3.3: assetTombstones ride along so deletions propagate across devices
// (the assets key itself is merged per-item by the sync loop, not replaced).
export const BACKUP_KEYS = ['argus.assets.v1', 'argus.judgmentLog.v1', 'argus.trades.v1', 'argus.research.v1', 'argus.assetTombstones.v1',
  // Snapshot/audit data is included in local JSON exports and remains
  // compatible with existing encrypted envelopes that can be restored.
  'argus.portfolio.snapshots.v1', 'argus.decision.audit.v1', 'argus.portfolioSync.meta.v1',
  'argus.notifications.v1',              // v11.14.0: notifications (device-local history)
  'argus.backupSafety.meta.v1',          // v11.16.0: recovery-drill verification state
  'argus.fireCore.v1'] as const;         // v11.19.1: FIRE Core fund meta (account/contribution/manual value)
const LAST_AUTO_KEY = 'argus.lastAutoBackup.v1';
const AUTO_INTERVAL_MS = 7 * 86_400_000; // weekly
const BACKUP_META_ONLY_KEYS = new Set<string>([
  'argus.portfolioSync.meta.v1', 'argus.backupSafety.meta.v1',
]);

export interface BackupFile {
  app: 'argus';
  exportedAt: string;
  version: string;
  auto?: boolean;
  /** sync-v2 metadata (v11.3.4): protocol 2 = per-item watchlist merge with
      tombstones. Absent = legacy v1 client (whole-payload LWW). */
  syncProtocolVersion?: number;
  deviceId?: string;
  data: Record<string, unknown>;
}

type BackupStorage = Pick<Storage, 'getItem' | 'setItem'>;

export interface BackupRoundTripProof {
  passed: boolean;
  restoredKeys: string[];
  missingKeys: string[];
  mismatchedKeys: string[];
}

export const SYNC_PROTOCOL_VERSION = 2;
const DEVICE_ID_KEY = 'argus.deviceId.v1';

export function deviceId(): string {
  try {
    let id = localStorage.getItem(DEVICE_ID_KEY);
    if (!id) {
      id = Math.random().toString(36).slice(2, 10) + Date.now().toString(36);
      localStorage.setItem(DEVICE_ID_KEY, id);
    }
    return id;
  } catch { return 'unknown'; }
}

export function hasBackupContent(storage: Pick<Storage, 'getItem'> = localStorage): boolean {
  for (const key of BACKUP_KEYS) {
    if (BACKUP_META_ONLY_KEYS.has(key)) continue;
    try {
      const raw = storage.getItem(key);
      if (raw == null) continue;
      const value = JSON.parse(raw) as unknown;
      if (Array.isArray(value) ? value.length > 0
        : value && typeof value === 'object' ? Object.keys(value).length > 0
        : value != null && value !== '') return true;
    } catch {
      return true; // unreadable protected data still exists and must not be ignored
    }
  }
  return false;
}

export function buildBackupPayload(
  auto = false,
  options: { deviceId?: string } = {},
): BackupFile {
  const data: Record<string, unknown> = {};
  for (const k of BACKUP_KEYS) {
    const raw = localStorage.getItem(k);
    if (raw != null) data[k] = JSON.parse(raw) as unknown;
  }
  return { app: 'argus', exportedAt: new Date().toISOString(), version: __APP_VERSION__,
           syncProtocolVersion: SYNC_PROTOCOL_VERSION, deviceId: options.deviceId ?? deviceId(), auto, data };
}

export function downloadBackup(auto = false): number {
  let payload: BackupFile;
  try { payload = buildBackupPayload(auto); }
  catch { return 0; }
  const n = Object.keys(payload.data).length;
  if (n === 0) return 0;
  const proof = verifyBackupRoundTrip(payload);
  if (!proof.passed) return 0;
  const date = new Date().toISOString().slice(0, 10);
  const blob = new Blob([JSON.stringify(payload, null, 1)], { type: 'application/json' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `argus-backup-${date}${auto ? '-auto' : ''}.json`;
  a.click();
  patchBackupMeta({
    lastExportAt: payload.exportedAt,
    lastExportContractVersion: BACKUP_CONTRACT_VERSION,
  });
  URL.revokeObjectURL(a.href);
  return n;
}

/** Weekly auto-export on app open. Saves to the browser's download folder —
    zero clicks. Returns true when a backup was produced this call. */
export function maybeAutoBackup(): boolean {
  try {
    const last = Number(localStorage.getItem(LAST_AUTO_KEY) || 0);
    if (Date.now() - last < AUTO_INTERVAL_MS) return false;
    // Only bother once there is something worth saving (a holding or a log).
    const hasData = BACKUP_KEYS.some((k) => {
      const raw = localStorage.getItem(k);
      return raw != null && raw.length > 2;
    });
    if (!hasData) return false;
    const n = downloadBackup(true);
    if (n > 0) localStorage.setItem(LAST_AUTO_KEY, String(Date.now()));
    return n > 0;
  } catch {
    return false;
  }
}

function restoreBackupInto(parsed: BackupFile, storage: BackupStorage, now: number): number {
  if (parsed.app !== 'argus' || !parsed.data) return 0;
  let n = 0;
  for (const k of BACKUP_KEYS) {
    if (parsed.data[k] == null) continue;
    let value = parsed.data[k];
    // Explicit restore = newest user intent (v11.3.3). Restored watchlist items
    // get updatedAt=now and their tombstones are cleared — otherwise the sync
    // merge would silently revert the restore within one poll tick (an old
    // backup item always loses to a newer cloud copy / deletion tombstone).
    if (k === 'argus.assets.v1' && Array.isArray(value)) {
      value = (value as { id?: string }[]).map((a) => ({ ...a, updatedAt: now }));
      try {
        const tombRaw = storage.getItem('argus.assetTombstones.v1');
        const tombs = tombRaw ? (JSON.parse(tombRaw) as Record<string, number>) : {};
        for (const a of value as { id?: string }[]) {
          if (a.id) delete tombs[a.id];
        }
        storage.setItem('argus.assetTombstones.v1', JSON.stringify(tombs));
      } catch { /* ignore */ }
    }
    storage.setItem(k, JSON.stringify(value));
    n++;
  }
  // Stamp restored state as a new local edit so an older read-only envelope is
  // not mistaken for protection of the newly restored data.
  try { storage.setItem('argus.lastLocalEditAt.v1', String(now)); } catch { /* ignore */ }
  return n;
}

export function restoreBackup(parsed: BackupFile): number {
  return restoreBackupInto(parsed, localStorage, Date.now());
}

/** Execute the production restore path against isolated storage and compare
 * every protected key. No current browser data is read or modified. */
export function verifyBackupRoundTrip(parsed: BackupFile): BackupRoundTripProof {
  const values = new Map<string, string>();
  const storage: BackupStorage = {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => { values.set(key, value); },
  };
  const expectedKeys = BACKUP_KEYS.filter((key) => parsed.data?.[key] != null);
  const now = Date.now();
  let restored = 0;
  try { restored = restoreBackupInto(parsed, storage, now); }
  catch {
    return { passed: false, restoredKeys: [], missingKeys: expectedKeys, mismatchedKeys: [] };
  }

  const restoredKeys: string[] = [];
  const missingKeys: string[] = [];
  const mismatchedKeys: string[] = [];
  for (const key of expectedKeys) {
    const raw = storage.getItem(key);
    if (raw == null) {
      missingKeys.push(key);
      continue;
    }
    let expected = parsed.data[key];
    if (key === 'argus.assets.v1' && Array.isArray(expected)) {
      expected = (expected as Record<string, unknown>[]).map((asset) => ({ ...asset, updatedAt: now }));
    }
    try {
      if (JSON.stringify(JSON.parse(raw)) !== JSON.stringify(expected)) mismatchedKeys.push(key);
      else restoredKeys.push(key);
    } catch {
      mismatchedKeys.push(key);
    }
  }
  return {
    passed: restored === expectedKeys.length && missingKeys.length === 0 && mismatchedKeys.length === 0,
    restoredKeys,
    missingKeys,
    mismatchedKeys,
  };
}
