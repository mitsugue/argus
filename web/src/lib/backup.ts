// Device-data backup (v10.3.2/.3). The ONLY device-local state is these two
// localStorage keys — everything else (ledger, prices, AI, code) is cloud-side.
// v10.3.3 adds a weekly AUTO-export on app open so a dying SSD or a new Mac
// never costs more than the last 7 days of holdings edits.

export const BACKUP_KEYS = ['argus.assets.v1', 'argus.judgmentLog.v1'] as const;
const LAST_AUTO_KEY = 'argus.lastAutoBackup.v1';
const AUTO_INTERVAL_MS = 7 * 86_400_000; // weekly

export interface BackupFile {
  app: 'argus';
  exportedAt: string;
  version: string;
  auto?: boolean;
  data: Record<string, unknown>;
}

export function buildBackupPayload(auto = false): BackupFile {
  const data: Record<string, unknown> = {};
  for (const k of BACKUP_KEYS) {
    try {
      const raw = localStorage.getItem(k);
      if (raw) data[k] = JSON.parse(raw);
    } catch { /* skip unreadable key */ }
  }
  return { app: 'argus', exportedAt: new Date().toISOString(), version: __APP_VERSION__, auto, data };
}

export function downloadBackup(auto = false): number {
  const payload = buildBackupPayload(auto);
  const n = Object.keys(payload.data).length;
  if (n === 0) return 0;
  const date = new Date().toISOString().slice(0, 10);
  const blob = new Blob([JSON.stringify(payload, null, 1)], { type: 'application/json' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `argus-backup-${date}${auto ? '-auto' : ''}.json`;
  a.click();
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

export function restoreBackup(parsed: BackupFile): number {
  if (parsed.app !== 'argus' || !parsed.data) return 0;
  let n = 0;
  for (const k of BACKUP_KEYS) {
    if (parsed.data[k] != null) {
      localStorage.setItem(k, JSON.stringify(parsed.data[k]));
      n++;
    }
  }
  return n;
}
