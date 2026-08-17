import type { BackupSafety } from '../lib/backupSafety';

export type RestoreReadinessState =
  | 'ready'
  | 'drill_required'
  | 'recovery_point_required'
  | 'attention'
  | 'no_data';

export interface RestoreReadinessView {
  state: RestoreReadinessState;
  label: string;
  summary: string;
  sources: string[];
  integrity: string;
  atRisk: string;
  nextAction: string;
}

const age = (days: number | null) => days == null ? '未確認' : days === 0 ? '本日' : `${days}日前`;

/** Pure view model. It never treats "backup configured" as proof of restore. */
export function buildRestoreReadiness(safety: BackupSafety): RestoreReadinessView {
  if (safety.protectionLevel === 'unknown') {
    return {
      state: 'no_data',
      label: 'NO PROTECTED DATA',
      summary: '保護対象の端末データがまだないため、復元可能性は未判定です。',
      sources: [],
      integrity: '対象データなし',
      atRisk: '0件（保護対象未登録）',
      nextAction: safety.nextStepJa,
    };
  }

  const sources: string[] = [];
  const durableSources: string[] = [];
  if (safety.vaultConfigured && safety.vaultSyncAgeDays != null) {
    sources.push(`暗号化vault · 最終同期 ${age(safety.vaultSyncAgeDays)}`);
    durableSources.push('vault');
  }
  if (safety.snapshotAgeDays != null) {
    sources.push(`端末内snapshot · ${age(safety.snapshotAgeDays)}`);
  }
  if (safety.exportAgeDays != null) {
    sources.push(`JSON export · ${age(safety.exportAgeDays)}`);
    durableSources.push('export');
  }

  // A localStorage snapshot disappears with the same site-data wipe as the
  // portfolio. Only a completed vault sync or an exported file is durable.
  const hasRecoveryPoint = durableSources.length > 0;
  const ready = safety.protectionLevel === 'protected'
    && safety.restoreVerified && hasRecoveryPoint;
  const state: RestoreReadinessState = ready ? 'ready'
    : !hasRecoveryPoint ? 'recovery_point_required'
    : !safety.restoreVerified ? 'drill_required' : 'attention';
  const label = ready ? 'RESTORE READY'
    : state === 'recovery_point_required' ? 'NO RECOVERY POINT'
    : state === 'drill_required' ? 'RESTORE NOT VERIFIED' : 'ATTENTION';

  return {
    state,
    label,
    summary: ready
      ? '復元元があり、非破壊read-back drillでschemaと件数の一致を確認済みです。'
      : state === 'recovery_point_required'
        ? '復元に使える暗号化同期・snapshot・JSON exportが確認できません。'
        : state === 'drill_required'
          ? '復元元はありますが、実際に読み戻せることをまだ検証していません。'
          : safety.statusJa,
    sources,
    integrity: safety.restoreVerified ? 'READ-BACK PASS' : 'NOT PROVEN',
    atRisk: ready ? '直近のrecovery point以降の変更' : safety.riskJa || safety.whatCanBeLostJa,
    nextAction: safety.nextStepJa,
  };
}
