// V11.16.0 — Backup Safety / Vault Guard + Recovery Drill (device-local TS port
// of argus_backup_safety.py). 保護状態の判定と復元ドリルは端末内で完結し、
// パスフレーズ・暗号ペイロード・保護状態がサーバーへ送られることはない。

import type { AssetItem } from '../types/assetItem';
import { lastCloudBackupAt } from './vault';
import { buildPortfolioBackup, listSnapshots, previewImport, syncMeta } from './portfolioSync';
import { listDQ } from './decisionQuality';
import { listNotifications } from './notifications';

export type ProtectionLevel = 'protected' | 'partially_protected' | 'unprotected' | 'needs_attention' | 'unknown';
export const LEVEL_JA: Record<ProtectionLevel, string> = {
  protected: '保護済み', partially_protected: '一部保護', unprotected: '未保護',
  needs_attention: '要確認', unknown: '判定保留',
};
export const LEVEL_TONE: Record<ProtectionLevel, string> = {
  protected: 'var(--value-positive)', partially_protected: 'var(--amber, #fbbf24)',
  unprotected: 'var(--value-negative)', needs_attention: 'var(--amber, #fbbf24)',
  unknown: 'var(--text-faint)',
};

export interface BackupSafety {
  protectionLevel: ProtectionLevel; protectionLevelJa: string;
  storageMode: string;
  vaultConfigured: boolean; vaultSyncAgeDays: number | null;
  snapshotAgeDays: number | null; exportAgeDays: number | null;
  restoreVerified: boolean; lastDrillAt: string | null;
  riskFlags: string[];
  statusJa: string; riskJa: string; nextStepJa: string; whatCanBeLostJa: string;
}

const META_KEY = 'argus.backupSafety.meta.v1';
interface Meta { restoreVerified?: boolean; lastDrillAt?: string; lastDrillResultJa?: string; }
function meta(): Meta {
  try { return JSON.parse(localStorage.getItem(META_KEY) || '{}'); } catch { return {}; }
}
function saveMeta(m: Meta): void {
  try { localStorage.setItem(META_KEY, JSON.stringify(m)); } catch { /* quota */ }
}
export function drillMeta(): Meta { return meta(); }

const ageDays = (iso?: string | null): number | null =>
  iso ? Math.floor((Date.now() - Date.parse(iso)) / 86_400_000) : null;

export function assessBackupSafety(assets: AssetItem[]): BackupSafety {
  const hasData = assets.some((a) => (a.quantity ?? 0) > 0) || listDQ().length > 0;
  const vault = typeof window !== 'undefined' && !!localStorage.getItem('argus.vaultPass.v1');
  const syncMs = lastCloudBackupAt();
  const vaultSyncAgeDays = syncMs > 0 ? Math.floor((Date.now() - syncMs) / 86_400_000) : null;
  const sm = syncMeta();
  const snaps = listSnapshots();
  const snapshotAgeDays = snaps.length ? ageDays(snaps[0].createdAt) : null;
  const exportAgeDays = ageDays(sm.lastExportAt);
  const m = meta();
  const verified = !!m.restoreVerified;

  const risks: string[] = [];
  if (!vault) risks.push('vault_not_configured', 'passphrase_not_set');
  if (vault && (vaultSyncAgeDays == null || vaultSyncAgeDays > 2)) risks.push('vault_sync_stale');
  if (exportAgeDays == null || exportAgeDays > 30) risks.push('no_export_backup');
  if (hasData && (snapshotAgeDays == null || snapshotAgeDays > 3)) risks.push('no_snapshot');
  if (!verified) risks.push('restore_not_verified');
  if (hasData && !vault) risks.push('local_only_with_private_data');

  let level: ProtectionLevel; let statusJa: string;
  if (!hasData) {
    level = 'unknown';
    statusJa = '保護対象の個人データはまだ端末にありません(保有数量を入力すると保護状態を判定します)。';
  } else if (vault && vaultSyncAgeDays != null && vaultSyncAgeDays <= 2
    && snapshotAgeDays != null && snapshotAgeDays <= 3
    && ((exportAgeDays != null && exportAgeDays <= 30) || verified)) {
    level = 'protected';
    statusJa = 'バックアップ保護済み：暗号化バックアップが最近同期され、スナップショットも最新です。';
  } else if (vault) {
    level = 'partially_protected';
    const missing = (risks.includes('no_export_backup') && !verified) ? '復元確認またはJSONエクスポート'
      : risks.includes('no_snapshot') ? 'スナップショット' : '同期の更新';
    statusJa = `一部保護：暗号化バックアップは有効ですが、${missing}がまだです。`;
  } else if (exportAgeDays != null && exportAgeDays <= 30) {
    level = 'partially_protected';
    statusJa = '一部保護：JSONエクスポートはありますが、暗号化バックアップ(端末間同期)が未設定です。';
  } else {
    level = 'unprotected';
    statusJa = 'バックアップ未保護：保有データはこの端末内にのみあります。暗号化バックアップを有効化してください。';
  }
  return {
    protectionLevel: level, protectionLevelJa: LEVEL_JA[level],
    storageMode: !hasData ? 'unknown'
      : vault && exportAgeDays != null && exportAgeDays <= 30 ? 'encrypted_vault_plus_export'
      : vault ? 'encrypted_vault' : 'local_only',
    vaultConfigured: vault, vaultSyncAgeDays, snapshotAgeDays, exportAgeDays,
    restoreVerified: verified, lastDrillAt: m.lastDrillAt ?? null,
    riskFlags: risks,
    statusJa,
    riskJa: level === 'unprotected'
      ? '保有・判断記録・通知・学習履歴がこの端末だけにあり、サイトデータ削除・ブラウザリセット・PWA削除・端末紛失で失われます。'
      : !verified && level !== 'unknown'
        ? '復元できることを一度も確認していません。復元ドリル(非破壊)の実行を推奨します。' : '',
    nextStepJa: !vault && hasData ? 'Backupページでパスフレーズを設定(暗号化バックアップ有効化)'
      : !verified && hasData ? '「復元ドリルを実行」で戻せることを確認(非破壊)'
      : risks.includes('no_export_backup') && hasData ? 'バックアップJSONを書き出してiCloud Drive等に保管'
      : '現状維持でOK(週1回のエクスポート保管を推奨)',
    whatCanBeLostJa: 'サイトデータ消去/ブラウザ初期化/PWA削除/プライベートブラウズ/端末変更・紛失で、端末内のデータが消える可能性があります。アプリを閉じるだけでは通常消えません。',
  };
}

/** 復元ドリル(非破壊): 書き出し→スキーマ検証→プレビュー読み戻し→件数照合。
 *  既存データは一切変更しない。成功時のみ restoreVerified=true。 */
export function runRecoveryDrill(assets: AssetItem[], appVersion: string):
  { passed: boolean; resultJa: string } {
  const file = buildPortfolioBackup(assets, appVersion);
  const expected = {
    positions: file.positions.length,
    snapshots: file.snapshots.length,
    decisions: file.decisionAudit.length,
  };
  const preview = previewImport(JSON.stringify(file));
  if (!preview.ok || !preview.file) {
    return { passed: false, resultJa: `復元ドリル失敗：書き出したバックアップが読み戻せません(${preview.errorJa ?? '不明'})。` };
  }
  const previewed = {
    positions: preview.file.positions.length,
    snapshots: preview.file.snapshots.length,
    decisions: preview.file.decisionAudit.length,
  };
  const mismatch = (Object.keys(expected) as (keyof typeof expected)[])
    .filter((k) => expected[k] !== previewed[k]);
  const now = new Date().toISOString();
  if (mismatch.length) {
    saveMeta({ ...meta(), lastDrillAt: now, lastDrillResultJa: `不一致: ${mismatch.join('/')}` });
    return { passed: false, resultJa: `復元ドリル不一致：${mismatch.join('/')}の件数が一致しません。再エクスポート後にもう一度実行してください。` };
  }
  const resultJa = `復元ドリル成功：保有${expected.positions}件/スナップショット${expected.snapshots}件/判断記録${expected.decisions}件を読み戻して照合しました(既存データは変更していません)。`;
  saveMeta({ restoreVerified: true, lastDrillAt: now, lastDrillResultJa: resultJa });
  return { passed: true, resultJa };
}

/** Handoff用のredacted一行(保有数値・パスフレーズ情報なし)。 */
export function backupSafetyLineJa(assets: AssetItem[]): string {
  const b = assessBackupSafety(assets);
  return `バックアップ: ${b.protectionLevelJa} / スナップショット${b.snapshotAgeDays != null ? `${b.snapshotAgeDays}日前` : 'なし'} / 復元確認${b.restoreVerified ? '済' : '未'}`;
}
