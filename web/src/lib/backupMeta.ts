export const BACKUP_META_KEY = 'argus.portfolioSync.meta.v1';
export const BACKUP_CONTRACT_VERSION = 1;

export interface BackupMeta {
  lastExportAt?: string;
  lastExportContractVersion?: number;
  lastPortfolioExportAt?: string;
  lastImportAt?: string;
  lastSnapshotAt?: string;
  lastSnapshotDay?: string;
}

export function certifiedCompleteExportAt(meta: BackupMeta): string | undefined {
  return meta.lastExportContractVersion === BACKUP_CONTRACT_VERSION ? meta.lastExportAt : undefined;
}

type BackupMetaStorage = Pick<Storage, 'getItem' | 'setItem'>;

export function readBackupMeta(storage: BackupMetaStorage = localStorage): BackupMeta {
  try {
    return JSON.parse(storage.getItem(BACKUP_META_KEY) || '{}') as BackupMeta;
  } catch {
    return {};
  }
}

export function patchBackupMeta(
  patch: Partial<BackupMeta>,
  storage: BackupMetaStorage = localStorage,
): void {
  try {
    storage.setItem(BACKUP_META_KEY, JSON.stringify({ ...readBackupMeta(storage), ...patch }));
  } catch { /* quota — protection state must never break the app */ }
}
